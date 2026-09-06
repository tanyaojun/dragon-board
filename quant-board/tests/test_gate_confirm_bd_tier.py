from __future__ import annotations

from backend.analysis.ranktrend.ranking.volume_price import assemble_observation
from backend.analysis.ranktrend.trend.gate_confirm import GateConfirmState, gate_reason


def _apply_bd_confirm(state: GateConfirmState, active: bool, code: str, lc_tier: str, reasons: list[str]) -> str | None:
    """与 _build_signal 插入段等价的确认逻辑：返回 lc_tier_override（None = 不 override）。

    R-C2 同源：active 且 K>1 时每帧无条件过 confirmed_value——B/D 帧走确认分支，
    非 B/D 帧走基线更新分支（中断计数）；未激活或 K=1 直通且不触碰状态。
    runtime 实际使用 f"{code}:lc" 命名空间 key（R-C5：与 action 确认通道隔离）；
    本 helper 只建模 B/D 单通道，key 语义等价。
    """
    required = state.required_frames
    if active and required > 1 and lc_tier in ("B", "D"):
        confirmed = state.confirmed_value(code, lc_tier, when_in=("B", "D"), default="C")
        if confirmed != lc_tier:
            reasons.append(gate_reason(f"周期 {lc_tier} 环境降档", state.streak(code), required))
            return confirmed
        return None                                    # 达 K：不 override，用原始值
    if lc_tier not in ("B", "D"):
        state.confirmed_value(code, lc_tier, when_in=("B", "D"), default="C")  # 非 B/D 帧更新基线
    return None


def test_bd_downgrade_held_on_first_frame():
    state = GateConfirmState(required_frames=2)
    reasons: list[str] = []
    override = _apply_bd_confirm(state, True, "000001", "D", reasons)
    assert override == "C"                                 # 首帧 D 未达 → override 为 C
    assert any("确认未达（1/2）" in reason for reason in reasons)


def test_bd_downgrade_passes_on_second_frame():
    state = GateConfirmState(required_frames=2)
    _apply_bd_confirm(state, True, "000001", "D", [])
    reasons: list[str] = []
    assert _apply_bd_confirm(state, True, "000001", "D", reasons) is None  # 连续第 2 帧 → 生效，不 override
    assert not any("确认未达" in reason for reason in reasons)


def test_bd_interrupt_returns_to_baseline():
    state = GateConfirmState(required_frames=2)
    _apply_bd_confirm(state, True, "000001", "D", [])
    reasons: list[str] = []
    assert _apply_bd_confirm(state, True, "000001", "A", reasons) is None  # 中断：基线更新为 A
    reasons2: list[str] = []
    override = _apply_bd_confirm(state, True, "000001", "D", reasons2)
    assert override == "A"                                 # 重新 1 帧不够 → 维持 A


def test_e_chain_not_touched_by_bd_confirm():
    state = GateConfirmState(required_frames=2)
    reasons: list[str] = []
    assert _apply_bd_confirm(state, True, "000001", "E", reasons) is None  # E 不在 when_in：直通
    assert not reasons


def test_inactive_or_k1_passthrough():
    state = GateConfirmState(required_frames=2)
    assert _apply_bd_confirm(state, False, "000001", "D", []) is None      # 未激活：现行为
    state1 = GateConfirmState(required_frames=1)
    assert _apply_bd_confirm(state1, True, "000001", "D", []) is None      # K=1：现行为


def test_suppression_reason_not_matched_by_wp32_anchor():
    """跨计划协同：抑制文案不得被 WP3.2 的精确锚点（周期 [BD] 环境降档）误判为真实降档。"""
    import re

    suppression = gate_reason("周期 D 环境降档", 1, 2)
    assert re.fullmatch(r"周期 [BD] 环境降档", suppression) is None        # 带后缀 → 不误配
    assert re.fullmatch(r"周期 [BD] 环境降档", "周期 D 环境降档") is not None  # 真实降档文案命中


def test_assemble_lc_tier_override_suppresses_bd_downgrade(monkeypatch):
    """assemble_observation 接线：override="C" 抑制 B/D 连锁降档，lifecycle.signalTier 保持原始值。"""
    import backend.analysis.ranktrend.ranking.volume_price as vp_mod

    monkeypatch.setattr(
        vp_mod, "compute_volume_price_score",
        lambda *args, **kwargs: {"signalTier": "A", "direction": "up", "score": 80.0},
    )
    stock = {"code": "000001", "change": 5.0, "volumeRatio": 2.0, "zlje": 1e8, "zljzb": 10.0}

    def _analysis(lc: str) -> dict:
        return {"observation": {
            "rankTrend": {"signalTier": "A", "direction": "up"},
            "lifecycle": {"signalTier": lc, "stage": "发酵"},
            "crossSection": {"signalTier": "A"},          # rank A(+1.0) + cs A(+1.0) + vp A(+1.0) = 3.0 → S
        }}

    base = assemble_observation(_analysis("D"), stock)    # 无 override：S 被降档为 A
    assert "周期 D 环境降档" in base["synergy"]["tierReasons"]
    assert base["lifecycle"]["signalTier"] == "D"

    held = assemble_observation(_analysis("D"), stock, lc_tier_override="C")   # override：不降档
    assert "周期 D 环境降档" not in held["synergy"]["tierReasons"]
    assert held["synergy"]["signalTier"] == "S"           # 保持未降档档位
    assert held["lifecycle"]["signalTier"] == "D"         # 发布输出保持原始值
