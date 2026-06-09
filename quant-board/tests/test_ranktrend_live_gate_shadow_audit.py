from __future__ import annotations

import json
from contextlib import nullcontext
from copy import deepcopy
from datetime import date
from pathlib import Path

from backend.analysis.ranktrend_live_gate_shadow_audit import (
    DEFAULT_SHADOW_VARIANTS,
    build_audit_meta,
    classify_hotlist_buy_pattern,
    evaluate_shadow_variants,
    load_hotlist_anchor_samples,
    rank_shadow_candidate,
    scan_jump_confidence_thresholds,
    summarize_fusion_gate_misses,
    summarize_first_failure,
)
from backend.services import RankTrendLiveGateAuditService


def make_signal(**overrides):
    signal = {
        "code": "600186",
        "name": "莲花控股",
        "change": 6.0057,
        "accDelta": None,
        "rankTrend": {
            "jump": {
                "event": "jump",
                "direction": "buy",
                "confidence": 88.0,
                "sustained": True,
            },
            "technical": {
                "macd": {"cross": "golden"},
                "signals": {
                    "direction": {"signal": "buy"},
                    "acceleration": {"signal": "buy"},
                    "zeroCross": {"signal": "buy"},
                },
                "momentumProfile": {
                    "short": 2.17,
                    "mid": 10.41,
                    "long": 1.42,
                    "acceleration": 11.3,
                },
            },
            "meta": {"sampleQuality": {"status": "ok"}},
            "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
            "strategy": {"candidateTier": "N_NEUTRAL"},
        },
    }
    signal.update(overrides)
    return signal


def test_shadow_variants_matrix_and_two_layer_gates() -> None:
    result = evaluate_shadow_variants(make_signal(), variants=DEFAULT_SHADOW_VARIANTS)

    keys = [variant.key for variant in DEFAULT_SHADOW_VARIANTS]

    assert keys == [
        "baseline",
        "delta_12_5",
        "delta_10",
        "confidence_85",
        "confidence_80",
        "change_no_gate",
        "allow_degraded",
        "tier_no_gate",
        "recall_first",
    ]
    variants_by_key = {variant.key: variant for variant in DEFAULT_SHADOW_VARIANTS}

    assert variants_by_key["delta_12_5"].requires_separate_replay is True
    assert variants_by_key["delta_10"].requires_separate_replay is True
    assert variants_by_key["recall_first"].requires_separate_replay is True
    assert variants_by_key["baseline"].requires_separate_replay is not True
    assert variants_by_key["confidence_85"].requires_separate_replay is not True
    assert variants_by_key["change_no_gate"].requires_separate_replay is not True
    assert result["baseline"]["jump"]["triggered"] is False
    assert result["baseline"]["fusion"]["triggered"] is False
    assert result["baseline"]["liveGateTriggered"] is False
    assert result["baseline"]["triggered"] is False
    assert result["confidence_85"]["jump"]["triggered"] is True
    assert result["confidence_85"]["triggered"] is False
    assert result["change_no_gate"]["jump"]["triggered"] is False
    assert result["change_no_gate"]["fusion"]["triggered"] is False
    assert result["tier_no_gate"]["fusion"]["triggered"] is False
    assert result["delta_12_5"]["liveGateTriggered"] is False
    assert result["delta_12_5"]["triggered"] is None
    assert result["delta_12_5"]["requiresReplayConfirmation"] is True
    assert result["delta_12_5"]["evaluationMode"] == "live_gate_partial"
    assert result["recall_first"]["liveGateTriggered"] is True
    assert result["recall_first"]["triggered"] is None
    assert result["recall_first"]["requiresReplayConfirmation"] is True
    assert result["recall_first"]["evaluationMode"] == "live_gate_partial"


def test_summarize_first_failure_can_read_jump_and_fusion_checks() -> None:
    result = evaluate_shadow_variants(make_signal(), variants=DEFAULT_SHADOW_VARIANTS)

    assert summarize_first_failure(result["baseline"]["jump"]["checks"]) == "jump_confidence"
    assert summarize_first_failure(result["baseline"]["fusion"]["checks"]) == "change_lt_6"


def test_confidence_85_only_relaxes_jump_and_keeps_fusion_blocked() -> None:
    result = evaluate_shadow_variants(make_signal(), variants=DEFAULT_SHADOW_VARIANTS)

    assert result["confidence_85"]["jump"]["triggered"] is True
    assert result["confidence_85"]["fusion"]["triggered"] is False
    assert result["confidence_85"]["triggered"] is False
    assert summarize_first_failure(result["confidence_85"]["fusion"]["checks"]) == "change_lt_6"


def test_change_and_tier_variants_only_release_their_own_fusion_blockers() -> None:
    result = evaluate_shadow_variants(
        make_signal(
            change=6.2,
            rankTrend={
                "jump": {
                    "event": "jump",
                    "direction": "buy",
                    "confidence": 92.0,
                    "sustained": True,
                },
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {
                        "short": 2.17,
                        "mid": 10.41,
                        "long": 1.42,
                        "acceleration": 11.3,
                    },
                },
                "meta": {"sampleQuality": {"status": "ok"}},
                "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
                "strategy": {"candidateTier": "N_NEUTRAL"},
            },
        ),
        variants=DEFAULT_SHADOW_VARIANTS,
    )

    assert result["baseline"]["jump"]["triggered"] is True
    assert result["baseline"]["fusion"]["triggered"] is False
    assert summarize_first_failure(result["baseline"]["fusion"]["checks"]) == "change_lt_6"
    assert result["change_no_gate"]["fusion"]["triggered"] is False
    assert summarize_first_failure(result["change_no_gate"]["fusion"]["checks"]) == "tier_gate"
    assert result["tier_no_gate"]["fusion"]["triggered"] is False
    assert summarize_first_failure(result["tier_no_gate"]["fusion"]["checks"]) == "change_lt_6"
    assert result["recall_first"]["liveGateTriggered"] is True
    assert result["recall_first"]["triggered"] is None
    assert result["recall_first"]["requiresReplayConfirmation"] is True


