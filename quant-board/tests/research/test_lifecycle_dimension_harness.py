# -*- coding: utf-8 -*-
"""周期（lifecycle）维参数贡献率评估 harness 锚点测试（2026-09-13，长测阶段 23 预研）。

背景（用户确认口径，brainstorming 2026-09-13）：
- B 组为主：lifecycle_decision 阈值族（config.py lifecycle* 10 参数）+ decisionReversal*
  3 参数 + riskPressureWeights 是周期维影响 synergy/veto 的真杠杆，做两层实证；
- A 组冗余验证：lifecycleWeights/lifecycleMomentumWeights/decisionRiskPenaltyWeights
  只进 observation.lifecycle.score 展示分（compose_observation_scores）与 final confidence，
  对 synergy saEx/passHard/veto 预期零效应——用少量 trial 验证零效应即判冗余，
  不做深扫（overfitting-audit §5.1 D 项 cycle* 50 结构参数不在本任务范围）；
- B 组 trial 档位：两轮制——第一轮粗筛 ×0.5/×1.5/×2（阈值是规则边界非连续权重，
  Min 类 ×2=收紧、Max 类 ×2=放宽），第二轮只对敏感参数补精扫；
- A 组 patch 口径：list 字段 from_patch 整体替换无归一化，trial patch 显式构造和=1。

端到端锚（live 数据，不在单测内）：baseline trial 必须逐位复现阶段 22.8 端到端锚
三窗读数（decision 0.0939 / oos1 0.0854 / oos2 0.0737，p2_aggressive 落默认后基线）。
"""
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.operations.evaluate_lifecycle_dimension import (
    BASELINE_ANCHOR,
    LC_EVENT_SUBSETS,
    THRESHOLD_FIELDS,
    TRIAL_GROUPS,
    WINDOWS,
    lifecycle_weights_patch,
    make_threshold_patch,
    threshold_semantics,
    zero_effect_summary,
)

# ---------------------------------------------------------------------------
# 默认值锚（golden 不漂移：默认参数被意外改动时此处先红）
# ---------------------------------------------------------------------------


def test_default_values_match_documented_anchors() -> None:
    """周期维参数默认值锚（config.py + ranktrend-l1-param-ledger 口径）。"""
    c = RankTrendConfig()
    assert c.lifecycleWeights == pytest.approx([0.35, 0.25, 0.2, 0.2])
    assert c.lifecycleMomentumWeights == pytest.approx([0.3, 0.45, 0.25])
    assert c.lifecycleMomentumScales == pytest.approx([15.0, 15.0, 8.0])
    # 2026-09-30 用户决策 x30 落默认（B-202610 批次 O6 触发成立且增强 + C1/C2/C3/C4 补测/C5 全过，
    # 长测阶段 27.4）：默认 15.0 → 45.0；回退 = 显式 patch lifecycleMidLongCommitmentMin=15.0
    assert c.lifecycleMidLongCommitmentMin == pytest.approx(45.0)
    assert c.lifecycleAccelCommitmentMin == pytest.approx(8.0)
    assert c.lifecycleWeakPathCommitmentMax == pytest.approx(0.45)
    assert c.lifecycleVelocityMin == pytest.approx(18.0)
    assert c.lifecycleAccelMin == pytest.approx(12.0)
    assert c.lifecycleLowVisibilityPathMax == pytest.approx(0.7)
    assert c.lifecycleLowVisibilityMomentumMin == pytest.approx(18.0)
    assert c.lifecycleHighRiskPressureMin == pytest.approx(0.75)
    assert c.lifecycleHighRiskDivergenceMin == pytest.approx(0.8)
    assert c.lifecycleHighRiskOverheatMin == pytest.approx(0.7)
    assert c.decisionReversalPressureMin == pytest.approx(0.78)
    assert c.decisionReversalOverheatMin == pytest.approx(0.7)
    assert c.decisionReversalMarginMax == pytest.approx(0.05)
    assert c.riskPressureWeights == pytest.approx([0.58, 0.42])
    assert c.decisionRiskPenaltyWeights == pytest.approx([11.0, 9.0, 5.0])


