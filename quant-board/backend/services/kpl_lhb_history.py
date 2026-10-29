# -*- coding: utf-8 -*-
"""KPL 龙虎榜历史回看链（HisBeOnTheLHB HTTP，2026-10-29 逆向 sb0.j/h + j00.D1/mo0.d + 开火实测）。

端点合同（**a/c 与 D1 参数顺序互换是本链关键坑**：请求键为 a=OnTheLHBList/OnTheLHBStock、
c=HisBeOnTheLHB——D1 第一参数放 c、第二参数放 a，侦察笔记初版记反导致 1020）：
- POST https://apphis.longhuvip.com/w1/api/index.php
- a=OnTheLHBList&c=HisBeOnTheLHB&Date=YYYY-MM-DD          → 按上榜原因分组榜单（sb0.j）
- a=OnTheLHBStock&c=HisBeOnTheLHB&Date=YYYY-MM-DD          → 个股历史行 22 列（sb0.h）
- 全局五件套 DeviceID/apiv/PhoneOSNew/VerSion/Red + 凭据（HttpUtils.n 同源，
  从 KPL_APP_BASE_PARAMS 公共出口取，禁止另拷凭据常量）。

OnTheLHBList 响应：{errcode, date, YCnum, orderSign[], ttag,
  info: [{BID, Reason("沪市主板:日价格偏离值达到7%前5只证券"), Index:["日偏离值;6",...],
          stockList: [[stockId, name, price, ?, amount, ?, ...12 列], ...]}]}
当日未生成时 info=[] 且 orderSign 给出全量 BID 集合（fail-visible 结构化空态，非零伪装）。

OnTheLHBStock 响应：{errcode, Count, ttag, info: [[stockId, name, plate, price, zf, tur?,
  amount, incSpeed?, mainNetAmount, mainBuy, mainSell, realTur?, cirMarket, ttlMarket,
  realCirMarket, amplitude, incRateText?, hotVal?, hotChange?, reason, ts, isNew], ...]}
字段族与 2112 ForecastLHBResp.Item 同源（reason/timestamp/isNew 尾部对位）；
数值列缩放口径已经 task-3 交叉验证裁决：**元原样无缩放**（2026-10-28 603696 双源
比对：成交额/市值精确一致，mainNetAmount 与东财主力净流入差 0.18%），详见
 docs/kpl-socket/lhb-scaling-verification.md；mainBuy+mainSell=mainNetAmount（卖出记负）。
解析层原样保留 raw 数组，不建转换层。

pytest 纪律：parse_* 为纯函数全 mock 覆盖；fetch_* 仅在人工运维路径真实调用
（AGENTS.md 红线 7），上游限频约分钟级 1 发（HisDaBanList 先例），30s TTL 缓存按日共享。
"""
from __future__ import annotations

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
_CACHE_TTL_SECONDS = 30.0
_CACHE_MAX_KEYS = 64        # 逐出上限：写前清理过期项，超限全清（按日 key 防长期累积）


def _global_params() -> Dict[str, Any]:
    """全局五件套 + 凭据（与 HttpUtils.n 同源，凭据单一事实源）。"""
    creds = {k: KPL_APP_BASE_PARAMS[k] for k in ("UserID", "DeviceID", "Token")}
    return {"apiv": "w48", "VerSion": "6.3.20.2", "PhoneOSNew": 1, "Red": 0, **creds}


def _fetch_cached(key: str, params: Dict[str, Any]) -> Dict[str, Any]:
    cached = _CACHE.get(key)
    if cached and time.time() - cached["ts"] < _CACHE_TTL_SECONDS:
        return cached["data"]
    now = time.time()
    # 逐出：过期项清理；超上限全清（缓存只做限频减负，逐出不损正确性）
    for k in [k for k, v in _CACHE.items() if now - v["ts"] >= _CACHE_TTL_SECONDS]:
        _CACHE.pop(k, None)
    if len(_CACHE) >= _CACHE_MAX_KEYS:
        _CACHE.clear()
    data = _post_form(_HOST_HISTORY, params, _UA_STOCKS)
    _check_errcode(data)
    _CACHE[key] = {"ts": time.time(), "data": data}
    return data


def fetch_his_lhb_list(date: str) -> Dict[str, Any]:
    """按日拉「会不会上龙虎榜·历史榜单」分组数据（上游限频，30s TTL 按日共享）。"""
    return _fetch_cached(f"lhbl:{date}",
                         {"a": "OnTheLHBList", "c": "HisBeOnTheLHB", "Date": date,
                          **_global_params()})


def fetch_his_lhb_stock(date: str) -> Dict[str, Any]:
    """按日拉龙虎榜个股历史行（同上限频/TTL）。"""
    return _fetch_cached(f"lhbs:{date}",
                         {"a": "OnTheLHBStock", "c": "HisBeOnTheLHB", "Date": date,
                          **_global_params()})


# ── 纯解析（pytest 覆盖面） ────────────────────────────────────────────────


def parse_his_lhb_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """OnTheLHBList → 结构化（分组榜单；info 空时保留 orderSign 结构化空态，不伪装）。"""
    info = data.get("info") or []
    groups: List[Dict[str, Any]] = []
    dropped = 0
    for g in info if isinstance(info, list) else []:
        if not isinstance(g, dict):
            dropped += 1
            continue
        stocks = [list(row) for row in (g.get("stockList") or []) if isinstance(row, list) and row]
        dropped += len(g.get("stockList") or []) - len(stocks)
        groups.append({
            "bid": g.get("BID", ""),
            "reason": g.get("Reason", ""),
            "index_cols": [c for c in (g.get("Index") or []) if isinstance(c, str)],
            "stocks": stocks,
        })
    return {
        "ok": True,
        "date": data.get("date", ""),
        "yc_num": data.get("YCnum", 0),
        "groups": groups,
        "order_sign": [str(x) for x in (data.get("orderSign") or [])],
        "raw_group_count": len(groups),
        "dropped": dropped,          # 非 dict 分组/非 list 行丢弃计数（fail-visible 聚合）
        "raw_len": len(json_bytes(data)),
    }


def parse_his_lhb_stock(data: Dict[str, Any]) -> Dict[str, Any]:
    """OnTheLHBStock → 结构化行（数值列原样保留 raw，缩放口径由 task-3 裁决）。"""
    info = data.get("info") or []
    rows: List[Dict[str, Any]] = []
    dropped = 0
    for r in info if isinstance(info, list) else []:
        if not (isinstance(r, list) and len(r) >= 21):
            dropped += 1
            continue
        rows.append({
            "stock_id": str(r[0]),
            "stock_name": str(r[1]),
            "plate": str(r[2]),
            "price": r[3],
            "zf": r[4],
            "raw": r,               # 22 列原样（fail-visible，语义随 task-3 增量落注）
            "main_net_amount": r[8] if len(r) > 8 else None,
            "main_buy": r[9] if len(r) > 9 else None,
            "main_sell": r[10] if len(r) > 10 else None,
            "reason": str(r[19]),
            "ts": r[20],
            "is_new": r[21] == "1" if len(r) > 21 else None,
        })
    return {
        "ok": True,
        "count": data.get("Count", len(rows)),
        "rows": rows,
        "dropped": dropped,          # 短行/非 list 行丢弃计数（fail-visible 聚合）
        "raw_len": len(json_bytes(data)),
    }


def json_bytes(data: Any) -> bytes:
    import json
    return json.dumps(data, ensure_ascii=False).encode("utf-8")
