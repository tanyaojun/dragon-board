"""Backfill MongoDB hotlist_sentiment from snapshot_frames.

Usage:
  cd quant-board
  .venv/Scripts/python.exe scripts/backfill_hotlist_sentiment.py --dry-run
  .venv/Scripts/python.exe scripts/backfill_hotlist_sentiment.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data import repository_factory
from backend.operations.hotlist_sentiment import HotListSentimentBackfillService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill hotlist_sentiment from MongoDB snapshot frames")
    parser.add_argument("--dataset-id", default="dragonboard_live")
    parser.add_argument("--snapshot-type", default="half_hour", choices=["half_hour", "quarter_hour"])
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("choose either --dry-run or --apply, not both")
    dry_run = not args.apply
    db = repository_factory.get_runtime_mongodb_database()
    result = HotListSentimentBackfillService(db).backfill(
        dataset_id=args.dataset_id,
        snapshot_type=args.snapshot_type,
        start_date=args.start_date,
        end_date=args.end_date,
        dry_run=dry_run,
        limit=args.limit,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
