"""RankTrend tier 阈值参数化（回测方案 §3.1）：RankTrendConfig 新增 tier* 字段与强校验。

合同（docs/ranktrend-signal-tier-backtest-plan.md §3.1）：
- 9 个 tier* 字段，默认值 = 当前硬编码值（golden 不漂移）。
- from_patch 强校验：
  - 0 < tierRankTrendConfirmMin < tierRankTrendStrongMin <= 1
  - tierSynergyVoteReverse <= tierSynergyVoteWeak < tierSynergyVoteStrong（weak 严格小于 strong）
  - 0 <= tierResonance*Min <= 1
  - 不满足时 from_patch 抛 ValueError（回测 trial 记 failed，防止非法阈值污染）。
"""

from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig


def test_tier_fields_defaults_match_hardcoded_values() -> None:
    """默认值 = 当前硬编码（engine/volume_price/_synergy_tier 现状），保证 golden 不漂移。"""
    c = RankTrendConfig()
    assert c.tierResonanceReversalPenaltyMin == 0.6
    assert c.tierResonanceJumpFreshnessMin == 0.5
    assert c.tierResonancePersistenceMin == 0.6
    assert c.tierResonanceEntryStrengthMin == 0.3
    assert c.tierRankTrendStrongMin == 0.5
    assert c.tierRankTrendConfirmMin == 0.25
    assert c.tierSynergyVoteStrong == 2
    assert c.tierSynergyVoteWeak == 1
    assert c.tierSynergyVoteReverse == -1


def test_tier_fields_patch_applies() -> None:
    c = RankTrendConfig.from_patch(
        {
            "tierResonanceReversalPenaltyMin": 0.7,
            "tierRankTrendStrongMin": 0.6,
            "tierRankTrendConfirmMin": 0.3,
            "tierSynergyVoteStrong": 3,
            "tierSynergyVoteWeak": 1,
            "tierSynergyVoteReverse": 0,
        }
    )
    assert c.tierResonanceReversalPenaltyMin == 0.7
    assert c.tierRankTrendStrongMin == 0.6
    assert c.tierRankTrendConfirmMin == 0.3
    assert c.tierSynergyVoteStrong == 3
    assert c.tierSynergyVoteWeak == 1
    assert c.tierSynergyVoteReverse == 0


@pytest.mark.parametrize(
    "patch",
    [
        {"tierRankTrendConfirmMin": 0.5, "tierRankTrendStrongMin": 0.5},  # confirm == strong
        {"tierRankTrendConfirmMin": 0.6, "tierRankTrendStrongMin": 0.5},  # confirm > strong
        {"tierRankTrendConfirmMin": 0.0},  # confirm <= 0
        {"tierRankTrendStrongMin": 1.1},  # strong > 1
        {"tierRankTrendStrongMin": 0.2, "tierRankTrendConfirmMin": 0.2},  # confirm == strong（边界）
        {"tierSynergyVoteWeak": 2, "tierSynergyVoteStrong": 2},  # weak == strong（分支不可达）
        {"tierSynergyVoteWeak": 3, "tierSynergyVoteStrong": 2},  # weak > strong
        {"tierSynergyVoteReverse": 1, "tierSynergyVoteWeak": 0},  # reverse(1) > weak(0)
        {"tierSynergyVoteReverse": 2},  # reverse 越界
        {"tierResonanceReversalPenaltyMin": -0.1},
        {"tierResonanceJumpFreshnessMin": 1.01},
        {"tierResonancePersistenceMin": -0.01},
        {"tierResonanceEntryStrengthMin": 1.5},
    ],
)
def test_tier_fields_invalid_patch_raises(patch: dict) -> None:
    with pytest.raises(ValueError):
        RankTrendConfig.from_patch(patch)


def test_tier_fields_boundary_valid_patch_ok() -> None:
    """合法边界：confirm 略小于 strong、weak 略小于 strong、resonance 恰在 [0,1] 端点。"""
    c = RankTrendConfig.from_patch(
        {
            "tierRankTrendConfirmMin": 0.001,
            "tierRankTrendStrongMin": 1.0,
            "tierSynergyVoteWeak": 1,
            "tierSynergyVoteStrong": 3,
            "tierSynergyVoteReverse": 1,
            "tierResonanceReversalPenaltyMin": 0.0,
            "tierResonancePersistenceMin": 1.0,
        }
    )
    assert c.tierRankTrendConfirmMin == 0.001
    assert c.tierRankTrendStrongMin == 1.0
    assert c.tierSynergyVoteStrong == 3
    assert c.tierSynergyVoteReverse == 1


