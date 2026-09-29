"""RankTrend analysis engine pure-function tests.

Extracted from tests/test_quant_board.py: ranktrend/lifecycle_decision/
compose_strategy engine-level tests (no HTTP, no bundle helpers).
"""

from __future__ import annotations

import math

import pytest

from backend.analysis.ranktrend.engine import (
    RankTrendConfig,
    analyze_cycle,
    analyze_momentum_signals,
    analyze_risk,
    analyze_technical,
    momentum_data,
)


def test_ranktrend_uses_fallback_below_min_computable_samples() -> None:
    config = RankTrendConfig()
    percentiles = [
        40,
        41,
        42,
        43,
        44,
        45,
        46,
        47,
        48,
        49,
        50,
        51,
        52,
        53,
        54,
        55,
        56,
        57,
        58,
        59,
        60,
        61,
        62,
        63,
        64,
        65,
        66,
        67,
        68,
    ]
    percentiles = percentiles[:20]  # 20 bar：低于 MACD 可计算窗口 21 与动量可计算窗口 22
    fallback = {"displayChange": 2.2, "stockChange": 1.8, "volumeRatio": 1.5, "zlje": 1, "zljzb": 1}

    technical = analyze_technical(percentiles, config, fallback)

    assert len(percentiles) < 22
    display_score = math.tanh(fallback["displayChange"] / 8)
    price_score = math.tanh(fallback["stockChange"] / 6)
    volume_score = math.tanh((fallback["volumeRatio"] - 1) / 0.75)
    expected_direction_score = display_score * 0.4 + price_score * 0.3 + 0.2 + volume_score * 0.1
    expected_direction_confidence = 50 + abs(expected_direction_score) * 40 + 4.5

    assert abs(technical["signals"]["direction"]["score"] - expected_direction_score) < 1e-12
    assert abs(technical["signals"]["direction"]["confidence"] - expected_direction_confidence) < 1e-12
    assert technical["signals"]["direction"]["signal"] == "buy"
    assert technical["signals"]["acceleration"]["confidence"] > 50


def test_ranktrend_computes_real_technical_from_min_computable_samples() -> None:
    config = RankTrendConfig()
    # 22 bar：达到动量 max(periods)+1 与 MACD macdSlow 的最小可计算窗口，但未达稳定窗口 30
    percentiles = [40 + index for index in range(22)]
    fallback = {"displayChange": 2.2, "stockChange": 1.8, "volumeRatio": 1.5, "zlje": 1, "zljzb": 1}

    technical = analyze_technical(percentiles, config, fallback)
    data = momentum_data(percentiles, config)

    assert abs(technical["macd"]["dif"]) > 0
    assert abs(technical["macd"]["histogram"]) > 0
    assert technical["momentumScore"] == pytest.approx(data["score"])
    real_signals = analyze_momentum_signals(data, config)
    assert technical["signals"]["direction"]["score"] == pytest.approx(
        real_signals["direction"]["score"]
    )


def test_ranktrend_momentum_signals_match_typescript_edge_cases() -> None:
    config = RankTrendConfig()
    signals = analyze_momentum_signals(
        {
            "values": [-1, -1, 0, 0, 0],
            "prevValues": [-4, -4, -3, -3, -3],
        },
        config,
    )

    assert signals["acceleration"]["signal"] == "buy"
    assert signals["acceleration"]["score"] > 0.18

    confirm_value = -math.atanh(0.13) * abs(config.sellThresholds[1])
    zero_cross = analyze_momentum_signals(
        {
            "values": [1, confirm_value, 0, 0, 0],
            "prevValues": [0, 0, 0, 0, 0],
        },
        config,
    )

    assert zero_cross["zeroCross"]["signal"] == "buy"


def test_ranktrend_risk_severity_clamps_before_stage_multiplier() -> None:
    risk = analyze_risk(
        90,
        {
            "macd": {"histogram": 0},
            "signals": {
                "direction": {"signal": "hold"},
                "acceleration": {"signal": "buy"},
                "zeroCross": {"signal": "hold"},
            },
        },
        {
            "stage": "cooling",
            "metrics": {
                "rankVelocity": 1,
                "rankAcceleration": 0,
                "rankShock": 0,
            },
        },
        zlje=-1,
        zljzb=-1,
        volume_ratio=1,
    )

    assert risk["divergence"]["severity"] == pytest.approx(0.15166666666666667)
    assert risk["pressure"] == pytest.approx(0.0637)


