from __future__ import annotations

import argparse
import json
import os
import sys

if __package__ in {None, ""}:
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from l2.qmt_provider import QmtL2Provider


def parse_codes(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe QMT / miniQMT Level2 availability.")
    parser.add_argument(
        "--codes",
        default=os.getenv("QMT_L2_PROBE_CODES", "000001.SZ,600000.SH"),
        help="Comma-separated stock codes, for example 000001.SZ,600000.SH",
    )
    args = parser.parse_args()

    provider = QmtL2Provider()
    codes = parse_codes(args.codes)
    status = provider.probe(codes)
    payload = status.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if status.status == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
