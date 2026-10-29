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
- 同族 API：GetAgencyListV2（机构榜）/ GetStockList（个股榜）/ UpdateList（未接，边界显式）

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
