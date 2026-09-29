"""rotation_regime 已知答案校验（Phase R2 三态 + Phase R3 引擎权威口径重构，设计文档 §5.3）。"""

from backend.analysis.theme.rotation.regime import (
    classify_regime,
    regime_sequence,
    rotation_state_context,
    top1_streaks,
    transition_counts,
)


class TestClassifyRegime:
    def test_fast_and_scattered_is_chaotic(self):
        # R1 实测 7-8 月形态：rot 0.89-0.93 / entropy 0.96
        assert classify_regime(0.89, 0.96) == "chaotic"

    def test_slow_and_concentrated_is_concentrated(self):
        # R1 实测 9 月形态：rot 0.45 / entropy 0.84
        assert classify_regime(0.45, 0.84) == "concentrated"

    def test_fast_and_concentrated_is_rotating(self):
        assert classify_regime(0.80, 0.80) == "rotating"

    def test_slow_and_scattered_merged_into_chaotic(self):
        assert classify_regime(0.30, 0.95) == "chaotic"

    def test_boundary_inclusive_on_hi_thresholds(self):
        # rot==rot_hi 记快；entropy==entropy_hi 记散（>= 语义）
        assert classify_regime(0.70, 0.84) == "rotating"
        assert classify_regime(0.45, 0.90) == "chaotic"

    def test_missing_inputs_return_none(self):
        assert classify_regime(None, 0.9) is None
        assert classify_regime(0.5, None) is None

    def test_custom_thresholds(self):
        assert classify_regime(0.65, 0.96, rot_hi=0.60, entropy_hi=0.95) == "chaotic"


class TestRegimeSequence:
    def test_sequence_and_missing_days(self):
        metrics = {
            "d1": {"rot_speed": 0.9, "entropy": 0.96},
            "d2": {"rot_speed": None, "entropy": 0.9},
            "d3": {"rot_speed": 0.4, "entropy": 0.8},
        }
        seq = regime_sequence(metrics)
        assert seq == {"d1": "chaotic", "d2": None, "d3": "concentrated"}

    def test_empty_sequence(self):
        assert regime_sequence({}) == {}
        assert transition_counts({}) == {}


class TestTransitionCounts:
    def test_transition_matrix_counts(self):
        seq = {"d1": "chaotic", "d2": "chaotic", "d3": "concentrated", "d4": None, "d5": "concentrated"}
        counts = transition_counts(seq)
        assert counts == {("chaotic", "concentrated"): 1}

    def test_none_day_resets_transition_chain(self):
        # None 重置 prev：concentrated →(None)→ chaotic 不产生跨缺口转移
        seq = {"d1": "concentrated", "d2": None, "d3": "chaotic"}
        assert transition_counts(seq) == {}

    def test_same_state_after_none_not_recounted(self):
        seq = {"d1": "chaotic", "d2": None, "d3": "chaotic"}
        assert transition_counts(seq) == {}


class TestTop1Streaks:
    def test_same_theme_accrues(self):
        seq = {"d1": "AI", "d2": "AI", "d3": "AI"}
        assert top1_streaks(seq) == {"d1": 1, "d2": 2, "d3": 3}

    def test_switch_resets_to_one(self):
        seq = {"d1": "AI", "d2": "AI", "d3": "机器人"}
        assert top1_streaks(seq) == {"d1": 1, "d2": 2, "d3": 1}

    def test_none_day_breaks_segment(self):
        # None 日计数中断且如实输出 None；下一个已知日从 1 重算（不接断前段）
        seq = {"d1": "AI", "d2": "AI", "d3": None, "d4": "AI"}
        assert top1_streaks(seq) == {"d1": 1, "d2": 2, "d3": None, "d4": 1}

    def test_dates_sorted_not_insertion_order(self):
        # 键序无关：按日期字典序累计，乱序插入结果一致
        seq = {"d3": "AI", "d1": "AI", "d2": "AI"}
        assert top1_streaks(seq) == {"d1": 1, "d2": 2, "d3": 3}

    def test_empty_and_all_none(self):
        assert top1_streaks({}) == {}
        assert top1_streaks({"d1": None, "d2": None}) == {"d1": None, "d2": None}


class TestRotationStateContext:
    def test_full_inputs_no_flags(self):
        ctx = rotation_state_context("mainline", "cooling", 4)
        assert ctx == {
            "rotationState": "mainline",
            "marketPhase": "cooling",
            "top1Streak": 4,
            "headStable": True,
            "qualityFlags": [],
        }

    def test_head_stable_boundary_inclusive(self):
        assert rotation_state_context("inflow", "chaos", 3)["headStable"] is True
        assert rotation_state_context("inflow", "chaos", 2)["headStable"] is False

    def test_missing_top1_streak_keeps_state_but_flags(self):
        ctx = rotation_state_context("neutral", "rising", None)
        assert ctx["rotationState"] == "neutral"
        assert ctx["headStable"] is None
        assert ctx["qualityFlags"] == ["missing_top1_streak"]

    def test_missing_state_and_phase_flagged_not_fabricated(self):
        ctx = rotation_state_context(None, None, None)
        assert ctx["rotationState"] is None
        assert ctx["marketPhase"] is None
        assert sorted(ctx["qualityFlags"]) == ["missing_market_phase", "missing_rotation_state", "missing_top1_streak"]

    def test_empty_string_treated_as_missing(self):
        ctx = rotation_state_context("", "cooling", 1)
        assert ctx["rotationState"] is None
        assert ctx["qualityFlags"] == ["missing_rotation_state"]

    def test_custom_min_days(self):
        assert rotation_state_context("inflow", "cooling", 2, head_stable_min_days=2)["headStable"] is True
        assert rotation_state_context("inflow", "cooling", 1, head_stable_min_days=2)["headStable"] is False

    def test_invalid_min_days_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            rotation_state_context("inflow", "cooling", 2, head_stable_min_days=0)
