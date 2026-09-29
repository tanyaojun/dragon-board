# -*- coding: utf-8 -*-
"""TS 五因子权重实证评估 harness 锚点测试（2026-09-13，权重重定义任务）。

背景：五因子权重 0.24/0.20/0.16/0.20/0.20 是历史比例归一化继承值（阶段 21.8），
用户命题"按各因子正向贡献率重新科学评估和重新定义权重"。本测试锁住评估 harness
`backend/operations/evaluate_ts_factor_weights.py` 的纯函数合同：

1. 事件级谓词：五因子 buy/sell 事件/状态帧过滤器的键结构与缺字段容忍（fail-visible）；
2. trial 规格：留一（weight→0）与半权（weight×0.5）trial 的 from_patch 归一化语义
   ——单变量、同量纲（和=1），是"边际贡献可归因"的前提；
3. 判定卡纯函数：提案 trial 的 C1-C5 判定逻辑（Track 2 同口径）与 None 容忍。

端到端锚（live 数据，不在单测内）：baseline trial 必须逐位复现阶段 21.8 端到端锚
三窗读数（decision 0.0835 / oos1 0.0657 / oos2 0.0572）。
"""
from __future__ import annotations

import math

import pytest

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.operations.evaluate_ts_factor_weights import (
    EVENT_SUBSETS,
    TRIAL_GROUPS,
    WEIGHT_FIELDS,
    _signal_component,
    contribution_summary,
    make_half_patch,
    make_loo_patch,
    proposal_verdict,
    scaled_patch,
)


# ---------------------------------------------------------------------------
# 夹具：合成信号（technical 五分量结构，与 analyze_technical 输出同键）
# ---------------------------------------------------------------------------


def _signal_with(
    direction: str | None = "buy",
    acceleration: str | None = "hold",
    zero_cross: str | None = "sell",
    macd_cross: str | None = "golden",
    ma_cross: str | None = "death",
) -> dict:
    technical: dict = {
        "signals": {
            "direction": {"signal": direction or "hold", "confidence": 50, "score": 0.3},
            "acceleration": {"signal": acceleration or "hold", "confidence": 50, "score": 0.1},
            "zeroCross": {"signal": zero_cross or "hold", "confidence": 50, "score": -0.2},
        },
        "macd": {"cross": macd_cross or "none", "dif": 0.5, "dea": 0.2},
        "maCross": {"cross": ma_cross or "none", "state": "bull", "fast": 15.0, "slow": 14.0},
    }
    return {"rankTrend": {"technical": technical}}


# ---------------------------------------------------------------------------
# 事件级谓词
# ---------------------------------------------------------------------------


def test_event_subsets_covers_five_factors_both_directions() -> None:
    """10 个事件谓词 = 五因子 × {正向, 反向}，键名稳定（报告合同）。"""
    expected = {
        "direction_buy", "direction_sell",
        "acceleration_buy", "acceleration_sell",
        "zeroCross_buy", "zeroCross_sell",
        "macd_golden_event", "macd_death_event",
        "ma_golden_event", "ma_death_event",
    }
    assert set(EVENT_SUBSETS) == expected


def test_event_predicates_match_component_states() -> None:
    assert EVENT_SUBSETS["direction_buy"][1](_signal_with(direction="buy")) is True
    assert EVENT_SUBSETS["direction_sell"][1](_signal_with(direction="sell")) is True
    assert EVENT_SUBSETS["direction_buy"][1](_signal_with(direction="sell")) is False
    assert EVENT_SUBSETS["acceleration_buy"][1](_signal_with(acceleration="buy")) is True
    assert EVENT_SUBSETS["zeroCross_sell"][1](_signal_with(zero_cross="sell")) is True
    assert EVENT_SUBSETS["macd_golden_event"][1](_signal_with(macd_cross="golden")) is True
    assert EVENT_SUBSETS["macd_death_event"][1](_signal_with(macd_cross="death")) is True
    assert EVENT_SUBSETS["ma_golden_event"][1](_signal_with(ma_cross="golden")) is True
    assert EVENT_SUBSETS["ma_death_event"][1](_signal_with(ma_cross="death")) is True


