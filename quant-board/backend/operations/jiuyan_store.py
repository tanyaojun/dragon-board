# -*- coding: utf-8 -*-
"""韭研异动存储层（集合 jiuyan_action，设计 jiuyan-collector-design.md §2/§3）。

jiuyan_action：_id="<date>:<kind>"（kind=midday/final），幂等 upsert，重采覆盖同键。
动态凭据缓存=Redis（24h TTL 兜底，authFailed 显式删除）：铸造 token（jiuyan:minted-token）+
登录会话（jiuyan:session，2026-10-05 认证链自动化）；静态凭据=JIUYAN_SESSION（.env.local）。
**密钥/凭据禁止落 MongoDB**（2026-10-02 用户红线：单一事实源，DB 不存机密）。
fail-visible：写入失败抛给调用方记录，不在本层吞错。
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from backend.market_proxy.redis_client import get_hotlist_redis_client

COLLECTION_ACTION = "jiuyan_action"
TOKEN_REDIS_KEY = "jiuyan:minted-token"
TOKEN_TTL_SECONDS = 24 * 3600
SESSION_REDIS_KEY = "jiuyan:session"
SESSION_TTL_SECONDS = 24 * 3600


def _token_cache_key() -> str:
    from backend.core.settings import get_settings

    return f"{get_settings().redis_key_prefix}:{TOKEN_REDIS_KEY}"


def _session_cache_key() -> str:
    from backend.core.settings import get_settings

    return f"{get_settings().redis_key_prefix}:{SESSION_REDIS_KEY}"


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


def get_cached_token() -> dict | None:
    """读取铸造 token 缓存（Redis）。不可用/无缓存/连接故障 → None（缓存层容错，调用方走铸造）。"""
    client = get_hotlist_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(_token_cache_key())
        if not raw:
            return None
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001 redis-py 懒连接：配好但宕机在首个 get 才抛（评审 M-1）
        return None
    return {"token": parsed.get("token"), "timestamp": parsed.get("timestamp"),
            "mintedAt": parsed.get("mintedAt"), "source": parsed.get("source")}


def save_token(*, token: str, timestamp: str, source: str) -> bool:
    """缓存铸造 token（Redis，24h TTL 兜底）。Redis 不可用/连接故障返回 False（调用方如实提示）。"""
    client = get_hotlist_redis_client()
    if client is None:
        return False
    try:
        client.set(_token_cache_key(), json.dumps({
            "token": token, "timestamp": timestamp,
            "mintedAt": datetime.now().isoformat(timespec="seconds"), "source": source}),
            ex=TOKEN_TTL_SECONDS)
    except Exception:  # noqa: BLE001 缓存写失败不炸采集链（评审 M-1）
        return False
    return True


def clear_cached_token() -> None:
    """authFailed 时显式删除缓存 token（避免陈旧密钥滞留）。"""
    client = get_hotlist_redis_client()
    if client is not None:
        try:
            client.delete(_token_cache_key())
        except Exception:  # noqa: BLE001 缓存层无谓失败不炸链（评审 M-1）
            pass


def get_cached_session() -> dict | None:
    """读取动态登录会话缓存（Redis）。不可用/无缓存/连接故障 → None（调用方走登录/静态回退）。"""
    client = get_hotlist_redis_client()
    if client is None:
        return None
    try:
        raw = client.get(_session_cache_key())
        if not raw:
            return None
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001 缓存层容错（评审 M-1）
        return None
    return {"session": parsed.get("session"), "source": parsed.get("source"),
            "savedAt": parsed.get("savedAt")}


def save_session(*, session: str, source: str) -> bool:
    """缓存动态登录会话（Redis，24h TTL 兜底）。空会话/Redis 不可用/连接故障 → False（不缓存空值）。"""
    if not session:
        return False
    client = get_hotlist_redis_client()
    if client is None:
        return False
    try:
        client.set(_session_cache_key(), json.dumps({
            "session": session, "source": source,
            "savedAt": datetime.now().isoformat(timespec="seconds")}),
            ex=SESSION_TTL_SECONDS)
    except Exception:  # noqa: BLE001 缓存写失败不炸采集链（评审 M-1）
        return False
    return True


def clear_cached_session() -> None:
    """authFailed 时显式删除缓存会话（下次采集触发重登）。"""
    client = get_hotlist_redis_client()
    if client is not None:
        try:
            client.delete(_session_cache_key())
        except Exception:  # noqa: BLE001 缓存层无谓失败不炸链（评审 M-1）
            pass
