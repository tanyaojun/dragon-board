# -*- coding: utf-8 -*-
"""phase-monitor 读口（前端可见化看板数据源，设计 ranktrend-phase-frontend-design.md §3）。

GET /api/phase-monitor/board：Mongo phase_monitor 集合（phase_monitor_persistence 落库）
→ {northstar 基线文档, months 逐月监督按月升序, c9 深谷账本按月升序, sentinelDivergence 哨兵分歧}。
集合空/未迁移时结构化缺失原因（fail-visible 不伪造）。低频读口不接 Redis 缓存。

哨兵分歧=融合总纲（ranktrend-phase-fusion-master-plan.md §5）合流点一：规则分主定义 ×
jev 日级哨兵（hotlist_jev_driver_labels origin=phase_band_daily）逐日三档带比较，
只告警不改判——哨兵读数永不替代规则分，分歧仅作人工复核线索。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.data.repositories import repository_factory

router = APIRouter(prefix="/api/phase-monitor", tags=["phase-monitor"])

# 三档带秩（冷=0/弱势=1/强势=2）：与引擎 band_of_score 四带的 40/60 切点一致（极热并入强势档比较无意义，
# 哨兵题仅三档）；_SENTINEL_BAND_NAMES 键=哨兵题 choice 值（jev_label_jiuyan.py QUESTIONS_PHASE）。
_BAND_NAMES = ("低温带", "弱势带", "强势带")
_SENTINEL_BAND_RANK = {"cold_lt40": 0, "weak_40_60": 1, "strong_ge60": 2}
_SENTINEL_BAND_NAMES = {"cold_lt40": "低温带", "weak_40_60": "弱势带", "strong_ge60": "强势带"}


def _rule_band_rank(score: float) -> int:
    if score < 40.0:
        return 0
    if score < 60.0:
        return 1
    return 2


def sentinel_divergence(db: Any) -> dict[str, Any]:
    """规则分 × jev 哨兵逐日三档比较（合流点一）。

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
        raw = str(s.get("phaseBand") or "")
        sent_rank = _SENTINEL_BAND_RANK.get(raw)
        score = eod.get(str(s.get("tradingDate") or ""))
        if sent_rank is None or score is None:
            skipped += 1
            continue
        rule_rank = _rule_band_rank(score)
        days.append({
            "date": str(s.get("tradingDate")),
            "ruleScore": score,
            "ruleBand": _BAND_NAMES[rule_rank],
            "sentinelBand": _SENTINEL_BAND_NAMES[raw],
            "sentinelRaw": raw,
            "relation": "agree" if sent_rank == rule_rank else ("lower" if sent_rank < rule_rank else "higher"),
        })
    summary = {
        "comparable": len(days),
        "agree": sum(1 for x in days if x["relation"] == "agree"),
        "lower": sum(1 for x in days if x["relation"] == "lower"),
        "higher": sum(1 for x in days if x["relation"] == "higher"),
        "skipped": skipped,
    }
    return {"summary": summary, "days": days}


@router.get("/board")
def get_phase_monitor_board() -> dict[str, Any]:
    db = repository_factory.get_runtime_mongodb_database()
    docs = list(db["phase_monitor"].find({}))
    northstar: dict[str, Any] | None = None
    pulses: list[dict[str, Any]] = []
    months: list[dict[str, Any]] = []
    c9_docs: list[dict[str, Any]] = []
    for doc in docs:
        if doc.get("kind") == "northstar":
            # 多基线取 updatedAt 最新（重跑升版本；当前单基线场景恒取唯一）
            if northstar is None or str(doc.get("updatedAt") or "") >= str(northstar.get("updatedAt") or ""):
                northstar = doc
        elif doc.get("kind") == "pulse":
            pulses.append(doc)  # 全量返回：C6 证据=逐月累积，前端画月度分带表
        elif doc.get("kind") == "monthly":
            months.append(doc)
        elif doc.get("kind") == "c9":
            c9_docs.append(doc)  # 深谷节点账本（C9 事件轴，融合总纲 §5 合流点二数据源）
    pulses.sort(key=lambda m: str(m.get("month") or ""))
    months.sort(key=lambda m: str(m.get("month") or ""))
    c9_docs.sort(key=lambda m: str(m.get("month") or ""))
    body: dict[str, Any] = {
        "northstar": northstar,
        "pulse": pulses[-1] if pulses else None,  # 兼容字段=最新月
        "pulses": pulses,
        "months": months,
        "count": len(months),
        "c9": c9_docs,
        "sentinelDivergence": sentinel_divergence(db),
    }
    if northstar is None:
        body["northstarMissingReason"] = (
            "phase_monitor 集合无 northstar 文档——先跑 backend.operations.phase_northstar（幂等落库）"
        )
    return body