def test_build_audit_meta_reports_accdelta_policy() -> None:
    meta = build_audit_meta(acc_delta_present_ratio=0.0)

    assert meta["accDeltaPresentRatio"] == 0.0
    assert meta["accDeltaPolicy"].startswith("live数据当前缺少accDelta")
    assert "sampleQuality=ok" in meta["engineMetaPolicy"]


def test_rank_shadow_candidate_only_adds_sorting_score() -> None:
    scored = rank_shadow_candidate(
        {
            "code": "600186",
            "change": 6.2,
            "rankTrend": {
                "cycle": {"stage": "ignition"},
                "strategy": {"candidateTier": "N_NEUTRAL"},
                "technical": {
                    "macd": {"cross": "none"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                },
            },
        }
    )

    assert scored["score"] > 0
    assert "stage:ignition" in scored["reasons"]
    assert "direction:buy" in scored["reasons"]
    assert "zeroCross:buy" in scored["reasons"]
    assert "triggered" not in scored


def test_tier_gate_matches_a_main_and_b_ignition_v3_logic() -> None:
    b_ignition_pass = evaluate_shadow_variants(
        make_signal(
            change=5.2,
            rankTrend={
                "jump": {
                    "event": "jump",
                    "direction": "buy",
                    "confidence": 92.0,
                    "sustained": True,
                },
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {
                        "short": 2.17,
                        "mid": 20.0,
                        "long": 1.42,
                        "acceleration": 11.3,
                    },
                },
                "meta": {"sampleQuality": {"status": "ok"}},
                "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
                "strategy": {"candidateTier": "B_IGNITION"},
            },
        )
    )

    b_ignition_fail = evaluate_shadow_variants(
        make_signal(
            change=5.2,
            rankTrend={
                "jump": {
                    "event": "jump",
                    "direction": "buy",
                    "confidence": 92.0,
                    "sustained": True,
                },
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "sell"},
                    },
                    "momentumProfile": {
                        "short": 2.17,
                        "mid": 19.0,
                        "long": 1.42,
                        "acceleration": 11.3,
                    },
                },
                "meta": {"sampleQuality": {"status": "ok"}},
                "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
                "strategy": {"candidateTier": "B_IGNITION"},
            },
        )
    )

    a_focus_fail = evaluate_shadow_variants(
        make_signal(
            change=5.2,
            rankTrend={
                "jump": {
                    "event": "jump",
                    "direction": "buy",
                    "confidence": 92.0,
                    "sustained": True,
                },
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {
                        "short": 2.17,
                        "mid": 21.0,
                        "long": 1.42,
                        "acceleration": 11.3,
                    },
                },
                "meta": {"sampleQuality": {"status": "ok"}},
                "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
                "strategy": {"candidateTier": "A_FOCUS"},
            },
        )
    )

    assert b_ignition_pass["baseline"]["fusion"]["triggered"] is True
    assert b_ignition_pass["baseline"]["triggered"] is True
    assert b_ignition_fail["baseline"]["fusion"]["triggered"] is False
    assert summarize_first_failure(b_ignition_fail["baseline"]["fusion"]["checks"]) == "tier_gate"
    assert a_focus_fail["baseline"]["fusion"]["triggered"] is False
    assert summarize_first_failure(a_focus_fail["baseline"]["fusion"]["checks"]) == "tier_gate"


def test_accdelta_can_satisfy_fusion_acceleration_gate_when_acceleration_is_low() -> None:
    result = evaluate_shadow_variants(
        make_signal(
            change=5.2,
            accDelta=8.4,
            rankTrend={
                "jump": {
                    "event": "jump",
                    "direction": "buy",
                    "confidence": 92.0,
                    "sustained": True,
                },
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {
                        "short": 2.17,
                        "mid": 12.0,
                        "long": 1.42,
                        "acceleration": 5.0,
                    },
                },
                "meta": {"sampleQuality": {"status": "ok"}},
                "cycle": {"stage": "expansion", "decision": {"action": "allow"}},
                "strategy": {"candidateTier": "A_MAIN"},
            },
        )
    )

    assert result["baseline"]["fusion"]["triggered"] is True
    assert result["baseline"]["triggered"] is True


