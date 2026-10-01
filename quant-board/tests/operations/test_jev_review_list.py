# -*- coding: utf-8 -*-
"""W1 复核工作台纯函数测试：三类分类、斜率、裁决保留、边界容差（无 Mongo）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_review_list import (
    build_review_items,
    merge_preserving_rulings,
    slopes_of_day,
)


def _mk(rule_slots, jev_slots, eod_scores=None, eod_stages=None, jev_eod=None, day_rets=None):
    return build_review_items(rule_slots, jev_slots, eod_scores or {}, eod_stages or {}, jev_eod or {}, day_rets or {})


def test_type_a_day_level_with_slot_table():
    """A 类为日级（2026-10-01 用户反馈）：一天一项，证据带全天槽位对照。"""
    rule = {("2026-09-08", "09:30"): {"stageCn": "启动", "score": 55.0},
            ("2026-09-08", "10:00"): {"stageCn": "发酵", "score": 62.0}}
    jev = {("2026-09-08", "09:30"): {"stage": "retreat", "confidence": 0.8, "temperature": 30.0, "narrativeHead": "…"},
           ("2026-09-08", "10:00"): {"stage": "retreat", "confidence": 0.9, "temperature": 32.0, "narrativeHead": None}}
    items = _mk(rule, jev)
    assert len(items) == 1 and items[0]["type"] == "A"
    assert items[0]["_id"] == "review:2026-09-08:DAY:A" and items[0]["slot"] == "DAY"
    assert items[0]["rule"]["stageSummary"] == "start×1、ferment×1"
    assert items[0]["jev"]["stageSummary"] == "retreat×2"
    assert len(items[0]["rule"]["slots"]) == 2 and len(items[0]["jev"]["slots"]) == 2
    # 同形态但非登记日 → 不产生任何项
    rule2 = {("2026-09-09", "10:00"): {"stageCn": "启动", "score": 55.0}}
    assert _mk(rule2, jev) == []


def test_type_b_rule_defense_vs_jev_offense():
    rule = {("2026-08-01", "10:00"): {"stageCn": "退潮", "score": 35.0},
            ("2026-08-01", "10:30"): {"stageCn": "启动", "score": 45.0}}
    jev = {("2026-08-01", "10:00"): {"stage": "start", "confidence": 0.6, "temperature": 20.0, "narrativeHead": None},
           ("2026-08-01", "10:30"): {"stage": "start", "confidence": 0.6, "temperature": 25.0, "narrativeHead": None}}
    items = _mk(rule, jev)
    assert [i["type"] for i in items] == ["B"]  # 只有 退潮×start 命中
    assert items[0]["rule"]["stage"] == "retreat" and items[0]["jev"]["stage"] == "start"


def test_type_c_boundary_eod_days():
    eod = {"2026-07-10": 42.5, "2026-07-11": 50.0, "2026-07-14": 57.2, "2026-07-15": 63.5}
    eod_stages = {"2026-07-10": "退潮", "2026-07-14": "启动"}
    jev_eod = {"2026-07-10": "retreat", "2026-07-14": "ferment"}
    items = _mk({}, {}, eod, eod_stages, jev_eod)
    by_date = {i["date"]: i for i in items}
    assert "2026-07-10" in by_date and by_date["2026-07-10"]["type"] == "C"
    assert by_date["2026-07-10"]["jev"]["dayStage"] == "retreat"
    assert by_date["2026-07-10"]["rule"]["nearEdge"] == 40
    assert "2026-07-14" in by_date and by_date["2026-07-14"]["rule"]["nearEdge"] == 60
    assert "2026-07-11" not in by_date and "2026-07-15" not in by_date  # 50 和 63.5 不贴界


def test_auto_consistent_when_stages_match():
    """口径一致（五档字面相等）→ 自动裁决 consistent；不同档保持 pending（2026-10-01 用户指令）。"""
    # A 类日级：全天两侧各自单档且相等 → consistent；混档或与 jev 不同 → pending
    rule_same = {("2026-09-08", "09:30"): {"stageCn": "退潮", "score": 35.0},
                 ("2026-09-08", "10:00"): {"stageCn": "退潮", "score": 33.0}}
    jev_same = {("2026-09-08", "09:30"): {"stage": "retreat", "confidence": 0.8, "temperature": 20.0, "narrativeHead": None},
                ("2026-09-08", "10:00"): {"stage": "retreat", "confidence": 0.9, "temperature": 22.0, "narrativeHead": None}}
    assert _mk(rule_same, jev_same)[0]["ruling"]["status"] == "consistent"
    rule_mixed = {("2026-09-08", "09:30"): {"stageCn": "启动", "score": 55.0},
                  ("2026-09-08", "10:00"): {"stageCn": "启动", "score": 58.0}}
    assert _mk(rule_mixed, jev_same)[0]["ruling"]["status"] == "pending"  # 启动 vs 退潮
    # B 类构造上必不同档 → 恒 pending
    rule_b = {("2026-08-01", "10:00"): {"stageCn": "退潮", "score": 35.0}}
    jev_b = {("2026-08-01", "10:00"): {"stage": "start", "confidence": 0.6, "temperature": 20.0, "narrativeHead": None}}
    assert _mk(rule_b, jev_b)[0]["ruling"]["status"] == "pending"
    # C 类：EOD 档位与 jev 日级同档 → consistent（59.1 启动 vs 发酵 不同档 → pending）
    eod = {"2026-07-10": 42.5, "2026-07-14": 59.1}
    eod_stages = {"2026-07-10": "退潮", "2026-07-14": "启动"}
    jev_eod = {"2026-07-10": "retreat", "2026-07-14": "ferment"}
    by_date = {i["date"]: i for i in _mk({}, {}, eod, eod_stages, jev_eod)}
    assert by_date["2026-07-10"]["ruling"]["status"] == "consistent"
    assert by_date["2026-07-14"]["ruling"]["status"] == "pending"


def test_slopes_of_day_first_slot_none():
    slopes = slopes_of_day({"09:30": 50.0, "10:00": 48.0, "10:30": 48.0})
    assert slopes["09:30"] is None
    assert slopes["10:00"] == -2.0
    assert slopes["10:30"] == 0.0


def test_merge_preserves_ruled_and_refreshes_pending():
    items = [{"_id": "review:d:s:A", "evidence": 1, "ruling": {"status": "pending", "note": "", "ruledAt": None}},
             {"_id": "review:d:s:B", "evidence": 1, "ruling": {"status": "pending", "note": "", "ruledAt": None}}]
    existing = {"review:d:s:A": {"_id": "review:d:s:A",
                                 "ruling": {"status": "jev_right", "note": "盘感核实", "ruledAt": "2026-10-01T10:00:00"}}}
    merged = merge_preserving_rulings(items, existing)
    assert merged[0]["ruling"]["status"] == "jev_right" and merged[0]["ruling"]["note"] == "盘感核实"
    assert merged[0]["evidence"] == 1  # 证据刷新
    assert merged[1]["ruling"]["status"] == "pending"
