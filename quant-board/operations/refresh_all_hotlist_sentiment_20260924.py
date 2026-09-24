"""一次性批量刷新 hotlist_sentiment half_hour 文档（2026-09-24 口径统一修复后）。

对全部 half_hour 交易日执行：
- EOD 文档：HotListSentimentComputeService.recompute（旧文档自动备份到
  hotlist_sentiment_recompute_backup，幂等 upsert，失效 series 读口缓存）
- 槽位文档：compute_and_upsert_for_slot 逐槽重算

daily 类型 21 个文档无对应快照帧（历史迁移产物），不在刷新范围。
跑法：cd quant-board && ./.venv/Scripts/python.exe operations/refresh_all_hotlist_sentiment_20260924.py
"""
from __future__ import annotations

import time

from pymongo import MongoClient

from backend.services.theme.hotlist_sentiment_compute import (
    HotListSentimentComputeService,
    compute_and_upsert_for_slot,
)


def main() -> None:
    client = MongoClient("mongodb://127.0.0.1:27017/")
    db = client["dragon_board_quant"]
    svc = HotListSentimentComputeService(db)

    docs = list(db["hotlist_sentiment"].find({"_id": {"$regex": "^dragonboard_live:half_hour:"}}, {"_id": 1}))
    eod_dates: list[str] = []
    slot_jobs: list[tuple[str, str]] = []
    for d in docs:
        parts = str(d["_id"]).split(":")
        # dragonboard_live : half_hour : DATE [: SLOT]
        if len(parts) >= 4:
            slot_jobs.append((parts[2], parts[3]))
        else:
            eod_dates.append(parts[2])
    eod_dates = sorted(set(eod_dates))
    print(f"refresh half_hour EOD days={len(eod_dates)} slots={len(slot_jobs)}", flush=True)

    failed: list[str] = []
    for i, date in enumerate(eod_dates, 1):
        try:
            r = svc.recompute("dragonboard_live", "half_hour", date, persist=True)
            after = r.get("after") or {}
            print(f"[EOD {i}/{len(eod_dates)}] {date} applied={r['applied']} counts={after.get('stageCounts')}", flush=True)
        except Exception as exc:
            failed.append(f"EOD {date}: {exc}")
            print(f"[EOD {i}/{len(eod_dates)}] {date} FAILED: {exc}", flush=True)
        time.sleep(0.2)

    for i, (date, slot) in enumerate(sorted(slot_jobs), 1):
        try:
            r = compute_and_upsert_for_slot(
                db, dataset_id="dragonboard_live", snapshot_type="half_hour",
                trading_date=date, slot_time=slot,
            )
            if not r.get("written"):
                # 无帧/无行等历史缺失：原样保留旧文档，不算失败，如实记录
                print(f"[SLOT {i}/{len(slot_jobs)}] {date} {slot} skipped: {r.get('reason')}", flush=True)
            if i % 20 == 0 or i == len(slot_jobs):
                print(f"[SLOT {i}/{len(slot_jobs)}] progress", flush=True)
        except Exception as exc:
            failed.append(f"SLOT {date} {slot}: {exc}")
            print(f"[SLOT {i}/{len(slot_jobs)}] {date} {slot} FAILED: {exc}", flush=True)
        time.sleep(0.1)

    print(f"done. failed={len(failed)}", flush=True)
    for f in failed:
        print("FAIL:", f, flush=True)


if __name__ == "__main__":
    main()
