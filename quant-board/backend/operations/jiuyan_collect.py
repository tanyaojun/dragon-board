# -*- coding: utf-8 -*-
"""韭研单日采集编排（resolve_auth → fetch → store，设计 jiuyan-collector-design.md §3/§4/§8）。

流程：认证解析（Redis 缓存 → 浏览器铸造/账号密码登录 → 静态回退，见 jiuyan_auth）→
count-pc 探针 → field 全量 → 解析 → jiuyan_action 落库。
authFailed 时清两缓存并强制重新解析（可触发浏览器铸造/登录）自愈重试一次；仍失败如实
返回并附 selfHeal 留痕。fail-visible：任何失败原样返回不伪造。
"""
from __future__ import annotations

import logging
from typing import Any

from backend.operations import jiuyan_auth, jiuyan_mark_sync, jiuyan_store
from backend.operations.jiuyan_fetch import fetch_count, fetch_field

logger = logging.getLogger(__name__)


def _attempt(date: str, kind: str, db: Any, auth: dict) -> dict:
    probe = fetch_count(date, session_cookie=auth["session"], token=auth["token"],
                        timestamp=auth["timestamp"])
    if not probe.get("ok"):
        return {"ok": False, "date": date, "kind": kind, "error": probe.get("error"),
                "authFailed": bool(probe.get("authFailed")), "quota": bool(probe.get("quota"))}
    counts = {"all": probe.get("all"), "recommend": probe.get("recommend")}

    field = fetch_field(date, session_cookie=auth["session"], token=auth["token"],
                        timestamp=auth["timestamp"])
    if not field.get("ok"):
        # authFailed/quota 由 fetch_field 结构化返回（errCode 110/9），不再做子串猜测
        return {"ok": False, "date": date, "kind": kind, "error": field.get("error"),
                "authFailed": bool(field.get("authFailed")), "quota": bool(field.get("quota"))}

    parsed = field["parsed"]
    doc_id = jiuyan_store.save_action_doc(db, date=date, kind=kind, parsed=parsed, counts=counts,
                                          token_source=str(auth.get("source") or "unknown"))
    return {"ok": True, "date": date, "kind": kind, "docId": doc_id,
            "fields": len(parsed.get("fields") or []), "stocks": parsed.get("totalStocks"),
            "degraded": len(parsed.get("degradedSources") or [])}


def _collect_and_store_impl(date: str, kind: str = "final", db: Any = None) -> dict:
    """采集某交易日并落库。返回 {ok, date, kind, ...}；失败 {ok: False, error, authFailed?}。

    authFailed（会话/token 失效）→ 清两缓存强制重新解析（可触发浏览器铸造/登录）自愈重试一次；
    重试结果一律附 selfHeal={ok, firstError[, error]} 留痕。quota（每日配额耗尽）不是鉴权
    失败，不进入自愈（白耗一次登录还会踢掉用户会话）。
    """
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
        return {**result, "selfHeal": {"ok": False, "firstError": result.get("error"),
                                       "error": auth2.get("error")}}
    result2 = _attempt(date, kind, db, auth2)
    self_heal = {"ok": bool(result2.get("ok")), "firstError": result.get("error")}
    if not result2.get("ok"):
        self_heal["error"] = result2.get("error")
    return {**result2, "selfHeal": self_heal}


def collect_and_store(date: str, kind: str = "final", db: Any = None) -> dict:
    """采集并落库；final 成功入库后自动同步板块名到 mark.dat（after-collect 钩子）。

    钩子由 jiuyan_mark_sync.maybe_sync_after_collect 单点触发（无独立定时脚本）：仅 final、
    启用且 mark 文件存在时才写；pytest 跳过；任何异常只记录不外抛，绝不影响采集主链。
    结果附 markSync 子字典留痕。
    """
    result = _collect_and_store_impl(date, kind, db)
    if result.get("ok") and kind == "final":
        try:
            if db is None:
                from backend.data.repositories.repository_factory import get_runtime_mongodb_database
                db = get_runtime_mongodb_database()
            result["markSync"] = jiuyan_mark_sync.maybe_sync_after_collect(db, date, kind)
        except Exception as exc:  # 双保险：钩子异常绝不波及采集主链
            logger.exception("jiuyan mark sync hook failed")
            result["markSync"] = {"ok": False, "error": str(exc)}
    return result
