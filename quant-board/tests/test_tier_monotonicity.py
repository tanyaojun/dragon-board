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
    """阶段 3 修复后合同通过 fixture：S(30)/A(30)/B(30) 同桶交错（frame0 rank 3i+1/3i+2/3i+3），
    frame1 S 升（rank 1-30）、A 平（rank 31-60）、B 降（rank 61-90）。
    预期（excess 口径，§5.2 修复后）：S exM≈+0.33 > A≈0 > B≈−0.33 单调、S/A 加权 excess≈0.25、
    S 样本 30、unknown 0 → 硬约束全过（spearman=1.0、无反转、saExcessAccuracy≥0.05）。"""
    tiers = ["S"] * 30 + ["A"] * 30 + ["B"] * 30
    frame0 = [3 * i + 1 for i in range(30)] + [3 * i + 2 for i in range(30)] + [3 * i + 3 for i in range(30)]
    frame1 = list(range(1, 31)) + list(range(31, 61)) + list(range(61, 91))
    return _frames_and_signals(tiers, frame0, frame1)


def _no_a_fixture() -> tuple[list[dict], list[dict]]:
    """无 A 样本 fixture（§5.2 saExcessAccuracy 样本池加权）：S(30)/B(30) 偶数交错同桶，
    S 升 B 降 → S excess≈+0.25，A n=0 不拖死加权结果。"""
    tiers = ["S"] * 30 + ["B"] * 30
    frame0 = [2 * i + 1 for i in range(30)] + [2 * i + 2 for i in range(30)]
    frame1 = list(range(1, 31)) + list(range(31, 61))
    return _frames_and_signals(tiers, frame0, frame1)


def test_tier_forward_returns_layer_stats() -> None:
    frames, signals = _monotonic_passing_fixture()
    stats = tier_forward_returns(signals, frames, horizon=1)
    tiers = stats["tiers"]
    assert tiers["S"]["count"] == 30
    assert tiers["A"]["count"] == 30
    assert tiers["B"]["count"] == 30
    assert tiers["S"]["meanFutureReturn"] > tiers["A"]["meanFutureReturn"] > tiers["B"]["meanFutureReturn"]
    assert tiers["S"]["directionAccuracy"] >= 0.9  # 交错边界个别 delta≈0，非全升
    assert tiers["B"]["meanFutureReturn"] < 0
    # 修复后口径：excess（去趋势）字段存在且 S 最高
    assert tiers["S"]["excessMeanFutureReturn"] > 0
    assert tiers["S"]["excessDirectionAccuracy"] > 0


def test_monotonicity_passes_hard_constraint() -> None:
    frames, signals = _monotonic_passing_fixture()
    stats = tier_forward_returns(signals, frames, horizon=1)
    assert stats["monotonicity"]["passHardConstraint"] is True
    assert stats["monotonicity"]["spearmanRankCorr"] > 0
    assert stats["monotonicity"]["reversals"] == []
    checks = stats["monotonicity"]["checks"]
    assert checks["sSampleCount"]["ok"] is True
    assert checks["saExcessAccuracy"]["ok"] is True  # 修复后：excess 达标线 0.05
    assert checks["unknownRateBelow5pct"]["ok"] is True
    assert checks["monotonicNoReversal"]["validTiers"] == 3  # 链收窄为 S/A/B


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
    """A 档无样本时 S/A 合并 excess 按样本池加权：仅 S 样本且 excess>0 → 约束通过（不被 None→0 拖死）。"""
    frames, signals = _no_a_fixture()
    stats = tier_forward_returns(signals, frames, horizon=1)
    assert stats["tiers"]["A"]["count"] == 0
    assert stats["tiers"]["S"]["count"] == 30
    checks = stats["monotonicity"]["checks"]
    assert checks["saExcessAccuracy"]["ok"] is True
    assert checks["saExcessAccuracy"]["actual"] >= 0.05


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
    """同一批 signals 按不同维度分层：rankTrend 维 S 升 A 平 B 降 → 单调（新合同链 S/A/B）；
    volumePrice 维（同一批股票）反向 C 升 S 降 → 不单调。验证 dimension 参数真正生效。"""
    tiers, frame0, frame1 = ["S"] * 30 + ["A"] * 30 + ["B"] * 30, None, None
    frame0 = [3 * i + 1 for i in range(30)] + [3 * i + 2 for i in range(30)] + [3 * i + 3 for i in range(30)]
    frame1 = list(range(1, 31)) + list(range(31, 61)) + list(range(61, 91))
    frames, _ = _frames_and_signals(tiers, frame0, frame1)
    signals = [
        _multi_dimension_signal(
            {
                # rankTrend 维与档位块一致；volumePrice 维故意反向（S 块实际下跌）
                "resonance": tier,
                "rankTrend": tier,
                "volumePrice": {"S": "C", "A": "B", "B": "S"}[tier],
                "lifecycle": "B",
                "synergy": tier,
            }
        )
        | {"snapshotId": "s0", "code": f"{i:06d}"}
        for i, tier in enumerate(tiers)
    ]
    rank_trend_stats = tier_forward_returns(signals, frames, horizon=1, dimension="rankTrend")
    assert rank_trend_stats["tiers"]["S"]["count"] == 30
    assert rank_trend_stats["tiers"]["S"]["meanFutureReturn"] > rank_trend_stats["tiers"]["B"]["meanFutureReturn"]
    assert rank_trend_stats["monotonicity"]["passHardConstraint"] is True

    vp_stats = tier_forward_returns(signals, frames, horizon=1, dimension="volumePrice")
    assert vp_stats["tiers"]["S"]["count"] == 30  # 原 B 块被映射为 S
    assert vp_stats["tiers"]["S"]["meanFutureReturn"] < 0
    assert vp_stats["tiers"]["C"]["count"] == 30  # 原 S 块被映射为 C
    assert vp_stats["tiers"]["C"]["meanFutureReturn"] > 0
    assert vp_stats["monotonicity"]["passHardConstraint"] is False


