# -*- coding: utf-8 -*-
"""存量 jev 槽位文档补 `answers.temperature.percentile`（2026-10-14）。

背景：该字段自 relay_page「分位」列上线起就没有生产者——后端从未写过，前端却按
0-1 小数读，历史 0% 覆盖，列子结构性恒空。口径经用户裁决定为「近 20 个交易日的
EOD 日级温度」（见 services/jev/jev_sentiment_compute.temperature_percentile）。

本脚本是**纯数据补丁，零 jev 模型调用**：只读 scores.temperature + 库内 EOD 历史，
算分位后 `$set` 嵌套路径。不 replace_one 全量重建（避免冲掉锚告警等旁路字段，
10-05 v2.5 重跑冲掉回填值的教训）。未来槽位由 compute_and_upsert_for_slot 自动带出，
本脚本只补历史。

fail-visible：样本 <10 的文档不写字段（如实留空，不补 0），计数进 summary.thinSample。

用法（默认 dry-run 只报数不写库）：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.jev_temperature_percentile_backfill \
      [--start 2026-09-01] [--end 2026-10-13] [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.data.repositories import repository_factory
from backend.services.jev.jev_sentiment_compute import temperature_percentile

COLLECTION = "hotlist_jev_sentiment"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="存量 jev 槽位文档补 temperature.percentile（默认 dry-run）")
    parser.add_argument("--start", default=None, help="起始交易日（含，YYYY-MM-DD）")
    parser.add_argument("--end", default=None, help="结束交易日（含，YYYY-MM-DD）")
    parser.add_argument("--apply", action="store_true", help="写库（缺省只报数）")
    args = parser.parse_args()

    db = repository_factory.get_runtime_mongodb_database()
    col = db[COLLECTION]
    query: dict = {"kind": "slot", "status": "ok"}
    if args.start or args.end:
        query["tradingDate"] = {}
        if args.start:
            query["tradingDate"]["$gte"] = args.start
        if args.end:
            query["tradingDate"]["$lte"] = args.end

    docs = list(col.find(query, {"datasetId": 1, "snapshotType": 1, "tradingDate": 1,
                                 "slotTime": 1, "scores": 1, "answers": 1}))
    written = unchanged = skipped = thin = 0
    thin_dates: dict[str, int] = {}
    t0 = time.time()
    for i, doc in enumerate(docs):
        date = str(doc.get("tradingDate") or "")
        answers = doc.get("answers") or {}
        temp_answer = answers.get("temperature")
        current = (doc.get("scores") or {}).get("temperature")
        if not isinstance(temp_answer, dict) or not isinstance(current, (int, float)):
            skipped += 1  # 无 temperature 题/无还原分数：无从算起，字段保持缺席
            continue
        percentile, samples = temperature_percentile(
            db, dataset_id=str(doc.get("datasetId") or "dragonboard_live"),
            trading_date=date, current=current)
        if percentile is None:
            thin += 1
            thin_dates[f"{samples}样本"] = thin_dates.get(f"{samples}样本", 0) + 1
            continue
        prior = temp_answer.get("percentile")
        if isinstance(prior, (int, float)) and abs(float(prior) - percentile) < 1e-9:
            unchanged += 1
            continue
        if args.apply:
            # 嵌套路径 $set：只落这一个派生字段，不动文档其余部分
            col.update_one({"_id": doc["_id"]},
                           {"$set": {"answers.temperature.percentile": percentile}})
        written += 1
        if (i + 1) % 200 == 0:
            print(json.dumps({"progress": f"{i + 1}/{len(docs)}", "written": written,
                              "elapsed": round(time.time() - t0, 1)},
                             ensure_ascii=False), flush=True)

    summary = {"apply": args.apply, "scanned": len(docs), "written": written,
               "alreadyCorrect": unchanged, "noTemperature": skipped,
               "thinSample": thin, "thinSampleBreakdown": thin_dates,
               "elapsedSec": round(time.time() - t0, 1)}
    print(json.dumps(summary, ensure_ascii=False))
    if not args.apply:
        print("dry-run：未写库。确认上述 written 数后加 --apply 落地。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
