from __future__ import annotations

from backend.core.backtest.config import DEFAULT_TRADE_CONFIG


def test_default_trade_config_has_fallback_slippage_rate():
    assert "fallbackSlippageRate" in DEFAULT_TRADE_CONFIG
    assert float(DEFAULT_TRADE_CONFIG["fallbackSlippageRate"]) == 0.001


def test_run_cost_grid_covers_2x2_min_grid():
    from backend.operations.diagnose_cost_sensitivity import run_cost_grid

    grid = {"slippageRate": [0.001, 0.002], "feeRate": [0.0003]}
    # frames/signals 用最小合成序列；TradeSimulator 不可用字段允许 None（fail-visible）
    rows = run_cost_grid([], [], dict(DEFAULT_TRADE_CONFIG), grid=grid)
    assert len(rows) == 2
    assert {row["slippageRate"] for row in rows} == {0.001, 0.002}
    assert {row["feeRate"] for row in rows} == {0.0003}