def test_event_predicates_hold_is_neither() -> None:
    """hold 状态帧不属于任何方向事件（不伪装成事件样本）。"""
    s = _signal_with(direction="hold", acceleration="hold", zero_cross="hold")
    for key in ("direction_buy", "direction_sell", "acceleration_buy", "zeroCross_buy"):
        assert EVENT_SUBSETS[key][1](s) is False


def test_event_predicates_tolerate_missing_fields() -> None:
    """缺字段/空结构不抛错、判 False（fail-visible：样本计数侧如实可见）。"""
    for key in EVENT_SUBSETS:
        assert EVENT_SUBSETS[key][1]({}) is False
        assert EVENT_SUBSETS[key][1]({"rankTrend": {}}) is False
        assert EVENT_SUBSETS[key][1]({"rankTrend": {"technical": {"signals": {}}}}) is False


def test_signal_component_returns_empty_dict_on_missing() -> None:
    assert _signal_component(_signal_with(), "direction")["signal"] == "buy"
    assert _signal_component({}, "direction") == {}
    assert _signal_component({"rankTrend": None}, "direction") == {}


# ---------------------------------------------------------------------------
# trial 规格：留一 / 半权（单变量 + from_patch 归一化同量纲）
# ---------------------------------------------------------------------------


def test_trial_groups_baseline_plus_loo_and_half() -> None:
    """core 组 = baseline + 5 留一 + 5 半权；键唯一；overrides 全部是权重字段。"""
    core = TRIAL_GROUPS["core"]
    keys = [t["key"] for t in core]
    assert keys[0] == "baseline"
    assert len(keys) == len(set(keys)) == 11
    loo_keys = {f"loo_{f.removesuffix('Weight')}" for f in WEIGHT_FIELDS}
    half_keys = {f"half_{f.removesuffix('Weight')}" for f in WEIGHT_FIELDS}
    assert loo_keys | half_keys | {"baseline"} == set(keys)
    for spec in core:
        for field, value in (spec["overrides"] or {}).items():
            assert field in WEIGHT_FIELDS
            assert value >= 0


def test_loo_patch_zeroes_target_and_normalizes_rest() -> None:
    """留一 trial：目标权重=0，其余等比归一化（和=1）——移除语义可归因。"""
    patch = make_loo_patch("directionWeight")
    assert patch == {"directionWeight": 0.0}
    c = RankTrendConfig.from_patch(patch)
    assert c.directionWeight == pytest.approx(0.0)
    total = sum(getattr(c, f) for f in WEIGHT_FIELDS)
    assert total == pytest.approx(1.0)
    # 其余四因子相对比例不变（acceleration:crossWeight 保持当前默认比例）
    base = RankTrendConfig()
    assert c.accelerationWeight / c.crossWeight == pytest.approx(
        base.accelerationWeight / base.crossWeight
    )


def test_half_patch_halves_relative_ratio() -> None:
    """半权 trial：目标因子相对其余因子的比例减半（归一化后同量纲）。"""
    base = RankTrendConfig()
    patch = make_half_patch("maWeight")
    assert patch == {"maWeight": pytest.approx(base.maWeight / 2)}
    c = RankTrendConfig.from_patch(patch)
    total = sum(getattr(c, f) for f in WEIGHT_FIELDS)
    assert total == pytest.approx(1.0)
    base_ratio = base.maWeight / base.macdWeight
    assert (c.maWeight / c.macdWeight) == pytest.approx(base_ratio / 2)


def test_half_patch_value_is_half_of_default_and_non_negative() -> None:
    """半权 patch 值 = 当前默认 × 0.5，恒非负（未来某权重默认为 0 时 patch=0 仍合法）。"""
    for field in WEIGHT_FIELDS:
        patch = make_half_patch(field)
        assert patch[field] == pytest.approx(getattr(RankTrendConfig(), field) * 0.5)
        assert patch[field] >= 0


def test_scaled_patch_multiplies_default() -> None:
    """dose-response 扫描：scaled_patch(field, f) = 默认 × f（单变量、同量纲）。"""
    for field in WEIGHT_FIELDS:
        assert scaled_patch(field, 0.25) == {
            field: pytest.approx(getattr(RankTrendConfig(), field) * 0.25)
        }
        assert scaled_patch(field, 1.5) == {
            field: pytest.approx(getattr(RankTrendConfig(), field) * 1.5)
        }


