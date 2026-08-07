"""Backend services package.

- backtest_service: BacktestService（回测/研究报告服务）
- optimization_service: OptimizationService（参数优化服务）
- audit_service: RankTrendLiveGateAuditService（live 门禁审计）
- golden_service: GoldenService（golden case 服务）
- efficacy: 信号功效/对齐计算（compute_signal_efficacy 等）
- checkpoint: 长测 checkpoint 分析（check_layer1_meltdown 等）
- _shared: 共享常量与辅助（camel_get/价格质量校验等）
- theme: 题材领域服务（资金缓存/热度/映射刷新/调度）
- market: 市场资金领域服务（资金调度/资金流）
"""

from backend.services.shared import (
    BACKTEST_COMPARE_METRICS,
    CROSS_MARKET_ZERO_PRICE_PREFIXES,
    DEFAULT_BACKTEST_STRATEGY_CONFIG,
    FATAL_QUALITY_STATS,
    MONEY_FLOW_QUALITY_FIELDS,
    V5_LIFECYCLE_FUSION_STRATEGY,
    _ensure_runtime_filtered_frames_usable,
    _prepare_frames_for_backtest,
    _stock_rows_for_quality,
    camel_get,
    trade_defaults_for_strategy,
)
from backend.services.efficacy import (
    compute_alignment,
    compute_execution_entry_layer1_efficacy,
    compute_execution_quality,
    compute_signal_efficacy,
)
from backend.services.checkpoint import (
    check_layer1_meltdown,
    check_layer3_trend,
    compute_checkpoint_layer2,
    read_checkpoint_history,
    select_longtest_baseline_slots,
    summarize_longtest_slot_label,
)
from backend.data.repositories.repository_factory import storage_source_label
from backend.services.backtest_service import (
    BacktestService,
    _cross_market_zero_price_stock_rows,
    _drop_all_zero_price_frames,
    _positive_price_stock_rows,
    _price_quality_diagnostics,
)
from backend.services.optimization_service import OptimizationService
from backend.services.audit_service import RankTrendLiveGateAuditService
from backend.services.golden_service import GoldenService
from backend.services.theme import (
    ThemeFundCache,
    ThemeHeatService,
    ThemeHeatUnavailable,
    ThemeMappingRefreshScheduler,
    get_theme_fund_cache,
    get_theme_heat_service,
    refresh_theme_stock_mappings,
)
from backend.services.market import (
    MarketFundScheduler,
    MarketFundStream,
    get_market_fund_stream,
)

__all__ = [
    "storage_source_label",

    "DEFAULT_BACKTEST_STRATEGY_CONFIG",
    "V5_LIFECYCLE_FUSION_STRATEGY",
    "BACKTEST_COMPARE_METRICS",
    "FATAL_QUALITY_STATS",
    "MONEY_FLOW_QUALITY_FIELDS",
    "CROSS_MARKET_ZERO_PRICE_PREFIXES",
    "camel_get",
    "trade_defaults_for_strategy",
    "compute_signal_efficacy",
    "compute_execution_entry_layer1_efficacy",
    "compute_execution_quality",
    "compute_alignment",
    "read_checkpoint_history",
    "select_longtest_baseline_slots",
    "compute_checkpoint_layer2",
    "summarize_longtest_slot_label",
    "check_layer1_meltdown",
    "check_layer3_trend",
    "BacktestService",
    "OptimizationService",
    "RankTrendLiveGateAuditService",
    "GoldenService",
    "_cross_market_zero_price_stock_rows",
    "_drop_all_zero_price_frames",
    "_ensure_runtime_filtered_frames_usable",
    "_positive_price_stock_rows",
    "_prepare_frames_for_backtest",
    "_price_quality_diagnostics",
    "_stock_rows_for_quality",
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
]
