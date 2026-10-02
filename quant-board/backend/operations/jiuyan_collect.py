# -*- coding: utf-8 -*-
"""韭研单日采集编排（fetch → store，设计 jiuyan-collector-design.md §3/§4）。

流程：缓存 token → count-pc 探针（110/登录失效 = authFailed，需重铸 token 或重扫码）
→ field 全量 → 解析 → jiuyan_action 落库。fail-visible：任何失败原样返回不伪造。
"""
from __future__ import annotations

import os
from typing import Any

from backend.operations import jiuyan_store
from backend.operations.jiuyan_fetch import fetch_count, fetch_field


def collect_and_store(date: str, kind: str = "final", db: Any = None) -> dict:
    """采集某交易日并落库。返回 {ok, date, kind, ...}；失败 {ok: False, error, authFailed?}。"""
    session = os.environ.get("JIUYAN_SESSION") or ""
    if not session:
        return {"ok": False, "date": date, "kind": kind, "error": "缺 JIUYAN_SESSION"}
    if db is None:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        db = get_runtime_mongodb_database()

    cached = jiuyan_store.get_cached_token(db)
    if not cached or not cached.get("token"):
        return {"ok": False, "date": date, "kind": kind, "error": "无缓存 token（需铸造）", "authFailed": True}

    probe = fetch_count(date, session_cookie=session, token=cached["token"], timestamp=cached["timestamp"])
    if not probe.get("ok"):
        return {"ok": False, "date": date, "kind": kind, "error": probe.get("error"),
                "authFailed": probe.get("authFailed", False)}
    counts = {"all": probe.get("all"), "recommend": probe.get("recommend")}

    field = fetch_field(date, session_cookie=session, token=cached["token"], timestamp=cached["timestamp"])
    if not field.get("ok"):
        return {"ok": False, "date": date, "kind": kind, "error": field.get("error"),
                "authFailed": "110" in str(field.get("error"))}

    parsed = field["parsed"]
    doc_id = jiuyan_store.save_action_doc(db, date=date, kind=kind, parsed=parsed, counts=counts,
                                          token_source=str(cached.get("source") or "cache"))
    return {"ok": True, "date": date, "kind": kind, "docId": doc_id,
            "fields": len(parsed.get("fields") or []), "stocks": parsed.get("totalStocks"),
            "degraded": len(parsed.get("degradedSources") or [])}
