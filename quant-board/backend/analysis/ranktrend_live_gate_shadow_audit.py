from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
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


def load_hotlist_anchor_samples(path: str | Path) -> list[dict[str, str]]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("anchor sample file must contain a JSON array")
    output: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("anchor sample row must be an object")
        status = str(row.get("status") or "confirmed").strip()
        if status not in {"confirmed", "borderline", "exclude"}:
            raise ValueError(f"unsupported anchor sample status: {status}")
        output.append(
            {
                "code": str(row.get("code") or "").strip(),
                "tradingDate": str(row.get("tradingDate") or "").strip(),
                "slotTime": str(row.get("slotTime") or "").strip(),
                "snapshotType": str(row.get("snapshotType") or "half_hour").strip(),
                "label": str(row.get("label") or "").strip(),
                "evidence": str(row.get("evidence") or "").strip(),
                "annotator": str(row.get("annotator") or "").strip(),
                "status": status,
            }
        )
    return output


def classify_hotlist_buy_pattern(signal: dict[str, Any]) -> list[str]:
    technical = _nested_get(signal, "rankTrend", "technical") or {}
    tech_signals = technical.get("signals") or {}
    momentum = technical.get("momentumProfile") or {}
    jump = _nested_get(signal, "rankTrend", "jump") or {}
    cycle_stage = str(_nested_get(signal, "rankTrend", "cycle", "stage") or "")
    tags: list[str] = []

    buy_votes = [
        _nested_get(tech_signals, "direction", "signal") == "buy",
        _nested_get(tech_signals, "acceleration", "signal") == "buy",
        _nested_get(tech_signals, "zeroCross", "signal") == "buy",
        _nested_get(technical, "macd", "cross") == "golden",
    ]
    if sum(1 for vote in buy_votes if vote) >= 3:
        tags.append("technical_buy_alignment")
    if (
        jump.get("direction") == "buy"
        and jump.get("sustained") is True
        and _to_float(jump.get("confidence")) >= 70
    ):
        tags.append("progressive_rank_lift")
    if (
        _to_float(momentum.get("short")) > 0
        and _to_float(momentum.get("mid")) > 0
        and _to_float(momentum.get("long")) > 0
        and _to_float(momentum.get("acceleration")) < 10
    ):
        tags.append("non_explosive_but_valid")
    if cycle_stage == "ignition":
        tags.append("early_hotlist_ignition")
    return tags


def scan_jump_confidence_thresholds(
    findings: list[dict[str, Any]],
    thresholds: list[float],
) -> list[dict[str, Any]]:
    anchor_total = sum(1 for item in findings if item.get("isAnchor"))
    positive_total = sum(1 for item in findings if item.get("isPositiveOutcome"))
    rows: list[dict[str, Any]] = []
    for raw_threshold in thresholds:
        threshold = float(raw_threshold)
        anchor_recall = 0
        positive_recall = 0
        recalled_total = 0
        noise_count = 0
        jump_confidences: list[float] = []
        for item in findings:
            jump = _nested_get(item, "baselineSignal", "rankTrend", "jump") or {}
            confidence = _to_float(jump.get("confidence"))
            recalled = (
                jump.get("event") == "jump"
                and jump.get("direction") == "buy"
                and jump.get("sustained") is True
                and confidence >= threshold
            )
            if not recalled:
                continue
            recalled_total += 1
            jump_confidences.append(confidence)
            if item.get("isAnchor"):
                anchor_recall += 1
            if item.get("isPositiveOutcome"):
                positive_recall += 1
            if (
                not item.get("isAnchor")
                and not item.get("isPositiveOutcome")
                and "technical_buy_alignment" not in (item.get("hotlistBuyTags") or [])
            ):
                noise_count += 1
        rows.append(
            {
                "threshold": threshold,
                "anchorTotalCount": anchor_total,
                "anchorRecallCount": anchor_recall,
                "anchorRecallRate": round(anchor_recall / anchor_total, 4) if anchor_total else 0.0,
                "positiveTotalCount": positive_total,
                "positiveRecallCount": positive_recall,
                "positiveRecallRate": round(positive_recall / positive_total, 4) if positive_total else 0.0,
                "recalledCount": recalled_total,
                "noiseCount": noise_count,
                "jumpConfidenceDistribution": {
                    "min": min(jump_confidences) if jump_confidences else None,
                    "max": max(jump_confidences) if jump_confidences else None,
                    "count": len(jump_confidences),
                },
                "derivedBy": "rule",
            }
        )
    return rows


