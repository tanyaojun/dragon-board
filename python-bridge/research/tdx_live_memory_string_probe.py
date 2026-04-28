"""Read-only string scan for live TDX auth/L2 state.

This does not inject, suspend, or load DLLs into tdxw.exe. It enumerates
readable committed memory regions with VirtualQueryEx, scans for a narrow set
of L2/auth keywords, and emits masked context snippets.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import re
import subprocess
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROCESS_NAME = "tdxw.exe"
DEFAULT_KEYWORDS = (
    "TdxWL2",
    "L2ZH",
    "L2Right",
    "RightInfo",
    "Local.GetLoginRetInfo",
    "TdxW_GetLoginRetInfo",
    "TP_Check_GTJAL2",
    "TPL2_Check",
    "tc.JSSO:applysso",
    "ReqLscjmxTdxSSO",
    "SSOMode",
    "AuthInfo",
    "InputQSID",
    "TDXToken",
    "PTOKEN",
    "PTYPE",
)


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
READABLE_PROTECTS = {
    0x02,  # PAGE_READONLY
    0x04,  # PAGE_READWRITE
    0x08,  # PAGE_WRITECOPY
    0x20,  # PAGE_EXECUTE_READ
    0x40,  # PAGE_EXECUTE_READWRITE
    0x80,  # PAGE_EXECUTE_WRITECOPY
}


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", wintypes.LPVOID),
        ("AllocationBase", wintypes.LPVOID),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


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
VirtualQueryEx = kernel32.VirtualQueryEx
VirtualQueryEx.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
    ctypes.c_size_t,
]
VirtualQueryEx.restype = ctypes.c_size_t
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

    def iter_regions(self, max_address: int = 0x7FFF0000) -> list[dict[str, int]]:
        regions: list[dict[str, int]] = []
        address = 0
        mbi = MEMORY_BASIC_INFORMATION()
        mbi_size = ctypes.sizeof(mbi)
        while address < max_address:
            result = VirtualQueryEx(self.handle, ctypes.c_void_p(address), ctypes.byref(mbi), mbi_size)
            if not result:
                address += 0x10000
                continue
            base = int(ctypes.cast(mbi.BaseAddress, ctypes.c_void_p).value or 0)
            size = int(mbi.RegionSize)
            protect = int(mbi.Protect)
            if (
                size > 0
                and int(mbi.State) == MEM_COMMIT
                and not (protect & PAGE_GUARD)
                and not (protect & PAGE_NOACCESS)
                and (protect & 0xFF) in READABLE_PROTECTS
            ):
                regions.append(
                    {
                        "base": base,
                        "size": size,
                        "protect": protect,
                        "type": int(mbi.Type),
                    }
                )
            address = max(address + 0x1000, base + max(size, 0x1000))
        return regions

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
        if not ok or read_count.value <= 0:
            return None
        return bytes(buffer[: read_count.value])


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
        if row and len(row) >= 2 and row[0].lower().endswith(".exe"):
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


def mask_secret(value: str) -> str:
    if value == "":
        return ""
    digest = hashlib.sha1(value.encode("utf-8", errors="replace")).hexdigest()[:10]
    if len(value) <= 12:
        return f"{value[:2]}...{value[-2:]} (len={len(value)}, sha1={digest})"
    return f"{value[:6]}...{value[-6:]} (len={len(value)}, sha1={digest})"


SECRET_PATTERNS = (
    re.compile(r"([A-Za-z0-9+/=]{24,})"),
    re.compile(r"(tdxP[A-Za-z0-9]+)"),
    re.compile(r"(R\d{6,}[A-Za-z0-9]+)"),
    re.compile(r"([0-9a-f]{16,}_[0-9]{8,})", re.IGNORECASE),
)


def sanitize_text(text: str, reveal: bool) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"\s+", " ", text).strip()
    if reveal:
        return text[:500]
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: mask_secret(match.group(1)), text)
    return text[:500]


def decode_context(data: bytes, encoding: str) -> str:
    try:
        return data.decode(encoding, errors="replace")
    except LookupError:
        return data.decode("latin1", errors="replace")


def find_all(data: bytes, needle: bytes) -> list[int]:
    results: list[int] = []
    start = 0
    while True:
        index = data.find(needle, start)
        if index < 0:
            return results
        results.append(index)
        start = index + 1


def build_needles(keywords: tuple[str, ...]) -> list[dict[str, Any]]:
    needles: list[dict[str, Any]] = []
    for keyword in keywords:
        needles.append({"keyword": keyword, "encoding": "ascii", "needle": keyword.encode("ascii", errors="ignore")})
        needles.append({"keyword": keyword, "encoding": "gbk", "needle": keyword.encode("gbk", errors="ignore")})
        needles.append({"keyword": keyword, "encoding": "utf-16le", "needle": keyword.encode("utf-16le", errors="ignore")})
    unique: dict[tuple[str, str, bytes], dict[str, Any]] = {}
    for item in needles:
        if item["needle"]:
            unique[(item["keyword"], item["encoding"], item["needle"])] = item
    return list(unique.values())


def scan_region(
    reader: ProcessMemoryReader,
    region: dict[str, int],
    needles: list[dict[str, Any]],
    context_bytes: int,
    limit_per_keyword: int,
    reveal: bool,
    hit_counts: dict[str, int],
) -> list[dict[str, Any]]:
    data = reader.read(region["base"], region["size"])
    if not data:
        return []

    hits: list[dict[str, Any]] = []
    for item in needles:
        keyword = item["keyword"]
        if hit_counts.get(keyword, 0) >= limit_per_keyword:
            continue
        for index in find_all(data, item["needle"]):
            if hit_counts.get(keyword, 0) >= limit_per_keyword:
                break
            start = max(0, index - context_bytes)
            end = min(len(data), index + len(item["needle"]) + context_bytes)
            context = data[start:end]
            decoded = decode_context(context, "utf-16le" if item["encoding"] == "utf-16le" else "gbk")
            hit = {
                "keyword": keyword,
                "encoding": item["encoding"],
                "address": f"0x{region['base'] + index:08X}",
                "regionBase": f"0x{region['base']:08X}",
                "regionSize": region["size"],
                "context": sanitize_text(decoded, reveal),
            }
            hits.append(hit)
            hit_counts[keyword] = hit_counts.get(keyword, 0) + 1
    return hits


def build_report(
    pid: int,
    process_name: str,
    keywords: tuple[str, ...],
    max_mb: int,
    context_bytes: int,
    limit_per_keyword: int,
    reveal: bool,
) -> dict[str, Any]:
    with ProcessMemoryReader(pid) as reader:
        regions = reader.iter_regions()
        scanned_regions = 0
        scanned_bytes = 0
        hit_counts: dict[str, int] = {}
        hits: list[dict[str, Any]] = []
        needles = build_needles(keywords)
        max_bytes = max_mb * 1024 * 1024
        for region in regions:
            if scanned_bytes >= max_bytes:
                break
            if region["size"] <= 0:
                continue
            if region["size"] > 64 * 1024 * 1024:
                continue
            next_scanned = scanned_bytes + region["size"]
            if next_scanned > max_bytes:
                continue
            scanned_regions += 1
            scanned_bytes = next_scanned
            hits.extend(
                scan_region(
                    reader,
                    region,
                    needles,
                    context_bytes,
                    limit_per_keyword,
                    reveal,
                    hit_counts,
                )
            )

    return {
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
        "ok": True,
        "pid": pid,
        "processName": process_name,
        "keywordCount": len(keywords),
        "scannedRegions": scanned_regions,
        "scannedBytes": scanned_bytes,
        "scannedMB": round(scanned_bytes / 1024 / 1024, 2),
        "hitCounts": {key: hit_counts.get(key, 0) for key in keywords},
        "hits": hits,
        "notes": [
            "Read-only VirtualQueryEx + ReadProcessMemory scan.",
            "Sensitive-looking tokens and ids are masked unless --reveal is explicitly used.",
            "A hit only proves the string is resident in the process; it does not prove the helper can call that branch.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only live TDX memory string scanner")
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--process-name", default=DEFAULT_PROCESS_NAME)
    parser.add_argument("--keywords", default="")
    parser.add_argument("--max-mb", type=int, default=512)
    parser.add_argument("--context-bytes", type=int, default=160)
    parser.add_argument("--limit-per-keyword", type=int, default=20)
    parser.add_argument("--reveal", action="store_true")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    pid = args.pid or find_pid_by_name(args.process_name)
    if not pid:
        payload = {
            "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(),
            "ok": False,
            "error": f"process not found: {args.process_name}",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    keywords = tuple(item.strip() for item in args.keywords.split(",") if item.strip()) or DEFAULT_KEYWORDS
    report = build_report(
        pid,
        args.process_name,
        keywords,
        max(1, args.max_mb),
        max(16, args.context_bytes),
        max(1, args.limit_per_keyword),
        args.reveal,
    )
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "pid": pid, "hits": len(report["hits"])}, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
