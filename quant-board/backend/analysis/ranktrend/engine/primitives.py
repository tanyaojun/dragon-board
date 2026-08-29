from __future__ import annotations

import math
from typing import Any

def clamp(value: float, min_value: float, max_value: float) -> float:
    if not math.isfinite(value):
        return min_value
    return max(min_value, min(max_value, value))


def _is_finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def normalize_signed(value: float, positive_scale: float, negative_scale: float) -> float:
    scale = abs(positive_scale) if value >= 0 else abs(negative_scale)
    return clamp(math.tanh(value / max(1e-6, scale)), -1, 1)


def signal_confidence(raw_score: float, agreement_bonus: float = 0) -> float:
    return clamp(50 + abs(raw_score) * 40 + agreement_bonus, 50, 90)


def weighted_share(scores: list[float], weights: list[float], predicate) -> float:
    numerator = 0.0
    denominator = 0.0
    for index, score in enumerate(scores):
        weight = float(weights[index] if index < len(weights) else 0)
        if weight <= 0 or not math.isfinite(weight):
            continue
        denominator += weight
        if predicate(score, index):
            numerator += weight
    return numerator / denominator if denominator > 0 else 0.0




from .config import RankTrendConfig
def get_macd_min_samples(config: RankTrendConfig) -> int:
    return max(2, int(config.macdSlow))


def get_momentum_min_samples(config: RankTrendConfig) -> int:
    return max(2, int(max(config.momentumPeriods)) + 1)


def get_technical_min_computable_samples(config: RankTrendConfig) -> int:
    return max(get_macd_min_samples(config), get_momentum_min_samples(config))


def get_technical_min_samples(config: RankTrendConfig) -> int:
    return max(get_technical_min_computable_samples(config), 30)


def percentile_rank(rank: float, total_count: int) -> float:
    if rank <= 0 or total_count <= 0:
        return 0.0
    return ((total_count - rank + 1) / total_count) * 100


def attention_rank_lookup(stocks: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    """旧 TS attention 口径：趋势核心因子是 avgRankNum 均榜百分位重排后的序号。

    过滤 avgRankNum > 0，按 (avgRankNum, code) 升序重排；综合排名只决定池子大小
    （哪些股票进池），不参与趋势百分位计算。
    """
    valid: list[tuple[str, float]] = []
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "")
        if not code:
            continue
        avg = stock.get("avgRankNum")
        try:
            avg = float(avg)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(avg) or avg <= 0:
            continue
        valid.append((code, avg))
    valid.sort(key=lambda item: (item[1], item[0]))
    return {code: index + 1 for index, (code, _avg) in enumerate(valid)}, len(valid)
