"""Load-only probe for TDXDeep.dll exports.

This helper only checks PE bitness and resolves exported function addresses. It
does not call TdxDeep_StartInit, TdxDeep_Data, or any other DLL entry.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import struct
from pathlib import Path
from typing import Any

import pefile


DEFAULT_TDX_ROOT = Path(r"D:\TDX_PLUS")
DEFAULT_EXPORTS = (
    "TdxDeep_Data",
    "TdxDeep_Func",
    "TdxDeep_RegisterCallBackFunc",
    "TdxDeep_SetMainWnd",
    "TdxDeep_StartInit",
    "TdxDeep_Uninit",
)


def machine_bits(machine: int) -> int:
    if machine == 0x014C:
        return 32
    if machine == 0x8664:
        return 64
    return 0


def read_exports(path: Path) -> dict[str, dict[str, Any]]:
    pe = pefile.PE(str(path), fast_load=False)
    exports: dict[str, dict[str, Any]] = {}
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if symbol.name:
                exports[symbol.name.decode("ascii", errors="replace")] = {
                    "ordinal": int(symbol.ordinal),
                    "rva": int(symbol.address),
                }
    return exports


def probe(tdx_root: Path) -> dict[str, Any]:
    path = tdx_root / "TDXDeep.dll"
    if not path.exists():
        return {"ok": False, "reason": "missing_tdxdeep_dll", "path": str(path)}

    pe = pefile.PE(str(path), fast_load=True)
    dll_bits = machine_bits(pe.FILE_HEADER.Machine)
    python_bits = struct.calcsize("P") * 8
    exports = read_exports(path)
    report: dict[str, Any] = {
        "ok": False,
        "mode": "load_only",
        "path": str(path),
        "pythonBits": python_bits,
        "pythonArchitecture": platform.architecture()[0],
        "dllMachine": hex(pe.FILE_HEADER.Machine),
        "dllBits": dll_bits,
        "exports": exports,
        "resolved": {},
    }

    if dll_bits and dll_bits != python_bits:
        report["reason"] = "bitness_mismatch"
        return report

    handle = ctypes.WinDLL(str(path))
    resolved = {}
    for name in DEFAULT_EXPORTS:
        try:
            fn = getattr(handle, name)
            resolved[name] = {"ok": True, "address": ctypes.cast(fn, ctypes.c_void_p).value}
        except AttributeError:
            resolved[name] = {"ok": False}
    report["ok"] = True
    report["resolved"] = resolved
    report["note"] = "DLL loaded and exports resolved only; no exported function was called."
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Load-only TDXDeep.dll probe")
    parser.add_argument("--tdx-root", default=str(DEFAULT_TDX_ROOT))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    report = probe(Path(args.tdx_root))
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
