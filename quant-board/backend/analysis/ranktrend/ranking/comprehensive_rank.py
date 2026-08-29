# -*- coding: utf-8 -*-
"""综合排名 compScore/compRank 后端 golden 生产（2026-08-23，前后端分离 G1）。

移植前端 ComprehensiveRankEngine 的五维综合评分到后端（后端为 golden）：
compScore = 归一化(avgRankNum 反)*HOT_RANK + 归一化(zljzb)*MONEY_RATIO
          + 归一化(fundPenetration)*FUND_PENETRATION + 换手率得分*TURNOVER_RATE
          + 归一化(turnover)*VOLUME
compRank = compScore 降序序号（并列按 code 稳定排序）。

纯函数，由 analyze/快照采集链路调用并入库。
"""
from __future__ import annotations

import math
from typing import Any

# 五维权重（与前端 COMPREHENSIVE_WEIGHTS 一致，防漂移见 tests/test_comprehensive_rank.py 金标准断言）
HOT_RANK = 0.45
MONEY_RATIO = 0.25
FUND_PENETRATION = 0.10
TURNOVER_RATE = 0.12
VOLUME = 0.08

OPTIMAL_TURNOVER = 15.0
TURNOVER_SIGMA = 10.0


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return default
    return val if math.isfinite(val) else default


def _normalize(val: float, low: float, high: float, reverse: bool = False) -> float:
    """min-max 归一化到 0-100；reverse=True 时 min→100（排名反，越小越好）。"""
    if high == low or not (math.isfinite(low) and math.isfinite(high)):
        if val > 0:
            return 0.0 if reverse else 100.0
        if val < 0:
            return 100.0 if reverse else 0.0
        return 50.0
    score = ((val - low) / (high - low)) * 100
    clamped = min(100.0, max(0.0, score))
    return 100.0 - clamped if reverse else clamped


def _turnover_score(rate: float) -> float:
    return 100.0 * math.exp(-((rate - OPTIMAL_TURNOVER) ** 2) / (2 * TURNOVER_SIGMA ** 2))


def compute_comprehensive_scores(stocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为每只股票计算 compScore（五维加权），并赋 compRank（降序稳定序号）。"""
    if not stocks:
        return []
    valid = [s for s in stocks if isinstance(s, dict)]
    if not valid:
        return []

    # 五维 min/max 基线（与前端 updateMinMax 一致）
    stats = {
        "avgRankNum": (math.inf, -math.inf),
        "zljzb": (math.inf, -math.inf),
        "fundPenetration": (math.inf, -math.inf),
        "turnover": (math.inf, -math.inf),
    }
    raw_scores: dict[int, float | None] = {}
    for s in valid:
        avg = _num(s.get("avgRankNum"))
        zljzb = _num(s.get("zljzb"))
        fund = _num(s.get("fundPenetration"))
        turnover = _num(s.get("turnover"))
        for key, val in (("avgRankNum", avg), ("zljzb", zljzb), ("fundPenetration", fund), ("turnover", turnover)):
            if val is None:
                continue
            if val < stats[key][0]:
                stats[key] = (val, stats[key][1])
            if val > stats[key][1]:
                stats[key] = (stats[key][0], val)

    for s in valid:
        avg = _num(s.get("avgRankNum"))
        zljzb = _num(s.get("zljzb"))
        fund = _num(s.get("fundPenetration"))
        turnover = _num(s.get("turnover"))
        turnover_rate = _num(s.get("turnoverRate"))
        components = (
            (avg, HOT_RANK, lambda value: _normalize(value, stats["avgRankNum"][0], stats["avgRankNum"][1], reverse=True)),
            (zljzb, MONEY_RATIO, lambda value: _normalize(value, stats["zljzb"][0], stats["zljzb"][1], reverse=False)),
            (fund, FUND_PENETRATION, lambda value: _normalize(value, stats["fundPenetration"][0], stats["fundPenetration"][1], reverse=False)),
            (turnover_rate, TURNOVER_RATE, _turnover_score),
            (turnover, VOLUME, lambda value: _normalize(value, stats["turnover"][0], stats["turnover"][1], reverse=False)),
        )
        available = [(weight, scorer(value)) for value, weight, scorer in components if value is not None]
        score = sum(weight * value for weight, value in available) / sum(weight for weight, _ in available) if available else None
        raw_scores[id(s)] = score
        s["compScore"] = round(score, 4) if score is not None else None
        missing = [
            key for key in ("avgRankNum", "zljzb", "fundPenetration", "turnoverRate", "turnover")
            if s.get(key) is None or not math.isfinite(_num(s.get(key), float("nan")))
        ]
        s["qualityFlags"] = ["missing_comprehensive_fields"] if missing else []
        s["missingFields"] = missing

    # 降序序号（并列按 code 稳定排序）
    ranked = sorted(valid, key=lambda s: (-(raw_scores.get(id(s)) if raw_scores.get(id(s)) is not None else -1.0), str(s.get("code") or "")))
    for index, s in enumerate(ranked, start=1):
        s["compRank"] = index
    return valid