def test_tier_discrimination_contract() -> None:
    """tier_discrimination 输出区分度指标：S−C 收益差、S/A 方向精度、D/E 相对 C、档位收益极差、正单调。"""
    # positiveMonotonic 用新合同 passing fixture（S/A/B 交错，excess 单调）
    frames, signals = _monotonic_passing_fixture()
    stats = tier_forward_returns(signals, frames, horizon=1)
    disc = tier_discrimination(stats)
    assert disc["tierSpread"] is not None and disc["tierSpread"] > 0
    assert disc["saDirectionAccuracy"] > 0  # 原始口径保留（验收以 excess 为准）
    assert disc["positiveMonotonic"] is True
    # sMinusC/aMinusC/deVsC 用含 C/D/E 的 fixture（S 升 C 降，无 D/E → deVsC None 不伪造）
    tiers = ["S"] * 30 + ["A"] * 20 + ["C"] * 10
    frame0 = list(range(31, 61)) + list(range(11, 31)) + list(range(1, 11))
    frame1 = list(range(1, 31)) + list(range(10, 30)) + list(range(31, 41))
    frames2, signals2 = _frames_and_signals(tiers, frame0, frame1)
    disc2 = tier_discrimination(tier_forward_returns(signals2, frames2, horizon=1))
    assert disc2["sMinusC"] is not None and disc2["sMinusC"] > 0
    assert disc2["aMinusC"] is not None
    assert disc2["deVsC"] is None  # 无 D/E 样本时为 None，不伪造


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


def test_excess_direction_accuracy_conditions_by_rank_bucket() -> None:
    """分位条件化（阶段 3 修复方向 2）：纯均值回归下 excess≈0——追强档位原始 acc 被
    高分位基线拉低，但条件化后不额外惩罚；excess = directionAccuracy − 样本桶基线 acc。"""
    # S 25 只高桶（rank 1-25 → pct 60-100，桶 6-9）全降；C 35 只低桶（rank 26-60 → pct 1.67-58.33，桶 0-5）全升
    # 桶完全分离（S 最小 pct 60 = 桶 6 起点，C 最大 pct 58.33 = 桶 5）→ 纯均值回归
    tiers = ["S"] * 25 + ["C"] * 35
    frame0 = list(range(1, 26)) + list(range(26, 61))
    frame1 = list(range(26, 51)) + list(range(1, 36))  # S rank 26-50（降）、C rank 1-35（升）
    frames, signals = _frames_and_signals(tiers, frame0, frame1)
    stats = tier_forward_returns(signals, frames, horizon=1)
    s = stats["tiers"]["S"]
    c = stats["tiers"]["C"]
    assert s["directionAccuracy"] == 0.0  # 原始 acc 被均值回归打成 0
    assert s["excessDirectionAccuracy"] is not None
    assert abs(s["excessDirectionAccuracy"]) < 0.01  # 同桶基线同为 0 → excess≈0
    assert abs(c["excessDirectionAccuracy"]) < 0.01
    # 字段关系：excess = directionAccuracy − 样本桶基线 acc
    assert abs((s["excessDirectionAccuracy"] or 0) - (s["directionAccuracy"] - (s["bucketBaselineAccuracy"] or 0))) < 1e-6
    assert "bucketBaselines" in stats


def test_excess_direction_accuracy_positive_when_signal_beats_baseline() -> None:
    """同桶内信号优于基线：S 低桶升入高桶、C 高桶降 → S excess > 0（条件化后信号有增量信息）。"""
    # frame0：S 20 只 rank 1-20（高桶）、C 40 只 rank 21-60（中低桶）
    # frame1：S 保持高桶 rank 1-20（delta≈0）、C 中低桶部分升、高桶 C 部分降
    tiers = ["S"] * 20 + ["C"] * 40
    frame0 = list(range(1, 21)) + list(range(21, 61))
    frame1 = list(range(1, 21)) + list(range(41, 61)) + list(range(21, 41))  # C 前 20 降、后 20 升
    frames, signals = _frames_and_signals(tiers, frame0, frame1)
    stats = tier_forward_returns(signals, frames, horizon=1)
    assert "excessDirectionAccuracy" in stats["tiers"]["S"]
    assert "excessDirectionAccuracy" in stats["tiers"]["C"]
