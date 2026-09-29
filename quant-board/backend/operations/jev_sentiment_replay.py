# -*- coding: utf-8 -*-
"""jev 观察轨道最近 N 交易日回放 runner（观察轨道 v3）。

用途（design §7/D3）：上线即有可看数据——对最近 N 个交易日的已采 half_hour 帧重跑
双问题评判（槽位 + 日级），落 hotlist_jev_sentiment（origin=replay）。非回测、不判对错。

用法（Git Bash，令牌经环境变量传入不入仓）：
  export JEV_CF_TOKEN=<token>
  ./.venv/Scripts/python.exe -m backend.operations.jev_sentiment_replay --days 3 --dry-run
  ./.venv/Scripts/python.exe -m backend.operations.jev_sentiment_replay --days 3
"""
from __future__ import annotations

import argparse
import os
import sys

from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.jev.jev_sentiment_compute import (
    _jev_config,
    compute_and_upsert_for_day,
    compute_and_upsert_for_slot,
)

DATASET_DEFAULT = "dragonboard_live"
HALF_HOUR = "half_hour"


def _trading_dates(db, dataset_id: str, days: int, start: str | None, end: str | None) -> list[str]:
    query: dict = {"datasetId": dataset_id, "type": HALF_HOUR}
    if start or end:
        range_query: dict = {}
        if start:
            range_query["$gte"] = start
        if end:
            range_query["$lte"] = end
        query["tradingDate"] = range_query
    dates = sorted({
        str(row.get("tradingDate"))
        for row in db["snapshot_frames"].find(query, {"tradingDate": 1})
        if row.get("tradingDate")
    })
    return dates[-days:] if days and days > 0 else dates


def run(days: int = 3, dry_run: bool = False, start: str | None = None,
        end: str | None = None, dataset_id: str = DATASET_DEFAULT) -> int:
    enabled, token, account = _jev_config()
    if not dry_run and not token:
        print("需要 JEV_CF_TOKEN 环境变量（Cloudflare API token，不入仓）", file=sys.stderr)
        return 2
    if not enabled and not dry_run:
        print("提示：JEV_SENTIMENT_ENABLED 未开启；回放 runner 显式执行，继续（origin=replay）。")
    db = get_runtime_mongodb_database()
    dates = _trading_dates(db, dataset_id, days, start, end)
    if not dates:
        print(f"窗口内无 half_hour 帧：dataset={dataset_id} start={start} end={end}")
        return 1
    print(f"回放窗口 {dates[0]} → {dates[-1]}（{len(dates)} 个交易日，dry_run={dry_run}）")
    counts = {"ok": 0, "degraded": 0, "no_data": 0, "written": 0}
    for index, trading_date in enumerate(dates, 1):
        slots = sorted({
            str(row.get("slotTime"))
            for row in db["snapshot_frames"].find(
                {"datasetId": dataset_id, "type": HALF_HOUR, "tradingDate": trading_date})
            if row.get("slotTime")
        })
        if dry_run:
            print(f"[{index}/{len(dates)}] {trading_date} slots={slots}（dry-run 不调用不落库）")
            continue
        for slot in slots:
            result = compute_and_upsert_for_slot(
                db, dataset_id=dataset_id, trading_date=trading_date, slot_time=slot, origin="replay", force=True)
            counts[result.get("status", "unknown")] = counts.get(result.get("status", "unknown"), 0) + 1
            counts["written"] += int(result.get("written") or 0)
        day_result = compute_and_upsert_for_day(
            db, dataset_id=dataset_id, trading_date=trading_date, origin="replay", force=True)
        counts[day_result.get("status", "unknown")] = counts.get(day_result.get("status", "unknown"), 0) + 1
        counts["written"] += int(day_result.get("written") or 0)
        print(f"[{index}/{len(dates)}] {trading_date} slots={len(slots)} day={day_result.get('status')}")
    print("FINAL:", counts)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="jev 观察轨道最近 N 交易日回放")
    parser.add_argument("--days", type=int, default=3, help="最近 N 个交易日（默认 3）")
    parser.add_argument("--start", default=None, help="YYYY-MM-DD（与 --days 二选一优先）")
    parser.add_argument("--end", default=None, help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="只列窗口与槽位，不调用不落库")
    parser.add_argument("--dataset", default=DATASET_DEFAULT)
    args = parser.parse_args()
    raise SystemExit(run(days=args.days, dry_run=args.dry_run, start=args.start,
                         end=args.end, dataset_id=args.dataset))
