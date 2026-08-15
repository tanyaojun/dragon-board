"""档位单调性统计测试（回测方案 §5.1/§5.2）。

构造已知档位收益序列验证：分层统计、Spearman 单调、相邻反转、硬约束判定
（S 样本≥30、无反转、S/A 方向精度≥60%、D/E 低于 C、unknown<5%）。
"""

from __future__ import annotations

from backend.analysis.ranktrend.tier_monotonicity import (
    TIER_ORDER,
    tier_discrimination,
    tier_forward_returns,
    tier_monotonicity_score,
    tier_signal_of,
)


def _frames_and_signals(
    tier_block: list[str],
    frame0_ranks: list[int],
    frame1_ranks: list[int],
) -> tuple[list[dict], list[dict]]:
    frame0 = {
        "snapshotId": "s0",
        "stocks": [{"code": f"{i:06d}", "rank": r} for i, r in enumerate(frame0_ranks)],
    }
    frame1 = {
        "snapshotId": "s1",
        "stocks": [{"code": f"{i:06d}", "rank": r} for i, r in enumerate(frame1_ranks)],
    }
    signals = [
        {
            "snapshotId": "s0",
            "code": f"{i:06d}",
            "rankTrend": {"observation": {"synergy": {"signalTier": tier}}},
        }
        for i, tier in enumerate(tier_block)
    ]
    return [frame0, frame1], signals


def _monotonic_passing_fixture() -> tuple[list[dict], list[dict]]:
    """S(30) rank 31-60→1-30（+0.5）；A(20) rank 11-30→10-29（+0.017）；C(10) rank 1-10→31-40（−0.5）。
    预期：S>A>C 单调、S 样本 30、S/A 精度 100%、unknown 0 → 硬约束全过。"""
    tiers = ["S"] * 30 + ["A"] * 20 + ["C"] * 10
    frame0 = list(range(31, 61)) + list(range(11, 31)) + list(range(1, 11))
    frame1 = list(range(1, 31)) + list(range(10, 30)) + list(range(31, 41))
    return _frames_and_signals(tiers, frame0, frame1)


def test_tier_forward_returns_layer_stats() -> None:
    frames, signals = _monotonic_passing_fixture()
    stats = tier_forward_returns(signals, frames, horizon=1)
    tiers = stats["tiers"]
    assert tiers["S"]["count"] == 30
    assert tiers["A"]["count"] == 20
    assert tiers["C"]["count"] == 10
    assert tiers["S"]["meanFutureReturn"] > tiers["A"]["meanFutureReturn"] > tiers["C"]["meanFutureReturn"]
    assert tiers["S"]["directionAccuracy"] == 1.0
    assert tiers["C"]["meanFutureReturn"] < 0


def test_monotonicity_passes_hard_constraint() -> None:
    frames, signals = _monotonic_passing_fixture()
    stats = tier_forward_returns(signals, frames, horizon=1)
    assert stats["monotonicity"]["passHardConstraint"] is True
    assert stats["monotonicity"]["spearmanRankCorr"] > 0
    assert stats["monotonicity"]["reversals"] == []
    checks = stats["monotonicity"]["checks"]
    assert checks["sSampleCount"]["ok"] is True
    assert checks["saDirectionAccuracy"]["ok"] is True
    assert checks["unknownRateBelow5pct"]["ok"] is True


def test_reversal_detected_when_a_below_b() -> None:
    """A 收益 < B → 相邻反转被检出 → 硬约束失败。"""
    tiers = ["S"] * 30 + ["A"] * 20 + ["B"] * 10
    # S 升、A 平（0）、B 升（+0.083）→ A(0) < B(0.083) 反转
    frame0 = list(range(31, 61)) + list(range(11, 31)) + list(range(6, 16))
    frame1 = list(range(1, 31)) + list(range(11, 31)) + list(range(1, 11))
    frames, signals = _frames_and_signals(tiers, frame0, frame1)
    stats = tier_forward_returns(signals, frames, horizon=1)
    assert stats["tiers"]["B"]["meanFutureReturn"] > stats["tiers"]["A"]["meanFutureReturn"]
    assert len(stats["monotonicity"]["reversals"]) >= 1
    assert stats["monotonicity"]["passHardConstraint"] is False
    assert stats["monotonicity"]["checks"]["monotonicNoReversal"]["ok"] is False


def test_s_sample_below_minimum_fails() -> None:
    """S 样本 15 < 30 → 硬约束失败（结构化原因可见）。"""
    tiers = ["S"] * 15 + ["A"] * 25 + ["C"] * 20
    frame0 = list(range(46, 61)) + list(range(11, 36)) + list(range(1, 21))
    frame1 = list(range(1, 16)) + list(range(11, 36)) + list(range(31, 51))
    frames, signals = _frames_and_signals(tiers, frame0, frame1)
    stats = tier_forward_returns(signals, frames, horizon=1)
    assert stats["tiers"]["S"]["count"] == 15
    assert stats["monotonicity"]["passHardConstraint"] is False
    assert stats["monotonicity"]["checks"]["sSampleCount"]["ok"] is False
    assert stats["monotonicity"]["checks"]["sSampleCount"]["actual"] == 15


