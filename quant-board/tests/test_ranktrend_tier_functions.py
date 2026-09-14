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
    # 采纳口径（2026-09-14 阶段 23.9：res/rank/cs 票权 ×0.75、vp ×1.0）
    # 3× A+buy：v = 0.75+0.75+1.0(vp) = 2.5 ≥ strong=2 → A
    assert _synergy_tier("A", "buy", "A", "buy", "A", "up", "A")[0] == "A"
    # 2× A+buy = 1.5 ≥ weak=1 → B
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", None)[0] == "B"
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", "A")[0] == "B"
    # 1× A+buy = 0.75 < weak → C（单票不再过 B 线）
    assert _synergy_tier("A", "buy", "B", "hold", "C", "hold", None)[0] == "C"
    # 全 hold → C
    assert _synergy_tier("C", "hold", "C", "hold", "C", "hold", None)[0] == "C"
    # D+sell 单维 = -0.75 → C（单维反向不足 reverse 线 -1；反向确认需双维）
    assert _synergy_tier("D", "sell", "C", "hold", "C", "hold", None)[0] == "C"
    # lc=B/D 时 S/A 降一档：v=2.5 → A 且 lc=B → A 降 B
    assert _synergy_tier("A", "buy", "A", "buy", "A", "up", "B")[0] == "B"  # A→B
    # v=1.5 → B 且 lc=D → B 保持（仅 S/A 降档）
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", "D")[0] == "B"


def test_synergy_tier_weighted_vote() -> None:
    """档位强度加权投票核心语义（vote 语义改进方案 §3.3 场景表，v4 强度 + 阶段 23.9 采纳票权 0.75）。"""
    # 1× S+buy = 0.9 → C（单维强信号不足 weak 线）
    assert _synergy_tier("S", "buy", "C", "hold", "C", "hold", None)[0] == "C"
    # S+buy(0.9) + A+buy(0.75) = 1.65 ≥ weak → B
    assert _synergy_tier("S", "buy", "A", "buy", "C", "hold", None)[0] == "B"
    # S+buy + B+buy = 0.9 + 0.6 = 1.5 → B
    assert _synergy_tier("S", "buy", "B", "buy", "C", "hold", None)[0] == "B"
    # 2× S+buy = 1.8 → B
    assert _synergy_tier("S", "buy", "S", "buy", "C", "hold", None)[0] == "B"
    # 3× S+buy = 0.9+0.9+1.2(vp) = 3.0 ≥ strong+1 → S（S 线需 vp 强票同向参与）
    assert _synergy_tier("S", "buy", "S", "buy", "S", "buy", None)[0] == "S"
    # 1× B+buy = 0.6 < weak → C（弱档单票不升 B）
    assert _synergy_tier("B", "buy", "C", "hold", "C", "hold", None)[0] == "C"
    # 1× C+buy = 0.375 < weak → C（弱信号不误导升档）
    assert _synergy_tier("C", "buy", "C", "hold", "C", "hold", None)[0] == "C"
    # 3× C+buy = 1.125 ≥ weak → B（C 档 3 票弱确认）
    assert _synergy_tier("C", "buy", "C", "buy", "C", "buy", None)[0] == "B"
    # D+buy（方向主导 v4）= 0.75 → C（单 D 票不足 weak 线）
    assert _synergy_tier("D", "buy", "C", "hold", "C", "hold", None)[0] == "C"
    # 两维空：D+sell + D+sell = -1.5 ≤ reverse → D（反向确认）
    assert _synergy_tier("D", "sell", "D", "sell", "C", "hold", None)[0] == "D"
    # S+sell（强卖）= -0.9 → C（单维反向不足 reverse 线）
    assert _synergy_tier("S", "sell", "C", "hold", "C", "hold", None)[0] == "C"


def test_synergy_tier_uses_config_vote_thresholds() -> None:
    # 采纳票权 0.75：strong=3, weak=2 时 A+A+C = 1.5 < weak → C
    c = RankTrendConfig.from_patch({"tierSynergyVoteStrong": 3, "tierSynergyVoteWeak": 2})
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", None, c)[0] == "C"
    # A+A+A = 2.25 < strong=3，≥ weak=2 → B
    assert _synergy_tier("A", "buy", "A", "buy", "A", "up", None, c)[0] == "B"
    # strong=3, weak=1：A+A+C = 1.5 ≥ weak=1 → B
    c2 = RankTrendConfig.from_patch({"tierSynergyVoteStrong": 3, "tierSynergyVoteWeak": 1})
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", None, c2)[0] == "B"
    # reverse=0：v=0 不再 C → D
    c3 = RankTrendConfig.from_patch({"tierSynergyVoteStrong": 2, "tierSynergyVoteWeak": 1, "tierSynergyVoteReverse": 0})
    assert _synergy_tier("C", "hold", "C", "hold", "C", "hold", None, c3)[0] == "D"
