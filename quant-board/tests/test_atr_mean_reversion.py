"""ATR 真实波动均值回归信号测试（2026-08-17，设计 v2）。

覆盖：TR/ATR 简单均值 golden case（含跳空）、样本不足/ATR≈0 → insufficient（fail-visible）、
超买/超卖/深偏离档位、bar 字段回退、missing/gap 计数透传、RankTrendConfig 默认值。
"""

from __future__ import annotations

import math

import pytest

from backend.analysis.ranktrend.atr_mean_reversion import (
    analyze_atr_mean_reversion,
    atr_of,
    bar_of,
    true_ranges,
)
from backend.analysis.ranktrend.engine import RankTrendConfig


def test_true_ranges_basic() -> None:
    bars = [(10.0, 8.0, 9.0), (11.0, 9.0, 10.5), (12.0, 10.0, 11.0), (13.0, 11.0, 12.5)]
    # TR(1) = max(11-9, |11-9|, |9-9|) = 2；TR(2) = max(2, |12-10.5|, |10-10.5|) = 2；TR(3) = 2
    assert true_ranges(bars) == [2.0, 2.0, 2.0]


def test_true_ranges_gap_dominated() -> None:
    # 跳空：|high - prevClose| 主导
    bars = [(10.0, 9.0, 9.5), (14.0, 11.0, 13.0)]
    tr = true_ranges(bars)
    assert len(tr) == 1
    assert tr[0] == pytest.approx(4.5)  # max(14-11=3, |14-9.5|=4.5, |11-9.5|=1.5)


def test_atr_of_simple_mean() -> None:
    bars = [(10.0, 8.0, 9.0), (11.0, 9.0, 10.5), (12.0, 10.0, 11.0), (13.0, 11.0, 12.5)]
    assert atr_of(bars, period=2) == pytest.approx(2.0)  # mean([2, 2])
    assert atr_of(bars, period=3) == pytest.approx(2.0)  # mean([2, 2, 2])


def test_atr_of_insufficient_returns_none() -> None:
    assert atr_of(None) is None
    assert atr_of([]) is None
    # 样本 < period + 1 → None（与 execution.py _atr_of 一致）
    bars = [(10.0, 8.0, 9.0), (11.0, 9.0, 10.5)]
    assert atr_of(bars, period=2) is None  # len=2 < 2+1


def test_analyze_insufficient_short_sample() -> None:
    # 样本 < max(atrPeriod+1=15, atrRefPeriod=20)=20 → insufficient
    bars = [(10.0, 8.0, 9.0)] * 19
    result = analyze_atr_mean_reversion(bars, RankTrendConfig())
    assert result["status"] == "insufficient"
    assert result["direction"] == "hold"
    assert result["signalTier"] == "unknown"


def test_analyze_atr_zero_insufficient_no_nan() -> None:
    # 单帧快照 high≈low≈close → TR≈0、ATR≈0 → insufficient（不产生 NaN/无穷）
    bars = [(10.0, 10.0, 10.0)] * 21
    result = analyze_atr_mean_reversion(bars, RankTrendConfig())
    assert result["status"] == "insufficient"
    assert result["direction"] == "hold"
    deviation = result.get("deviation")
    assert deviation is None or (math.isfinite(deviation) and abs(deviation) <= 10)


def test_analyze_oversold_buy() -> None:
    # close 明显低于 20 帧均值且 |deviation| >= k → buy + A 档
    c = RankTrendConfig()
    bars = [(10.5, 9.5, 10.0)] * 19 + [(7.5, 7.1, 7.3), (7.2, 6.8, 7.0)]
    result = analyze_atr_mean_reversion(bars, c)
    assert result["status"] == "ok"
    assert result["direction"] == "buy"
    assert result["signalTier"] == "A"
    assert result["deviation"] is not None and result["deviation"] <= -c.atrChannelK


