"""MainlineScore 日间稳定性三候选（Phase R2 研究纯函数）。

R1 实测：单日横截面 percentile 无平滑时 Top3 日间 Jaccard 仅 0.0604~0.0925
（四组权重均然）——稳定性问题在合成方式而非权重。本模块提供三个统一接口
的平滑候选，输入统一为逐日分数 {date: {themeKey: score}}，输出逐日 TopK
名单 {date: [themeKey]}：
  ema_toplists       分数 EMA 平滑后排序（滞后换头）
  window_toplists    近 N 日 TopK 霸榜计数排序（累计确认）
  hysteresis_toplists 双阈值滞回进出（粘性名单，长度可 >k）
fail-visible：缺日/空日输出空名单或按可得数据递推，不伪造、不中断。
研究参数（alpha/window/exit_rank）由 R2 runner 敏感性对比后提案定版。
"""

from __future__ import annotations

from typing import Any


def _top_k(scores: dict[str, Any], k: int) -> list[str]:
    valid = [(t, float(s)) for t, s in scores.items() if s is not None]
    ranked = sorted(valid, key=lambda kv: kv[1], reverse=True)
    return [t for t, _ in ranked[:k]]


def ema_toplists(
    scores_by_day: dict[str, dict[str, Any]], *, alpha: float = 0.5, k: int = 3
) -> dict[str, list[str]]:
    """分数 EMA：smooth_t = alpha*score_t + (1-alpha)*smooth_{t-1}，题材级逐日递推。

    首见题材初值=当日原分；当日缺分的题材沿用昨日 smooth 参与排序。
    """
    smooth: dict[str, float] = {}
    out: dict[str, list[str]] = {}
    for d in sorted(scores_by_day):
        for t, s in scores_by_day[d].items():
            if s is None:
                continue
            prev = smooth.get(t)
            smooth[t] = float(s) if prev is None else alpha * float(s) + (1 - alpha) * prev
        out[d] = _top_k(smooth, k)
    return out


def window_toplists(
    scores_by_day: dict[str, dict[str, Any]],
    *,
    window: int = 5,
    broad_k: int = 10,
    k: int = 3,
) -> dict[str, list[str]]:
    """近 window 日每日 Top(broad_k) 霸榜次数计数，按计数降序（并列按当日分数）取前 k。"""
    days = sorted(scores_by_day)
    daily_tops = [set(_top_k(scores_by_day[d], broad_k)) for d in days]
    out: dict[str, list[str]] = {}
    for i, d in enumerate(days):
        counts: dict[str, int] = {}
        for j in range(max(0, i - window + 1), i + 1):
            for t in daily_tops[j]:
                counts[t] = counts.get(t, 0) + 1
        cur = scores_by_day[d]

        def _sort_key(t: str) -> tuple[int, float]:
            s = cur.get(t)
            return (counts[t], float(s) if s is not None else float("-inf"))

        ranked = sorted(counts, key=_sort_key, reverse=True)
        out[d] = ranked[:k]
    return out


def hysteresis_toplists(
    scores_by_day: dict[str, dict[str, Any]],
    *,
    k: int = 3,
    exit_rank: int = 5,
) -> dict[str, list[str]]:
    """双阈值滞回：新进需当日原始 rank<=k；在列者当日原始 rank>exit_rank 才退出。

    输出为完整滞回名单（长度可 >k），按当日原始 rank 升序。
    """
    out: dict[str, list[str]] = {}
    held: list[str] = []
    for d in sorted(scores_by_day):
        ranked = _top_k(scores_by_day[d], len(scores_by_day[d]))
        rank_of = {t: i + 1 for i, t in enumerate(ranked)}
        held = [t for t in held if rank_of.get(t, 10**9) <= exit_rank]
        for t in ranked[:k]:
            if t not in held:
                held.append(t)
        out[d] = sorted(held, key=lambda t: rank_of.get(t, 10**9))
    return out
