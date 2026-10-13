# -*- coding: utf-8 -*-
"""jev 方向线（v4-material）判据冻结件。

预登记单一事实源：docs/hotlist-jev/jev-direction-v4-preregistration.md §五（判据与本文件
逐字一致，改动任何一项=改门须用户点头）。v4 与 v3 的代际差异=原料合同重写（八块，审计
文档 jev-direction-material-audit.md）+人口全池（2026-10-13 用户裁决）：v3 Gate1 让模型
从 5 个分位自判生命周期（病根），v4 改锚具体字段——板序（●○ 模式）/TDX 位置轴/板型三件套/
市场 as-of 帧/摆动锚。原料组装：backend/operations/jev_direction_gate.py（build_state_v4）。
计分口径冻结：判读=11:00 槽帧；验证=隔日涨幅；hold 遇 |隔日|≥5% 算错。
测试：tests/hotlist/test_jev_direction_gate.py 判据 VERBATIM 锁定。
"""
from __future__ import annotations

from typing import Any

QUESTION_SET_VERSION = "v4-material"
AMMO_VERSION = "2026-10-13a"
DIRECTION_SLOT = "11:00"

QUESTIONS: dict[str, dict] = {
    "direction": {
        "type": "choice",
        "instructions": "You are given descriptive raw data for one stock from a hot-list attention ranking system — NO pre-computed tiers, signals, or conclusions. Data blocks: [Attention Series] daily-folded attention percentiles (0-100, higher = hotter rank in the pool) with a history-depth header — depth below 5 trading days (FIRST-SEEN) means the series is NOT usable as primary evidence; [Position] TDX daily price axis (distance to 20-day high, 20-day window gain, days since window low, 5-day contribution, volume vs 3-day average) plus the board sequence (last 10 trading days, ● = limit-up close, ○ = not; last cell is today) with current consecutive-board count; [Volume-Price + Board Type] today's intraday change, volume ratio, main-force net flow and net ratio, turnover, and if the stock is at limit — first seal time, last seal time, seal order size, board height; [Market as-of 11:00] same-source market frame facts: limit-up count, zhaban (failed limits) count and rate, big-drawdown count, max board, THS intraday pools (failed/drawdown/rushing), frame seal quality (one-word boards / hard boards / rotten boards with share and average success rate), pool breadth; [Swing Anchor] the market's limit-up count peak and trough over the last 11 trading days with days-ago, today's intraday value, delta vs yesterday and distance from peak; [Themes] collection-fact sector labels; [Data Quality] self-reported missing fields; [Market Gate] hot-list sentiment phase band by fixed lines (cold <40 / weak 40-60 / strong 60-75 / peak >=75), pool median 3-trading-day percentile change, pool breadth (share of pool rising). Task: judge the stock's short-term directional state AS OF THIS INTRADAY 11:00 MOMENT: buy / sell / hold / insufficient, with a confidence between 0 and 1. Reading guide: (1) SERIES: use the attention series as PRIMARY evidence only when history depth is 5+ trading days; for FIRST-SEEN / short history rely on Position and Board sequence and Board type instead, lower confidence, and NEVER cite history that is not shown. A trend requires a multi-day same-direction movement (read the day-over-day direction list, not slot noise); a jump AGAINST the prevailing multi-day direction vetoes that direction; 3+ consecutive falling days is retreat evidence; a choppy back-and-forth path reduces confidence. (2) POSITION + BOARD SEQUENCE: rising consecutive-board trajectory at a low position (more than 20% below the 20-day high, or the window low within 8 trading days) = ignition/expansion; stagnant or declining board trajectory at a high position (within 10% of the 20-day high, or the window low 15+ trading days ago) = crowded; a board-sequence break (last cell flipping from ● to ○) with a deep drawdown = reversal. (3) VOLUME-PRICE + BOARD TYPE: price up on volume ratio between 1 and 2.5 confirms; volume ratio above 2.5 on an up day is distribution suspicion; a net ratio above +20% is blow-off/wash-trading suspicion, NOT bullish; a net ratio of -10% or worse suggests distribution; price down on expanding volume is the strongest sell evidence; a one-word limit board (first seal = last seal = 09:25 with a huge seal order) is a real but UNTRADEABLE signal — never buy evidence; rotten boards, repeated seal breaks, or huge volume without price progress are disagreement warnings. (4) MARKET as-of + SWING ANCHOR: when the market sits near its swing peak with a rising zhaban rate and big-drawdown count, the tone is retreat — raise the bar for buy and amplify sell evidence; near the trough with zhaban converging, late-washout — do not chase sell; missing market facts are treated as missing — never substitute them with the sentiment score. (5) ENVIRONMENT GATE for buy (applies to the FINAL call): buy is allowed ONLY when BOTH gates pass. Gate 1 — position: the stock must sit in an ignition/expansion position (board trajectory rising AND not at a high position); a crowded or reversal position FAILS the gate — never buy, at most hold, or sell with collapse evidence. Gate 2 — sentiment PHASE BAND by the fixed lines in [Market Gate]: buy is allowed ONLY in the strong band; in the peak band (>=75), the cold band (<40) and the weak band (40-60) buy is BLOCKED — a bullish reading in a blocked band must be downgraded to hold, or sell with collapse evidence. (6) insufficient is ONLY for unavailable data (missing blocks per [Data Quality]); conflicting evidence means hold. Lower confidence when evidence conflicts or fields are missing.",
        "criteria": {
            "buy": "Attention series multi-day rise (history depth 5+) outpacing the pool median; position = ignition/expansion (rising board trajectory, low position); volume-price confirming with a normal net ratio; BOTH environment gates pass (position gate AND sentiment phase band = strong).",
            "sell": "Multi-day attention fall, 3+ consecutive falling days, or a series veto by an against-trend jump; and/or high position with board-type disagreement (rotten board, repeated seal breaks, huge volume without progress); and/or price down on expanding volume or net ratio -10% or worse; and/or a board-sequence break with deep drawdown (reversal); amplified when the market sits near its swing peak with rising zhaban and drawdowns.",
            "hold": "Evidence mixed or conflicting, magnitudes too weak, a failed buy gate without sell evidence, or a bullish reading in a blocked sentiment band.",
            "insufficient": "ONLY data unavailability per [Data Quality] (missing blocks). Never for conflicting evidence."
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
