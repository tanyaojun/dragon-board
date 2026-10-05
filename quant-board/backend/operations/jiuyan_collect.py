# -*- coding: utf-8 -*-
"""韭研单日采集编排（resolve_auth → fetch → store，设计 jiuyan-collector-design.md §3/§4/§8）。

流程：认证解析（Redis 缓存 → 浏览器铸造/账号密码登录 → 静态回退，见 jiuyan_auth）→
count-pc 探针 → field 全量 → 解析 → jiuyan_action 落库。
authFailed 时清两缓存并强制重新解析（可触发浏览器铸造/登录）自愈重试一次；仍失败如实
返回并附 selfHeal 留痕。fail-visible：任何失败原样返回不伪造。
"""
from __future__ import annotations

from typing import Any

from backend.operations import jiuyan_auth, jiuyan_store
from backend.operations.jiuyan_fetch import fetch_count, fetch_field


def _attempt(date: str, kind: str, db: Any, auth: dict) -> dict:
    probe = fetch_count(date, session_cookie=auth["session"], token=auth["token"],
                        timestamp=auth["timestamp"])
    if not probe.get("ok"):
        return {"ok": False, "date": date, "kind": kind, "error": probe.get("error"),
                "authFailed": probe.get("authFailed", False)}
    counts = {"all": probe.get("all"), "recommend": probe.get("recommend")}

    field = fetch_field(date, session_cookie=auth["session"], token=auth["token"],
                        timestamp=auth["timestamp"])
    if not field.get("ok"):
        return {"ok": False, "date": date, "kind": kind, "error": field.get("error"),
                "authFailed": "110" in str(field.get("error"))}

    parsed = field["parsed"]
    doc_id = jiuyan_store.save_action_doc(db, date=date, kind=kind, parsed=parsed, counts=counts,
                                          token_source=str(auth.get("source") or "cache"))
    return {"ok": True, "date": date, "kind": kind, "docId": doc_id,
            "fields": len(parsed.get("fields") or []), "stocks": parsed.get("totalStocks"),
            "degraded": len(parsed.get("degradedSources") or [])}


def collect_and_store(date: str, kind: str = "final", db: Any = None) -> dict:
    """采集某交易日并落库。返回 {ok, date, kind, ...}；失败 {ok: False, error, authFailed?}。"""
    if db is None:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        db = get_runtime_mongodb_database()

    auth = jiuyan_auth.resolve_auth(date=date)
    if not auth.get("ok"):
        return {"ok": False, "date": date, "kind": kind, "error": auth.get("error"),
                "authFailed": bool(auth.get("authFailed"))}

    result = _attempt(date, kind, db, auth)
    if result.get("ok") or not result.get("authFailed"):
        return result

    # 自愈重试一次：清陈旧缓存 → 强制重新解析（可触发浏览器铸造/登录）→ 再试
    jiuyan_store.clear_cached_token()
    jiuyan_store.clear_cached_session()
    auth2 = jiuyan_auth.resolve_auth(date=date, force_refresh=True)
    if not auth2.get("ok"):
        return {**result, "selfHeal": {"ok": False, "error": auth2.get("error")}}
    return _attempt(date, kind, db, auth2)
