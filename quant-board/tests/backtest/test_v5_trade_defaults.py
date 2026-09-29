# -*- coding: utf-8 -*-
"""v3 锚（ranktrend_early_big_move_v3_lifecycle_fusion）trade 默认参数合同。

2026-09-23 用户裁决落默认（阶段 A 终局，判定卡 exit-scan-batch3-verdict.md）：
- takeProfit 9.99(≈关闭) → 0.06（兑现窗口）；
- breakevenTrailing False → True + breakevenThreshold 0.02（保本保护）。
覆盖：默认值断言 + 合并解析断言 + 非 v3 策略不受影响断言。
参数生效行为由 tests/test_trade_simulator_entry_refinements.py 覆盖。
"""
from backend.core.backtest.config import V5_LIFECYCLE_FUSION_TRADE_DEFAULTS
from backend.services.shared import (
    V5_LIFECYCLE_FUSION_STRATEGY,
    trade_defaults_for_strategy,
)


def test_v5_defaults_take_profit_006() -> None:
    assert V5_LIFECYCLE_FUSION_TRADE_DEFAULTS["takeProfit"] == 0.06


def test_v5_defaults_breakeven_enabled_at_002() -> None:
    assert V5_LIFECYCLE_FUSION_TRADE_DEFAULTS["breakevenTrailing"] is True
    assert V5_LIFECYCLE_FUSION_TRADE_DEFAULTS["breakevenThreshold"] == 0.02


def test_resolved_v3_defaults_apply_both_protectives() -> None:
    defaults = trade_defaults_for_strategy(V5_LIFECYCLE_FUSION_STRATEGY)
    assert defaults["takeProfit"] == 0.06
    assert defaults["breakevenTrailing"] is True
    assert defaults["breakevenThreshold"] == 0.02
    # 未涉及的 v3 项保持原默认
    assert defaults["stopLoss"] == -0.05
    assert defaults["maxHoldingBars"] == 30


def test_non_v3_strategy_keeps_generic_defaults() -> None:
    defaults = trade_defaults_for_strategy("rank_trend_candidate")
    assert defaults["takeProfit"] == 0.12
    assert defaults["breakevenTrailing"] is False


def test_run_ranktrend_wiring_calls_defaults_merge() -> None:
    """锁定 run_ranktrend 对合并函数的接线（回归背景：显式构造曾丢弃 defaults 独有键，
    breakeven 默认静默不生效）。完整集成断言（捕获 BacktestEngine.run 的 trade_config）
    待引擎 fixture 就绪后补；此处用源码级断言防止接线被删或退回裸 update。"""
    import inspect

    from backend.services.backtest_service import BacktestService

    source = inspect.getsource(BacktestService.run_ranktrend)
    assert "_apply_trade_config_defaults_and_patch(trade_config, trade_defaults" in source
    assert "trade_config.update(trade_config_patch)" not in source


def test_run_ranktrend_merges_defaults_keys_not_explicitly_built() -> None:
    """run_ranktrend 的 trade_config 显式构造不含 v5 新键（breakeven* 等），
    defaults 中其余键必须 setdefault 并入（显式键不被覆盖、patch 最后覆盖一切）。
    回归背景：2026-09-23 落默认复现发现 breakevenTrailing 默认不生效——
    显式构造丢弃了 defaults 独有键。"""
    from backend.services.backtest_service import _apply_trade_config_defaults_and_patch

    defaults = trade_defaults_for_strategy(V5_LIFECYCLE_FUSION_STRATEGY)
    # 模拟 run_ranktrend 显式构造后的 trade_config（节选；显式键已用 defaults 作默认值）
    explicit = {
        "takeProfit": defaults["takeProfit"],
        "stopLoss": defaults["stopLoss"],
        "maxHoldingBars": defaults["maxHoldingBars"],
    }
    merged = _apply_trade_config_defaults_and_patch(dict(explicit), defaults, {})
    assert merged["breakevenTrailing"] is True  # defaults 独有键并入
    assert merged["breakevenThreshold"] == 0.02
    assert merged["takeProfit"] == defaults["takeProfit"]  # 显式键不被 defaults 覆盖

    patched = _apply_trade_config_defaults_and_patch(
        dict(explicit), defaults, {"breakevenTrailing": False}
    )
    assert patched["breakevenTrailing"] is False  # payload patch 覆盖一切
