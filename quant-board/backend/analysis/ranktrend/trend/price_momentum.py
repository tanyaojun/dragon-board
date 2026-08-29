# -*- coding: utf-8 -*-
"""价格动量观察因子（2026-08-17 审计缺口 G1 修复）。

背景：趋势维度（momentum/MA5/MA10/MACD/zeroCross）全部计算在排名百分位时序上，
价格（change 涨跌幅）只进量价（单帧）与 fallback（样本不足降级）——价格时序信息
完全没进趋势主信号。排名上升≠价格上涨（全市场普涨时排名不动但价格涨）。

本模块补价格口径观察（不进 synergy 投票，先验证区分度，同 crossSection 流程）：
- priceMaShort/priceMaLong：change 序列均线（价格均线）方向 up/down/steady
- priceMomentumScore：短周期 change 均值（价格动量，buy/sell/hold）
- signalTier：A 强（动量 buy + 均线上行）/ B 偏强 / C 偏弱 / D 弱 / unknown（时序不足）
- MACD 不做价格口径（G5 定义：MACD 金死叉 = 排名百分位计算，非价格 MACD）
"""
from __future__ import annotations

import math
from typing import Any

PRICE_MOMENTUM_DEFAULTS: dict[str, float] = {
    "priceMaShort": 5.0,
    "priceMaLong": 10.0,
    "priceMomentumPeriod": 3.0,
    "priceMomentumScoreThreshold": 0.5,
}


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def compute_price_momentum(price_changes: list[Any], config: Any) -> dict[str, Any]:
    """计算个股价格动量观察。

    Args:
        price_changes: 个股 change（涨跌幅，%）历史序列（[-1] 为当前帧；无效值 None/NaN 跳过）。
        config: RankTrendConfig（priceMaShort/priceMaLong/priceMomentumPeriod/
            priceMomentumScoreThreshold）。

    Returns:
        observation.priceMomentum 结构：priceMaShort/priceMaLong/maTrend/
        momentumScore/momentumSignal/signalTier（A/B/C/D/unknown）/tierReasons/invalidCount。
    """
    changes = [_finite(v) for v in (price_changes or [])]
    invalid_count = sum(1 for v in changes if v is None)
    valid = [v for v in changes if v is not None]
    ma_short = int(getattr(config, "priceMaShort", 5))
    ma_long = int(getattr(config, "priceMaLong", 10))
    mom_period = int(getattr(config, "priceMomentumPeriod", 3))
    threshold = float(getattr(config, "priceMomentumScoreThreshold", 0.5))

    if len(valid) < max(ma_short, ma_long, mom_period):
        return {
            "priceMaShort": None,
            "priceMaLong": None,
            "maTrend": "steady",
            "momentumScore": None,
            "momentumSignal": "hold",
            "signalTier": "unknown",
            "tierReasons": [f"价格时序不足（有效 {len(valid)} < 需求 {max(ma_short, ma_long, mom_period)}）"],
            "invalidCount": invalid_count,
        }

    ma_s = _mean(valid[-ma_short:])
    ma_l = _mean(valid[-ma_long:])
    ma_trend = "up" if ma_s > ma_l else "down" if ma_s < ma_l else "steady"
    mom_score = _mean(valid[-mom_period:]) or 0.0

    if mom_score >= threshold and ma_trend == "up":
        tier, reasons = "A", ["价格动量 buy + 短均线高于长均线（价格趋势上行）"]
    elif mom_score >= threshold:
        tier, reasons = "B", ["价格动量 buy（均线未确认）"]
    elif mom_score <= -threshold and ma_trend == "down":
        tier, reasons = "D", ["价格动量 sell + 短均线低于长均线（价格趋势下行）"]
    elif mom_score <= -threshold:
        tier, reasons = "C", ["价格动量 sell（均线未确认）"]
    elif ma_trend == "up":
        tier, reasons = "B", ["均线上行但动量不足"]
    elif ma_trend == "down":
        tier, reasons = "C", ["均线下行但动量不足"]
    else:
        tier, reasons = "C", ["价格无明确方向"]

    return {
        "priceMaShort": ma_s,
        "priceMaLong": ma_l,
        "maTrend": ma_trend,
        "momentumScore": round(mom_score, 4),
        "momentumSignal": "buy" if mom_score >= threshold else "sell" if mom_score <= -threshold else "hold",
        "signalTier": tier,
        "tierReasons": reasons,
        "invalidCount": invalid_count,
    }
