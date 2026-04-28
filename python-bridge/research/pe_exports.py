"""Minimal PE export table reader for TDX L2 research."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any


def u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def read_c_string(data: bytes, offset: int) -> str:
    end = data.find(b"\x00", offset)
    if end < 0:
        end = len(data)
    return data[offset:end].decode("ascii", errors="replace")


def rva_to_offset(rva: int, sections: list[dict[str, int]]) -> int:
    for section in sections:
        size = max(section["virtual_size"], section["raw_size"])
        if section["virtual_address"] <= rva < section["virtual_address"] + size:
            return section["raw_pointer"] + (rva - section["virtual_address"])
    return -1


def parse_sections(data: bytes) -> tuple[int, bool, list[dict[str, int]]]:
    pe_offset = u32(data, 0x3C)
    optional_offset = pe_offset + 0x18
    magic = u16(data, optional_offset)
    is_pe32_plus = magic == 0x20B
    section_count = u16(data, pe_offset + 0x6)
    optional_size = u16(data, pe_offset + 0x14)
    section_offset = optional_offset + optional_size
    sections: list[dict[str, int]] = []

    for index in range(section_count):
        offset = section_offset + index * 40
        sections.append(
            {
                "name": read_c_string(data, offset),
                "virtual_size": u32(data, offset + 8),
                "virtual_address": u32(data, offset + 12),
                "raw_size": u32(data, offset + 16),
                "raw_pointer": u32(data, offset + 20),
            }
        )

    return optional_offset, is_pe32_plus, sections


def parse_pe_exports(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    optional_offset, is_pe32_plus, sections = parse_sections(data)
    data_directory_offset = optional_offset + (0x70 if is_pe32_plus else 0x60)
    export_rva = u32(data, data_directory_offset)
    export_size = u32(data, data_directory_offset + 4)
    export_offset = rva_to_offset(export_rva, sections)

    if export_rva == 0 or export_offset < 0:
        return {"path": str(path), "exportRva": export_rva, "exportSize": export_size, "exports": []}

    ordinal_base = u32(data, export_offset + 16)
    number_of_functions = u32(data, export_offset + 20)
    number_of_names = u32(data, export_offset + 24)
    address_of_functions_rva = u32(data, export_offset + 28)
    address_of_names_rva = u32(data, export_offset + 32)
    address_of_name_ordinals_rva = u32(data, export_offset + 36)

    functions_offset = rva_to_offset(address_of_functions_rva, sections)
    names_offset = rva_to_offset(address_of_names_rva, sections)
    ordinals_offset = rva_to_offset(address_of_name_ordinals_rva, sections)

    exports: list[dict[str, Any]] = []
    if names_offset < 0 or ordinals_offset < 0 or functions_offset < 0:
        return {"path": str(path), "exportRva": export_rva, "exportSize": export_size, "exports": exports}

    for index in range(number_of_names):
        name_rva = u32(data, names_offset + index * 4)
        name_offset = rva_to_offset(name_rva, sections)
        ordinal_index = u16(data, ordinals_offset + index * 2)
        function_rva = 0
        if ordinal_index < number_of_functions:
            function_rva = u32(data, functions_offset + ordinal_index * 4)
        exports.append(
            {
                "name": read_c_string(data, name_offset) if name_offset >= 0 else "",
                "ordinal": ordinal_base + ordinal_index,
                "rva": function_rva,
            }
        )

    return {
        "path": str(path),
        "exportRva": export_rva,
        "exportSize": export_size,
        "exports": exports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump PE export table")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    report = [parse_pe_exports(Path(path)) for path in args.paths]
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
