# -*- coding: utf-8 -*-
"""题材周期状态机全历史回填（P2，Q7:A 主算=重算龙一+对账台账）。

用法：python scripts/backfill_theme_cycle.py [--from 2026-05-06] [--to 2026-10-30]
幂等 upsert（hotlist_jev_theme_cycle 每板块×轨每日一文档）；升序重放，
状态跨日携带（进程内），断点后重跑建议 --from 回退几日（首日态取库中前一日）。
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.data.repositories.repository_factory import (  # noqa: E402
    get_runtime_mongodb_database)
from backend.operations.jev_label_jiuyan import trading_dates_before  # noqa: E402
from backend.operations.theme_cycle import (COLLECTION,  # noqa: E402
                                            build_and_save_theme_cycle)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="dfrom", default=None)
    ap.add_argument("--to", dest="dto", default=None)
    args = ap.parse_args()
    db = get_runtime_mongodb_database()

    dates = sorted({str(d.get("tradingDate"))
                    for d in db["jiuyan_action"].find(
                        {"_id": {"$regex": ":final$"}}, {"tradingDate": 1})
                    if d.get("tradingDate")})
    if args.dfrom:
        dates = [d for d in dates if d >= args.dfrom]
    if args.dto:
        dates = [d for d in dates if d <= args.dto]
    if not dates:
        print("无可回填交易日（韭研 final 缺失）")
        return 1
    print(f"theme_cycle 回填 {len(dates)} 交易日: {dates[0]}..{dates[-1]}")

    summary = build_and_save_theme_cycle(db, dates)
    print({
        "dates": summary["dates"], "rows": summary["rows"],
        "migrated": summary["migrated"],
        "gaps": len(summary["gaps"]),
    }, flush=True)
    for g in summary["gaps"][:20]:
        print("  gap:", g)
    n = Counter()
    for d in db[COLLECTION].find({}, {"state": 1}):
        n[d.get("state")] += 1
    print("state distribution:", dict(n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
