"""分位数拥挤度小模块已知答案校验（Phase 2，设计文档 §5.1 D1 研究口径）。"""

from backend.analysis.theme.crowding_percentile import (
    combine_equal_weight,
    rolling_percentile,
    theme_amount_share,
    theme_turnover_mean,
)


class TestThemeAmountShare:
    def test_share_of_pool_total(self):
        amounts = {"A": 100.0, "B": 100.0, "C": 100.0}
        members = {"T1": {"A", "B"}}
        out = theme_amount_share(amounts, members)
        # 池总和 300，T1 成员和 200 → 2/3
        assert abs(out["T1"] - 200.0 / 300.0) < 1e-9

    def test_overlapping_themes_double_count(self):
        amounts = {"A": 100.0}
        out = theme_amount_share(amounts, {"T1": {"A"}, "T2": {"A"}})
        # 一股多题材重复计入：两题材各拿满 A 份额（全题材份额和 >1 是白名单口径）
        assert abs(out["T1"] - 1.0) < 1e-9 and abs(out["T2"] - 1.0) < 1e-9

    def test_members_outside_pool_count_zero(self):
        out = theme_amount_share({"A": 100.0}, {"T1": {"A", "X"}})
        # X 不在采集池 → 计 0，分母仍是池总和
        assert abs(out["T1"] - 1.0) < 1e-9

    def test_zero_pool_returns_empty(self):
        assert theme_amount_share({}, {"T1": {"A"}}) == {}


class TestThemeTurnoverMean:
    def test_mean_over_available_members(self):
        turnover = {"A": 10.0, "B": 30.0}
        out = theme_turnover_mean(turnover, {"T1": {"A", "B", "C"}})
        # C 缺位 → 只均 A/B（缺位跳过，覆盖计数职责归调用方）
        assert abs(out["T1"] - 20.0) < 1e-9

    def test_no_available_member_is_none(self):
        assert theme_turnover_mean({}, {"T1": {"A"}})["T1"] is None


class TestRollingPercentile:
    def test_first_valid_day_uses_min_periods(self):
        values = {"d1": 10.0, "d2": 20.0, "d3": 30.0}
        out = rolling_percentile(values, window=60, min_periods=3)
        assert out["d1"] is None and out["d2"] is None
        # d3：窗口 [10,20,30]，30 为最大 → 弱占比 100
        assert abs(out["d3"] - 100.0) < 1e-9

    def test_new_low_weak_share(self):
        values = {"d1": 30.0, "d2": 20.0, "d3": 10.0}
        out = rolling_percentile(values, window=60, min_periods=3)
        # d3=10 为最小：<=10 只有自身 → 1/3
        assert abs(out["d3"] - 100.0 / 3.0) < 1e-9

    def test_window_truncates_history(self):
        values = {f"d{i}": float(i) for i in range(1, 9)}
        out = rolling_percentile(values, window=3, min_periods=2)
        # 严格递增序列：除首日外每天都是窗口新高 → 100；d1 观测不足 → None
        assert out["d1"] is None
        assert all(abs(out[f"d{i}"] - 100.0) < 1e-9 for i in range(2, 9))

    def test_all_ties_weak_share_100(self):
        values = {"d1": 5.0, "d2": 5.0, "d3": 5.0}
        out = rolling_percentile(values, window=60, min_periods=3)
        # 全并列：<= 口径全部计入 → 100（弱占比语义，docstring 显式声明）
        assert abs(out["d3"] - 100.0) < 1e-9

    def test_none_day_is_gap_not_zero(self):
        values = {"d1": 10.0, "d2": None, "d3": 20.0}
        out = rolling_percentile(values, window=60, min_periods=2)
        # 缺失日输出 None 且不入窗（trailing 观测=有值观测，不伪造）
        assert out["d2"] is None
        assert abs(out["d3"] - 100.0) < 1e-9

    def test_dates_sorted_not_insertion_order(self):
        values = {"d3": 30.0, "d1": 10.0, "d2": 20.0}
        out = rolling_percentile(values, window=60, min_periods=3)
        assert abs(out["d3"] - 100.0) < 1e-9

    def test_invalid_params_rejected(self):
        import pytest

        with pytest.raises(ValueError):
            rolling_percentile({"d1": 1.0}, window=0, min_periods=1)
        with pytest.raises(ValueError):
            rolling_percentile({"d1": 1.0}, window=5, min_periods=10)


class TestCombineEqualWeight:
    def test_average_of_two(self):
        out = combine_equal_weight({"d1": 80.0}, {"d1": 60.0})
        assert abs(out["d1"] - 70.0) < 1e-9

    def test_single_side_none_falls_back(self):
        out = combine_equal_weight({"d1": 80.0}, {"d1": None})
        assert abs(out["d1"] - 80.0) < 1e-9

    def test_both_none(self):
        assert combine_equal_weight({"d1": None}, {"d1": None})["d1"] is None
