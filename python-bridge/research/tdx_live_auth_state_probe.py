"""Read-only live probe for selected TDX auth state.

This probe does not inject code, suspend threads, or load TDX DLLs into the
target process. It only uses:

- tasklist / netstat for process and TCP discovery
- OpenProcess + ReadProcessMemory for a few known static addresses
- masked output for sensitive runtime strings by default

The current address set is intentionally narrow and focused on objects already
anchored by static analysis:

- 0x011D4FEC: global CString used by the SSO/JSSO worker and the
  TC_SetL2UserInfo callsite; current live sampling shows this is the
  runtime L2ZH string, not the datacache TDXID field
- 0x011D41E0 / 0x011D4340: global path CString objects used near
  TdxDeep_StartInit
- 0x011CE734 / 0x011CE738 / 0x011CE7F8 / 0x00E7F07E / 0x00E7F21D:
  globals observed near the SSO/JSSO worker

The probe also reports a few persisted fields from T0002/user.ini with
masking so they can be correlated with the live process state without storing
full secrets in the repo.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import re
import subprocess
import time
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_TDX_ROOT = Path(r"D:\APP_SOFT\TDX")
DEFAULT_PROCESS_NAME = "tdxw.exe"


OBJECT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "syssource_inline_buffer",
        "kind": "inline_ascii",
        "address": 0x011BED6C,
        "size": 256,
        "sensitive": False,
        "notes": [
            "2026-04-28 live read confirms this is an inline buffer, not a CString*.",
            "Current live value aligns with connect.cfg QSID and tpbus InputQSID hypotheses.",
        ],
    },
    {
        "name": "l2right_inline_buffer",
        "kind": "inline_ascii",
        "address": 0x011BEE80,
        "size": 256,
        "sensitive": False,
        "notes": [
            "2026-04-28 live read confirms this is an inline buffer, not a CString*.",
            "Current live value shape is a short L2 rights marker, not a path or GUID.",
        ],
    },
    {
        "name": "l2zh_string_object",
        "kind": "cstring",
        "address": 0x011D4FEC,
        "sensitive": True,
        "notes": [
            "Used by the SSO/JSSO JSON worker and the TC_SetL2UserInfo callsite.",
            "2026-04-27 live read confirms the value shape matches runtime L2ZH, not datacache TDXID.",
        ],
    },
    {
        "name": "t0002_dir_string_object",
        "kind": "cstring",
        "address": 0x011D41E0,
        "sensitive": False,
        "notes": ["Observed near the TdxDeep_StartInit callsite."],
    },
    {
        "name": "tdx_root_string_object",
        "kind": "cstring",
        "address": 0x011D4340,
        "sensitive": False,
        "notes": ["Observed near the TdxDeep_StartInit callsite."],
    },
    {
        "name": "sso_state_ptr_a",
        "kind": "pointer_blob",
        "address": 0x011CE734,
        "sensitive": True,
        "notes": ["Referenced by the SSO/JSSO worker before the SSOMode 13/15 JSON format branch."],
    },
    {
        "name": "sso_state_ptr_b",
        "kind": "pointer_blob",
        "address": 0x011CE738,
        "sensitive": True,
        "notes": ["Referenced by the SSO/JSSO worker before the SSOMode 13/15 JSON format branch."],
    },
    {
        "name": "sso_state_flag",
        "kind": "u32",
        "address": 0x011CE7F8,
        "sensitive": False,
    },
    {
        "name": "loginret_seq_mirror_a",
        "kind": "u32",
        "address": 0x011CE73C,
        "sensitive": False,
        "notes": [
            "Observed in the 2026-04-28 TP_Check_GTJAL2 direct-caller context window.",
            "This dword is written immediately before Local.GetLoginRetInfo / TdxW_GetLoginRetInfo logging.",
        ],
    },
    {
        "name": "loginret_seq_mirror_b",
        "kind": "u32",
        "address": 0x011C8DF4,
        "sensitive": False,
        "notes": [
            "Observed in the 2026-04-28 TP_Check_GTJAL2 direct-caller context window.",
            "This dword mirrors the same incremented value as loginret_seq_mirror_a in the current static view.",
        ],
    },
    {
        "name": "tpcheck_mode_gate",
        "kind": "u32",
        "address": 0x00E7F17C,
        "sensitive": False,
        "notes": [
            "Compared against 7 in the current TP_Check_GTJAL2 direct caller.",
            "Useful to watch during manual login/refresh because it gates the Local.GetLoginRetInfo branch.",
        ],
    },
    {
        "name": "loginret_zero_gate",
        "kind": "u32",
        "address": 0x00E7F259,
        "sensitive": False,
        "notes": [
            "Compared against 0 in the current TP_Check_GTJAL2 direct caller.",
            "Useful to watch during manual login/refresh because it gates the Local.GetLoginRetInfo branch.",
        ],
    },
    {
        "name": "sso_switch_gate",
        "kind": "u32",
        "address": 0x00E7F07E,
        "sensitive": False,
    },
    {
        "name": "req_lscjmx_gate_bytes",
        "kind": "bytes",
        "address": 0x00E7F21D,
        "size": 16,
        "sensitive": False,
    },
)


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE
ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    wintypes.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
ReadProcessMemory.restype = wintypes.BOOL
CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL


@dataclass
class ProcessMemoryReader:
    pid: int

    def __post_init__(self) -> None:
        access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION
        self.handle = OpenProcess(access, False, self.pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), f"OpenProcess failed for pid={self.pid}")

    def close(self) -> None:
        handle = getattr(self, "handle", None)
        if handle:
            CloseHandle(handle)
            self.handle = None

    def __enter__(self) -> "ProcessMemoryReader":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def read(self, address: int, size: int) -> bytes | None:
        buffer = (ctypes.c_ubyte * size)()
        read_count = ctypes.c_size_t()
        ok = ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            buffer,
            size,
            ctypes.byref(read_count),
        )
        if not ok:
            return None
        return bytes(buffer[: read_count.value])

    def read_u32(self, address: int) -> int | None:
        data = self.read(address, 4)
        if not data or len(data) < 4:
            return None
        return int.from_bytes(data, "little")

    def read_c_string(self, address: int, limit: int = 512, encoding: str = "gbk") -> str | None:
        data = self.read(address, limit)
        if not data:
            return None
        end = data.find(b"\x00")
        if end < 0:
            end = len(data)
        if end == 0:
            return ""
        return data[:end].decode(encoding, errors="replace")


def is_path_like(value: str) -> bool:
    return value.startswith("\\\\") or bool(re.match(r"^[A-Za-z]:\\", value))


def mask_secret(value: str) -> str:
    if value == "":
        return ""
    if len(value) <= 8:
        prefix = value[:1]
        suffix = value[-1:]
    else:
        prefix = value[:4]
        suffix = value[-4:]
    digest = hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:10]
    return f"{prefix}...{suffix} (len={len(value)}, sha1={digest})"


def extract_ascii_fragments(data: bytes, min_len: int = 4) -> list[str]:
    fragments = re.findall(rb"[ -~]{%d,}" % min_len, data)
    values: list[str] = []
    for raw in fragments:
        try:
            values.append(raw.decode("ascii"))
        except UnicodeDecodeError:
            continue
    return values


def mask_if_needed(value: str, sensitive: bool) -> str:
    if not sensitive or is_path_like(value):
        return value
    return mask_secret(value)


def read_cstring_object(
    reader: ProcessMemoryReader,
    address: int,
    sensitive: bool,
) -> dict[str, Any]:
    pointer = reader.read_u32(address)
    entry: dict[str, Any] = {
        "kind": "cstring",
        "staticVa": f"0x{address:08X}",
        "stringPointer": f"0x{pointer:08X}" if pointer else "",
    }
    if not pointer:
        entry["present"] = False
        return entry

    value = reader.read_c_string(pointer, limit=512) or ""
    meta = reader.read(pointer - 12, 12)
    entry["present"] = True
    entry["value"] = mask_if_needed(value, sensitive)
    if meta and len(meta) >= 12:
        entry["length"] = int.from_bytes(meta[0:4], "little")
        entry["capacity"] = int.from_bytes(meta[4:8], "little")
        entry["refCount"] = int.from_bytes(meta[8:12], "little")
    return entry


def read_pointer_blob(
    reader: ProcessMemoryReader,
    address: int,
    sensitive: bool,
) -> dict[str, Any]:
    pointer = reader.read_u32(address)
    entry: dict[str, Any] = {
        "kind": "pointer_blob",
        "staticVa": f"0x{address:08X}",
        "targetPointer": f"0x{pointer:08X}" if pointer else "",
    }
    if not pointer:
        entry["present"] = False
        return entry

    data = reader.read(pointer, 128)
    entry["present"] = data is not None
    if data:
        fragments = extract_ascii_fragments(data)
        if fragments:
            entry["printableFragments"] = [mask_if_needed(item, sensitive) for item in fragments[:8]]
        entry["blobSha1"] = hashlib.sha1(data).hexdigest()[:12]
    return entry


def read_inline_ascii(
    reader: ProcessMemoryReader,
    address: int,
    size: int,
    sensitive: bool,
) -> dict[str, Any]:
    data = reader.read(address, size)
    entry: dict[str, Any] = {
        "kind": "inline_ascii",
        "staticVa": f"0x{address:08X}",
        "size": size,
    }
    if not data:
        entry["present"] = False
        return entry

    end = data.find(b"\x00")
    if end < 0:
        end = len(data)
    value = data[:end].decode("gbk", errors="replace").strip()
    entry["present"] = True
    entry["value"] = mask_if_needed(value, sensitive)
    entry["rawLength"] = end
    entry["hexPreview"] = data[: min(len(data), 32)].hex(" ")
    return entry


def read_u32_value(reader: ProcessMemoryReader, address: int) -> dict[str, Any]:
    value = reader.read_u32(address)
    return {
        "kind": "u32",
        "staticVa": f"0x{address:08X}",
        "value": value,
        "valueHex": f"0x{value:08X}" if value is not None else "",
    }


def read_bytes_value(reader: ProcessMemoryReader, address: int, size: int) -> dict[str, Any]:
    data = reader.read(address, size)
    return {
        "kind": "bytes",
        "staticVa": f"0x{address:08X}",
        "size": size,
        "hex": data.hex(" ") if data else "",
    }


def tasklist_rows(process_name: str) -> list[list[str]]:
    result = subprocess.run(
        ["tasklist", "/fo", "csv", "/nh", "/fi", f"imagename eq {process_name}"],
        check=False,
        capture_output=True,
        text=True,
        encoding="gbk",
        errors="ignore",
    )
    rows: list[list[str]] = []
    for row in csv.reader(result.stdout.splitlines()):
        if not row:
            continue
        if len(row) < 2 or not row[0].lower().endswith(".exe"):
            continue
        rows.append(row)
    return rows


def find_pid_by_name(process_name: str) -> int | None:
    rows = tasklist_rows(process_name)
    if not rows:
        return None
    try:
        return int(rows[0][1])
    except ValueError:
        return None


def split_endpoint(endpoint: str) -> tuple[str, int]:
    if endpoint.startswith("[") and "]:" in endpoint:
        host, port = endpoint.rsplit("]:", 1)
        return host + "]", int(port)
    host, port = endpoint.rsplit(":", 1)
    return host, int(port)


def collect_established_tcp(pid: int) -> list[dict[str, Any]]:
    result = subprocess.run(
        ["netstat", "-ano", "-p", "tcp"],
        check=False,
        capture_output=True,
        text=True,
        encoding="gbk",
        errors="ignore",
    )
    entries: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        text = line.strip()
        if not text.startswith("TCP"):
            continue
        parts = re.split(r"\s+", text)
        if len(parts) < 5:
            continue
        proto, local, remote, state, pid_text = parts[:5]
        if proto != "TCP":
            continue
        try:
            owning_pid = int(pid_text)
        except ValueError:
            continue
        if owning_pid != pid or state.upper() != "ESTABLISHED":
            continue
        try:
            local_host, local_port = split_endpoint(local)
            remote_host, remote_port = split_endpoint(remote)
        except ValueError:
            continue
        entries.append(
            {
                "localAddress": local_host,
                "localPort": local_port,
                "remoteAddress": remote_host,
                "remotePort": remote_port,
                "state": state,
            }
        )
    entries.sort(key=lambda item: (item["remotePort"], item["remoteAddress"]))
    return entries


def extract_persisted_values(tdx_root: Path) -> dict[str, Any]:
    values: dict[str, Any] = {
        "files": [],
        "keys": {},
    }

    def read_kv_file(
        relative_path: str,
        encoding: str,
        keys: tuple[str, ...],
        sensitive_keys: set[str] | None = None,
    ) -> None:
        sensitive_keys = sensitive_keys or set()
        path = tdx_root / relative_path
        entry = {
            "path": str(path),
            "exists": path.exists(),
            "keys": {},
        }
        values["files"].append(entry)
        if not path.exists():
            return

        text = path.read_text(encoding=encoding, errors="replace")
        for key in keys:
            match = re.search(rf"^{re.escape(key)}=(.*)$", text, re.MULTILINE)
            if not match:
                continue
            raw_value = match.group(1).strip()
            masked = mask_secret(raw_value) if key in sensitive_keys else raw_value
            entry["keys"][key] = masked
            values["keys"][key] = masked

    read_kv_file(
        r"T0002\user.ini",
        "gbk",
        ("OID", "TPSession", "RegUID", "TDXToken", "JYMainQSID", "LastLoginType", "Embed_YybID"),
        {"TPSession", "RegUID", "TDXToken"},
    )
    read_kv_file(
        r"T0002\usercomm.ini",
        "gbk",
        ("UserPUID", "SSOLoginYMD", "SSOLoginSeconds", "SAVEZH", "UseSpecTPHost"),
        {"UserPUID"},
    )
    read_kv_file(r"T0002\hostip.ini", "gbk", ("HostIP",))
    read_kv_file(
        "connect.cfg",
        "gbk",
        ("QSID", "WTPreNAME", "JyLogin_Style", "JyLogin", "SpecIPLogin"),
    )

    data_cache = tdx_root / "T0002" / "datacache.json"
    data_cache_entry = {
        "path": str(data_cache),
        "exists": data_cache.exists(),
        "keys": {},
    }
    values["files"].append(data_cache_entry)
    if data_cache.exists():
        try:
            document = json.loads(data_cache.read_text(encoding="utf-8", errors="replace"))
            login_extend = document.get("LoninExtendSvc")
            if isinstance(login_extend, dict):
                for key in ("TDXID", "OID"):
                    raw_value = str(login_extend.get(key, "") or "").strip()
                    if not raw_value:
                        continue
                    masked = mask_secret(raw_value) if key == "TDXID" else raw_value
                    data_cache_entry["keys"][key] = masked
                    values["keys"][key] = masked
        except Exception as exc:
            data_cache_entry["error"] = str(exc)

    if "QSID" in values["keys"]:
        values["keys"]["ConnectQSID"] = values["keys"]["QSID"]
    return values


def collect_live_values(reader: ProcessMemoryReader) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for spec in OBJECT_SPECS:
        kind = spec["kind"]
        address = int(spec["address"])
        sensitive = bool(spec.get("sensitive", False))
        if kind == "cstring":
            entry = read_cstring_object(reader, address, sensitive)
        elif kind == "inline_ascii":
            entry = read_inline_ascii(reader, address, int(spec.get("size", 256)), sensitive)
        elif kind == "pointer_blob":
            entry = read_pointer_blob(reader, address, sensitive)
        elif kind == "u32":
            entry = read_u32_value(reader, address)
        elif kind == "bytes":
            entry = read_bytes_value(reader, address, int(spec.get("size", 16)))
        else:
            entry = {"kind": kind, "staticVa": f"0x{address:08X}", "error": "unsupported_kind"}
        entry["name"] = spec["name"]
        if spec.get("notes"):
            entry["notes"] = spec["notes"]
        results.append(entry)
    return results


def summarize_live_entry(entry: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"kind": entry.get("kind", "")}
    for key in (
        "present",
        "value",
        "valueHex",
        "hex",
        "blobSha1",
        "targetPointer",
        "stringPointer",
        "rawLength",
        "length",
        "capacity",
        "refCount",
        "hexPreview",
    ):
        if key in entry:
            summary[key] = entry[key]
    if "printableFragments" in entry:
        summary["printableFragments"] = entry["printableFragments"]
    return summary


def sample_signature(sample: dict[str, Any]) -> dict[str, Any]:
    return {
        "establishedTcp": sample["establishedTcp"],
        "liveValues": {
            entry["name"]: summarize_live_entry(entry)
            for entry in sample["liveValues"]
        },
    }


def diff_signatures(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    if previous is None:
        return []

    changed: list[str] = []
    if previous.get("establishedTcp") != current.get("establishedTcp"):
        changed.append("establishedTcp")

    previous_live = previous.get("liveValues", {})
    current_live = current.get("liveValues", {})
    for name in sorted(set(previous_live) | set(current_live)):
        if previous_live.get(name) != current_live.get(name):
            changed.append(f"liveValues.{name}")
    return changed


def take_sample(pid: int, process_name: str, tdx_root: Path, index: int) -> dict[str, Any]:
    with ProcessMemoryReader(pid) as reader:
        live_values = collect_live_values(reader)

    return {
        "sampleIndex": index,
        "sampledAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "establishedTcp": collect_established_tcp(pid),
        "liveValues": live_values,
    }


def build_report(
    pid: int,
    process_name: str,
    tdx_root: Path,
    sample_count: int,
    interval_ms: int,
    diff_only: bool,
) -> dict[str, Any]:
    persisted_values = extract_persisted_values(tdx_root)
    samples: list[dict[str, Any]] = []
    previous_signature: dict[str, Any] | None = None
    all_changed_fields: set[str] = set()

    for index in range(sample_count):
        sample = take_sample(pid, process_name, tdx_root, index)
        signature = sample_signature(sample)
        changed_fields = diff_signatures(previous_signature, signature)
        sample["changedFields"] = changed_fields
        previous_signature = signature
        all_changed_fields.update(changed_fields)
        if not diff_only or index == 0 or changed_fields:
            samples.append(sample)
        if index + 1 < sample_count and interval_ms > 0:
            time.sleep(interval_ms / 1000.0)

    latest_sample = samples[-1] if samples else take_sample(pid, process_name, tdx_root, sample_count)
    return {
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "ok": True,
        "pid": pid,
        "processName": process_name,
        "tdxRoot": str(tdx_root),
        "sampleCount": sample_count,
        "intervalMs": interval_ms,
        "diffOnly": diff_only,
        "changedFieldCount": len(all_changed_fields),
        "changedFields": sorted(all_changed_fields),
        "establishedTcp": latest_sample["establishedTcp"],
        "liveValues": latest_sample["liveValues"],
        "persistedValues": persisted_values,
        "samples": samples,
        "notes": [
            "Sensitive live strings are masked by default before JSON is emitted.",
            "OpenProcess + ReadProcessMemory only; no DLL load or code injection into tdxw.exe.",
            "Current address set is anchored to the 2026-04-26/2026-04-28 static analysis around sub_00510740, sub_007012B0, TP_Check_GTJAL2, and the TC_SetL2UserInfo callsite.",
            "Use sampleCount > 1 while manually triggering login/refresh in tdxw.exe to see which live fields actually move.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only live probe for selected TDX auth state")
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--process-name", default=DEFAULT_PROCESS_NAME)
    parser.add_argument("--tdx-root", default=str(DEFAULT_TDX_ROOT))
    parser.add_argument("--sample-count", type=int, default=1)
    parser.add_argument("--interval-ms", type=int, default=1000)
    parser.add_argument("--diff-only", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    pid = args.pid or find_pid_by_name(args.process_name)
    if not pid:
        payload = {
            "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
            "ok": False,
            "error": f"process not found: {args.process_name}",
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 2

    report = build_report(
        pid,
        args.process_name,
        Path(args.tdx_root),
        max(1, args.sample_count),
        max(0, args.interval_ms),
        args.diff_only,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "pid": pid, "liveValueCount": len(report["liveValues"])}, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
