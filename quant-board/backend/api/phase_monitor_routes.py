# -*- coding: utf-8 -*-
"""phase-monitor 读口（前端可见化看板数据源，设计 ranktrend-phase-frontend-design.md §3）。

GET /api/phase-monitor/board：Mongo phase_monitor 集合（phase_monitor_persistence 落库）
→ {northstar 基线文档, months 逐月监督按月升序}。集合空/未迁移时结构化缺失原因
（fail-visible 不伪造）。低频读口不接 Redis 缓存。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.data.repositories import repository_factory

router = APIRouter(prefix="/api/phase-monitor", tags=["phase-monitor"])


@router.get("/board")
def get_phase_monitor_board() -> dict[str, Any]:
    db = repository_factory.get_runtime_mongodb_database()
    docs = list(db["phase_monitor"].find({}))
    northstar: dict[str, Any] | None = None
    months: list[dict[str, Any]] = []
    for doc in docs:
        if doc.get("kind") == "northstar":
            # 多基线取 updatedAt 最新（重跑升版本；当前单基线场景恒取唯一）
            if northstar is None or str(doc.get("updatedAt") or "") >= str(northstar.get("updatedAt") or ""):
                northstar = doc
        elif doc.get("kind") == "monthly":
            months.append(doc)
    months.sort(key=lambda m: str(m.get("month") or ""))
    body: dict[str, Any] = {
        "northstar": northstar,
        "months": months,
        "count": len(months),
    }
    if northstar is None:
        body["northstarMissingReason"] = (
            "phase_monitor 集合无 northstar 文档——先跑 backend.operations.phase_northstar（幂等落库）"
        )
    return body
