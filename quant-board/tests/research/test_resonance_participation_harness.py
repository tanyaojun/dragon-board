# -*- coding: utf-8 -*-
"""共振频率轴剂量 + label 收口 harness 测试（方案 D D-b/D-c）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_resonance_participation import (
    ANCHOR_BASELINE,
    ALL_TRIALS,
    DB_TRIALS,
    DC_TRIALS,
    SA_COUNT_FLOOR,
    _assert_overrides_applied,
    participation_of,
    trial_summary,
    zero_effect_check,
)


def test_db_trials_are_existing_config_fields_only():
    """D-b 首批只用已 config 化字段（门槛/序列窗口），零代码改动。"""
    fields = set()
    for spec in DB_TRIALS:
        fields |= set(spec["overrides"])
    assert fields == {"resonanceMinMarketSampleCount", "resonanceMidWindowBars"}


def test_db_dose_axis_pairing():
    patches = {s["key"]: s["overrides"] for s in DB_TRIALS}
    assert patches["db_ms10"] == {"resonanceMinMarketSampleCount": 10}   # 回收 ×0.5
    assert patches["db_ms40"] == {"resonanceMinMarketSampleCount": 40}   # 收紧 ×2
    assert patches["db_mid6"] == {"resonanceMidWindowBars": 6}           # 降窗回收
    assert patches["db_mid10"] == {"resonanceMidWindowBars": 10}         # 加窗收紧


def test_dc_label_patches_and_expected_zero_effect():
    patches = {s["key"]: s["overrides"] for s in DC_TRIALS}
    assert patches["dc_label_x05"]["resonanceLabelThresholds"] == [42.5, 33.5, 25.0, 13.5]
    assert patches["dc_label_x2"]["resonanceLabelThresholds"] == [170.0, 134.0, 100.0, 54.0]
    assert patches["dc_weights_equal"]["resonanceWeights"] == [0.2, 0.2, 0.2, 0.2, 0.2]
    for spec in ALL_TRIALS:
        assert RankTrendConfig.from_patch(spec["overrides"]) is not None


def test_anchor_and_floor_constants():
    """锚单一源 = 注册表 currentGeneration（gen-2026-09-30-midlong-x30 三参组合四窗锚）。
    SA_COUNT_FLOOR 为 harness 强度样本下限常量，与引擎锚无关。"""
    from backend.operations.harness_common import baseline_anchor

    assert ANCHOR_BASELINE == baseline_anchor()[1]
    assert set(ANCHOR_BASELINE) >= {"decision", "oos1", "oos2"}
    assert SA_COUNT_FLOOR == 30


def test_assert_overrides_applied_rejects_unknown_field():
    """review C1：from_patch 对未知字段静默忽略——harness 必须逐键断言 override 生效。"""
    ok = RankTrendConfig.from_patch({"resonanceMidWindowBars": 6})
    _assert_overrides_applied(ok, {"resonanceMidWindowBars": 6})
    bad = RankTrendConfig.from_patch({"resonanceMidWindowBarsTypo": 6})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"resonanceMidWindowBarsTypo": 6})


def test_participation_rate():
    assert participation_of(["buy", "sell", "hold", ""]) == 0.5
    assert participation_of([]) is None


def test_zero_effect_check_requires_tiers_and_saex_dirs_diagnostic():
    base = {"signalTiers": ["A", "C"], "synergy": {"saEx": 0.1}, "resonanceDirections": ["buy", "hold"]}
    same = {"signalTiers": ["A", "C"], "synergy": {"saEx": 0.1}, "resonanceDirections": ["buy", "hold"]}
    dir_changed = {"signalTiers": ["A", "C"], "synergy": {"saEx": 0.1}, "resonanceDirections": ["hold", "buy"]}
    # tiers+saEx 一致 → zero_effect；dirs 一致性为诊断项（True）
    assert zero_effect_check(base, same)["verdict"] == "zero_effect_redundant"
    assert zero_effect_check(base, same)["resonanceDirectionsIdentical"] is True
    # dirs 不一致但 tiers+saEx 一致：代码事实兜底（weights/label 只进展示分）→ 仍判 zero_effect，诊断项 False
    assert zero_effect_check(base, dir_changed)["verdict"] == "zero_effect_redundant"
    assert zero_effect_check(base, dir_changed)["resonanceDirectionsIdentical"] is False
    # 缓存 baseline 缺 dirs 字段：诊断降级 None，不阻塞判定
    missing = {"signalTiers": ["A", "C"], "synergy": {"saEx": 0.1}}
    check = zero_effect_check(missing, same)
    assert check["resonanceDirectionsIdentical"] is None
    assert check["verdict"] == "zero_effect_redundant"


def test_zero_effect_tier_change_still_investigate():
    base = {"signalTiers": ["A", "C"], "synergy": {"saEx": 0.1}, "resonanceDirections": ["buy", "hold"]}
    tier_changed = {"signalTiers": ["B", "C"], "synergy": {"saEx": 0.1}, "resonanceDirections": ["buy", "hold"]}
    assert zero_effect_check(base, tier_changed)["verdict"] == "unexpected_effect"


def test_dc_summary_zero_effect_vs_investigate():
    def _result(part, tiers):
        return {"synergy": {"saEx": 0.1, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}, "signalTiers": tiers, "resonanceParticipation": part, "resonanceDirections": ["buy"] * len(tiers)}

    report = {
        win: {"trials": {
            "baseline": {"result": _result(0.44, ["A", "C", "C"])},
            "dc_x": {"result": _result(0.44, ["A", "C", "C"])},
        }}
        for win in ("decision", "oos1", "oos2")
    }
    summary = trial_summary(report, {"key": "dc_x", "group": "dc"})
    assert summary["dcVerdict"] == "zero_effect_redundant"

    report2 = {
        win: {"trials": {
            "baseline": {"result": _result(0.44, ["A", "C", "C"])},
            "dc_x": {"result": _result(0.44, ["B", "C", "C"])},
        }}
        for win in ("decision", "oos1", "oos2")
    }
    summary2 = trial_summary(report2, {"key": "dc_x", "group": "dc"})
    assert summary2["dcVerdict"] == "unexpected_effect_investigate"


def test_db_summary_card_and_next_gate():
    report = {
        "decision": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.10, "passHard": True, "distribution": {"S": 20, "A": 20, "C": 960}}, "resonanceParticipation": 0.40}},
            "db_ms10": {"result": {"synergy": {"saEx": 0.104, "passHard": True, "distribution": {"S": 25, "A": 25, "C": 950}}, "resonanceParticipation": 0.44}},
        }},
        "oos1": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 20, "A": 20, "C": 960}}, "resonanceParticipation": 0.40}},
            "db_ms10": {"result": {"synergy": {"saEx": 0.052, "passHard": True, "distribution": {"S": 25, "A": 25, "C": 950}}, "resonanceParticipation": 0.44}},
        }},
        "oos2": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 20, "A": 20, "C": 960}}, "resonanceParticipation": 0.40}},
            "db_ms10": {"result": {"synergy": {"saEx": 0.049, "passHard": True, "distribution": {"S": 25, "A": 25, "C": 950}}, "resonanceParticipation": 0.44}},
        }},
    }
    summary = trial_summary(report, {"key": "db_ms10", "group": "db"})
    assert summary["verdictCard"] == {"C1_decisionRelGE3pct": True, "C2_oosAnyPositive": True, "C3_decisionPassHard": True}
    assert summary["cardResult"] == "PASS_CANDIDATE"
    assert "票权三档交互表" in summary["nextGate"]
    win = summary["windows"]["decision"]
    assert win["saCountCollapse"] is False
    assert win["resonanceParticipation"] == 0.44


def test_sa_collapse_flag():
    report = {
        "decision": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.10, "passHard": True, "distribution": {"S": 20, "A": 20, "C": 960}}}},
            "db_tight": {"result": {"synergy": {"saEx": 0.10, "passHard": True, "distribution": {"S": 10, "A": 15, "C": 975}}}},
        }},
        "oos1": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 20, "A": 20, "C": 960}}}},
            "db_tight": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 10, "A": 15, "C": 975}}}},
        }},
        "oos2": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 20, "A": 20, "C": 960}}}},
            "db_tight": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 10, "A": 15, "C": 975}}}},
        }},
    }
    summary = trial_summary(report, {"key": "db_tight", "group": "db"})
    assert all(w["saCountCollapse"] is True for w in summary["windows"].values())  # S+A=25 < 30