def test_not_limit_up_uses_board_specific_thresholds() -> None:
    growth_board = evaluate_shadow_variants(
        make_signal(
            code="300001",
            change=10.5,
            rankTrend={
                "jump": {
                    "event": "jump",
                    "direction": "buy",
                    "confidence": 92.0,
                    "sustained": True,
                },
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {
                        "short": 2.17,
                        "mid": 12.0,
                        "long": 1.42,
                        "acceleration": 11.3,
                    },
                },
                "meta": {"sampleQuality": {"status": "ok"}},
                "cycle": {"stage": "expansion", "decision": {"action": "allow"}},
                "strategy": {"candidateTier": "A_MAIN"},
            },
        )
    )
    main_board = evaluate_shadow_variants(
        make_signal(
            code="600001",
            change=10.5,
            rankTrend={
                "jump": {
                    "event": "jump",
                    "direction": "buy",
                    "confidence": 92.0,
                    "sustained": True,
                },
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {
                        "short": 2.17,
                        "mid": 12.0,
                        "long": 1.42,
                        "acceleration": 11.3,
                    },
                },
                "meta": {"sampleQuality": {"status": "ok"}},
                "cycle": {"stage": "expansion", "decision": {"action": "allow"}},
                "strategy": {"candidateTier": "A_MAIN"},
            },
        )
    )

    assert growth_board["baseline"]["jump"]["triggered"] is True
    assert main_board["baseline"]["jump"]["triggered"] is False
    assert summarize_first_failure(main_board["baseline"]["jump"]["checks"]) == "not_limit_up"


