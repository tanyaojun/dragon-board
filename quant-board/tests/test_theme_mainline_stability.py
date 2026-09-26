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
        # d2: A smooth=15, B 首见=15 → 并列，按 sorted 稳定序（A 先入 smooth）
        assert len(out["d2"]) == 2

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
