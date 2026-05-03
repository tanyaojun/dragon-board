# 回测包兼容导出层
# 所有历史 from backend.core.backtest import ... 继续可用
from __future__ import annotations

from backend.core.backtest.config import DEFAULT_TRADE_CONFIG
from backend.core.backtest.engine import BacktestEngine, Optimizer
from backend.core.backtest.evaluator import (
    OutcomeEvaluator,
    build_frame_lookup,
    find_frame_index,
    find_stock,
    momentum_bucket,
    percentile,
)
from backend.core.backtest.execution import TradeSimulator
from backend.core.backtest.metrics import (
    _first_finite,
    _first_number,
    _round_or_none,
    _sample_std,
    average,
    max_drawdown,
    share,
    short_cycle_sharpe,
)
from backend.core.backtest.strategy import (
    CONTROL_STRATEGIES,
    DEFAULT_STRATEGY_NAME,
    STRATEGY_DEFINITIONS,
    SUPPORTED_STRATEGY_NAMES,
    STRATEGY_REGISTRY,
    BaseStrategy,
    FrameStrategyResult,
    StrategyDecision,
    StrategyInput,
    get_strategy,
    normalize_strategy_name,
)

__all__ = [
    "DEFAULT_TRADE_CONFIG",
    "DEFAULT_STRATEGY_NAME",
    "STRATEGY_DEFINITIONS",
    "SUPPORTED_STRATEGY_NAMES",
    "CONTROL_STRATEGIES",
    "STRATEGY_REGISTRY",
    "normalize_strategy_name",
    "get_strategy",
    "BaseStrategy",
    "StrategyInput",
    "StrategyDecision",
    "FrameStrategyResult",
    "share",
    "average",
    "max_drawdown",
    "_sample_std",
    "short_cycle_sharpe",
    "_round_or_none",
    "_first_number",
    "_first_finite",
    "find_frame_index",
    "find_stock",
    "build_frame_lookup",
    "percentile",
    "momentum_bucket",
    "OutcomeEvaluator",
    "TradeSimulator",
    "BacktestEngine",
    "Optimizer",
]