def test_rank_shadow_candidate_prioritizes_a_main_and_confirmed_b_ignition() -> None:
    neutral = rank_shadow_candidate(
        {
            "code": "600100",
            "rankTrend": {
                "cycle": {"stage": "ignition"},
                "strategy": {"candidateTier": "N_NEUTRAL"},
                "technical": {
                    "signals": {
                        "direction": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {"mid": 18},
                },
            },
        }
    )
    confirmed_b = rank_shadow_candidate(
        {
            "code": "600101",
            "rankTrend": {
                "cycle": {"stage": "ignition"},
                "strategy": {"candidateTier": "B_IGNITION"},
                "technical": {
                    "signals": {
                        "direction": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {"mid": 21},
                },
            },
        }
    )
    a_main = rank_shadow_candidate(
        {
            "code": "600102",
            "rankTrend": {
                "cycle": {"stage": "expansion"},
                "strategy": {"candidateTier": "A_MAIN"},
                "technical": {
                    "signals": {
                        "direction": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {"mid": 25},
                },
            },
        }
    )

    assert confirmed_b["score"] > neutral["score"]
    assert a_main["score"] > neutral["score"]
    assert "b_ignition_mid>=20_zeroCross:buy" in confirmed_b["reasons"]


def test_load_hotlist_anchor_samples_reads_minimal_contract(tmp_path) -> None:
    path = tmp_path / "anchors.json"
    path.write_text(
        """
        [
          {
            "code": "600186",
            "tradingDate": "2026-06-09",
            "slotTime": "10:30",
            "snapshotType": "half_hour",
            "label": "lotus_1030",
            "evidence": "技术三买共振，盘中热榜买点",
            "annotator": "user",
            "status": "confirmed"
          }
        ]
        """.strip(),
        encoding="utf-8",
    )

    anchors = load_hotlist_anchor_samples(path)

    assert anchors == [
        {
            "code": "600186",
            "tradingDate": "2026-06-09",
            "slotTime": "10:30",
            "snapshotType": "half_hour",
            "label": "lotus_1030",
            "evidence": "技术三买共振，盘中热榜买点",
            "annotator": "user",
            "status": "confirmed",
        }
    ]


def test_hotlist_anchor_fixture_keeps_tfwd_borderline_until_bar_is_confirmed() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "ranktrend_hotlist_anchor_samples.json"

    anchors = load_hotlist_anchor_samples(fixture_path)
    tfwd = next(item for item in anchors if item["code"] == "002156")

    assert tfwd["status"] == "borderline"
    assert tfwd["slotTime"] == ""


def test_classify_hotlist_buy_pattern_marks_progressive_non_explosive_setup() -> None:
    tags = classify_hotlist_buy_pattern(
        {
            "change": 5.2,
            "rankTrend": {
                "jump": {"direction": "buy", "confidence": 78, "sustained": True},
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {
                        "short": 7.3,
                        "mid": 24.9,
                        "long": 28.6,
                        "acceleration": 4.3,
                    },
                },
                "cycle": {"stage": "expansion"},
            },
        }
    )

    assert "technical_buy_alignment" in tags
    assert "progressive_rank_lift" in tags
    assert "non_explosive_but_valid" in tags
    assert "early_hotlist_ignition" not in tags


def test_classify_hotlist_buy_pattern_handles_missing_ranktrend_fields() -> None:
    tags = classify_hotlist_buy_pattern({"code": "000001"})

    assert tags == []


def test_scan_jump_confidence_thresholds_returns_interval_rows() -> None:
    findings = [
        {
            "code": "600186",
            "isAnchor": True,
            "isPositiveOutcome": True,
            "baselineSignal": {
                "rankTrend": {
                    "jump": {
                        "confidence": 79.8,
                        "direction": "buy",
                        "event": "jump",
                        "sustained": True,
                    }
                }
            },
            "hotlistBuyTags": ["technical_buy_alignment"],
        },
        {
            "code": "300433",
            "isAnchor": False,
            "isPositiveOutcome": True,
            "baselineSignal": {
                "rankTrend": {
                    "jump": {
                        "confidence": 77.9,
                        "direction": "buy",
                        "event": "jump",
                        "sustained": True,
                    }
                }
            },
            "hotlistBuyTags": ["technical_buy_alignment"],
        },
        {
            "code": "000001",
            "isAnchor": False,
            "isPositiveOutcome": False,
            "baselineSignal": {
                "rankTrend": {
                    "jump": {
                        "confidence": 81.0,
                        "direction": "buy",
                        "event": "jump",
                        "sustained": True,
                    }
                }
            },
            "hotlistBuyTags": [],
        },
    ]

    rows = scan_jump_confidence_thresholds(findings, thresholds=[75, 80, 85, 90])

    assert [row["threshold"] for row in rows] == [75.0, 80.0, 85.0, 90.0]
    assert rows[0]["anchorRecallCount"] == 1
    assert rows[1]["anchorRecallCount"] == 0
    assert rows[0]["positiveRecallCount"] == 2
    assert rows[0]["noiseCount"] == 1
    assert rows[0]["derivedBy"] == "rule"


def test_summarize_fusion_gate_misses_separates_anchor_extended_and_reason_types() -> None:
    findings = [
        {
            "isAnchor": True,
            "hotlistBuyTags": ["technical_buy_alignment"],
            "candidateTier": "N_NEUTRAL",
            "cycleStage": "ignition",
            "cycleDecisionAction": "allow",
            "sampleQualityStatus": "ok",
            "variantResults": {
                "baseline": {
                    "fusion": {
                        "checks": [
                            {"name": "short_mid_long_positive", "passed": True},
                            {"name": "acceleration_ge_10_or_accdelta_ge_8", "passed": False},
                            {"name": "tier_gate", "passed": False},
                        ]
                    }
                }
            },
        },
        {
            "isAnchor": False,
            "hotlistBuyTags": ["technical_buy_alignment", "non_explosive_but_valid"],
            "candidateTier": "B_IGNITION",
            "cycleStage": "expansion",
            "cycleDecisionAction": "allow",
            "sampleQualityStatus": "ok",
            "variantResults": {
                "baseline": {
                    "fusion": {
                        "checks": [
                            {"name": "short_mid_long_positive", "passed": True},
                            {"name": "tier_gate", "passed": False},
                        ]
                    }
                }
            },
        },
    ]

    summary = summarize_fusion_gate_misses(findings)

    assert summary["anchorMissCounts"]["acceleration_ge_10_or_accdelta_ge_8"] == 1
    assert "tier_gate" not in summary["anchorMissCounts"]
    assert summary["extendedMissCounts"]["tier_gate"] == 1
    assert summary["reasonTypeCounts"]["true_gate_block"] == 1
    assert summary["reasonTypeCounts"]["candidate_tier_side_effect"] == 1
    assert summary["confounderBreakdowns"]["candidateTier"]["B_IGNITION"] == 1


def test_summarize_fusion_gate_misses_marks_baseline_missing_as_replay_missing() -> None:
    summary = summarize_fusion_gate_misses(
        [
            {
                "isAnchor": True,
                "variantResults": {
                    "baseline": {
                        "fusion": {
                            "checks": [
                                {"name": "signal_missing_in_baseline_replay", "passed": False}
                            ]
                        }
                    }
                },
            }
        ]
    )

    assert summary["anchorMissCounts"]["signal_missing_in_baseline_replay"] == 1
    assert summary["reasonTypeCounts"]["replay_missing"] == 1
    assert "true_gate_block" not in summary["reasonTypeCounts"]


class StubAuditRepo:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def load_dataset_bundle_slice(
        self,
        dataset_id: str,
        *,
        snapshot_types: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        max_snapshots: int | None = None,
    ):
        self.calls.append(
            {
                "dataset_id": dataset_id,
                "snapshot_types": snapshot_types,
                "start_date": start_date,
                "end_date": end_date,
                "max_snapshots": max_snapshots,
            }
        )
        frames = [
            {
                "snapshotId": "s1",
                "type": "half_hour",
                "tradingDate": "2026-06-03",
                "slotTime": "09:30",
                "timestamp": 1,
            },
            {
                "snapshotId": "s2",
                "type": "half_hour",
                "tradingDate": "2026-06-03",
                "slotTime": "10:00",
                "timestamp": 2,
            },
        ]
        stock_rows = [
            {"snapshotId": "s1", "code": "600186", "name": "莲花控股", "rank": 1},
            {"snapshotId": "s1", "code": "002156", "name": "通富微电", "rank": 2},
            {"snapshotId": "s2", "code": "600186", "name": "莲花控股", "rank": 1},
            {"snapshotId": "s2", "code": "002156", "name": "通富微电", "rank": 2},
        ]
        return [], frames, stock_rows, []


class StubRankTrendLiveGateAuditService(RankTrendLiveGateAuditService):
    def __init__(self) -> None:
        self.repo = StubAuditRepo()
        self.replay_calls: list[dict[str, object]] = []

    def _today(self) -> date:
        return date(2026, 6, 9)

    def _replay_frame_signals(
        self,
        frames: list[dict[str, object]],
        *,
        jump_delta_pct: float = 15.0,
    ) -> dict[str, dict[str, object]]:
        snapshot_id = str(frames[-1]["snapshotId"])
        self.replay_calls.append(
            {
                "snapshot_id": snapshot_id,
                "frame_count": len(frames),
                "jump_delta_pct": jump_delta_pct,
            }
        )
        base_600186 = make_signal(snapshotId=snapshot_id)
        base_002156 = make_signal(
            code="002156",
            name="通富微电",
            snapshotId=snapshot_id,
            change=5.2,
            rankTrend={
                "jump": {
                    "event": "jump",
                    "direction": "buy" if jump_delta_pct != 10.0 else "sell",
                    "confidence": 92.0,
                    "sustained": True,
                },
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                        "zeroCross": {"signal": "buy"},
                    },
                    "momentumProfile": {
                        "short": 2.17,
                        "mid": 10.41,
                        "long": 1.42,
                        "acceleration": 11.3,
                    },
                },
                "meta": {"sampleQuality": {"status": "ok"}},
                "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
                "strategy": {"candidateTier": "A_MAIN"},
            },
        )
        signal_map = {
            "600186": deepcopy(base_600186),
            "002156": deepcopy(base_002156),
        }
        if jump_delta_pct == 12.5:
            signal_map.pop("600186")
        return signal_map


