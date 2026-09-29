# -*- coding: utf-8 -*-
"""MA 因子贡献度 harness 前置修复测试（B-202610 阶段 0.4，审计 harness-audit-20260921 §7.2.2）。

审计要求：baseline desc 仍写"四因子"，但 maWeight=0.37 已于 §22.8 随 p2_aggressive 落默认
（五因子合同）——R3/R4 回退判读依赖 baseline 语义正确，须更正五因子口径。
同批补 from_patch override 生效性守卫（该 harness 走 from_patch 却无断言，范式 13 项之一）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_ma_factor_contribution import (
    TRIALS,
    WINDOWS,
    _assert_overrides_applied,
    run_window,
)


def test_baseline_desc_is_five_factor_generation():
    """baseline 即当前生产默认栈=五因子 p2_aggressive；desc 不得再写四因子（审计 B2 文档漂移）。"""
    assert getattr(RankTrendConfig(), "maWeight") == 0.37
    spec = next(s for s in TRIALS if s["key"] == "baseline")
    assert "四因子" not in spec["desc"]
    assert "五因子" in spec["desc"]
    assert spec["overrides"] == {}


def test_windows_oos2_legacy_truncation_annotated():
    """历史 oos2=09-01~09-12 截断口径必须在源码标注（audit §5.1/D1），防批次报告误读为全月。"""
    assert WINDOWS["oos2"] == ("2026-09-01", "2026-09-12")


def test_assert_overrides_applied_rejects_unknown_field():
    ok = RankTrendConfig.from_patch({"maWeight": 0.25})
    _assert_overrides_applied(ok, {"maWeight": 0.25})
    bad = RankTrendConfig.from_patch({"maWeightTypo": 0.25})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"maWeightTypo": 0.25})


def test_run_window_asserts_overrides_per_trial(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.operations.evaluate_ma_factor_contribution.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_ma_factor_contribution.subset_discrimination",
        lambda signals, frames: {"all": {}},
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_ma_factor_contribution.evaluate_gate",
        lambda config, frames: {
            "score": 0.0,
            "synergy": {"saEx": 0.1, "passHard": True},
            "rankTrend": {"saEx": None},
            "flipRates": {"veto": 0.0, "bd_downgrade": 0.0},
            "regimeView": {},
        },
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_ma_factor_contribution.TRIALS",
        [
            {"key": "baseline", "desc": "b", "overrides": {}},
            {"key": "typo_arm", "desc": "t", "overrides": {"maWeightTypo": 0.25}},
        ],
    )
    report = {"__out__": str(tmp_path / "m.json")}
    with pytest.raises(AssertionError, match="override 未生效"):
        run_window("decision", report, skip_trials=False)


def test_run_window_full_trials_pass(monkeypatch, tmp_path):
    """合法 TRIALS 全量跑通：subsets + trials 均执行，守卫不误伤。"""
    monkeypatch.setattr(
        "backend.operations.evaluate_ma_factor_contribution.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_ma_factor_contribution.subset_discrimination",
        lambda signals, frames: {"all": {}, "eventOverlapRawCounts": {"totalSignals": 0}},
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_ma_factor_contribution.evaluate_gate",
        lambda config, frames: {
            "score": 0.0,
            "synergy": {"saEx": 0.1, "passHard": True},
            "rankTrend": {"saEx": None},
            "flipRates": {"veto": 0.0, "bd_downgrade": 0.0},
            "regimeView": {},
        },
    )
    report = {"__out__": str(tmp_path / "m.json")}
    run_window("decision", report, skip_trials=False)
    entry = report["decision"]
    assert set(entry["trials"]) == {s["key"] for s in TRIALS}
    assert "all" in entry["subsets"]
