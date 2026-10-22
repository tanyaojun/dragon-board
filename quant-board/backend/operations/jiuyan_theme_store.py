# -*- coding: utf-8 -*-
"""韭研题材语料存储层（集合 `jiuyan_ai_industry`；2026-10-23 v4 换源后单源化）。

单主链：只在 MongoDB `dragon_board_quant`；不建备份/对照集合（历史靠 git + 幂等覆盖）。

事件层（原 `jiuyan_timeline`：投资日历+早报）随 2026-10-23 裁决（方案 A：事件层唯一权威源
=开盘啦，`kpl_theme_store.py`）退役：存储/读取函数删除，集合导出归档后 drop。

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



def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
                            "contentChangedAt": 1, "contentChangedDate": 1,
                            "content": 1}) or {}
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


def get_industry_nodes(db: Any) -> list[dict]:
    return list(db[COLLECTION_INDUSTRY].find({}, {
        "code": 1, "name": 1, "level": 1, "parentCode": 1, "path": 1, "content": 1,
        "hot": 1, "contentChangedDate": 1, "industryUpdateTime": 1, "lastFetchDate": 1,
    }))