class StubVariantOnlyRecallAuditService(StubRankTrendLiveGateAuditService):
    def _replay_frame_signals(
        self,
        frames: list[dict[str, object]],
        *,
        jump_delta_pct: float = 15.0,
    ) -> dict[str, dict[str, object]]:
        snapshot_id = str(frames[-1]["snapshotId"])
        self.replay_calls.append(
            {
                "snapshot_id": snapshot_id,
                "frame_count": len(frames),
                "jump_delta_pct": jump_delta_pct,
            }
        )
        baseline_only = {
            "600186": deepcopy(make_signal(snapshotId=snapshot_id)),
        }
        if jump_delta_pct == 10.0:
            baseline_only["300001"] = make_signal(
                code="300001",
                name="特例召回",
                snapshotId=snapshot_id,
                change=4.2,
                rankTrend={
                    "jump": {
                        "event": "jump",
                        "direction": "buy",
                        "confidence": 95.0,
                        "sustained": True,
                    },
                    "technical": {
                        "macd": {"cross": "golden"},
                        "signals": {
                            "direction": {"signal": "buy"},
                            "acceleration": {"signal": "buy"},
                            "zeroCross": {"signal": "buy"},
                        },
                        "momentumProfile": {
                            "short": 2.1,
                            "mid": 8.4,
                            "long": 1.1,
                            "acceleration": 10.4,
                        },
                    },
                    "meta": {"sampleQuality": {"status": "ok"}},
                    "cycle": {"stage": "ignition", "decision": {"action": "allow"}},
                    "strategy": {"candidateTier": "A_MAIN"},
                },
            )
        return baseline_only


class StubNoReplaySignalAuditService(StubRankTrendLiveGateAuditService):
    def _replay_frame_signals(
        self,
        frames: list[dict[str, object]],
        *,
        jump_delta_pct: float = 15.0,
    ) -> dict[str, dict[str, object]]:
        snapshot_id = str(frames[-1]["snapshotId"])
        self.replay_calls.append(
            {
                "snapshot_id": snapshot_id,
                "frame_count": len(frames),
                "jump_delta_pct": jump_delta_pct,
            }
        )
        return {}


class StubAccDeltaRatioAuditRepo(StubAuditRepo):
    def load_dataset_bundle_slice(
        self,
        dataset_id: str,
        *,
        snapshot_types: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        max_snapshots: int | None = None,
    ):
        records, frames, stock_rows, sector_rows = super().load_dataset_bundle_slice(
            dataset_id,
            snapshot_types=snapshot_types,
            start_date=start_date,
            end_date=end_date,
            max_snapshots=max_snapshots,
        )
        stock_rows[1]["accDelta"] = 9.5
        return records, frames, stock_rows, sector_rows


class StubAccDeltaRatioAuditService(StubRankTrendLiveGateAuditService):
    def __init__(self) -> None:
        self.repo = StubAccDeltaRatioAuditRepo()
        self.replay_calls: list[dict[str, object]] = []


