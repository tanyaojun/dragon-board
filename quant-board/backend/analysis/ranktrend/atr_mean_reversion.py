# -*- coding: utf-8 -*-
"""ATR 真实波动均值回归信号（backend/analysis/ranktrend，2026-08-17）。

设计：docs/ranktrend-tier-backtest/ranktrend-atr-signal-design.md v2（已过对抗性审计）。

核心思想：价格偏离其波动通道（ref ± k×ATR）过远时预期向均值回归——超买 sell / 超卖 buy。
与现有"追强"信号（共振/趋势/量价）互补；**独立观察维度，不进 synergy 投票**。

关键口径（审计修订）：
- ATR = TR 的**简单均值**（与 backend/core/backtest/execution.py::_atr_of 一致，行为不漂移；
  不用 Wilder 平滑）；
- 样本门槛取交集：不足 max(atrPeriod+1, atrRefPeriod) 帧 → insufficient（unknown，不归零）；
- ATR≈0（单帧快照 high≈low≈close）→ insufficient，不产生 NaN/无穷；
- 断档/缺帧由调用方（replay 累积层）计数并重置序列（gapResets/missingBars 透传）。
"""

from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend.engine import RankTrendConfig


def bar_of(stock: dict[str, Any] | None) -> tuple[float, float, float] | None:
    """从股票 record 提取 (high, low, close)，字段回退顺序同回测引擎 execution.py。

    high：high → highPrice → dayHigh；low：low → lowPrice → dayLow；
    close：close → closePrice → lastPrice → lastTradePrice → price。
    任一维全缺或非正 → 返回 None（该帧不累积，fail-visible）。
    """
    if not stock:
        return None

    def first_number(*keys: str) -> float | None:
        for key in keys:
            value = stock.get(key)
            if value is None:
                continue
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                return number
        return None

    high = first_number("high", "highPrice", "dayHigh")
    low = first_number("low", "lowPrice", "dayLow")
    close = first_number("close", "closePrice", "lastPrice", "lastTradePrice", "price")
    if high is None or low is None or close is None:
        return None
    return (high, low, close)


def true_ranges(bars: list[tuple[float, float, float]]) -> list[float]:
    """TR 序列：TR(i) = max(high_i − low_i, |high_i − close_{i−1}|, |low_i − close_{i−1}|)。"""
    trs: list[float] = []
    for i in range(1, len(bars)):
        high, low, prev_close = bars[i][0], bars[i][1], bars[i - 1][2]
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return trs


def atr_of(bars: list[tuple[float, float, float]] | None, period: int = 14) -> float | None:
    """ATR(period) 简单均值（与 execution.py::_atr_of 一致）；样本不足/缺失返回 None。"""
    if not bars or len(bars) < period + 1:
        return None
    trs = true_ranges(bars)
    if len(trs) < period:
        return None
    return sum(trs[-period:]) / period


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def analyze_atr_mean_reversion(
    bars: list[tuple[float, float, float]],
    config: RankTrendConfig,
    missing_bars: int = 0,
    gap_resets: int = 0,
) -> dict[str, Any]:
    """ATR 均值回归信号（输出契约见设计文档 §2.4/§2.5）。

    fail-visible：样本不足 / ATR≈0 / ref 缺失 → status=insufficient、direction=hold、
    signalTier=unknown（不归零不伪装）。
    """
    min_bars = max(config.atrPeriod + 1, config.atrRefPeriod)
    if len(bars) < min_bars:
        return {
            "status": "insufficient",
            "direction": "hold",
            "score": 0,
            "deviation": None,
            "atr": None,
            "ref": None,
            "missingBars": missing_bars,
            "gapResets": gap_resets,
            "reasons": [f"ATR 样本不足（{len(bars)}/{min_bars} 帧）"],
            "signalTier": "unknown",
        }

    atr = atr_of(bars, config.atrPeriod)
    closes = [bar[2] for bar in bars]
    ref = _mean(closes[-config.atrRefPeriod :])
    current_close = closes[-1]
    if atr is None or atr <= 0 or ref is None or ref <= 0:
        return {
            "status": "insufficient",
            "direction": "hold",
            "score": 0,
            "deviation": None,
            "atr": atr,
            "ref": ref,
            "missingBars": missing_bars,
            "gapResets": gap_resets,
            "reasons": ["ATR/参考均值不可用（波动为零或缺失）"],
            "signalTier": "unknown",
        }
    # 数值安全：ATR 相对价格过小（单帧快照 high≈low≈close）→ deviation 分母不稳定，视为不足
    if atr < abs(ref) * 1e-9:
        return {
            "status": "insufficient",
            "direction": "hold",
            "score": 0,
            "deviation": None,
            "atr": atr,
            "ref": ref,
            "missingBars": missing_bars,
            "gapResets": gap_resets,
            "reasons": ["ATR 过小（瞬时快照波幅≈0），偏离度不稳定"],
            "signalTier": "unknown",
        }

    raw_deviation = (current_close - ref) / atr
    deviation = max(-10.0, min(10.0, raw_deviation))  # 防御异常值

    if deviation >= config.atrChannelK:
        direction = "sell"
        label = "超买"
    elif deviation <= -config.atrChannelK:
        direction = "buy"
        label = "超卖"
    else:
        direction = "hold"
        label = "通道内"

    score = round(50 + min(50.0, abs(deviation) * 15.0), 2)

    abs_dev = abs(deviation)
    if direction != "hold" and abs_dev >= config.atrDeepDeviation:
        tier = "S"
    elif direction != "hold":
        tier = "A"
    elif abs_dev >= 0.5 * config.atrChannelK:
        tier = "C"
    else:
        tier = "B"

    if direction == "hold":
        reason = f"均值附近（deviation={deviation:.2f}），通道内"
    else:
        reason = f"{label}：deviation={deviation:.2f}，回归预期（direction={direction}）"
    return {
        "status": "ok",
        "direction": direction,
        "score": score,
        "deviation": round(deviation, 4),
        "atr": round(atr, 6),
        "ref": round(ref, 4),
        "missingBars": missing_bars,
        "gapResets": gap_resets,
        "reasons": [reason],
        "signalTier": tier,
    }
