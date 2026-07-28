"""Safely backfill exact historical snapshot rank fields in MongoDB.

Defaults to dry-run. Only ``compRank = rank`` is currently recoverable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data import repository_factory
from backend.operations.rank_field_backfill import RankFieldBackfillService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill recoverable MongoDB snapshot rank fields")
    parser.add_argument("--dataset-id", default="dragonboard_live")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--snapshot-type",
        action="append",
        dest="snapshot_types",
        choices=["quarter_hour", "half_hour", "hourly", "daily"],
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("choose either --dry-run or --apply, not both")
    db = repository_factory.get_runtime_mongodb_database()
    result = RankFieldBackfillService(db).backfill_comp_rank(
        dataset_id=args.dataset_id,
        start_date=args.start_date,
        end_date=args.end_date,
        snapshot_types=args.snapshot_types,
        dry_run=not args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
