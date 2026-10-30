# -*- coding: utf-8 -*-
"""KPL 龙虎榜营业部榜链（GetBusinessList HTTP，2026-10-29 逆向 j00.F + le0.p + 开火实测）。

端点合同（a/c 与 D1 参数互换规同龙虎榜历史链：**D1 第一参数→c、第二参数→a**）：
- POST https://applhb.longhuvip.com/w1/api/index.php（API_LHB 专用域，le0.p()）
- a=GetBusinessList&c=LongHuBang&Time=YYYY-MM-DD&Index=0&Type=0&STAT_SDK_TYPE=500
  + 全局五件套 + 凭据（复用 kpl_lhb_history._global_params，凭据单一事实源）
- App 入口：个股图表页「龙虎榜」ViewPager「营业部」页签（ChartsFragment.java:231，
  ChartsSalePresenter → ox0.Z → j00.F，每页 100；STAT_SDK_TYPE 位实测放行 500 一页全量）

响应（2026-10-29 开火 2 发，证据 .tmp_review/lhbsale_probe_results.jsonl）：
{errcode, Time, Total, sDay, list: [{ID, Name(营业部名), Buy(买入额元), Sell(卖出额元),
  JoinNum(参与上榜次数)}]}
- 资金口径同 task-3 裁决：**元原样无缩放**（Buy/Sell 为浮点字符串，不建转换层）
- 当日盘前/盘中 list=[] Total=0（营业部榜约 17:00 盘后生成，结构化空态非降级）
- 同族接入（2026-10-30 开火实测，AMMO 语料扩维）：
  - **GetStockList（营业部个股榜）**：同参数合同，`list` 每股一行（当日 69 行，
    STAT_SDK_TYPE=500 一页全量）：{ID(代码), Name, IncreaseAmount(涨幅), D3, BuyIn(席位
    买入额元), JoinNum(4，疑席位/营业部家数，语义待证不渲染), Turnover(成交额元),
    CircPrice(流通市值), Amplitude, TurnoverRatio, Capitalization(总市值)}；另有
    `Count` 字典 {code: int}（语义未考，原样透传不消费）；当日 601188 BuyIn=1.21亿。
  - **GetAgencyListV2（机构榜）**：同参数合同，`List`（大写 L，注意与 GetBusinessList
    的 list 不同）每股一行（当日 42 行）：{ID(代码), Name, Day, BuyIn(**机构净买额元**，
    负=净卖出), JoinNum(机构家数), Turnover, IncreaseAmount, FengKou(风口代码，不消费)}；
    tag="lv2"。
- 同族 UpdateList（未接，边界显式）

pytest 纪律：parse 为纯函数全 mock 覆盖；fetch 仅人工运维路径真实调用（红线 7），
上游限频分钟级，30s TTL 缓存按日+Type 共享。
"""
from __future__ import annotations

from typing import Any, Dict, List

from backend.services.kpl_lhb_history import (
    _UA_STOCKS,
    _check_errcode,
    _fetch_cached,
    _global_params,
)

_HOST_SALE = "https://applhb.longhuvip.com/w1/api/index.php"   # API_LHB（le0.p 默认值）


def fetch_lhb_sale(date: str, type_: int = 0) -> Dict[str, Any]:
    """按日拉营业部成交榜（上游限频，30s TTL 按 date+Type 共享；STAT_SDK_TYPE=500 一页全量）。"""
    return _fetch_cached(f"sale:{type_}:{date}",
                         {"a": "GetBusinessList", "c": "LongHuBang", "Time": date,
                          "Index": "0", "Type": str(type_), "STAT_SDK_TYPE": "500",
                          **_global_params()}, host=_HOST_SALE, ua=_UA_STOCKS)


def fetch_lhb_stock_list(date: str) -> Dict[str, Any]:
    """按日拉营业部个股榜 GetStockList（同域同限频；30s TTL 按日共享）。"""
    return _fetch_cached(f"salestock:{date}",
                         {"a": "GetStockList", "c": "LongHuBang", "Time": date,
                          "Index": "0", "Type": "0", "STAT_SDK_TYPE": "500",
                          **_global_params()}, host=_HOST_SALE, ua=_UA_STOCKS)


