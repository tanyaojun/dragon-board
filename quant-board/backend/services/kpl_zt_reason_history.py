# -*- coding: utf-8 -*-
"""KPL 涨停原因全文·历史档案链（HisLimitResumption/GetDayZhangTing HTTP，2026-11-08 探测实弹）。

背景：socket 2203 涨停原因推送只覆盖**当日盘中实时态**（订阅面=涨停池成员）；历史/存档态
（如周末回看上一交易日）需要大段详情时的数据源。端点合同实测
（.tmp_review/kpl_stockpage_probe_results_2026-11-08.jsonl tag=zt_reason_hist，errcode=0）：
- POST https://apphis.longhuvip.com/w1/api/index.php
- c=HisLimitResumption&a=GetDayZhangTing&StockID=<单股>&Index=0&STAT_SDK_TYPE=50
  + 公共参数（凭据走 KPL_APP_BASE_PARAMS 公共出口，游客亦可用）
- **无 Date 参数**：返回该股最近涨停日的条目（List 每项自带 Date 字段），调用方按
  展示日期过滤匹配；非该日条目不伪装（结构化 note 透出 matched_date）
- 响应 {StockID, List:[{ZSCode:[概念码组], Reason(全文组合), Date, SCLT(日内梯队),
  GNSM(概念解析全文), Boom_ZS(媒体催化), Type, PZSCode, Group_Str, SCDW, QitaStr}]}
- 与 socket 2203 zt 字段同源互证（301697 双源一致）；2103 zt_reason=短原因串（客户端拼接）

pytest 纪律：parse 为纯函数全 mock 覆盖；fetch 仅人工运维路径真实调用（AGENTS.md 红线 7）。
限频：复用 kpl_ranking_service._post_form 的全局 ≥2s 单发间隔锁；缓存只做限频减负。
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List

from backend.services.kpl_ranking_service import (
    _HOST_HISTORY,
    _UA_STOCKS,
    _check_errcode,
    _post_form,
)
from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 300.0      # 盘中最近涨停记录会变，5 分钟 TTL；历史回看命中即免发
_CACHE_MAX_KEYS = 2000          # 单股粒度，全池 ~200 只，超限全清（缓存不损正确性）


def _global_params() -> Dict[str, Any]:
    """公共参数（凭据单一事实源=KPL_APP_BASE_PARAMS；其余按 2026-11-08 实测组合）。"""
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    return {"apiv": "w38", "VerSion": "5.16.0.5", "PhoneOSNew": "2",
            "Index": "0", "STAT_SDK_TYPE": "50", **creds}


def _real_post_form() -> bool:
    """`_post_form` 是否仍为生产实现（未被测试 monkeypatch）——pytest 护栏判据。"""
    return getattr(_post_form, "__module__", "") == "backend.services.kpl_ranking_service"


def _pytest_guard() -> None:
    """硬护栏：pytest 进程内禁止真实调用上游（AGENTS 红线 7：测试全 mock）。

    测试必须 monkeypatch `_post_form` 或注入 fetcher；真实调用只走运维/语料补拉路径。
    """
    if os.environ.get("PYTEST_CURRENT_TEST") and _real_post_form():
        raise RuntimeError(
            "pytest 禁止真实调用 KPL 上游 HTTP（红线 7）：请 monkeypatch _post_form 或注入 fetcher")


def fetch_stock_zt_reason_raw(stock_id: str) -> Dict[str, Any]:
    """单股最近涨停记录（带缓存；真实调用仅运维路径，pytest 全 mock）。"""
    cached = _CACHE.get(stock_id)
    if cached and time.time() - cached["ts"] < _CACHE_TTL_SECONDS:
        return cached["data"]
    _pytest_guard()
    if len(_CACHE) >= _CACHE_MAX_KEYS:
        _CACHE.clear()
    data = _post_form(_HOST_HISTORY,
                      {"a": "GetDayZhangTing", "c": "HisLimitResumption",
                       "StockID": stock_id, **_global_params()},
                      _UA_STOCKS)
    _check_errcode(data)
    _CACHE[stock_id] = {"ts": time.time(), "data": data}
    return data


_WS_RE = re.compile("[ \t\u3000]+")
_NL_RE = re.compile("\n{3,}")


def _clean_text(s: Any) -> str:
    """文本归一：上游 Reason/GNSM 含 CRLF 与全角空格，原生 tooltip 会显示成乱序换行。"""
    t = str(s or "").replace("\r\n", "\n").replace("\r", "\n")
    t = _WS_RE.sub(" ", t)
    t = _NL_RE.sub("\n\n", t)
    return t.strip()


def parse_zt_reason_history(data: Dict[str, Any], date: str) -> Dict[str, Any]:
    """GetDayZhangTing → 结构化（按展示日期过滤；无匹配日条目不伪装，透出 matched_date）。

    List 为空 = 该股最近涨停日无记录（当日未涨停属正常态，ok:true items:[]，非错误）。
    """
    lst = data.get("List") or []
    items: List[Dict[str, Any]] = []
    dropped = 0
    dates_seen: List[str] = []
    for it in lst if isinstance(lst, list) else []:
        if not isinstance(it, dict):
            dropped += 1
            continue
        d = str(it.get("Date") or "")
        if d and d not in dates_seen:
            dates_seen.append(d)
        if date and d != date:
            continue
        zs = it.get("ZSCode")
        items.append({
            "date": d,
            "reason": _clean_text(it.get("Reason")),
            "gns": _clean_text(it.get("GNSM")),
            "boom_zs": _clean_text(it.get("Boom_ZS")),
            "sclt": _clean_text(it.get("SCLT")),
            "zs_codes": [str(x) for x in zs if str(x)] if isinstance(zs, list) else [],
        })
    matched = next((d for d in dates_seen if d), "")
    out: Dict[str, Any] = {
        "ok": True,
        "stock_id": str(data.get("StockID") or ""),
        "matched_date": matched,
        "items": items,
        "dropped": dropped,
    }
    if date and not items and matched and matched != date:
        out["note"] = f"上游仅回最近涨停日 {matched}（无 {date} 条目），不伪装该日详情"
    return out


def get_stock_zt_reason(date: str, stock_id: str) -> Dict[str, Any]:
    """读口（历史档案详情）：{ok, date, stock_id, items, matched_date}，fail-visible 结构化。"""
    try:
        raw = fetch_stock_zt_reason_raw(stock_id)
    except Exception as exc:  # KplRankingError/HTTP 层异常 → 结构化降级（不伪装空详情）
        reason = getattr(exc, "errorCode", "") or type(exc).__name__
        return {"ok": False, "degraded": True, "reason": str(reason)[:60],
                "error": str(getattr(exc, "error", "") or exc)[:120],
                "date": date, "stock_id": stock_id, "items": []}
    out = parse_zt_reason_history(raw, date)
    out["date"] = date
    return out