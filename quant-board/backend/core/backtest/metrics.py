from __future__ import annotations

import math
from typing import Any


def share(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def max_drawdown(equity: list[dict[str, Any]]) -> float:
    peak = equity[0]["equity"] if equity else 0
    drawdown = 0.0
    for point in equity:
        peak = max(peak, point["equity"])
        if peak > 0:
            drawdown = min(drawdown, (point["equity"] - peak) / peak)
    return round(drawdown, 4)


def _sample_std(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / (len(values) - 1)
    return math.sqrt(variance)


def short_cycle_sharpe(trades: list[dict[str, Any]], target_holding_days: float = 5.0, trading_days_per_year: int = 252) -> dict[str, Any]:
    returns = [float(trade.get("netReturn") or 0) for trade in trades if trade.get("netReturn") is not None]
    std = _sample_std(returns)
    if len(returns) < 2:
        return {"sharpe": None, "tradeSharpe": None, "avgTradeReturn": None, "tradeReturnStd": None}
    mean = sum(returns) / len(returns)
    if not std or std <= 1e-12:
        return {"sharpe": None, "tradeSharpe": None, "avgTradeReturn": round(mean, 4), "tradeReturnStd": None}
    trade_sharpe = mean / std
    cycle_scale = math.sqrt(trading_days_per_year / max(1.0, target_holding_days))
    return {
        "sharpe": round(trade_sharpe * cycle_scale, 4),
        "tradeSharpe": round(trade_sharpe, 4),
        "avgTradeReturn": round(mean, 4),
        "tradeReturnStd": round(std, 4),
    }


def _round_or_none(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _first_number(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = source.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _first_finite(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = source.get(key)
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None
