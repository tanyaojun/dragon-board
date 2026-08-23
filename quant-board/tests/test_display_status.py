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


# 前端 UI 样式 classKey 白名单（src/components/panels/RankTrendPanel.vue .hero-card.tier-*
# 与 statusClassifier.ts 兜底名）。后端 classKey 必须落在此集合内，否则样式丢失（口径漂移）。
_UI_KNOWN_KEYS = {
    "main_confirmed",
    "ignition_watch",
    "weakening",
    "new_watch",
    "crowded",
    "money_divergence",
    "strong_money",  # G2 补充：强资确认（前端 UI .hero-card.tier-strong_money 存在）
    "insufficient",
}


def test_classkey_aligned_with_frontend_ui_whitelist():
    cases = [
        compute_display_status(_analysis(sample_status="insufficient", tier="A_MAIN"), {}),
        compute_display_status(_analysis(tier="D_EXIT_RISK"), {}),
        compute_display_status(_analysis(tier="C_CROWDED"), {}),
        compute_display_status(_analysis(tier="A_MAIN"), {}),
        compute_display_status(_analysis(tier="B_IGNITION"), {}),
        compute_display_status(_analysis(synergy_state="启动确认"), {}),
        compute_display_status(_analysis(synergy_state="风险升级"), {}),
        compute_display_status(_analysis(synergy_state="存疑"), {"zljzb": -5.0}),
        compute_display_status(_analysis(synergy_state="主升确认"), {}),
    ]
    for case in cases:
        assert case["classKey"] in _UI_KNOWN_KEYS, f"classKey {case['classKey']} 不在前端 UI 白名单"


def test_strong_money_when_strong_fund_and_volume_supported():
    a = _analysis(sample_status="ok", synergy_state="主升确认")
    a["observation"]["volumePrice"] = {"signalTier": "A"}
    r = compute_display_status(a, {"zlje": 1e8, "zljzb": 12.0})
    assert r["label"] == "强资确认"
    assert r["classKey"] == "strong_money"
    # 量能承接 B 档（放量上涨量价配合）也产强资确认
    a["observation"]["volumePrice"] = {"signalTier": "B"}
    assert compute_display_status(a, {"zlje": 1e8, "zljzb": 12.0})["classKey"] == "strong_money"


def test_strong_money_not_with_weak_volume_or_fund():
    a = _analysis(sample_status="ok", synergy_state="主升确认")
    a["observation"]["volumePrice"] = {"signalTier": "D"}
    # 量能走弱（D）→ 不产强资确认
    assert compute_display_status(a, {"zlje": 1e8, "zljzb": 12.0})["classKey"] != "strong_money"
    # 资金流出 → 不产强资确认
    a["observation"]["volumePrice"] = {"signalTier": "A"}
    assert compute_display_status(a, {"zlje": -1e8, "zljzb": -5})["classKey"] != "strong_money"
