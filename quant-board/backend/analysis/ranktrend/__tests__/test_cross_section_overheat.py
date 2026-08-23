# -*- coding: utf-8 -*-
"""analyze_cross_section_overheat 纯函数单测（crossSection 追强 × ATR 波动过热/超卖回归校准）。

观察信号，不进 synergy。详见 docs/ranktrend-percentile-atr-fusion-signal-design.md §3/§4。
"""
import pytest

from backend.analysis.ranktrend.cross_section_vol_overheat import analyze_cross_section_overheat


class _C:
    crossVolP33 = 0.33
    crossVolP67 = 0.67
    crossVolP90 = 0.90


def test_strong_deep_overheat_is_sell_s():
    r = analyze_cross_section_overheat("A", 0.95, _C())
    assert r["direction"] == "sell" and r["signalTier"] == "S"


def test_strong_high_vol_is_overheat():
    r = analyze_cross_section_overheat("B", 0.8, _C())
    assert r["direction"] == "sell" and r["signalTier"] == "C"


def test_strong_mid_vol_is_warm():
    r = analyze_cross_section_overheat("A", 0.5, _C())
    assert r["direction"] == "sell" and r["signalTier"] == "B"


def test_strong_low_vol_is_mild():
    r = analyze_cross_section_overheat("A", 0.1, _C())
    assert r["direction"] == "hold" and r["signalTier"] == "A"


def test_weak_low_vol_is_rebound():
    r = analyze_cross_section_overheat("D", 0.1, _C())
    assert r["direction"] == "buy" and r["signalTier"] == "B"


def test_weak_high_vol_is_stay_away():
    r = analyze_cross_section_overheat("D", 0.9, _C())
    assert r["direction"] == "hold" and r["signalTier"] == "C"


def test_unknown_input_is_fail_visible():
    r = analyze_cross_section_overheat("unknown", 0.5, _C())
    assert r["status"] == "insufficient" and r["signalTier"] == "unknown"
    r2 = analyze_cross_section_overheat("A", None, _C())
    assert r2["status"] == "insufficient" and r2["signalTier"] == "unknown"
