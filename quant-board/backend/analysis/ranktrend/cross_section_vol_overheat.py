# -*- coding: utf-8 -*-
"""crossSection 追强 × ATR 波动 → 过热/超卖回归校准（观察信号，不进 synergy）。
纯函数：输入 crossSection 档 + 该股 pct_vol 相对当帧全体的分位(0-1)，返回观察信号契约。
设计文档 ranktrend-percentile-atr-fusion-signal-design.md §3/§4。
"""
from __future__ import annotations

import math
from typing import Any

STRONG = ("A", "B")
WEAK = ("C", "D")


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def analyze_cross_section_overheat(cross_tier: str | None, vol_rank: float | None, config: Any) -> dict[str, Any]:
    p33 = float(getattr(config, "crossVolP33", 0.33))
    p67 = float(getattr(config, "crossVolP67", 0.67))
    p90 = float(getattr(config, "crossVolP90", 0.90))
    rank = _finite(vol_rank)
    if cross_tier not in (*STRONG, *WEAK) or rank is None:
        return {"status": "insufficient", "direction": "hold", "score": 0, "crossTier": cross_tier, "volTier": None, "pctVolRank": rank, "signalTier": "unknown", "reasons": ["crossSection 档位或波动率不可用"]}
    strong = cross_tier in STRONG
    if strong:
        if rank >= p90:
            direction, tier, reason = "sell", "S", "横截面强势 + 深度放量，过热回归风险"
        elif rank >= p67:
            direction, tier, reason = "sell", "C", "横截面强势 + 放量过热，回归风险"
        elif rank >= p33:
            direction, tier, reason = "sell", "B", "横截面强势 + 活跃偏热"
        else:
            direction, tier, reason = "hold", "A", "横截面强势 + 缩量，温和强势"
    else:
        if rank <= p33:
            direction, tier, reason = "buy", "B", "横截面弱势 + 缩量企稳，超卖回升观察"
        else:
            direction, tier, reason = "hold", "C", "横截面弱势（无缩量企稳），回避"
    score = {"S": 100, "A": 60, "B": 45, "C": 25}.get(tier, 0)
    return {"status": "ok", "direction": direction, "score": score, "crossTier": cross_tier, "volTier": None, "pctVolRank": rank, "signalTier": tier, "reasons": [reason]}
