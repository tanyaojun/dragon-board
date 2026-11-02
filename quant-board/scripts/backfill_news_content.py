# -*- coding: utf-8 -*-
"""新题正文一次性回填（2026-11-02 正文预登记 §三.4）。

对近 N 日（默认 3）窗内缺 `contentHtml` 的 `kpl_theme_news` 条目逐条拉
`ThemeNews GetInfo NewsID=` 正文，走 `save_news_items` 同款合并（空不覆盖）。
确定性重放、零 jev token；调用计入 `kpl_api_calls` 当日预算（可 --budget 覆盖）。

用法：
  python -m scripts.backfill_news_content [--days 3] [--budget 40] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from backend.operations import kpl_theme_collect as C
from backend.operations import kpl_theme_fetch as F
from backend.operations import kpl_theme_store as S


def backfill(*, db: Any, days: int = 3, budget: int | None = None,
             dry_run: bool = False) -> dict:
    budget = C.daily_call_budget() if budget is None else int(budget)
    today = datetime.now().strftime("%Y-%m-%d")
    used = S.calls_recorded(db, today)
    # 目标条目：近 N 日 eventDate、缺 contentHtml（缺失/null/空串一次覆盖）
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    targets = list(db[S.COLLECTION_NEWS].find(
        {"eventDate": {"$gte": since, "$lte": today},
         "contentHtml": {"$in": [None, ""]}},
        {"cid": 1, "title": 1, "eventDate": 1}))

    result: dict[str, Any] = {"ok": True, "fetchDate": today, "since": since,
                              "targets": len(targets), "budget": budget,
                              "callsUsedToday": used, "filled": 0,
                              "skippedByBudget": False, "failures": []}
    for t in targets:
        if used >= budget:
            result["skippedByBudget"] = True
            result["failures"].append("预算耗尽，剩余条目未回填")
            break
        cid = str(t.get("cid") or "")
        if not cid:
            continue
        if dry_run:
            result["filled"] += 0
            continue
        time.sleep(C.INTER_CALL_DELAY_SECONDS)
        S.record_api_calls(db, today, ("news_detail_backfill",))
        used = S.calls_recorded(db, today)
        dres = F.fetch_news_detail(cid)
        if dres.get("ok") and (dres.get("detail") or {}).get("content"):
            S.save_news_items(db, fetch_date=today,
                              items=[{"cid": cid, "title": t.get("title") or "",
                                      "kword": "", "zsName": "", "source": "",
                                      "eventDate": t.get("eventDate") or "",
                                      "timeStamp": None, "stocks": []}],
                              details={cid: dres["detail"]})
            result["filled"] += 1
        else:
            result["failures"].append(f"{cid}: {dres.get('error') or '空详情'}")
    result["callsUsedTodayAfter"] = S.calls_recorded(db, today)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--budget", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    stats = backfill(db=get_runtime_mongodb_database(), days=args.days,
                     budget=args.budget, dry_run=args.dry_run)
    print("NEWS_BACKFILL_RESULT_JSON:" + json.dumps(stats, ensure_ascii=False))
    sys.exit(0 if stats.get("ok") else 1)


if __name__ == "__main__":
    main()
