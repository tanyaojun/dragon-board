# -*- coding: utf-8 -*-
"""L2 amount 喂量价档位专项测试（2026-10-08 预登记合同 v1.1；vote-l2-vp-amount-tier-preregistration.md）。

- 默认 off 零行为=第一断言（合同 测试纪律）；
- 三态谓词：边界含等号（ar≥1.5 含 1.5 / ar≤0.5 含 0.5）；None 不可算帧不参与；
- E/缩量涨停优先级不被 amount 门改写（硬风险语义高于 amount 门）；
- b 臂升档只触 rise_shrink/normal 的 C（缩量涨停帧不参与升档）；
- off 恒走原路径（compute_volume_price_score 全链逐位一致）。
"""
import pytest

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.ranking.volume_price import _volume_price_tier, compute_volume_price_score

HI, LO = 1.5, 0.5


def _tier(mode, ar, quadrant="rise_volume", fund=1.0, reasons=None):
    return _volume_price_tier(
        quadrant, fund, reasons or ["放量上涨"], amount_ratio=ar, tier_mode=mode,
        amount_ratio_high=HI, amount_ratio_low=LO,
    )


class TestDefaultOffZeroBehavior:
    def test_default_mode_is_off(self):
        assert RankTrendConfig().volumePriceAmountTierMode == "off"

    def test_off_ignores_gate_params(self):
        """off 下传门参数也零行为（各档位与原路径逐位一致）。"""
        cases = [
            ("rise_volume", 1.0, None, "A"),
            ("rise_volume", -1.0, None, "B"),
            ("rise_shrink", 0.0, None, "C"),
            ("fall_volume", 0.0, None, "D"),
            ("rise_volume", 0.0, ["对倒出货"], "E"),
        ]
        for quadrant, fund, reasons, expected in cases:
            tier, _ = _volume_price_tier(quadrant, fund, reasons or ["放量上涨"],
                                         amount_ratio=2.0, tier_mode="off",
                                         amount_ratio_high=HI, amount_ratio_low=LO)
            assert tier == expected

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError):
            RankTrendConfig.from_patch({"volumePriceAmountTierMode": "bogus"})


class TestHighDemoteArm:
    def test_a_to_b_at_boundary_inclusive(self):
        tier, reasons = _tier("high_demote", 1.5)
        assert tier == "B"  # ≥ 含等号
        assert any("放量奖励撤回" in r for r in reasons)

    def test_below_boundary_untouched(self):
        assert _tier("high_demote", 1.49)[0] == "A"

    def test_b_to_c_demote(self):
        assert _tier("high_demote", 2.0, fund=-1.0)[0] == "C"

    def test_non_ab_tiers_untouched(self):
        assert _tier("high_demote", 2.0, quadrant="rise_shrink")[0] == "C"
        assert _tier("high_demote", 2.0, quadrant="fall_volume")[0] == "D"
        assert _tier("high_demote", 2.0, reasons=["对倒出货"])[0] == "E"

    def test_none_amount_ratio_not_participating(self):
        assert _tier("high_demote", None)[0] == "A"


class TestBothArm:
    def test_c_to_b_at_boundary_inclusive(self):
        tier, reasons = _tier("both", 0.5, quadrant="rise_shrink")
        assert tier == "B"  # ≤ 含等号
        assert any("缩量惜售升档" in r for r in reasons)

    def test_above_low_boundary_untouched(self):
        assert _tier("both", 0.51, quadrant="normal")[0] == "C"

    def test_limit_up_shrink_c_not_upgraded(self):
        """缩量涨停帧语义特殊（封板买不进），不参与升档。"""
        assert _tier("both", 0.4, quadrant="rise_shrink", reasons=["缩量涨停"])[0] == "C"

    def test_ab_leg_shared_with_high_demote(self):
        """b 臂含 a 臂全部语义：放量 A/B 同样降档。"""
        assert _tier("both", 2.0, fund=-1.0)[0] == "C"
        assert _tier("both", 0.4)[0] == "A"  # 低量 A 不动（升档腿只触 C）


class TestComputeScoreIntegration:
    """全链集成：off 与「门参数未启用时代」输出逐位一致；arm 生效且 score 零改动。"""

    _ARGS = dict(code="600000", change=3.0, volume_ratio=2.0, zlje=1.0, zljzb=1.0)

    def test_off_chain_identical(self):
        c = RankTrendConfig()
        a = compute_volume_price_score(amount_ratio=2.0, config=c, **self._ARGS)
        b = compute_volume_price_score(amount_ratio=None, config=c, **self._ARGS)
        assert a["signalTier"] == b["signalTier"] == "A"  # 该形态 ar=2.0 放量上涨=原 A
        assert a["signalTier"] == "A"

    def test_high_demote_downgrades_tier_keeps_score(self):
        c = RankTrendConfig(volumePriceAmountTierMode="high_demote")
        out = compute_volume_price_score(amount_ratio=2.0, config=c, **self._ARGS)
        assert out["signalTier"] == "B"
        assert any("放量奖励撤回" in r for r in out["tierReasons"])
        c_off = RankTrendConfig()
        assert out["score"] == compute_volume_price_score(amount_ratio=2.0, config=c_off, **self._ARGS)["score"]

    def test_both_upgrades_shrink_c(self):
        args = dict(code="600000", change=1.0, volume_ratio=0.3, zlje=1.0, zljzb=1.0)
        c = RankTrendConfig(volumePriceAmountTierMode="both")
        out = compute_volume_price_score(amount_ratio=0.4, config=c, **args)
        assert out["signalTier"] == "B"
