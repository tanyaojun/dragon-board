"""五组轮动因子：全部纯函数，输入为跨槽位 sector/stock rows，输出 0-100 或 None。"""

from __future__ import annotations

import math
import statistics
from typing import Any, Protocol

from backend.analysis.theme.heat_level import resolve_heat_level


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def robust_z(value: float, values: list[float]) -> float:
    """稳健 z-score：(value - median) / (MAD + 1e-9)。"""
    if not values:
        return 0.0
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values]) if len(values) > 1 else 0.0
    return (value - median) / (mad + 1e-9)


def z_to_score(z: float, slope: float = 16.7) -> float:
    """稳健 z 映射到 0-100：z=0 → 50。"""
    return _clamp(50.0 + slope * z)


def linear_slope(values: list[float]) -> float | None:
    """按槽位序号做最小二乘斜率（每槽单位）。"""
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(values) / n
    denom = sum((x - x_mean) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, values)) / denom


def strength_score(
    row: dict[str, Any],
    history_heats: list[float],
    all_current_heats: list[float],
    market_change: float | None,
    prev_zt_count: float | None,
) -> tuple[float | None, list[str]]:
    """强度/动量：heat、横向 z、heat 斜率、涨停动能、板块超额。

    热度统一走 heat_level.resolve_heat_level（design §4.2）：heatLevel 相对分缺失时
    按缺失返回（missing 标记沿用 "heatScore" 名，rotation 合同不变），由
    combine_scores 按可用因子归一。"""
    missing: list[str] = []
    heat = resolve_heat_level(row)
    if heat is None:
        missing.append("heatScore")
        return None, missing
    heat_score = _clamp(heat)

    z = robust_z(heat, all_current_heats)
    cross_z_score = z_to_score(z)

    series = [*history_heats, heat]
    slope = linear_slope(series)
    slope_score = _clamp(50.0 + (slope or 0.0) * 20.0)

    zt_count = _num(row.get("ztCount"), 0.0) or 0.0
    zt_delta = zt_count - (prev_zt_count or 0.0)
    zt_score = _clamp(zt_count * 6.0 + max(0.0, zt_delta) * 10.0)

    theme_change = _num(row.get("change"))
    if theme_change is not None and market_change is not None:
        excess_score = _clamp(50.0 + (theme_change - market_change) * 12.0)
    else:
        missing.append("excess")
        excess_score = None

    parts: list[float] = []
    weights: list[float] = []
    for value, weight in (
        (heat_score, 0.30),
        (cross_z_score, 0.20),
        (slope_score, 0.20),
        (zt_score, 0.15),
    ):
        parts.append(value)
        weights.append(weight)
    if excess_score is not None:
        parts.append(excess_score)
        weights.append(0.15)
    total_w = sum(weights)
    score = sum(p * w for p, w in zip(parts, weights)) / total_w
    return _clamp(score), missing


def flow_score(
    row: dict[str, Any],
    inflow_series: list[float | None],
    all_current_inflows: list[float],
    positive_streak: int,
) -> tuple[float | None, list[str]]:
    """资金：主力净流入、加速度、集中度、持续性。"""
    missing: list[str] = []
    inflow = _num(row.get("mainNetInflow"))
    if inflow is None:
        missing.append("mainNetInflow")
        return None, missing

    inflow_z = z_to_score(robust_z(inflow, all_current_inflows))

    deltas: list[float] = []
    for prev in inflow_series[-3:]:
        if prev is not None:
            deltas.append(inflow - prev)
    if deltas:
        total_delta = sum(deltas)
        accel_score = _clamp(
            50.0
            + (1.0 if total_delta >= 0 else -1.0) * min(30.0, abs(total_delta) * 3.0)
        )
    else:
        missing.append("flowAcceleration")
        accel_score = None

    positive = [v for v in all_current_inflows if v and v > 0]
    total_positive = sum(positive)
    if total_positive > 0:
        share = inflow / total_positive
        concentration_score = _clamp(share * 300.0)
    else:
        missing.append("flowConcentration")
        concentration_score = None

    persistence_score = _clamp(positive_streak * 20.0)

    parts = [inflow_z, persistence_score]
    weights = [0.35, 0.20]
    if accel_score is not None:
        parts.append(accel_score)
        weights.append(0.25)
    if concentration_score is not None:
        parts.append(concentration_score)
        weights.append(0.20)
    total_w = sum(weights)
    return _clamp(sum(p * w for p, w in zip(parts, weights)) / total_w), missing


