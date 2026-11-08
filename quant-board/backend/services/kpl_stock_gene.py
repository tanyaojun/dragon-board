# -*- coding: utf-8 -*-
"""KPL 涨停基因（溢价基因）协议层（apphq StockL2Data/GetZhangTingGene，2026-11-08 探测实弹）。

背景：个股详情页「涨停基因」统计（涨停次数/溢价 5% 次数/次日红盘率/首板封板率/首板被板率/
连板率）是题材龙头语料的关键维度；2026-11-08 HTTP 全表探测命中本端点（errcode=0），
本模块只做协议层（fetch/parse/读口），落库由 kpl_daban_archiver 的 gene_ 通道消费。

端点合同（.tmp_review/kpl_stockpage_probe_results_2026-11-08.jsonl tag=premium_gene）：
- POST https://apphq.longhuvip.com/w1/api/index.php
- c=StockL2Data&a=GetZhangTingGene&StockID=<单股> + 公共参数（凭据走 KPL_APP_BASE_PARAMS
  公共出口；游客 UserID/Token=0 亦可）
- 响应 {"List": [涨停次数, 溢价5%次数, 次日红盘率%, 首板封板率%, 首板被板率%, 连板率%],
  "ttag": ..., "errcode": "0"}——六元数组，实测 301697 = [4,1,50,100,0,50]，
  与 App 盘口 tab 逐项一致（来源 ox0.s5().i4）；
- **统计窗口上游未标注**（App 与源码均无天数常量）→ window_note 原样透出，禁止自算/反推；
- 单股粒度、无按日批量版 → 全池语料只能逐股懒取（复用 _post_form 全局 ≥2s 单发间隔锁）。

pytest 纪律：parse 纯函数全 mock；fetch 仅人工运维/JEV 语料补拉路径真实调用（红线 7）。
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List

from backend.services.kpl_ranking_service import (
    _UA_STOCKS,
    _check_errcode,
    _post_form,
)
from backend.services.theme.mapping_refresh import KPL_APP_BASE_PARAMS

_HOST_HQ = "https://apphq.longhuvip.com/w1/api/index.php"   # API_HQ（个股 L2/详情域）
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL_SECONDS = 300.0
_CACHE_MAX_KEYS = 2000

# 六元数组逐位语义（顺序即上游顺序，App 盘口 tab「涨停基因」逐项对齐）
GENE_FIELDS: tuple[tuple[int, str, str], ...] = (
    (0, "zt_count", "涨停次数"),
    (1, "premium5_count", "溢价5%次数"),
    (2, "next_day_red_pct", "次日红盘率%"),
    (3, "first_seal_pct", "首板封板率%"),
    (4, "first_broken_pct", "首板被板率%"),
    (5, "lianban_pct", "连板率%"),
)
WINDOW_NOTE = "上游未标注统计窗口（六元数组原样透出，不自算不反推）"


def _global_params() -> Dict[str, Any]:
    """公共参数（凭据单一事实源=KPL_APP_BASE_PARAMS；其余按 2026-11-08 实测组合）。"""
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    return {"apiv": "w38", "VerSion": "5.16.0.5", "PhoneOSNew": "2", **creds}


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


def fetch_zt_gene_raw(stock_id: str) -> Dict[str, Any]:
    """单股涨停基因原始响应（带缓存；真实调用仅运维/语料补拉路径，pytest 全 mock）。"""
    cached = _CACHE.get(stock_id)
    if cached and time.time() - cached["ts"] < _CACHE_TTL_SECONDS:
        return cached["data"]
    _pytest_guard()
    if len(_CACHE) >= _CACHE_MAX_KEYS:
        _CACHE.clear()
    data = _post_form(_HOST_HQ,
                      {"a": "GetZhangTingGene", "c": "StockL2Data",
                       "StockID": stock_id, **_global_params()},
                      _UA_STOCKS)
    _check_errcode(data)
    _CACHE[stock_id] = {"ts": time.time(), "data": data}
    return data


def parse_zt_gene(data: Dict[str, Any], *, stock_id: str = "") -> Dict[str, Any]:
    """六元数组 → 具名字段 + raw 原样保留（缺位不补 0，partial 标记 fail-visible）。

    上游若返回非数组/短数组：raw 原样留档，缺失位为 None 并置 partial=True——不把
    「未拿到」伪装成 0（AGENTS §4.0）。
    """
    raw = data.get("List")
    sid = str(data.get("StockID") or stock_id or "")
    if not isinstance(raw, list):
        return {"ok": False, "degraded": True, "reason": "unexpected_payload",
                "stock_id": sid, "raw": raw, "window_note": WINDOW_NOTE}
    gene: Dict[str, Any] = {}
    missing: List[str] = []
    for idx, name, label in GENE_FIELDS:
        val = raw[idx] if idx < len(raw) else None
        if val is None or isinstance(val, (dict, list)):
            gene[name] = None
            missing.append(name)
        else:
            gene[name] = val
    out: Dict[str, Any] = {
        "ok": True,
        "stock_id": sid,
        "gene": gene,
        "gene_labels": {name: label for _, name, label in GENE_FIELDS},
        "raw": list(raw),
        "raw_len": len(raw),
        "window_note": WINDOW_NOTE,
    }
    if missing:
        out["partial"] = True
        out["missing_fields"] = missing
    return out


def get_zt_gene(stock_id: str) -> Dict[str, Any]:
    """读口（单股）：{ok, stock_id, gene, raw, window_note}，fail-visible 结构化降级。"""
    try:
        raw = fetch_zt_gene_raw(stock_id)
    except Exception as exc:   # KplRankingError/HTTP 层异常 → 结构化降级（不伪装空基因）
        reason = getattr(exc, "errorCode", "") or type(exc).__name__
        return {"ok": False, "degraded": True, "reason": str(reason)[:60],
                "error": str(getattr(exc, "error", "") or exc)[:120],
                "stock_id": stock_id, "raw": None, "window_note": WINDOW_NOTE}
    return parse_zt_gene(raw, stock_id=stock_id)