def test_baseline_anchor_is_stage_22_8_end_to_end() -> None:
    """baseline 锚 = 阶段 22.8 落默认 p2_aggressive 后的端到端三窗读数。"""
    assert BASELINE_ANCHOR == {"decision": 0.0939, "oos1": 0.0854, "oos2": 0.0737}


def test_windows_avoid_frozen_final() -> None:
    """四窗纪律（B-202610 口径 §2.1/§3）：decision/oos1/oos2 全月/oos2u 未消费子窗；
    FINAL(8/1-8/14) 无窗覆盖。WINDOWS 派生自 data_windows 单一源（审计 D1 同族防线）。
    （旧断言 oos2=(09-01,09-12) 为截断口径，已随 §2.1 定案废弃。）"""
    from backend.optimization.data_windows import WINDOWS as STANDARD

    assert WINDOWS == {
        "decision": ("2026-04-15", "2026-07-31"),
        "oos1": ("2026-08-15", "2026-08-31"),
        "oos2": ("2026-09-01", "2026-09-30"),
        "oos2u": ("2026-09-13", "2026-09-30"),
    }
    for name, (start, end) in WINDOWS.items():
        assert (start, end) == STANDARD[name], name
        assert not (start <= "2026-08-14" and end >= "2026-08-01"), (start, end)


# ---------------------------------------------------------------------------
# THRESHOLD_FIELDS 与 trial patch 构造（B 组）
# ---------------------------------------------------------------------------


def test_threshold_fields_cover_lifecycle_and_reversal_families() -> None:
    """阈值字段清单：lifecycle_decision 10 参数 + decisionReversal 3 信号面参数。

    decisionReversalFinalConfCap 只 cap confidence 数值不改变信号方向，不入阈值扫描；
    riskPressureWeights 是 list 权重单独成组（rp_* trial）。
    """
    fields = {f: kind for f, kind in THRESHOLD_FIELDS}
    expected = {
        "lifecycleMidLongCommitmentMin": "min",
        "lifecycleAccelCommitmentMin": "min",
        "lifecycleWeakPathCommitmentMax": "max",
        "lifecycleVelocityMin": "min",
        "lifecycleAccelMin": "min",
        "lifecycleLowVisibilityPathMax": "max",
        "lifecycleLowVisibilityMomentumMin": "min",
        "lifecycleHighRiskPressureMin": "min",
        "lifecycleHighRiskDivergenceMin": "min",
        "lifecycleHighRiskOverheatMin": "min",
        "decisionReversalPressureMin": "min",
        "decisionReversalOverheatMin": "min",
        "decisionReversalMarginMax": "max",
    }
    assert fields == expected


def test_threshold_patch_scales_current_default() -> None:
    """阈值 patch = 当前默认 × factor（单变量）；from_patch 可直接接受。"""
    for field, _kind in THRESHOLD_FIELDS:
        patch = make_threshold_patch(field, 0.5)
        assert patch == {field: pytest.approx(getattr(RankTrendConfig(), field) * 0.5)}
        c = RankTrendConfig.from_patch(patch)
        assert getattr(c, field) == pytest.approx(getattr(RankTrendConfig(), field) * 0.5)


def test_threshold_patch_rejects_unknown_field_and_nonpositive_factor() -> None:
    with pytest.raises(ValueError):
        make_threshold_patch("lifecycleWeights", 0.5)  # list 权重不走阈值 patch
    with pytest.raises(ValueError):
        make_threshold_patch("notAField", 0.5)
    with pytest.raises(ValueError):
        make_threshold_patch("lifecycleVelocityMin", 0.0)
    with pytest.raises(ValueError):
        make_threshold_patch("lifecycleVelocityMin", -1.5)


def test_threshold_semantics_direction_annotated() -> None:
    """语义标注：Min 类 ×>1=收紧（更难满足）、×<1=放宽；Max 类相反；×1=baseline。"""
    assert threshold_semantics("lifecycleVelocityMin", 2.0) == "tighten"
    assert threshold_semantics("lifecycleVelocityMin", 0.5) == "loosen"
    assert threshold_semantics("lifecycleWeakPathCommitmentMax", 2.0) == "loosen"
    assert threshold_semantics("lifecycleWeakPathCommitmentMax", 0.5) == "tighten"
    assert threshold_semantics("lifecycleVelocityMin", 1.0) == "baseline"


