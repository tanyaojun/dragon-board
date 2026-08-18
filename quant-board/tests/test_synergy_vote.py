# -*- coding: utf-8 -*-
"""synergy 档位投票单元测试（golden 补强，2026-08-17 用户反馈 golden 形同虚设）。

直接调用 _synergy_tier 断言档位——覆盖 G2 crossSection 第 5 维投票默认打开的行为，
防止算法变更悄悄漂移（此前 golden 测试无 synergy 档位断言）。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.volume_price import _synergy_tier


def cfg(**patch) -> RankTrendConfig:
    base = dict(RankTrendConfig().__dict__)
    base.update(patch)
    return RankTrendConfig(**base)


def syn(res_tier="B", rank_tier="B", vp_tier="B", lc_tier="A", cs_tier=None, **cfg_patch):
    return _synergy_tier(
        res_tier, "up", rank_tier, "up", vp_tier, "up", lc_tier, cfg(**cfg_patch), cs_tier=cs_tier,
    )[0]


# ---------- 默认投票（tierSynergyCrossSectionVote=1.0 用户决策）----------

def test_default_vote_includes_cross_section() -> None:
    c = RankTrendConfig()
    assert c.tierSynergyCrossSectionVote == 1.0
    assert c.tierSynergyPriceMomentumVote == 0.0  # G1 实证负贡献，观察不进投票


def test_cross_section_a_tier_upgrades_synergy() -> None:
    # 三票 B（+0.8×3=2.4）+ cs A（+1.0）> strong+1 → S
    assert syn(cs_tier="A") == "S"


def test_cross_section_d_tier_downgrades_synergy() -> None:
    # 三票 B（2.4）+ cs D（-1.0）= 1.4 < strong(2.0) → B
    assert syn(cs_tier="D") == "B"


def test_cross_section_c_tier_downgrades_below_strong() -> None:
    # 三票 B（2.4）+ cs C（-0.5）= 1.9 < strong(2.0) → B（C 档弱势拉低 A 档）
    assert syn(cs_tier="C") == "B"


def test_cross_section_unknown_ignored() -> None:
    assert syn(cs_tier="unknown") == "A"  # 未知不投票


# ---------- 权重关闭时不投票（回归旧 golden）----------

def test_vote_zero_preserves_old_semantics() -> None:
    assert syn(cs_tier="A", tierSynergyCrossSectionVote=0.0) == "A"
    assert syn(cs_tier="D", tierSynergyCrossSectionVote=0.0) == "A"


# ---------- 一票否决优先级（cs 不能绕过硬风险）----------

def test_hard_risk_overrides_cross_section() -> None:
    assert syn(cs_tier="A", vp_tier="E") == "D"  # 量价出货硬风险
    assert syn(cs_tier="A", lc_tier="E") == "E"  # 周期一票否决


# ---------- G1 priceMomentum 投票默认关闭 ----------

def test_price_momentum_vote_disabled_by_default() -> None:
    c = RankTrendConfig()
    assert c.tierSynergyPriceMomentumVote == 0.0
    # 即使传 pm_tier，权重 0 不影响
    assert syn(cs_tier=None, tierSynergyPriceMomentumVote=0.0) == "A"
