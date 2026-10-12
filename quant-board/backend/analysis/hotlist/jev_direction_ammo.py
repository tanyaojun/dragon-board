# -*- coding: utf-8 -*-
"""jev 方向独立裁决线（v3-gate）判据冻结件。

预登记单一事实源：docs/hotlist-jev/jev-direction-standalone-preregistration.md §五（判据与本文件
逐字一致，改动任何一项=改门须用户点头）。判读时点=盘中 11:00 槽帧；原料=跨日出现序列（引擎
_build_code_attention_series 同源口径）+Position Stats 日级锚现算+量价行+Market Gate（热榜情绪
相位带 as-of，固定分线 40/60/75 切 冷/弱/强/高峰 四带）。计分=隔日涨幅，hold 遇 |≥5%| 算错。
测试：tests/hotlist/test_jev_direction_gate.py 判据 VERBATIM 锁定。
"""
from __future__ import annotations

from typing import Any

QUESTION_SET_VERSION = "v3-gate"
AMMO_VERSION = "2026-10-13a"
DIRECTION_SLOT = "11:00"

QUESTIONS_A: dict[str, dict] = {
    "direction": {
        "type": "choice",
        "instructions": "You are given descriptive raw data for one stock from a hot-list attention ranking system — NO pre-computed tiers, signals, or conclusions. Data: [Attention Series] the stock's last appearances across days and intraday slots (percentile 0-100, higher = hotter; last line = current intraday reading); [Position Stats] day-level anchors; [Volume-Price] today's intraday price-volume-capital row; [Market Gate] the market environment for buy decisions (hot-list sentiment score, market stage, pool breadth); [Market Context] pool median 3-trading-day percentile change (the stock only counts as strong if it OUTPACES this baseline). Task: judge the stock's short-term directional state AS OF THIS INTRADAY MOMENT: buy / sell / hold / insufficient, with a confidence between 0 and 1. Reading guide: (1) A trend requires a multi-day same-direction movement across the series — a single-bar spike is not a trend; judge the swing across days, not the noise between consecutive appearances; a jump AGAINST the prevailing multi-day direction vetoes that direction; a choppy back-and-forth path reduces confidence. (2) Volume-price confirmation: price up on expanding volume (ratio above 1 but not above 2.5) confirms; volume ratio above 2.5 on an up day is distribution suspicion; an abnormally HIGH net ratio (above +20%) is blow-off/wash-trading suspicion, NOT bullish; a strongly negative net ratio (about -10% or worse) suggests distribution; price down on expanding volume is the strongest sell evidence; a limit-up flag is a real but untradeable signal (never buy evidence); a limit-down flag means panic selling. (3) insufficient is ONLY for unavailable data (a too-short series or missing market context); conflicting evidence means hold. Lower confidence when evidence conflicts or fields are missing. (5) ENVIRONMENT GATE for buy (applies to the FINAL call): buy is allowed ONLY when BOTH gates pass. Gate 1 — lifecycle position: the stock must sit in an ignition/expansion position (appearing consistently, percentile rising from a low or mid base, shallow drawdown); a crowded position (long hot-zone stay with decaying velocity) or a reversal/retreat phase (3-trading-day net change clearly negative with a deep 15+ point drawdown, or 5+ consecutive falling percentile days) FAILS the gate — never buy, at most hold, or sell with collapse evidence. Gate 2 — market sentiment PHASE BAND, by the fixed phase lines given in [Market Gate] (cold <40 / weak 40-60 / strong 60-75 / peak >=75): buy is allowed ONLY in the strong band; in the peak band (>=75, crowded blow-off top), the cold band (<40) and the weak band (40-60, materially a retreat phase) buy is BLOCKED — a bullish reading in a blocked band must be downgraded to hold, or sell with collapse evidence.",
        "criteria": {
            "buy": "Multi-day percentile rise outpacing the market baseline; volume-price confirming; BOTH environment gates pass (ignition/expansion lifecycle position AND sentiment phase band = strong).",
            "sell": "Multi-day percentile fall/collapse with market-relative weakness; and/or price down on expanding volume; and/or net outflow or abnormally negative net ratio; and/or reversal/retreat phase with collapse evidence.",
            "hold": "Evidence mixed or conflicting, magnitudes too weak, OR a failed buy gate without sell evidence.",
            "insufficient": "ONLY data unavailability. Never for conflicting evidence."
        }
    }
}


QUESTIONS_B1: dict[str, dict] = {
    "trend_direction": {
        "type": "choice",
        "instructions": "You are given a stock's cross-day attention rank percentile series (last appearances across days and slots, time-ascending; the LAST line is the current intraday reading) plus day-level position stats and the market baseline. All changes are in percentile points, positive = attention rising; drawdown is the distance below the peak. Judge ONLY the attention-momentum direction of the STOCK ITSELF: buy / sell / hold, confidence between 0 and 1. buy requires ALL of: a multi-day same-direction rise across the series, outpacing the market median 3-trading-day change (compare directly), and NOT a reversal/retreat phase (3-trading-day net change clearly negative with a deep 15+ point drawdown, or 5+ consecutive falling percentile days — NEVER buy). sell: sustained multi-day fall or collapse, or clear market-relative weakness. hold: mixed, weak, or conflicting evidence. Lower your confidence when evidence conflicts or key fields are missing.",
        "criteria": {
            "buy": "Multi-day percentile rise outpacing the baseline, no reversal/retreat phase.",
            "sell": "Sustained multi-day fall/collapse or market-relative weakness.",
            "hold": "Mixed, weak, or conflicting evidence."
        }
    }
}


