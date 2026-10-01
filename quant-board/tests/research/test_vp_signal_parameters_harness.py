# -*- coding: utf-8 -*-
"""vp 量价维信号参数再审视 harness 测试（方案 C，§4 审计条款落实断言）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_vp_signal_parameters import (
    ANCHOR_BASELINE,
    CA_TRIALS,
    CB_TRIALS,
    DOWN_FAMILY,
    DTH_DEFAULT,
    FUND_FAMILY,
    UP_FAMILY,
    _assert_overrides_applied,
    _scale_family,
    _scale_list,
    family_verdict,
    trial_summary,
)


def test_families_match_config_defaults():
    """家族枚举与 config 默认值逐一对应（config.py:166-190 批 2）——枚举漏字段即此测试失败。"""
    config = RankTrendConfig()
    for family in (UP_FAMILY, DOWN_FAMILY, FUND_FAMILY):
        for field, default in family.items():
            assert abs(float(getattr(config, field)) - default) < 1e-9, f"{field} 默认值漂移"
    assert list(_scale_list(DTH_DEFAULT, 1.0)) == list(config.volumePriceDirectionThresholds)


def test_family_counts_match_doc():
    assert len(UP_FAMILY) == 14
    assert len(DOWN_FAMILY) == 4
    assert len(FUND_FAMILY) == 5
    assert len(DTH_DEFAULT) == 6


def test_ca_patches_match_doc_values():
    """C-a trial 与 §4.2 表逐一对应：fund10/over2/fund10+over2/mild115。"""
    patches = {s["key"]: s["overrides"] for s in CA_TRIALS}
    assert patches["fund10"] == {"volumePriceAbnormalFundRatio": 10.0}
    assert patches["over2"] == {"volumePriceOverVolumeRatio": 2.0}
    assert patches["fund10_over2"] == {"volumePriceAbnormalFundRatio": 10.0, "volumePriceOverVolumeRatio": 2.0}
    assert patches["mild115"] == {"volumePriceMildRatio": 1.15}


def test_cb_windows_decision_only():
    """C-b 家族探针只跑 decision 窗（§4.2：分组不需三窗）。"""
    for spec in CB_TRIALS:
        assert spec["windows"] == ("decision",)


def test_all_patches_construct_valid_configs():
    for spec in (*CA_TRIALS, *CB_TRIALS):
        assert RankTrendConfig.from_patch(spec["overrides"]) is not None


def test_scale_helpers_negative_values_and_rounding():
    assert _scale_family(DOWN_FAMILY, 0.5)["volumeScoreDownOverMild"] == -10.0
    assert _scale_family(DOWN_FAMILY, 2.0)["volumeScoreDownOverMild"] == -40.0
    assert _scale_list([7.0, 0.5], 0.5) == [3.5, 0.25]
    assert _scale_list([7.0, 5.0], 2.0) == [14.0, 10.0]


def test_family_probe_changes_only_own_fields():
    """家族探针不越界：up 探针不得动 fund/down/dth 字段。"""
    up_patch = _scale_family(UP_FAMILY, 0.5)
    assert not any(k.startswith("fundScore") for k in up_patch)
    assert not any(k.startswith("volumeScoreDown") for k in up_patch)
    assert "volumePriceDirectionThresholds" not in up_patch


def test_family_verdict_zero_effect_requires_both():
    base = {"signalTiers": ["A", "C"], "synergy": {"saEx": 0.1044}}
    same = {"signalTiers": ["A", "C"], "synergy": {"saEx": 0.1044}}
    changed_tier = {"signalTiers": ["B", "C"], "synergy": {"saEx": 0.1044}}
    changed_sa = {"signalTiers": ["A", "C"], "synergy": {"saEx": 0.11}}
    assert family_verdict(base, same)["verdict"] == "zero_effect_redundant"
    assert family_verdict(base, changed_tier)["verdict"] == "active"
    assert family_verdict(base, changed_sa)["verdict"] == "active"


def test_anchor_constant():
    """锚单一源：ANCHOR_BASELINE = 注册表 currentGeneration（gen-2026-09-30-midlong-x30 三参组合四窗锚），
    不再锁 fund10 字面量代际。"""
    from backend.operations.harness_common import baseline_anchor

    assert ANCHOR_BASELINE == baseline_anchor()[1]
    assert set(ANCHOR_BASELINE) >= {"decision", "oos1", "oos2"}


def test_cb_summary_reports_family_verdict():
    report = {
        "decision": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.1044, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}, "signalTiers": ["A", "C"]}},
            "fam_x": {"result": {"synergy": {"saEx": 0.1044, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}, "signalTiers": ["A", "C"]}},
        }},
    }
    summary = trial_summary(report, {"key": "fam_x", "windows": ("decision",)}, "cb")
    assert summary["familyVerdict"] == "zero_effect_redundant"


def test_ca_summary_card_and_fund10_over2_note():
    report = {
        "decision": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.10, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "fund10": {"result": {"synergy": {"saEx": 0.104, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
        }},
        "oos1": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "fund10": {"result": {"synergy": {"saEx": 0.052, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
        }},
        "oos2": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "fund10": {"result": {"synergy": {"saEx": 0.049, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
        }},
    }
    summary = trial_summary(report, {"key": "fund10", "windows": ("decision", "oos1", "oos2")}, "ca")
    assert summary["verdictCard"] == {"C1_decisionRelGE3pct": True, "C2_oosAnyPositive": True, "C3_decisionPassHard": True}
    assert "fund10+over2" in summary["note"]


def test_assert_overrides_applied_rejects_unknown_field():
    """review C1：from_patch 对未知字段静默忽略——harness 必须逐键断言 override 生效。"""
    ok = RankTrendConfig.from_patch({"volumePriceBase": 51.0})
    _assert_overrides_applied(ok, {"volumePriceBase": 51.0})
    bad = RankTrendConfig.from_patch({"volumePriceBaseTypo": 51.0})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"volumePriceBaseTypo": 51.0})
