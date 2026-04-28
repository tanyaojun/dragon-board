"""Isolated TC L2 entry probe.

Default mode is static-only: it parses PE metadata, export entries, function
heads, likely stack arguments, and direct call targets. It does not call into
TDX DLLs or use credentials.

The TDX client modules observed on this machine are 32-bit. Loading them from a
64-bit Python process is not possible, so dynamic loading is intentionally gated
behind --load-only and a bitness check.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import struct
import sys
from pathlib import Path
from typing import Any

import pefile


DEFAULT_TDX_ROOT = Path(r"D:\APP_SOFT\TDX")
DEFAULT_FUNCTIONS = (
    "TC_Init_Environ",
    "TC_Login",
    "TC_Login2",
    "TC_GetLoginRet",
    "TC_GetRightInfo",
    "TC_GetL2Info",
    "TC_SetL2UserInfo",
    "TC_Uninit",
)

MACHINE_NAMES = {
    0x014C: "x86",
    0x8664: "x64",
}


def resolve_tc_path(tdx_root: Path, explicit: str = "") -> Path:
    if explicit:
        return Path(explicit)
    candidates = [
        tdx_root / "tc.dll",
        tdx_root / "NewTc" / "tc.dll",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def read_export_map(pe: pefile.PE) -> dict[str, dict[str, Any]]:
    exports: dict[str, dict[str, Any]] = {}
    if not hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        return exports
    for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if not symbol.name:
            continue
        name = symbol.name.decode("ascii", errors="replace")
        exports[name] = {
            "ordinal": int(symbol.ordinal),
            "rva": int(symbol.address),
        }
    return exports


def signed_i32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<i", data, offset)[0]


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def collect_arg_refs(data: bytes) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    patterns = {
        b"\x8b\x45": "mov eax,[ebp+N]",
        b"\x8b\x4d": "mov ecx,[ebp+N]",
        b"\x8b\x55": "mov edx,[ebp+N]",
        b"\x8d\x45": "lea eax,[ebp+N]",
        b"\x8d\x4d": "lea ecx,[ebp+N]",
        b"\x8d\x55": "lea edx,[ebp+N]",
        b"\x83\x7d": "cmp dword [ebp+N],imm8",
    }
    valid = {8, 12, 16, 20, 24, 28, 32, 36, 40}
    for index in range(0, max(0, len(data) - 3)):
        op = data[index : index + 2]
        if op not in patterns:
            continue
        displacement = data[index + 2]
        if displacement not in valid:
            continue
        refs.append(
            {
                "offset": index,
                "argOffset": displacement,
                "argIndex": (displacement - 4) // 4,
                "pattern": patterns[op],
                "bytes": data[index : index + 3].hex(" "),
            }
        )
    return refs


def collect_returns(data: bytes) -> list[dict[str, Any]]:
    returns: list[dict[str, Any]] = []
    for index, byte in enumerate(data):
        if byte == 0xC3:
            returns.append({"offset": index, "kind": "ret"})
        elif byte == 0xC2 and index + 2 < len(data):
            returns.append({"offset": index, "kind": "ret_imm", "imm": u16(data, index + 1)})
    return returns


def collect_calls(pe: pefile.PE, data: bytes, base_rva: int) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    image_base = pe.OPTIONAL_HEADER.ImageBase
    for index in range(0, max(0, len(data) - 5)):
        if data[index] == 0xE8:
            rel = signed_i32(data, index + 1)
            next_rva = base_rva + index + 5
            target_rva = (next_rva + rel) & 0xFFFFFFFF
            calls.append(
                {
                    "offset": index,
                    "kind": "call_rel32",
                    "targetRva": target_rva,
                    "targetVa": image_base + target_rva,
                }
            )
        elif data[index : index + 2] == b"\xff\x15" and index + 6 <= len(data):
            pointer_va = struct.unpack_from("<I", data, index + 2)[0]
            calls.append(
                {
                    "offset": index,
                    "kind": "call_mem32",
                    "pointerVa": pointer_va,
                }
            )
    return calls


def estimate_function_size(rva: int, exports: dict[str, dict[str, Any]], window: int) -> int:
    next_rvas = sorted(item["rva"] for item in exports.values() if item["rva"] > rva)
    if not next_rvas:
        return window
    return max(1, min(window, next_rvas[0] - rva))


def analyze_function(
    pe: pefile.PE,
    file_data: bytes,
    name: str,
    export: dict[str, Any],
    exports: dict[str, dict[str, Any]],
    window: int,
) -> dict[str, Any]:
    rva = export["rva"]
    file_offset = pe.get_offset_from_rva(rva)
    function_size = estimate_function_size(rva, exports, window)
    body = file_data[file_offset : file_offset + function_size]
    arg_refs = collect_arg_refs(body)
    arg_offsets = sorted({item["argOffset"] for item in arg_refs})
    returns = collect_returns(body)
    calls = collect_calls(pe, body, rva)
    return {
        "name": name,
        "ordinal": export["ordinal"],
        "rva": rva,
        "fileOffset": file_offset,
        "analyzedSize": function_size,
        "head": body[:64].hex(" "),
        "argOffsets": arg_offsets,
        "argCountGuess": max(((offset - 4) // 4 for offset in arg_offsets), default=0),
        "argRefs": arg_refs[:80],
        "returns": returns[:40],
        "calls": calls[:60],
    }


def static_probe(tdx_root: Path, functions: list[str], window: int, tc_path: Path) -> dict[str, Any]:
    deep_path = tdx_root / "TDXDeep.dll"
    tpbus_path = tdx_root / "tpbus.dll"
    tdxw_path = tdx_root / "tdxw.exe"
    if not tdxw_path.exists():
        tdxw_path = tdx_root / "TdxW.exe"
    paths = [tc_path, deep_path, tpbus_path, tdxw_path]

    modules = []
    for path in paths:
        if not path.exists():
            modules.append(
                {
                    "path": str(path),
                    "exists": False,
                    "exportCount": 0,
                    "exports": {},
                }
            )
            continue
        pe = pefile.PE(str(path), fast_load=False)
        exports = read_export_map(pe)
        machine = pe.FILE_HEADER.Machine
        modules.append(
            {
                "path": str(path),
                "exists": True,
                "machine": hex(machine),
                "machineName": MACHINE_NAMES.get(machine, "unknown"),
                "imageBase": pe.OPTIONAL_HEADER.ImageBase,
                "exportCount": len(exports),
                "exports": exports,
            }
        )

    function_reports = []
    if tc_path.exists():
        pe = pefile.PE(str(tc_path), fast_load=False)
        file_data = tc_path.read_bytes()
        exports = read_export_map(pe)
        for name in functions:
            export = exports.get(name)
            if not export:
                function_reports.append({"name": name, "missing": True})
                continue
            function_reports.append(analyze_function(pe, file_data, name, export, exports, window))

    return {
        "mode": "static",
        "pythonBits": struct.calcsize("P") * 8,
        "pythonArchitecture": platform.architecture()[0],
        "tdxRoot": str(tdx_root),
        "modules": modules,
        "tcEntryFunctions": function_reports,
        "notes": [
            "Static-only probe: no DLL calls were made.",
            "argCountGuess is a heuristic from [ebp+N] references, not a confirmed signature.",
            "A 64-bit Python process cannot load the observed 32-bit TDX DLLs.",
        ],
    }


def load_only(tdx_root: Path, tc_path: Path) -> dict[str, Any]:
    if not tc_path.exists():
        return {
            "mode": "load_only",
            "ok": False,
            "reason": "missing_tc_dll",
            "path": str(tc_path),
        }
    pe = pefile.PE(str(tc_path), fast_load=True)
    dll_bits = 32 if pe.FILE_HEADER.Machine == 0x014C else 64 if pe.FILE_HEADER.Machine == 0x8664 else 0
    python_bits = struct.calcsize("P") * 8
    if dll_bits and dll_bits != python_bits:
        return {
            "mode": "load_only",
            "ok": False,
            "reason": "bitness_mismatch",
            "pythonBits": python_bits,
            "dllBits": dll_bits,
            "path": str(tc_path),
        }

    handle = ctypes.WinDLL(str(tc_path))
    resolved = {}
    for name in DEFAULT_FUNCTIONS:
        try:
            resolved[name] = bool(getattr(handle, name))
        except AttributeError:
            resolved[name] = False
    return {
        "mode": "load_only",
        "ok": True,
        "path": str(tc_path),
        "resolved": resolved,
        "note": "DLL loaded and exports resolved only; no entry function was called.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Isolated tc.dll L2 entry probe")
    parser.add_argument("--tdx-root", default=str(DEFAULT_TDX_ROOT))
    parser.add_argument("--tc-path", default="", help="Optional explicit tc.dll path.")
    parser.add_argument("--functions", default=",".join(DEFAULT_FUNCTIONS))
    parser.add_argument("--window", type=int, default=768)
    parser.add_argument("--output", default="")
    parser.add_argument("--load-only", action="store_true", help="Load tc.dll and resolve exports, but do not call them.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    tdx_root = Path(args.tdx_root)
    tc_path = resolve_tc_path(tdx_root, args.tc_path)
    functions = [item.strip() for item in args.functions.split(",") if item.strip()]
    report = load_only(tdx_root, tc_path) if args.load_only else static_probe(tdx_root, functions, args.window, tc_path)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
