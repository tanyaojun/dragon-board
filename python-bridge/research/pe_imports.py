"""Minimal PE import table reader for TDX L2 research."""

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


def u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


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


def parse_pe_imports(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    pe_offset = u32(data, 0x3C)
    optional_offset = pe_offset + 0x18
    magic = u16(data, optional_offset)
    is_pe32_plus = magic == 0x20B
    data_directory_offset = optional_offset + (0x70 if is_pe32_plus else 0x60)
    import_rva = u32(data, data_directory_offset + 8)
    import_size = u32(data, data_directory_offset + 12)

    section_count = u16(data, pe_offset + 0x6)
    optional_size = u16(data, pe_offset + 0x14)
    section_offset = optional_offset + optional_size
    sections: list[dict[str, int]] = []

    for index in range(section_count):
        offset = section_offset + index * 40
        name = read_c_string(data, offset)
        sections.append(
            {
                "name": name,
                "virtual_size": u32(data, offset + 8),
                "virtual_address": u32(data, offset + 12),
                "raw_size": u32(data, offset + 16),
                "raw_pointer": u32(data, offset + 20),
            }
        )

    import_offset = rva_to_offset(import_rva, sections)
    imports: list[dict[str, Any]] = []
    if import_rva == 0 or import_offset < 0:
        return {
            "path": str(path),
            "importRva": import_rva,
            "importSize": import_size,
            "imports": imports,
        }

    descriptor_size = 20
    descriptor_index = 0
    while True:
        descriptor_offset = import_offset + descriptor_index * descriptor_size
        original_first_thunk = u32(data, descriptor_offset)
        time_date_stamp = u32(data, descriptor_offset + 4)
        forwarder_chain = u32(data, descriptor_offset + 8)
        name_rva = u32(data, descriptor_offset + 12)
        first_thunk = u32(data, descriptor_offset + 16)

        if not any([original_first_thunk, time_date_stamp, forwarder_chain, name_rva, first_thunk]):
            break

        name_offset = rva_to_offset(name_rva, sections)
        dll_name = read_c_string(data, name_offset) if name_offset >= 0 else ""
        thunk_rva = original_first_thunk or first_thunk
        thunk_offset = rva_to_offset(thunk_rva, sections)
        functions: list[str] = []

        if thunk_offset >= 0:
            thunk_size = 8 if is_pe32_plus else 4
            thunk_index = 0
            while True:
                value = u64(data, thunk_offset + thunk_index * thunk_size) if is_pe32_plus else u32(data, thunk_offset + thunk_index * thunk_size)
                if value == 0:
                    break
                ordinal_flag = 0x8000000000000000 if is_pe32_plus else 0x80000000
                if value & ordinal_flag:
                    functions.append(f"ordinal:{value & 0xFFFF}")
                else:
                    hint_name_offset = rva_to_offset(value, sections)
                    if hint_name_offset >= 0:
                        functions.append(read_c_string(data, hint_name_offset + 2))
                thunk_index += 1

        imports.append({"dll": dll_name, "functions": functions})
        descriptor_index += 1

    return {
        "path": str(path),
        "importRva": import_rva,
        "importSize": import_size,
        "imports": imports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump PE import table")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    report = [parse_pe_imports(Path(path)) for path in args.paths]
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