def test_live_gate_audit_service_returns_three_layers_and_separate_replay_results() -> None:
    service = StubRankTrendLiveGateAuditService()

    result = service.run({"dataset_id": "ds_live_gate"})

    assert service.repo.calls == [
        {
            "dataset_id": "ds_live_gate",
            "snapshot_types": ["half_hour"],
            "start_date": "2026-06-03",
            "end_date": "2026-06-09",
            "max_snapshots": None,
        }
    ]
    assert result["meta"]["snapshotType"] == "half_hour"
    assert result["meta"]["accDeltaPresentRatio"] == 0.0
    assert "accDeltaPolicy" in result["meta"]
    assert "engineMetaPolicy" in result["meta"]
    assert result["focusFindings"]
    assert result["dailySummaries"]
    assert result["rankingSuggestions"]
    assert [item["snapshotId"] for item in result["rankingSuggestions"][:4]] == ["s1", "s2", "s1", "s2"]

    focus_by_snapshot_and_code = {
        (item["snapshotId"], item["code"]): item for item in result["focusFindings"]
    }
    lotus_findings = [item for item in result["focusFindings"] if item["code"] == "600186"]
    tfwd_findings = [item for item in result["focusFindings"] if item["code"] == "002156"]

    assert [(item["snapshotId"], item["code"]) for item in result["focusFindings"]] == [
        ("s1", "002156"),
        ("s1", "600186"),
        ("s2", "002156"),
        ("s2", "600186"),
    ]
    assert [item["snapshotId"] for item in lotus_findings] == ["s1", "s2"]
    assert [item["snapshotId"] for item in tfwd_findings] == ["s1", "s2"]

    lotus = focus_by_snapshot_and_code[("s1", "600186")]
    lotus_second = focus_by_snapshot_and_code[("s2", "600186")]
    tfwd = focus_by_snapshot_and_code[("s1", "002156")]
    tfwd_second = focus_by_snapshot_and_code[("s2", "002156")]

    assert lotus["baselineTriggered"] is False
    assert lotus["baselineJumpTriggered"] is False
    assert lotus["baselineFusionTriggered"] is False
    assert lotus["firstJumpFailure"] == "jump_confidence"
    assert lotus["firstFusionFailure"] == "change_lt_6"
    assert set(lotus["variantResults"]["baseline"]) >= {"jump", "fusion"}
    assert lotus["variantResults"]["delta_12_5"]["triggered"] is False
    assert lotus["variantResults"]["delta_12_5"]["liveGateTriggered"] is False
    assert lotus["variantResults"]["delta_12_5"]["missingSignal"] is True
    assert lotus["variantResults"]["delta_12_5"]["failureReason"] == "signal_missing_in_replay"
    assert lotus["variantResults"]["delta_12_5"]["evaluationMode"] == "replay_missing"
    assert lotus["variantResults"]["delta_12_5"]["requiresReplayConfirmation"] is False
    assert lotus["variantResults"]["delta_12_5"]["jump"] == {
        "triggered": False,
        "missing": True,
        "checks": [],
    }
    assert lotus["variantResults"]["delta_12_5"]["fusion"] == {
        "triggered": False,
        "missing": True,
        "checks": [],
    }
    assert lotus_second["variantResults"]["delta_12_5"]["missingSignal"] is True
    assert lotus_second["variantResults"]["delta_12_5"]["liveGateTriggered"] is False
    assert lotus_second["variantResults"]["delta_12_5"]["jump"] == {
        "triggered": False,
        "missing": True,
        "checks": [],
    }
    assert lotus_second["variantResults"]["delta_12_5"]["fusion"] == {
        "triggered": False,
        "missing": True,
        "checks": [],
    }

    assert tfwd["variantResults"]["baseline"]["jump"]["signal"]["direction"] == "buy"
    assert "missingSignal" not in tfwd["variantResults"]["delta_12_5"]
    assert set(tfwd["variantResults"]["delta_12_5"]) >= {"jump", "fusion"}
    assert tfwd["variantResults"]["delta_10"]["jump"]["signal"]["direction"] == "sell"
    assert tfwd["variantResults"]["delta_10"]["triggered"] is False
    assert tfwd["variantResults"]["delta_10"]["requiresReplayConfirmation"] is False
    assert tfwd["variantResults"]["recall_first"]["jump"]["signal"]["direction"] == "sell"
    assert tfwd_second["variantResults"]["delta_10"]["jump"]["signal"]["direction"] == "sell"
    assert tfwd_second["variantResults"]["recall_first"]["jump"]["signal"]["direction"] == "sell"

    assert service.replay_calls == [
        {"snapshot_id": "s1", "frame_count": 1, "jump_delta_pct": 15.0},
        {"snapshot_id": "s2", "frame_count": 2, "jump_delta_pct": 15.0},
        {"snapshot_id": "s1", "frame_count": 1, "jump_delta_pct": 12.5},
        {"snapshot_id": "s2", "frame_count": 2, "jump_delta_pct": 12.5},
        {"snapshot_id": "s1", "frame_count": 1, "jump_delta_pct": 10.0},
        {"snapshot_id": "s2", "frame_count": 2, "jump_delta_pct": 10.0},
    ]


def test_live_gate_audit_service_filters_focus_findings_by_focus_codes() -> None:
    service = StubRankTrendLiveGateAuditService()

    result = service.run({"dataset_id": "ds_live_gate", "focus_codes": ["600186"]})

    assert {(item["snapshotId"], item["code"]) for item in result["focusFindings"]} == {
        ("s1", "600186"),
        ("s2", "600186"),
    }
    assert {item["code"] for item in result["rankingSuggestions"][:4]} == {"600186", "002156"}


def test_live_gate_audit_service_accdelta_ratio_scans_all_stock_rows() -> None:
    service = StubAccDeltaRatioAuditService()

    result = service.run({"dataset_id": "ds_live_gate", "focus_codes": ["600186"]})

    assert {(item["snapshotId"], item["code"]) for item in result["focusFindings"]} == {
        ("s1", "600186"),
        ("s2", "600186"),
    }
    assert result["meta"]["accDeltaPresentRatio"] == 0.25


def test_live_gate_audit_service_keeps_variant_only_recall_codes() -> None:
    service = StubVariantOnlyRecallAuditService()

    result = service.run({"dataset_id": "ds_live_gate"})

    finding = next(item for item in result["focusFindings"] if item["code"] == "300001")

    assert finding["baselineTriggered"] is False
    assert finding["baselineJumpTriggered"] is False
    assert finding["baselineFusionTriggered"] is False
    assert finding["firstJumpFailure"] == "signal_missing_in_baseline_replay"
    assert finding["firstFusionFailure"] == "signal_missing_in_baseline_replay"
    assert finding["variantResults"]["baseline"]["missingSignal"] is True
    assert finding["variantResults"]["baseline"]["evaluationMode"] == "baseline_missing"
    assert finding["variantResults"]["delta_10"]["triggered"] is True
    assert finding["variantResults"]["delta_10"]["jump"]["signal"]["direction"] == "buy"
    assert any(item["code"] == "300001" for item in result["rankingSuggestions"])


