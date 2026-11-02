# -*- coding: utf-8 -*-
"""开盘啦题材语料存储层（集合 `kpl_topic_events` / `kpl_theme_news` / `kpl_theme_calendar`，
2026-10-23 v4 换源）。

单主链：只在 MongoDB `dragon_board_quant`；幂等 upsert（`firstSeenAt` 不覆盖）；
入站空载荷不得覆盖已采证据（§4.0，同 `jiuyan_theme_store` 口径）。

- `kpl_topic_events`：题材事件池。_id="{day}:{eventId}"；day(事件日)/title/content(详情全文)/
  source/hotVal/num/isVote/eventTime/detailFetched。
- `kpl_theme_news`：题材新闻流。_id="news:{CID}"；kword(题材标签)/eventDate/timeStamp/
  stocks[{code,name,rate,setTop}]。
- `kpl_theme_calendar`：前瞻日历。_id="cal:{PID}"；date/tagName/brief/stocks。
- `kpl_api_calls`：调用计数（`_id={fetchDate}`，`calls.{source}=n`，失败同样计数）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

COLLECTION_TOPIC = "kpl_topic_events"
COLLECTION_NEWS = "kpl_theme_news"
COLLECTION_CALENDAR = "kpl_theme_calendar"
COLLECTION_API_CALLS = "kpl_api_calls"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def record_api_calls(db: Any, fetch_date: str, sources: tuple[str, ...]) -> dict:
    """累加当日 KPL 端点调用计数（`$inc` 幂等；失败请求同样计数）。"""
    if sources:
        db[COLLECTION_API_CALLS].update_one(
            {"_id": fetch_date},
            {"$inc": {**{f"calls.{s}": 1 for s in sources}}, "$set": {"lastCallAt": _now()}},
            upsert=True,
        )
    return calls_recorded(db, fetch_date)


def calls_recorded(db: Any, fetch_date: str) -> int:
    doc = db[COLLECTION_API_CALLS].find_one({"_id": fetch_date}, {"calls": 1}) or {}
    return sum(int(v or 0) for v in (doc.get("calls") or {}).values())


def _base_doc(existing: dict | None, fetch_date: str) -> dict:
    return {
        "firstSeenAt": (existing or {}).get("firstSeenAt") or _now(),
        "firstSeenDate": (existing or {}).get("firstSeenDate") or fetch_date,
        "lastFetchDate": fetch_date,
        "updatedAt": _now(),
    }


def save_topic_events(db: Any, *, fetch_date: str, events: list[dict],
                      details: dict[str, dict] | None = None) -> dict:
    """题材事件池幂等 upsert。`details` = 本次新拉的详情（eventId → detail）。"""
    written = detail_fetched = 0
    for ev in events:
        eid, day = str(ev.get("eventId") or ""), str(ev.get("day") or "")
        if not eid or not day:
            continue
        _id = f"{day}:{eid}"
        existing = db[COLLECTION_TOPIC].find_one(
            {"_id": _id}, {"firstSeenAt": 1, "firstSeenDate": 1, "content": 1, "source": 1,
                           "title": 1, "num": 1, "eventTime": 1}) or {}
        detail = (details or {}).get(eid) or {}
        # 详情只在缺失时补：已有全文不重拉（省调用），已有正文不被空详情覆盖（§4.0）；
        # num/eventTime 同理——重采（列表窗内再次出现）不得抹掉首轮详情（review 2026-10-23）
        content = detail.get("content") or existing.get("content") or ""
        num = detail.get("num") if detail.get("num") is not None else existing.get("num")
        doc = {
            "_id": _id, "kind": "kpl_topic_event", "eventId": eid, "day": day,
            "title": ev.get("title") or detail.get("title") or existing.get("title") or "",
            "content": content,
            "source": detail.get("source") or existing.get("source") or "",
            "hotVal": ev.get("hotVal"), "num": num,
            "isVote": ev.get("isVote"),
            "eventTime": detail.get("time") or existing.get("eventTime"),
            "detailFetched": bool(content),
            **_base_doc(existing, fetch_date),
        }
        db[COLLECTION_TOPIC].replace_one({"_id": _id}, doc, upsert=True)
        written += 1
        if detail.get("content"):
            detail_fetched += 1
    return {"written": written, "detailFetched": detail_fetched}


def save_news_items(db: Any, *, fetch_date: str, items: list[dict],
                    details: dict[str, dict] | None = None) -> dict:
    """news 流落库；`details`（2026-11-02 预登记 §三）为 cid→详情正文映射，
    空详情不覆盖已存内容（同事件详情惯例）。"""
    written = 0
    details_merged = 0
    for it in items:
        cid = str(it.get("cid") or "")
        if not cid:
            continue
        _id = f"news:{cid}"
        existing = db[COLLECTION_NEWS].find_one(
            {"_id": _id},
            {"firstSeenAt": 1, "firstSeenDate": 1, "contentHtml": 1,
             "kwordDesc": 1, "zsCode": 1, "isChoice": 1}) or {}
        det = (details or {}).get(cid) or {}
        doc = {
            "_id": _id, "kind": "kpl_theme_news", "cid": cid,
            "title": it.get("title") or "", "kword": it.get("kword") or "",
            # 2026-11-02 用户裁决①：KPL 官方板块归属（确定性板块↔新闻链接第二通道）
            "zsName": it.get("zsName") or "",
            "source": it.get("source") or "", "eventDate": it.get("eventDate") or "",
            "timeStamp": it.get("timeStamp"), "stocks": it.get("stocks") or [],
            # 2026-11-02 预登记 §三：正文原文（HTML 单主链，消费端剥标签）；只存不用字段
            "contentHtml": str(det.get("content") or "") or existing.get("contentHtml") or "",
            "kwordDesc": det.get("kwordDesc") or existing.get("kwordDesc") or "",
            "zsCode": det.get("zsCode") or existing.get("zsCode") or "",
            "isChoice": det.get("isChoice", existing.get("isChoice")),
            **_base_doc(existing, fetch_date),
        }
        if det.get("content") and not existing.get("contentHtml"):
            details_merged += 1
        db[COLLECTION_NEWS].replace_one({"_id": _id}, doc, upsert=True)
        written += 1
    return {"written": written, "newDetails": details_merged}


def save_calendar_items(db: Any, *, fetch_date: str, items: list[dict]) -> dict:
    written = 0
    for it in items:
        pid = str(it.get("pid") or "")
        if not pid or not it.get("date"):
            continue
        _id = f"cal:{pid}"
        existing = db[COLLECTION_CALENDAR].find_one({"_id": _id}, {"firstSeenAt": 1, "firstSeenDate": 1}) or {}
        doc = {
            "_id": _id, "kind": "kpl_theme_calendar", "pid": pid,
            "brief": it.get("brief") or "", "date": it.get("date") or "",
            "tagName": it.get("tagName") or "", "stocks": it.get("stocks") or [],
            **_base_doc(existing, fetch_date),
        }
        db[COLLECTION_CALENDAR].replace_one({"_id": _id}, doc, upsert=True)
        written += 1
    return {"written": written}


def _shift(date: str, days: int) -> str | None:
    try:
        return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _window(date: str, include_past_recent: int, window_days: int) -> dict:
    lo = _shift(date, -abs(int(include_past_recent)))
    hi = _shift(date, abs(int(window_days)))
    return {"$gte": lo, "$lte": hi}


def get_topic_events(db: Any, *, date: str, include_past_recent: int = 3,
                     window_days: int = 1) -> list[dict]:
    """题材事件（按事件日取窗，热度降序）——「当日/近两日炒什么」的事件池。"""
    docs = db[COLLECTION_TOPIC].find(
        {"day": _window(date, include_past_recent, window_days)},
        {"day": 1, "eventId": 1, "title": 1, "content": 1, "source": 1, "hotVal": 1, "num": 1},
    )
    return sorted(docs, key=lambda d: (d.get("day") or "", -(d.get("hotVal") or 0)))


def get_news_items(db: Any, *, date: str, include_past_recent: int = 2,
                   window_days: int = 1) -> list[dict]:
    """题材新闻流（按事件日取窗，时间降序）——Kword 题材标签 + 关联个股。"""
    docs = db[COLLECTION_NEWS].find(
        {"eventDate": _window(date, include_past_recent, window_days)},
        {"eventDate": 1, "cid": 1, "title": 1, "kword": 1, "zsName": 1, "source": 1, "stocks": 1,
         "contentHtml": 1, "kwordDesc": 1, "zsCode": 1, "isChoice": 1,
         "timeStamp": 1},
    )
    return sorted(docs, key=lambda d: -(d.get("timeStamp") or 0))


def get_calendar_items(db: Any, *, date: str, window_days: int = 3) -> list[dict]:
    """前瞻日历（未来 window_days 日，按日期升序）。"""
    docs = db[COLLECTION_CALENDAR].find(
        {"date": _window(date, 0, window_days)},
        {"date": 1, "pid": 1, "brief": 1, "tagName": 1, "stocks": 1},
    )
    return sorted(docs, key=lambda d: (d.get("date") or "", d.get("tagName") or ""))


def corpus_stats(db: Any) -> dict:
    """三集合计数 + 各自最近采集日（corpus_state 用，fail-visible）。"""
    out: dict[str, Any] = {}
    latest = None
    for name, col in (("topic", COLLECTION_TOPIC), ("news", COLLECTION_NEWS),
                      ("calendar", COLLECTION_CALENDAR)):
        row = db[col].find_one({}, {"lastFetchDate": 1}, sort=[("lastFetchDate", -1)]) or {}
        d = row.get("lastFetchDate")
        out[name] = {"count": db[col].count_documents({}), "latestFetchDate": d}
        if d and (latest is None or d > latest):
            latest = d
    out["latestFetchDate"] = latest
    return out
