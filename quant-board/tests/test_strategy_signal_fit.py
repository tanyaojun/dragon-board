"""策略-信号匹配度综合评估测试（阶段 6 综合评估）。

验证逐环节损耗拆解：
1. tier_distribution_by_candidate：synergy S/A 档按 candidateTier 分层的 h8 收益 + 相对基线 delta；
2. amain_funnel_by_regime：A_MAIN 候选按 regime 分层的 h8 收益；
3. entered_vs_unentered：A_MAIN 内实际入场 vs 未入场的 h8 收益对比。
fail-visible：空分组 None 不伪造；样本不足如实输出 count 与 None。
"""

from __future__ import annotations

from backend.analysis.ranktrend.strategy_signal_fit import (
    amain_funnel_by_regime,
    entered_vs_unentered,
    tier_distribution_by_candidate,
)


def _frames(frame_count: int = 12) -> list[dict]:
    frames: list[dict] = []
    for i in range(frame_count):
        rows = [
            {"code": f"{idx:06d}", "rank": idx + 1, "price": 10.0 + (i * 1.0 if idx == 0 else 0.0)}
            for idx in range(6)
        ]
        frames.append({"snapshotId": f"s{i}", "stocks": rows})
    return frames


def _signal(snapshot_id: str, code: str, tier: str, candidate_tier: str = "A_MAIN", regime: str = "normal") -> dict:
    return {
        "snapshotId": snapshot_id,
        "code": code,
        "candidateTier": candidate_tier,
        "regime": regime,
        "rankTrend": {"observation": {"synergy": {"signalTier": tier}}},
    }


def test_tier_distribution_by_candidate_partitions() -> None:
    """S/A 档按 candidateTier 分层：A_MAIN 上涨、B_IGNITION 持平 → 各自 count 与 delta 正确。"""
    frames = _frames()
    # s0 → s8（horizon=8）：000000 上涨（+80%），000001 持平
    signals = [
        _signal("s0", "000000", "S", candidate_tier="A_MAIN"),
        _signal("s0", "000001", "A", candidate_tier="B_IGNITION"),
    ]
    result = tier_distribution_by_candidate(signals, frames, horizon=8)
    assert result["saSignalCount"] == 2
    assert result["sampleCount"] == 2
    by_tier = result["byCandidateTier"]
    assert by_tier["A_MAIN"]["count"] == 1
    assert by_tier["A_MAIN"]["mean"] > 0
    assert by_tier["B_IGNITION"]["count"] == 1
    assert by_tier["B_IGNITION"]["mean"] == 0
    # A_MAIN 相对基线（全量 S/A）的 winRate delta
    assert by_tier["A_MAIN"]["winRateDelta"] > 0


def test_tier_distribution_by_candidate_empty_group_none() -> None:
    """某档无样本 → count=0、mean/median=None（fail-visible，不伪造 0）。"""
    frames = _frames()
    signals = [_signal("s0", "000000", "S", candidate_tier="A_MAIN")]
    result = tier_distribution_by_candidate(signals, frames, horizon=8)
    assert result["byCandidateTier"]["C_CROWDED"]["count"] == 0
    assert result["byCandidateTier"]["C_CROWDED"]["mean"] is None


def test_tier_distribution_by_candidate_empty_input() -> None:
    """无 S/A 档信号 → sampleCount=0 且 note 提示，不抛错。"""
    frames = _frames()
    signals = [_signal("s0", "000000", "B", candidate_tier="A_MAIN")]
    result = tier_distribution_by_candidate(signals, frames, horizon=8)
    assert result["saSignalCount"] == 0
    assert result["sampleCount"] == 0
    assert "note" in result


def test_amain_funnel_by_regime() -> None:
    """A_MAIN 候选按 regime 分层：strong 上涨、weak 下跌 → 各 regime count 与 delta 正确。"""
    frames = _frames()
    signals = [
        _signal("s0", "000000", "S", candidate_tier="A_MAIN", regime="strong"),
        _signal("s0", "000001", "S", candidate_tier="A_MAIN", regime="weak"),
        _signal("s0", "000002", "S", candidate_tier="B_IGNITION", regime="strong"),
    ]
    result = amain_funnel_by_regime(signals, frames, horizon=8)
    assert result["amainSignalCount"] == 2  # 仅 A_MAIN 计入
    assert result["sampleCount"] == 2
    by_regime = result["byRegime"]
    assert by_regime["strong"]["count"] == 1
    assert by_regime["strong"]["mean"] > 0
    assert by_regime["weak"]["count"] == 1
    assert by_regime["weak"]["mean"] == 0


def test_entered_vs_unentered() -> None:
    """A_MAIN 内实际入场 vs 未入场：entered 上涨、unentered 下跌 → enteredMeanDelta 为正。"""
    frames = _frames()
    signals = [
        _signal("s0", "000000", "S", candidate_tier="A_MAIN"),  # entered（上涨）
        _signal("s0", "000001", "S", candidate_tier="A_MAIN"),  # unentered（持平）
        _signal("s0", "000002", "S", candidate_tier="B_IGNITION"),  # 不计入（非 A_MAIN）
    ]
    result = entered_vs_unentered(signals, frames, entered_keys={"s0:000000"}, horizon=8)
    assert result["amainSignalCount"] == 2
    assert result["entered"]["count"] == 1
    assert result["entered"]["mean"] > 0
    assert result["unentered"]["count"] == 1
    assert result["enteredMeanDelta"] > 0
    assert result["enteredWinRateDelta"] > 0


def test_entered_vs_unentered_empty_amain() -> None:
    """无 A_MAIN 候选 → entered/unentered 均 count=0（fail-visible）。"""
    frames = _frames()
    signals = [_signal("s0", "000000", "S", candidate_tier="B_IGNITION")]
    result = entered_vs_unentered(signals, frames, entered_keys=set(), horizon=8)
    assert result["amainSignalCount"] == 0
    assert result["entered"]["count"] == 0
    assert result["unentered"]["count"] == 0
