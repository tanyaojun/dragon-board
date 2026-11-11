# -*- coding: utf-8 -*-
"""题材龙头 JEV 语料 · 龙虎榜事实段（2026-10-29，task-6；方向线 C 级补采第 4 条落地）。

原料（全部纯事实，不喂任何引擎判断产物——遵守 audit §4 禁喂清单）：
- 2112 ForecastLHBResp 快照（kpl_collector 读口）：reason（上榜原因偏离值口径）、
  plate（概念标签）、hot_val（KPL 热度）、main_net_amount/mainBuy/mainSell（盘中主力
  大单资金流，元原样，口径见 docs/kpl-socket/lhb-scaling-verification.md）；
- HisBeOnTheLHB 历史（kpl_lhb_history）：交易所分组榜单 Reason + stockList、个股行
  22 列（同字段族）。

「jev 语料管道入口」= 方向线 ammo 模块（jev_driver_ammo 同构；原 jev_resonance_ammo
已随热榜行情页删除移除，2026-10-29）：
本模块提供 collect_lhb_facts（取数+归一）与 build_lhb_facts_lines（事实行组装），
方向线叙事层按需引用。本模块不调用 jev（红线 7），取数失败走结构化降级不伪装。

pytest 纪律：fetch 读口注入 mock；零真实 KPL/jev 调用。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID  # noqa: F401（与方向线同源约定）
from backend.services import kpl_lhb_history, kpl_lhb_sale

# 2026-10-30b：取数层分页修复（kpl_lhb_history 显式 st=300，默认页个股 9 行/分组 3 组
# 严重不全——10-29 全量实为 129 只，龙江交通 601188 漏配导致语料误称「0 只上榜」）。
# 判据/题集零变化（题集 hash 不动），仅事实完整性修复。
# 2026-10-30c：接入营业部个股榜（GetStockList，席位买入额）与机构榜（GetAgencyListV2，
# 机构净买额可负）——原 LHB 行只有盘中主力大单资金流口径，非交易所席位额；扩维后相关
# 个股可披露席位/机构事实。判据/题集零变化。
# 2026-11-11：增加结构化端点标志 list_ok/stock_ok（个股行端点失败时 groups 兜底 join，
# 已取得的分组榜单不得丢弃、更不得误称「全市场无上榜」——2026-11-11 语料丢龙虎榜数据
# 复盘）。判据/题集零变化。
AMMO_VERSION_LHB = "2026-11-11"


def collect_lhb_facts(date: str, *, _fetch_list=None, _fetch_stock=None,
                      _fetch_stock_board=None, _fetch_agency=None) -> Dict[str, Any]:
    """按日收集龙虎榜事实（历史链为主；失败结构化降级，不伪装空）。

    返回 {ok, date, version, groups, stocks, stock_board, agency, list_ok, stock_ok,
    degraded/reason}。groups: [{reason, bid, stocks:[{code,name,price,deviation,
    amount_yuan,turn}]}]；
    stocks: [{code,name,plate,price,zf,main_net_yuan,main_buy_yuan,main_sell_yuan,reason}]；
    stock_board: code → {name, buy_in(席位买入额元), join_num(语义待证不渲染), turnover}
      （GetStockList 营业部个股榜，2026-10-30c）；
    agency: code → {name, buy_in(机构净买额元，负=净卖出), join_num(机构家数), turnover}
      （GetAgencyListV2 机构榜，2026-10-30c）。两维缺席（端点失败/该股不在榜）不伪装。
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
    # 个股榜/机构榜扩维（2026-10-30c）：逐端点独立捕获，任一失败不拖垮主链（fail-visible）
    parsed_sb = None
    try:
        raw_sb = (_fetch_stock_board or kpl_lhb_sale.fetch_lhb_stock_list)(date)
        parsed_sb = kpl_lhb_sale.parse_lhb_stock_list(raw_sb)
    except Exception as exc:
        out["degraded"] = True
        out.setdefault("reasons", []).append(f"lhb_stock_board_fetch_failed: {exc}")
    parsed_ag = None
    try:
        raw_ag = (_fetch_agency or kpl_lhb_sale.fetch_lhb_agency)(date)
        parsed_ag = kpl_lhb_sale.parse_lhb_agency(raw_ag)
    except Exception as exc:
        out["degraded"] = True
        out.setdefault("reasons", []).append(f"lhb_agency_fetch_failed: {exc}")
    stock_board = {r["code"]: {"name": r["name"], "buy_in": r["buy_in"],
                               "join_num": r["join_num"], "turnover": r["turnover"]}
                   for r in (parsed_sb or {}).get("rows") or []}
    agency = {r["code"]: {"name": r["name"], "buy_in": r["buy_in"],
                          "join_num": r["join_num"], "turnover": r["turnover"]}
              for r in (parsed_ag or {}).get("rows") or []}
    out.update({
        "ok": bool(groups or stocks),
        "groups": groups,
        "stocks": stocks,
        "stock_board": stock_board,
        "agency": agency,
        # 端点级成功标志（2026-11-11）：叙事层区分「验证后的全市场无上榜」（双端点均成功
        # 且全空）与「个股行端点失败但分组榜单在手」（groups 兜底 join，不得丢弃）
        "list_ok": parsed_list is not None,
        "stock_ok": parsed_stock is not None,
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
