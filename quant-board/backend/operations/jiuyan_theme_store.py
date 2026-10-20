# -*- coding: utf-8 -*-
"""韭研题材/事件语料存储层（集合 `jiuyan_timeline` / `jiuyan_ai_industry`，2026-10-20）。

单主链：只在 MongoDB `dragon_board_quant`；不建备份/对照集合（历史靠 git + 幂等覆盖）。

`jiuyan_timeline`（事件日历，**含未来日期**）
  _id = "{date}:{sha1(title)[:12]}"（按事件身份去重，news+list 同一条只留一份），kind="jiuyan_timeline"
  date(事件日期，可>今日) / title / content / grade(1-5) / createTime(录入时间) /
  themes[] / firstSeenAt(首次采集到的时间，**不覆盖**) / updatedAt / forwardDays /
  sourceIds{timelineId,articleId} / sources[]（news|list，同一事件可能两边都有）

`jiuyan_ai_industry`（板块级催化原文 + 热度）
  _id = code（如 "0118"），kind="jiuyan_ai_industry"
  name / level / parentCode / path[] / content(板块级催化原文) / hot /
  contentHash / contentChangedAt（内容变更时刷新，用于「是否新催化」）/ firstSeenAt /
  updatedAt / lastFetchDate

fail-visible：写入异常向上抛（不吞），缺 content 如实留空字符串，不用占位文本冒充催化。
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

COLLECTION_TIMELINE = "jiuyan_timeline"
COLLECTION_INDUSTRY = "jiuyan_ai_industry"
# 题材端点调用计数（额度护栏，2026-10-20）：`_id={fetchDate}`，`calls.{source} = n`。
# 不存凭据，只存计数；失败请求同样计数（服务端已扣额度）。
COLLECTION_API_CALLS = "jiuyan_api_calls"


def record_api_calls(db: Any, fetch_date: str, sources: tuple[str, ...]) -> dict:
    """累加当日题材端点调用计数（幂等可重入，`$inc` 语义）。返回累加后计数。"""
    if not sources:
        return calls_recorded(db, fetch_date)
    inc = {f"calls.{s}": 1 for s in sources}
    db[COLLECTION_API_CALLS].update_one(
        {"_id": fetch_date},
        {"$inc": inc, "$set": {"lastCallAt": _now()}},
        upsert=True,
    )
    return calls_recorded(db, fetch_date)


def calls_recorded(db: Any, fetch_date: str) -> int:
    """当日题材端点已计调用总数（取不到按 0；缺字段容错）。"""
    doc = db[COLLECTION_API_CALLS].find_one({"_id": fetch_date}, {"calls": 1}) or {}
    return sum(int(v or 0) for v in (doc.get("calls") or {}).values())


def timeline_doc_id(date: str, title: str) -> str:
    """`_id` 由 (事件日期, 标题) 决定：news 与 list 两个端点会重复给同一条事件，
    用上游 id 会建出两条平行文档（2026-10-20 实测 20 对重复），故按事件身份去重。"""
    key = hashlib.sha1(f"{date}|{re.sub(r'\s+', '', title)}".encode("utf-8")).hexdigest()[:12]
    return f"{date}:{key}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _days_between(fetch_date: str, event_date: str) -> int | None:
    try:
        d1 = datetime.strptime(fetch_date, "%Y-%m-%d")
        d2 = datetime.strptime(event_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return (d2 - d1).days


def save_timeline_items(db: Any, *, fetch_date: str, source: str,
                        items: list[dict]) -> dict:
    """时间轴/投资日历幂等 upsert。返回 {written, skipped, future, past}。

    同一 `_id` 重采只刷新 title/content/grade/录入时间与 sources，**保留 firstSeenAt**，
    这样「事件是不是今天新冒出来的」可判定（新近度 = firstSeenAt 距今日）。
    """
    written = skipped = future = past = 0
    seen_ids: set[str] = set()
    for it in items:
        title = (it.get("title") or "").strip()
        date = str(it.get("date") or "")
        if not title or not date:
            skipped += 1
            continue
        _id = timeline_doc_id(date, title)
        existing = db[COLLECTION_TIMELINE].find_one(
            {"_id": _id}, {"firstSeenAt": 1, "firstSeenDate": 1, "sources": 1, "grade": 1,
                          "createTime": 1, "themes": 1, "content": 1}) or {}
        sources = list(existing.get("sources") or [])
        if source not in sources:
            sources.append(source)
        # 同一条事件两源各带一半信息（list 有 grade/themes/录入时间，news 有正文）：取更全的一方
        grade = it.get("grade") if it.get("grade") is not None else existing.get("grade")
        content = (it.get("content") or "").strip() or (existing.get("content") or "")
        doc = {
            "_id": _id,
            "kind": "jiuyan_timeline",
            "date": date,
            "title": title,
            "sourceIds": {"articleId": it.get("articleId") or existing.get("articleId"),
                          "timelineId": it.get("timelineId") or existing.get("timelineId")},
            "content": content,
            "grade": grade,
            "createTime": it.get("createTime") or existing.get("createTime"),
            "themes": it.get("themes") or existing.get("themes") or [],
            "dateAnchor": "event_date",
            "forwardDays": _days_between(fetch_date, date),
            "sources": sources,
            "firstSeenAt": (existing or {}).get("firstSeenAt") or _now(),
            "firstSeenDate": (existing or {}).get("firstSeenDate") or fetch_date,
            "lastFetchDate": fetch_date,
            "updatedAt": _now(),
        }
        db[COLLECTION_TIMELINE].replace_one({"_id": _id}, doc, upsert=True)
        if _id not in seen_ids:          # 同批内 news/list 重复事件只算一次写入
            seen_ids.add(_id)
            written += 1
        fd = doc["forwardDays"]
        if fd is not None and fd >= 0:
            future += 1
        else:
            past += 1
    return {"written": written, "skipped": skipped, "future": future, "past": past}


def save_industry_nodes(db: Any, *, fetch_date: str, nodes: list[dict]) -> dict:
    """产业树节点幂等 upsert。返回 {written, contentChanged, withContent, reused}。"""
    written = content_changed = with_content = 0
    for n in nodes:
        code = str(n.get("code") or "")
        if not code:
            continue
        content = n.get("content") or ""
        digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12] if content else None
        existing = db[COLLECTION_INDUSTRY].find_one(
            {"_id": code}, {"contentHash": 1, "firstSeenAt": 1, "name": 1,
                             "contentChangedAt": 1, "contentChangedDate": 1}) or {}
        changed = bool(digest) and digest != existing.get("contentHash")
        # P2 修复（2026-10-20 review）：入站 content 为空但库内非空时保留旧值——
        # 服务端降级 payload（errCode=0 但 content 空）不得把已采证据覆盖成空（§4.0）；
        # timeline 层同口径（it.content or existing.content）。
        if not content and existing.get("content"):
            content = existing["content"]
        doc = {
            "_id": code,
            "kind": "jiuyan_ai_industry",
            "code": code,
            "name": n.get("name") or existing.get("name") or "",
            "level": n.get("level"),
            "parentCode": n.get("parentCode"),
            "path": n.get("path") or [],
            "content": content,
            "contentHash": digest,
            "contentChangedAt": (_now() if changed else None)
            or existing.get("contentChangedAt"),
            "contentChangedDate": (fetch_date if changed else None)
            or existing.get("contentChangedDate"),
            "hot": n.get("hot"),
            "industryUpdateTime": n.get("updateTime"),
            "stockCount": n.get("stockCount"),
            "firstSeenAt": existing.get("firstSeenAt") or _now(),
            "lastFetchDate": fetch_date,
            "updatedAt": _now(),
        }
        db[COLLECTION_INDUSTRY].replace_one({"_id": code}, doc, upsert=True)
        written += 1
        if content:
            with_content += 1
        if changed:
            content_changed += 1
    return {"written": written, "contentChanged": content_changed, "withContent": with_content}


def get_timeline_window(db: Any, *, date: str, window_days: int = 3,
                        include_past_recent: int = 0) -> list[dict]:
    """取事件日期落在 [date - include_past_recent, date + window_days] 的事件（按日期升序）。

    只按**事件日期**取（dateAnchor=event_date），不拿录入时间冒充事件时间。
    """
    lo = _shift(date, -abs(int(include_past_recent)))
    hi = _shift(date, abs(int(window_days)))
    if lo is None or hi is None:
        return []
    docs = db[COLLECTION_TIMELINE].find(
        {"date": {"$gte": lo, "$lte": hi}},
        {"date": 1, "title": 1, "content": 1, "grade": 1, "themes": 1, "createTime": 1,
         "firstSeenDate": 1, "forwardDays": 1, "sources": 1},
    )
    return sorted(docs, key=lambda d: (d.get("date") or "", -(d.get("grade") or 0)))


def get_industry_nodes(db: Any) -> list[dict]:
    return list(db[COLLECTION_INDUSTRY].find({}, {
        "code": 1, "name": 1, "level": 1, "parentCode": 1, "path": 1, "content": 1,
        "hot": 1, "contentChangedDate": 1, "industryUpdateTime": 1, "lastFetchDate": 1,
    }))


def _shift(date: str, days: int) -> str | None:
    from datetime import timedelta
    try:
        return (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=days)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None