def test_analyze_overbought_sell() -> None:
    # 对称：超买 → sell
    c = RankTrendConfig()
    bars = [(10.5, 9.5, 10.0)] * 19 + [(12.5, 12.1, 12.3), (12.8, 12.4, 12.6)]
    result = analyze_atr_mean_reversion(bars, c)
    assert result["status"] == "ok"
    assert result["direction"] == "sell"
    assert result["signalTier"] == "A"
    assert result["deviation"] is not None and result["deviation"] >= c.atrChannelK


def test_analyze_deep_deviation_s_tier() -> None:
    # |deviation| >= atrDeepDeviation(3.0) → S 档
    c = RankTrendConfig()
    bars = [(10.5, 9.5, 10.0)] * 19 + [(5.5, 5.0, 5.2), (5.4, 4.9, 5.1)]
    result = analyze_atr_mean_reversion(bars, c)
    assert result["status"] == "ok"
    assert result["direction"] == "buy"
    assert result["signalTier"] == "S"


def test_analyze_channel_hold_tier() -> None:
    # 通道内（|deviation| < 0.5k）→ hold + B 档
    c = RankTrendConfig()
    bars = [(10.5, 9.5, 10.0)] * 21
    result = analyze_atr_mean_reversion(bars, c)
    assert result["status"] == "ok"
    assert result["direction"] == "hold"
    assert result["signalTier"] == "B"


def test_missing_and_gap_counters_passthrough() -> None:
    bars = [(10.5, 9.5, 10.0)] * 21
    result = analyze_atr_mean_reversion(bars, RankTrendConfig(), missing_bars=3, gap_resets=2)
    assert result["missingBars"] == 3
    assert result["gapResets"] == 2


def test_bar_of_field_fallback() -> None:
    # 字段回退：high→highPrice→dayHigh；low→lowPrice→dayLow；close→closePrice→lastPrice→lastTradePrice→price
    assert bar_of({"high": 11.0, "low": 9.0, "close": 10.0}) == (11.0, 9.0, 10.0)
    assert bar_of({"highPrice": 12.0, "lowPrice": 8.0, "lastTradePrice": 10.5}) == (12.0, 8.0, 10.5)
    assert bar_of({"dayHigh": 13.0, "dayLow": 7.0, "price": 9.5}) == (13.0, 7.0, 9.5)
    assert bar_of({"high": 11.0}) is None  # low/close 缺失
    assert bar_of({}) is None
    assert bar_of(None) is None


def test_atr_config_defaults() -> None:
    c = RankTrendConfig()
    assert c.atrPeriod == 14
    assert c.atrRefPeriod == 20
    assert c.atrChannelK == 2.0
    assert c.atrDeepDeviation == 3.0
    assert c.atrMaxHistoryBars == 60
    assert c.atrGapResetBars == 2
    assert c.atrAggregateByDay is False
    assert c.atrBucketBySlot is False


# ── replay 挂载（engine.py assemble 分支）──


def _make_atr_frames(
    n: int = 22,
    start_date: str = "2026-08-02",
    missing_last: bool = False,
    change_date_at: int | None = None,
) -> list[dict]:
    frames: list[dict] = []
    stocks_base = [
        {"code": "002279", "rank": 1, "avgRankNum": 1},
        {"code": "603580", "rank": 2, "avgRankNum": 2},
    ]
    for i in range(n):
        rows = []
        for s in stocks_base:
            row = dict(s)
            row.update({"change": 1.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.1})
            if not (missing_last and i == n - 1):
                row["high"] = 10.5 + i * 0.05
                row["low"] = 9.5 + i * 0.05
                row["close"] = 10.0 + i * 0.05
            rows.append(row)
        date = change_date_at if change_date_at is not None else start_date
        trading_date = f"2026-08-0{(i % 5) + 1}" if change_date_at is not None else start_date
        frames.append(
            {
                "snapshotId": f"half_hour:{trading_date}:{(9 + (i * 30) // 60) % 24:02d}:{(i * 30) % 60:02d}",
                "tradingDate": trading_date,
                "slotTime": f"{(9 + (i * 30) // 60) % 24:02d}:{(i * 30) % 60:02d}",
                "type": "half_hour",
                "timestamp": i,
                "stocks": rows,
                "marketContext": {"sentiment": {"phaseName": "启动"}, "marketStats": {}},
            }
        )
    return frames


