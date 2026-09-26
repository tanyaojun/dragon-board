"""因子时间序列小模块已知答案校验（Phase 3，设计文档 §5.1 D2/D3、§5.2 F1 研究口径）。"""

from backend.analysis.theme.factor_series import (
    positive_streak,
    sharpe_momentum,
    top_membership_streak,
)


class TestSharpeMomentum:
    def test_constant_series_zero_std_is_none(self):
        values = {f"d{i}": 1.0 for i in range(1, 6)}
        out = sharpe_momentum(values, window=5, min_periods=5)
        assert all(v is None for v in out.values())

    def test_insufficient_observations_is_none(self):
        values = {"d1": 1.0, "d2": 2.0}
        out = sharpe_momentum(values, window=5, min_periods=5)
        assert out["d1"] is None and out["d2"] is None

    def test_upward_trend_positive_sharpe(self):
        steady = {f"d{i:02d}": float(i) for i in range(1, 11)}
        out = sharpe_momentum(steady, window=10, min_periods=10)
        assert out["d10"] is not None and out["d10"] > 0

    def test_window_truncates_history(self):
        # 尾段 [3,6,9]：mean=6、总体 std=sqrt(6) → sharpe=6/sqrt(6)；
        # 前段不同取值不影响 d6 —— 截断不变性即窗口语义证明
        tail = {"d4": 3.0, "d5": 6.0, "d6": 9.0}
        a = sharpe_momentum({**{"d1": 1000.0, "d2": -1000.0}, **tail}, window=3, min_periods=3)
        b = sharpe_momentum({**{"d1": 1.0, "d2": 2.0}, **tail}, window=3, min_periods=3)
        assert a["d6"] == b["d6"]
        assert abs(a["d6"] - 6.0 / (6.0 ** 0.5)) < 1e-9

    def test_missing_day_not_in_window(self):
        # trailing 观测=有值观测：d3 窗口取 [d1,d3] 两个观测（d2 缺失不入窗）
        out = sharpe_momentum({"d1": 5.0, "d3": 7.0}, window=2, min_periods=2)
        assert abs(out["d3"] - 6.0) < 1e-9

    def test_dates_sorted_not_insertion_order(self):
        a = sharpe_momentum({"d3": 3.0, "d1": 1.0, "d2": 2.0}, window=3, min_periods=3)
        b = sharpe_momentum({"d1": 1.0, "d2": 2.0, "d3": 3.0}, window=3, min_periods=3)
        assert a == b

    def test_negative_sharpe_for_downtrend(self):
        down = {f"d{i:02d}": -float(i) for i in range(1, 11)}
        out = sharpe_momentum(down, window=10, min_periods=10)
        assert out["d10"] is not None and out["d10"] < 0


class TestTopMembershipStreak:
    def test_streak_accrues_and_resets(self):
        top = {"d1": {"A"}, "d2": {"A"}, "d3": set(), "d4": {"A", "B"}}
        observed = {"d1": {"A"}, "d2": {"A"}, "d3": {"A"}, "d4": {"A", "B"}}
        out = top_membership_streak(top, observed, "A")
        assert out == {"d1": 1, "d2": 2, "d3": 0, "d4": 1}

    def test_absence_breaks_chain_with_none(self):
        # d2 A 未观测（题材不在当日横截面）→ None 断链，d3 从 1 重计
        top = {"d1": {"A"}, "d2": {"B"}, "d3": {"A"}}
        observed = {"d1": {"A", "B"}, "d2": {"B"}, "d3": {"A"}}
        out = top_membership_streak(top, observed, "A")
        assert out == {"d1": 1, "d2": None, "d3": 1}

    def test_day_without_top_set_counts_as_miss(self):
        # 观测了但当日无 Top 集合（横截面过薄未构建）→ 按落选归 0
        top = {"d1": {"A"}}
        observed = {"d1": {"A"}, "d2": {"A"}}
        out = top_membership_streak(top, observed, "A")
        assert out == {"d1": 1, "d2": 0}

    def test_theme_never_observed(self):
        out = top_membership_streak({"d1": {"A"}}, {"d1": {"A"}}, "B")
        assert out == {"d1": None}


class TestPositiveStreak:
    def test_accrue_and_reset(self):
        values = {"d1": 5.0, "d2": 0.0, "d3": -1.0, "d4": 3.0, "d5": 4.0}
        assert positive_streak(values) == {"d1": 1, "d2": 0, "d3": 0, "d4": 1, "d5": 2}

    def test_none_day_breaks_chain(self):
        values = {"d1": 5.0, "d2": None, "d3": 2.0}
        assert positive_streak(values) == {"d1": 1, "d2": None, "d3": 1}

    def test_zero_not_positive(self):
        values = {"d1": 0.0, "d2": 0.0001}
        assert positive_streak(values) == {"d1": 0, "d2": 1}

    def test_threshold_strictly_greater(self):
        values = {"d1": 5.0, "d2": 10.0}
        assert positive_streak(values, threshold=5.0) == {"d1": 0, "d2": 1}

    def test_dates_sorted_not_insertion_order(self):
        a = positive_streak({"d3": 3.0, "d1": -1.0, "d2": 2.0})
        b = positive_streak({"d1": -1.0, "d2": 2.0, "d3": 3.0})
        assert a == b

    def test_empty(self):
        assert positive_streak({}) == {}
