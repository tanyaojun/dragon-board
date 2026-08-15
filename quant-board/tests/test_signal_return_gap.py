"""阶段 5：信号→收益映射缺口诊断（纯函数）测试。

验证四类诊断能力（ranktrend-longterm-backtest-plan.md §阶段 5）：
1. 入场后 horizon 价格收益分布（S/A 档 vs 同分位桶未入场样本对照）；
2. 分位桶条件化（验证"追强入场集中高分位、被均值回归吃掉"假设）；
3. S/A 档信号 ∩ A_MAIN 入场集合的重叠度（Jaccard）；
4. 退出机制检验（horizon 收益为正但交易净收益为负 → 缺口在退出）。
fail-visible：帧边界不足/股票缺失/缺价格 → 样本不计但 count 可见，不伪造收益。
"""

from __future__ import annotations

from backend.analysis.ranktrend.signal_return_gap import (
    assess_gap,
    horizon_price_return_stats,
    sa_bucket_distribution,
    sa_vs_amain_overlap,
    signal_entry_tier,
)


def _frames(
    frame_count: int,
    *,
    price_up_codes: set[str] | None = None,
    price_down_codes: set[str] | None = None,
) -> list[dict]:
    """构造 frame_count 帧；price_up_codes 股票价格逐帧上涨，price_down_codes 逐帧下跌，其余持平。"""
    frames: list[dict] = []
    for i in range(frame_count):
        rows: list[dict] = []
        for idx, code in enumerate(["000001", "000002", "000003", "000004", "000005"]):
            price = 10.0
            if code in (price_up_codes or set()):
                price = 10.0 + i * 1.0
            elif code in (price_down_codes or set()):
                price = 10.0 - i * 0.5
            rows.append({"code": code, "rank": idx + 1, "price": price})
        frames.append({"snapshotId": f"s{i}", "stocks": rows})
    return frames


def _signal(snapshot_id: str, code: str, tier: str, candidate_tier: str = "B_IGNITION") -> dict:
    return {
        "snapshotId": snapshot_id,
        "code": code,
        "candidateTier": candidate_tier,
        "rankTrend": {"observation": {"synergy": {"signalTier": tier}}},
    }


def test_signal_entry_tier_reads_synergy_tier() -> None:
    assert signal_entry_tier(_signal("s0", "000001", "S")) == "S"
    assert signal_entry_tier(_signal("s0", "000002", "A")) == "A"
    assert signal_entry_tier(_signal("s0", "000003", "B")) == "B"
    assert signal_entry_tier({}) == "unknown"


def test_horizon_price_return_stats_entry_vs_control() -> None:
    """S/A 档（追强）未来上涨、对照组未来下跌 → entry 收益为正、control 为负（fail-visible 无伪造）。"""
    frames = _frames(5, price_up_codes={"000001"}, price_down_codes={"000003", "000004", "000005"})
    signals = [
        _signal("s0", "000001", "S"),  # S 档上涨
        _signal("s0", "000002", "A"),  # A 档持平
        _signal("s0", "000003", "B"),  # B 档下跌（对照组）
        _signal("s0", "000004", "C"),  # C 档下跌（对照组）
        _signal("s0", "000005", "D"),  # D 档下跌（对照组）
    ]
    stats = horizon_price_return_stats(signals, frames, horizon=2)
    assert stats["horizon"] == 2
    entry = stats["entry"]
    assert entry["count"] == 2  # S + A
    assert entry["mean"] > 0
    assert entry["median"] >= 0
    assert entry["winRate"] >= 0.5
    control = stats["control"]
    assert control["count"] == 3
    assert control["mean"] < 0
    assert control["winRate"] < 0.5
    # 分位桶：rank1（S）→ 桶 9（最高分位），rank2（A）→ 桶 8，rank3/4/5（B/C/D）→ 桶 6/4/2
    assert stats["byBucket"]["9"]["entryCount"] == 1
    assert stats["byBucket"]["8"]["entryCount"] == 1
    assert stats["byBucket"]["2"]["controlCount"] == 1


def test_horizon_price_return_stats_fail_visible_frame_boundary() -> None:
    """帧边界不足的样本不计入收益但保留在 count 缺失统计中，不伪造收益（fail-visible）。"""
    frames = _frames(3, price_up_codes={"000001"})
    signals = [_signal("s0", "000001", "S"), _signal("s1", "000001", "S"), _signal("s2", "000001", "S")]
    stats = horizon_price_return_stats(signals, frames, horizon=2)
    # s1/s2 触发后不足 2 帧 → 不计入收益样本（共 2 个帧边界不足）
    assert stats["entry"]["count"] == 1
    assert stats["skippedFrameBoundary"] == 2
    assert stats["entry"]["mean"] > 0


