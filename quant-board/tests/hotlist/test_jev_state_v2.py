# -*- coding: utf-8 -*-
"""情绪判定问题集 v2 测试：近20日参照锚（分位/fail-visible）+ 叙事插段 + 问题集结构。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS_V2,
    JEV_SLOT_QUESTIONS_V2,
    build_day_jev_state,
    build_history_anchor,
    build_slot_jev_state,
    extract_history_anchor_range,
)

STATS = [
    {"date": f"2026-08-{d:02d}", "ztCount": 30 + i * 2, "maxBoard": 4 + (i % 3),
     "amountYi": 15000.0 + i * 100, "zhabanRate": 10.0 + i}
    for i, d in enumerate(range(11, 31))
]


def test_history_anchor_percentiles():
    out = build_history_anchor(STATS)
    assert out.startswith("【近20日参照】（2026-08-11 → 2026-08-30，20 个交易日收盘统计")
    assert "涨停数：p20=" in out and "p50=" in out and "p80=" in out
    assert "（2026-08-30 68 家）" in out  # 最后非空样本带实际日期（防陈旧值误标"昨日"）
    assert "最高连板：p20=" in out and "炸板率：p20=" in out


def test_history_anchor_insufficient_sample_fail_visible():
    # 指标样本 <8 → 如实标注，不伪造刻度
    out = build_history_anchor(STATS[:5])
    assert "历史样本不足（5 日）" in out
    assert "p20" not in out.split("\n")[1] or "涨停数 历史样本不足" in out


def test_history_anchor_empty():
    out = build_history_anchor([])
    assert "历史参照缺失" in out and "不得虚构对比" in out


def test_extract_history_anchor_range():
    # 标准首行 → 括号内完整区间（含中文逗号段，前端 split('，')[0] 取日期段）
    assert extract_history_anchor_range(build_history_anchor(STATS)) == \
        "2026-08-11 → 2026-08-30，20 个交易日收盘统计，判读坐标系"
    # 历史参照缺失首行不带（ 前缀 → None（旧定长切片在此错位产出半截句）
    assert extract_history_anchor_range(build_history_anchor([])) is None


def test_slot_narrative_contains_anchor():
    state = build_slot_jev_state(trading_date="2026-09-07", slot_time="09:30",
                                 current={"quality": {"degradedSources": []}}, priors=[],
                                 history_anchor=build_history_anchor(STATS))
    assert "【近20日参照】" in state
    assert "2026-09-07 09:30 时点快照" in state
    # 空 anchor 行被过滤不留双空行
    state2 = build_slot_jev_state(trading_date="2026-09-07", slot_time="09:30",
                                  current={"quality": {"degradedSources": []}}, priors=[])
    assert "【近20日参照】" not in state2


def test_day_narrative_contains_anchor():
    out = build_day_jev_state(trading_date="2026-09-07", evidences=[],
                              history_anchor="【近20日参照】X")
    assert "无帧证据" in out  # 空证据仍是 fail-visible 短路


def test_v2_question_sets_structure():
    # crowding 已离散归层（五选一含逃生口）
    assert JEV_SLOT_QUESTIONS_V2["crowding"]["type"] == "choice"
    assert set(JEV_SLOT_QUESTIONS_V2["crowding"]["criteria"]) == {
        "top_acceleration", "late_seal_weakness", "breadth_climax", "no_crowding", "insufficient_evidence"}
    assert JEV_DAY_QUESTIONS_V2["day_crowding"]["type"] == "choice"
    # 温度仍 score 且题干锚定参照系
    assert JEV_SLOT_QUESTIONS_V2["temperature"]["type"] == "score"
    assert "近20日参照" in JEV_SLOT_QUESTIONS_V2["temperature"]["instructions"]
    # 五档判据绑可数证据
    assert "近20日参照低位" in JEV_SLOT_QUESTIONS_V2["frame_stage"]["criteria"]["ice"]
    assert "炸板率" in JEV_SLOT_QUESTIONS_V2["frame_stage"]["criteria"]["retreat"]
    # v1 问题集不动（封存对照）
    from backend.analysis.hotlist.jev_state import JEV_SLOT_QUESTIONS

    assert JEV_SLOT_QUESTIONS["crowding"]["type"] == "score"
