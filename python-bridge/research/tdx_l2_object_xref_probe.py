"""Static xref probe for global objects used near TDX L2 auth callsites.

The callsite probe showed TC_SetL2UserInfo using global object 0x011D4FEC
through an MFC helper. This script finds code references to selected global
objects and summarizes nearby strings/calls so L2-specific uses can be
separated from generic UI/string helper usage.

No DLL is loaded or called.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any

import pefile


DEFAULT_TDXW = Path(r"D:\APP_SOFT\TDX\tdxw.exe")
DEFAULT_TARGETS = {
    "mfc_string_object_a": 0x011D4FEC,
    "deep_string_object_a": 0x011D41E0,
    "deep_string_object_b": 0x011D4340,
    "deep_global_dword": 0x010FCF54,
    "deep_global_flag": 0x00E7F11B,
}

KEY_TERMS = (
    "CITICS",
    "%s#CFV",
    "TC_SetL2UserInfo",
    "TC_GetL2Info",
    "L2Right",
    "L2ZH",
    "QSID",
    "TDXToken",
    "AuthInfo",
    "RightInfo",
    "Local.GetLoginRetInfo",
    "connect.cfg",
    "TDXDeep.dll",
    "TdxDeep_StartInit",
)


def offset_to_rva(pe: pefile.PE, offset: int) -> int:
    for section in pe.sections:
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        if start <= offset < end:
            return section.VirtualAddress + (offset - start)
    return -1


def is_executable_section(section: pefile.SectionStructure) -> bool:
    return bool(section.Characteristics & 0x20000000)


def read_c_string(data: bytes, offset: int, limit: int = 180) -> str:
    end = data.find(b"\x00", offset, min(len(data), offset + limit))
    if end < 0:
        end = min(len(data), offset + limit)
    return data[offset:end].decode("ascii", errors="replace")


def string_from_va(pe: pefile.PE, data: bytes, va: int) -> str:
    rva = va - pe.OPTIONAL_HEADER.ImageBase
    try:
        offset = pe.get_offset_from_rva(rva)
    except Exception:
        return ""
    if not (0 <= offset < len(data)):
        return ""
    text = read_c_string(data, offset)
    printable = sum(32 <= ord(ch) < 127 for ch in text)
    if printable < min(4, len(text)):
        return ""
    return text


def find_text_refs(pe: pefile.PE, data: bytes, start: int, end: int) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for offset in range(start, max(start, end - 5)):
        op = data[offset]
        if op not in (0x68, 0xB8, 0xB9, 0xBA, 0xBB, 0xBE, 0xBF):
            continue
        value = struct.unpack_from("<I", data, offset + 1)[0]
        text = string_from_va(pe, data, value)
        if not text:
            continue
        refs.append(
            {
                "rva": offset_to_rva(pe, offset),
                "fileOffset": offset,
                "opcode": hex(op),
                "valueVa": value,
                "text": text[:160],
            }
        )
    return refs


def import_map(pe: pefile.PE) -> dict[int, str]:
    result: dict[int, str] = {}
    if not hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        return result
    for dll in pe.DIRECTORY_ENTRY_IMPORT:
        dll_name = dll.dll.decode("ascii", errors="replace")
        for item in dll.imports:
            if item.name:
                name = item.name.decode("ascii", errors="replace")
            else:
                name = f"ord{item.ordinal}"
            result[int(item.address)] = f"{dll_name}!{name}"
    return result


def find_calls(pe: pefile.PE, data: bytes, start: int, end: int) -> list[dict[str, Any]]:
    image_base = pe.OPTIONAL_HEADER.ImageBase
    imports = import_map(pe)
    calls: list[dict[str, Any]] = []
    for offset in range(start, max(start, end - 6)):
        if data[offset] == 0xE8:
            rel = struct.unpack_from("<i", data, offset + 1)[0]
            next_rva = offset_to_rva(pe, offset) + 5
            target_rva = (next_rva + rel) & 0xFFFFFFFF
            calls.append(
                {
                    "rva": offset_to_rva(pe, offset),
                    "kind": "call_rel32",
                    "targetRva": target_rva,
                    "targetVa": image_base + target_rva,
                }
            )
        elif data[offset : offset + 2] == b"\xff\x15":
            pointer_va = struct.unpack_from("<I", data, offset + 2)[0]
            calls.append(
                {
                    "rva": offset_to_rva(pe, offset),
                    "kind": "call_mem32",
                    "pointerVa": pointer_va,
                    "import": imports.get(pointer_va, ""),
                }
            )
    return calls


def find_key_terms(pe: pefile.PE, data: bytes, start: int, end: int) -> list[str]:
    text_refs = find_text_refs(pe, data, start, end)
    values = [item["text"] for item in text_refs]
    hits: list[str] = []
    for term in KEY_TERMS:
        if any(term in value for value in values):
            hits.append(term)
    return hits


def scan_target(pe: pefile.PE, data: bytes, name: str, va: int, radius: int, limit: int) -> dict[str, Any]:
    needle = struct.pack("<I", va)
    refs: list[dict[str, Any]] = []
    for section in pe.sections:
        if not is_executable_section(section):
            continue
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        pos = start
        while True:
            offset = data.find(needle, pos, end)
            if offset < 0:
                break
            window_start = max(start, offset - radius)
            window_end = min(end, offset + radius)
            refs.append(
                {
                    "rva": offset_to_rva(pe, offset),
                    "fileOffset": offset,
                    "contextHex": data[max(start, offset - 24) : min(end, offset + 40)].hex(" "),
                    "nearbyStrings": find_text_refs(pe, data, window_start, window_end),
                    "nearbyCalls": find_calls(pe, data, window_start, window_end),
                    "keyTerms": find_key_terms(pe, data, window_start, window_end),
                }
            )
            pos = offset + 1

    refs.sort(key=lambda item: (0 if item["keyTerms"] else 1, item["rva"]))
    return {
        "name": name,
        "va": va,
        "rva": va - pe.OPTIONAL_HEADER.ImageBase,
        "refCount": len(refs),
        "refs": refs[:limit],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Static xref probe for selected tdxw.exe global objects")
    parser.add_argument("--tdxw", default=str(DEFAULT_TDXW))
    parser.add_argument("--targets", default="")
    parser.add_argument("--radius", type=int, default=160)
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    path = Path(args.tdxw)
    pe = pefile.PE(str(path), fast_load=False)
    data = path.read_bytes()
    targets = dict(DEFAULT_TARGETS)
    if args.targets:
        targets = {}
        for item in args.targets.split(","):
            if not item.strip():
                continue
            name, value = item.split("=", 1)
            targets[name.strip()] = int(value.strip(), 0)

    report = {
        "path": str(path),
        "imageBase": pe.OPTIONAL_HEADER.ImageBase,
        "targets": [scan_target(pe, data, name, va, args.radius, args.limit) for name, va in targets.items()],
        "notes": [
            "Refs are sorted so windows containing known L2 terms appear first.",
            "This is byte-pattern xref analysis, not full disassembly.",
            "No DLL was loaded or called.",
        ],
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "targetCount": len(report["targets"])}, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
