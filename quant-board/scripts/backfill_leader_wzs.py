# -*- coding: utf-8 -*-
"""题材周期·龙头弱转强 P1 历史回填（v5 预登记，2026-11-01）。

逐交易日构建 `hotlist_jev_leader_wzs` 观察池/事件流文档（upsert 幂等，重跑可回放）。
深历史用覆盖式日线（bars_covering 渐进 offset）；gain10 同理注入覆盖式 fetcher。

用法：
  python scripts/backfill_leader_wzs.py [--from 2026-09-01] [--to 2026-10-31] [--force]

写库边界：生产集合 hotlist_jev_leader_wzs ∈ dragon_board_quant（运行链单主）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.jev_label_jiuyan import trading_dates_before
from backend.operations.leader_wzs import (COLLECTION,
                                           build_and_save_leader_wzs)
from backend.operations.tdx_daily_bars import fetch_daily_bars, gain10_from_bars

# 单档大 offset：260 根日线 ≈ 覆盖一年（回填窗 118 交易日 + 11 根 gain10 基线）。
# 一次拉取进程内缓存 (code, offset) 复用，避免阶梯式逐档重试（每档一次 TDX 连接）。
_BAR_OFFSET = 260


def _bars(code: str, _date: str):
    return fetch_daily_bars(code, offset=_BAR_OFFSET)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="date_from", default=None)
    ap.add_argument("--to", dest="date_to", default=None)
    ap.add_argument("--force", action="store_true", help="覆盖已有文档重算")
    ap.add_argument("--refresh", action="store_true", help="重算已有文档（缺省跳过，可断点续跑）")
    args = ap.parse_args()

    db = get_runtime_mongodb_database()
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "_id": {"$regex": ":final$"}}, {"tradingDate": 1})
        if d.get("tradingDate")})
    if args.date_from:
        dates = [d for d in dates if d >= args.date_from]
    if args.date_to:
        dates = [d for d in dates if d <= args.date_to]
    if not dates:
        print("no trading dates in range", file=sys.stderr)
        return 1
    print(f"backfill {len(dates)} trading days: {dates[0]}..{dates[-1]}")

    def _gain(codes, end):
        # 单档大 offset：与 _bars 同一 (code, offset) 缓存，每只股全程只拉一次
        return {c: gain10_from_bars(fetch_daily_bars(c, offset=_BAR_OFFSET), end)
                for c in codes}

    def _day_change(codes, day):
        out = {}
        for c in codes:
            bars = fetch_daily_bars(c, offset=_BAR_OFFSET)
            out[c] = None
            if bars and day in bars:
                ds = sorted(bars)
                i = ds.index(day)
                if i:
                    pc, cc = bars[ds[i - 1]].get("close"), bars[day].get("close")
                    if pc and cc:
                        out[c] = round((cc / pc - 1) * 100, 2)
        return out

    status_n: Counter[str] = Counter()
    event_n: Counter[str] = Counter()
    pool_n = 0
    degraded: list[str] = []
    for d in dates:
        if not args.refresh and not args.force \
                and db[COLLECTION].find_one({"_id": d}, {"_id": 1}):
            status_n["skipped"] += 1
            continue
        doc = build_and_save_leader_wzs(db, d, gain_fetcher=_gain,
                                        day_change_fetcher=_day_change,
                                        bars_fetcher=_bars,
                                        force=args.force)
        status_n[doc["status"]] += 1
        if doc["status"] == "degraded":
            degraded.append(f"{d}: {doc['meta'].get('reason')}")
            print(f"[backfill] {d} degraded: {doc['meta'].get('reason')}", flush=True)
            continue
        pool_n += len(doc["poolRows"])
        for e in doc["events"]:
            event_n[e["type"]] += 1
        print(f"[backfill] {d} ok pool={len(doc['poolRows'])} "
              f"events={len(doc['events'])} done={sum(status_n.values())}/{len(dates)}",
              flush=True)
    summary = {"days": len(dates), "status": dict(status_n), "poolRows": pool_n,
               "events": dict(event_n), "degraded": degraded}
    print(json.dumps({k: v for k, v in summary.items() if k != "degraded"},
                     ensure_ascii=False, indent=2))
    if degraded:
        print(f"degraded days ({len(degraded)}):", file=sys.stderr)
        for line in degraded:
            print(" ", line, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
