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
AMMO_VERSION = "2026-10-13b"
DIRECTION_SLOT = "11:00"

QUESTIONS_A: dict[str, dict] = {
    "direction": {
        "type": "choice",
        "instructions": "You are given descriptive raw data for one stock from a hot-list attention ranking system — NO pre-computed tiers, signals, or conclusions. Data: [Attention Series] the stock's last appearances across days and intraday slots (percentile 0-100, higher = hotter; last line = current intraday reading); [Position Stats] day-level anchors; [Volume-Price] today's intraday price-volume-capital row; [Market Gate] the market environment for buy decisions (hot-list sentiment score, market stage, pool breadth); [Market Context] pool median 3-trading-day percentile change (the stock only counts as strong if it OUTPACES this baseline). Task: judge the stock's short-term directional state AS OF THIS INTRADAY MOMENT: buy / sell / hold / insufficient, with a confidence between 0 and 1. Reading guide: (1) A trend requires a multi-day same-direction movement across the series — a single-bar spike is not a trend; judge the swing across days, not the noise between consecutive appearances; a jump AGAINST the prevailing multi-day direction vetoes that direction; a choppy back-and-forth path reduces confidence. (2) Volume-price confirmation: price up on expanding volume (ratio above 1 but not above 2.5) confirms; volume ratio above 2.5 on an up day is distribution suspicion; an abnormally HIGH net ratio (above +20%) is blow-off/wash-trading suspicion, NOT bullish; a strongly negative net ratio (about -10% or worse) suggests distribution; price down on expanding volume is the strongest sell evidence; a limit-up flag is a real but untradeable signal (never buy evidence); a limit-down flag means panic selling; price-volume evidence showing no clear direction does NOT block a trajectory-based direction — it only lowers the confidence. (3) insufficient is ONLY for unavailable data (a too-short series or missing market context); conflicting evidence means hold. Lower confidence when evidence conflicts or fields are missing. (5) ENVIRONMENT GATE for buy (applies to the FINAL call): buy is allowed ONLY when BOTH gates pass. Gate 1 — lifecycle position: the stock must sit in an ignition/expansion position (appearing consistently, percentile rising from a low or mid base, shallow drawdown); a crowded position (long hot-zone stay with decaying velocity) or a reversal/retreat phase (3-trading-day net change clearly negative with a deep 15+ point drawdown, or 5+ consecutive falling percentile days) FAILS the gate — never buy, at most hold, or sell with collapse evidence. Gate 2 — market sentiment PHASE BAND, by the fixed phase lines given in [Market Gate] (cold <40 / weak 40-60 / strong 60-75 / peak >=75): buy is allowed ONLY in the strong band; in the peak band (>=75, crowded blow-off top), the cold band (<40) and the weak band (40-60, materially a retreat phase) buy is BLOCKED — a bullish reading in a blocked band must be downgraded to hold, or sell with collapse evidence.",
        "criteria": {
            "buy": "Multi-day percentile rise outpacing the market baseline; volume-price confirming; BOTH environment gates pass (ignition/expansion lifecycle position AND sentiment phase band = strong).",
            "sell": "Multi-day percentile fall/collapse with market-relative weakness; and/or price down on expanding volume; and/or net outflow or abnormally negative net ratio; and/or reversal/retreat phase with collapse evidence.",
            "hold": "Evidence mixed or conflicting, magnitudes too weak, OR a failed buy gate without sell evidence.",
            "insufficient": "ONLY data unavailability. Never for conflicting evidence."
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
