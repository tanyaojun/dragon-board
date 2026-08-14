"""搜索空间追加 tier/synergy 参数（回测方案 §4.1/§4.2）。

合同：
- default_search_space() 追加 9 个 tier* 档位阈值 + 2 个 synergy 交易开关；
- tier* 进 _STRATEGY_SCALAR_KEYS 自动白名单（int/float 字段）→ to_strategy_config 收走进
  RankTrendConfig，to_trade_config pop；
- synergyEntryTierMin（str）/synergyExitOnDanger（bool）为交易层参数：不进 RankTrendConfig、
  不进 _STRATEGY_PARAM_KEYS → to_trade_config 透传进 trade_config（TradeSimulator 消费，见 Task 4）。
  注：与 plan §4.1 的"显式追加进 _STRATEGY_PARAM_KEYS"不同——那是基于 strategy.py 交易链路的
  判断；真实交易主链在 execution.py（TradeSimulator 读 trade_config），透传才是正确路径。
"""

from __future__ import annotations

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.optimization.search_space import (
    _STRATEGY_PARAM_KEYS,
    _STRATEGY_SCALAR_KEYS,
    candidate_count,
    default_search_space,
    to_strategy_config,
    to_trade_config,
)

TIER_KEYS = [
    "tierResonanceReversalPenaltyMin",
    "tierResonanceJumpFreshnessMin",
    "tierResonancePersistenceMin",
    "tierResonanceEntryStrengthMin",
    "tierRankTrendStrongMin",
    "tierRankTrendConfirmMin",
    "tierSynergyVoteStrong",
    "tierSynergyVoteWeak",
    "tierSynergyVoteReverse",
]
SYNERGY_TRADE_KEYS = ["synergyEntryTierMin", "synergyExitOnDanger"]


def test_default_search_space_contains_tier_and_synergy_params() -> None:
    space = default_search_space()
    for key in TIER_KEYS + SYNERGY_TRADE_KEYS:
        assert key in space, f"搜索空间缺 {key}"


def test_tier_params_values_match_plan() -> None:
    """§4.1 值域：3⁶（共振4+趋势2）× 2³（vote3）× 2（entry）× 2（exit）。"""
    space = default_search_space()
    assert space["tierResonanceReversalPenaltyMin"] == [0.5, 0.6, 0.7]
    assert space["tierResonanceJumpFreshnessMin"] == [0.4, 0.5, 0.6]
    assert space["tierResonancePersistenceMin"] == [0.5, 0.6, 0.7]
    assert space["tierResonanceEntryStrengthMin"] == [0.2, 0.3, 0.4]
    assert space["tierRankTrendStrongMin"] == [0.4, 0.5, 0.6]
    assert space["tierRankTrendConfirmMin"] == [0.2, 0.25, 0.3]
    assert space["tierSynergyVoteStrong"] == [2, 3]
    assert space["tierSynergyVoteWeak"] == [1, 2]
    assert space["tierSynergyVoteReverse"] == [-1, 0]
    assert space["synergyEntryTierMin"] == ["none", "a"]
    assert space["synergyExitOnDanger"] == [False, True]


def test_tier_fields_auto_in_strategy_scalar_whitelist() -> None:
    """9 个 tier* 字段为 int/float → 自动进 _STRATEGY_SCALAR_KEYS（无需手工维护）。"""
    assert set(TIER_KEYS).issubset(set(_STRATEGY_SCALAR_KEYS))


def test_synergy_trade_params_not_in_strategy_whitelist() -> None:
    """synergy 交易参数不进 RankTrendConfig / _STRATEGY_PARAM_KEYS（保持交易层透传）。"""
    for key in SYNERGY_TRADE_KEYS:
        assert not hasattr(RankTrendConfig(), key)
        assert key not in _STRATEGY_PARAM_KEYS


def test_to_strategy_config_keeps_tier_drops_synergy() -> None:
    params = {
        "tierRankTrendStrongMin": 0.6,
        "tierSynergyVoteStrong": 3,
        "synergyEntryTierMin": "a",
        "synergyExitOnDanger": True,
        "macdFast": 8,
    }
    strategy_config = to_strategy_config(params)
    assert strategy_config["tierRankTrendStrongMin"] == 0.6
    assert strategy_config["tierSynergyVoteStrong"] == 3
    assert "synergyEntryTierMin" not in strategy_config
    assert "synergyExitOnDanger" not in strategy_config


def test_to_trade_config_pops_tier_passes_synergy() -> None:
    params = {
        "tierRankTrendStrongMin": 0.6,
        "synergyEntryTierMin": "a",
        "synergyExitOnDanger": True,
        "takeProfit": 0.12,
    }
    trade_config = to_trade_config(params)
    assert trade_config["synergyEntryTierMin"] == "a"
    assert trade_config["synergyExitOnDanger"] is True
    assert "tierRankTrendStrongMin" not in trade_config
    assert trade_config["takeProfit"] == 0.12  # 既有交易参数不受影响


def test_candidate_count_nominal_matches_plan() -> None:
    """名义组合 3⁶×2³×2×2 = 23328（§4.2；无效 weak<strong 组合由 from_patch 拒绝计 failed）。"""
    space = default_search_space()
    count = candidate_count(space)
    tier_vote_strong = len(space["tierSynergyVoteStrong"])
    tier_vote_weak = len(space["tierSynergyVoteWeak"])
    tier_vote_reverse = len(space["tierSynergyVoteReverse"])
    tier_6 = 1
    for key in [
        "tierResonanceReversalPenaltyMin",
        "tierResonanceJumpFreshnessMin",
        "tierResonancePersistenceMin",
        "tierResonanceEntryStrengthMin",
        "tierRankTrendStrongMin",
        "tierRankTrendConfirmMin",
    ]:
        tier_6 *= len(space[key])
    expected = tier_6 * tier_vote_strong * tier_vote_weak * tier_vote_reverse * 2 * 2
    assert expected == 3**6 * 2**3 * 2 * 2 == 23328
    assert count >= expected  # 含既有参数（macd/分层阈值/交易层），名义总空间 >= 新增档位子空间