def test_live_gate_audit_service_emits_hotlist_recall_research_sections() -> None:
    service = StubRankTrendLiveGateAuditService()

    result = service.run(
        {
            "dataset_id": "ds_live_gate",
            "anchor_samples": [
                {
                    "code": "600186",
                    "tradingDate": "2026-06-03",
                    "slotTime": "09:30",
                    "snapshotType": "half_hour",
                    "label": "lotus_0930",
                    "evidence": "盘中热榜买点",
                    "annotator": "user",
                    "status": "confirmed",
                }
            ],
            "confidence_thresholds": [75, 80, 85, 90],
            "research_all_frames": True,
        }
    )

    assert set(result) >= {
        "anchorFindings",
        "extendedHotlistFindings",
        "confidenceThresholdScan",
        "jumpDefinitionReplaySummary",
        "fusionGateMissSummary",
    }
    assert result["anchorFindings"][0]["isAnchor"] is True
    assert result["anchorFindings"][0]["anchorLabel"] == "lotus_0930"
    assert result["confidenceThresholdScan"][0]["threshold"] == 75.0
    assert "delta_10" in result["jumpDefinitionReplaySummary"]
    assert "anchorMissCounts" in result["fusionGateMissSummary"]


def test_live_gate_audit_service_marks_focus_findings_with_anchor_and_hotlist_tags() -> None:
    service = StubRankTrendLiveGateAuditService()

    result = service.run(
        {
            "dataset_id": "ds_live_gate",
            "focus_codes": ["600186"],
            "anchor_samples": [
                {
                    "code": "600186",
                    "tradingDate": "2026-06-03",
                    "slotTime": "10:00",
                    "snapshotType": "half_hour",
                    "label": "lotus_1000",
                    "evidence": "技术三买共振，盘中热榜买点",
                    "annotator": "user",
                    "status": "confirmed",
                }
            ],
        }
    )

    finding = next(item for item in result["focusFindings"] if item["snapshotId"] == "s2")

    assert finding["isAnchor"] is True
    assert finding["anchorLabel"] == "lotus_1000"
    assert "hotlistBuyTags" in finding
    assert finding["baselineSignal"] is not None
    assert finding["displaySignal"] is not None


def test_live_gate_audit_service_keeps_baseline_signal_separate_from_variant_display_signal() -> None:
    service = StubVariantOnlyRecallAuditService()

    result = service.run({"dataset_id": "ds_live_gate", "research_all_frames": True})

    finding = next(item for item in result["extendedHotlistFindings"] if item["code"] == "300001")

    assert finding["baselineSignal"] is None
    assert finding["displaySignal"] is not None
    assert finding["variantResults"]["delta_10"]["triggered"] is True


def test_live_gate_audit_service_reports_focus_code_when_all_replays_are_missing() -> None:
    service = StubNoReplaySignalAuditService()

    result = service.run(
        {
            "dataset_id": "ds_live_gate",
            "focus_codes": ["600186"],
            "anchor_samples": [
                {
                    "code": "600186",
                    "tradingDate": "2026-06-03",
                    "slotTime": "09:30",
                    "snapshotType": "half_hour",
                    "label": "lotus_missing",
                    "evidence": "热榜行存在但 replay 无信号",
                    "annotator": "user",
                    "status": "confirmed",
                },
                {
                    "code": "002156",
                    "tradingDate": "2026-06-09",
                    "slotTime": "",
                    "snapshotType": "half_hour",
                    "label": "tfwd_pending",
                    "evidence": "具体 bar 待补",
                    "annotator": "user",
                    "status": "borderline",
                },
            ],
        }
    )

    finding = next(item for item in result["focusFindings"] if item["code"] == "600186")

    assert finding["baselineSignal"] is None
    assert finding["displaySignal"] is None
    assert finding["isAnchor"] is True
    assert finding["firstJumpFailure"] == "signal_missing_in_baseline_replay"
    assert finding["firstFusionFailure"] == "signal_missing_in_baseline_replay"
    assert result["meta"]["anchorSampleStatusCounts"] == {"confirmed": 1, "borderline": 1}
    assert result["fusionGateMissSummary"]["reasonTypeCounts"]["replay_missing"] >= 1


def test_live_gate_audit_service_allows_snapshot_type_override() -> None:
    service = StubRankTrendLiveGateAuditService()

    service.run({"dataset_id": "ds_live_gate", "snapshot_type": "quarter_hour"})

    assert service.repo.calls == [
        {
            "dataset_id": "ds_live_gate",
            "snapshot_types": ["quarter_hour"],
            "start_date": "2026-06-03",
            "end_date": "2026-06-09",
            "max_snapshots": None,
        }
    ]


def test_live_gate_audit_service_requires_dataset_id() -> None:
    service = StubRankTrendLiveGateAuditService()

    try:
        service.run({})
    except ValueError as exc:
        assert str(exc) == "dataset_id is required"
    else:
        raise AssertionError("expected ValueError when dataset_id is missing")


def test_live_gate_audit_service_rejects_empty_frames() -> None:
    service = RankTrendLiveGateAuditService.__new__(RankTrendLiveGateAuditService)
    service.repo = type(
        "EmptyRepo",
        (),
        {
            "load_dataset_bundle_slice": staticmethod(
                lambda *args, **kwargs: ([], [], [], [])
            )
        },
    )()

    try:
        service.run({"dataset_id": "ds_empty"})
    except ValueError as exc:
        assert str(exc) == "dataset has no frames for half_hour: ds_empty"
    else:
        raise AssertionError("expected ValueError when dataset has no frames")


