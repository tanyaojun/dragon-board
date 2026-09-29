# -*- coding: utf-8 -*-
"""jev 热榜情绪观察轨道读写 API（观察轨道 v3，2026-10-08）。

- POST /api/hotlist-jev/evaluate：手动触发槽位/日级评判。**不受 gate 限制**（显式
  用户意图），origin=manual；token 缺失时照常落 degraded 文档并返回 degraded 结果。
- GET  /api/hotlist-jev/series：单日读口（槽位升序 + eod），v1 无缓存。

读口只返回 hotlist_jev_sentiment 原文档（独立观察轨道），不与规则情绪文档合并。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.data.repositories import repository_factory

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])


class JevEvaluatePayload(BaseModel):
    tradingDate: str
    scope: str = "slot"  # "slot" | "day"
    slotTime: str | None = None
    datasetId: str = "dragonboard_live"


def _slots_collection(db: Any):
    return db["hotlist_jev_sentiment"]


def _latest_date(db: Any, dataset_id: str) -> str | None:
    dates = sorted({
        str(row.get("tradingDate"))
        for row in _slots_collection(db).find({"datasetId": dataset_id})
        if row.get("tradingDate")
    })
    return dates[-1] if dates else None


@router.post("/evaluate")
def evaluate_hotlist_jev(payload: JevEvaluatePayload) -> dict[str, Any]:
    from backend.services.jev.jev_sentiment_compute import (
        compute_and_upsert_for_day,
        compute_and_upsert_for_slot,
    )

    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}

    if payload.scope not in ("slot", "day"):
        return {"ok": False, "errorCode": "bad_scope", "error": "scope must be slot|day"}

    try:
        if payload.scope == "day":
            result = compute_and_upsert_for_day(
                db, dataset_id=payload.datasetId, trading_date=payload.tradingDate,
                origin="manual", force=True)
            return {"ok": True, **result}
        slot_time = payload.slotTime
        if not slot_time:
            # 缺省取当日最新已采 half_hour 槽
            slots = sorted({
                str(row.get("slotTime"))
                for row in db["snapshot_frames"].find({
                    "datasetId": payload.datasetId, "type": "half_hour",
                    "tradingDate": payload.tradingDate})
                if row.get("slotTime")
            })
            if not slots:
                return JSONResponse(
                    status_code=404,
                    content={"ok": False, "errorCode": "no_slot",
                             "error": f"no half_hour frames for {payload.tradingDate}"})
            slot_time = slots[-1]
        result = compute_and_upsert_for_slot(
            db, dataset_id=payload.datasetId, trading_date=payload.tradingDate,
            slot_time=slot_time, origin="manual", force=True)
        return {"ok": True, "slotTime": slot_time, **result}
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"evaluate_failed: {exc}"}


@router.get("/series")
def get_hotlist_jev_series(
    dataset_id: str = "dragonboard_live",
    date: str | None = None,
) -> dict[str, Any]:
    """单日 jev 观察轨道读口：槽位文档升序 + eod 文档；无任何文档时不报错不伪造。"""
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}

    try:
        trading_date = date or _latest_date(db, dataset_id)
        if not trading_date:
            return {"ok": True, "date": None, "slots": [], "eod": None, "degradedCount": 0}
        rows = list(_slots_collection(db).find(
            {"datasetId": dataset_id, "tradingDate": trading_date}))
        slots = sorted(
            (row for row in rows if row.get("kind") == "slot"),
            key=lambda row: str(row.get("slotTime") or ""),
        )
        eod = next((row for row in rows if row.get("kind") == "eod"), None)
        degraded_count = sum(
            1 for row in [*slots, eod] if row and row.get("status") in ("degraded", "no_data"))
        return {"ok": True, "date": trading_date, "slots": slots, "eod": eod,
                "degradedCount": degraded_count}
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"series_read_failed: {exc}", "slots": []}
