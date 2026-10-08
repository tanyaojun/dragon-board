# -*- coding: utf-8 -*-
"""W1-1 共振 D∧buy 倒挂票专项测试（2026-10-08 预登记合同；vote-w11-res-dbuy-preregistration.md）。

- 默认 off 零行为=第一断言（合同 §四）；
- cap_b=票值封顶 B（min(强度D,强度B)×res 权重）→ 行为等价断言：cap_b 下 D∧buy 的输出
  逐位等于 off 下 B∧buy 的输出（票值相同 ⇒ 全函数输出相同）；
- abstain=弃权票 0 → 等价于 res 不计票（res=(None,None)）；
- 红线：D∧sell（路径 2 真反向 D）两态都不动；非 D 档（B∧buy）不触；rank/vp/cs 维不触及；
- 风险③：强度表长度≠6 时 cap_b 断言报错（不走静默 fallback）。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.ranking.volume_price import _synergy_tier


def _tier(res, rank=(None, None), vp=(None, None), config=None):
    return _synergy_tier(
        res[0], res[1], rank[0], rank[1], vp[0], vp[1], "C",
        config or RankTrendConfig(),
    )


class TestDefaultOffZeroBehavior:
    def test_default_mode_is_off(self):
        assert RankTrendConfig().tierSynergyResonanceDbuyMode == "off"

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError):
            RankTrendConfig.from_patch({"tierSynergyResonanceDbuyMode": "cap_a"})

    def test_off_matches_pre_w11_path(self):
        """off 恒走原路径：D∧buy 仍投 +strength(D)×res 权重（倒挂实体：高于 B∧buy 同输入）。"""
        c2 = RankTrendConfig.from_patch({"tierSynergyResonanceVote": 2.0})
        # D∧buy v=2.0→A；B∧buy v=1.4→B（倒挂：衰竭档票高于健康弱确认档）
        assert _tier(("D", "buy"), config=c2)[0] == "A"
        assert _tier(("B", "buy"), config=c2)[0] == "B"


class TestCapB:
    def test_cap_b_equals_b_buy_original_path(self):
        """行为等价：cap_b 下 D∧buy ≡ off 下 B∧buy（票值 min(D,B)=0.7 相同）。"""
        base = RankTrendConfig()
        capped = RankTrendConfig.from_patch({"tierSynergyResonanceDbuyMode": "cap_b"})
        for rank, vp in (((None, None), (None, None)), (("B", "buy"), ("B", "buy")), (("D", "sell"), ("C", "hold"))):
            assert _tier(("D", "buy"), rank, vp, capped) == _tier(("B", "buy"), rank, vp, base)

    def test_cap_b_lowers_tier_vs_off(self):
        c = RankTrendConfig.from_patch({"tierSynergyResonanceVote": 2.0, "tierSynergyResonanceDbuyMode": "cap_b"})
        # off 时 v=2.0→A；cap_b v=1.4→B
        assert _tier(("D", "buy"), config=c)[0] == "B"

    def test_cap_b_reads_strength_table_not_hardcoded(self):
        """强度表可变：cap_b 读 min(表[D],表[B])，表改动跟随（合同 §二 不硬编码）。"""
        c = RankTrendConfig.from_patch(
            {"tierSynergyResonanceDbuyMode": "cap_b", "tierSynergyVoteStrengths": [1.2, 1.0, 0.3, 0.5, 1.0, 1.0],
             "tierSynergyResonanceVote": 2.0}
        )
        # min(D=0.5, B=0.3)=0.3×2.0=0.6 <weak(1.0) → C；若硬编码 0.7 会是 1.4→B
        assert _tier(("D", "buy"), config=c)[0] == "C"

    def test_cap_b_strength_table_bad_length_raises(self):
        """长度守卫双层：config 层 _validate 先挡（from_patch 拒绝）；分支内断言为纵深防御
        （对象级篡改绕过构造校验的场景仍 fail-fast，不走静默 fallback）。"""
        with pytest.raises(ValueError, match="长度必须为 6"):
            RankTrendConfig.from_patch({"tierSynergyVoteStrengths": [1.0, 1.0, 0.7, 0.5, 1.0]})
        c = RankTrendConfig()
        c.tierSynergyVoteStrengths = [1.0, 1.0, 0.7, 0.5, 1.0]  # 绕过构造校验模拟运行期篡改
        c.tierSynergyResonanceDbuyMode = "cap_b"
        with pytest.raises(ValueError, match="长度必须为 6"):
            _tier(("D", "buy"), config=c)


class TestAbstain:
    def test_abstain_equals_no_res_vote(self):
        """行为等价：abstain 下 D∧buy ≡ res 不计票。"""
        base = RankTrendConfig()
        abst = RankTrendConfig.from_patch({"tierSynergyResonanceDbuyMode": "abstain"})
        for rank, vp in (((None, None), (None, None)), (("B", "buy"), ("B", "buy")), (("S", "buy"), ("D", "sell"))):
            assert _tier(("D", "buy"), rank, vp, abst) == _tier((None, None), rank, vp, base)


class TestRedLines:
    """D∧sell 真反向 / 非 D 档 / 其他维零触碰。"""

    def test_d_sell_untouched_both_modes(self):
        base = RankTrendConfig.from_patch({"tierSynergyResonanceVote": 2.0})
        for patch in ({"tierSynergyResonanceVote": 2.0, "tierSynergyResonanceDbuyMode": "cap_b"},
                      {"tierSynergyResonanceVote": 2.0, "tierSynergyResonanceDbuyMode": "abstain"}):
            c = RankTrendConfig.from_patch(patch)
            expected = _tier(("D", "sell"), config=base)
            assert _tier(("D", "sell"), config=c) == expected  # 真反向 D 票 −strength×w 不动（v=−2.0→D 反向）

    def test_b_buy_untouched_cap_b(self):
        base = RankTrendConfig.from_patch({"tierSynergyResonanceVote": 2.0})
        c = RankTrendConfig.from_patch({"tierSynergyResonanceVote": 2.0, "tierSynergyResonanceDbuyMode": "cap_b"})
        assert _tier(("B", "buy"), config=c) == _tier(("B", "buy"), config=base)

    def test_other_dimensions_untouched(self):
        """rank/vp/cs 维输入在 cap_b/abstain 下与 off 输出逐位一致（res 项外全同）。"""
        base = RankTrendConfig()
        for patch in ({"tierSynergyResonanceDbuyMode": "cap_b"}, {"tierSynergyResonanceDbuyMode": "abstain"}):
            c = RankTrendConfig.from_patch(patch)
            for rank, vp, cs in ((("S", "buy"), ("A", "up"), None), (("D", "sell"), ("E", "down"), "C")):
                got = _synergy_tier((None, None)[0], (None, None)[1], rank[0], rank[1], vp[0], vp[1], "C", c, cs_tier=cs)
                exp = _synergy_tier(None, None, rank[0], rank[1], vp[0], vp[1], "C", base, cs_tier=cs)
                assert got == exp
