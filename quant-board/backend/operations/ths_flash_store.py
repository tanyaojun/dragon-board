# -*- coding: utf-8 -*-
"""同花顺 7×24 快讯存储层（集合 `ths_flash` + 计数 `ths_api_calls`；2026-11-14 盘前催化
增量 C，只供 09:26 竞价链晨间窗消费）。

单主链：只在 MongoDB `dragon_board_quant`；`ths_flash` 文档 `_id={ctimeDate}:{id}`
（ctimeDate=快讯发布日，跨日重采天然去重），firstSeenAt 首见不覆盖、正文不可变。
fail-visible：计数/读写异常向上抛（不吞）；窗口查询缺字段容错。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

COLLECTION_FLASH = "ths_flash"
COLLECTION_META = "ths_flash_meta"
COLLECTION_API_CALLS = "ths_api_calls"
# 消费窗口：[T−1 日历日 15:00, 当日 09:26)（09:26=竞价投喂截止， baked 进读口防回放前视；
# T−1 取上一日历日而非上一交易日——周一窗口自然覆盖周末快讯，多覆盖无害）。
FLASH_WINDOW_START_HOUR = 15
FLASH_FEED_END = (9, 26)
_TZ = timezone(timedelta(hours=8))


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def record_api_calls(db: Any, fetch_date: str, n: int = 1) -> int:
    """累加当日 THS 端点调用计数（`$inc` 语义；失败请求同样计数）。返回累加后总数。"""
    db[COLLECTION_API_CALLS].update_one(
        {"_id": fetch_date},
        {"$inc": {"calls": int(n)}, "$set": {"lastCallAt": _now()}},
        upsert=True,
    )
    return calls_recorded(db, fetch_date)


def calls_recorded(db: Any, fetch_date: str) -> int:
    doc = db[COLLECTION_API_CALLS].find_one({"_id": fetch_date}, {"calls": 1}) or {}
    try:
        return int(doc.get("calls") or 0)
    except (TypeError, ValueError):
        return 0


def flash_window_epochs(date: str) -> tuple[int, int]:
    """`date` 的消费窗口 [T−1 15:00, 当日 09:26) 的 epoch 秒（显式 UTC+8，不依赖机器时区）。"""
    d = datetime.strptime(str(date), "%Y-%m-%d")
    start = (d - timedelta(days=1)).replace(
        hour=FLASH_WINDOW_START_HOUR, minute=0, second=0, tzinfo=_TZ).timestamp()
    end = d.replace(hour=FLASH_FEED_END[0], minute=FLASH_FEED_END[1], second=0,
                    tzinfo=_TZ).timestamp()
    return int(start), int(end)


def save_flash_items(db: Any, *, fetch_date: str, items: list[dict]) -> dict:
    """幂等 upsert（首见不覆盖）；返回 {written, skippedExisting}。"""
    written = skipped = 0
    for it in items or []:
        _id = f"{it.get('ctimeDate')}:{it.get('id')}"
        if not it.get("id") or not it.get("ctimeDate"):
            continue
        existing = db[COLLECTION_FLASH].find_one({"_id": _id}, {"firstSeenAt": 1}) or {}
        if existing:
            skipped += 1
            continue
        doc = {**it, "_id": _id, "kind": "ths_flash",
               "firstSeenAt": _now(), "firstSeenDate": fetch_date}
        db[COLLECTION_FLASH].replace_one({"_id": _id}, doc, upsert=True)
        written += 1
    return {"written": written, "skippedExisting": skipped}


def get_flash_window(db: Any, *, start_epoch: int, end_epoch: int,
                     limit: int = 60) -> list[dict]:
    """读半开窗口 [start, end) 内快讯（ctimeEpoch 降序，python 侧排序兼容 fake 库）。

    `end` 为当日 09:26:00 epoch：恰 09:26:00 发布的条目不进晨间窗（与预登记
    C2 半开区间合同一致，评审修复 P2）。"""
    rows = list(db[COLLECTION_FLASH].find({"ctimeEpoch": {"$gte": int(start_epoch),
                                                          "$lt": int(end_epoch)}}))
    rows.sort(key=lambda d: d.get("ctimeEpoch") or 0, reverse=True)
    return rows[:limit]


def save_meta(db: Any, *, fetch_date: str, state: str, pages: int, written: int,
              oldest_ctime: int | None, error: str | None = None) -> dict:
    """当日采集覆盖档（`_id={fetchDate}`）：state ok=已到窗口起点/页尽，failed=页失败。"""
    doc = {"_id": fetch_date, "kind": "ths_flash_meta", "date": fetch_date,
           "state": state, "pages": pages, "written": written,
           "oldestCtime": oldest_ctime, "fetchedAt": _now()}
    if error:
        doc["error"] = error[:200]
    db[COLLECTION_META].replace_one({"_id": fetch_date}, doc, upsert=True)
    return doc


def get_meta(db: Any, *, date: str) -> dict | None:
    return db[COLLECTION_META].find_one({"_id": date})