def test_cli_audit_ranktrend_live_gates_parses_parameters() -> None:
    from backend.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        [
            "audit-ranktrend-live-gates",
            "--dataset-id",
            "dragonboard_live",
            "--snapshot-type",
            "quarter_hour",
            "--start-date",
            "2026-06-01",
            "--end-date",
            "2026-06-09",
            "--focus-code",
            "600186",
            "--focus-code",
            "002156",
            "--anchor-file",
            "fixtures/anchors.json",
            "--confidence-thresholds",
            "75,80,85,90",
            "--research-all-frames",
            "--output",
            "tmp/audit.json",
        ]
    )

    assert args.func.__name__ == "cmd_audit_ranktrend_live_gates"
    assert args.dataset_id == "dragonboard_live"
    assert args.snapshot_type == "quarter_hour"
    assert args.start_date == "2026-06-01"
    assert args.end_date == "2026-06-09"
    assert args.focus_code == ["600186", "002156"]
    assert args.anchor_file == "fixtures/anchors.json"
    assert args.confidence_thresholds == [75.0, 80.0, 85.0, 90.0]
    assert args.research_all_frames is True
    assert args.output == "tmp/audit.json"


def test_cli_audit_ranktrend_live_gates_uses_default_focus_codes_and_writes_output(
    tmp_path,
    monkeypatch,
) -> None:
    import backend.cli as cli

    captured: dict[str, object] = {}
    printed: list[dict[str, object]] = []
    result = {"ok": True, "focusFindings": [{"code": "600186", "name": "莲花控股"}]}

    class StubCliAuditService:
        def __init__(self, session) -> None:
            captured["session"] = session

        def run(self, payload: dict[str, object]) -> dict[str, object]:
            captured["payload"] = payload
            return result

    output = tmp_path / "nested" / "audit.json"

    monkeypatch.setattr(cli, "runtime_session", lambda: nullcontext("cli-session"))
    monkeypatch.setattr(cli, "RankTrendLiveGateAuditService", StubCliAuditService)
    monkeypatch.setattr(cli, "print_json", lambda payload: printed.append(payload))

    args = cli.build_parser().parse_args(
        [
            "audit-ranktrend-live-gates",
            "--dataset-id",
            "ds_live_gate",
            "--output",
            str(output),
        ]
    )

    cli.cmd_audit_ranktrend_live_gates(args)

    assert captured["session"] == "cli-session"
    assert captured["payload"] == {
        "dataset_id": "ds_live_gate",
        "snapshot_type": "half_hour",
        "start_date": None,
        "end_date": None,
        "focus_codes": ["600186", "002156"],
        "anchor_samples": [],
        "confidence_thresholds": [70.0, 75.0, 80.0, 85.0, 90.0, 95.0],
        "research_all_frames": False,
    }
    assert output.parent.is_dir()
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert printed == [result]


def test_cli_audit_ranktrend_live_gates_loads_anchor_file_and_confidence_thresholds(
    tmp_path,
    monkeypatch,
) -> None:
    import backend.cli as cli

    captured: dict[str, object] = {}
    anchor_file = tmp_path / "anchors.json"
    anchor_file.write_text(
        '[{"code":"600186","tradingDate":"2026-06-09","slotTime":"10:30","snapshotType":"half_hour","label":"lotus_1030","evidence":"盘中热榜买点","annotator":"user","status":"confirmed"}]',
        encoding="utf-8",
    )

    class StubCliAuditService:
        def __init__(self, session) -> None:
            captured["session"] = session

        def run(self, payload: dict[str, object]) -> dict[str, object]:
            captured["payload"] = payload
            return {
                "meta": {"datasetId": "dragonboard_live"},
                "anchorFindings": [],
                "extendedHotlistFindings": [],
                "confidenceThresholdScan": [],
                "jumpDefinitionReplaySummary": {},
                "fusionGateMissSummary": {},
            }

    monkeypatch.setattr(cli, "runtime_session", lambda: nullcontext("cli-session"))
    monkeypatch.setattr(cli, "RankTrendLiveGateAuditService", StubCliAuditService)
    monkeypatch.setattr(cli, "print_json", lambda payload: None)

    args = cli.build_parser().parse_args(
        [
            "audit-ranktrend-live-gates",
            "--dataset-id",
            "dragonboard_live",
            "--snapshot-type",
            "half_hour",
            "--anchor-file",
            str(anchor_file),
            "--confidence-thresholds",
            "75,80,85,90",
            "--research-all-frames",
        ]
    )

    cli.cmd_audit_ranktrend_live_gates(args)

    assert captured["payload"] == {
        "dataset_id": "dragonboard_live",
        "snapshot_type": "half_hour",
        "start_date": None,
        "end_date": None,
        "focus_codes": ["600186", "002156"],
        "anchor_samples": [
            {
                "code": "600186",
                "tradingDate": "2026-06-09",
                "slotTime": "10:30",
                "snapshotType": "half_hour",
                "label": "lotus_1030",
                "evidence": "盘中热榜买点",
                "annotator": "user",
                "status": "confirmed",
            }
        ],
        "confidence_thresholds": [75.0, 80.0, 85.0, 90.0],
        "research_all_frames": True,
    }
