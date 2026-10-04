# -*- coding: utf-8 -*-
"""哨兵分歧（融合总纲 ranktrend-phase-fusion-master-plan.md §5 合流点一）。

规则分主定义 × jev 日级哨兵（hotlist_jev_driver_labels origin=phase_band_daily）逐日三档带
比较，只告警不改判——哨兵读数永不替代规则分，分歧仅作人工复核线索。
消费方：/api/phase-monitor/board（全期日清单）+ phase_monitor_monthly（当月告警线）。
唯一实现；禁止在读口/监控/前端再抄比较逻辑（单一事实源纪律）。
"""
from __future__ import annotations

from typing import Any

from backend.core.backtest.execution import band_of_score

# 三档带秩（冷=0/弱势=1/强势=2）：归类经引擎 band_of_score 四带映射（极热并入强势档，哨兵题
# 仅三档）——切点不在此重抄，引擎改边界自动跟随（章程 §7.1-4 单一事实源；review P2 收编）。
# _SENTINEL_BAND_* 键=哨兵题 choice 值（jev_label_jiuyan.py QUESTIONS_PHASE）。
BAND_NAMES = ("低温带", "弱势带", "强势带")
_SENTINEL_BAND_RANK = {"cold_lt40": 0, "weak_40_60": 1, "strong_ge60": 2}
_SENTINEL_BAND_NAMES = {"cold_lt40": "低温带", "weak_40_60": "弱势带", "strong_ge60": "强势带"}


def rule_band_rank(score: float) -> int:
    tag = band_of_score(score)
    if tag == "冷10-40":
        return 0
    if tag == "弱势40-60":
        return 1
    return 2


def sentinel_divergence(db: Any, month: str = "") -> dict[str, Any]:
    """规则分 × jev 哨兵逐日三档比较。

    month 非空时只统计该月（前缀匹配），供月度监控取当月告警线；空=全期（board 读口）。
    fail-visible：哨兵 insufficient/缺失或当日无 EOD 分 → 不计入可比集，skipped 计数如实披露。
    """
    eod: dict[str, float] = {}
    for d in db["hotlist_sentiment"].find(
            {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD"},
            {"tradingDate": 1, "emotionScore.score": 1}):
        es = d.get("emotionScore")
        if isinstance(es, dict) and isinstance(es.get("score"), (int, float)):
            eod[str(d["tradingDate"])] = float(es["score"])
    days: list[dict[str, Any]] = []
    skipped = 0
    cur = db["hotlist_jev_driver_labels"].find(
        {"origin": "phase_band_daily"}, {"tradingDate": 1, "phaseBand": 1})
    for s in cur.sort("tradingDate", 1):
        date = str(s.get("tradingDate") or "")
        if month and not date.startswith(month):
            continue
        raw = str(s.get("phaseBand") or "")
        sent_rank = _SENTINEL_BAND_RANK.get(raw)
        score = eod.get(date)
        if sent_rank is None or score is None:
            skipped += 1
            continue
        rule_rank = rule_band_rank(score)
        days.append({
            "date": date,
            "ruleScore": score,
            "ruleBand": BAND_NAMES[rule_rank],
            "sentinelBand": _SENTINEL_BAND_NAMES[raw],
            "sentinelRaw": raw,
            "relation": "agree" if sent_rank == rule_rank else ("lower" if sent_rank < rule_rank else "higher"),
            # 档位差（负=哨兵更冷）：可差两档（如强势带读成低温带），前端按差值表述不写死「一档」
            "notches": sent_rank - rule_rank,
        })
    summary = {
        "comparable": len(days),
        "agree": sum(1 for x in days if x["relation"] == "agree"),
        "lower": sum(1 for x in days if x["relation"] == "lower"),
        "higher": sum(1 for x in days if x["relation"] == "higher"),
        "skipped": skipped,
    }
    return {"summary": summary, "days": days}
