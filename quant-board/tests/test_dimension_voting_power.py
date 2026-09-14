# -*- coding: utf-8 -*-
"""维度话语权归零对照 harness 锚点测试（2026-09-14，阶段 23 追问：谁在总档投票中话语权最大）。

背景：synergy 总档投票 v = res票 + rank票 + vp票 + cs票，res/rank/vp 权重硬编码 1.0
（volume_price.py:339，无维度级权重扫描记录）。用户命题：测各维实际话语权。
方法：整维归零对照（每维从合成中移除后 vs baseline 的 ΔsaEx + 档位翻转率）+
结构统计（各维实际投票率、环境门触发率）。

归零路径差异（如实区分）：
- cs：config patch tierSynergyCrossSectionVote=0（干净配置路径）；
- rank/vp：monkeypatch _synergy_tier wrapper 置空 tier/dir（无配置字段，评估态注入）；
- lc_gate：wrapper 把 lc_tier 置 "C"（同时去掉 E veto 与 B/D 降档）；
- res：replay 链路 100% 缺票（阶段 3 诊断），无法做"去共振"对照——结构事实如实报告。
"""
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.operations.evaluate_dimension_voting_power import (
    DIM_COMBO_TRIALS,
    DIM_REFINE_TRIALS,
    DIM_ZERO_TRIALS,
    DIM_WEIGHT_SCAN_TRIALS,
    NEUTRAL_DIMS,
    power_summary,
    make_neutralize_wrapper,
    structural_power_stats,
)


# ---------------------------------------------------------------------------
# 层 1 结构统计：voteRate 口径（方向词汇 buy/sell 与 vp 的 up/down 都算非零票）
# ---------------------------------------------------------------------------


