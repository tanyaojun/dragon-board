# -*- coding: utf-8 -*-
"""T5 历史重算 + 新旧档位 diff（路线 B，emotion-score-design v3 §5.3）。

流程（幂等，可重复执行）：
1. 重算前先采集全部现有文档的 stage/rawStage（旧级联口径真实输出——比 confirm_stage
   重放重建更精确的对照基线，审计 S8 的强化版）；
2. 逐交易日调 HotListSentimentBackfillService.run_for_date_slots（T3 已接线评分 evidence
   parts，每槽 + 收尾 EOD；legacyCascadeStage 一并重算写入——回退可执行前提，审计 S7）；
3. 新旧逐槽对照：一致率、5×5 迁移矩阵、分歧分布、每日一致率（典型分歧日定位）。

只写 hotlist_sentiment（重算本义）；dry-run 全程不写。旧档位快照与 diff 明细随 --json 落盘。
用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.emotion_score_recompute --dry-run
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.emotion_score_recompute \
      [--start-date 2026-04-15] [--end-date 2026-09-30] [--json .tmp/emotion-score-recompute.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any

_STAGES = ("冰点", "启动", "发酵", "高潮", "退潮")


def _snapshot_old_stages(db: Any, dataset_id: str, snapshot_type: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in db["hotlist_sentiment"].find(
        {"datasetId": dataset_id, "snapshotType": snapshot_type},
        {"tradingDate": 1, "slotTime": 1, "stage": 1, "rawStage": 1},
    ):
        key = str(row.get("_id") or "")
        if not key:
            continue
        out[key] = {
            "tradingDate": str(row.get("tradingDate") or ""),
            "slotTime": str(row.get("slotTime") or ""),
            "stage": row.get("stage"),
            "rawStage": row.get("rawStage"),
        }
    return out


def _snapshot_new_stages(db: Any, dataset_id: str, snapshot_type: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in db["hotlist_sentiment"].find(
        {"datasetId": dataset_id, "snapshotType": snapshot_type},
        {"tradingDate": 1, "slotTime": 1, "stage": 1, "rawStage": 1,
         "legacyCascadeStage": 1, "emotionScore.score": 1},
    ):
        key = str(row.get("_id") or "")
        if not key:
            continue
        score = (row.get("emotionScore") or {}).get("score")
        out[key] = {
            "tradingDate": str(row.get("tradingDate") or ""),
            "slotTime": str(row.get("slotTime") or ""),
            "stage": row.get("stage"),
            "rawStage": row.get("rawStage"),
            "legacyCascadeStage": row.get("legacyCascadeStage"),
            "score": score if isinstance(score, (int, float)) else None,
        }
    return out


def summarize(old: dict[str, dict], new: dict[str, dict]) -> dict[str, Any]:
    common = [key for key in new if key in old]
    slot_keys = [key for key in common if old[key]["slotTime"] != "EOD"]
    eod_keys = [key for key in common if old[key]["slotTime"] == "EOD"]

    def _pair_stats(keys: list[str]) -> dict[str, Any]:
        same = sum(1 for key in keys if old[key]["stage"] == new[key]["stage"])
        raw_same = sum(
            1 for key in keys
            if (old[key]["rawStage"] or None) == (new[key]["rawStage"] or None))
        matrix: Counter = Counter()
        for key in keys:
            matrix[(old[key]["stage"], new[key]["stage"])] += 1
        return {
            "n": len(keys),
            "stageSame": same,
            "stageSameRate": round(same / len(keys), 4) if keys else None,
            "rawStageSame": raw_same,
            "rawStageSameRate": round(raw_same / len(keys), 4) if keys else None,
            "matrix": {f"{o}->{n_}": c for (o, n_), c in matrix.most_common()},
        }

    daily: dict[str, dict[str, int]] = {}
    for key in slot_keys:
        date = old[key]["tradingDate"]
        bucket = daily.setdefault(date, {"n": 0, "same": 0})
        bucket["n"] += 1
        bucket["same"] += 1 if old[key]["stage"] == new[key]["stage"] else 0
    new_stage_counts = Counter(new[key]["stage"] for key in slot_keys)
    old_stage_counts = Counter(old[key]["stage"] for key in slot_keys)
    return {
        "slotDocs": _pair_stats(slot_keys),
        "eodDocs": _pair_stats(eod_keys),
        "oldStageCounts": dict(old_stage_counts.most_common()),
        "newStageCounts": dict(new_stage_counts.most_common()),
        "dailyConsistency": {
            date: {"rate": round(v["same"] / v["n"], 3), "same": v["same"], "n": v["n"]}
            for date, v in sorted(daily.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="路线 B 历史重算 + 新旧档位 diff")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--snapshot-type", default="half_hour")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--dry-run", action="store_true", help="只重算不写库（仍产出 diff）")
    parser.add_argument("--json", default=None, help="diff 明细 JSON 输出路径")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = get_runtime_mongodb_database()
    service = HotListSentimentBackfillService(db)
    dates = [
        date for date in service.trading_dates(dataset_id=args.dataset, snapshot_type=args.snapshot_type)
        if (not args.start_date or date >= args.start_date)
        and (not args.end_date or date <= args.end_date)
    ]
    if not dates:
        print({"error": "no trading dates in range"}, file=sys.stderr)
        return 1

    print(f"[recompute] snapshot old stages ...", file=sys.stderr)
    old = _snapshot_old_stages(db, args.dataset, args.snapshot_type)

    written_total = 0
    slot_error_total = 0
    for index, date in enumerate(dates):
        result = service.run_for_date_slots(
            dataset_id=args.dataset, snapshot_type=args.snapshot_type, trading_date=date,
            dry_run=args.dry_run,
        )
        written_total += int(result.get("written") or 0) + (1 if result.get("eodWritten") else 0)
        slot_error_total += len(result.get("slotErrors") or [])
        if result.get("slotErrors"):
            print(f"[recompute] {date}: {len(result['slotErrors'])} slotErrors", file=sys.stderr)
        print(f"[recompute] {index + 1}/{len(dates)} {date} done", file=sys.stderr)

    print(f"[recompute] snapshot new stages ...", file=sys.stderr)
    new = _snapshot_new_stages(db, args.dataset, args.snapshot_type)
    summary = summarize(old, new)
    summary["meta"] = {
        "dryRun": args.dry_run,
        "dates": len(dates),
        "writtenTotal": written_total,
        "slotErrorTotal": slot_error_total,
    }
    if args.json:
        details = [
            {"_id": key, **old[key], "newStage": new[key]["stage"], "newRawStage": new[key]["rawStage"],
             "legacyCascadeStage": new[key].get("legacyCascadeStage"), "score": new[key].get("score")}
            for key in sorted(new) if key in old
            and (old[key]["stage"] != new[key]["stage"] or old[key]["rawStage"] != new[key]["rawStage"])
        ]
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary, "differingDocs": details}, fh, ensure_ascii=False, indent=1)
        print(f"[recompute] json -> {args.json}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
