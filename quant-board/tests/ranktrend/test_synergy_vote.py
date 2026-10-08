# -*- coding: utf-8 -*-
"""synergy 档位投票单元测试（golden 补强，2026-08-17 用户反馈 golden 形同虚设）。

直接调用 _synergy_tier 断言档位——覆盖 G2 crossSection 第 5 维投票默认打开的行为，
防止算法变更悄悄漂移（此前 golden 测试无 synergy 档位断言）。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.volume_price import _synergy_tier


def cfg(**patch) -> RankTrendConfig:
    # 票强表冻结 pre-vsB070 口径（B=0.8；eabf4b44 于 2026-09-30 落默认 0.7）：本文件的
    # 票值算术注释（三票 B 0.6+0.6+0.8=2.0 恰达强买线）按 B=0.8 校准，与
    # test_lifecycle_gate_form._w1、evaluate_synergy_tier_thresholds.BASE_VOTE_STRENGTHS
    # 同一冻结回退对照口径；引擎默认票强由 test_hardcoded_parameterization.py 单独覆盖。
    base = dict(RankTrendConfig().__dict__)
    base["tierSynergyVoteStrengths"] = [1.2, 1.0, 0.8, 0.5, 1.0, 1.0]
    base.update(patch)
    return RankTrendConfig(**base)


def syn(res_tier="B", rank_tier="B", vp_tier="B", lc_tier="A", cs_tier=None, **cfg_patch):
    return _synergy_tier(
        res_tier, "up", rank_tier, "up", vp_tier, "up", lc_tier, cfg(**cfg_patch), cs_tier=cs_tier,
    )[0]


# ---------- 默认投票（tierSynergyCrossSectionVote=1.0 用户决策）----------

def test_default_vote_includes_cross_section() -> None:
    c = RankTrendConfig()
    assert c.tierSynergyCrossSectionVote == 0.75  # 阶段 23.9 采纳 combo_three_quarter（2026-09-14 用户决策）
    assert not hasattr(c, "tierSynergyPriceMomentumVote")  # W0-1 死票位摘除（实证 −32%，观察因子本体不动）


def test_cross_section_a_tier_upgrades_synergy() -> None:
    # 三票 B（0.6+0.6+0.8=2.0）+ cs A（1.0×0.75=0.75）= 2.75 ≥ strong → A（<3 不达 S）
    assert syn(cs_tier="A") == "A"


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


# ---------- W0-1：pm/dv 死票位摘除（2026-10-08）----------

def test_price_momentum_vote_removed_by_w01() -> None:
    """W0-1：pm/dv 票位字段与传参链已摘除（账面七维→五维实态）；观察因子本体不动。"""
    c = RankTrendConfig()
    assert not hasattr(c, "tierSynergyPriceMomentumVote")
    assert not hasattr(c, "tierSynergyDivergenceVote")
    # pm/dv 观察因子照常进 observation（runtime 侧不动）——此处只断言投票面签名收窄
    assert "pm_tier" not in _synergy_tier.__code__.co_varnames
    assert "dv_tier" not in _synergy_tier.__code__.co_varnames