def _fusion_miss_reason_type(check: dict[str, Any]) -> str:
    explicit = check.get("reasonType")
    if explicit in {
        "true_gate_block",
        "field_missing",
        "replay_missing",
        "candidate_tier_side_effect",
        "sample_quality_side_effect",
    }:
        return str(explicit)
    name = str(check.get("name") or "")
    if check.get("missing"):
        return "field_missing"
    if name in {"signal_missing_in_baseline_replay", "fusion_replay_missing"}:
        return "replay_missing"
    if name == "tier_gate":
        return "candidate_tier_side_effect"
    if name == "sample_quality_ok":
        return "sample_quality_side_effect"
    return "true_gate_block"


def summarize_fusion_gate_misses(findings: list[dict[str, Any]]) -> dict[str, Any]:
    anchor_counts: dict[str, int] = {}
    extended_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    confounders: dict[str, dict[str, int]] = {
        "candidateTier": {},
        "cycleStage": {},
        "cycleDecisionAction": {},
        "sampleQualityStatus": {},
    }
    for item in findings:
        checks = (((item.get("variantResults") or {}).get("baseline") or {}).get("fusion") or {}).get("checks")
        if not checks:
            checks = [{"name": "fusion_replay_missing", "passed": False, "reasonType": "replay_missing"}]
        failed = [check for check in checks if not check.get("passed")]
        if failed:
            failed = failed[:1]
        for check in failed:
            name = str(check.get("name") or "")
            if not name:
                continue
            target = anchor_counts if item.get("isAnchor") else extended_counts
            target[name] = int(target.get(name) or 0) + 1
            reason_type = _fusion_miss_reason_type(check)
            reason_counts[reason_type] = int(reason_counts.get(reason_type) or 0) + 1
            for source_key, output_key in [
                ("candidateTier", "candidateTier"),
                ("cycleStage", "cycleStage"),
                ("cycleDecisionAction", "cycleDecisionAction"),
                ("sampleQualityStatus", "sampleQualityStatus"),
            ]:
                value = str(item.get(source_key) or "unknown")
                bucket = confounders[output_key]
                bucket[value] = int(bucket.get(value) or 0) + 1
    return {
        "anchorMissCounts": anchor_counts,
        "extendedMissCounts": extended_counts,
        "reasonTypeCounts": reason_counts,
        "confounderBreakdowns": confounders,
    }


def summarize_jump_definition_replays(findings: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, dict[str, Any]] = {}
    for variant in DEFAULT_SHADOW_VARIANTS:
        if not variant.requires_separate_replay:
            continue
        row = summary.setdefault(
            variant.key,
            {
                "variant": variant.key,
                "jumpDeltaPct": variant.jump_delta_pct,
                "triggeredCount": 0,
                "missingReplayCount": 0,
                "directionCounts": {},
                "derivedBy": "rule",
            },
        )
        for item in findings:
            result = (item.get("variantResults") or {}).get(variant.key) or {}
            if result.get("missingSignal"):
                row["missingReplayCount"] += 1
                continue
            if result.get("triggered"):
                row["triggeredCount"] += 1
            direction = str(_nested_get(result, "jump", "signal", "direction") or "unknown")
            counts = row["directionCounts"]
            counts[direction] = int(counts.get(direction) or 0) + 1
    return summary


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
