"""MainlineScore 稳定性三候选已知答案校验（Phase R2）。"""

from backend.analysis.theme.mainline_stability import (
    ema_toplists,
    hysteresis_toplists,
    window_toplists,
)


def _two_days():
    return {
        "d1": {"A": 100.0, "B": 50.0},
        "d2": {"A": 0.0, "B": 100.0},
    }


class TestEmaToplists:
    def test_ema_flips_leader_with_lag(self):
        out = ema_toplists(_two_days(), alpha=0.5, k=2)
        # d1: A=100,B=50 → [A,B]；d2: A=50,B=75 → [B,A]（EMA 引入滞后）
        assert out["d1"] == ["A", "B"]
        assert out["d2"] == ["B", "A"]

    def test_first_seen_theme_uses_raw_score(self):
        out = ema_toplists({"d1": {"A": 10.0}, "d2": {"A": 20.0, "B": 15.0}}, alpha=0.5, k=2)
        # d2: A smooth=15, B 首见=15 → 精确并列，排序键规范化后按字典序 A 先
        assert out["d2"] == ["A", "B"]

    def test_missing_day_carries_forward_smooth(self):
        out = ema_toplists(
            {"d1": {"A": 100.0, "B": 50.0}, "d2": {}, "d3": {"B": 80.0}},
            alpha=0.5,
            k=2,
        )
        # d2 全缺：沿用 d1 smooth → [A,B]；d3: B=0.5*80+0.5*50=65 < A=100 → [A,B]
        assert out["d2"] == ["A", "B"]
        assert out["d3"] == ["A", "B"]

    def test_none_score_skipped(self):
        out = ema_toplists({"d1": {"A": None, "B": 5.0}}, alpha=0.5, k=2)
        assert out["d1"] == ["B"]


class TestWindowToplists:
    def test_persistence_counting(self):
        scores = {
            "d1": {"A": 30.0, "B": 20.0, "C": 10.0},
            "d2": {"A": 30.0, "B": 20.0, "C": 10.0},
            "d3": {"B": 100.0, "C": 20.0, "A": 5.0},
        }
        out = window_toplists(scores, window=3, broad_k=2, k=2)
        # 近 3 日 Top2 计数：A=2,B=3,C=1 → d3 名单 [B, A]（计数优先，并列/次序按当日分）
        assert out["d3"][0] == "B"
        assert "A" in out["d3"]

    def test_window_truncates_history(self):
        scores = {f"d{i}": {"A": 10.0} for i in range(1, 6)}
        out = window_toplists(scores, window=2, broad_k=1, k=1)
        assert all(v == ["A"] for v in out.values())

    def test_empty_day_yields_empty_list(self):
        out = window_toplists({"d1": {}}, window=3, broad_k=2, k=2)
        assert out["d1"] == []

    def test_tie_broken_by_current_day_score(self):
        scores = {
            "d1": {"A": 50.0, "B": 40.0},
            "d2": {"A": 10.0, "B": 90.0},
        }
        out = window_toplists(scores, window=2, broad_k=2, k=2)
        # 近 2 日计数 A=2、B=2 全并列 → 按当日分 d2: B=90 > A=10 → [B, A]
        assert out["d2"] == ["B", "A"]


class TestHysteresisToplists:
    def test_member_survives_dip_within_exit_rank(self):
        scores = {
            "d1": {"A": 90.0, "B": 60.0, "C": 30.0, "D": 10.0},
            "d2": {"B": 90.0, "C": 60.0, "A": 30.0, "D": 10.0},  # A 跌到 rank3（k=3 边界内）
            "d3": {"B": 90.0, "C": 60.0, "D": 30.0, "A": 10.0},  # A 跌到 rank4（>k，<=exit_rank=4）
        }
        out = hysteresis_toplists(scores, k=3, exit_rank=4)
        # d3: A rank4 > k=3 但 <= exit_rank=4 → A 仍在滞回名单
        assert "A" in out["d3"]
        assert out["d3"][0] == "B"

    def test_member_exits_beyond_exit_rank(self):
        scores = {
            "d1": {"A": 90.0, "B": 60.0, "C": 30.0},
            "d2": {"B": 90.0, "C": 60.0, "D": 30.0, "E": 20.0, "A": 5.0},  # A rank5 > exit 4
        }
        out = hysteresis_toplists(scores, k=3, exit_rank=4)
        assert "A" not in out["d2"]

    def test_newcomer_enters_on_strong_day(self):
        scores = {
            "d1": {"A": 90.0, "B": 60.0, "C": 30.0},
            "d2": {"A": 90.0, "X": 80.0, "B": 60.0, "C": 30.0},  # X rank2 进列
        }
        out = hysteresis_toplists(scores, k=3, exit_rank=4)
        assert "X" in out["d2"]

    def test_all_missing_day_preserves_membership(self):
        scores = {
            "d1": {"A": 90.0, "B": 60.0, "C": 30.0},
            "d2": {"A": None, "B": None, "C": None},  # 全缺 → 名单保留不洗白
            "d3": {"B": 90.0, "C": 60.0, "D": 30.0, "A": 10.0},
        }
        out = hysteresis_toplists(scores, k=3, exit_rank=4)
        assert out["d2"] == ["A", "B", "C"]
        # d3: A rank4 <= exit 4 仍保留；D rank3 进列
        assert "A" in out["d3"] and "D" in out["d3"]

    def test_first_day_equals_pure_topk(self):
        scores = {"d1": {"A": 30.0, "B": 90.0, "C": 60.0, "D": 10.0}}
        out = hysteresis_toplists(scores, k=3, exit_rank=4)
        # 首日无在列成员，名单 == 纯 TopK（D rank4 > k=3 不进列）
        assert out["d1"] == ["B", "C", "A"]


class TestDeterministicOrdering:
    def test_all_equal_scores_yield_lexicographic_order(self):
        # 3 题材全等分 + dict 插入序刻意打乱（C,A,B），断言名单 == 字典序（跨进程确定）
        scores = {f"d{i}": {"C": 50.0, "A": 50.0, "B": 50.0} for i in (1, 2)}
        assert ema_toplists(scores, alpha=0.5, k=3)["d1"] == ["A", "B", "C"]
        assert window_toplists(scores, window=2, broad_k=3, k=3)["d2"] == ["A", "B", "C"]
        assert hysteresis_toplists(scores, k=3, exit_rank=4)["d1"] == ["A", "B", "C"]
