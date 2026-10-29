# -*- coding: utf-8 -*-
"""题材龙头 JEV 语料 · 龙虎榜事实段（2026-10-29，task-6；方向线 C 级补采第 4 条落地）。

原料（全部纯事实，不喂任何引擎判断产物——遵守 audit §4 禁喂清单）：
- 2112 ForecastLHBResp 快照（kpl_collector 读口）：reason（上榜原因偏离值口径）、
  plate（概念标签）、hot_val（KPL 热度）、main_net_amount/mainBuy/mainSell（盘中主力
  大单资金流，元原样，口径见 docs/kpl-socket/lhb-scaling-verification.md）；
- HisBeOnTheLHB 历史（kpl_lhb_history）：交易所分组榜单 Reason + stockList、个股行
  22 列（同字段族）。

「jev 语料管道入口」= 方向线 ammo 模块（jev_driver_ammo/jev_resonance_ammo 同构）：
本模块提供 collect_lhb_facts（取数+归一）与 build_lhb_facts_lines（事实行组装），
方向线叙事层按需引用。本模块不调用 jev（红线 7），取数失败走结构化降级不伪装。

pytest 纪律：fetch 读口注入 mock；零真实 KPL/jev 调用。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID  # noqa: F401（与方向线同源约定）
from backend.services import kpl_lhb_history

AMMO_VERSION_LHB = "2026-10-29a"


def collect_lhb_facts(date: str, *, _fetch_list=None, _fetch_stock=None) -> Dict[str, Any]:
    """按日收集龙虎榜事实（历史链为主；失败结构化降级，不伪装空）。

    返回 {ok, date, version, groups, stocks, degraded/reason}。
    groups: [{reason, bid, stocks:[{code,name,price,deviation,amount_yuan,turn}]}]；
    stocks: [{code,name,plate,price,zf,main_net_yuan,main_buy_yuan,main_sell_yuan,reason}]。
    """
    out: Dict[str, Any] = {"ok": False, "date": date, "version": AMMO_VERSION_LHB,
                           "groups": [], "stocks": []}
    try:
        raw_list = (_fetch_list or kpl_lhb_history.fetch_his_lhb_list)(date)
        parsed_list = kpl_lhb_history.parse_his_lhb_list(raw_list)
    except Exception as exc:
        out["degraded"] = True
        out["reason"] = f"lhb_list_fetch_failed: {exc}"
        parsed_list = None
    try:
        raw_stock = (_fetch_stock or kpl_lhb_history.fetch_his_lhb_stock)(date)
        parsed_stock = kpl_lhb_history.parse_his_lhb_stock(raw_stock)
    except Exception as exc:
        out["degraded"] = True
        out.setdefault("reasons", []).append(f"lhb_stock_fetch_failed: {exc}")
        out["reason"] = out.get("reason") or f"lhb_stock_fetch_failed: {exc}"
        parsed_stock = None
    if parsed_list is None and parsed_stock is None:
        return out
    groups: List[Dict[str, Any]] = []
    for g in (parsed_list or {}).get("groups") or []:
        groups.append({
            "reason": g.get("reason", ""),
            "bid": g.get("bid", ""),
            "stocks": [{
                "code": s[0] if len(s) > 0 else "",
                "name": s[1] if len(s) > 1 else "",
                "price": s[2] if len(s) > 2 else None,
                "deviation": s[3] if len(s) > 3 else None,
                "amount_yuan": s[4] if len(s) > 4 else None,
                "turn": s[5] if len(s) > 5 else None,
            } for s in g.get("stocks") or [] if isinstance(s, list) and s],
        })
    stocks: List[Dict[str, Any]] = [{
        "code": r.get("stock_id", ""),
        "name": r.get("stock_name", ""),
        "plate": r.get("plate", ""),
        "price": r.get("price"),
        "zf": r.get("zf"),
        # 元原样（task-3 裁决）：mainBuy+mainSell=mainNetAmount，卖出记负
        "main_net_yuan": r.get("main_net_amount"),
        "main_buy_yuan": r.get("main_buy"),
        "main_sell_yuan": r.get("main_sell"),
        "reason": r.get("reason", ""),
    } for r in (parsed_stock or {}).get("rows") or []]
    out.update({
        "ok": bool(groups or stocks),
        "groups": groups,
        "stocks": stocks,
        "empty_structured": bool(parsed_list and not groups
                                 and (parsed_list.get("order_sign") or [])),
        "order_sign_count": len((parsed_list or {}).get("order_sign") or []),
    })
    return out


def _fmt_yi(v: Any) -> str:
    """元 → 亿字符串（非数值回 '--'，不伪装 0）。"""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "--"
    return f"{n / 1e8:.2f}亿"


def build_lhb_facts_lines(facts: Dict[str, Any], *, max_groups: int = 6,
                          max_stocks_per_group: int = 5) -> List[str]:
    """龙虎榜事实 → 语料行（纯事实组装；空数据显式「--」不产伪行）。"""
    lines: List[str] = []
    if not facts:
        return ["龙虎榜：--（no_data）"]
    if facts.get("empty_structured"):
        lines.append(f"龙虎榜：--（当日分组榜单未生成；上游 orderSign={facts.get('order_sign_count')} 组）")
        return lines
    if not facts.get("ok"):
        lines.append(f"龙虎榜：--（未取到当日数据；{facts.get('reason', 'no_data')}）")
        return lines
    for g in (facts.get("groups") or [])[:max_groups]:
        stocks = (g.get("stocks") or [])[:max_stocks_per_group]
        if not stocks:
            continue
        seg = "；".join(
            f"{s.get('code')} {s.get('name')}"
            f" 偏离{s.get('deviation') if s.get('deviation') not in (None, '') else '--'}"
            f" 额{_fmt_yi(s.get('amount_yuan'))}"
            for s in stocks)
        lines.append(f"龙虎榜·{g.get('reason') or '未知原因'}：{seg}")
    for s in (facts.get("stocks") or [])[:max_groups * max_stocks_per_group]:
        net = _fmt_yi(s.get("main_net_yuan"))
        lines.append(f"龙虎榜个股·{s.get('code')} {s.get('name')}"
                     f"（{s.get('plate') or '--'}）：主力净额{net}，原因 {s.get('reason') or '--'}")
    if not lines:
        lines.append("龙虎榜：--（当日无上榜分组与个股行）")
    return lines
