from __future__ import annotations

from backend.analysis.ranktrend.trend.gate_confirm import GateConfirmState


def _apply_action_confirm(state: GateConfirmState, active: bool, code: str, cycle: dict) -> dict:
    """与 _build_signal 插入段等价的确认逻辑（集成断言由 Step 4 的真实引擎 replay 用例覆盖）。

    R-C2 裁决：active 且 K>1 时每帧无条件过 confirmed_value——非 veto 值走其非触发分支
    （基线更新 + 原样返回），veto 值走连续计数；否则"维持上一帧已确认 action"无从成立
    （计划原接线只在 veto 帧调 confirmed_value，非 veto 帧基线永不更新，与本文件
    test_veto_action_holds_previous_non_veto_action 相矛盾）。
    """
    decision = cycle.setdefault("decision", {})
    action = str(decision.get("action") or "")
    required = state.required_frames
    if active and required > 1:
        from backend.analysis.ranktrend.trend.gate_confirm import gate_reason

        confirmed = state.confirmed_value(code, action, when_in=("veto",), default="caution")
        if confirmed != action:
            decision["action"] = confirmed
            decision.setdefault("reasons", []).append(gate_reason("周期 veto", state.streak(code), required))
    return cycle


def test_veto_action_suppressed_on_first_frame_with_reason():
    state = GateConfirmState(required_frames=2)
    cycle = {"decision": {"action": "veto", "reasons": ["周期退潮"]}}
    result = _apply_action_confirm(state, True, "000001", cycle)
    assert result["decision"]["action"] == "caution"        # 首帧未达 → default
    assert any("确认未达（1/2）" in str(reason) for reason in result["decision"]["reasons"])
    assert "周期退潮" in result["decision"]["reasons"]       # 原因保留


def test_veto_action_holds_previous_non_veto_action():
    state = GateConfirmState(required_frames=2)
    _apply_action_confirm(state, True, "000001", {"decision": {"action": "confirm", "reasons": []}})  # 基线 confirm
    cycle = _apply_action_confirm(state, True, "000001", {"decision": {"action": "veto", "reasons": []}})
    assert cycle["decision"]["action"] == "confirm"         # 未达 → 维持上一帧已确认 action


def test_veto_action_confirmed_on_second_consecutive_frame():
    state = GateConfirmState(required_frames=2)
    _apply_action_confirm(state, True, "000001", {"decision": {"action": "veto", "reasons": []}})
    cycle = _apply_action_confirm(state, True, "000001", {"decision": {"action": "veto", "reasons": []}})
    assert cycle["decision"]["action"] == "veto"            # 连续第 2 帧：真 veto


def test_non_veto_action_updates_baseline_and_passthrough():
    state = GateConfirmState(required_frames=2)
    _apply_action_confirm(state, True, "000001", {"decision": {"action": "veto", "reasons": []}})
    cycle = _apply_action_confirm(state, True, "000001", {"decision": {"action": "caution", "reasons": []}})
    assert cycle["decision"]["action"] == "caution"         # 非 veto 直通 + 基线更新（中断计数）


def test_inactive_or_k1_passthrough():
    state = GateConfirmState(required_frames=2)
    cycle = {"decision": {"action": "veto", "reasons": []}}
    assert _apply_action_confirm(state, False, "000001", cycle)["decision"]["action"] == "veto"  # 单股链路直通
    state1 = GateConfirmState(required_frames=1)
    cycle1 = {"decision": {"action": "veto", "reasons": []}}
    assert _apply_action_confirm(state1, True, "000001", cycle1)["decision"]["action"] == "veto"  # K=1 现行为


# ── Step 4：真实引擎 replay 集成断言（强制 veto 经 lifecycle_decision 覆盖层注入，
# 确认层走完整 _build_signal → compose 下游真实链路）──

import backend.analysis.ranktrend.trend.lifecycle as _lifecycle_mod
import backend.analysis.ranktrend.engine.runtime as _runtime_mod
from backend.analysis.ranktrend.engine import RankTrendPythonEngine
from backend.analysis.ranktrend.engine.config import RankTrendConfig
from tests.ranktrend.test_ranktrend_golden_alignment import _make_frames


def _force_actions(monkeypatch, veto_frames: set[int]):
    """按 processed-frame 序号强制 action：veto_frames 内的帧 → veto，其余帧 → allow。
    lifecycle_decision 每帧被调用两次（analyze_cycle + analyze_cycle_with_risk），
    call_idx // 2 = 帧序号；两处命名空间都要 patch（runtime 顶部 from-import 绑定原始引用）。"""
    calls = {"n": 0}
    original = _lifecycle_mod.lifecycle_decision

    def wrapper(*args, **kwargs):
        result = dict(original(*args, **kwargs))
        frame_index = calls["n"] // 2
        calls["n"] += 1
        if frame_index in veto_frames:
            result["action"] = "veto"
            result["reasons"] = list(result.get("reasons") or []) + ["forced veto for test"]
        else:
            result["action"] = "allow"
        return result

    monkeypatch.setattr(_lifecycle_mod, "lifecycle_decision", wrapper)
    monkeypatch.setattr(_runtime_mod, "lifecycle_decision", wrapper)


def _actions(signals: list[dict]) -> list[str]:
    return [str(s["rankTrend"]["cycle"]["decision"]["action"]) for s in signals]


def test_replay_k2_suppresses_single_frame_veto_with_reason(monkeypatch):
    _force_actions(monkeypatch, veto_frames={1, 2})  # 帧 0 非 veto，帧 1/2 veto
    engine = RankTrendPythonEngine(config=RankTrendConfig(lifecycleConfirmFrames=2))
    signals = engine.replay(_make_frames(), meta={})
    actions = _actions(signals)
    assert actions[1] != "veto"                                  # 单帧 veto 被抑制
    assert actions[1] == "allow"                                 # 维持上一帧已确认 action
    reasons = signals[1]["rankTrend"]["cycle"]["decision"]["reasons"]
    assert any("确认未达（1/2）" in str(reason) for reason in reasons)   # fail-visible
    assert actions[2] == "veto"                                  # 连续第 2 帧：真 veto


def test_replay_k1_default_keeps_current_behavior(monkeypatch):
    _force_actions(monkeypatch, veto_frames={1, 2})
    engine = RankTrendPythonEngine(config=RankTrendConfig())     # K=1 默认：现行为
    signals = engine.replay(_make_frames(), meta={})
    actions = _actions(signals)
    assert actions[1] == "veto"                                  # 单帧 veto 直接发布
    reasons = signals[1]["rankTrend"]["cycle"]["decision"]["reasons"]
    assert not any("确认未达" in str(reason) for reason in reasons)