def test_tier_fields_unknown_keys_still_ignored() -> None:
    """from_patch 对未知 key 保持现有宽松行为（不抛错、不写入）。"""
    c = RankTrendConfig.from_patch({"notAField": 123, "tierSynergyVoteStrong": 2})
    assert c.tierSynergyVoteStrong == 2
    assert not hasattr(c, "notAField")


def test_tier_fields_bool_patch_preserved() -> None:
    """现有 bool 字段转换行为不回归（from_patch 内 isinstance bool 分支）。"""
    c = RankTrendConfig.from_patch({"requireMacdGoldenCross": "true"})
    assert c.requireMacdGoldenCross is True
    assert RankTrendConfig.from_patch({"requireMacdGoldenCross": "false"}).requireMacdGoldenCross is False


def test_tier_fields_empty_patch_no_raise() -> None:
    """from_patch(None)/from_patch({}) 不触发校验、不抛错。"""
    assert RankTrendConfig.from_patch(None).tierRankTrendStrongMin == 0.5
    assert RankTrendConfig.from_patch({}).tierSynergyVoteStrong == 2


def test_tier_fields_macd_fix_still_applies() -> None:
    """既有 macdSlow/macdFast 强制修正不因新校验回归。"""
    c = RankTrendConfig.from_patch({"macdFast": 34, "macdSlow": 21})
    assert c.macdSlow == 35  # 修正为 fast+1


def test_tier_fields_str_numeric_patch_converted() -> None:
    """str 数值 patch 被按字段类型转换（float/int），非法字符串抛 ValueError 而非 TypeError。"""
    c = RankTrendConfig.from_patch({"tierRankTrendStrongMin": "0.6", "tierSynergyVoteStrong": "3"})
    assert c.tierRankTrendStrongMin == 0.6
    assert c.tierSynergyVoteStrong == 3.0  # vote 阈值 float 化（vote 语义改进 2026-08-15）
    with pytest.raises(ValueError):
        RankTrendConfig.from_patch({"tierRankTrendStrongMin": "abc"})
    # 非数值 vote 阈值仍拒绝
    with pytest.raises(ValueError):
        RankTrendConfig.from_patch({"tierSynergyVoteWeak": "abc"})


def test_tier_fields_synergy_vote_float_allowed() -> None:
    """tierSynergyVote* 档位加权后为 float：float 阈值允许（原 int 强制已移除）。"""
    c = RankTrendConfig.from_patch({"tierSynergyVoteWeak": 1.5, "tierSynergyVoteStrong": 2.5})
    assert c.tierSynergyVoteWeak == 1.5
    assert c.tierSynergyVoteStrong == 2.5


@pytest.mark.parametrize(
    "patch",
    [
        {"buyThresholds": [5, 8, 13, 21]},  # 短 list：tanh 消费侧 index 越界 IndexError
        {"sellThresholds": [-5, -8, -13, -21, -34, -50]},  # 长 list：静默截断
        {"tierSynergyVoteStrengths": [1.2, 1.0, 0.8, 0.5, 1.0]},  # len!=6：_vote 静默回退旧硬编码 fallback（trial 假绿）
        {"tierSynergyCsStrengths": [1.0, 0.5, -0.5]},  # len!=4
    ],
)
def test_tier_fields_list_shape_guard_raises(patch: dict) -> None:
    """list 形状守卫（2026-09-15 补扫总纲预检纪律 1 / P5-0）：from_patch 此前对 list
    长度零校验——短 list 运行期 IndexError、长 list 静默截断、VoteStrengths 长度不符
    时 _vote 静默回退旧硬编码（volume_price.py:405-406）产出假绿 trial。fail-fast。"""
    with pytest.raises(ValueError, match="长度"):
        RankTrendConfig.from_patch(patch)


def test_tier_fields_list_shape_guard_allows_correct_lengths() -> None:
    """守卫不误伤：正确长度的 list patch 与默认构造照常通过。"""
    ok = RankTrendConfig.from_patch(
        {
            "buyThresholds": [2.5, 4, 6.5, 10.5, 17],
            "sellThresholds": [-2.5, -4, -6.5, -10.5, -17],
            "tierSynergyVoteStrengths": [1.0, 1.0, 0.8, 0.5, 1.0, 1.0],
            "tierSynergyCsStrengths": [1.0, 0.5, -0.5, -1.0],
        }
    )
    assert ok.buyThresholds == [2.5, 4, 6.5, 10.5, 17]
    assert len(ok.tierSynergyVoteStrengths) == 6
    assert len(ok.tierSynergyCsStrengths) == 4
    RankTrendConfig()  # 默认构造（未触发 from_patch 校验路径）不受影响