def test_trial_group_up_is_directional_dose_response() -> None:
    """up 组 = 负贡献因子下探 ×0.25 + 正贡献因子上探 ×1.5；键唯一、全权重字段、非零。"""
    up = TRIAL_GROUPS["up"]
    keys = [t["key"] for t in up]
    assert len(keys) == len(set(keys))
    for spec in up:
        for field, value in spec["overrides"].items():
            assert field in WEIGHT_FIELDS
            assert value > 0
    by_key = {t["key"]: t["overrides"] for t in up}
    base = RankTrendConfig()
    assert by_key["quarter_direction"]["directionWeight"] == pytest.approx(base.directionWeight * 0.25)
    assert by_key["quarter_acceleration"]["accelerationWeight"] == pytest.approx(base.accelerationWeight * 0.25)
    assert by_key["up_cross"]["crossWeight"] == pytest.approx(base.crossWeight * 1.5)
    assert by_key["up_macd"]["macdWeight"] == pytest.approx(base.macdWeight * 1.5)
    assert by_key["up_ma"]["maWeight"] == pytest.approx(base.maWeight * 1.5)


def test_trial_group_proposal_weights_are_normalized_and_directional() -> None:
    """proposal 组（2026-09-13 评估口径，基线=旧默认 0.24/0.20/0.16/0.20/0.20）：
    权重精确归一（和=1）、非负、三档梯度方向一致（降 direction/accel、升 ma）。

    阶段 22.8 落默认后 p2_aggressive 已成为当前默认——提案组保留为历史评估记录，
    梯度断言改用提案间字面值互比，不随当前默认漂移。
    """
    proposals = TRIAL_GROUPS["proposal"]
    assert len(proposals) == 3
    keys = [t["key"] for t in proposals]
    assert len(keys) == len(set(keys))
    for spec in proposals:
        patch = spec["overrides"]
        assert set(patch) == set(WEIGHT_FIELDS)
        assert all(v >= 0 for v in patch.values())
        assert sum(patch.values()) == pytest.approx(1.0)
    p1, p2, p3 = (t["overrides"] for t in proposals)
    # 梯度方向（温和 → 激进 → 归零）：负贡献因子单调降、正贡献因子单调升
    assert p2["directionWeight"] < p1["directionWeight"]
    assert p2["accelerationWeight"] < p1["accelerationWeight"]
    assert p1["maWeight"] < p2["maWeight"] < p3["maWeight"]
    # 归零档：三窗负贡献最硬的两个因子直接归 0（vote=0 关闭观察语义）
    assert p3["directionWeight"] == 0.0
    assert p3["accelerationWeight"] == 0.0
    # 采纳锚：p2_aggressive 即当前默认（阶段 22.8 用户决策落默认）
    default = RankTrendConfig()
    for field in WEIGHT_FIELDS:
        assert p2[field] == pytest.approx(getattr(default, field)), field


# ---------------------------------------------------------------------------
# 边际贡献汇总 / 提案判定卡（纯函数，合成报告）
# ---------------------------------------------------------------------------


def _synthetic_report(sa_ex: dict[str, float | None], scores: dict[str, float]) -> dict:
    """合成三窗报告：每 trial 的 synergy.saEx / score。"""

    def _trial(sa: float | None, score: float) -> dict:
        return {"result": {"synergy": {"saEx": sa, "passHard": True}, "score": score}}

    windows: dict = {}
    for win in ("decision", "oos1", "oos2"):
        trials: dict = {"baseline": _trial(sa_ex[win], scores["baseline"])}
        for key in ("loo_direction", "proposal_x"):
            if key in scores:
                trials[key] = _trial(sa_ex.get(f"{win}:{key}"), scores[key])
        windows[win] = {"trials": trials}
    return windows


def test_contribution_summary_windows_and_deltas() -> None:
    """边际贡献汇总：逐窗输出 trial vs baseline 的 saEx/score 绝对差与相对差。"""
    report = _synthetic_report(
        {"decision": 0.08, "oos1": 0.06, "oos2": 0.05,
         "decision:loo_direction": 0.07, "oos1:loo_direction": 0.06, "oos2:loo_direction": None},
        {"baseline": 1.0, "loo_direction": 0.9},
    )
    summary = contribution_summary(report, "loo_direction")
    assert summary["decision"]["saExDelta"] == pytest.approx(-0.01)
    assert summary["decision"]["saExRel"] == pytest.approx(round(-0.01 / 0.08, 4))
    assert summary["oos2"]["saExDelta"] is None  # None 传播，不伪造 0
    assert summary["oos2"]["scoreDelta"] == pytest.approx(-0.1)