def parse_lhb_stock_list(data: Dict[str, Any]) -> Dict[str, Any]:
    """GetStockList → 结构化行（金额元原样；非 dict/缺 ID 行丢弃计数 fail-visible）。"""
    lst = data.get("list") or []
    rows: List[Dict[str, Any]] = []
    dropped = 0
    for r in lst if isinstance(lst, list) else []:
        if not (isinstance(r, dict) and r.get("ID")):
            dropped += 1
            continue
        rows.append({
            "code": str(r.get("ID", "")),
            "name": str(r.get("Name", "")),
            "buy_in": r.get("BuyIn"),        # 净买入（2026-10-30 实测与 App 净买入列逐分一致，
                                             # 非席位买入额；元原样）
            "join_num": r.get("JoinNum"),    # 疑席位家数，语义待证不渲染
            "turnover": r.get("Turnover"),   # 成交额，元原样
            "turnover_ratio": r.get("TurnoverRatio"),  # 换手率（原样字符串，如 "37.05"）
            "increase_amount": r.get("IncreaseAmount"),
            "raw": r,                        # 原样保留（fail-visible，语义增量落注）
        })
    return {
        "ok": True,
        "date": data.get("Time", ""),
        "total": data.get("Total", len(rows)),
        "rows": rows,
        "dropped": dropped,
        # Count 字典 {code: int} 语义未考，原样透传不消费（防伪装读数）
        "count_map": data.get("Count") if isinstance(data.get("Count"), dict) else None,
        "raw_len": len(str(data)),
    }


def fetch_lhb_agency(date: str) -> Dict[str, Any]:
    """按日拉机构榜 GetAgencyListV2（同域同限频；30s TTL 按日共享）。"""
    return _fetch_cached(f"agency:{date}",
                         {"a": "GetAgencyListV2", "c": "LongHuBang", "Time": date,
                          "Index": "0", "Type": "0", "STAT_SDK_TYPE": "500",
                          **_global_params()}, host=_HOST_SALE, ua=_UA_STOCKS)


def parse_lhb_agency(data: Dict[str, Any]) -> Dict[str, Any]:
    """GetAgencyListV2 → 结构化行（`List` 大写 L；BuyIn 可负=净卖出，元原样）。"""
    lst = data.get("List") or []
    rows: List[Dict[str, Any]] = []
    dropped = 0
    for r in lst if isinstance(lst, list) else []:
        if not (isinstance(r, dict) and r.get("ID")):
            dropped += 1
            continue
        rows.append({
            "code": str(r.get("ID", "")),
            "name": str(r.get("Name", "")),
            "buy_in": r.get("BuyIn"),        # 机构净买额，元原样，负=净卖出
            "join_num": r.get("JoinNum"),    # 机构家数
            "turnover": r.get("Turnover"),
            "increase_amount": r.get("IncreaseAmount"),
            "raw": r,
        })
    return {
        "ok": True,
        "date": data.get("Time", "") or data.get("Day", ""),
        "rows": rows,
        "dropped": dropped,
        "raw_len": len(str(data)),
    }


def parse_lhb_sale(data: Dict[str, Any]) -> Dict[str, Any]:
    """GetBusinessList → 结构化行（金额元原样保留；非 dict 行丢弃计数 fail-visible）。"""
    lst = data.get("list") or []
    rows: List[Dict[str, Any]] = []
    dropped = 0
    for r in lst if isinstance(lst, list) else []:
        if not isinstance(r, dict):
            dropped += 1
            continue
        rows.append({
            "sale_id": str(r.get("ID", "")),
            "name": str(r.get("Name", "")),
            "buy": r.get("Buy"),            # 元原样（字符串浮点，不缩放）
            "sell": r.get("Sell"),
            "join_num": r.get("JoinNum"),
            "raw": r,                       # 原样保留（fail-visible，字段语义增量落注）
        })
    return {
        "ok": True,
        "date": data.get("Time", ""),
        "total": data.get("Total", len(rows)),
        "rows": rows,
        "dropped": dropped,                 # 非 dict 行丢弃计数（fail-visible 聚合）
        "raw_len": len(str(data)),
    }
