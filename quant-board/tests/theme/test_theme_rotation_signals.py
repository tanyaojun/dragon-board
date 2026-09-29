"""SG 三信号算子已知答案校验（Phase R3，设计文档 §5.4）。

合同统一：{date: bool | None}——True=当日触发；False=可判定但未触发；
None=不可判定（无前置证据/断链），不伪造。
"""

from backend.analysis.theme.rotation.signals import (
    rrg_quadrants,
    sg1_rrg_migration_flags,
    sg2_rotation_switch_flags,
    sg3_inflow_turn_positive_flags,
)


class TestRrgQuadrants:
    def test_outperforming_rising_is_leading(self):
        # 基准恒 0：RS=题材指数本身；+10%/日 → RS>1 且动量>0
        assert rrg_quadrants([0.1, 0.1], [0.0, 0.0]) == [None, "leading"]

    def test_underperforming_falling_is_lagging(self):
        assert rrg_quadrants([-0.1, -0.1], [0.0, 0.0]) == [None, "lagging"]

    def test_below_one_but_rising_is_improving(self):
        assert rrg_quadrants([-0.1, 0.1], [0.0, 0.0]) == [None, "improving"]

    def test_above_one_but_falling_is_weakening(self):
        # 题材第二日持平、基准 +5% → RS 1.1→1.0476 相对回落但仍 >1（weakening 形态）
        assert rrg_quadrants([0.1, 0.0], [0.0, 0.05]) == [None, "weakening"]

    def test_rs_exactly_one_with_zero_momentum_is_leading(self):
        # RS>=1 含边界（恰为 1）；动量>=0 含边界（恰为 0）
        assert rrg_quadrants([0.0, 0.0], [0.0, 0.0]) == [None, "leading"]

    def test_benchmark_nonzero_relative_strength(self):
        # 题材 +10% vs 基准 +5% → RS=1.1/1.05>1，首日动量不可知
        assert rrg_quadrants([0.1], [0.05]) == [None]

    def test_length_mismatch_truncated_to_min(self):
        out = rrg_quadrants([0.1, 0.1, 0.1], [0.0])
        assert len(out) == 1 and out[0] is None

    def test_empty_inputs(self):
        assert rrg_quadrants([], []) == []


class TestSg1RrgMigration:
    def test_lagging_to_improving_triggers(self):
        flags = sg1_rrg_migration_flags({"d1": "lagging", "d2": "improving"})
        assert flags == {"d1": None, "d2": True}

    def test_weakening_to_leading_triggers(self):
        flags = sg1_rrg_migration_flags({"d1": "weakening", "d2": "leading"})
        assert flags == {"d1": None, "d2": True}

    def test_other_transitions_do_not_trigger(self):
        flags = sg1_rrg_migration_flags({"d1": "lagging", "d2": "leading", "d3": "improving", "d4": "improving"})
        assert flags == {"d1": None, "d2": False, "d3": False, "d4": False}

    def test_none_day_breaks_chain(self):
        flags = sg1_rrg_migration_flags({"d1": "lagging", "d2": None, "d3": "improving"})
        assert flags == {"d1": None, "d2": None, "d3": None}

    def test_empty_map(self):
        assert sg1_rrg_migration_flags({}) == {}


class TestSg2RotationSwitch:
    def test_outflow_to_inflow_triggers(self):
        flags = sg2_rotation_switch_flags({"d1": "outflow", "d2": "inflow"})
        assert flags == {"d1": None, "d2": True}

    def test_neutral_to_inflow_triggers(self):
        flags = sg2_rotation_switch_flags({"d1": "neutral", "d2": "inflow"})
        assert flags == {"d1": None, "d2": True}

    def test_cooling_to_inflow_not_in_whitelist(self):
        # 白名单只有 outflow/neutral→inflow；cooling→inflow 是研究口径外的迁移
        flags = sg2_rotation_switch_flags({"d1": "cooling", "d2": "inflow"})
        assert flags == {"d1": None, "d2": False}

    def test_same_state_does_not_trigger(self):
        flags = sg2_rotation_switch_flags({"d1": "inflow", "d2": "inflow"})
        assert flags == {"d1": None, "d2": False}

    def test_none_day_breaks_chain(self):
        flags = sg2_rotation_switch_flags({"d1": "outflow", "d2": None, "d3": "inflow"})
        assert flags == {"d1": None, "d2": None, "d3": None}

    def test_empty_map(self):
        assert sg2_rotation_switch_flags({}) == {}


class TestSg3InflowTurnPositive:
    def test_negative_then_positive_triggers(self):
        flags = sg3_inflow_turn_positive_flags({"d1": -100.0, "d2": -50.0, "d3": 30.0})
        assert flags == {"d1": False, "d2": False, "d3": True}

    def test_history_starting_positive_is_undecidable_then_false(self):
        # 历史首日即为正：无前置非正证据 → None；此后正段持续 → False
        flags = sg3_inflow_turn_positive_flags({"d1": 100.0, "d2": 100.0})
        assert flags == {"d1": None, "d2": False}

    def test_positive_min_days_two_requires_two_consecutive(self):
        flags = sg3_inflow_turn_positive_flags({"d1": -100.0, "d2": 30.0, "d3": 40.0}, positive_min_days=2)
        assert flags == {"d1": False, "d2": False, "d3": True}

    def test_positive_min_days_two_single_day_positive_not_enough(self):
        flags = sg3_inflow_turn_positive_flags({"d1": -100.0, "d2": 30.0}, positive_min_days=2)
        assert flags == {"d1": False, "d2": False}

    def test_none_day_breaks_chain_and_rebuilds_baseline(self):
        # 断链后首个已知正值无前置证据 → None；重新观察到非正后可再触发
        flags = sg3_inflow_turn_positive_flags({"d1": -1.0, "d2": None, "d3": 5.0, "d4": -2.0, "d5": 7.0})
        assert flags == {"d1": False, "d2": None, "d3": None, "d4": False, "d5": True}

    def test_zero_counts_as_non_positive(self):
        flags = sg3_inflow_turn_positive_flags({"d1": 0.0, "d2": 1.0})
        assert flags == {"d1": False, "d2": True}

    def test_empty_map(self):
        assert sg3_inflow_turn_positive_flags({}) == {}

    def test_invalid_positive_min_days_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            sg3_inflow_turn_positive_flags({"d1": 1.0}, positive_min_days=0)
