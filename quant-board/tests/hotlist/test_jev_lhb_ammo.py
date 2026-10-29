# -*- coding: utf-8 -*-
"""jev_lhb_ammo.collect_lhb_facts 集成测试（2026-10-30c 席位/机构扩维）。

全 mock 零真实调用（AGENTS 红线 7）；逐端点独立 fail-visible 断言。
"""
from __future__ import annotations

from backend.analysis.hotlist import jev_lhb_ammo as J


def _raw_list():
    return {"errcode": "0", "info": [
        {"BID": "1", "Reason": "偏离7%前5", "Index": ["日偏离值;6"],
         "stockList": [["601188", "龙江交通", "5.1", "7.0", 1e8, "1.0"]]},
    ], "orderSign": []}


def _raw_stock():
    rows = [["601188", "龙江交通", "公路", 5.1, 10.0, 1.0, 1e8, 0.1,
             2.38e8, 3.84e8, -1.46e8, 1.0, 1e9, 2e9, 1e9, 3.0, "10.06%", 100, 1,
             "偏离7%", "2026-10-29 17:00:00", "0"]]
    return {"errcode": "0", "Count": 1, "info": rows}


def _raw_stock_board():
    return {"errcode": "0", "Time": "2026-10-29", "Total": 1, "list": [
        {"ID": "601188", "Name": "龙江交通", "BuyIn": "121003701.36",
         "JoinNum": 4, "Turnover": 642104876, "IncreaseAmount": "10.06%"},
    ], "Count": {"601188": 46980}}


def _raw_agency():
    return {"errcode": "0", "Time": "2026-10-29", "Day": "2026-10-29", "tag": "lv2",
            "List": [{"ID": "601188", "Name": "龙江交通", "BuyIn": 3225162.13,
                      "JoinNum": 1, "Turnover": 191263535}]}


def test_collect_joins_stock_board_and_agency():
    facts = J.collect_lhb_facts(
        "2026-10-29", _fetch_list=lambda d: _raw_list(),
        _fetch_stock=lambda d: _raw_stock(),
        _fetch_stock_board=lambda d: _raw_stock_board(),
        _fetch_agency=lambda d: _raw_agency())
    assert facts["ok"] is True
    assert facts["version"] == "2026-10-30c"
    assert facts["stocks"][0]["code"] == "601188"
    assert facts["stock_board"]["601188"]["buy_in"] == "121003701.36"
    assert facts["agency"]["601188"]["buy_in"] == 3225162.13
    assert not facts.get("degraded") and not facts.get("reasons")


def test_agency_failure_degrades_without_killing_main_chain():
    """机构榜端点失败：degraded + 结构化 reason，主链 stocks/stock_board 不受拖垮（§4.0）。"""
    def boom(date):
        raise RuntimeError("upstream 500")
    facts = J.collect_lhb_facts(
        "2026-10-29", _fetch_list=lambda d: _raw_list(),
        _fetch_stock=lambda d: _raw_stock(),
        _fetch_stock_board=lambda d: _raw_stock_board(),
        _fetch_agency=boom)
    assert facts["ok"] is True and facts["stocks"]
    assert facts["stock_board"]["601188"]["buy_in"] == "121003701.36"
    assert facts["agency"] == {}
    assert facts["degraded"] is True
    assert any(r.startswith("lhb_agency_fetch_failed") for r in facts.get("reasons") or [])


def test_stock_board_failure_also_structured():
    def boom(date):
        raise RuntimeError("upstream 500")
    facts = J.collect_lhb_facts(
        "2026-10-29", _fetch_list=lambda d: _raw_list(),
        _fetch_stock=lambda d: _raw_stock(),
        _fetch_stock_board=boom,
        _fetch_agency=lambda d: _raw_agency())
    assert facts["ok"] is True and facts["agency"]["601188"]
    assert facts["stock_board"] == {}
    assert any(r.startswith("lhb_stock_board_fetch_failed")
               for r in facts.get("reasons") or [])


def test_lhb_line_with_joined_facts_renders_full_segment():
    """端到端：collect 归一层 → lhb_line 席位/机构段渲染（601188 真实形状样本）。"""
    from backend.analysis.hotlist.theme_leader_ammo import lhb_line
    facts = J.collect_lhb_facts(
        "2026-10-29", _fetch_list=lambda d: _raw_list(),
        _fetch_stock=lambda d: _raw_stock(),
        _fetch_stock_board=lambda d: _raw_stock_board(),
        _fetch_agency=lambda d: _raw_agency())
    line = lhb_line(facts, codes=["601188"], roles={"601188": "主板龙一"})
    assert "主板龙一 龙江交通（601188）：主力净额 2.38亿" in line
    assert "席位买入 1.21亿" in line
    assert "机构净买 0.03亿（1 家）" in line
