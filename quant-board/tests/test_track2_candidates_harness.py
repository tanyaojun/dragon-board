# -*- coding: utf-8 -*-
"""Track 2 统一判定 harness 前置修复测试（B-202610 阶段 0.4，审计 harness-audit-20260921 §7.2.1）。

审计三项要求：① 补 baseline 锚（gen-2026-10-b202610）；② 补 _assert_overrides_applied 逐键断言；
③ fund10 已落默认（config 10.0=现值），fund10_over2 trial 的 fund 轴不再是扰动轴——重定义扰动轴，
并按观察池 O2 baselineNote 增设 fund10 回退口径对照臂。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_track2_candidates import (
    BASELINE_ANCHORS,
    COMBO_PARTS,
    P1_OVERRIDES,
    TRIALS,
    _assert_baseline_anchor,
    _assert_overrides_applied,
    run_window,
)


def _gate_result(sa_ex: float) -> dict:
    return {
        "score": 0.5,
        "synergy": {"saEx": sa_ex, "passHard": True},
        "rankTrend": {"saEx": sa_ex},
        "flipRates": {"veto": 0.01, "bd_downgrade": 0.01},
        "regimeView": {},
    }


def test_fund_axis_no_longer_a_perturbation_axis():
    """fund10 已于 2026-09-15 落默认（AbnormalFundRatio=10.0），fund10_over2 不得再把该轴当扰动。"""
    assert getattr(RankTrendConfig(), "volumePriceAbnormalFundRatio") == 10.0
    spec = next(s for s in TRIALS if s["key"] == "fund10_over2")
    assert "volumePriceAbnormalFundRatio" not in spec["overrides"], "fund 轴已落默认，写入 overrides 只会误导判定卡"
    assert spec["overrides"] == {"volumePriceOverVolumeRatio": 2.0}


def test_fund10_revert_control_arm_present():
    """O2 对照基线必须显式声明为 fund10 回退口径（observation-pool O2 baselineNote / rerun-plan §4 阶段 3）。"""
    spec = next(s for s in TRIALS if s["key"] == "fund10_revert")
    assert spec["overrides"] == {"volumePriceAbnormalFundRatio": 20.0}


def test_p1_combo_drops_fund_axis():
    """combo 组合定义相对当前默认栈：fund10 已在栈内，P1_OVERRIDES 只保留真实扰动轴。"""
    assert "volumePriceAbnormalFundRatio" not in P1_OVERRIDES
    assert set(P1_OVERRIDES) == {"volumePriceOverVolumeRatio", "jumpDeltaPct", "tierResonanceJumpFreshnessMin"}
    combo = next(s for s in TRIALS if s["key"] == "combo_p1")
    assert combo["overrides"] == dict(P1_OVERRIDES)
    assert COMBO_PARTS["combo_p1"] == ["fund10_over2", "jump25_fresh06"]


def test_baseline_anchor_constant_gen_2026_10():
    """锚代际 gen-2026-10-b202610（config/ranktrend-anchors.json，2026-09-16 预建）；oos2/oos2u 待批次填充。"""
    assert BASELINE_ANCHORS == {"decision": 0.1323, "oos1": 0.0862, "oos2": None, "oos2u": None}


def test_baseline_anchor_drift_raises():
    """锚 trial 级即时 raise：漂移=代际/config 污染，不许带病出判定卡；未建锚窗口不校验。"""
    _assert_baseline_anchor("decision", 0.1323)
    _assert_baseline_anchor("oos1", 0.0862)
    _assert_baseline_anchor("oos2u", None)  # 锚为 None：跳过
    with pytest.raises(AssertionError, match="锚漂移"):
        _assert_baseline_anchor("decision", 0.1300)
    with pytest.raises(AssertionError, match="锚漂移"):
        _assert_baseline_anchor("oos1", None)


def test_assert_overrides_applied_rejects_unknown_field():
    """from_patch 对未知字段静默忽略——逐键断言拦截字段拼错误跑成 baseline 复刻。"""
    ok = RankTrendConfig.from_patch({"volumePriceOverVolumeRatio": 2.0})
    _assert_overrides_applied(ok, {"volumePriceOverVolumeRatio": 2.0})
    bad = RankTrendConfig.from_patch({"volumePriceOverVolumeRatioTypo": 2.0})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"volumePriceOverVolumeRatioTypo": 2.0})


def test_run_window_baseline_anchor_drift_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.operations.evaluate_track2_candidates.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_track2_candidates.evaluate_gate",
        lambda config, frames: _gate_result(0.9999),
    )
    report = {"__out__": str(tmp_path / "t2.json")}
    with pytest.raises(AssertionError, match="锚漂移"):
        run_window("decision", report)


def test_run_window_asserts_overrides_per_trial(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.operations.evaluate_track2_candidates.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_track2_candidates.evaluate_gate",
        lambda config, frames: _gate_result(0.1323),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_track2_candidates.TRIALS",
        [
            {"key": "baseline", "desc": "b", "overrides": {}},
            {"key": "typo_arm", "desc": "t", "overrides": {"tierSynergyVoteStrengthsTypo": 0.7}},
        ],
    )
    report = {"__out__": str(tmp_path / "t2.json")}
    with pytest.raises(AssertionError, match="override 未生效"):
        run_window("decision", report)


def test_run_window_full_trials_pass_and_cache(monkeypatch, tmp_path):
    """合法 TRIALS 全量跑通：守卫不误伤，trial 结果与 overrides 进缓存报告。"""
    calls: list[str] = []

    def gate(config, frames):
        calls.append("gate")
        return _gate_result(0.1323)

    monkeypatch.setattr(
        "backend.operations.evaluate_track2_candidates.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr("backend.operations.evaluate_track2_candidates.evaluate_gate", gate)
    report = {"__out__": str(tmp_path / "t2.json")}
    run_window("decision", report)
    trials = report["decision"]["trials"]
    assert set(trials) == {s["key"] for s in TRIALS}
    assert trials["fund10_over2"]["overrides"] == {"volumePriceOverVolumeRatio": 2.0}
    assert len(calls) == len(TRIALS)
    # resume：已缓存 trial 不重跑
    run_window("decision", report)
    assert len(calls) == len(TRIALS)
