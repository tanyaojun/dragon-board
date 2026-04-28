"""Static probe for TP_Check_GTJAL2 / TPL2_Check auth context.

This script is read-only. It does not load or call any TDX DLL. It anchors on
known strings inside tdxw.exe, scans executable sections for immediate
references to those strings, and reports nearby calls, stack pushes, and
string immediates so the L2 auth entry chain can be reproduced.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any

import pefile


DEFAULT_TDXW = Path(r"D:\APP_SOFT\TDX\tdxw.exe")
DEFAULT_KEYWORDS = (
    "TP_Check_GTJAL2",
    "Start TP_Check_GTJAL2: %s,%s,%s",
    "TP_Check_GTJAL2 return,SyncMode=%d,code=%d,ans: %s",
    "TPL2_Check",
    "Start TPL2_Check",
    "TPL2_Check Sync OK!",
    "Local.GetLoginRetInfo",
    "TdxW_GetLoginRetInfo",
    "RightInfo",
    "L2ZH",
)


def read_ascii_string(data: bytes, offset: int, limit: int = 240) -> str:
    end = data.find(b"\x00", offset, min(len(data), offset + limit))
    if end < 0:
        end = min(len(data), offset + limit)
    return data[offset:end].decode("ascii", errors="replace")


def section_for_offset(pe: pefile.PE, offset: int) -> pefile.SectionStructure | None:
    for section in pe.sections:
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        if start <= offset < end:
            return section
    return None


def offset_to_rva(pe: pefile.PE, offset: int) -> int:
    section = section_for_offset(pe, offset)
    if section is None:
        return -1
    return section.VirtualAddress + (offset - section.PointerToRawData)


def rva_to_offset(pe: pefile.PE, rva: int) -> int:
    try:
        return pe.get_offset_from_rva(rva)
    except Exception:
        return -1


def is_executable(section: pefile.SectionStructure) -> bool:
    return bool(section.Characteristics & 0x20000000)


def find_all(data: bytes, needle: bytes) -> list[int]:
    hits: list[int] = []
    start = 0
    while True:
        index = data.find(needle, start)
        if index < 0:
            return hits
        hits.append(index)
        start = index + 1


def find_strings(pe: pefile.PE, data: bytes, keyword: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    needle = keyword.encode("ascii")
    image_base = pe.OPTIONAL_HEADER.ImageBase
    for offset in find_all(data, needle):
        rva = offset_to_rva(pe, offset)
        if rva < 0:
            continue
        section = section_for_offset(pe, offset)
        results.append(
            {
                "keyword": keyword,
                "fileOffset": offset,
                "rva": rva,
                "va": image_base + rva,
                "section": section.Name.decode("ascii", errors="replace").rstrip("\x00") if section else "",
                "value": read_ascii_string(data, offset),
            }
        )
    return results


def collect_nearby_calls(pe: pefile.PE, data: bytes, file_offset: int, radius: int) -> list[dict[str, Any]]:
    image_base = pe.OPTIONAL_HEADER.ImageBase
    start = max(0, file_offset - radius)
    end = min(len(data), file_offset + radius)
    calls: list[dict[str, Any]] = []
    for offset in range(start, max(start, end - 6)):
        rva = offset_to_rva(pe, offset)
        if data[offset] == 0xE8 and offset + 5 <= len(data):
            rel = struct.unpack_from("<i", data, offset + 1)[0]
            target_rva = (rva + 5 + rel) & 0xFFFFFFFF
            calls.append(
                {
                    "fileOffset": offset,
                    "rva": rva,
                    "kind": "call_rel32",
                    "targetRva": target_rva,
                    "targetVa": image_base + target_rva,
                }
            )
        elif data[offset : offset + 2] == b"\xff\x15" and offset + 6 <= len(data):
            pointer_va = struct.unpack_from("<I", data, offset + 2)[0]
            calls.append(
                {
                    "fileOffset": offset,
                    "rva": rva,
                    "kind": "call_mem32",
                    "pointerVa": pointer_va,
                }
            )
    return calls


def collect_pushes(pe: pefile.PE, data: bytes, start: int, end: int) -> list[dict[str, Any]]:
    image_base = pe.OPTIONAL_HEADER.ImageBase
    pushes: list[dict[str, Any]] = []
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
            string_offset = rva_to_offset(pe, value - image_base)
            if 0 <= string_offset < len(data):
                text = read_ascii_string(data, string_offset)
                if text:
                    entry["string"] = text
                    entry["stringRva"] = value - image_base
            pushes.append(entry)
        elif op == 0x6A and offset + 2 <= len(data):
            pushes.append(
                {
                    "kind": "push_imm8",
                    "fileOffset": offset,
                    "rva": offset_to_rva(pe, offset),
                    "value": data[offset + 1],
                }
            )
        elif op in (0x50, 0x51, 0x52, 0x53, 0x56, 0x57):
            pushes.append(
                {
                    "kind": "push_reg",
                    "fileOffset": offset,
                    "rva": offset_to_rva(pe, offset),
                    "opcode": hex(op),
                }
            )
    return pushes


def collect_string_immediates(pe: pefile.PE, data: bytes, file_offset: int, radius: int) -> list[dict[str, Any]]:
    image_base = pe.OPTIONAL_HEADER.ImageBase
    start = max(0, file_offset - radius)
    end = min(len(data), file_offset + radius)
    refs: list[dict[str, Any]] = []
    for offset in range(start, max(start, end - 5)):
        if data[offset] not in (0x68, 0xB8, 0xB9, 0xBA, 0xBB, 0xBE, 0xBF):
            continue
        value = struct.unpack_from("<I", data, offset + 1)[0]
        string_offset = rva_to_offset(pe, value - image_base)
        if not (0 <= string_offset < len(data)):
            continue
        text = read_ascii_string(data, string_offset)
        if not text:
            continue
        printable = sum(ch.isprintable() for ch in text)
        if printable < min(4, len(text)):
            continue
        refs.append(
            {
                "fileOffset": offset,
                "rva": offset_to_rva(pe, offset),
                "opcode": hex(data[offset]),
                "valueVa": value,
                "valueRva": value - image_base,
                "text": text[:220],
            }
        )
    return refs[:80]


def collect_refs(pe: pefile.PE, data: bytes, target_va: int, radius: int) -> list[dict[str, Any]]:
    needle = struct.pack("<I", target_va)
    refs: list[dict[str, Any]] = []
    for section in pe.sections:
        if not is_executable(section):
            continue
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        chunk = data[start:end]
        for index in find_all(chunk, needle):
            offset = start + index
            window_start = max(0, offset - radius)
            window_end = min(len(data), offset + radius)
            refs.append(
                {
                    "fileOffset": offset,
                    "rva": offset_to_rva(pe, offset),
                    "section": section.Name.decode("ascii", errors="replace").rstrip("\x00"),
                    "nearbyCalls": collect_nearby_calls(pe, data, offset, radius),
                    "nearbyPushes": collect_pushes(pe, data, window_start, offset),
                    "nearbyStringImmediates": collect_string_immediates(pe, data, offset, radius),
                    "contextHex": data[window_start:window_end].hex(" "),
                }
            )
    return refs


def collect_direct_callers(pe: pefile.PE, data: bytes, target_rva: int) -> list[dict[str, Any]]:
    callers: list[dict[str, Any]] = []
    image_base = pe.OPTIONAL_HEADER.ImageBase
    for section in pe.sections:
        if not is_executable(section):
            continue
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        for offset in range(start, max(start, end - 5)):
            if data[offset] != 0xE8:
                continue
            rva = offset_to_rva(pe, offset)
            rel = struct.unpack_from("<i", data, offset + 1)[0]
            call_target = (rva + 5 + rel) & 0xFFFFFFFF
            if call_target != target_rva:
                continue
            window_start = max(0, offset - 96)
            callers.append(
                {
                    "fileOffset": offset,
                    "rva": rva,
                    "targetRva": call_target,
                    "targetVa": image_base + call_target,
                    "pushesBeforeCall": collect_pushes(pe, data, window_start, offset),
                    "nearbyStringImmediates": collect_string_immediates(pe, data, offset, 128),
                    "contextHex": data[window_start : min(len(data), offset + 48)].hex(" "),
                }
            )
    return callers


def main() -> int:
    parser = argparse.ArgumentParser(description="Static probe for TP_Check_GTJAL2 / TPL2_Check context")
    parser.add_argument("--tdxw", default=str(DEFAULT_TDXW))
    parser.add_argument("--output", default="")
    parser.add_argument("--radius", type=int, default=192)
    parser.add_argument("--function-rva", default="0x00511F10")
    args = parser.parse_args()

    path = Path(args.tdxw)
    pe = pefile.PE(str(path), fast_load=True)
    data = path.read_bytes()
    function_rva = int(args.function_rva, 0)

    strings: list[dict[str, Any]] = []
    for keyword in DEFAULT_KEYWORDS:
        for item in find_strings(pe, data, keyword):
            item["refs"] = collect_refs(pe, data, item["va"], args.radius)
            strings.append(item)

    report = {
        "path": str(path),
        "imageBase": pe.OPTIONAL_HEADER.ImageBase,
        "functionRva": function_rva,
        "functionVa": pe.OPTIONAL_HEADER.ImageBase + function_rva,
        "directCallers": collect_direct_callers(pe, data, function_rva),
        "strings": strings,
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "strings": len(strings), "directCallers": len(report["directCallers"])}, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
