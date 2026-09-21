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


# ---------------------------------------------------------------------------
# 八平台热榜均榜（weighted_platform_percentile_v1）
#
# 2026-09-22 从 snapshot_collector.providers._calculate_average_rank_fields 提升
# 为唯一权威实现（采集链 import 本表，防止采集/实时两处公式漂移）：
# avgRankNum = Σ 平台 (rank/榜单总数)*100*权重 / Σ 权重；rank≥DEFAULT_RANK 视为
# 该平台缺失，按 100 分（榜尾）计权。platforms = 有效平台数。
# ---------------------------------------------------------------------------

HOTLIST_PLATFORMS = ("eastmoney", "ths", "kpl", "tdx", "xueqiu", "cls", "tgb", "dzh")
HOTLIST_RANK_FIELDS = {
    "eastmoney": "emRank",
    "ths": "thsRank",
    "kpl": "kplRank",
    "tdx": "tdxRank",
    "xueqiu": "xqRank",
    "cls": "clsRank",
    "tgb": "tgbRank",
    "dzh": "dzhRank",
}
HOTLIST_WEIGHTS = {
    "kpl": 1.0,
    "tdx": 0.9,
    "ths": 0.85,
    "eastmoney": 0.75,
    "dzh": 0.7,
    "tgb": 0.4,
    "xueqiu": 0.35,
    "cls": 0.35,
}
HOTLIST_DEFAULT_RANK = 999


def average_rank_fields(
    row: dict[str, Any],
    platform_totals: dict[str, int],
) -> None:
    """按 weighted_platform_percentile_v1 赋值行的 avgRankNum/avgRank/platforms。

    与采集链入座行同公式；platform_totals 缺某平台时该平台不计权（与采集链
    ``total <= 0: continue`` 语义一致）。
    """
    weighted_sum = 0.0
    total_weight = 0.0
    platforms = 0
    for platform in HOTLIST_PLATFORMS:
        total = platform_totals.get(platform, 0)
        if total <= 0:
            continue
        field = HOTLIST_RANK_FIELDS[platform]
        weight = HOTLIST_WEIGHTS[platform]
        total_weight += weight
        rank = _safe_int_rank(row.get(field))
        if rank < HOTLIST_DEFAULT_RANK:
            platforms += 1
            weighted_sum += (rank / total) * 100 * weight
        else:
            weighted_sum += 100 * weight
    row["platforms"] = platforms
    row["avgRankNum"] = weighted_sum / total_weight if total_weight else float(HOTLIST_DEFAULT_RANK)
    row["avgRank"] = f"{row['avgRankNum']:.1f}"


def _safe_int_rank(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return HOTLIST_DEFAULT_RANK


def infer_platform_totals(stocks: list[dict[str, Any]]) -> dict[str, int]:
    """从 current 帧全池行推各平台榜单总数：每平台 rank(<DEFAULT_RANK) 的最大值。

    榜单返回前 N 名且 rank 连续时 max(rank)=N（与前端顶部状态条的平台计数一致）；
    平台整榜缺失时 total=0，average_rank_fields 会跳过该平台。
    """
    totals = {platform: 0 for platform in HOTLIST_PLATFORMS}
    for s in stocks if isinstance(stocks, list) else []:
        if not isinstance(s, dict):
            continue
        for platform, field in HOTLIST_RANK_FIELDS.items():
            rank = _safe_int_rank(s.get(field))
            if HOTLIST_DEFAULT_RANK > rank >= 1 and rank > totals[platform]:
                totals[platform] = rank
    return totals


def compute_live_ranking(
    stocks: list[dict[str, Any]],
    platform_totals: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """current_frame 实时排名（2026-09-22 用户裁决：列表均榜/综合实时口径）。

    对当前热榜合并行依次：① average_rank_fields 实时均榜（weights 与采集入库同源）；
    ② compute_comprehensive_scores 实时五维综合评分。**原地修改并返回**行列表；
    帧池 golden（快照行 compRank/avgRankNum）自此降级为 analyze 不可用时的历史回溯兜底。
    platform_totals 缺省时按行内 rank 推断（infer_platform_totals）。
    """
    valid = [s for s in (stocks or []) if isinstance(s, dict)]
    if not valid:
        return []
    # 仅未传时推断；显式传 {} 表示"无平台榜单数据"，不应被静默改为推断（语义显式化，review M6）
    totals = infer_platform_totals(valid) if platform_totals is None else platform_totals
    for row in valid:
        average_rank_fields(row, totals)
    return compute_comprehensive_scores(valid)