def test_b_scan_group_structure_baseline_plus_single_variable() -> None:
    """b_scan 组 = baseline + 13 阈值 × {0.5,1.5,2} + riskPressureWeights 3 档；键唯一、单变量。"""
    scan = TRIAL_GROUPS["b_scan"]
    keys = [t["key"] for t in scan]
    assert keys[0] == "baseline"
    assert len(keys) == len(set(keys)) == 1 + 13 * 3 + 3
    threshold_keys = {f"thr_{f}__x{f_}" for f, _ in THRESHOLD_FIELDS for f_ in ("05", "15", "20")}
    rp_keys = {"rp_overheat_lean", "rp_equal", "rp_divergence_lean"}
    assert threshold_keys | rp_keys | {"baseline"} == set(keys)
    for spec in scan:
        overrides = spec["overrides"] or {}
        if spec["key"] != "baseline":
            assert len(overrides) == 1, spec["key"]
    by_key = {t["key"]: t["overrides"] for t in scan}
    for field, _kind in THRESHOLD_FIELDS:
        default = getattr(RankTrendConfig(), field)
        assert by_key[f"thr_{field}__x05"] == {field: pytest.approx(default * 0.5)}
        assert by_key[f"thr_{field}__x15"] == {field: pytest.approx(default * 1.5)}
        assert by_key[f"thr_{field}__x20"] == {field: pytest.approx(default * 2.0)}
    assert by_key["rp_overheat_lean"]["riskPressureWeights"] == pytest.approx([0.7, 0.3])
    assert by_key["rp_equal"]["riskPressureWeights"] == pytest.approx([0.5, 0.5])
    assert by_key["rp_divergence_lean"]["riskPressureWeights"] == pytest.approx([0.42, 0.58])


# ---------------------------------------------------------------------------
# A 组冗余验证：list 权重 patch（和=1 归一化口径，用户确认）
# ---------------------------------------------------------------------------


def test_lifecycle_weights_patch_requires_normalized_four_vector() -> None:
    """lifecycleWeights patch：长度 4、非负、和=1（显式归一化口径）；非法输入拒绝。"""
    patch = lifecycle_weights_patch([0.4, 0.35, 0.25, 0.0])
    assert patch == {"lifecycleWeights": [0.4, 0.35, 0.25, 0.0]}
    c = RankTrendConfig.from_patch(patch)
    assert c.lifecycleWeights == pytest.approx([0.4, 0.35, 0.25, 0.0])
    with pytest.raises(ValueError):
        lifecycle_weights_patch([0.5, 0.5, 0.5, 0.5])  # 和≠1
    with pytest.raises(ValueError):
        lifecycle_weights_patch([0.3, 0.3, 0.3])  # 长度错
    with pytest.raises(ValueError):
        lifecycle_weights_patch([0.5, 0.5, 0.2, -0.2])  # 负权重


def test_a_display_group_structure() -> None:
    """a_display 组 = lifecycleWeights 3 变体 + momentumWeights 1 变体 + riskPenalty 1 变体。

    全部 list 整体替换 patch；权重类和=1（penalty 组 confidence-only 语义豁免和=1）。
    """
    display = TRIAL_GROUPS["a_display"]
    keys = [t["key"] for t in display]
    assert keys == [
        "a_equal_weights",
        "a_drop_risksafety",
        "a_stage_lean",
        "a_momentum_mid_lean",
        "a_risk_penalty_half",
    ]
    by_key = {t["key"]: t["overrides"] for t in display}
    assert by_key["a_equal_weights"]["lifecycleWeights"] == pytest.approx([0.25, 0.25, 0.25, 0.25])
    assert by_key["a_drop_risksafety"]["lifecycleWeights"] == pytest.approx([0.4, 0.35, 0.25, 0.0])
    assert by_key["a_stage_lean"]["lifecycleWeights"] == pytest.approx([0.5, 0.2, 0.15, 0.15])
    assert by_key["a_momentum_mid_lean"]["lifecycleMomentumWeights"] == pytest.approx([0.15, 0.6, 0.25])
    assert by_key["a_risk_penalty_half"]["decisionRiskPenaltyWeights"] == pytest.approx([5.5, 4.5, 2.5])
    for key in ("a_equal_weights", "a_drop_risksafety", "a_stage_lean", "a_momentum_mid_lean"):
        patch = by_key[key]
        for value in patch.values():
            assert sum(value) == pytest.approx(1.0)
            assert all(v >= 0 for v in value)


