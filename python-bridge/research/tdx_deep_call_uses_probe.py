"""Disassemble tdxw.exe uses of TDXDeep function pointer slots.

This is static-only. It scans executable sections for references to the known
TDXDeep GetProcAddress slots and emits short x86 disassembly windows so call
signatures can be inferred.
"""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32


DEFAULT_TDXW = Path(r"D:\APP_SOFT\TDX\tdxw.exe")
DEFAULT_SLOTS = {
    "TdxDeep_StartInit": 0x012285C8,
    "TdxDeep_RegisterCallBackFunc": 0x012285CC,
    "TdxDeep_SetMainWnd": 0x012285D0,
    "TdxDeep_Func": 0x012285D4,
    "TdxDeep_Data": 0x012285D8,
    "TdxDeep_Uninit": 0x012285DC,
}


def offset_to_rva(pe: pefile.PE, offset: int) -> int:
    for section in pe.sections:
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        if start <= offset < end:
            return section.VirtualAddress + (offset - start)
    return -1


def is_executable(section: pefile.SectionStructure) -> bool:
    return bool(section.Characteristics & 0x20000000)


def find_all(data: bytes, needle: bytes, start: int, end: int) -> list[int]:
    hits: list[int] = []
    pos = start
    while True:
        index = data.find(needle, pos, end)
        if index < 0:
            return hits
        hits.append(index)
        pos = index + 1


def classify_use(data: bytes, offset: int) -> str:
    if offset >= 2 and data[offset - 2 : offset] == b"\xff\x15":
        return "call_mem32"
    if offset >= 1 and data[offset - 1] == 0xA1:
        return "mov_eax_mem32"
    if offset >= 2 and data[offset - 2] == 0x8B:
        return "mov_reg_mem32"
    if offset >= 2 and data[offset - 2] == 0x83:
        return "cmp_mem32_imm8"
    return "ref"


def disassemble_window(pe: pefile.PE, data: bytes, center_offset: int, before: int, after: int) -> list[dict[str, Any]]:
    window_start = max(0, center_offset - before)
    window_end = min(len(data), center_offset + after)
    rva_start = offset_to_rva(pe, window_start)
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    instructions: list[dict[str, Any]] = []
    for insn in md.disasm(data[window_start:window_end], pe.OPTIONAL_HEADER.ImageBase + rva_start):
        instructions.append(
            {
                "va": f"0x{insn.address:08X}",
                "rva": f"0x{insn.address - pe.OPTIONAL_HEADER.ImageBase:08X}",
                "mnemonic": insn.mnemonic,
                "opStr": insn.op_str,
            }
        )
    return instructions


def scan_slot(pe: pefile.PE, data: bytes, name: str, slot_va: int, before: int, after: int, limit: int) -> dict[str, Any]:
    needle = struct.pack("<I", slot_va)
    uses: list[dict[str, Any]] = []
    for section in pe.sections:
        if not is_executable(section):
            continue
        start = section.PointerToRawData
        end = start + section.SizeOfRawData
        for offset in find_all(data, needle, start, end):
            use = {
                "fileOffset": offset,
                "rva": f"0x{offset_to_rva(pe, offset):08X}",
                "kind": classify_use(data, offset),
                "contextHex": data[max(start, offset - 16) : min(end, offset + 24)].hex(" "),
                "instructions": disassemble_window(pe, data, offset, before, after),
            }
            uses.append(use)
            if len(uses) >= limit:
                break
        if len(uses) >= limit:
            break
    return {
        "name": name,
        "slotVa": f"0x{slot_va:08X}",
        "useCount": len(uses),
        "uses": uses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Static disassembly probe for TDXDeep slot uses")
    parser.add_argument("--tdxw", default=str(DEFAULT_TDXW))
    parser.add_argument("--slots", default="")
    parser.add_argument("--before", type=int, default=96)
    parser.add_argument("--after", type=int, default=96)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    path = Path(args.tdxw)
    pe = pefile.PE(str(path), fast_load=False)
    data = path.read_bytes()
    names = [item.strip() for item in args.slots.split(",") if item.strip()]
    slots = {name: DEFAULT_SLOTS[name] for name in names} if names else DEFAULT_SLOTS
    report = {
        "path": str(path),
        "imageBase": f"0x{pe.OPTIONAL_HEADER.ImageBase:08X}",
        "slots": [scan_slot(pe, data, name, slot, args.before, args.after, args.limit) for name, slot in slots.items()],
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
        print(json.dumps({"output": str(output), "slotCount": len(report["slots"])}, ensure_ascii=False))
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