def test_ranktrend_cycle_crowded_raw_stage_persists_like_typescript() -> None:
    ranks = [
        147,
        186,
        192,
        189,
        166,
        150,
        53,
        4,
        3,
        3,
        8,
        7,
        7,
        8,
        8,
        10,
        11,
        10,
        12,
        20,
        30,
        31,
        20,
        14,
        16,
        8,
        5,
    ]
    percentiles = [
        45.52238805970149,
        20.600858369098713,
        30.79710144927536,
        27.413127413127413,
        36.29343629343629,
        51.77993527508091,
        76.78571428571429,
        98.45360824742268,
        96.0,
        99.10313901345292,
        97.4910394265233,
        98.07073954983923,
        97.32142857142857,
        96.72897196261681,
        97.21115537848605,
        96.34146341463415,
        95.63318777292577,
        96.08695652173913,
        95.23809523809523,
        92.08333333333333,
        87.71186440677965,
        87.28813559322035,
        92.14876033057851,
        94.6058091286307,
        93.44978165938865,
        96.875,
        98.23008849557522,
    ]

    cycle = analyze_cycle(ranks, percentiles)

    assert cycle["rawStage"] == "crowded"
    assert cycle["stage"] == "cooling"
    assert cycle["previousStage"] == "cooling"


def test_ranktrend_cycle_outputs_lifecycle_decision_contract() -> None:
    cycle = analyze_cycle([88, 76, 61, 44], [18, 26, 39, 57])

    assert cycle["decision"]["action"] == "allow"
    assert cycle["decision"]["confidence"] >= 50
    assert cycle["decision"]["reasons"]
    evidence = cycle["decision"]["evidence"]
    assert evidence["rawStage"] == cycle["rawStage"]
    assert evidence["stage"] == cycle["stage"]
    assert evidence["transition"] == cycle["transition"]
    assert evidence["rankVelocity"] == cycle["metrics"]["rankVelocity"]
    assert evidence["rankAcceleration"] == cycle["metrics"]["rankAcceleration"]
    assert evidence["drawdownFromPeak"] == cycle["metrics"]["drawdownFromPeak"]
    assert evidence["hotZoneStreak"] == cycle["metrics"]["hotZoneStreak"]


def test_ranktrend_lifecycle_decision_evidence_accepts_risk_pressure() -> None:
    from backend.analysis.ranktrend.engine import lifecycle_decision

    decision = lifecycle_decision(
        "expansion",
        "expansion",
        "cooling->expansion",
        90,
        {
            "rankVelocity": 20,
            "rankAcceleration": 12,
            "drawdownFromPeak": 0,
            "hotZoneStreak": 0,
        },
        {
            "pressure": 0.42,
            "divergence": {"severity": 0.35},
            "overheat": {"severity": 0.51},
        },
    )

    evidence = decision["evidence"]
    assert evidence["riskPressure"] == 0.42
    assert evidence["divergenceSeverity"] == 0.35
    assert evidence["overheatSeverity"] == 0.51


def test_ranktrend_lifecycle_decision_vetoes_high_risk_breakout() -> None:
    from backend.analysis.ranktrend.engine import lifecycle_decision

    decision = lifecycle_decision(
        "expansion",
        "expansion",
        "cooling->expansion",
        90,
        {
            "rankVelocity": 25,
            "rankAcceleration": 18,
            "drawdownFromPeak": 0,
            "hotZoneStreak": 0,
        },
        {
            "pressure": 0.78,
            "divergence": {"severity": 0.84},
            "overheat": {"severity": 0.72},
        },
    )

    assert decision["action"] == "veto"
    assert any("风险" in reason for reason in decision["reasons"])


def test_ranktrend_lifecycle_decision_outputs_discovery_diagnostic() -> None:
    cycle = analyze_cycle([120, 96, 72, 55], [28, 41, 53, 64])

    assert cycle["decision"]["action"] == "allow"
    assert cycle["decision"]["discovery"]["action"] == "research_watch"
    assert any("漏选" in reason for reason in cycle["decision"]["discovery"]["reasons"])


def test_ranktrend_lifecycle_decision_cautions_last_jump_without_path_commitment() -> None:
    from backend.analysis.ranktrend.engine import lifecycle_decision

    decision = lifecycle_decision(
        "expansion",
        "expansion",
        "cooling->expansion",
        86,
        {
            "rankVelocity": 35,
            "rankAcceleration": 34,
            "drawdownFromPeak": 0,
            "hotZoneStreak": 0,
            "rankPathCommitment": 0.28,
        },
        {
            "pressure": 0.22,
            "divergence": {"severity": 0.18},
            "overheat": {"severity": 0.24},
        },
    )

    assert decision["evidence"]["rankPathCommitment"] < 0.45
    assert decision["action"] == "caution"
    assert any("承接" in reason for reason in decision["reasons"])