# ---------------------------------------------------------------------------
# 层 1：周期维事件谓词（observation.lifecycle 路径）
# ---------------------------------------------------------------------------


def _signal_with_lc(veto: bool = False, tier: str = "C", stage: str = "ignition") -> dict:
    return {
        "rankTrend": {
            "observation": {
                "lifecycle": {"veto": veto, "signalTier": tier, "stage": stage},
            }
        }
    }


def test_lc_event_subsets_cover_tiers_and_stages() -> None:
    expected = {
        "lc_veto",
        "lc_tier_A", "lc_tier_B", "lc_tier_D", "lc_tier_E",
        "lc_stage_expansion", "lc_stage_ignition", "lc_stage_crowded",
        "lc_stage_cooling", "lc_stage_reversal",
    }
    assert set(LC_EVENT_SUBSETS) == expected


def test_lc_event_predicates_match() -> None:
    assert LC_EVENT_SUBSETS["lc_veto"][1](_signal_with_lc(veto=True)) is True
    assert LC_EVENT_SUBSETS["lc_veto"][1](_signal_with_lc(veto=False)) is False
    assert LC_EVENT_SUBSETS["lc_tier_E"][1](_signal_with_lc(tier="E")) is True
    assert LC_EVENT_SUBSETS["lc_tier_A"][1](_signal_with_lc(tier="A")) is True
    assert LC_EVENT_SUBSETS["lc_tier_D"][1](_signal_with_lc(tier="D")) is True
    assert LC_EVENT_SUBSETS["lc_tier_B"][1](_signal_with_lc(tier="B")) is True
    assert LC_EVENT_SUBSETS["lc_stage_reversal"][1](_signal_with_lc(stage="reversal")) is True
    assert LC_EVENT_SUBSETS["lc_stage_expansion"][1](_signal_with_lc(stage="expansion")) is True
    # S/C 档不属于任何被采集档位（C 中性不伪装成事件样本）
    s = _signal_with_lc(tier="C", stage="ignition")
    for key in ("lc_tier_A", "lc_tier_B", "lc_tier_D", "lc_tier_E"):
        assert LC_EVENT_SUBSETS[key][1](s) is False


def test_lc_event_predicates_tolerate_missing_fields() -> None:
    """缺字段/空结构不抛错、判 False（fail-visible：样本计数侧如实可见）。"""
    for key in LC_EVENT_SUBSETS:
        assert LC_EVENT_SUBSETS[key][1]({}) is False
        assert LC_EVENT_SUBSETS[key][1]({"rankTrend": {}}) is False
        assert LC_EVENT_SUBSETS[key][1]({"rankTrend": {"observation": {}}}) is False


# ---------------------------------------------------------------------------
# A 组零效应判定（纯函数，合成报告）
# ---------------------------------------------------------------------------


def _synthetic_report(
    sa: dict[str, float | None],
    pass_hard: dict[str, bool] | None = None,
    flips: dict[str, dict[str, float]] | None = None,
    counts: dict[str, int] | None = None,
) -> dict:
    """合成三窗报告：baseline 与 trial 的 synergy.saEx/passHard/flipRates/signalCount。

    sa/pass_hard/counts 的键用短标签 b:<tag>/t:<tag>（tag: d=decision, o1=oos1, o2=oos2）。
    """
    tags = {"decision": "d", "oos1": "o1", "oos2": "o2"}
    windows: dict = {}
    for win, tag in tags.items():
        default_flip = {"veto": 0.1, "bd_downgrade": 0.05}
        flip_base = (flips or {}).get(f"b:{tag}", default_flip)
        flip_trial = (flips or {}).get(f"t:{tag}", default_flip)
        result = {
            "synergy": {"saEx": sa.get(f"b:{tag}"), "passHard": (pass_hard or {}).get(f"b:{tag}", True)},
            "flipRates": dict(flip_base),
            "signalCount": (counts or {}).get(f"b:{tag}", 100),
        }
        trial = {
            "synergy": {"saEx": sa.get(f"t:{tag}"), "passHard": (pass_hard or {}).get(f"t:{tag}", True)},
            "flipRates": dict(flip_trial),
            "signalCount": (counts or {}).get(f"t:{tag}", 100),
        }
        windows[win] = {"trials": {"baseline": {"result": result}, "a_x": {"result": trial}}}
    return windows