def test_horizon_price_return_stats_fail_visible_missing_price() -> None:
    """未来帧缺该股票（无 price）→ 样本不计入且标记 skippedMissingRow（fail-visible）。"""
    frames = _frames(5)
    # 未来帧（s2 之后）删除 000001 → s0/s1 的信号找不到未来价格
    for frame in frames[2:]:
        frame["stocks"] = [row for row in frame["stocks"] if row["code"] != "000001"]
    signals = [_signal("s0", "000001", "S"), _signal("s1", "000001", "S")]
    stats = horizon_price_return_stats(signals, frames, horizon=2)
    assert stats["entry"]["count"] == 0
    assert stats["skippedMissingRow"] == 2


def test_horizon_price_return_stats_fail_visible_invalid_rank() -> None:
    """rank 超界（占位 rank=999）→ percentile 无意义，样本跳过且计数（fail-visible，不伪造分位桶）。"""
    frames = _frames(5, price_up_codes={"000001"})
    frames[0]["stocks"][0]["rank"] = 999  # 占位 rank 超界
    signals = [_signal("s0", "000001", "S")]
    stats = horizon_price_return_stats(signals, frames, horizon=2)
    assert stats["entry"]["count"] == 0
    assert stats["skippedInvalidRank"] == 1


def test_sa_bucket_distribution_skips_invalid_rank() -> None:
    """分位桶分布同样跳过 rank 超界样本（fail-visible，不归入 0 桶伪装）。"""
    frames = _frames(3)
    signals = [_signal("s0", "000001", "S")]
    frames[0]["stocks"][0]["rank"] = 999
    dist = sa_bucket_distribution(signals, frames)
    assert sum(dist.values()) == 0


def test_sa_bucket_distribution_high_bucket() -> None:
    """S/A 档信号集中在高分位桶（追强天然高分位 → 均值回归风险），0 桶最弱。"""
    frames = _frames(3)
    # 20 只股票：rank 1-5（高分位）S/A 档，rank 16-20（低分位）B 档
    frames[0]["stocks"] = [
        {"code": f"{i:06d}", "rank": i, "price": 10.0} for i in range(1, 21)
    ]
    signals = [
        _signal("s0", f"{i:06d}", "S" if i <= 5 else ("A" if i <= 10 else "B"))
        for i in range(1, 21)
    ]
    dist = sa_bucket_distribution(signals, frames)
    # rank 1-5 → percentile 80-99（桶 8/9），rank 6-10 → 桶 5-7
    high_bucket_total = (dist.get("8", 0) or 0) + (dist.get("9", 0) or 0)
    assert high_bucket_total >= 4  # rank 1-5 中至少 4 只为 S/A
    assert dist.get("0", 0) == 0  # 低分位无 S/A 档


def test_sa_vs_amain_overlap_jaccard() -> None:
    """Jaccard 重叠度：S/A 档信号与 A_MAIN 候选的交集/并集。"""
    signals = [
        _signal("s0", "000001", "S", candidate_tier="A_MAIN"),  # 重叠
        _signal("s0", "000002", "A", candidate_tier="A_MAIN"),  # 重叠
        _signal("s0", "000003", "S", candidate_tier="B_IGNITION"),  # 仅 S/A
        _signal("s0", "000004", "B", candidate_tier="A_MAIN"),  # 仅 A_MAIN
    ]
    result = sa_vs_amain_overlap(signals)
    assert result["saCount"] == 3
    assert result["amainCount"] == 3
    assert result["intersection"] == 2
    assert abs(result["jaccard"] - 2 / 4) < 1e-3
    assert abs(result["saShareInAmain"] - 2 / 3) < 1e-3


def test_assess_gap_entry_timing() -> None:
    """horizon 收益中位数为负 → 缺口在入场时机（追强被均值回归吃掉）。"""
    gap = assess_gap(entry_median=-0.02, entry_win_rate=0.4, trade_median=0.01, trade_win_rate=0.55)
    assert gap["location"] == "entry"
    assert gap["reason"]


def test_assess_gap_exit_mechanism() -> None:
    """horizon 收益为正但交易净收益为负 → 缺口在退出机制（吞利润）。"""
    gap = assess_gap(entry_median=0.05, entry_win_rate=0.6, trade_median=-0.03, trade_win_rate=0.45)
    assert gap["location"] == "exit"
    assert gap["reason"]


def test_assess_gap_both_positive_mapping_ok() -> None:
    """horizon 与交易收益均为正 → 映射正常，无缺口。"""
    gap = assess_gap(entry_median=0.04, entry_win_rate=0.6, trade_median=0.02, trade_win_rate=0.58)
    assert gap["location"] == "none"
