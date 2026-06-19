"""测试 jump_backfill 模块的核心算法，确保与前端 detectRankJumps 行为一致。"""
import pytest
from backend.data.jump_backfill import _detect_jump, _percentile_from_rank


class TestPercentileFromRank:
    def test_rank_1_of_100_is_100(self):
        assert _percentile_from_rank(1, 100) == 100.0

    def test_rank_50_of_100_is_about_50(self):
        pct = _percentile_from_rank(50, 100)
        assert 50.0 < pct < 51.0

    def test_rank_100_of_100_is_0(self):
        assert _percentile_from_rank(100, 100) == 0.0

    def test_single_stock_returns_50(self):
        assert _percentile_from_rank(1, 1) == 50.0


class TestDetectJump:
    def test_stable_no_jump(self):
        result = _detect_jump([50, 52, 48, 51, 50])
        assert result["direction"] == "hold"
        assert result["confidence"] == 50.0
        assert result["eventCount"] == 0

    def test_clear_surge_buy(self):
        result = _detect_jump([30, 35, 50, 65, 80])
        assert result["direction"] == "buy"
        assert result["confidence"] > 70.0

    def test_clear_collapse_sell(self):
        result = _detect_jump([80, 75, 60, 45, 30])
        assert result["direction"] == "sell"
        assert result["confidence"] > 70.0

    def test_insufficient_data(self):
        result = _detect_jump([50, 80])
        assert result["direction"] == "hold"
        assert result["confidence"] == 50.0

    def test_empty_input(self):
        result = _detect_jump([])
        assert result["direction"] == "hold"
        assert result["eventCount"] == 0

    def test_sustained_surge_higher_confidence(self):
        result = _detect_jump([30, 50, 35, 60, 45, 75])
        assert result["direction"] == "buy"
        assert result["confidence"] > 75.0

    def test_single_event_no_sustain_lower_confidence(self):
        result = _detect_jump([30, 48, 50, 51, 50])
        assert result["confidence"] < 90.0
