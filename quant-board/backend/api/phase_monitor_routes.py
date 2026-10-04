# -*- coding: utf-8 -*-
"""phase-monitor 读口（前端可见化看板数据源，设计 ranktrend-phase-frontend-design.md §3）。

GET /api/phase-monitor/board：Mongo phase_monitor 集合（phase_monitor_persistence 落库）
→ {northstar 基线文档, months 逐月监督按月升序, c9 深谷账本按月升序, sentinelDivergence 哨兵分歧}。
集合空/未迁移时结构化缺失原因（fail-visible 不伪造）。低频读口不接 Redis 缓存。

哨兵分歧=融合总纲（ranktrend-phase-fusion-master-plan.md §5）合流点一，唯一实现在
backend/operations/sentinel_divergence.py（月度监控同源消费）；规则分主定义 ×
jev 日级哨兵逐日三档带比较，只告警不改判——哨兵读数永不替代规则分。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.data.repositories import repository_factory
from backend.operations.sentinel_divergence import sentinel_divergence

router = APIRouter(prefix="/api/phase-monitor", tags=["phase-monitor"])


def _band_scale() -> list[dict[str, Any]]:
    """四带刻度（边界+用户展示名）——前端三轴「水平」轴按分数落区间用。

    单一事实源纪律（章程 §7.1-4）：带定义=引擎 BAND_TAGS/band_of_score，展示名=phase_pulse
    PULSE_BAND_LABELS；前端禁止再手抄阈值或档名（review P1-B：axisLevel 曾手抄四带副本）。
    """
    from backend.core.backtest.execution import BAND_TAGS
    from backend.operations.phase_pulse import PULSE_BAND_LABELS

    upper_by_tag = {"冷10-40": 40.0, "弱势40-60": 60.0, "强60-80": 80.0, "极热≥80": None}
    lower = 0.0
    out: list[dict[str, Any]] = []
    for tag in BAND_TAGS:
        label, range_text = PULSE_BAND_LABELS[tag]
        upper = upper_by_tag[tag]
        out.append({"tag": tag, "label": label, "rangeText": range_text,
                    "lower": lower, "upper": upper})
        lower = upper
    return out


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
        "bandScale": _band_scale(),
    }
    if northstar is None:
        body["northstarMissingReason"] = (
            "phase_monitor 集合无 northstar 文档——先跑 backend.operations.phase_northstar（幂等落库）"
        )
    return body
