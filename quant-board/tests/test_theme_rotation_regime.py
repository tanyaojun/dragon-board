"""rotation_regime 三态划分已知答案校验（Phase R2，设计文档 §5.3）。"""

from backend.analysis.theme.rotation.regime import (
    classify_regime,
    regime_sequence,
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


class TestRegimeSequence:
    def test_sequence_and_missing_days(self):
        metrics = {
            "d1": {"rot_speed": 0.9, "entropy": 0.96},
            "d2": {"rot_speed": None, "entropy": 0.9},
            "d3": {"rot_speed": 0.4, "entropy": 0.8},
        }
        seq = regime_sequence(metrics)
        assert seq == {"d1": "chaotic", "d2": None, "d3": "concentrated"}


class TestTransitionCounts:
    def test_transition_matrix_counts(self):
        seq = {"d1": "chaotic", "d2": "chaotic", "d3": "concentrated", "d4": None, "d5": "concentrated"}
        counts = transition_counts(seq)
        assert counts == {("chaotic", "concentrated"): 1}