def test_contribution_summary_score_delta_propagates_none() -> None:
    """scoreDelta 与 saExDelta 同合同：trial score 缺失时 None 传播，不以 0 兜底伪造差值。"""
    report = _synthetic_report(
        {"decision": 0.08, "oos1": 0.06, "oos2": 0.05,
         "decision:loo_direction": 0.07, "oos1:loo_direction": 0.06, "oos2:loo_direction": 0.05},
        {"baseline": 1.0, "loo_direction": 0.9},
    )
    # 构造 score 键缺失的 trial（review 发现：旧实现 get("score", 0) 会产出假 delta=-1.0）
    report["decision"]["trials"]["loo_direction"]["result"].pop("score")
    summary = contribution_summary(report, "loo_direction")
    assert summary["decision"]["score"] is None
    assert summary["decision"]["scoreDelta"] is None


def test_proposal_verdict_pass_candidate() -> None:
    """C1 决策窗 ≥+3% 且 C2 OOS ≥1 窗同向且 C3 passHard 保持 → PASS_CANDIDATE。"""
    report = _synthetic_report(
        {"decision": 0.08, "oos1": 0.06, "oos2": 0.05,
         "decision:proposal_x": 0.083, "oos1:proposal_x": 0.062, "oos2:proposal_x": 0.049},
        {"baseline": 1.0, "proposal_x": 1.0},
    )
    # 注入 passHard：trial 保持 True
    card = proposal_verdict(report, "proposal_x")
    assert card["conclusion"] == "PASS_CANDIDATE"
    assert card["C1_decisionSaExRel"]["pass"] is True
    assert card["C2_oosPositiveCount"]["pass"] is True


def test_proposal_verdict_reject_on_passhard_drop() -> None:
    """C3 决策窗 passHard 掉档一票否决 → REJECT。"""
    report = _synthetic_report(
        {"decision": 0.08, "oos1": 0.06, "oos2": 0.05,
         "decision:proposal_x": 0.10, "oos1:proposal_x": 0.07, "oos2:proposal_x": 0.06},
        {"baseline": 1.0, "proposal_x": 1.2},
    )
    report["decision"]["trials"]["proposal_x"]["result"]["synergy"]["passHard"] = False
    card = proposal_verdict(report, "proposal_x")
    assert card["conclusion"] == "REJECT"


def test_proposal_verdict_observe_when_c1_short() -> None:
    """C1 未达 +3% 但 C3 保持 → OBSERVE。"""
    report = _synthetic_report(
        {"decision": 0.08, "oos1": 0.06, "oos2": 0.05,
         "decision:proposal_x": 0.081, "oos1:proposal_x": 0.061, "oos2:proposal_x": 0.0505},
        {"baseline": 1.0, "proposal_x": 1.0},
    )
    card = proposal_verdict(report, "proposal_x")
    assert card["conclusion"] == "OBSERVE"
    assert card["C1_decisionSaExRel"]["pass"] is False
    assert card["C2_oosPositiveCount"]["pass"] is True


def test_proposal_verdict_missing_trial_returns_none_safe() -> None:
    """trial 缺失/None saEx 不崩溃，fail-visible 输出 None。"""
    report = _synthetic_report({"decision": 0.08, "oos1": 0.06, "oos2": 0.05}, {"baseline": 1.0})
    card = proposal_verdict(report, "proposal_x")
    assert card == {}
    report2 = _synthetic_report(
        {"decision": 0.08, "oos1": 0.06, "oos2": 0.05,
         "decision:proposal_x": None, "oos1:proposal_x": None, "oos2:proposal_x": None},
        {"baseline": 1.0, "proposal_x": 1.0},
    )
    card2 = proposal_verdict(report2, "proposal_x")
    assert card2["C1_decisionSaExRel"]["value"] is None
    assert card2["C1_decisionSaExRel"]["pass"] is False
    assert not math.isnan(card2["C1_decisionSaExRel"]["value"] or 0)
