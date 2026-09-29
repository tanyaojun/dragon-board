# -*- coding: utf-8 -*-
"""核心信号参数扫描 harness 前置修复测试（B-202610 阶段 0.4，审计 harness-audit-20260921 §7.2.3）。

审计 FAIL（b 类）：_fmt 在 focus_dim="volumePrice" 时打印 result["resonance"] 冒充，
且 evaluate 返回体缺 volumePrice 键——量价维 trial 的日志/摘要全部错位。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.optimize_core_signal_parameters import _fmt, evaluate


def _full_result() -> dict:
    return {
        "score": 1.0,
        "synergy": {"saEx": 0.1, "passHard": True},
        "rankTrend": {"saEx": 0.2, "passHard": True, "unknownRate": 0.0},
        "resonance": {"saEx": 0.3, "passHard": True, "unknownRate": 0.0},
        "volumePrice": {"saEx": 0.4, "passHard": False, "unknownRate": 0.0},
        "signalCount": 1,
    }


def test_evaluate_returns_volume_price_key(monkeypatch):
    """evaluate 返回体必须含 focus 维全集（rankTrend/resonance/volumePrice），不丢量价摘要。"""
    monkeypatch.setattr(
        "backend.operations.optimize_core_signal_parameters.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, window_size=50: []),
    )
    monkeypatch.setattr(
        "backend.operations.optimize_core_signal_parameters.tier_forward_returns",
        lambda signals, frames, horizon, dimension: {"tiers": {}, "unknownRate": 0.0},
    )
    monkeypatch.setattr(
        "backend.operations.optimize_core_signal_parameters.sa_excess_of",
        lambda stats: 0.05,
    )
    monkeypatch.setattr(
        "backend.operations.optimize_core_signal_parameters._tier_summary",
        lambda stats: {"saEx": 0.05, "passHard": True},
    )
    result = evaluate(RankTrendConfig(), [], "volumePrice")
    for key in ("score", "synergy", "rankTrend", "resonance", "volumePrice", "signalCount"):
        assert key in result, f"evaluate 返回缺 {key} 键"


def test_fmt_volume_price_not_masqueraded():
    """focus_dim=volumePrice 必须打印量价维读数（旧 bug：打印 resonance 的 saEx 冒充）。"""
    line = _fmt(_full_result(), "volumePrice")
    assert "volumePrice" in line
    assert "0.4" in line
    assert "0.3" not in line  # resonance 读数不得混入


def test_fmt_focus_dimensions_all_supported():
    for dim, sa_ex in (("rankTrend", "0.2"), ("resonance", "0.3")):
        assert sa_ex in _fmt(_full_result(), dim)


def test_fmt_fail_fast_on_missing_key():
    """缺键 fail-fast：旧缓存报告缺 volumePrice 摘要时显式报错，不许静默用别的维度顶替。"""
    legacy = {"score": 1.0, "synergy": {}, "rankTrend": {"saEx": 0.2}, "resonance": {"saEx": 0.3}, "signalCount": 1}
    with pytest.raises(KeyError, match="volumePrice"):
        _fmt(legacy, "volumePrice")


def test_fmt_fail_fast_on_unknown_dimension():
    with pytest.raises(KeyError, match="focus_dim"):
        _fmt(_full_result(), "resonanceTypo")
