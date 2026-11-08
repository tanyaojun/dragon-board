# -*- coding: utf-8 -*-
"""KPL 公告/新闻/研报计数协议层（apphis CompanyNotice/GetCompanyCount，2026-11-08 探测实弹）。

背景：题材龙头语料候选第 3 项——龙头股的公告/新闻/研报密度是催化剂兑现与风险前兆的
画像维度；2026-11-08 HTTP 探测命中本端点（errcode=0）。本模块只做协议层
（fetch/parse/读口），落库由 kpl_daban_archiver 的 notice_ 通道消费。

端点合同（.tmp_review/kpl_stockpage_probe_results_2026-11-08.jsonl tag=notice_count，
2026-11-08 实测 301697）：
- POST https://apphis.longhuvip.com/w1/api/index.php（**apphis 域**，非 apphq）
- c=CompanyNotice&a=GetCompanyCount&StockID=<单股> + 公共参数（凭据走 KPL_APP_BASE_PARAMS
  公共出口；游客 UserID/Token=0 亦可）
- 响应 {"news":0,"report":0,"announcement":0,"CID":0,"Date":"20261108","ttag":...,
  "errcode":"0"}——三计数 + 上游数据日期；
- **计数统计窗口上游未标注**（当日/累计不可判）→ window_note 原样透出，禁止自算/反推；
- 单股粒度 → 全池语料逐股懒取（复用 _post_form 全局 ≥2s 单发间隔锁）；
- **公告标题/正文不进叙事**（只出计数与日期；内容消费另行裁决）。

pytest 纪律：parse 纯函数全 mock；fetch 仅人工运维/JEV 语料补拉路径真实调用（红线 7）。
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict

from backend.services.kpl_ranking_service import (
    _UA_STOCKS,
    _check_errcode,
    _post_form,
)
from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS

_HOST_HIS = "https://apphis.longhuvip.com/w1/api/index.php"   # API_HIS（公告/历史域）
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 300.0
_CACHE_MAX_KEYS = 2000

COUNT_FIELDS: tuple[str, ...] = ("announcement", "report", "news")
WINDOW_NOTE = "计数统计窗口上游未标注（公告/研报/新闻计数原样透出，不自算不反推）"


def _global_params() -> Dict[str, Any]:
    """公共参数（凭据单一事实源=KPL_APP_BASE_PARAMS；其余按 2026-11-08 实测组合）。"""
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    return {"apiv": "w38", "VerSion": "5.16.0.5", "PhoneOSNew": "2", **creds}


def _real_post_form() -> bool:
    return getattr(_post_form, "__module__", "") == "backend.services.kpl_ranking_service"


def _pytest_guard() -> None:
    """硬护栏：pytest 进程内禁止真实调用上游（AGENTS 红线 7：测试全 mock）。"""
    if os.environ.get("PYTEST_CURRENT_TEST") and _real_post_form():
        raise RuntimeError(
            "pytest 禁止真实调用 KPL 上游 HTTP（红线 7）：请 monkeypatch _post_form 或注入 fetcher")


def fetch_notice_count_raw(stock_id: str) -> Dict[str, Any]:
    """单股公告计数原始响应（带缓存；真实调用仅运维/语料补拉路径，pytest 全 mock）。"""
    cached = _CACHE.get(stock_id)
    if cached and time.time() - cached["ts"] < _CACHE_TTL_SECONDS:
        return cached["data"]
    _pytest_guard()
    if len(_CACHE) >= _CACHE_MAX_KEYS:
        _CACHE.clear()
    data = _post_form(_HOST_HIS,
                      {"a": "GetCompanyCount", "c": "CompanyNotice",
                       "StockID": stock_id, **_global_params()},
                      _UA_STOCKS)
    _check_errcode(data)
    _CACHE[stock_id] = {"ts": time.time(), "data": data}
    return data


def parse_notice_count(data: Dict[str, Any], *, stock_id: str = "") -> Dict[str, Any]:
    """计数响应 → 具名字段（缺位不补 0，partial 标记 fail-visible，AGENTS §4.0）。"""
    sid = str(data.get("StockID") or stock_id or "")
    if not isinstance(data, dict) or "announcement" not in data and "news" not in data:
        return {"ok": False, "degraded": True, "reason": "unexpected_payload",
                "stock_id": sid, "raw": data, "window_note": WINDOW_NOTE}
    counts: Dict[str, Any] = {}
    missing: list[str] = []
    for name in COUNT_FIELDS:
        val = data.get(name)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            counts[name] = None
            missing.append(name)
        else:
            counts[name] = val
    out: Dict[str, Any] = {
        "ok": True,
        "stock_id": sid,
        "counts": counts,
        "count_labels": {"announcement": "公告", "report": "研报", "news": "新闻"},
        "upstream_date": str(data.get("Date") or "") or None,
        "raw": {k: data.get(k) for k in ("news", "report", "announcement", "CID", "Date")},
        "window_note": WINDOW_NOTE,
    }
    if missing:
        out["partial"] = True
        out["missing_fields"] = missing
    return out


def get_notice_count(stock_id: str) -> Dict[str, Any]:
    """读口（单股）：{ok, stock_id, counts, upstream_date, window_note}，fail-visible 降级。"""
    try:
        raw = fetch_notice_count_raw(stock_id)
    except Exception as exc:   # KplRankingError/HTTP 层异常 → 结构化降级（不伪装空计数）
        reason = getattr(exc, "errorCode", "") or type(exc).__name__
        return {"ok": False, "degraded": True, "reason": str(reason)[:60],
                "error": str(getattr(exc, "error", "") or exc)[:120],
                "stock_id": stock_id, "raw": None, "window_note": WINDOW_NOTE}
    return parse_notice_count(raw, stock_id=stock_id)
