# -*- coding: utf-8 -*-
"""signal_cache 键参数分组测试（阶段 1 方案 B：交易层参数变化复用已算信号）。"""
from __future__ import annotations

from backend.optimization.trial import _signal_cache_key

SIGNAL_FRAMES = [{"snapshotId": "a"}, {"snapshotId": "b"}]

# 信号层基线（RankTrendConfig 字段，from_patch 可识别）
SIGNAL_BASE = {
    "macdFast": 21, "macdSlow": 34, "macdSignal": 13,
    "momentumPeriods": [3, 5, 8, 13, 21],
    "tierSynergyVoteStrong": 2, "tierSynergyVoteWeak": 1, "tierSynergyVoteReverse": -1,
}


def test_signal_cache_key_ignores_trade_layer_params_in_base() -> None:
    # 用户把交易层参数塞进 backtest.strategy_config → 不得污染缓存键
    contaminated = {
        **SIGNAL_BASE,
        "maxPositions": 8, "takeProfit": 0.12, "stopLoss": -0.06,
        "synergyEntryTierMin": "a", "synergyExitOnDanger": True,
        "minJumpConfidence": 0.6,
    }
    assert _signal_cache_key("train", SIGNAL_FRAMES, SIGNAL_BASE) == _signal_cache_key(
        "train", SIGNAL_FRAMES, contaminated
    )


def test_signal_cache_key_changes_with_signal_params() -> None:
    other = {**SIGNAL_BASE, "macdFast": 8}
    assert _signal_cache_key("train", SIGNAL_FRAMES, SIGNAL_BASE) != _signal_cache_key(
        "train", SIGNAL_FRAMES, other
    )


def test_signal_cache_key_distinguishes_phase_and_frame_range() -> None:
    assert _signal_cache_key("train", SIGNAL_FRAMES, SIGNAL_BASE) != _signal_cache_key(
        "validation", SIGNAL_FRAMES, SIGNAL_BASE
    )
    assert _signal_cache_key("train", SIGNAL_FRAMES, SIGNAL_BASE) != _signal_cache_key(
        "train", [{"snapshotId": "a"}, {"snapshotId": "c"}], SIGNAL_BASE
    )
