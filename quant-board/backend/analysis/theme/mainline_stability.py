"""MainlineScore 日间稳定性三候选（Phase R2 研究纯函数）。

R1 实测：单日横截面 percentile 无平滑时 Top3 日间 Jaccard 仅 0.0604~0.0925
（四组权重均然）——稳定性问题在合成方式而非权重。本模块提供三个统一接口
的平滑候选，输入统一为逐日分数 {date: {themeKey: score}}，输出逐日 TopK
名单 {date: [themeKey]}：
  ema_toplists       分数 EMA 平滑后排序（滞后换头）
  window_toplists    近 N 日 TopK 霸榜计数排序（累计确认）
  hysteresis_toplists 双阈值滞回进出（粘性名单，长度可 >k）
统一缺数据口径：缺失≠变差——ema 缺分题材 smooth 冻结在末值继续参与排序，
window 按窗口内历史计数继续计数，hysteresis 缺分在列成员保留资格（仅当日
显式 rank>exit_rank 才退出）。日期键需零填充可排序（ISO YYYY-MM-DD 或等宽
形式），本模块按字典序升序遍历。所有排序键显式规范化为「分数降序 + themeKey
字典序升序」，并列结果跨进程确定，不依赖 dict/set 迭代序（与 PYTHONHASHSEED
无关）。fail-visible：缺日/空日输出空名单或按可得数据递推，不伪造、不中断。
研究参数（alpha/window/exit_rank）由 R2 runner 敏感性对比后提案定版。
"""

from __future__ import annotations

from typing import Any


def _top_k(scores: dict[str, Any], k: int) -> list[str]:
    """按「分数降序 + themeKey 字典序升序」取前 k，并列结果跨进程确定。

    负号实现降序是为了让末位 themeKey 键保持字典序升序（reverse=True 会把
    字符串末位键一并反序）。
    """
    valid = [(t, float(s)) for t, s in scores.items() if s is not None]
    ranked = sorted(valid, key=lambda kv: (-kv[1], kv[0]))
    return [t for t, _ in ranked[:k]]


def ema_toplists(
    scores_by_day: dict[str, dict[str, Any]], *, alpha: float = 0.5, k: int = 3
) -> dict[str, list[str]]:
    """分数 EMA：smooth_t = alpha*score_t + (1-alpha)*smooth_{t-1}，题材级逐日递推。

    前提：输入分数须跨日可比（percentile 归一满足），否则 EMA 递推无意义。
    首见题材初值=当日原分；当日缺分的题材沿用昨日 smooth 参与排序——smooth
    冻结在末值，缺失≠变差是刻意取舍（与 window/hysteresis 缺数据口径一致）。
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
    """近 window 日每日 Top(broad_k) 霸榜计数，按计数降序（并列按当日分数、再按 themeKey）取前 k。"""
    days = sorted(scores_by_day)
    # 题材在单日 dict 键上唯一，用 list（_top_k 已定序）即可；不用 set（迭代序受 PYTHONHASHSEED 影响）
    daily_tops = [_top_k(scores_by_day[d], broad_k) for d in days]
    out: dict[str, list[str]] = {}
    for i, d in enumerate(days):
        counts: dict[str, int] = {}
        for j in range(max(0, i - window + 1), i + 1):
            for t in daily_tops[j]:
                counts[t] = counts.get(t, 0) + 1
        cur = scores_by_day[d]

        def _sort_key(t: str) -> tuple[int, float, str]:
            s = cur.get(t)
            score = float(s) if s is not None else float("-inf")
            # 负号实现计数/分数降序，themeKey 升序收尾，全并列时结果跨进程确定
            return (-counts[t], -score, t)

        ranked = sorted(counts, key=_sort_key)
        out[d] = ranked[:k]
    return out


def hysteresis_toplists(
    scores_by_day: dict[str, dict[str, Any]],
    *,
    k: int = 3,
    exit_rank: int = 5,
) -> dict[str, list[str]]:
    """双阈值滞回：新进需当日原始 rank<=k；在列者当日原始 rank>exit_rank 才退出。

    缺数据口径：当日无有效分（缺分/空日）的在列成员保留资格，不视为劣于
    exit_rank；仅当日有显式 rank 且 >exit_rank 才退出；当日无有效分的新题材
    不进列。输出为完整滞回名单（长度可 >k），按当日原始 rank 升序，缺分保留
    成员排在其后（sorted 稳定，保持既有 held 顺序）。
    """
    out: dict[str, list[str]] = {}
    held: list[str] = []
    for d in sorted(scores_by_day):
        ranked = _top_k(scores_by_day[d], len(scores_by_day[d]))
        rank_of = {t: i + 1 for i, t in enumerate(ranked)}
        # 有有效 rank 的按阈值过滤；无有效 rank 的（缺分日）保留资格，不洗白
        held = [
            t
            for t in held
            if (t in rank_of and rank_of[t] <= exit_rank) or t not in rank_of
        ]
        for t in ranked[:k]:
            if t not in held:
                held.append(t)
        # 默认 10**9 仍可达：缺分保留成员无当日 rank，稳定排到有 rank 成员之后
        out[d] = sorted(held, key=lambda t: rank_of.get(t, 10**9))
    return out