def test_unknown_rate_above_threshold_fails() -> None:
    """unknown 档占比 10/70≈14.3% > 5% → 硬约束失败；unknown 不计入单调性链（分母含 unknown 自身样本）。"""
    tiers = ["S"] * 30 + ["A"] * 20 + ["C"] * 10 + ["unknown"] * 10
    frame0 = list(range(31, 61)) + list(range(11, 31)) + list(range(1, 11)) + list(range(41, 51))
    frame1 = list(range(1, 31)) + list(range(10, 30)) + list(range(31, 41)) + list(range(41, 51))
    frames, signals = _frames_and_signals(tiers, frame0, frame1)
    stats = tier_forward_returns(signals, frames, horizon=1)
    assert stats["unknownRate"] > 0.05
    assert stats["tiers"]["unknown"]["count"] == 10
    assert stats["monotonicity"]["passHardConstraint"] is False
    assert stats["monotonicity"]["checks"]["unknownRateBelow5pct"]["ok"] is False


def test_empty_signals_returns_full_structure() -> None:
    """空 signals：结构完整不崩，S 样本不足 → 硬约束失败（不静默通过）。"""
    frames, _ = _monotonic_passing_fixture()
    stats = tier_forward_returns([], frames, horizon=1)
    assert stats["tiers"]["S"]["count"] == 0
    assert stats["unknownRate"] == 0
    assert stats["monotonicity"]["passHardConstraint"] is False
    assert stats["monotonicity"]["checks"]["sSampleCount"]["ok"] is False


def test_frame_boundary_samples_excluded() -> None:
    """signal 在最后一帧（未来帧不存在）→ 样本不计入，不伪造收益。"""
    frames, signals = _monotonic_passing_fixture()
    for signal in signals:
        signal["snapshotId"] = "s1"  # 最后一帧
    stats = tier_forward_returns(signals, frames, horizon=1)
    assert stats["tiers"]["S"]["count"] == 0
    assert stats["tiers"]["C"]["count"] == 0


def test_missing_synergy_tier_maps_to_unknown() -> None:
    """signal 缺 synergy.signalTier → 归 'unknown'（不伪装）。"""
    signal = {"rankTrend": {"observation": {}}}
    assert tier_signal_of(signal) == "unknown"
    signal["rankTrend"]["observation"]["synergy"] = {"signalTier": "X"}
    assert tier_signal_of(signal) == "unknown"


def test_tier_monotonicity_score_contract() -> None:
    frames, signals = _monotonic_passing_fixture()
    stats = tier_forward_returns(signals, frames, horizon=1)
    score = tier_monotonicity_score(stats)
    assert score["passHardConstraint"] is True
    assert score["spearmanRankCorr"] == stats["monotonicity"]["spearmanRankCorr"]
    assert score["unknownRate"] == 0
    assert "checks" in score


def test_sa_accuracy_without_a_samples_not_penalized() -> None:
    """A 档无样本时 S/A 合并精度按样本池加权：仅 S 样本且精度 100% → 约束通过（不被 None→0 拖死）。"""
    tiers = ["S"] * 30 + ["C"] * 30
    frame0 = list(range(31, 61)) + list(range(1, 31))
    frame1 = list(range(1, 31)) + list(range(31, 61))
    frames, signals = _frames_and_signals(tiers, frame0, frame1)
    stats = tier_forward_returns(signals, frames, horizon=1)
    assert stats["tiers"]["A"]["count"] == 0
    assert stats["monotonicity"]["checks"]["saDirectionAccuracy"]["ok"] is True
    assert stats["monotonicity"]["checks"]["saDirectionAccuracy"]["actual"] == 1.0


def test_tier_order_constant() -> None:
    """档位序 S>A>B>C 为单调性验证基线（D/E 不参与正向链）。"""
    assert TIER_ORDER == ["S", "A", "B", "C"]


# ─── 阶段 3：四维信号区分度诊断——按维度分层 ───


def _multi_dimension_signal(
    tiers: dict[str, str],
) -> dict:
    """按维度路径构造 signal：resonance 在 rankTrend.resonance，其余在 rankTrend.observation.<dim>。"""
    return {
        "rankTrend": {
            "resonance": {"signalTier": tiers["resonance"]},
            "observation": {
                "rankTrend": {"signalTier": tiers["rankTrend"]},
                "volumePrice": {"signalTier": tiers["volumePrice"]},
                "lifecycle": {"signalTier": tiers["lifecycle"]},
                "synergy": {"signalTier": tiers["synergy"]},
            },
        }
    }


