# -*- coding: utf-8 -*-
"""环境门干预形态 harness 测试（阶段 24）：trial 定义完整性 + 锚链/C5/判定卡纯逻辑。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_lifecycle_gate_form import (
    ALL_TRIALS,
    ANCHOR_GATE_OFF_OLD,
    ANCHOR_NEW_BASELINE,
    ANCHOR_OLD_BASELINE,
    ANCHOR_TRIALS,
    DOSE_TRIALS,
    VP_CONSERVATION_TRIALS,
    anchor_check,
    conservation_stats,
    trial_summary,
)


def test_trial_keys_unique():
    keys = [s["key"] for s in ALL_TRIALS]
    assert len(keys) == len(set(keys))


def test_anchor_constants_match_phased_docs():
    assert ANCHOR_NEW_BASELINE == {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}  # 23.9.1
    assert ANCHOR_OLD_BASELINE == {"decision": 0.0939, "oos1": 0.0854, "oos2": 0.0737}  # 22.8
    assert ANCHOR_GATE_OFF_OLD == {"decision": 0.0366, "oos1": 0.0437, "oos2": 0.0373}  # 23.8 no_lc_gate


def test_anchor_trials_declare_expected_anchors():
    declared = {s["key"]: s.get("anchor") for s in ANCHOR_TRIALS}
    assert declared["a0_baseline"] == ANCHOR_NEW_BASELINE
    assert declared["a1_old_baseline"] == ANCHOR_OLD_BASELINE
    assert declared["a2_gate_off_old"] == ANCHOR_GATE_OFF_OLD
    assert declared["a3_gate_off_new"] is None


def test_all_trial_patches_construct_valid_configs():
    for spec in ALL_TRIALS:
        config = RankTrendConfig.from_patch(spec["overrides"])  # 非法枚举/负值在此抛错
        assert config is not None


def test_dose_axis_covers_audit_values():
    strengths = [s["overrides"]["lifecycleVetoVoteStrength"] for s in DOSE_TRIALS]
    assert strengths == [0.375, 0.75, 1.5, 2.25]


def test_anchor_check_round4_match():
    assert anchor_check("decision", 0.10440, {"decision": 0.1044})["match"] is True
    assert anchor_check("decision", 0.1044, None)["checked"] is False
    assert anchor_check("decision", None, {"decision": 0.1044})["match"] is False
    assert anchor_check("decision", 0.1045, {"decision": 0.1044})["match"] is False


def test_conservation_zero_violation_on_untouched_frames():
    base = ["A", "S", "C", "B", "E", "D"]
    trial = ["A", "S", "C", "A", "C", "B"]  # B/E/D 帧翻转 = 处理效应；其余零翻转
    stats = conservation_stats(base, trial, ["C", "C", "A", "B", "E", "D"], ["A"] * 6, include_vp=False)
    assert stats["violated"] is False
    assert stats["checked"] == 3


def test_conservation_counts_violation_in_protected_zone():
    base = ["A", "C"]
    trial = ["B", "C"]  # 保护区帧翻转 → 违反
    stats = conservation_stats(base, trial, ["C", "A"], ["A", "A"], include_vp=False)
    assert stats["violated"] is True
    assert stats["violations"] == 1


def test_conservation_vp_mask_for_e_trials():
    base = ["A", "A", "S"]
    trial = ["A", "C", "S"]  # 帧 1 vp=E：e 组豁免；帧 0/2 必须守恒
    stats = conservation_stats(base, trial, ["C"] * 3, ["A", "E", "C"], include_vp=True)
    assert stats["violated"] is False
    assert stats["checked"] == 2


def test_conservation_length_mismatch_reported_not_faked():
    stats = conservation_stats(["A"], [], ["C"], ["A"], include_vp=False)
    assert stats["violated"] is True
    assert stats["violations"] is None


def test_trial_summary_verdict_card():
    def _win_report(sa, base_sa, pass_hard):
        return {"synergy": {"saEx": sa, "passHard": pass_hard, "distribution": {"S": 10, "A": 10, "C": 80}}}

    report = {
        "decision": {"trials": {
            "a0_baseline": {"result": _win_report(0.10, 0, True)},
            "t_x": {"result": _win_report(0.104, 0, True)},  # rel +4% ≥ 3%
        }},
        "oos1": {"trials": {
            "a0_baseline": {"result": _win_report(0.05, 0, True)},
            "t_x": {"result": _win_report(0.051, 0, True)},  # +2% 正
        }},
        "oos2": {"trials": {
            "a0_baseline": {"result": _win_report(0.05, 0, True)},
            "t_x": {"result": _win_report(0.049, 0, True)},  # −2% 负
        }},
    }
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["verdictCard"] == {"C1_decisionRelGE3pct": True, "C2_oosAnyPositive": True, "C3_decisionPassHard": True}
    assert summary["cardResult"] == "PASS_CANDIDATE"
    assert summary["windows"]["decision"]["triggerRateSA"] == 0.2


def test_vp_trials_flagged_for_vp_conservation():
    assert {s["key"] for s in ALL_TRIALS if s["key"] in VP_CONSERVATION_TRIALS} == {"e1a_vp_off", "e1b_vp_soft"}


@pytest.mark.parametrize("key", ["b0_soft_veto_0375", "b3_soft_veto_225", "c1_downgrade_off", "d1_reversal_hard", "d2_highrisk_hard"])
def test_conservation_trials_registered(key):
    from backend.operations.evaluate_lifecycle_gate_form import CONSERVATION_TRIALS

    assert key in CONSERVATION_TRIALS


def test_conservation_scope_auto_detection():
    from backend.operations.evaluate_lifecycle_gate_form import conservation_scope

    assert conservation_scope({"lifecycleVetoGateMode": "soft"}) == (True, False)
    assert conservation_scope({"lifecycleDowngradeGateMode": "soft", "lifecycleDowngradePenalty": 1.0}) == (True, False)
    assert conservation_scope({"volumePriceGateMode": "off"}) == (False, True)
    assert conservation_scope({"volumePriceGateMode": "off", "lifecycleVetoGateMode": "soft"}) == (True, True)
    assert conservation_scope({}) == (False, False)


def test_conservation_not_applicable_for_weight_mismatch_anchor_trials():
    """票权口径与 a0 不同的锚 trial（a1/a2）：守恒显式标 N/A，不产出伪 violations。"""

    def _win_report(sa: float) -> dict:
        return {"synergy": {"saEx": sa, "passHard": True, "distribution": {"C": 100}}}

    report = {
        w: {
            "trials": {
                "a0_baseline": {"result": _win_report(0.10)},
                "a1_old_baseline": {"result": _win_report(0.09)},
                "a2_gate_off_old": {"result": _win_report(0.04)},
            }
        }
        for w in ("decision", "oos1", "oos2")
    }
    for key in ("a1_old_baseline", "a2_gate_off_old"):
        spec = next(s for s in ANCHOR_TRIALS if s["key"] == key)
        summary = trial_summary(report, spec)
        for w in ("decision", "oos1", "oos2"):
            cons = summary["windows"][w]["conservation"]
            assert cons["skipped"] is True
            assert "票权口径" in cons["note"]