def breadth_score(
    row: dict[str, Any],
    prev_row: dict[str, Any] | None,
    theme_stocks: list[dict[str, Any]],
    prev_theme_stocks: list[dict[str, Any]] | None,
) -> tuple[float | None, list[str]]:
    """宽度/结构：板块宽度、晋级率、连板梯队、龙头集中度。"""
    missing: list[str] = []
    breadth = _num(row.get("breadthScore"))
    if breadth is None:
        missing.append("breadthScore")
        return None, missing

    prev_breadth = _num(prev_row.get("breadthScore")) if prev_row else None
    breadth_change = (breadth - prev_breadth) if prev_breadth is not None else 0.0
    breadth_change_score = _clamp(50.0 + breadth_change * 4.0)

    boards = sorted(
        (int(_num(s.get("boardHeight"), 0) or 0) for s in theme_stocks),
        reverse=True,
    )
    if boards:
        max_board = boards[0]
        second_board = boards[1] if len(boards) > 1 else 0
        ladder_score = _clamp(max_board * 12.0 + max(0, max_board - second_board) * 6.0)
    else:
        missing.append("boardHeight")
        ladder_score = None

    promotion_score: float | None = None
    if prev_theme_stocks:
        prev_zt = [
            s
            for s in prev_theme_stocks
            if str(s.get("leadStatus") or "").strip() == "涨停"
            or (_num(s.get("change"), 0) or 0) >= 9.5
        ]
        continuation = [
            s for s in theme_stocks if int(_num(s.get("boardHeight"), 0) or 0) >= 2
        ]
        if prev_zt:
            promotion_score = _clamp((len(continuation) / len(prev_zt)) * 150.0)
        else:
            missing.append("promotion")
    else:
        missing.append("promotion")

    stock_count = len(theme_stocks)
    leader_count = sum(
        1 for s in theme_stocks if str(s.get("leadStatus") or "").find("龙") >= 0
    )
    leader_score = _clamp((leader_count / stock_count) * 150.0) if stock_count else None
    if leader_score is None:
        missing.append("leaderCount")

    parts = [breadth, breadth_change_score]
    weights = [0.30, 0.20]
    if ladder_score is not None:
        parts.append(ladder_score)
        weights.append(0.25)
    if promotion_score is not None:
        parts.append(promotion_score)
        weights.append(0.15)
    if leader_score is not None:
        parts.append(leader_score)
        weights.append(0.10)
    total_w = sum(weights)
    return _clamp(sum(p * w for p, w in zip(parts, weights)) / total_w), missing


def crowding_score(
    row: dict[str, Any],
    crowding_series: list[float],
    theme_stocks: list[dict[str, Any]],
) -> tuple[float | None, list[str]]:
    """拥挤/风险：crowdingRisk、拥挤变化、量能高分位偏离。"""
    missing: list[str] = []
    crowding = _num(row.get("crowdingRisk"))
    if crowding is None:
        missing.append("crowdingRisk")
        return None, missing

    base = _clamp(crowding)
    if len(crowding_series) >= 2:
        change = crowding - crowding_series[-2]
    elif len(crowding_series) == 1:
        change = crowding - crowding_series[0]
    else:
        change = 0.0
    change_score = _clamp(50.0 + change * 2.0)

    ratios = sorted(
        _num(s.get("volumeRatio")) for s in theme_stocks if _num(s.get("volumeRatio")) is not None
    )
    if ratios:
        p90 = ratios[min(len(ratios) - 1, int(len(ratios) * 0.9))]
        volume_score = _clamp(p90 * 40.0)
    else:
        missing.append("volumeRatio")
        volume_score = None

    parts = [base, change_score]
    weights = [0.50, 0.30]
    if volume_score is not None:
        parts.append(volume_score)
        weights.append(0.20)
    total_w = sum(weights)
    return _clamp(sum(p * w for p, w in zip(parts, weights)) / total_w), missing


def lifecycle_score(
    prev_lifecycle: str | None,
    rank_changes: list[int],
) -> tuple[float | None, list[str]]:
    """轮动位置：状态连续性与 rank 波动。"""
    missing: list[str] = []
    if prev_lifecycle is None:
        missing.append("prevLifecycle")
        continuity = 50.0
    else:
        continuity = {
            "ice": 30.0,
            "emerging": 70.0,
            "expanding": 100.0,
            "climax": 70.0,
            "cooling": 30.0,
        }.get(prev_lifecycle, 50.0)

    if rank_changes:
        mean_abs = sum(abs(r) for r in rank_changes) / len(rank_changes)
        rank_vol = _clamp(100.0 - mean_abs * 8.0)
    else:
        missing.append("rankHistory")
        rank_vol = None

    if rank_vol is None:
        return _clamp(continuity), missing
    return _clamp(continuity * 0.6 + rank_vol * 0.4), missing


class ThemeFactorScoresLike(Protocol):
    def available(self) -> list[str]: ...


def combine_scores(
    scores: ThemeFactorScoresLike,
    weights: dict[str, float],
    min_factors: int = 3,
) -> float | None:
    """按可用因子归一化权重求 rotationScore；可用因子 < min_factors 返回 None（M1 生效）。"""
    available = scores.available()
    if len(available) < min_factors:
        return None
    total_w = sum(weights[k] for k in available)
    if total_w <= 0:
        return None
    return _clamp(sum(getattr(scores, k) * weights[k] for k in available) / total_w)
