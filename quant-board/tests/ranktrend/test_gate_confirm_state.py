from __future__ import annotations

from backend.analysis.ranktrend.trend.gate_confirm import GateConfirmState, gate_reason


def test_k1_passthrough_matches_condition():
    state = GateConfirmState(required_frames=1)
    assert state.confirm("c1", condition=True) is True
    assert state.confirm("c2", condition=False) is False


def test_k2_requires_consecutive_true_frames():
    state = GateConfirmState(required_frames=2)
    assert state.confirm("c1", condition=True) is False      # 第 1 帧：未达
    assert state.streak("c1") == 1
    assert state.confirm("c1", condition=True) is True       # 第 2 帧：确认
    assert state.confirm("c1", condition=True) is True       # 已确认持续


def test_k2_interrupt_resets_streak():
    state = GateConfirmState(required_frames=2)
    state.confirm("c1", condition=True)
    assert state.confirm("c1", condition=False) is False     # 中断清零
    assert state.streak("c1") == 0
    assert state.confirm("c1", condition=True) is False      # 重新计 1 帧不够
    assert state.confirm("c1", condition=True) is True


def test_keys_are_isolated():
    state = GateConfirmState(required_frames=2)
    state.confirm("a", condition=True)
    assert state.confirm("b", condition=True) is False       # b 的计数独立


def test_reset_clears_all_keys():
    state = GateConfirmState(required_frames=2)
    state.confirm("a", condition=True)
    state.reset()
    assert state.streak("a") == 0
    assert state.confirm("a", condition=True) is False


def test_confirmed_value_holds_previous_until_k_reached():
    state = GateConfirmState(required_frames=2)
    assert state.confirmed_value("s1", "B", when_in=("B", "D"), default="C") == "C"   # 首帧未达 → default
    assert state.confirmed_value("s1", "B", when_in=("B", "D"), default="C") == "B"   # 第 2 帧达 → B


def test_confirmed_value_non_trigger_value_updates_baseline():
    state = GateConfirmState(required_frames=2)
    state.confirmed_value("s1", "A", when_in=("B", "D"), default="C")                 # A 非 B/D：基线 A
    assert state.confirmed_value("s1", "B", when_in=("B", "D"), default="C") == "A"   # 未达 → 保持 A


def test_confirmed_value_k1_passthrough():
    state = GateConfirmState(required_frames=1)
    assert state.confirmed_value("s1", "B", when_in=("B", "D"), default="C") == "B"


def test_gate_reason_format():
    assert gate_reason("周期 veto", 1, 2) == "周期 veto 单帧确认未达（1/2），暂缓"