QUESTIONS_B2: dict[str, dict] = {
    "vp_direction": {
        "type": "choice",
        "instructions": "You are given ONLY price-volume-capital data for one stock at this intraday moment: change%, volume ratio (vs 5-day same-time-of-day average), main-force net flow (100M CNY; positive = inflow), main-force net ratio (%), turnover%, limit-up/down flags. Judge ONLY the price-volume direction: buy / sell / hold, confidence between 0 and 1. buy: price up on expanding volume (ratio above 1 but not above 2.5 — above 2.5 on an up day is distribution suspicion) with positive net flow and net ratio NOT above +20% (above +20% is blow-off/wash-trading suspicion, NOT bullish); a limit-up flag alone is a real but untradeable signal — do NOT count it as buy. sell: price down on expanding volume, or net ratio about -10% or worse, or the limit-down flag. hold: mild moves, shrinking volume without limit-up, or contradictory signals.",
        "criteria": {
            "buy": "Up on healthy expanding volume with positive, sane net ratio.",
            "sell": "Down on expanding volume, strong outflow, or limit-down.",
            "hold": "Mild or contradictory price-volume signals."
        }
    }
}


QUESTIONS_B3: dict[str, dict] = {
    "final_direction": {
        "type": "choice",
        "instructions": "Two independent judgments were made on the same stock at this intraday moment: JUDGMENT 1 read the cross-day attention trajectory; JUDGMENT 2 read the price-volume data. Their choices and confidences are below, with the position stats, market gate and market context. Output the FINAL call: buy / sell / hold / insufficient, confidence between 0 and 1. Apply the synthesis rules IN ORDER: (1) a judgment of hold means that layer found NO direction — it is NOT a vote against the other layer's direction. (2) If one layer gives a direction and the other holds, FOLLOW the directional layer (the holding layer neither confirms nor opposes), with confidence equal to the directional layer's confidence reduced somewhat (unconfirmed). (3) If both give the SAME direction, follow it with confidence equal to the higher of the two, raised if both are high. (4) If they give OPPOSITE directions, this is a true conflict: hold, UNLESS one side's confidence clearly dominates (difference of 0.4 or more), in which case follow the dominant side with reduced confidence. (5) a limit-up flag means a real but untradeable signal — never the final buy. (5) ENVIRONMENT GATE for buy (applies to the FINAL call): buy is allowed ONLY when BOTH gates pass. Gate 1 — lifecycle position: the stock must sit in an ignition/expansion position (appearing consistently, percentile rising from a low or mid base, shallow drawdown); a crowded position (long hot-zone stay with decaying velocity) or a reversal/retreat phase (3-trading-day net change clearly negative with a deep 15+ point drawdown, or 5+ consecutive falling percentile days) FAILS the gate — never buy, at most hold, or sell with collapse evidence. Gate 2 — market sentiment PHASE BAND, by the fixed phase lines given in [Market Gate] (cold <40 / weak 40-60 / strong 60-75 / peak >=75): buy is allowed ONLY in the strong band; in the peak band (>=75, crowded blow-off top), the cold band (<40) and the weak band (40-60, materially a retreat phase) buy is BLOCKED — a bullish reading in a blocked band must be downgraded to hold, or sell with collapse evidence. (6) insufficient ONLY for unavailable data. Never hold merely because the two layers differ in strength.",
        "criteria": {
            "buy": "Directional layer says buy and the other holds or agrees, or the buy side clearly dominates a conflict — AND both environment gates pass (ignition/expansion position AND sentiment phase band = strong).",
            "sell": "Directional layer says sell and the other holds or agrees, or the sell side clearly dominates a conflict — veto phase with collapse evidence also sells.",
            "hold": "True opposite-direction conflict without a dominant side, both layers hold, a failed buy gate without sell evidence, or a veto blocking buy.",
            "insufficient": "Data unavailable only."
        }
    }
}


def questions_hash(questions: dict[str, dict]) -> str:
    """判据指纹（幂等 done-skip 与代际追溯用）。"""
    import hashlib
    import json as _json
    return hashlib.sha256(_json.dumps(questions, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def band_of(score: Any) -> str | None:
    """热榜情绪分 → 相位带（固定分线 40/60/75；与判据 [Market Gate] 口径一致）。"""
    if not isinstance(score, (int, float)):
        return None
    if score >= 75:
        return "peak"
    if score >= 60:
        return "strong"
    if score >= 40:
        return "weak"
    return "cold"
