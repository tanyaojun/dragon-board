"""Spearman 秩相关（Phase 1 动量 IC 统计）。

与 `analysis/ranktrend/research/tier_monotonicity.py` 的 `_spearman` 同口径
（并列取平均秩 + 秩上 Pearson）；未跨域复用因其为 ranktrend 域私有实现，
数学常量级函数按已知答案测试防漂移。fail-visible：n<2 或全并列返回 None。
"""

from __future__ import annotations


def _average_ranks(values: list[float]) -> list[float]:
    """并列取平均秩（1 起）。全并列场景由调用方的方差为零检查兜底。"""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_rank_ic(xs: list[float], ys: list[float]) -> float | None:
    """两组等长观测的 Spearman 秩相关；n<2、长度不一致或任一侧全并列 → None。"""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    rank_x = _average_ranks([float(v) for v in xs])
    rank_y = _average_ranks([float(v) for v in ys])
    n = len(xs)
    mean_x = sum(rank_x) / n
    mean_y = sum(rank_y) / n
    cov = sum((rx - mean_x) * (ry - mean_y) for rx, ry in zip(rank_x, rank_y))
    var_x = sum((rx - mean_x) ** 2 for rx in rank_x)
    var_y = sum((ry - mean_y) ** 2 for ry in rank_y)
    if var_x == 0 or var_y == 0:
        return None
    return cov / (var_x * var_y) ** 0.5


def marginal_spearman_ic(
    values: list[float | None],
    baseline: list[float | None],
    forward: list[float | None],
) -> float | None:
    """边际 Spearman IC：候选因子秩对基准秩 OLS 残差后与 forward 的秩相关。

    回答"候选因子在基准之上是否仍有增量信息"（因子口径收敛批 TaskB，
    Phase 3 裁决标准的统计实现）。None 成对剔除（任一侧缺失 → 该观测丢弃，
    不伪造 0）；剔除后 n<3 → None；候选与基准秩完全共线（残差全等）→ None。
    """
    if len(values) != len(baseline) or len(values) != len(forward):
        return None
    pairs = [
        (float(v), float(b), float(f))
        for v, b, f in zip(values, baseline, forward)
        if v is not None and b is not None and f is not None
    ]
    if len(pairs) < 3:
        return None
    v = [p[0] for p in pairs]
    b = [p[1] for p in pairs]
    f = [p[2] for p in pairs]
    rank_v = _average_ranks(v)
    rank_b = _average_ranks(b)
    mean_v = sum(rank_v) / len(rank_v)
    mean_b = sum(rank_b) / len(rank_b)
    cov = sum((rb - mean_b) * (rv - mean_v) for rb, rv in zip(rank_b, rank_v))
    var_b = sum((rb - mean_b) ** 2 for rb in rank_b)
    if var_b == 0:
        residuals = [rv - mean_v for rv in rank_v]
    else:
        slope = cov / var_b
        intercept = mean_v - slope * mean_b
        residuals = [rv - (slope * rb + intercept) for rv, rb in zip(rank_v, rank_b)]
    return spearman_rank_ic(residuals, f)