def test_tier_signal_of_dimension_paths() -> None:
    """各维度 signalTier 按各自路径读取；默认维度为 synergy（向后兼容）。"""
    signal = _multi_dimension_signal(
        {"resonance": "S", "rankTrend": "A", "volumePrice": "B", "lifecycle": "C", "synergy": "D"}
    )
    assert tier_signal_of(signal, "resonance") == "S"
    assert tier_signal_of(signal, "rankTrend") == "A"
    assert tier_signal_of(signal, "volumePrice") == "B"
    assert tier_signal_of(signal, "lifecycle") == "C"
    assert tier_signal_of(signal, "synergy") == "D"
    assert tier_signal_of(signal) == "D"  # 默认 synergy


def test_tier_signal_of_dimension_missing_falls_back() -> None:
    """维度缺字段 / 非法值 → 'unknown'（fail-visible：不伪装、不归零）。"""
    signal = {"rankTrend": {"observation": {}}}
    assert tier_signal_of(signal, "resonance") == "unknown"
    assert tier_signal_of(signal, "volumePrice") == "unknown"
    assert tier_signal_of(signal, "rankTrend") == "unknown"
    signal["rankTrend"]["resonance"] = {"signalTier": "X"}
    assert tier_signal_of(signal, "resonance") == "unknown"


def test_tier_forward_returns_layers_by_dimension() -> None:
    """同一批 signals 按不同维度分层：rankTrend 维 S 升 A 平 C 降 → 单调；
    volumePrice 维（同一批股票）反向 C 升 S 降 → 不单调。验证 dimension 参数真正生效。"""
    tier_block = ["S"] * 30 + ["A"] * 20 + ["C"] * 10
    frame0 = list(range(31, 61)) + list(range(11, 31)) + list(range(1, 11))
    frame1 = list(range(1, 31)) + list(range(10, 30)) + list(range(31, 41))
    frames, _ = _frames_and_signals(tier_block, frame0, frame1)
    signals = [
        _multi_dimension_signal(
            {
                # rankTrend 维与档位块一致；volumePrice 维故意反向（S 块实际下跌）
                "resonance": tier,
                "rankTrend": tier,
                "volumePrice": {"S": "C", "A": "B", "C": "S"}[tier],
                "lifecycle": "B",
                "synergy": tier,
            }
        )
        | {"snapshotId": "s0", "code": f"{i:06d}"}
        for i, tier in enumerate(tier_block)
    ]
    rank_trend_stats = tier_forward_returns(signals, frames, horizon=1, dimension="rankTrend")
    assert rank_trend_stats["tiers"]["S"]["count"] == 30
    assert rank_trend_stats["tiers"]["S"]["meanFutureReturn"] > rank_trend_stats["tiers"]["C"]["meanFutureReturn"]
    assert rank_trend_stats["monotonicity"]["passHardConstraint"] is True

    vp_stats = tier_forward_returns(signals, frames, horizon=1, dimension="volumePrice")
    assert vp_stats["tiers"]["S"]["count"] == 10  # 原 C 块（rank 1-10）被映射为 S
    assert vp_stats["tiers"]["S"]["meanFutureReturn"] < 0
    assert vp_stats["tiers"]["C"]["count"] == 30  # 原 S 块被映射为 C
    assert vp_stats["tiers"]["C"]["meanFutureReturn"] > 0
    assert vp_stats["monotonicity"]["passHardConstraint"] is False


def test_tier_discrimination_contract() -> None:
    """tier_discrimination 输出区分度指标：S−C 收益差、S/A 方向精度、D/E 相对 C、档位收益极差、正单调。"""
    frames, signals = _monotonic_passing_fixture()
    stats = tier_forward_returns(signals, frames, horizon=1)
    disc = tier_discrimination(stats)
    assert disc["sMinusC"] is not None and disc["sMinusC"] > 0
    assert disc["aMinusC"] is not None
    assert disc["tierSpread"] is not None and disc["tierSpread"] > 0
    assert disc["saDirectionAccuracy"] >= 0.6
    assert disc["positiveMonotonic"] is True
    assert disc["deVsC"] is None or disc["deVsC"] < 0  # 无 D/E 样本时为 None，不伪造


def test_tier_discrimination_detects_non_monotonic() -> None:
    """A 收益 < B（反转）→ positiveMonotonic=False，sMinusC 仍如实输出（不隐藏数据）。"""
    tiers = ["S"] * 30 + ["A"] * 20 + ["B"] * 10
    frame0 = list(range(31, 61)) + list(range(11, 31)) + list(range(6, 16))
    frame1 = list(range(1, 31)) + list(range(11, 31)) + list(range(1, 11))
    frames, signals = _frames_and_signals(tiers, frame0, frame1)
    stats = tier_forward_returns(signals, frames, horizon=1)
    disc = tier_discrimination(stats)
    assert disc["positiveMonotonic"] is False
    assert "sMinusC" in disc  # 无 C 样本时如实为 None，不伪造