def test_structural_vote_rate_counts_up_down_directions() -> None:
    """vp 维 direction 用 up/down/neutral 词汇（volume_price.py:152）——
    voteRate 必须统计 buy/sell/up/down 四种非零方向，只认 buy/sell 会把 vp 误报为 0%。"""
    signals = [
        {"rankTrend": {"observation": {
            "synergy": {"signalTier": "A", "tierReasons": []},
            "rankTrend": {"signalTier": "A", "direction": "buy"},
            "volumePrice": {"signalTier": "A", "direction": "up"},
            "crossSection": {"signalTier": "B"},
            "lifecycle": {"veto": False},
        }}},
        {"rankTrend": {"observation": {
            "synergy": {"signalTier": "D", "tierReasons": ["周期 D 环境降档"]},
            "rankTrend": {"signalTier": "C", "direction": "hold"},
            "volumePrice": {"signalTier": "D", "direction": "down"},
            "crossSection": {"signalTier": "C"},
            "lifecycle": {"veto": True},
        }}},
    ]
    stats = structural_power_stats(signals)
    assert stats["voteRate"]["rank"] == pytest.approx(0.5)
    assert stats["voteRate"]["vp"] == pytest.approx(1.0)
    assert stats["voteRate"]["cs"] == pytest.approx(1.0)
    assert stats["lcGate"]["vetoShare"] == pytest.approx(0.5)
    assert stats["lcGate"]["downgradeShare"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# trial 规格：归零路径与覆盖完整性
# ---------------------------------------------------------------------------


def test_dim_zero_trials_cover_all_arithmetic_voters() -> None:
    """归零对照必须覆盖 v 算术的全部活跃投票源：rank/vp/cs + 环境门 lc。

    res 缺席是结构事实（replay 缺票，无法归零一个本来就为 0 的票），在 desc 中标注。
    pm/dv 权重默认 0（已关闭观察），不入对照。
    """
    keys = [t["key"] for t in DIM_ZERO_TRIALS]
    assert keys == ["dim_no_rank", "dim_no_vp", "dim_no_cs", "dim_no_lc_gate"]
    by_key = {t["key"]: t for t in DIM_ZERO_TRIALS}
    assert by_key["dim_no_cs"]["mechanism"] == "config"
    assert by_key["dim_no_cs"]["overrides"] == {"tierSynergyCrossSectionVote": 0.0}
    for key in ("dim_no_rank", "dim_no_vp", "dim_no_lc_gate"):
        assert by_key[key]["mechanism"] == "monkeypatch"
        assert by_key[key]["dim"] in NEUTRAL_DIMS


def test_neutralize_wrapper_zeroes_target_dimension_args() -> None:
    """wrapper 按位置置空目标维 tier/dir（_synergy_tier 前 7 个位置参数）。"""
    calls = []

    def fake_tier(res_t, res_d, rank_t, rank_d, vp_t, vp_d, lc_t, *args, **kwargs):
        calls.append((res_t, res_d, rank_t, rank_d, vp_t, vp_d, lc_t))
        return "C", []

    for dim, expect in (
        ("rank", ("S", "buy", None, None, "A", "up", "B")),
        ("vp", ("S", "buy", "A", "up", None, None, "B")),
        ("lc_gate", ("S", "buy", "A", "up", "A", "up", "C")),
    ):
        calls.clear()
        wrapper = make_neutralize_wrapper(dim, fake_tier)
        wrapper("S", "buy", "A", "up", "A", "up", "B", object())
        assert calls[-1] == expect, dim


def test_neutralize_wrapper_unknown_dim_rejected() -> None:
    with pytest.raises(ValueError):
        make_neutralize_wrapper("res", lambda *a, **k: ("C", []))
    with pytest.raises(ValueError):
        make_neutralize_wrapper("not_a_dim", lambda *a, **k: ("C", []))


# ---------------------------------------------------------------------------
# 话语权汇总（纯函数，合成报告）
# ---------------------------------------------------------------------------


def _synthetic_power_report(
    base_sa: dict[str, float],
    trial_sa: dict[str, dict[str, float]],
    base_tiers: dict[str, list[str]],
    trial_tiers: dict[str, dict[str, list[str]]],
) -> dict:
    """合成三窗报告：baseline/trial 的 synergy.saEx 与逐信号 signalTier 序列。"""
    windows: dict = {}
    for win in ("decision", "oos1", "oos2"):
        trials: dict = {
            "baseline": {
                "result": {
                    "synergy": {"saEx": base_sa[win]},
                    "signalTiers": base_tiers.get(win, []),
                }
            }
        }
        for key, sa in trial_sa.items():
            trials[key] = {
                "result": {
                    "synergy": {"saEx": sa[win]},
                    "signalTiers": trial_tiers.get(key, {}).get(win, []),
                }
            }
        windows[win] = {"trials": trials}
    return windows


def test_power_summary_flip_rate_and_sa_delta() -> None:
    """话语权 = 档位翻转帧占比 + saEx 绝对/相对差；翻转按逐位比较。"""
    report = _synthetic_power_report(
        {"decision": 0.09, "oos1": 0.08, "oos2": 0.07},
        {"dim_x": {"decision": 0.08, "oos1": 0.08, "oos2": 0.07}},
        {"decision": ["S", "A", "C", "D"], "oos1": ["A"], "oos2": ["C"]},
        {"dim_x": {"decision": ["S", "B", "C", "D"], "oos1": ["A"], "oos2": ["D"]}},
    )
    summary = power_summary(report, "dim_x")
    assert summary["windows"]["decision"]["saExDelta"] == pytest.approx(-0.01)
    assert summary["windows"]["decision"]["tierFlipRate"] == pytest.approx(0.25)
    assert summary["windows"]["decision"]["compared"] == 4
    assert summary["windows"]["oos1"]["tierFlipRate"] == pytest.approx(0.0)
    assert summary["windows"]["oos2"]["tierFlipRate"] == pytest.approx(1.0)


def test_power_summary_ranked_by_flip_then_sa() -> None:
    """verdict 提供跨窗汇总：翻转率均值（话语权主指标）+ saExRel 均值。"""
    report = _synthetic_power_report(
        {"decision": 0.09, "oos1": 0.08, "oos2": 0.07},
        {"dim_x": {"decision": 0.099, "oos1": 0.088, "oos2": 0.077}},
        {"decision": ["S", "A", "C", "D"], "oos1": ["A", "C"], "oos2": ["C", "D"]},
        {"dim_x": {"decision": ["B", "A", "C", "D"], "oos1": ["A", "D"], "oos2": ["C", "D"]}},
    )
    summary = power_summary(report, "dim_x")
    assert summary["meanTierFlipRate"] == pytest.approx((0.25 + 0.5 + 0.0) / 3)
    assert summary["meanSaExRel"] == pytest.approx(round(0.1, 4))


def test_power_summary_handles_missing_trial_and_length_mismatch() -> None:
    """trial 缺失 → insufficient_data；信号序列长度不一致（不可逐位对齐）→ flipRate=None 不伪造。"""
    report = _synthetic_power_report({"decision": 0.09, "oos1": 0.08, "oos2": 0.07}, {}, {}, {})
    assert power_summary(report, "dim_x")["verdict"] == "insufficient_data"
    report2 = _synthetic_power_report(
        {"decision": 0.09, "oos1": 0.08, "oos2": 0.07},
        {"dim_x": {"decision": 0.08, "oos1": 0.08, "oos2": 0.07}},
        {"decision": ["S", "A"], "oos1": ["A"], "oos2": ["C"]},
        {"dim_x": {"decision": ["S", "A", "C"], "oos1": ["A"], "oos2": ["C"]}},
    )
    summary = power_summary(report2, "dim_x")
    assert summary["windows"]["decision"]["tierFlipRate"] is None
    assert summary["verdict"] == "measured"


# ---------------------------------------------------------------------------
# 5 档维度权重扫描组（2026-09-14：res/rank/vp 权重参数化后，全 config 路径）
# ---------------------------------------------------------------------------


def test_dim_weight_scan_group_structure() -> None:
    """权重扫描 = baseline + 4 维 × {×0, ×0.5, ×1.5, ×2.0}（5 档含基线）；全 config patch。"""
    scan = DIM_WEIGHT_SCAN_TRIALS
    keys = [t["key"] for t in scan]
    assert keys[0] == "baseline"
    assert len(keys) == len(set(keys)) == 1 + 4 * 4
    expected = {
        f"dimw_{dim}__x{tag}"
        for dim in ("res", "rank", "vp", "cs")
        for tag in ("00", "05", "15", "20")
    }
    assert expected | {"baseline"} == set(keys)
    field_of = {
        "res": "tierSynergyResonanceVote",
        "rank": "tierSynergyRankVote",
        "vp": "tierSynergyVolumePriceVote",
        "cs": "tierSynergyCrossSectionVote",
    }
    by_key = {t["key"]: t["overrides"] for t in scan}
    for dim, field in field_of.items():
        assert by_key[f"dimw_{dim}__x00"] == {field: 0.0}
        assert by_key[f"dimw_{dim}__x05"] == {field: 0.5}
        assert by_key[f"dimw_{dim}__x15"] == {field: 1.5}
        assert by_key[f"dimw_{dim}__x20"] == {field: 2.0}
    # 每 patch 单变量、from_patch 可接受
    for key, patch in by_key.items():
        if key != "baseline":
            assert len(patch) == 1
            RankTrendConfig.from_patch(patch)


def test_dim_weight_zero_cross_validates_zero_out_trial() -> None:
    """权重归零（config 路径）与归零对照（monkeypatch 路径）对 rank 维同构——
    dimw_rank__x00 的 ΔsaEx 应与 dim_no_rank 一致（live 报告交叉验证锚）。"""
    by_key = {t["key"]: t["overrides"] for t in DIM_WEIGHT_SCAN_TRIALS}
    assert by_key["dimw_rank__x00"] == {"tierSynergyRankVote": 0.0}


# ---------------------------------------------------------------------------
# 第二轮精扫 + 组合提案（2026-09-14 第一轮证据驱动）
# 第一轮粗扫读数：res/rank/cs 三轴 ×0.5 三窗全正（res +19.5/+17.9/+2.4、
# rank +5.0/+3.8/+19.0、cs +2.7/+14.4/+10.3），×1.5/×2.0 三窗全负；
# vp 轴两侧受损（×0.5 OOS 双负 −18.9/−1.1、×0 oos1 −64.4），当前 1.0 在窄峰。
# 归零档全部不可行（res/rank ×0 passHard 全掉、vp ×0 oos1 −64.4）→ 精扫下限 0.25。
# ---------------------------------------------------------------------------


def test_dim_refine_group_targets_round1_sensitive_axes() -> None:
    """精扫 = res/rank/cs 各补 ×0.25/×0.625/×0.75（左侧通道找峰），vp 补 ×0.75/×1.25（确认窄峰）。"""
    refine = DIM_REFINE_TRIALS
    keys = [t["key"] for t in refine]
    assert keys == [
        "dimw_res__x025", "dimw_res__x0625", "dimw_res__x075",
        "dimw_rank__x025", "dimw_rank__x0625", "dimw_rank__x075",
        "dimw_cs__x025", "dimw_cs__x0625", "dimw_cs__x075",
        "dimw_vp__x075", "dimw_vp__x125",
    ]
    by_key = {t["key"]: t["overrides"] for t in refine}
    field_of = {
        "res": "tierSynergyResonanceVote",
        "rank": "tierSynergyRankVote",
        "cs": "tierSynergyCrossSectionVote",
        "vp": "tierSynergyVolumePriceVote",
    }
    factor_of_tag = {"025": 0.25, "0625": 0.625, "075": 0.75, "125": 1.25}
    for key, patch in by_key.items():
        dim = key.split("__")[0].replace("dimw_", "")
        factor = factor_of_tag[key.split("__x")[1]]
        assert patch == {field_of[dim]: pytest.approx(factor)}, key
        RankTrendConfig.from_patch(patch)


def test_dim_combo_group_proposals() -> None:
    """组合提案（判定卡对象）：三轴（res/rank/cs）同档减权、vp 保持 1.0。

    c_half 三轴 ×0.5（第一轮证据直译）、c_three_quarter 三轴 ×0.75（温和）、
    c_quarter 三轴 ×0.25（剂量下探）。梯度断言：同轴 quarter < half < three_quarter < 1.0。
    机制警告（已写入 desc）：三轴同减半后 v 上限 ≈2.6，S 线（≥3）不可达 → S 档消失，
    属档位重分布，必须过 Track 2 判定卡（C3 passHard 重点核查）。
    """
    combos = DIM_COMBO_TRIALS
    assert [t["key"] for t in combos] == ["combo_quarter_three", "combo_half_three", "combo_three_quarter"]
    field_of = {
        "tierSynergyResonanceVote": "res",
        "tierSynergyRankVote": "rank",
        "tierSynergyCrossSectionVote": "cs",
    }
    by_key = {t["key"]: t["overrides"] for t in combos}
    for key, factor in (("combo_quarter_three", 0.25), ("combo_half_three", 0.5), ("combo_three_quarter", 0.75)):
        patch = by_key[key]
        assert set(patch) == set(field_of), key
        assert "tierSynergyVolumePriceVote" not in patch, key
        for field in field_of:
            assert patch[field] == pytest.approx(factor), (key, field)
        c = RankTrendConfig.from_patch(patch)
        for field in field_of:
            assert getattr(c, field) == pytest.approx(factor)
        assert c.tierSynergyVolumePriceVote == pytest.approx(1.0)
