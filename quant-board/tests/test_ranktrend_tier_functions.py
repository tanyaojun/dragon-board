"""档位函数接 config（回测方案 §3.1/§8 步骤 2）。

五维档位阈值从硬编码改为读 RankTrendConfig.tier*，默认值=旧硬编码（golden 不漂移）。
覆盖：_rank_trend_tier / _resonance_tier / 新入榜分支 / _synergy_tier。
"""

from __future__ import annotations

from backend.analysis.ranktrend.engine import (
    RankTrendConfig,
    _rank_trend_tier,
    _resonance_tier,
    analyze_rank_resonance,
)
from backend.analysis.ranktrend.volume_price import _synergy_tier


# ── _rank_trend_tier ─────────────────────────────────────────────

def test_rank_trend_tier_default_matches_hardcoded() -> None:
    assert _rank_trend_tier("buy", 0.6)[0] == "S"
    assert _rank_trend_tier("buy", 0.3)[0] == "A"
    assert _rank_trend_tier("buy", 0.1)[0] == "B"
    assert _rank_trend_tier("sell", 0.3)[0] == "D"
    assert _rank_trend_tier("hold", 0.3)[0] == "C"


def test_rank_trend_tier_uses_config_thresholds() -> None:
    c = RankTrendConfig.from_patch(
        {"tierRankTrendStrongMin": 0.7, "tierRankTrendConfirmMin": 0.4}
    )
    assert _rank_trend_tier("buy", 0.6, c)[0] == "A"  # 默认 0.5 下是 S，0.7 下落到 A
    assert _rank_trend_tier("buy", 0.75, c)[0] == "S"
    assert _rank_trend_tier("buy", 0.35, c)[0] == "B"


# ── _resonance_tier ──────────────────────────────────────────────

def test_resonance_tier_default_matches_hardcoded() -> None:
    assert _resonance_tier("buy", 0.7, "jump", 0.6, 0.5)[0] == "S"  # jump 分支
    assert _resonance_tier("buy", 0.65, "none", 0, 0.5)[0] == "A"  # persistence
    assert _resonance_tier("buy", 0.5, "none", 0, 0.5)[0] == "B"
    assert _resonance_tier("buy", 0.5, "none", 0, 0.7)[0] == "D"  # reversal 否决
    assert _resonance_tier("hold", 0.0, "none", 0, 0.0)[0] == "C"
    assert _resonance_tier("sell", 0.0, "none", 0, 0.0)[0] == "D"


def test_resonance_tier_uses_config_thresholds() -> None:
    c = RankTrendConfig.from_patch(
        {
            "tierResonanceReversalPenaltyMin": 0.7,
            "tierResonancePersistenceMin": 0.7,
        }
    )
    assert _resonance_tier("buy", 0.65, "none", 0, 0.65, c)[0] == "B"  # reversal 0.65 < 0.7，persistence 0.65 < 0.7
    assert _resonance_tier("buy", 0.65, "none", 0, 0.0, c)[0] == "B"  # persistence 0.65 < 0.7（默认 0.6 下是 A）
    assert _resonance_tier("buy", 0.75, "none", 0, 0.0, c)[0] == "A"
    assert _resonance_tier("buy", 0.5, "jump", 0.4, 0.0, c)[0] == "B"  # jump freshness 0.4 < 0.5，persistence 0.5 < 0.7


# ── analyze_rank_resonance 新入榜分支 ─────────────────────────────

def _new_entry_input(attention_percentile: float, jump_events: list | None = None) -> dict:
    return {
        "percentiles": [0.9],  # len==1 → is_new_entry
        "sampleQuality": {"status": "ok", "timelineValid": True},
        "marketMedianShortChange": 0.5,
        "marketSampleCount": 30,
        "marketMedianPercentile": 0.5,
        "jump": {"events": jump_events or []},
        "entry": {"isNew": True, "currentAttentionPercentile": attention_percentile},
    }


