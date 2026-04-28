"""Static callsite probe for key TDX L2 auth/init entry points.

This script focuses on a few known callsites inside tdxw.exe and emits:
- raw bytes around the callsite
- immediate pushes in the nearby window
- simple notes for well-known patterns we already observed

It does not load or call any DLL.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any

import pefile


DEFAULT_TDXW = Path(r"D:\APP_SOFT\TDX\tdxw.exe")
DEFAULT_CALLSITES = {
    "TC_SetL2UserInfo": 0x003221D1,
    "TdxDeep_StartInit": 0x00325731,
}


def read_ascii_string(data: bytes, offset: int, limit: int = 160) -> str:
    end = data.find(b"\x00", offset, min(len(data), offset + limit))
    if end < 0:
        end = min(len(data), offset + limit)
    return data[offset:end].decode("ascii", errors="replace")


def offset_to_rva(pe: pefile.PE, offset: int) -> int:
    for section in pe.sections:
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        if start <= offset < end:
            return section.VirtualAddress + (offset - start)
    return -1


def va_to_string(pe: pefile.PE, data: bytes, va: int) -> dict[str, Any]:
    image_base = pe.OPTIONAL_HEADER.ImageBase
    rva = va - image_base
    try:
        offset = pe.get_offset_from_rva(rva)
    except Exception:
        return {"va": va, "rva": rva, "offset": -1, "text": ""}
    if not (0 <= offset < len(data)):
        return {"va": va, "rva": rva, "offset": offset, "text": ""}
    return {
        "va": va,
        "rva": rva,
        "offset": offset,
        "text": read_ascii_string(data, offset),
    }


def collect_pushes(pe: pefile.PE, data: bytes, start: int, end: int) -> list[dict[str, Any]]:
    pushes: list[dict[str, Any]] = []
    image_base = pe.OPTIONAL_HEADER.ImageBase
    for offset in range(start, max(start, end - 5)):
        op = data[offset]
        if op == 0x68 and offset + 5 <= len(data):
            value = struct.unpack_from("<I", data, offset + 1)[0]
            entry: dict[str, Any] = {
                "kind": "push_imm32",
                "fileOffset": offset,
                "rva": offset_to_rva(pe, offset),
                "value": value,
            }
            rva = value - image_base
            try:
                string_offset = pe.get_offset_from_rva(rva)
                if 0 <= string_offset < len(data):
                    text = read_ascii_string(data, string_offset)
                    if text:
                        entry["string"] = text
                        entry["stringRva"] = rva
            except Exception:
                pass
            pushes.append(entry)
        elif op in (0x50, 0x51, 0x52, 0x53, 0x56, 0x57):
            pushes.append(
                {
                    "kind": "push_reg",
                    "fileOffset": offset,
                    "rva": offset_to_rva(pe, offset),
                    "opcode": hex(op),
                }
            )
        elif op == 0x6A and offset + 2 <= len(data):
            value = data[offset + 1]
            pushes.append(
                {
                    "kind": "push_imm8",
                    "fileOffset": offset,
                    "rva": offset_to_rva(pe, offset),
                    "value": value,
                }
            )
    return pushes


def collect_context_objects(pe: pefile.PE, data: bytes, start: int, end: int) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for offset in range(start, max(start, end - 5)):
        op = data[offset]
        if op not in (0xB8, 0xB9, 0xBA, 0xBB, 0xBE, 0xBF):
            continue
        value = struct.unpack_from("<I", data, offset + 1)[0]
        info = va_to_string(pe, data, value)
        objects.append(
            {
                "kind": "mov_reg_imm32",
                "fileOffset": offset,
                "rva": offset_to_rva(pe, offset),
                "opcode": hex(op),
                "value": value,
                "string": info.get("text", ""),
                "stringRva": info.get("rva", -1),
            }
        )
    return objects


def analyze_callsite(pe: pefile.PE, data: bytes, name: str, call_rva: int) -> dict[str, Any]:
    call_offset = pe.get_offset_from_rva(call_rva)
    window_start = max(0, call_offset - 96)
    window_end = min(len(data), call_offset + 48)
    window = data[window_start:window_end]
    pushes = collect_pushes(pe, data, window_start, call_offset)
    context_objects = collect_context_objects(pe, data, window_start, call_offset)

    notes: list[str] = []
    interpretation: list[str] = []
    if name == "TC_SetL2UserInfo":
        notes.extend(
            [
                "Observed pattern builds a local buffer with '%s#CFV' and 'CITICS' before the call.",
                "The indirect call is followed by 'add esp, 0x0c', consistent with 3 stack arguments.",
                "Two return values from mfc100.dll ordinal 1448 are pushed immediately before the call.",
            ]
        )
        interpretation.extend(
            [
                "mov esi, 'CITICS'",
                "push esi",
                "lea edx, [ebp-0x28]",
                "push '%s#CFV'",
                "push edx",
                "call mfc100.dll ordinal 4283",
                "add esp, 0x0c",
                "push 0x00C1C58C",
                "mov ecx, 0x011D4FEC",
                "call mfc100.dll ordinal 1448",
                "push eax",
                "lea ecx, [ebp-0x28]",
                "call mfc100.dll ordinal 1448",
                "push eax",
                "call [TC_SetL2UserInfo slot]",
                "add esp, 0x0c",
            ]
        )
    elif name == "TdxDeep_StartInit":
        notes.extend(
            [
                "The indirect call is followed by 'add esp, 0x1c', consistent with 7 stack arguments.",
                "Three return values from mfc100.dll ordinal 1448 are pushed immediately before the call.",
                "Earlier stack args include 0, a byte-sized global flag, and a dword loaded from .data.",
            ]
        )
        interpretation.extend(
            [
                "push 'connect.cfg'",
                "lea eax, [ebp-0x10]",
                "push 0x011D4340",
                "push eax",
                "call local helper",
                "add esp, 0x0c",
                "movzx ecx, byte ptr [0x00E7F11B]",
                "mov edx, dword ptr [0x010FCF54]",
                "push 0",
                "push 0x00E75858",
                "push ecx",
                "push edx",
                "mov ecx, eax",
                "call mfc100.dll ordinal 1448",
                "push eax",
                "mov ecx, 0x011D41E0",
                "call mfc100.dll ordinal 1448",
                "push eax",
                "mov ecx, 0x011D4340",
                "call mfc100.dll ordinal 1448",
                "push eax",
                "call [TdxDeep_StartInit slot]",
                "add esp, 0x1c",
            ]
        )

    return {
        "name": name,
        "callRva": call_rva,
        "callFileOffset": call_offset,
        "windowHex": window.hex(" "),
        "pushesBeforeCall": pushes,
        "contextObjects": context_objects,
        "notes": notes,
        "interpretation": interpretation,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Static callsite probe for TDX L2 entry points")
    parser.add_argument("--tdxw", default=str(DEFAULT_TDXW))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    path = Path(args.tdxw)
    pe = pefile.PE(str(path), fast_load=True)
    data = path.read_bytes()

    report = {
        "path": str(path),
        "imageBase": pe.OPTIONAL_HEADER.ImageBase,
        "callsites": [analyze_callsite(pe, data, name, rva) for name, rva in DEFAULT_CALLSITES.items()],
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "callsiteCount": len(report["callsites"])}, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
