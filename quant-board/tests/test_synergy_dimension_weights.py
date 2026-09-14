# -*- coding: utf-8 -*-
"""synergy 维度票权重参数化锚点测试（2026-09-14，阶段 23 追问后续：维度权重实证前置）。

背景：_synergy_tier 的 v = res票 + rank票 + vp票 + cs票，res/rank/vp 权重硬编码 1.0
（volume_price.py:339，无维度级权重扫描记录）。本改动把三维权重参数化：
tierSynergyResonanceVote / tierSynergyRankVote / tierSynergyVolumePriceVote，
默认值 = 1.0（与硬编码行为逐位一致）；2026-09-14 用户决策采纳 combo_three_quarter 后 res/rank/cs 默认 0.75、vp 1.0（见 test_dimension_vote_weight_defaults_are_adopted_values）。

事实修正注记（2026-09-14 复核）：共振维自阶段 3 修复方向 1 起已在 replay 投票
（rankTrend.resonance 每信号产出，market_ctx 每帧构造）——tier_monotonicity.py
头部"replay 链路缺共振维"为阶段 3 时期旧口径。
"""
from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.ranking.volume_price import _synergy_tier

DIM_VOTE_FIELDS = (
    "tierSynergyResonanceVote",
    "tierSynergyRankVote",
    "tierSynergyVolumePriceVote",
    "tierSynergyCrossSectionVote",
)


def _tier_with(res=("S", "buy"), rank=("A", "buy"), vp=("D", "down"), cs="A", config=None):
    return _synergy_tier(
        res[0], res[1],
        rank[0], rank[1],
        vp[0], vp[1],
        "C",
        config,
        cs_tier=cs,
    )


# ---------------------------------------------------------------------------
# 默认值锚（golden 不漂移：默认参数被意外改动时此处先红）
# ---------------------------------------------------------------------------


def test_dimension_vote_weight_defaults_are_adopted_values() -> None:
    """默认值锚 = combo_three_quarter 采纳口径（阶段 23.9 用户决策 2026-09-14）。"""
    c = RankTrendConfig()
    assert c.tierSynergyResonanceVote == pytest.approx(0.75)
    assert c.tierSynergyRankVote == pytest.approx(0.75)
    assert c.tierSynergyVolumePriceVote == pytest.approx(1.0)
    assert c.tierSynergyCrossSectionVote == pytest.approx(0.75)


def test_default_config_equals_combo_three_quarter_adoption_anchor() -> None:
    """采纳锚：默认构造 ≡ from_patch(combo_three_quarter 实证口径)——端到端复现前提。"""
    combo_patch = {
        "tierSynergyResonanceVote": 0.75,
        "tierSynergyRankVote": 0.75,
        "tierSynergyCrossSectionVote": 0.75,
    }
    default = RankTrendConfig()
    patched = RankTrendConfig.from_patch(combo_patch)
    for field in DIM_VOTE_FIELDS:
        assert getattr(default, field) == pytest.approx(getattr(patched, field)), field


def test_default_weights_reproduce_adopted_vote_arithmetic() -> None:
    """默认权重下 _synergy_tier 输出与采纳口径算术逐位一致。

    v = res S买 0.9(1.2×0.75) + rank A买 0.75 + vp D跌 −1.0(×1.0) + cs A 0.75 = 1.4 → B。
    """
    tier, reasons = _tier_with()
    assert tier == "B"
    # 去 cs（权重 0 的既有路径）后 v = 0.9 + 0.75 − 1.0 = 0.65 → C
    tier_b, _ = _tier_with(cs=None)
    assert tier_b == "C"


def test_weight_zero_disables_dimension_vote() -> None:
    """权重 0 = 该维归零（与硬编码时代 monkeypatch 归零语义等价，可配置化）。"""
    c = RankTrendConfig.from_patch({"tierSynergyRankVote": 0.0})
    tier, _ = _tier_with(config=c)  # v = 0.9 − 1.0 + 0.75 = 0.65 → C
    assert tier == "C"
    c2 = RankTrendConfig.from_patch({"tierSynergyVolumePriceVote": 0.0})
    tier2, _ = _tier_with(config=c2)  # v = 0.9 + 0.75 + 0.75 = 2.4 → A
    assert tier2 == "A"
    c3 = RankTrendConfig.from_patch({"tierSynergyResonanceVote": 0.0})
    tier3, _ = _tier_with(config=c3)  # v = 0.75 − 1.0 + 0.75 = 0.5 → C
    assert tier3 == "C"


def test_weight_scaling_moves_tier_boundary() -> None:
    """权重上探：rank ×2 时 v = 0.9 + 2.0 − 1.0 + 0.75 = 2.65 → A（剂量可调）。"""
    c = RankTrendConfig.from_patch({"tierSynergyRankVote": 2.0})
    tier, _ = _tier_with(config=c)
    assert tier == "A"


def test_negative_vote_weights_rejected() -> None:
    """负权重拒绝（fail-fast，负值会翻转票向扭曲合成）。"""
    with pytest.raises(ValueError):
        RankTrendConfig.from_patch({"tierSynergyRankVote": -0.5})
    with pytest.raises(ValueError):
        RankTrendConfig.from_patch({"tierSynergyResonanceVote": -0.1})
    with pytest.raises(ValueError):
        RankTrendConfig.from_patch({"tierSynergyVolumePriceVote": -1.0})
    with pytest.raises(ValueError):
        RankTrendConfig.from_patch({"tierSynergyCrossSectionVote": -0.5})
