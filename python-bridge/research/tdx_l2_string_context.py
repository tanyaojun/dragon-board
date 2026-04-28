"""Extract offset-aware string context for TDX 7719/L2 research.

This is a read-only helper. It scans binary files for ASCII and UTF-16LE string
runs, keeps their file offsets, and emits keyword neighborhoods without
modifying any TDX client files.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_KEYWORDS = (
    "TDXDeep",
    "TdxDeep_",
    "TC_SetL2UserInfo",
    "TC_GetL2Info",
    "TPL2_Check",
    "TP_Check_GTJAL2",
    "TPL2_GetSSO",
    "QSTPLevel2",
    "Level2_SepcComte",
    "L2HOST",
    "COMM_LEVEL2",
    "now-auth-tdx",
    "SSOMode",
    "L2Right",
    "QSID",
    "CURL2",
)


@dataclass
class StringRun:
    offset: int
    encoding: str
    value: str


@dataclass
class KeywordContext:
    keyword: str
    offset: int
    encoding: str
    value: str
    before: list[StringRun]
    after: list[StringRun]


def extract_ascii_strings(data: bytes, min_length: int) -> list[StringRun]:
    runs: list[StringRun] = []
    start: int | None = None
    buf = bytearray()

    for index, byte in enumerate(data):
        if 32 <= byte <= 126:
            if start is None:
                start = index
            buf.append(byte)
            continue

        if start is not None and len(buf) >= min_length:
            runs.append(StringRun(start, "ascii", buf.decode("ascii", errors="replace")))
        start = None
        buf.clear()

    if start is not None and len(buf) >= min_length:
        runs.append(StringRun(start, "ascii", buf.decode("ascii", errors="replace")))

    return runs


def extract_utf16le_strings(data: bytes, min_length: int) -> list[StringRun]:
    runs: list[StringRun] = []
    start: int | None = None
    chars: list[str] = []

    for index in range(0, len(data) - 1, 2):
        lo = data[index]
        hi = data[index + 1]
        if hi == 0 and 32 <= lo <= 126:
            if start is None:
                start = index
            chars.append(chr(lo))
            continue

        if start is not None and len(chars) >= min_length:
            runs.append(StringRun(start, "utf16le", "".join(chars)))
        start = None
        chars.clear()

    if start is not None and len(chars) >= min_length:
        runs.append(StringRun(start, "utf16le", "".join(chars)))

    return runs


def build_contexts(
    runs: list[StringRun],
    keywords: list[str],
    radius: int,
    max_per_keyword: int,
) -> list[KeywordContext]:
    contexts: list[KeywordContext] = []
    lowered = [(keyword, keyword.lower()) for keyword in keywords]

    for keyword, lowered_keyword in lowered:
        count = 0
        for index, run in enumerate(runs):
            if lowered_keyword not in run.value.lower():
                continue
            contexts.append(
                KeywordContext(
                    keyword=keyword,
                    offset=run.offset,
                    encoding=run.encoding,
                    value=run.value,
                    before=runs[max(0, index - radius) : index],
                    after=runs[index + 1 : index + 1 + radius],
                )
            )
            count += 1
            if count >= max_per_keyword:
                break

    return contexts


def scan_file(path: Path, keywords: list[str], min_length: int, radius: int, max_per_keyword: int) -> dict:
    data = path.read_bytes()
    runs = extract_ascii_strings(data, min_length) + extract_utf16le_strings(data, min_length)
    runs.sort(key=lambda item: (item.offset, item.encoding))
    contexts = build_contexts(runs, keywords, radius, max_per_keyword)
    return {
        "path": str(path),
        "length": len(data),
        "stringRunCount": len(runs),
        "keywords": keywords,
        "contexts": [asdict(item) for item in contexts],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract TDX L2 keyword string context")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--keywords", default=",".join(DEFAULT_KEYWORDS))
    parser.add_argument("--min-length", type=int, default=5)
    parser.add_argument("--radius", type=int, default=4)
    parser.add_argument("--max-per-keyword", type=int, default=20)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    keywords = [item.strip() for item in args.keywords.split(",") if item.strip()]
    report = [
        scan_file(Path(path), keywords, args.min_length, args.radius, args.max_per_keyword)
        for path in args.paths
    ]
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
