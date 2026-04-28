"""Static xref probe for TDX L2 auth-related strings.

This script is read-only. It does not load or call any TDX DLL. It maps target
strings to PE VA/RVA/file offsets, then scans executable sections for immediate
references to those addresses. This helps locate code that resolves or consumes
L2 auth entry names such as TC_SetL2UserInfo and TdxDeep_StartInit.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any

import pefile


DEFAULT_TDX_ROOT = Path(r"D:\APP_SOFT\TDX")
DEFAULT_MODULES = ("tdxw.exe", "tc.dll", "tpbus.dll", "TDXDeep.dll")
DEFAULT_KEYWORDS = (
    "TC_SetL2UserInfo",
    "TC_GetL2Info",
    "TC_GetLoginRet",
    "TC_GetRightInfo",
    "TC_Login",
    "TC_Login2",
    "TdxDeep_StartInit",
    "TdxDeep_Data",
    "TdxDeep_Func",
    "L2Right",
    "L2ZH",
    "QSID",
    "TDXToken",
    "AuthInfo",
    "RightInfo",
    "Local.GetLoginRetInfo",
    "TPL2_Check",
    "TP_Check_GTJAL2",
    "QSTPLevel2_SepcComte",
)


def read_c_string(data: bytes, offset: int, limit: int = 240) -> str:
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


def section_for_rva(pe: pefile.PE, rva: int) -> pefile.SectionStructure | None:
    for section in pe.sections:
        start = section.VirtualAddress
        end = start + max(section.Misc_VirtualSize, section.SizeOfRawData)
        if start <= rva < end:
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


def import_iat_map(pe: pefile.PE) -> dict[int, str]:
    result: dict[int, str] = {}
    if not hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        return result
    for dll in pe.DIRECTORY_ENTRY_IMPORT:
        dll_name = dll.dll.decode("ascii", errors="replace")
        for item in dll.imports:
            if not item.name:
                continue
            name = item.name.decode("ascii", errors="replace")
            result[int(item.address)] = f"{dll_name}!{name}"
    return result


def collect_nearby_calls(pe: pefile.PE, data: bytes, file_offset: int, radius: int) -> list[dict[str, Any]]:
    image_base = pe.OPTIONAL_HEADER.ImageBase
    iat = import_iat_map(pe)
    start = max(0, file_offset - radius)
    end = min(len(data), file_offset + radius)
    chunk = data[start:end]
    calls: list[dict[str, Any]] = []
    for index in range(0, max(0, len(chunk) - 6)):
        absolute = start + index
        rva = offset_to_rva(pe, absolute)
        if chunk[index] == 0xE8 and index + 5 <= len(chunk):
            rel = struct.unpack_from("<i", chunk, index + 1)[0]
            next_rva = rva + 5
            target_rva = (next_rva + rel) & 0xFFFFFFFF
            calls.append(
                {
                    "fileOffset": absolute,
                    "rva": rva,
                    "kind": "call_rel32",
                    "targetRva": target_rva,
                    "targetVa": image_base + target_rva,
                }
            )
        if chunk[index : index + 2] == b"\xff\x15" and index + 6 <= len(chunk):
            pointer_va = struct.unpack_from("<I", chunk, index + 2)[0]
            calls.append(
                {
                    "fileOffset": absolute,
                    "rva": rva,
                    "kind": "call_mem32",
                    "pointerVa": pointer_va,
                    "import": iat.get(pointer_va, ""),
                }
            )
    return calls


def collect_stack_immediates(pe: pefile.PE, data: bytes, file_offset: int, radius: int) -> list[dict[str, Any]]:
    image_base = pe.OPTIONAL_HEADER.ImageBase
    start = max(0, file_offset - radius)
    end = min(len(data), file_offset + radius)
    chunk = data[start:end]
    refs: list[dict[str, Any]] = []
    for index in range(0, max(0, len(chunk) - 5)):
        if chunk[index] not in (0x68, 0xB8, 0xB9, 0xBA, 0xBB, 0xBE, 0xBF):
            continue
        value = struct.unpack_from("<I", chunk, index + 1)[0]
        rva = value - image_base
        ref_offset = rva_to_offset(pe, rva)
        if ref_offset < 0 or ref_offset >= len(data):
            continue
        text = read_c_string(data, ref_offset)
        if not text or sum(ch.isprintable() for ch in text) < min(4, len(text)):
            continue
        absolute = start + index
        refs.append(
            {
                "fileOffset": absolute,
                "rva": offset_to_rva(pe, absolute),
                "opcode": hex(chunk[index]),
                "valueVa": value,
                "valueRva": rva,
                "valueFileOffset": ref_offset,
                "value": text[:180],
            }
        )
    return refs[:80]


def collect_pointer_slots(pe: pefile.PE, data: bytes, ref_offset: int, lookahead: int = 40) -> list[dict[str, Any]]:
    """Find likely global function pointer stores after a GetProcAddress name ref."""
    slots: list[dict[str, Any]] = []
    image_base = pe.OPTIONAL_HEADER.ImageBase
    end = min(len(data), ref_offset + lookahead)
    index = ref_offset
    while index < end:
        # A3 imm32 = mov [imm32], eax
        if data[index] == 0xA3 and index + 5 <= len(data):
            slot_va = struct.unpack_from("<I", data, index + 1)[0]
            slots.append(
                {
                    "storeFileOffset": index,
                    "storeRva": offset_to_rva(pe, index),
                    "storeKind": "mov_mem_eax",
                    "slotVa": slot_va,
                    "slotRva": slot_va - image_base,
                    "slotFileOffset": rva_to_offset(pe, slot_va - image_base),
                }
            )
        # 89 05 imm32 = mov [imm32], eax
        if data[index : index + 2] == b"\x89\x05" and index + 6 <= len(data):
            slot_va = struct.unpack_from("<I", data, index + 2)[0]
            slots.append(
                {
                    "storeFileOffset": index,
                    "storeRva": offset_to_rva(pe, index),
                    "storeKind": "mov_mem_eax",
                    "slotVa": slot_va,
                    "slotRva": slot_va - image_base,
                    "slotFileOffset": rva_to_offset(pe, slot_va - image_base),
                }
            )
        index += 1
    return slots


def collect_slot_uses(pe: pefile.PE, data: bytes, slot_va: int, limit: int = 80) -> list[dict[str, Any]]:
    uses: list[dict[str, Any]] = []
    needle = struct.pack("<I", slot_va)
    for ref_offset in find_all(data, needle):
        section = section_for_offset(pe, ref_offset)
        if section is None or not is_executable(section):
            continue
        start = max(0, ref_offset - 8)
        end = min(len(data), ref_offset + 16)
        context = data[start:end]
        kind = "ref"
        if ref_offset >= 2 and data[ref_offset - 2 : ref_offset] == b"\xff\x15":
            kind = "call_mem32"
        elif ref_offset >= 2 and data[ref_offset - 2] in (0x8B, 0xA1):
            kind = "load"
        uses.append(
            {
                "fileOffset": ref_offset,
                "rva": offset_to_rva(pe, ref_offset),
                "section": section.Name.rstrip(b"\x00").decode("ascii", errors="replace"),
                "kind": kind,
                "contextHex": context.hex(" "),
                "nearbyCalls": collect_nearby_calls(pe, data, ref_offset, 120),
                "nearbyStringImmediates": collect_stack_immediates(pe, data, ref_offset, 120),
            }
        )
        if len(uses) >= limit:
            break
    return uses


def scan_module(path: Path, keywords: list[str], radius: int) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False}

    data = path.read_bytes()
    pe = pefile.PE(str(path), fast_load=False)
    image_base = pe.OPTIONAL_HEADER.ImageBase

    executable_ranges: list[tuple[int, int]] = []
    for section in pe.sections:
        if not is_executable(section):
            continue
        start = section.PointerToRawData
        executable_ranges.append((start, start + section.SizeOfRawData))

    def in_executable(offset: int) -> bool:
        return any(start <= offset < end for start, end in executable_ranges)

    keyword_reports: list[dict[str, Any]] = []
    for keyword in keywords:
        occurrences = []
        for encoding, needle in (
            ("ascii", keyword.encode("ascii", errors="ignore") + b"\x00"),
            ("utf16le", keyword.encode("utf-16le") + b"\x00\x00"),
        ):
            if not needle.strip(b"\x00"):
                continue
            for string_offset in find_all(data, needle):
                string_rva = offset_to_rva(pe, string_offset)
                if string_rva < 0:
                    continue
                string_va = image_base + string_rva
                ref_needles = [
                    ("va32", struct.pack("<I", string_va)),
                    ("rva32", struct.pack("<I", string_rva)),
                    ("file_offset32", struct.pack("<I", string_offset)),
                ]
                refs = []
                for ref_kind, ref_needle in ref_needles:
                    for ref_offset in find_all(data, ref_needle):
                        if ref_offset == string_offset:
                            continue
                        if not in_executable(ref_offset):
                            continue
                        refs.append(
                            ref_report := 
                            {
                                "kind": ref_kind,
                                "fileOffset": ref_offset,
                                "rva": offset_to_rva(pe, ref_offset),
                                "section": (section_for_offset(pe, ref_offset).Name.rstrip(b"\x00").decode("ascii", errors="replace") if section_for_offset(pe, ref_offset) else ""),
                                "nearbyCalls": collect_nearby_calls(pe, data, ref_offset, radius),
                                "nearbyStringImmediates": collect_stack_immediates(pe, data, ref_offset, radius),
                                "contextHex": data[max(0, ref_offset - 32) : min(len(data), ref_offset + 64)].hex(" "),
                            }
                        )
                        slots = collect_pointer_slots(pe, data, ref_offset)
                        if slots:
                            for slot in slots:
                                slot["uses"] = collect_slot_uses(pe, data, slot["slotVa"])
                            ref_report["pointerSlots"] = slots
                occurrences.append(
                    {
                        "encoding": encoding,
                        "stringFileOffset": string_offset,
                        "stringRva": string_rva,
                        "stringVa": string_va,
                        "section": (section_for_rva(pe, string_rva).Name.rstrip(b"\x00").decode("ascii", errors="replace") if section_for_rva(pe, string_rva) else ""),
                        "value": read_c_string(data, string_offset) if encoding == "ascii" else keyword,
                        "refs": refs[:40],
                    }
                )
        if occurrences:
            keyword_reports.append({"keyword": keyword, "occurrences": occurrences})

    return {
        "path": str(path),
        "exists": True,
        "imageBase": image_base,
        "machine": hex(pe.FILE_HEADER.Machine),
        "keywords": keyword_reports,
        "notes": [
            "xref refs are static immediate references to string VA/RVA/file offsets in executable sections.",
            "nearbyStringImmediates is a lightweight hint, not full disassembly.",
            "No DLL was loaded or called.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Static xref probe for TDX L2 auth strings")
    parser.add_argument("--tdx-root", default=str(DEFAULT_TDX_ROOT))
    parser.add_argument("--modules", default=",".join(DEFAULT_MODULES))
    parser.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS))
    parser.add_argument("--radius", type=int, default=160)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    tdx_root = Path(args.tdx_root)
    modules = [item.strip() for item in args.modules.split(",") if item.strip()]
    keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]

    report = {
        "tdxRoot": str(tdx_root),
        "modules": [scan_module(tdx_root / module, keywords, args.radius) for module in modules],
    }
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        output.write_text(payload + "\n", encoding="utf-8")
        summary = {
            "output": str(output),
            "moduleCount": len(report["modules"]),
            "keywordHitCount": sum(len(module.get("keywords", [])) for module in report["modules"]),
        }
        sys.stdout.buffer.write((json.dumps(summary, ensure_ascii=False) + "\n").encode("utf-8", errors="replace"))
    else:
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        sys.stdout.buffer.write((payload + "\n").encode("utf-8", errors="replace"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
