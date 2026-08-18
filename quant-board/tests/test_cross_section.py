# -*- coding: utf-8 -*-
"""crossSection（横截面相对强弱）观察因子测试。

设计（2026-08-17）：个股 avgRankNum 横截面 percentile 相对强弱——纯算法结构升级，
不进 synergy 投票（先验证区分度）。档位规则：
- A 强：percentile >= 85 且 delta >= 5（高位 + 上升）
- B 偏强：percentile >= 70 或 (percentile >= 50 且 delta >= 15)
- C 偏弱：percentile <= 30 或 (percentile <= 50 且 delta <= -15)
- D 弱：percentile <= 15 且 delta <= -5
- unknown：percentile 不可得（无 avgRankNum 过滤后不在横截面）
- 首帧缺 delta：降级绝对档（不给 A/D，delta 是 A/D 的必要确认）
"""
import pytest

from backend.analysis.ranktrend.cross_section import (
    CROSS_SECTION_DEFAULTS,
    compute_cross_section,
)
from backend.analysis.ranktrend.engine import RankTrendConfig


def cfg(**patch) -> RankTrendConfig:
    base = dict(RankTrendConfig().__dict__)
    base.update(patch)
    return RankTrendConfig(**base)


# ---------- 默认值契约（参数化，golden 不漂移） ----------

def test_cross_section_defaults_match_engine_config() -> None:
    c = RankTrendConfig()
    assert c.crossSectionStrongMin == CROSS_SECTION_DEFAULTS["crossSectionStrongMin"]
    assert c.crossSectionStrongDeltaUp == CROSS_SECTION_DEFAULTS["crossSectionStrongDeltaUp"]
    assert c.crossSectionWeakMax == CROSS_SECTION_DEFAULTS["crossSectionWeakMax"]
    assert c.crossSectionWeakDeltaDown == CROSS_SECTION_DEFAULTS["crossSectionWeakDeltaDown"]
    assert c.crossSectionStrongMin == 85.0
    assert c.crossSectionStrongDeltaUp == 5.0
    assert c.crossSectionWeakMax == 15.0
    assert c.crossSectionWeakDeltaDown == -5.0


# ---------- 档位判定 ----------

def test_tier_a_strong_high_and_rising() -> None:
    r = compute_cross_section(percentiles=[80.0, 88.0], market_median=50.0, config=cfg())
    assert r["signalTier"] == "A"
    assert r["percentile"] == pytest.approx(88.0)
    assert r["percentileDelta"] == pytest.approx(8.0)
    assert r["relativeToMarket"] == pytest.approx(38.0)
    assert any("高位" in x for x in r["tierReasons"])


def test_tier_b_mid_or_strong_delta() -> None:
    r = compute_cross_section(percentiles=[50.0, 72.0], market_median=50.0, config=cfg())
    assert r["signalTier"] == "B"
    r2 = compute_cross_section(percentiles=[30.0, 50.0], market_median=50.0, config=cfg())
    assert r2["signalTier"] == "B"  # delta=20 >= 15 → B
    assert r2["percentileDelta"] == pytest.approx(20.0)


def test_tier_c_weak_or_strong_drop() -> None:
    r = compute_cross_section(percentiles=[30.0, 28.0], market_median=50.0, config=cfg())
    assert r["signalTier"] == "C"
    r2 = compute_cross_section(percentiles=[60.0, 42.0], market_median=50.0, config=cfg())
    assert r2["signalTier"] == "C"  # delta=-18 <= -15 → C


def test_tier_d_weak_low_and_falling() -> None:
    r = compute_cross_section(percentiles=[20.0, 10.0], market_median=50.0, config=cfg())
    assert r["signalTier"] == "D"
    assert any("低位" in x for x in r["tierReasons"])


def test_first_frame_no_delta_downgrades_to_absolute() -> None:
    # 首帧（len==1）无 delta：不给 A/D（缺上升/下降确认），绝对档 B/C
    r_high = compute_cross_section(percentiles=[92.0], market_median=50.0, config=cfg())
    assert r_high["signalTier"] == "B"
    assert any("缺 delta" in x for x in r_high["tierReasons"])
    r_low = compute_cross_section(percentiles=[5.0], market_median=50.0, config=cfg())
    assert r_low["signalTier"] == "C"
    r_mid = compute_cross_section(percentiles=[50.0], market_median=50.0, config=cfg())
    assert r_mid["signalTier"] == "C"  # 中位默认偏弱（无上升证据不给 B）
    r_b = compute_cross_section(percentiles=[75.0], market_median=50.0, config=cfg())
    assert r_b["signalTier"] == "B"


def test_unknown_when_no_percentile() -> None:
    r = compute_cross_section(percentiles=[], market_median=50.0, config=cfg())
    assert r["signalTier"] == "unknown"
    assert any("横截面数据不足" in x for x in r["tierReasons"])


def test_market_median_missing_keeps_absolute_tier() -> None:
    # relativeToMarket 不可算时不阻断：percentile/delta 档位照常，relativeToMarket=None（fail-visible）
    r = compute_cross_section(percentiles=[70.0, 88.0], market_median=None, config=cfg())
    assert r["signalTier"] == "A"
    assert r["relativeToMarket"] is None
    assert any("市场 median 缺失" in x for x in r["tierReasons"])


# ---------- config 参数生效 ----------

def test_config_thresholds_effective() -> None:
    c = cfg(crossSectionStrongMin=90.0)
    r = compute_cross_section(percentiles=[80.0, 88.0], market_median=50.0, config=c)
    assert r["signalTier"] == "B"  # 88 < 90，A 门槛提高
    c2 = cfg(crossSectionStrongDeltaUp=10.0)
    r2 = compute_cross_section(percentiles=[80.0, 88.0], market_median=50.0, config=c2)
    assert r2["signalTier"] == "B"  # delta=8 < 10