def test_ranktrend_lifecycle_decision_does_not_veto_weak_path_when_mid_long_commit() -> None:
    from backend.analysis.ranktrend.engine import lifecycle_decision

    decision = lifecycle_decision(
        "expansion",
        "expansion",
        "cooling->expansion",
        86,
        {
            "rankVelocity": 20.13,
            "rankAcceleration": 20.13,
            "drawdownFromPeak": 0,
            "hotZoneStreak": 0,
            "rankPathCommitment": 0.373,
        },
        {
            "pressure": 0.05,
            "divergence": {"severity": 0.0},
            "overheat": {"severity": 0.08},
        },
        {
            "short": 17.03,
            "mid": 16.61,
            "long": 36.07,
            "acceleration": 23.51,
        },
    )

    assert decision["evidence"]["rankPathCommitment"] < 0.45
    assert decision["action"] != "veto"
    assert not any("一票否决" in reason for reason in decision["reasons"])


def test_ranktrend_lifecycle_decision_preserves_low_long_big_move_when_path_commits() -> None:
    from backend.analysis.ranktrend.engine import lifecycle_decision

    decision = lifecycle_decision(
        "expansion",
        "expansion",
        "cooling->expansion",
        84,
        {
            "rankVelocity": 5,
            "rankAcceleration": 1,
            "drawdownFromPeak": 0,
            "hotZoneStreak": 0,
            "rankPathCommitment": 0.72,
        },
        {
            "pressure": 0.2,
            "divergence": {"severity": 0.16},
            "overheat": {"severity": 0.25},
        },
    )

    assert decision["evidence"]["rankPathCommitment"] >= 0.65
    assert decision["action"] != "veto"
    assert not any("长周期" in reason for reason in decision["reasons"])


def test_ranktrend_lifecycle_decision_flags_low_visibility_ignition_commitment() -> None:
    from backend.analysis.ranktrend.engine import lifecycle_decision

    decision = lifecycle_decision(
        "ignition",
        "ignition",
        "cooling->ignition",
        80,
        {
            "rankVelocity": 22.24,
            "rankAcceleration": 22.11,
            "drawdownFromPeak": 0,
            "hotZoneStreak": 0,
            "rankPathCommitment": 0.66,
        },
        {
            "pressure": 0.18,
            "divergence": {"severity": 0.1},
            "overheat": {"severity": 0.22},
        },
        {
            "short": 21.83,
            "mid": 28.95,
            "long": 23.83,
            "acceleration": 24.29,
        },
    )

    assert decision["evidence"]["hotZoneStreak"] == 0
    assert decision["evidence"]["rankPathCommitment"] < 0.7
    assert decision["action"] == "caution"
    assert any("低可见度" in reason for reason in decision["reasons"])


def test_ranktrend_compose_strategy_keeps_low_visibility_b_ignition_as_caution_candidate() -> None:
    from backend.analysis.ranktrend.engine import compose_strategy

    technical = {
        "signals": {
            "direction": {"signal": "buy"},
            "acceleration": {"signal": "buy"},
        },
        "macd": {"cross": "none"},
        "momentumProfile": {
            "short": 21.83,
            "mid": 28.95,
            "long": 23.83,
            "acceleration": 24.29,
        },
    }
    cycle = {
        "stage": "ignition",
        "decision": {
            "action": "caution",
            "reasons": ["生命周期B识别到低可见度首段点火，承接尚未扩散，防止抢占后续高质量仓位。"],
        },
    }
    risk = {
        "pressure": 0.18,
        "divergence": {"severity": 0.1},
        "overheat": {"severity": 0.22},
    }

    strategy = compose_strategy(
        technical,
        cycle,
        risk,
        {"stage": "高潮", "riskLevel": "中", "confidence": 80},
    )

    assert strategy["candidateTier"] == "B_IGNITION"
    assert any("低可见度" in reason for reason in strategy["reasons"])


def test_ranktrend_compose_strategy_blocks_execution_tier_when_lifecycle_vetoes() -> None:
    from backend.analysis.ranktrend.engine import compose_strategy

    technical = {
        "signals": {
            "direction": {"signal": "buy"},
            "acceleration": {"signal": "hold"},
        },
        "macd": {"cross": "none"},
        "momentumProfile": {
            "short": 8,
            "mid": 6,
            "long": 2,
            "acceleration": 4,
        },
    }
    cycle = {
        "stage": "expansion",
        "decision": {"action": "veto", "reasons": ["生命周期B否决"]},
    }
    risk = {
        "pressure": 0.1,
        "divergence": {"severity": 0.1},
        "overheat": {"severity": 0.1},
    }

    strategy = compose_strategy(
        technical,
        cycle,
        risk,
        {"stage": "发酵", "riskLevel": "低", "confidence": 80},
    )

    assert strategy["candidateTier"] == "N_NEUTRAL"
    assert any("生命周期" in reason for reason in strategy["reasons"])


def test_ranktrend_cycle_reversal_vetoes_lifecycle_entry() -> None:
    cycle = analyze_cycle([18, 8, 4, 6, 9], [82, 93, 97, 94, 89])

    assert cycle["stage"] == "reversal"
    assert cycle["decision"]["action"] == "veto"
    assert any("反转" in reason for reason in cycle["decision"]["reasons"])
