# -*- coding: utf-8 -*-
"""display_status 后端状态分类单测（2026-08-23 前后端分离 G2）。"""
from backend.analysis.ranktrend.display_status import compute_display_status


def _analysis(sample_status="ok", tier=None, synergy_state=None):
    return {
        "meta": {"sampleStatus": sample_status},
        "strategy": {"candidateTier": tier} if tier else {},
        "observation": {"synergy": {"state": synergy_state}},
    }


def test_sample_insufficient_priority():
    r = compute_display_status(_analysis(sample_status="insufficient", tier="A_MAIN", synergy_state="主升确认"), {})
    assert r["label"] == "样本不足"


def test_tier_branch():
    assert compute_display_status(_analysis(tier="D_EXIT_RISK"), {})["label"] == "转弱预警"
    assert compute_display_status(_analysis(tier="C_CROWDED"), {})["label"] == "高位拥挤"
    assert compute_display_status(_analysis(tier="A_MAIN"), {})["label"] == "主升确认"
    assert compute_display_status(_analysis(tier="B_IGNITION"), {})["label"] == "点火观察"


def test_synergy_state_branch():
    assert compute_display_status(_analysis(synergy_state="启动确认"), {})["label"] == "点火观察"
    assert compute_display_status(_analysis(synergy_state="风险升级"), {})["label"] == "转弱预警"


def test_money_divergence_when_synergy_stuck_and_outflow():
    r = compute_display_status(_analysis(synergy_state="存疑"), {"zljzb": -5.0})
    assert r["label"] == "资金背离"


def test_default_when_no_signal():
    r = compute_display_status(_analysis(synergy_state="主升确认"), {})
    # synergy 主升确认但无 candidateTier → 兜底新入观察（后端未给 tier 时不放大）
    assert r["label"] in ("新入观察", "主升确认")