def test_zero_effect_summary_confirmed_when_identical() -> None:
    """trial 与 baseline 三窗逐位一致 → zero_effect_confirmed（A 组冗余判定的合同）。"""
    report = _synthetic_report({"b:d": 0.09, "t:d": 0.09, "b:o1": 0.08, "t:o1": 0.08, "b:o2": 0.07, "t:o2": 0.07})
    summary = zero_effect_summary(report, "a_x")
    assert summary["verdict"] == "zero_effect_confirmed"
    assert summary["windows"]["decision"]["saExDelta"] == pytest.approx(0.0)
    assert summary["windows"]["decision"]["passHardSame"] is True
    assert summary["windows"]["decision"]["flipVetoDelta"] == pytest.approx(0.0)


def test_zero_effect_summary_active_when_sa_ex_shifts() -> None:
    """saEx 出现差异 → signal_active（展示分权重若影响信号即推翻冗余假设）。"""
    report = _synthetic_report({"b:d": 0.09, "t:d": 0.095, "b:o1": 0.08, "t:o1": 0.08, "b:o2": 0.07, "t:o2": 0.07})
    summary = zero_effect_summary(report, "a_x")
    assert summary["verdict"] == "signal_active"
    assert summary["windows"]["decision"]["saExDelta"] == pytest.approx(0.005)


def test_zero_effect_summary_active_when_flip_or_count_changes() -> None:
    """翻转率或信号量漂移同样视为 signal_active（不只看 saEx）。"""
    report = _synthetic_report(
        {"b:d": 0.09, "t:d": 0.09, "b:o1": 0.08, "t:o1": 0.08, "b:o2": 0.07, "t:o2": 0.07},
        flips={"t:d": {"veto": 0.1, "bd_downgrade": 0.06}},
    )
    assert zero_effect_summary(report, "a_x")["verdict"] == "signal_active"
    report2 = _synthetic_report(
        {"b:d": 0.09, "t:d": 0.09, "b:o1": 0.08, "t:o1": 0.08, "b:o2": 0.07, "t:o2": 0.07},
        counts={"t:d": 99},
    )
    assert zero_effect_summary(report2, "a_x")["verdict"] == "signal_active"


def test_zero_effect_summary_handles_missing_trial_and_none_sa() -> None:
    """trial 缺失 → insufficient_data；saEx None 与 None 对比不伪造一致也不误报差异。"""
    report = _synthetic_report({"b:d": 0.09, "b:o1": 0.08, "b:o2": 0.07})
    for win in ("decision", "oos1", "oos2"):
        report[win]["trials"].pop("a_x")
    assert zero_effect_summary(report, "a_x")["verdict"] == "insufficient_data"
    report2 = _synthetic_report({"b:d": None, "t:d": None, "b:o1": 0.08, "t:o1": 0.08, "b:o2": 0.07, "t:o2": 0.07})
    summary = zero_effect_summary(report2, "a_x")
    assert summary["verdict"] == "zero_effect_confirmed"
    assert summary["windows"]["decision"]["saExDelta"] is None


def test_zero_effect_summary_active_when_passhard_drops() -> None:
    """passHard 掉档 → signal_active（C3 约束在 A 组同样一票否决冗余判定）。"""
    report = _synthetic_report(
        {"b:d": 0.09, "t:d": 0.09, "b:o1": 0.08, "t:o1": 0.08, "b:o2": 0.07, "t:o2": 0.07},
        pass_hard={"t:d": False},
    )
    assert zero_effect_summary(report, "a_x")["verdict"] == "signal_active"


# ---------------------------------------------------------------------------
# 第二轮精扫 + 组合提案（第一轮证据驱动，2026-09-13）
# ---------------------------------------------------------------------------


