"""Backend services package.

- services_core: 服务编排（BacktestService/OptimizationService/GoldenService 等，历史单文件）
- theme: 题材领域服务（资金缓存/热度/映射刷新/调度）
- market: 市场资金领域服务（资金调度/资金流）
"""

from backend.services_core import *  # noqa: F401,F403
from backend.services_core import (  # noqa: F401  (测试直接引用的私有符号)
    _cross_market_zero_price_stock_rows,
    _drop_all_zero_price_frames,
    _ensure_runtime_filtered_frames_usable,
    _positive_price_stock_rows,
    _prepare_frames_for_backtest,
    _price_quality_diagnostics,
    _stock_rows_for_quality,
)
from backend.services.theme import (  # noqa: F401
    ThemeFundCache,
    ThemeHeatService,
    ThemeHeatUnavailable,
    ThemeMappingRefreshScheduler,
    get_theme_fund_cache,
    get_theme_heat_service,
    refresh_theme_stock_mappings,
)
from backend.services.market import (  # noqa: F401
    MarketFundScheduler,
    MarketFundStream,
    get_market_fund_stream,
)

__all__ = [
    'DEFAULT_BACKTEST_STRATEGY_CONFIG',
    'V5_LIFECYCLE_FUSION_STRATEGY',
    'trade_defaults_for_strategy',
    'BACKTEST_COMPARE_METRICS',
    'FATAL_QUALITY_STATS',
    'camel_get',
    'MONEY_FLOW_QUALITY_FIELDS',
    'CROSS_MARKET_ZERO_PRICE_PREFIXES',
    'compute_signal_efficacy',
    'compute_execution_entry_layer1_efficacy',
    'compute_execution_quality',
    'compute_alignment',
    'read_checkpoint_history',
    'select_longtest_baseline_slots',
    'compute_checkpoint_layer2',
    'summarize_longtest_slot_label',
    'check_layer1_meltdown',
    'check_layer3_trend',
    'BacktestService',
    'OptimizationService',
    'RankTrendLiveGateAuditService',
    'GoldenService',
    "ThemeFundCache",
    "ThemeHeatService",
    "ThemeHeatUnavailable",
    "ThemeMappingRefreshScheduler",
    "get_theme_fund_cache",
    "get_theme_heat_service",
    "refresh_theme_stock_mappings",
    "MarketFundScheduler",
    "MarketFundStream",
    "get_market_fund_stream",
    "_cross_market_zero_price_stock_rows",
    "_drop_all_zero_price_frames",
    "_ensure_runtime_filtered_frames_usable",
    "_positive_price_stock_rows",
    "_prepare_frames_for_backtest",
    "_price_quality_diagnostics",
    "_stock_rows_for_quality",
]
