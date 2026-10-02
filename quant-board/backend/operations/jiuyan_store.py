# -*- coding: utf-8 -*-
"""韭研异动存储层（集合 jiuyan_action / jiuyan_meta，设计 jiuyan-collector-design.md §2/§3）。

jiuyan_action：_id="<date>:<kind>"（kind=midday/final），幂等 upsert，重采覆盖同键。
jiuyan_meta：_id="jiuyan_token" 缓存 {token, timestamp, mintedAt, source}。
fail-visible：写入失败抛给调用方记录，不在本层吞错。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

COLLECTION_ACTION = "jiuyan_action"
COLLECTION_META = "jiuyan_meta"
TOKEN_DOC_ID = "jiuyan_token"


def action_doc_id(date: str, kind: str) -> str:
    if kind not in ("midday", "final"):
        raise ValueError(f"kind 必须为 midday|final，得到 {kind!r}")
    return f"{date}:{kind}"


def save_action_doc(db: Any, *, date: str, kind: str, parsed: dict,
                    counts: dict | None = None, token_source: str = "cache") -> str:
    """解析结果落库（幂等 upsert）。返回 _id。"""
    doc = {
        "_id": action_doc_id(date, kind),
        "kind": "jiuyan_action",
        "tradingDate": date,
        "updateKind": kind,
        "counts": counts or {},
        "fields": parsed.get("fields") or [],
        "totalStocks": parsed.get("totalStocks") or 0,
        "quality": {"degradedSources": parsed.get("degradedSources") or [], "tokenSource": token_source},
        "fetchedAt": datetime.now().isoformat(timespec="seconds"),
    }
    db[COLLECTION_ACTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return doc["_id"]


def get_action_doc(db: Any, date: str, kind: str = "final") -> dict | None:
    return db[COLLECTION_ACTION].find_one({"_id": action_doc_id(date, kind)})


def list_action_dates(db: Any) -> list[dict]:
    """全部已落库日期（升序）：[{date, kinds}]。"""
    out: dict[str, set[str]] = {}
    for doc in db[COLLECTION_ACTION].find({}, {"tradingDate": 1, "updateKind": 1}):
        out.setdefault(str(doc.get("tradingDate")), set()).add(str(doc.get("updateKind")))
    return [{"date": d, "kinds": sorted(k)} for d, k in sorted(out.items())]


def get_cached_token(db: Any) -> dict | None:
    doc = db[COLLECTION_META].find_one({"_id": TOKEN_DOC_ID})
    if not doc:
        return None
    return {"token": doc.get("token"), "timestamp": doc.get("timestamp"),
            "mintedAt": doc.get("mintedAt"), "source": doc.get("source")}


def save_token(db: Any, *, token: str, timestamp: str, source: str) -> None:
    db[COLLECTION_META].replace_one(
        {"_id": TOKEN_DOC_ID},
        {"_id": TOKEN_DOC_ID, "token": token, "timestamp": timestamp,
         "mintedAt": datetime.now().isoformat(timespec="seconds"), "source": source},
        upsert=True)
