"""regime 分状态 saEx/passHard 摘要统计（评估基建防均值掩盖视图，纯函数）。

背景（longterm-backtest-plan 阶段 14/15）：决策窗 ALL passHard=True 掩盖同窗
strong 桶 passHard=False——ALL 口径被 normal/weak 体量稀释，状态级失效不可见。
本模块提供按 market regime state（rankTrend.strategy.regime.state，同帧全股相同）
分桶的 tier_forward_returns 统计集合，供评估 harness（optimize_* 的 evaluate_*）
产出分状态视图；口径与阶段 14 诊断一致：每状态独立
tier_forward_returns(signal_filter=...)（分桶基线同口径重算）。

fail-visible：state 缺失信号计入 "<missing>" 计数、不产出桶（不静默丢弃）；
空状态不产出桶。桶内 stats 的 passHard 为桶内口径，样本不足如实判 False——
调用方按 sSampleCount 区分"样本不足"与"真失效"。纯函数无 I/O；报告视图
（saEx 汇总格式）由 operations 层调用方以既有 _tier_summary 映射。
"""
from __future__ import annotations

from typing import Any

from backend.analysis.ranktrend.research.gate_flip_stats import extract_gate_states
from backend.analysis.ranktrend.research.tier_monotonicity import (
    DEFAULT_DIMENSION,
    tier_forward_returns,
)

MISSING_STATE = "<missing>"


def regime_state_of(signal: dict[str, Any]) -> str:
    """market 级 regime state（同帧全股相同）；缺路径/空值回退空串，由调用方计 <missing>。"""
    return str(extract_gate_states(signal).get("regime_state") or "")


def regime_saex_stats(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizon: int = 1,
    dimension: str = DEFAULT_DIMENSION,
) -> dict[str, Any]:
    """按 regime state 分桶的 tier 统计集合。

    返回 {"stateCounts": {state: 信号数, 含 <missing>}, "states": {state: stats}}；
    states 只含有效状态桶（<missing>/空计数不产出）。闭包用默认参数固定 state，
    避免循环变量 late binding。
    """
    state_counts: dict[str, int] = {}
    for signal in signals:
        state = regime_state_of(signal) or MISSING_STATE
        state_counts[state] = state_counts.get(state, 0) + 1

    states: dict[str, dict[str, Any]] = {}
    for state, count in state_counts.items():
        if state == MISSING_STATE or count <= 0:
            continue
        states[state] = tier_forward_returns(
            signals,
            frames,
            horizon=horizon,
            dimension=dimension,
            signal_filter=lambda signal, _state=state: regime_state_of(signal) == _state,
        )
    return {"stateCounts": state_counts, "states": states}
