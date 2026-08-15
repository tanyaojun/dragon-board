# -*- coding: utf-8 -*-
"""四维离散档位（signalTier）单元测试。"""
from backend.analysis.ranktrend.engine import (
    _resonance_tier,
    _rank_trend_tier,
    _lifecycle_tier,
)
from backend.analysis.ranktrend.volume_price import _volume_price_tier
from backend.api.ranktrend_routes import _synergy_tier


def test_resonance_tier_reversal_penalty_priority():
    # 反转惩罚优先于 Jump 事件（D 否决）
    assert _resonance_tier("buy", 0.8, "jump", 1.0, 0.7)[0] == "D"


def test_resonance_tier_jump_event():
    assert _resonance_tier("buy", 0.3, "jump", 0.8, 0.0)[0] == "S"


def test_resonance_tier_confirmed_weak_neutral_reverse():
    assert _resonance_tier("buy", 0.7, "none", 0.0, 0.0)[0] == "A"
    assert _resonance_tier("buy", 0.3, "none", 0.0, 0.0)[0] == "B"
    assert _resonance_tier("hold", 0.0, "none", 0.0, 0.0)[0] == "C"
    assert _resonance_tier("sell", 0.0, "none", 0.0, 0.0)[0] == "D"


def test_rank_trend_tier():
    assert _rank_trend_tier("hold", 0.0)[0] == "C"
    assert _rank_trend_tier("sell", -0.5)[0] == "D"
    assert _rank_trend_tier("buy", 0.6)[0] == "S"
    assert _rank_trend_tier("buy", 0.3)[0] == "A"
    assert _rank_trend_tier("buy", 0.2)[0] == "B"


def test_lifecycle_tier():
    assert _lifecycle_tier("expansion", "veto")[0] == "E"
    assert _lifecycle_tier("expansion", "allow")[0] == "A"
    assert _lifecycle_tier("ignition", "caution")[0] == "B"
    assert _lifecycle_tier("crowded", "exit_watch")[0] == "D"
    assert _lifecycle_tier("cooling", "caution")[0] == "D"
    assert _lifecycle_tier("high_reversal", "caution")[0] == "C"


def test_volume_price_tier_priority():
    assert _volume_price_tier(None, 0.0, [])[0] == "unknown"
    assert _volume_price_tier("rise_volume", 0.0, ["主力净占比异常高（疑似对倒出货）"])[0] == "E"
    assert _volume_price_tier("rise_shrink", 0.0, ["缩量涨停（封板惜售，好票）"])[0] == "C"
    # 缩量涨停 + 对倒出货同现 → E 硬风险优先于 C
    assert _volume_price_tier(
        "rise_shrink", 0.0, ["缩量涨停（封板惜售，好票）", "主力净占比异常高（疑似对倒出货）"]
    )[0] == "E"


def test_volume_price_tier_levels():
    assert _volume_price_tier("rise_volume", 5.0, ["放量上涨（量价配合）"])[0] == "A"
    assert _volume_price_tier("rise_volume", 0.0, ["放量上涨（量价配合）"])[0] == "B"
    assert _volume_price_tier("rise_shrink", 0.0, ["缩量上涨（惜售/无量涨）"])[0] == "C"
    assert _volume_price_tier("fall_volume", 0.0, ["放量下跌（风险）"])[0] == "D"


def test_synergy_tier_veto_and_hard_risk():
    assert _synergy_tier("A", "buy", "A", "buy", "A", "buy", "E")[0] == "E"
    assert _synergy_tier("A", "buy", "A", "buy", "E", "buy", "A")[0] == "D"


def test_synergy_tier_direction_vote():
    # 档位加权 v2（vote 语义改进 2026-08-15）：A=1.0，保持旧票数门槛
    assert _synergy_tier("A", "buy", "A", "buy", "A", "buy", "A")[0] == "S"  # v=3.0 → S
    assert _synergy_tier("A", "buy", "A", "buy", "A", "buy", None)[0] == "S"  # v=3.0, lc 非 B/D → S 保持
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", None)[0] == "A"  # v=2.0 == strong → A（旧门槛保持）
    assert _synergy_tier("A", "buy", "A", "buy", "B", "buy", "B")[0] == "B"  # v=2.5 → A，lc=B 降 B
    assert _synergy_tier("B", "buy", "C", "hold", "C", "neutral", "A")[0] == "C"  # v=0.5 < weak → C（弱档单票不升）
    assert _synergy_tier("D", "sell", "D", "sell", "D", "sell", "A")[0] == "D"  # v=-1.5 ≤ reverse → D


def test_synergy_tier_none_tier_boundary():
    # 旧快照缺 tier 字段（None）不应投票
    assert _synergy_tier(None, "buy", None, None, None, None, "A")[0] == "C"


def test_synergy_tier_lifecycle_env_downgrade():
    # 周期 B（caution）时 S 降一档为 A（v=3.0 高票一致 → S → 降 A）
    assert _synergy_tier("A", "buy", "A", "buy", "A", "buy", "B")[0] == "A"
    # 周期 B 时 A 降一档为 B（v=2.0 → A → 降 B）
    assert _synergy_tier("A", "buy", "A", "buy", "C", "hold", "B")[0] == "B"
