"""RankTrend 分析包：golden 引擎与观察/回测辅助。

兼容入口：旧代码 `from backend.analysis.ranktrend import ...` 在本包经 `import *`
re-export `engine` 全部公开符号（含 analyze_technical/analyze_risk 等，供测试 monkeypatch）。
"""

from backend.analysis.ranktrend.engine import *  # noqa: F401,F403

# 目录化迁移兼容：历史脚本仍可能直接导入
# ``backend.analysis.ranktrend.<module>``。将旧模块名映射到新的领域子包，
# 避免在根目录保留一批只有转发逻辑的重复文件。
import importlib
import sys

_LEGACY_MODULE_ALIASES = {
    "technical": ".trend.technical",
    "lifecycle": ".trend.lifecycle",
    "risk": ".trend.risk",
    "cross_section": ".trend.cross_section",
    "price_momentum": ".trend.price_momentum",
    "price_rank_divergence": ".trend.price_rank_divergence",
    "trend_reversal": ".trend.trend_reversal",
    "display_status": ".trend.display_status",
    "atr_mean_reversion": ".atr.atr_mean_reversion",
    "cross_section_vol_overheat": ".atr.cross_section_vol_overheat",
    "volume_price": ".ranking.volume_price",
    "comprehensive_rank": ".ranking.comprehensive_rank",
    "simple_backtest": ".research.simple_backtest",
    "jump_research": ".research.jump_research",
    "signal_return_gap": ".research.signal_return_gap",
    "strategy_signal_fit": ".research.strategy_signal_fit",
    "tier_monotonicity": ".research.tier_monotonicity",
    "trend_reversal_jump": ".research.trend_reversal_jump",
    "live_gate_shadow_audit": ".research.live_gate_shadow_audit",
}

for _legacy_name, _target in _LEGACY_MODULE_ALIASES.items():
    _module_name = f"{__name__}.{_legacy_name}"
    if _module_name not in sys.modules:
        sys.modules[_module_name] = importlib.import_module(_target, __name__)

del importlib, sys, _legacy_name, _target, _module_name
