# -*- coding: utf-8 -*-
"""trend_reversal × jump 搭配分析纯函数测试。"""
from backend.analysis.ranktrend.signal_return_gap import _percentile
from backend.analysis.ranktrend.trend_reversal_jump import (
    FRESHNESS_HIGH,
    FRESHNESS_MID,
    MAGNITUDE_HIGH,
    _is_jump_buy,
    _jump_direction,
    _jump_event,
    _jump_freshness,
    _jump_magnitude,
    _is_trend_reversal,
    trend_reversal_jump_buckets,
    trend_reversal_jump_stats,
)


def _frame(sid: str, codes: list[str], price: float = 10.0) -> dict:
    stocks = [{"code": code, "rank": i + 1, "price": price} for i, code in enumerate(codes)]
    return {"snapshotId": sid, "stocks": stocks}


def _frames(n: int, codes: list[str]) -> list[dict]:
    return [_frame(f"s{i}", codes) for i in range(n)]


def _signal(
    sid: str,
    code: str,
    *,
    is_reversal: bool = True,
    jump_event: str = "jump",
    jump_direction: str = "buy",
    jump_freshness: float | None = 1.0,
    jump_magnitude: float | None = 25.0,
) -> dict:
    signal = {
        "snapshotId": sid,
        "code": code,
        "rankTrend": {
            "trendReversal": {"isReversal": is_reversal},
            # 完整 jump 事件对象（detect_rank_jumps 输出）
            "jump": {
                "event": jump_event,
                "direction": jump_direction,
                "events": (
                    [{"index": 0, "direction": "surge", "magnitude": jump_magnitude}]
                    if jump_magnitude is not None
                    else []
                ),
            },
            "resonance": {"jumpFreshness": jump_freshness},
        },
    }
    return signal


def test_jump_field_accessors() -> None:
    s = _signal("s1", "000001")
    assert _is_trend_reversal(s) is True
    assert _jump_event(s) == "jump"
    assert _jump_direction(s) == "buy"
    assert _jump_freshness(s) == 1.0
    assert _jump_magnitude(s) == 25.0
    assert _is_jump_buy(s) is True


def test_jump_accessors_fail_visible() -> None:
    s = _signal("s1", "000001", is_reversal=False, jump_event="none", jump_direction="hold",
                jump_freshness=None, jump_magnitude=None)
    assert _is_trend_reversal(s) is False
    assert _jump_event(s) == "none"
    assert _jump_direction(s) == "hold"
    assert _jump_freshness(s) is None
    assert _jump_magnitude(s) is None
    assert _is_jump_buy(s) is False


def test_jump_magnitude_none_without_events() -> None:
    s = _signal("s1", "000001", jump_event="none", jump_direction="hold", jump_magnitude=None)
    assert _jump_magnitude(s) is None


def test_bucket_definitions_complete() -> None:
    buckets = trend_reversal_jump_buckets()
    assert "all_trend_reversal" in buckets
    assert "jump_buy" in buckets
    assert "jump_buy_freshness_high_magnitude_high" in buckets
    # 组合桶是子集：跳买+新鲜+大幅 ⊆ 跳买
    s = _signal("s1", "000001")
    assert buckets["jump_buy_freshness_high_magnitude_high"](s)
    assert buckets["jump_buy"](s)


def test_freshness_and_magnitude_thresholds() -> None:
    s_high = _signal("s1", "000001", jump_freshness=0.8, jump_magnitude=30.0)
    assert FRESHNESS_HIGH == 0.5
    assert FRESHNESS_MID == 0.2
    assert MAGNITUDE_HIGH == 20.0
    buckets = trend_reversal_jump_buckets()
    assert buckets["jump_freshness_high"](s_high)
    assert buckets["jump_freshness_mid"](s_high) is False
    assert buckets["jump_magnitude_high"](s_high)
    assert buckets["jump_buy_freshness_high_magnitude_high"](s_high)


def test_stats_counts_trend_reversal_only() -> None:
    """只有 isReversal=True 的信号进入分桶统计。"""
    frames = _frames(5, ["000001", "000002"])
    signals = [
        _signal("s1", "000001", is_reversal=True),
        _signal("s2", "000002", is_reversal=False),
    ]
    stats = trend_reversal_jump_stats(signals, frames, horizons=(1,))
    assert stats["signalCount"] == 2
    assert stats["trendReversalCount"] == 1
    h1 = stats["horizons"]["1"]
    # all_trend_reversal 只含 1 个信号（000001）
    assert h1["all_trend_reversal"]["count"] == 1
    assert h1["jump_buy"]["count"] == 1
    # 非 trend_reversal 信号不应出现在任何桶
    for bucket in h1.values():
        assert bucket["count"] <= 1


def test_stats_price_return_horizon() -> None:
    """horizon 收益按未来帧价格计算：000001 涨、000002 跌，分桶均值应反映。"""
    # s0: rank1=000001 rank2=000002（pct 100/50），s1: 价格翻倍/减半
    frames = [
        {"snapshotId": "s0", "stocks": [
            {"code": "000001", "rank": 1, "price": 10.0},
            {"code": "000002", "rank": 2, "price": 10.0},
        ]},
        {"snapshotId": "s1", "stocks": [
            {"code": "000001", "rank": 1, "price": 11.0},
            {"code": "000002", "rank": 2, "price": 9.0},
        ]},
    ]
    signals = [
        _signal("s0", "000001", is_reversal=True, jump_freshness=0.8, jump_magnitude=25.0),
        _signal("s0", "000002", is_reversal=True, jump_freshness=0.1, jump_magnitude=5.0),
    ]
    stats = trend_reversal_jump_stats(signals, frames, horizons=(1,))
    h1 = stats["horizons"]["1"]
    all_stats = h1["all_trend_reversal"]
    assert all_stats["count"] == 2
    assert all_stats["mean"] == 0.0  # (+10% + -10%) / 2
    assert all_stats["median"] == 0.0
    # 新鲜+大幅桶只含 000001（+10%）
    fresh = h1["jump_buy_freshness_high_magnitude_high"]
    assert fresh["count"] == 1
    assert fresh["mean"] == 0.1
    assert fresh["winRate"] == 1.0


def test_stats_skipped_boundary() -> None:
    """horizon 越界信号计入 skippedFrameBoundary，不伪造收益。"""
    frames = _frames(2, ["000001"])
    signals = [
        _signal("s0", "000001", is_reversal=True),
        _signal("s1", "000001", is_reversal=True),  # 最后一帧 horizon=1 越界
    ]
    stats = trend_reversal_jump_stats(signals, frames, horizons=(1,))
    h1 = stats["horizons"]["1"]["all_trend_reversal"]
    assert h1["count"] == 1
    assert h1["skipped"]["frameBoundary"] == 1
    assert h1["winRate"] is not None


def test_percentile_helper_consistency() -> None:
    assert _percentile(1, 2) == 100.0
    assert _percentile(2, 2) == 50.0
