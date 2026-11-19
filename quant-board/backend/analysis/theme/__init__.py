"""题材分析包：题材热度/动量/轮动（theme_momentum v2 归属）。ThemeTrend 链已于 2026-11-19 淘汰删除。"""

from backend.analysis.theme.heat import compute_theme_heat
from backend.analysis.theme.momentum import compute_theme_momentum_series, stock_theme_exposure
from backend.analysis.theme.rotation import (
    HistorySlot,
    MarketRotationSummary,
    RotationHistory,
    ThemeRotationConfig,
    ThemeRotationEngine,
    ThemeRotationResult,
    ThemeRotationStatus,
)
from backend.analysis.theme.support_index import build_theme_support_index

__all__ = [
    "compute_theme_heat",
    "compute_theme_momentum_series",
    "stock_theme_exposure",
    "HistorySlot",
    "MarketRotationSummary",
    "RotationHistory",
    "ThemeRotationConfig",
    "ThemeRotationEngine",
    "ThemeRotationResult",
    "ThemeRotationStatus",
    "build_theme_support_index",
]
