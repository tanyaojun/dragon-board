"""题材轮动度量纯函数（Phase R1 研究，ThemeTrend 设计文档 §5.3 轮动维 / §6.1 Phase R1）。

输入输出均为普通 dict/list，无 I/O、无 MongoDB 依赖。
fail-visible：样本不足返回 status="insufficient" 并保留可计算部分，
不伪造 0、不抛异常中断。
"""

from __future__ import annotations

import math
from typing import Any


def rotation_speed(top_sets: list[set[str]]) -> dict[str, Any]:
    """TopN 题材名单的日间 Jaccard 距离序列 → 轮动速度统计。

    rotation_speed_t = 1 - |TopN_t ∩ TopN_{t-1}| / |TopN_t ∪ TopN_{t-1}|
    值域 0-1：0=名单完全不变（主线极稳），1=名单完全换血（极速轮动）。
    空集合日两侧转移均标 insufficient，不参与均值但保留在 series：
    空集只来自断采缺槽日，缺失日两侧的转移都无信息（可能是缺数据而非真换血）；
    若把"流入缺失日"计为 1.0 满分轮动并进均值，会系统性抬高轮动速度、污染核心度量。
    """
    series: list[dict[str, Any]] = []
    for i in range(1, len(top_sets)):
        a, b = top_sets[i - 1], top_sets[i]
        if not a or not b:
            series.append({"index": i, "value": None, "status": "insufficient"})
            continue
        union = a | b
        series.append(
            {"index": i, "value": round(1.0 - len(a & b) / len(union), 4), "status": "ok"}
        )
    values = [s["value"] for s in series if s["value"] is not None]
    if not values:
        return {
            "status": "insufficient",
            "reason": "need_at_least_two_nonempty_days",
            "series": series,
        }
    return {
        "status": "ok",
        "mean": round(sum(values) / len(values), 4),
        "max": round(max(values), 4),
        "min": round(min(values), 4),
        "n_transitions": len(values),
        "series": series,
    }


def mainline_persistence(mainline_by_day: dict[str, str | None]) -> dict[str, Any]:
    """每日主线题材（Top1）序列 → 主线连续保持天数分布与切换频率。

    None（缺失/未判出）日断开连续段：结束当前段、不计切换、不并入下一段。
    键需为零填充可排序日期串（ISO 格式），内部按字典序确定时序。
    comparable 统计同段内相邻两天均有主线的转移总数（含主题相同者），
    switch_rate = switches / comparable；无任何可比转移时为 None（不伪装成 0）。
    """
    days = sorted(mainline_by_day)
    streaks: list[int] = []
    switches = 0
    comparable = 0
    cur_theme: str | None = None
    cur_len = 0
    for d in days:
        theme = mainline_by_day[d]
        if theme is None:
            if cur_len:
                streaks.append(cur_len)
            cur_theme, cur_len = None, 0
            continue
        if cur_theme is None:
            cur_theme, cur_len = theme, 1
        elif theme == cur_theme:
            comparable += 1
            cur_len += 1
        else:
            comparable += 1
            switches += 1
            streaks.append(cur_len)
            cur_theme, cur_len = theme, 1
    if cur_len:
        streaks.append(cur_len)
    if not streaks:
        return {"status": "insufficient", "reason": "no_mainline_days", "streaks": []}
    return {
        "status": "ok",
        "streaks": streaks,
        "mean_streak": round(sum(streaks) / len(streaks), 2),
        "max_streak": max(streaks),
        "switches": switches,
        "comparable_transitions": comparable,
        "switch_rate": round(switches / comparable, 4) if comparable else None,
        "n_days": len([d for d in days if mainline_by_day[d] is not None]),
    }


def rank_entropy(top_counts: dict[str, int]) -> dict[str, Any]:
    """TopN 成员霸榜频率分布的归一化 Shannon 熵。

    p_i = 题材 i 进入 TopN 的天数 / Σ(全部题材霸榜天数)；
    熵低 = 少数题材霸榜（主线集中）；熵高 = 频繁换脸（轮动混沌）。
    归一化基准 log(k)，k=出现过的题材数。
    零/负计数视为非法输入，直接过滤不参与分布（fail-visible：不抛异常、不伪装成 0 熵）。
    """
    # 只累计正数计数：负数计数非法但不中断，避免 math.log 抛 ValueError
    total_hits = sum(c for c in top_counts.values() if c > 0)
    if total_hits == 0:
        return {"status": "insufficient", "reason": "no_top_hits"}
    probs = [c / total_hits for c in top_counts.values() if c > 0]
    h = -sum(p * math.log(p) for p in probs)
    k = len(probs)
    norm = h / math.log(k) if k > 1 else 0.0
    return {
        "status": "ok",
        "entropy": round(h, 4),
        "normalized": round(norm, 4),
        "k_themes": k,
        "total_hits": total_hits,
    }


def dedup_limit_count(
    repeat_counted: dict[str, set[str]], owner: dict[str, str]
) -> dict[str, Any]:
    """守恒涨停计数 vs 重复计数对比（Phase 0 已知失真方向的量化）。

    repeat_counted: {themeKey: set(stockCode)} 现有口径（一股属多题材重复计入）
    owner: {stockCode: themeKey} 个股唯一归属（mainTheme 判定链输出）
    """
    dedup: dict[str, int] = {}
    for code, theme in owner.items():
        dedup[theme] = dedup.get(theme, 0) + 1
    dedup_total = sum(dedup.values())
    repeat_total = sum(len(v) for v in repeat_counted.values())
    return {
        "status": "ok" if dedup_total else "insufficient",
        "reason": None if dedup_total else "empty_owner",
        "repeat_by_theme": {k: len(v) for k, v in repeat_counted.items()},
        "repeat_total": repeat_total,
        "dedup_by_theme": dedup,
        "dedup_total": dedup_total,
        "inflation_ratio": round(repeat_total / dedup_total, 4) if dedup_total else None,
    }
