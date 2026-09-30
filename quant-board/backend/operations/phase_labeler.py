# -*- coding: utf-8 -*-
"""M1 相位标签器（ranktrend-phase-acceptance-design.md §5 M1）。

候选相位信号 → 帧级/日级相位标签（offense/neutral/defense/unknown）。
纪律：标签计算 as-of（单帧标签只用当前帧信号；日级众数含日末槽，对"日中入场"存在
轻微前视——交易层切片另提供前日标签变体 dailyByPrevDay，M1 报告诚实边界披露）；
缺信号 → unknown（fail-visible 不伪造）；相位定义（阈值/档数）变更 = 标签全量重打。
"""
from __future__ import annotations

from collections import Counter
from typing import Any

# 保守序：平票时防守侧优先（宁可少进攻不可漏防守）
_TIE_BREAK = {"defense": 0, "neutral": 1, "offense": 2}


def phase_from_sentiment_score(score: float | None, *, hi: float, lo: float) -> str:
    """情绪 route B 连续分（0-100）→ 相位：score≥hi 进攻 / <lo 防守 / 其间中性。"""
    if score is None:
        return "unknown"
    if score >= hi:
        return "offense"
    if score < lo:
        return "defense"
    return "neutral"


def phase_from_emotion_value(value: float | None, *, hi: float, lo: float) -> str:
    """帧自带 marketStats.emotionValue（市场宽度情绪小数）→ 相位，同三段规则。"""
    if value is None:
        return "unknown"
    if value >= hi:
        return "offense"
    if value < lo:
        return "defense"
    return "neutral"


def load_sentiment_scores(docs: list[dict[str, Any]]) -> tuple[dict[tuple[str, str], float | None], dict[str, float | None]]:
    """hotlist_sentiment 文档 → 帧级 (tradingDate, slotTime)→score 与日级 EOD→score 两张表。

    内化 snapshotType 过滤（非 half_hour 整体排除——同槽多版本以列表后序为准，调用方
    Mongo 查询同样带过滤，双保险）；emotionScore 为 dict（route B，score-v1）或 None。
    """
    frame_scores: dict[tuple[str, str], float | None] = {}
    eod_scores: dict[str, float | None] = {}
    for d in docs:
        st = d.get("snapshotType")
        if st not in (None, "half_hour"):
            continue
        date, slot = str(d.get("tradingDate") or ""), str(d.get("slotTime") or "")
        es = d.get("emotionScore")
        score = float(es["score"]) if isinstance(es, dict) and isinstance(es.get("score"), (int, float)) else None
        if slot == "EOD":
            eod_scores[date] = score
        elif slot:
            frame_scores[(date, slot)] = score
    return frame_scores, eod_scores


def daily_phase_from_frames(frames: list[dict[str, Any]]) -> dict[str, str]:
    """帧级相位 → 日级相位（日内众数；平票取保守序靠前；全 unknown → unknown）。"""
    by_day: dict[str, Counter] = {}
    for f in frames:
        day, phase = str(f.get("tradingDate") or ""), str(f.get("phase") or "unknown")
        if day:
            by_day.setdefault(day, Counter())[phase] += 1
    daily: dict[str, str] = {}
    for day, counter in by_day.items():
        if set(counter) == {"unknown"}:
            daily[day] = "unknown"
            continue
        counted = {p: c for p, c in counter.items() if p != "unknown"}
        top = max(counted.values())
        daily[day] = sorted((p for p, c in counted.items() if c == top), key=lambda p: _TIE_BREAK.get(p, 9))[0]
    return daily


def shift_daily_to_prev(daily: dict[str, str], ordered_days: list[str]) -> dict[str, str]:
    """日级标签前移一日（严格 as-of 变体）：entry 日用前一交易日的日级相位。

    ordered_days = 全窗升序交易日列表（调用方从帧提取），首日无前日 → unknown。
    """
    prev_of: dict[str, str] = {}
    for i, day in enumerate(ordered_days):
        prev_of[day] = daily.get(ordered_days[i - 1], "unknown") if i > 0 else "unknown"
    return prev_of
