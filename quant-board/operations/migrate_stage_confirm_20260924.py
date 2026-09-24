"""阶段多帧确认上线迁移：按 snapshot_frames 槽位升序全量重算 hotlist_sentiment（2026-09-24）。

- 目标槽来自 snapshot_frames（不是枚举现有 hotlist_sentiment——缺失槽必须补齐）；
- 每个交易日按 slotTime 升序 compute_and_upsert_for_slot，最后 recompute EOD（自动备份）；
- 写入前记录日期/槽位数；单槽失败记录错误并继续，完成后输出失败清单；
- 重算不删除任何文档；可随时用 HOTLIST_STAGE_CONFIRM_SLOTS=1 观察回退。
"""
from __future__ import annotations

import time

from pymongo import MongoClient

from backend.operations.hotlist_sentiment import HotListSentimentBackfillService
from backend.services.theme.hotlist_sentiment_compute import (
    HotListSentimentComputeService,
    compute_and_upsert_for_slot,
)


def main() -> None:
    client = MongoClient("mongodb://127.0.0.1:27017/")
    db = client["dragon_board_quant"]
    svc = HotListSentimentBackfillService(db)
    compute = HotListSentimentComputeService(db)

    dates = svc.trading_dates(dataset_id="dragonboard_live", snapshot_type="half_hour")
    print(f"migrate days={len(dates)}", flush=True)
    failures: list[str] = []
    total_slots = 0

    for day_index, date in enumerate(dates, 1):
        # 目标槽来自 snapshot_frames（升序），缺失槽由此补齐
        slot_times = sorted(str(s) for s in svc._slot_times_of_date("dragonboard_live", "half_hour", date))
        written = 0
        for slot in slot_times:
            try:
                result = compute_and_upsert_for_slot(
                    db, dataset_id="dragonboard_live", snapshot_type="half_hour",
                    trading_date=date, slot_time=slot,
                )
                if result.get("written"):
                    written += 1
                else:
                    failures.append(f"{date} {slot}: {result.get('reason')}")
            except Exception as exc:
                failures.append(f"{date} {slot}: error {exc}")
            time.sleep(0.05)
        total_slots += written
        try:
            eod = compute.recompute("dragonboard_live", "half_hour", date, persist=True)
            eod_note = "ok" if eod.get("applied") else "not-applied"
        except Exception as exc:
            eod_note = f"error {exc}"
            failures.append(f"{date} EOD: {exc}")
        print(f"[{day_index}/{len(dates)}] {date} slots={written}/{len(slot_times)} eod={eod_note}", flush=True)

    print(f"done. slots_written={total_slots} failures={len(failures)}", flush=True)
    for line in failures[:50]:
        print("FAIL:", line, flush=True)


if __name__ == "__main__":
    main()
