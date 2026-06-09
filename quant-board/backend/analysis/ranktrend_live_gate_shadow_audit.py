from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ShadowVariant:
    key: str
    label: str
    # Research-only replay config for Task 2. Task 1 pure analysis does not
    # change gate results from this field; separate replay is required.
    jump_delta_pct: float = 15.0
    min_jump_confidence: float = 90.0
    require_change_lt_6: bool = True
    allow_degraded_sample: bool = False
    require_tier_gate: bool = True
    requires_separate_replay: bool = False


DEFAULT_SHADOW_VARIANTS = (
    ShadowVariant(key="baseline", label="baseline"),
    ShadowVariant(
        key="delta_12_5",
        label="delta=12.5",
        jump_delta_pct=12.5,
        requires_separate_replay=True,
    ),
    ShadowVariant(
        key="delta_10",
        label="delta=10",
        jump_delta_pct=10.0,
        requires_separate_replay=True,
    ),
    ShadowVariant(key="confidence_85", label="jump>=85", min_jump_confidence=85.0),
    ShadowVariant(key="confidence_80", label="jump>=80", min_jump_confidence=80.0),
    ShadowVariant(key="change_no_gate", label="change不硬拦", require_change_lt_6=False),
    ShadowVariant(key="allow_degraded", label="允许degraded", allow_degraded_sample=True),
    ShadowVariant(key="tier_no_gate", label="不卡tier", require_tier_gate=False),
    ShadowVariant(
        key="recall_first",
        label="召回优先全放",
        jump_delta_pct=10.0,
        min_jump_confidence=80.0,
        require_change_lt_6=False,
        allow_degraded_sample=True,
        require_tier_gate=False,
        requires_separate_replay=True,
    ),
)


