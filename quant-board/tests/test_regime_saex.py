"""regime 分状态 saEx/passHard 摘要测试（评估基建防均值掩盖视图）。

背景（longterm-backtest-plan 阶段 14）：决策窗 ALL passHard=True 掩盖同窗 strong
桶 passHard=False——分状态视图必须让桶内失效可见；桶样本数守恒、缺失 state
fail-visible 计入 "<missing>"、空状态不产出桶。
"""

from __future__ import annotations

from backend.analysis.ranktrend.research.regime_saex import (
    MISSING_STATE,
    regime_saex_stats,
    regime_state_of,
)


def _regime_signal(tier: str, state: str, code: str) -> dict:
    """带 regime 路径（rankTrend.strategy.regime.state）+ synergy tier 的 signal。"""
    return {
        "snapshotId": "s0",
        "code": code,
        "rankTrend": {
            "strategy": {"regime": {"state": state}},
            "observation": {"synergy": {"signalTier": tier}},
        },
    }


def _fixture() -> tuple[list[dict], list[dict]]:
    """S/A/B 各 30、strong/normal 交错（偶数 strong）：桶内各档 15，升/平/降模式每桶一致。"""
    tiers = ["S"] * 30 + ["A"] * 30 + ["B"] * 30
    frame0_stocks = [
        {"code": f"{i:06d}", "rank": (3 * i + 1 if i < 30 else 3 * (i - 30) + 2 if i < 60 else 3 * (i - 60) + 3)}
        for i in range(90)
    ]
    frame1_stocks = [
        {"code": f"{i:06d}", "rank": (i + 1 if i < 30 else (i - 30) + 31 if i < 60 else (i - 60) + 61)}
        for i in range(90)
    ]
    frames = [
        {"snapshotId": "s0", "stocks": frame0_stocks},
        {"snapshotId": "s1", "stocks": frame1_stocks},
    ]
    signals = [
        _regime_signal(tier, "strong" if i % 2 == 0 else "normal", f"{i:06d}")
        for i, tier in enumerate(tiers)
    ]
    return frames, signals


def test_regime_state_of_reads_strategy_path() -> None:
    """state 从 rankTrend.strategy.regime.state 读取；缺路径回退空串（调用方计 <missing>）。"""
    assert regime_state_of(_regime_signal("S", "strong", "000001")) == "strong"
    assert regime_state_of({"rankTrend": {"observation": {}}}) == ""
    assert regime_state_of({}) == ""


def test_regime_saex_stats_buckets_and_conservation() -> None:
    """两状态分桶：桶内 S/A/B 各 15，与 ALL（各 30）守恒；桶内升/平/降单调保持、
    saEx>0、sSampleCount 因桶样本 15<30 如实判 False（区分样本不足与真失效）。"""
    frames, signals = _fixture()
    result = regime_saex_stats(signals, frames, horizon=1)

    assert result["stateCounts"] == {"strong": 45, "normal": 45}
    assert set(result["states"]) == {"strong", "normal"}
    for state, stats in result["states"].items():
        tiers = stats["tiers"]
        assert tiers["S"]["count"] == 15
        assert tiers["A"]["count"] == 15
        assert tiers["B"]["count"] == 15
        # 升/平/降模式在每桶内保持：S meanRet > B meanRet、S excess>0
        assert tiers["S"]["meanFutureReturn"] > tiers["B"]["meanFutureReturn"]
        assert tiers["S"]["excessMeanFutureReturn"] > 0
        checks = stats["monotonicity"]["checks"]
        assert checks["monotonicNoReversal"]["ok"] is True
        assert checks["sSampleCount"]["ok"] is False  # 桶内 15<30，如实 fail-visible
        assert checks["sSampleCount"]["actual"] == 15


def test_regime_saex_stats_missing_state_counted_not_bucketed() -> None:
    """state 缺失信号计入 "<missing>" 计数、不产出桶（fail-visible，不静默丢弃）。"""
    frames, signals = _fixture()
    signals.append({"snapshotId": "s0", "code": "999999",
                    "rankTrend": {"observation": {"synergy": {"signalTier": "S"}}}})
    result = regime_saex_stats(signals, frames, horizon=1)

    assert result["stateCounts"][MISSING_STATE] == 1
    assert MISSING_STATE not in result["states"]
    # 分桶守恒不受缺失影响：桶内仍是各 15
    assert result["states"]["strong"]["tiers"]["S"]["count"] == 15


def test_regime_saex_stats_empty_signals() -> None:
    """空 signals：stateCounts 空、states 空，不伪造桶。"""
    result = regime_saex_stats([], [{"snapshotId": "s0", "stocks": []}], horizon=1)
    assert result["stateCounts"] == {}
    assert result["states"] == {}
