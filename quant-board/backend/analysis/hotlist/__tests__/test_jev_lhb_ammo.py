# -*- coding: utf-8 -*-
"""jev_lhb_ammo 测试：取数注入 mock（零真实 KPL/jev，红线 7）；事实行纯组装。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import jev_lhb_ammo as ammo  # noqa: E402


LIST_RAW = {"errcode": "0", "date": "2026-10-28", "YCnum": 1,
            "orderSign": [], "info": [
                {"BID": "1", "Reason": "沪市主板:日价格偏离值达到7%前5只证券",
                 "Index": ["日偏离值;6"],
                 "stockList": [["600715", "文投控股", "10.16", "7.96", "432493211", "15.08"]]}]}
STOCK_RAW = {"errcode": "0", "Count": 1, "info": [
    ["603696", "安记食品", "食品加工、社区团购", "14.31", "-10", "16.38", "562678136",
     "-0.069832", "-27469779", "49176780", "-76646559", "38.72", "3365712000",
     "3365712000", "1423696176", "5.79", "", "3739", "3", "偏离-7%", "1793170523", "1"]]}


class TestCollectLhbFacts:
    def test_collect_ok(self):
        facts = ammo.collect_lhb_facts("2026-10-28",
                                       _fetch_list=lambda d: LIST_RAW,
                                       _fetch_stock=lambda d: STOCK_RAW)
        assert facts["ok"] is True and facts["date"] == "2026-10-28"
        g = facts["groups"][0]
        assert "偏离值达到7%" in g["reason"] and g["stocks"][0]["code"] == "600715"
        s = facts["stocks"][0]
        assert s["main_net_yuan"] == "-27469779"     # 元原样（task-3 裁决）
        assert s["plate"] == "食品加工、社区团购" and s["reason"] == "偏离-7%"

    def test_collect_degraded_not_fake_empty(self):
        def boom(d):
            raise RuntimeError("upstream limit")
        facts = ammo.collect_lhb_facts("2026-10-28", _fetch_list=boom, _fetch_stock=boom)
        assert facts["ok"] is False and facts["degraded"] is True
        assert "lhb_list_fetch_failed" in facts["reason"]

    def test_collect_structured_empty(self):
        # 当日未生成：info=[] + orderSign 非空 → 结构化空态（非降级非伪装）
        facts = ammo.collect_lhb_facts(
            "2026-10-29",
            _fetch_list=lambda d: {"errcode": "0", "date": d, "YCnum": 0,
                                   "orderSign": ["19", "20"], "info": []},
            _fetch_stock=lambda d: {"errcode": "0", "Count": 0, "info": []})
        assert facts["ok"] is False
        assert facts["empty_structured"] is True and facts["order_sign_count"] == 2


class TestBuildLines:
    def test_lines_facts_only_no_engine_output(self):
        facts = ammo.collect_lhb_facts("2026-10-28",
                                       _fetch_list=lambda d: LIST_RAW,
                                       _fetch_stock=lambda d: STOCK_RAW)
        lines = ammo.build_lhb_facts_lines(facts)
        assert any("偏离值达到7%" in l and "600715" in l for l in lines)
        assert any("4.32亿" in l for l in lines)          # 432493211 元 → 4.32亿
        assert any("主力净额-0.27亿" in l for l in lines)  # -27469779 → -0.27亿
        # 禁喂纪律：事实行不得含引擎判断词
        for l in lines:
            assert not any(w in l for w in ("finalSignal", "compScore", "tier", "买入", "卖出建议"))

    def test_lines_empty_structured_explicit(self):
        facts = {"ok": False, "empty_structured": True, "order_sign_count": 11,
                 "groups": [], "stocks": [], "date": "2026-10-29"}
        lines = ammo.build_lhb_facts_lines(facts)
        assert len(lines) == 1 and "orderSign=11" in lines[0] and "--" in lines[0]

    def test_lines_no_data_explicit_dash(self):
        lines = ammo.build_lhb_facts_lines({"ok": False, "reason": "lhb_list_fetch_failed: x"})
        assert lines == ["龙虎榜：--（未取到当日数据；lhb_list_fetch_failed: x）"]