def test_new_entry_default_matches_hardcoded() -> None:
    # percentile=60 → entry_strength=(60-50)/25=0.4 → A（0.4>=0.3）
    assert analyze_rank_resonance(_new_entry_input(60))["signalTier"] == "A"
    # percentile=45 → entry_strength=0 → C
    assert analyze_rank_resonance(_new_entry_input(45))["signalTier"] == "C"
    # jump 事件 → S
    assert (
        analyze_rank_resonance(_new_entry_input(60, [{"index": 0, "direction": "surge", "magnitude": 1}]))["signalTier"]
        == "S"
    )


def test_new_entry_uses_config_entry_strength() -> None:
    c = RankTrendConfig.from_patch({"tierResonanceEntryStrengthMin": 0.5})
    # entry_strength=0.4：默认 0.3 下 A，0.5 下落 B
    assert analyze_rank_resonance(_new_entry_input(60), c)["signalTier"] == "B"


def test_new_entry_jump_freshness_config_boundary() -> None:
    """新入榜 jump_freshness 恒 1.0（有 events）；阈值上调到合法上限 1.0 仍 S（边界回归）。"""
    inp = _new_entry_input(60, [{"index": 0, "direction": "surge", "magnitude": 1}])
    c = RankTrendConfig.from_patch({"tierResonanceJumpFreshnessMin": 1.0})
    assert analyze_rank_resonance(inp, c)["signalTier"] == "S"
    # 无 events → freshness=0 → 阈值 0.1 下不满足 jump S，落 A
    c2 = RankTrendConfig.from_patch({"tierResonanceJumpFreshnessMin": 0.1})
    assert analyze_rank_resonance(_new_entry_input(60), c2)["signalTier"] == "A"


# ── _synergy_tier ────────────────────────────────────────────────

def test_synergy_tier_default_matches_hardcoded() -> None:
    # lc=E 硬分支优先
    assert _synergy_tier("A", "buy", "A", "buy", "A", "up", "E")[0] == "E"
    # vp=E 硬分支
    assert _synergy_tier("A", "buy", "A", "buy", "E", "down", None)[0] == "D"
    # v=2 且 lc==A → S
    assert _synergy_tier("A", "buy", "A", "buy", "A", "up", "A")[0] == "S"
    # v=2 → A
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", None)[0] == "A"
    # v=1 → B
    assert _synergy_tier("A", "buy", "B", "hold", "C", "hold", None)[0] == "B"
    # v=0 → C
    assert _synergy_tier("C", "hold", "C", "hold", "C", "hold", None)[0] == "C"
    # v=-1 → D
    assert _synergy_tier("D", "sell", "C", "hold", "C", "hold", None)[0] == "D"
    # lc=B 时 S 分支不可达（S 需 lc==A），最高 A → 降档 B
    assert _synergy_tier("A", "buy", "A", "buy", "A", "up", "B")[0] == "B"  # A→B
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", "D")[0] == "B"  # A→B


def test_synergy_tier_uses_config_vote_thresholds() -> None:
    # strong=3, weak=2：v=2 → v==weak → B
    c = RankTrendConfig.from_patch({"tierSynergyVoteStrong": 3, "tierSynergyVoteWeak": 2})
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", None, c)[0] == "B"
    # v=3 → A
    assert _synergy_tier("A", "buy", "A", "buy", "A", "up", None, c)[0] == "A"
    # strong=3, weak=1：v=2 既不满足 S/A 也不满足 B/D → C（强买门槛上调后的预期语义）
    c2 = RankTrendConfig.from_patch({"tierSynergyVoteStrong": 3, "tierSynergyVoteWeak": 1})
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", None, c2)[0] == "C"
    # reverse=0：v=0 不再 C → D
    c3 = RankTrendConfig.from_patch({"tierSynergyVoteStrong": 2, "tierSynergyVoteWeak": 1, "tierSynergyVoteReverse": 0})
    assert _synergy_tier("C", "hold", "C", "hold", "C", "hold", None, c3)[0] == "D"