def test_b_refine_group_targets_round1_sensitive_params() -> None:
    """b_refine 组（第一轮证据驱动）：只精扫敏感参数。

    - MidLongCommitmentMin：唯一三窗全正方向（×1.5/×2 dec +0.1~0.6/oos1 +0.9/oos2 +3.5），
      补 ×1.25/×1.75 剂量曲线 + ×3 上探找平台；
    - VelocityMin：oos2 全档正（×1.5 +6.0%）但 decision/oos1 微弱，补 ×1.25/×1.75；
    - WeakPathCommitmentMax ×0.75：第一轮放宽侧（×1.5/×2）oos1 −5.0/−7.6% 明确受损，
      补收紧侧确认单调性。
    零效应参数（HighRisk Divergence/Overheat、decisionReversal*、riskPressure）不进精扫。
    """
    refine = TRIAL_GROUPS["b_refine"]
    keys = [t["key"] for t in refine]
    assert keys == [
        "thr_lifecycleMidLongCommitmentMin__x125",
        "thr_lifecycleMidLongCommitmentMin__x175",
        "thr_lifecycleMidLongCommitmentMin__x30",
        "thr_lifecycleVelocityMin__x125",
        "thr_lifecycleVelocityMin__x175",
        "thr_lifecycleWeakPathCommitmentMax__x075",
    ]
    by_key = {t["key"]: t["overrides"] for t in refine}
    c = RankTrendConfig()
    assert by_key["thr_lifecycleMidLongCommitmentMin__x125"] == {
        "lifecycleMidLongCommitmentMin": pytest.approx(c.lifecycleMidLongCommitmentMin * 1.25)
    }
    assert by_key["thr_lifecycleMidLongCommitmentMin__x30"] == {
        "lifecycleMidLongCommitmentMin": pytest.approx(c.lifecycleMidLongCommitmentMin * 3.0)
    }
    assert by_key["thr_lifecycleVelocityMin__x125"] == {
        "lifecycleVelocityMin": pytest.approx(c.lifecycleVelocityMin * 1.25)
    }
    assert by_key["thr_lifecycleWeakPathCommitmentMax__x075"] == {
        "lifecycleWeakPathCommitmentMax": pytest.approx(c.lifecycleWeakPathCommitmentMax * 0.75)
    }
    # 每档语义标注与方向一致（精扫档全为收紧侧）
    for spec in refine:
        assert spec["semantics"] == "tighten"


def test_proposal_group_combination_trials() -> None:
    """proposal 组（组合提案，Track 2 判定卡对象）：承诺/速度门槛收紧的两档梯度。

    单变量第一轮 decision rel 全部 <±2.3%（远低于 C1 +3% 线），组合是唯一可能
    达线路径；c1 双参数保守、c2 三参数扩展（MidLong 剂量上探到 ×2）。

    2026-09-30 x30（MidLongCommitmentMin 45.0）落默认后，c1/c2 的 overrides 仍为
    基于 pre-x30 默认 15 的绝对 patch（22.5/30）——组合臂冻结为历史口径（相对新默认
    反转为放宽侧），其批次读数（OBSERVE，C1 未过）仅作历史证据；未来组合剂量扫描
    须以新默认重新定义。
    """
    proposals = TRIAL_GROUPS["proposal"]
    assert [t["key"] for t in proposals] == ["c1_commit_tight", "c2_commit_tight_ext"]
    c = RankTrendConfig()
    assert c.lifecycleMidLongCommitmentMin == pytest.approx(45.0)
    p1 = proposals[0]["overrides"]
    assert p1["lifecycleMidLongCommitmentMin"] == pytest.approx(22.5)  # 冻结 pre-x30 口径 15×1.5
    assert p1["lifecycleVelocityMin"] == pytest.approx(c.lifecycleVelocityMin * 1.5)
    p2 = proposals[1]["overrides"]
    assert p2["lifecycleMidLongCommitmentMin"] == pytest.approx(30.0)  # 冻结 pre-x30 口径 15×2.0
    assert p2["lifecycleVelocityMin"] == pytest.approx(c.lifecycleVelocityMin * 1.5)
    assert p2["lifecycleAccelMin"] == pytest.approx(c.lifecycleAccelMin * 1.5)
    # 梯度：c2 在 c1 基础上加码（MidLong 更紧 + 多一参数）
    assert p2["lifecycleMidLongCommitmentMin"] > p1["lifecycleMidLongCommitmentMin"]
    assert p2["lifecycleVelocityMin"] == p1["lifecycleVelocityMin"]
