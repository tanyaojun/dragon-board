# -*- coding: utf-8 -*-
"""M2 月度监控测试：三监督线读数组装 + 走廊状态机（不写 Mongo，纯函数）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_monitor_monthly import build_supervision, corridor_state


def test_build_supervision_lines():
    """三监督线：S+A 触发率(<3.5% 预警)/insufficient 占比(回弹预警)/北极星单期读数。"""
    sup = build_supervision(
        sa_trigger_rate=0.032,
        insufficient_share=0.088,
        northstar_pass={"offense": True, "defense": True},
    )
    assert sup["saTriggerRate"]["value"] == 0.032
    assert sup["saTriggerRate"]["alert"] is True          # <3.5% 触发 R3 预警线
    assert sup["insufficientShare"]["value"] == 0.088
    assert sup["insufficientShare"]["alert"] is False      # <15%（floor5 原水平）不预警
    assert sup["northstar"]["pass"] == {"offense": True, "defense": True}


def test_corridor_state_three_strikes():
    """走廊：连续 3 期 offense 达线 → 达成；中断即清零重计。"""
    hist = [{"offense": True, "defense": True},
            {"offense": True, "defense": False},
            {"offense": True, "defense": False},
            {"offense": True, "defense": True}]
    state = corridor_state(hist)
    assert state["offenseStreak"] == 4      # 4 期连续
    assert state["offenseAchieved"] is True  # ≥3 达成
    assert state["defenseStreak"] == 1
    assert state["defenseAchieved"] is False


def test_corridor_state_resets_on_false():
    hist = [{"offense": True}, {"offense": True}, {"offense": False}, {"offense": True}]
    state = corridor_state(hist)
    assert state["offenseStreak"] == 1
    assert state["offenseAchieved"] is False
