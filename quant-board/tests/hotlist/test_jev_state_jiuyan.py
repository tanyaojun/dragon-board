# -*- coding: utf-8 -*-
"""jev 打标 v2 叙事构建器测试（纯函数）+ day_population/fake db 测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist.jev_state import build_jiuyan_label_narrative
from backend.operations.jev_label_jiuyan import day_population


STOCK = {"code": "sh600825", "name": "新华传媒", "day": 7, "time": "09:25:00",
         "expound": "拟收购界面财联社+华字辈\n1、2026年9月18日盘后公告，公司拟发行股份购买界面财联社100%股权。"}


def test_narrative_normal_fields():
    out = build_jiuyan_label_narrative(STOCK, "公告", 3)
    assert out.startswith("新华传媒（600825）：")
    assert "7天7板" in out and "首次涨停 09:25:00" in out
    assert "热榜第3名" in out and "板块：公告" in out
    assert "拟收购界面财联社" in out


def test_narrative_prefix_stripped():
    out = build_jiuyan_label_narrative({**STOCK, "code": "sz000504"}, "医药医疗", None)
    assert "（000504）" in out
    assert not ("（sz000504）" in out)


def test_narrative_missing_day_means_first_board():
    out = build_jiuyan_label_narrative({**STOCK, "day": None}, "公告", 1)
    assert "首板" in out
    out1 = build_jiuyan_label_narrative({**STOCK, "day": 1}, "公告", 1)
    assert "首板" in out1
    assert "7天7板" not in out1


def test_narrative_missing_time_and_rank_fail_visible():
    out = build_jiuyan_label_narrative({**STOCK, "time": ""}, "公告", None)
    assert "涨停时间未提供" in out
    assert "未进热榜" in out
    assert "热榜第None名" not in out


def test_narrative_missing_expound_fail_visible():
    out = build_jiuyan_label_narrative({**STOCK, "expound": None}, "公告", 3)
    assert "缺失" in out  # 如实披露，不伪造原料


def test_narrative_cap_length():
    out = build_jiuyan_label_narrative({**STOCK, "expound": "长" * 5000}, "公告", 3)
    assert len(out) <= 1400


class _FakeCol:
    def __init__(self, doc):
        self._doc = doc

    def find_one(self, *_a, **_k):
        return self._doc


class _FakeDb(dict):
    def __init__(self, doc):
        super().__init__()
        self["jiuyan_action"] = _FakeCol(doc)


def test_day_population_uses_final_only():
    doc = {"_id": "2026-09-30:final", "fields": [
        {"name": "公告", "stocks": [{"code": "sh600825", "name": "新华传媒"}]},
        {"name": "医药医疗", "stocks": [{"code": "sz000504", "name": "南华生物"}]},
    ]}
    pop = day_population(_FakeDb(doc), "2026-09-30")
    assert [(p["stock"]["code"], p["board"]) for p in pop] == [
        ("sh600825", "公告"), ("sz000504", "医药医疗")]


def test_day_population_missing_date_returns_empty():
    assert day_population(_FakeDb(None), "2026-09-30") == []
