# -*- coding: utf-8 -*-
"""月度重校准落地驱动：全量（或区间）按日×槽位时序重算 hotlist_sentiment。

顺序硬约束：每个交易日内先按槽位时序重算全部槽位文档（compute_and_upsert_for_slot，
读库源真重算），再重算 EOD 文档（recompute，内置备份集合 + 读口缓存失效）——
EOD 的确认轨迹/斜率读取槽位文档 stored stage/score，乱序会代际混用。

用途：月度重校准落地（预登记六门全过 + 用户裁决后）、消除历史 fallback 口径。
默认 dry-run；--apply 写库。用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.emotion_score_full_recompute \
      [--start 2026-07-14] [--end 2026-10-08] [--date 2026-10-08] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.data.repositories import repository_factory
from backend.operations.hotlist_sentiment import HotListSentimentBackfillService
from backend.services.theme.hotlist_sentiment_compute import (
    HotListSentimentComputeService,
    compute_and_upsert_for_slot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="月度重校准落地驱动（默认 dry-run）")
    parser.add_argument("--dataset-id", default="dragonboard_live")
    parser.add_argument("--snapshot-type", default="half_hour")
    parser.add_argument("--date", default=None, help="单日重算（YYYY-MM-DD）")
    parser.add_argument("--start", default=None, help="起始交易日（含）")
    parser.add_argument("--end", default=None, help="结束交易日（含）")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    db = repository_factory.get_runtime_mongodb_database()
    backfill = HotListSentimentBackfillService(db)
    service = HotListSentimentComputeService(db)
    dates = backfill.trading_dates(dataset_id=args.dataset_id, snapshot_type=args.snapshot_type)
    if args.date:
        targets = [args.date]
    else:
        targets = [d for d in dates
                   if (args.start is None or d >= args.start)
                   and (args.end is None or d <= args.end)]
    print(json.dumps({"days": len(targets), "apply": args.apply,
                      "range": [targets[0], targets[-1]] if targets else []},
                     ensure_ascii=False))

    rows: list[dict] = []
    t0 = time.time()
    for i, dt in enumerate(targets):
        eod_doc = db["hotlist_sentiment"].find_one(
            {"_id": f"{args.dataset_id}:{args.snapshot_type}:{dt}"})
        es = ((eod_doc or {}).get("emotionScore") or {})
        old_score = es.get("score")
        old_stage = (eod_doc or {}).get("stage")
        slots = sorted(
            (str(r["slotTime"]) for r in db["hotlist_sentiment"].find(
                {"datasetId": args.dataset_id, "snapshotType": args.snapshot_type,
                 "tradingDate": dt, "slotTime": {"$ne": "EOD"}})),
        )
        for slot in slots:
            if args.apply:
                compute_and_upsert_for_slot(
                    db, dataset_id=args.dataset_id, snapshot_type=args.snapshot_type,
                    trading_date=dt, slot_time=slot)
        result = service.recompute(args.dataset_id, args.snapshot_type, dt,
                                   persist=bool(args.apply)) if args.apply else None
        new_doc = db["hotlist_sentiment"].find_one(
            {"_id": f"{args.dataset_id}:{args.snapshot_type}:{dt}"}) if args.apply else None
        new_score = (((new_doc or {}).get("emotionScore") or {}).get("score")) if args.apply else None
        new_stage = (new_doc or {}).get("stage") if args.apply else None
        rows.append({"date": dt, "slots": len(slots), "oldScore": old_score,
                     "newScore": new_score, "oldStage": old_stage, "newStage": new_stage,
                     "recomputed": result is not None})
        # 逐日一行进度（review P3：断点可核对——中断后已重算到哪天一眼可见）
        print(json.dumps({"day": f"{i + 1}/{len(targets)}", "date": dt,
                          "slots": len(slots), "score": [old_score, new_score],
                          "stage": [old_stage, new_stage],
                          "elapsed": round(time.time() - t0, 1)}, ensure_ascii=False), flush=True)

    if args.apply:
        migration = [{"date": r["date"], "old": r["oldStage"], "new": r["newStage"]}
                     for r in rows if r["oldStage"] and r["newStage"]
                     and r["oldStage"] != r["newStage"]]
        scores = [r for r in rows if isinstance(r["oldScore"], (int, float))
                  and isinstance(r["newScore"], (int, float))]
        mean_delta = (round(sum(r["newScore"] - r["oldScore"] for r in scores) / len(scores), 2)
                      if scores else None)
        summary = {"days": len(rows),
                   "slots": sum(r["slots"] for r in rows),
                   "stageMigration": migration,
                   "meanDelta": mean_delta}
        Path(".tmp").mkdir(exist_ok=True)
        Path(".tmp/emotion-score-full-recompute-result.json").write_text(
            json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