def _nested_get(payload: dict[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_check(name: str, passed: bool) -> dict[str, Any]:
    return {"name": name, "passed": passed}


def _daily_limit_pct(code: Any) -> float:
    value = str(code or "").strip()
    if value.startswith(("300", "301", "688", "689")):
        return 19.8
    if value.startswith(("8", "4", "9")):
        return 29.8
    return 9.8


def _signal_acc_delta(signal: dict[str, Any], momentum: dict[str, Any]) -> float:
    if signal.get("accDelta") is not None:
        return _to_float(signal.get("accDelta"))
    return _to_float(momentum.get("accDelta"))


def _tier_gate_passed(candidate_tier: Any, momentum: dict[str, Any], tech_signals: dict[str, Any]) -> bool:
    if candidate_tier == "A_MAIN":
        return True
    if candidate_tier != "B_IGNITION":
        return False
    return (
        _to_float(momentum.get("mid")) >= 20
        and str(_nested_get(tech_signals, "zeroCross", "signal") or "") == "buy"
    )


def evaluate_variant_layers(
    signal: dict[str, Any],
    variant: ShadowVariant,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    jump = _nested_get(signal, "rankTrend", "jump") or {}
    technical = _nested_get(signal, "rankTrend", "technical") or {}
    tech_signals = technical.get("signals") or {}
    momentum = technical.get("momentumProfile") or {}
    sample_quality = _nested_get(signal, "rankTrend", "meta", "sampleQuality") or {}
    cycle_decision = _nested_get(signal, "rankTrend", "cycle", "decision") or {}
    candidate_tier = _nested_get(signal, "rankTrend", "strategy", "candidateTier")
    code = str(signal.get("code") or "")
    change = _to_float(signal.get("change"))
    acceleration = _to_float(momentum.get("acceleration"))
    acc_delta = _signal_acc_delta(signal, momentum)
    sample_status = str(sample_quality.get("status") or "")
    cycle_action = str(cycle_decision.get("action") or "")
    not_limit_up = change < _daily_limit_pct(code)

    jump_checks = [
        _build_check("jump_event_is_jump", jump.get("event") == "jump"),
        _build_check("jump_sustained", jump.get("sustained") is True),
        _build_check("jump_direction_buy", jump.get("direction") == "buy"),
        _build_check("jump_confidence", _to_float(jump.get("confidence")) >= variant.min_jump_confidence),
        _build_check("technical_direction_buy", _nested_get(tech_signals, "direction", "signal") == "buy"),
        _build_check("technical_acceleration_buy", _nested_get(tech_signals, "acceleration", "signal") == "buy"),
        _build_check("change_gt_0", change > 0),
        _build_check("not_limit_up", not_limit_up),
        _build_check("macd_golden", _nested_get(technical, "macd", "cross") == "golden"),
    ]

    fusion_checks = [
        _build_check(
            "short_mid_long_positive",
            _to_float(momentum.get("short")) > 0
            and _to_float(momentum.get("mid")) > 0
            and _to_float(momentum.get("long")) > 0,
        ),
        _build_check("acceleration_ge_10_or_accdelta_ge_8", acceleration >= 10 or acc_delta >= 8),
        _build_check("change_lt_6", True if not variant.require_change_lt_6 else change < 6),
        _build_check("not_limit_up", not_limit_up),
        _build_check(
            "sample_quality_ok",
            sample_status == "ok" or (variant.allow_degraded_sample and sample_status == "degraded"),
        ),
        _build_check("cycle_not_veto", cycle_action != "veto"),
        _build_check(
            "tier_gate",
            True if not variant.require_tier_gate else _tier_gate_passed(candidate_tier, momentum, tech_signals),
        ),
    ]
    return jump_checks, fusion_checks


def evaluate_shadow_variants(
    signal: dict[str, Any],
    variants: tuple[ShadowVariant, ...] = DEFAULT_SHADOW_VARIANTS,
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    jump_signal = _nested_get(signal, "rankTrend", "jump") or {}
    for variant in variants:
        jump_checks, fusion_checks = evaluate_variant_layers(signal, variant)
        jump_triggered = all(check["passed"] for check in jump_checks)
        fusion_triggered = all(check["passed"] for check in fusion_checks)
        live_gate_triggered = jump_triggered and fusion_triggered
        requires_replay_confirmation = variant.requires_separate_replay
        results[variant.key] = {
            "variant": variant.key,
            "requiresSeparateReplay": variant.requires_separate_replay,
            # Task 1 only computes the current live-gate view. Variants that
            # require separate replay must not expose this partial boolean as
            # their final triggered conclusion.
            "evaluationMode": "live_gate_partial" if requires_replay_confirmation else "direct",
            "requiresReplayConfirmation": requires_replay_confirmation,
            "jump": {
                "triggered": jump_triggered,
                "signal": jump_signal,
                "checks": jump_checks,
            },
            "fusion": {
                "triggered": fusion_triggered,
                "checks": fusion_checks,
            },
            "liveGateTriggered": live_gate_triggered,
            "triggered": None if requires_replay_confirmation else live_gate_triggered,
        }
    return results


def summarize_first_failure(checks: list[dict[str, Any]]) -> str | None:
    for check in checks:
        if not check.get("passed"):
            return str(check.get("name"))
    return None


def build_audit_meta(*, acc_delta_present_ratio: float) -> dict[str, Any]:
    return {
        "accDeltaPresentRatio": acc_delta_present_ratio,
        "accDeltaPolicy": (
            "live数据当前缺少accDelta，acceleration gate 实际主要依赖 acceleration"
            if acc_delta_present_ratio <= 0
            else "accDelta 可参与辅助解释，但当前不作为独立 shadow 变体"
        ),
        "engineMetaPolicy": (
            "RankTrend replay() 在 shadow audit 中固定传入 sampleQuality=ok、warnings=[]，"
            "用于 recall-first 审计覆盖；质量过滤不在引擎内提前拦截。"
        ),
    }


def rank_shadow_candidate(signal: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    score = 0

    stage = _nested_get(signal, "rankTrend", "cycle", "stage")
    if stage:
        score += 2
        reasons.append(f"stage:{stage}")

    tier = _nested_get(signal, "rankTrend", "strategy", "candidateTier")
    momentum = _nested_get(signal, "rankTrend", "technical", "momentumProfile") or {}
    zero_cross = _nested_get(signal, "rankTrend", "technical", "signals", "zeroCross", "signal")
    if tier == "A_MAIN":
        score += 3
        reasons.append("tier:A_MAIN")
    elif tier == "B_IGNITION":
        score += 2
        reasons.append(f"tier:{tier}")
        if _to_float(momentum.get("mid")) >= 20 and zero_cross == "buy":
            score += 2
            reasons.append("b_ignition_mid>=20_zeroCross:buy")
    elif tier:
        score += 1
        reasons.append(f"tier:{tier}")

    direction = _nested_get(signal, "rankTrend", "technical", "signals", "direction", "signal")
    if direction == "buy":
        score += 2
        reasons.append("direction:buy")

    if zero_cross == "buy":
        score += 1
        reasons.append("zeroCross:buy")

    return {
        "code": signal.get("code"),
        "score": score,
        "reasons": reasons,
    }