def _last_signal_for(signals: list[dict], code: str = "002279") -> dict:
    return [s for s in signals if s["code"] == code][-1]


def test_replay_atr_mean_reversion_present() -> None:
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    frames = _make_atr_frames(n=22, start_date="2026-08-02")
    engine = RankTrendPythonEngine()
    signals = engine.replay(frames, warmup_count=1)
    assert len(signals) == 44  # 22 帧 × 2 股
    for code in ("002279", "603580"):
        atr = _last_signal_for(signals, code)["rankTrend"]["observation"].get("atrMeanReversion")
        assert atr is not None
        assert atr["status"] in ("ok", "insufficient")
        assert {"status", "direction", "score", "deviation", "atr", "ref", "missingBars", "gapResets", "reasons", "signalTier"} <= set(atr)
        assert atr["missingBars"] == 0
        assert atr["signalTier"] in ("S", "A", "B", "C", "D", "E", "unknown")


def test_replay_atr_gap_reset_cross_day() -> None:
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    # 每天 1 帧（tradingDate 每天变化）→ 跨日恒重置，最后一帧 gapResets ≥ 1
    frames = _make_atr_frames(n=22, change_date_at=1)
    engine = RankTrendPythonEngine()
    signals = engine.replay(frames, warmup_count=1)
    assert signals
    atr = _last_signal_for(signals)["rankTrend"]["observation"]["atrMeanReversion"]
    assert atr["gapResets"] >= 1


def test_replay_atr_missing_bar_counts() -> None:
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    # 最后一帧缺 high/low/close → 最后一帧信号 missingBars 计数（该帧不累积）
    frames = _make_atr_frames(n=22, missing_last=True)
    engine = RankTrendPythonEngine()
    signals = engine.replay(frames, warmup_count=1)
    assert signals
    atr = _last_signal_for(signals)["rankTrend"]["observation"]["atrMeanReversion"]
    assert atr["missingBars"] >= 1


def test_replay_atr_gap_reset_within_day() -> None:
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    # 同日内该股缺席中间帧（帧 4-7 移除 002279）→ 再现时帧索引间隔 ≥ atrGapResetBars → gap 分支重置
    frames = _make_atr_frames(n=12, start_date="2026-08-02")
    for i in range(4, 8):
        frames[i]["stocks"] = [s for s in frames[i]["stocks"] if s["code"] != "002279"]
    engine = RankTrendPythonEngine()
    signals = engine.replay(frames, warmup_count=1)
    assert signals
    atr = _last_signal_for(signals)["rankTrend"]["observation"]["atrMeanReversion"]
    assert atr["gapResets"] >= 1


def test_replay_atr_technical_hang_also_present() -> None:
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine

    # 设计文档 §4.2：technical.atrMeanReversion 与 observation.atrMeanReversion 同源挂载
    frames = _make_atr_frames(n=22, start_date="2026-08-02")
    engine = RankTrendPythonEngine()
    signals = engine.replay(frames, warmup_count=1)
    obs = _last_signal_for(signals)["rankTrend"]["observation"]["atrMeanReversion"]
    tech = _last_signal_for(signals)["rankTrend"]["technical"]["atrMeanReversion"]
    assert obs is not None and tech is not None
    assert tech == obs


def test_atr_of_matches_backtest_engine() -> None:
    from backend.core.backtest.execution import TradeSimulator

    # 审计修复（双源一致性）：atr_mean_reversion.atr_of 与 execution.py::_atr_of 对同一 bars 输出一致
    bars = [(10.0, 8.0, 9.0), (11.0, 9.0, 10.5), (12.0, 10.0, 11.0), (13.0, 11.0, 12.5)]
    for period in (2, 3):
        assert atr_of(bars, period=period) == TradeSimulator._atr_of(bars, period=period)
    # 样本不足同样返回 None
    assert atr_of(bars, period=10) is None
    assert TradeSimulator._atr_of(bars, period=10) is None
