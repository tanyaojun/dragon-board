# -*- coding: utf-8 -*-
"""jev 热榜情绪观察轨道读写 API（观察轨道 v3，2026-10-08）。

- POST /api/hotlist-jev/evaluate：手动触发槽位/日级评判。**不受 gate 限制**（显式
  用户意图），origin=manual；token 缺失时照常落 degraded 文档并返回 degraded 结果。
- GET  /api/hotlist-jev/series：单日读口（槽位升序 + eod），v1 无缓存。
- GET  /api/hotlist-jev/range：多日窗口读口（2026-09-30，前端 jev 观察轨道图表消费），
  按快照交易日历逐日返回；纯读不补算（jev 结论唯一来源 = 采集链落库）。
- GET  /api/hotlist-jev/review-list：复核工作台清单（W1 辅助线，2026-10-01）——
  分歧仲裁/退潮异议/边界日三类复核项，按日聚合；清单为空时懒生成（读 frames，首次较慢）。
- POST /api/hotlist-jev/review-ruling：复核裁决回填（status ∈ rule_right/jev_right/
  ambiguous/pending + 备注），幂等更新。
- GET  /api/hotlist-jev/jiuyan-action：韭研公社异动读口（W-jiuyan，2026-10-02）——
  无 date 返回 {dates, doc=最新 final}；带 date 返回该日文档（kind 默认 final）。纯读。

读口只返回 hotlist_jev_sentiment 原文档（独立观察轨道），不与规则情绪文档合并。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.data.repositories import repository_factory

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])

REVIEW_RULING_STATUSES = ("rule_right", "jev_right", "ambiguous", "pending", "consistent")


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


@router.get("/range")
def get_hotlist_jev_range(
    dataset_id: str = "dragonboard_live",
    days: int = 3,
) -> dict[str, Any]:
    """多日 jev 观察轨道读口：快照交易日历窗口逐日返回槽位 + eod（槽位升序）。

    - 窗口基准 = 快照帧交易日历（与 hotlist-sentiment series 同口径），非 jev 文档日期；
      窗口内无 jev 文档的交易日以 ``{tradingDate, missing, reason}`` 结构化返回，
      不吞掉不伪造（fail-visible：jev 轨道历史覆盖浅时缺口必须可见）。
    - 纯读不 lazy 补算（jev 结论唯一来源 = 采集链落库），v1 无缓存。
    """
    capped_days = max(1, min(int(days), 30))
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}", "days": []}

    try:
        from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

        dates = HotListSentimentBackfillService(db).trading_dates(
            dataset_id=dataset_id, snapshot_type="half_hour")
        if not dates:
            return {"ok": False, "degraded": True, "reason": "no_snapshot_trading_date", "days": []}
        window = dates[-capped_days:]
        rows = list(_slots_collection(db).find({"datasetId": dataset_id}))
        by_date: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            date_key = str(row.get("tradingDate") or "")
            if date_key:
                by_date.setdefault(date_key, []).append(row)

        days_out: list[dict[str, Any]] = []
        degraded_count = 0
        for trading_date in window:
            day_rows = by_date.get(trading_date) or []
            if not day_rows:
                days_out.append(
                    {"tradingDate": trading_date, "missing": True, "reason": "no_jev_docs"})
                continue
            slots = sorted(
                (row for row in day_rows if row.get("kind") == "slot"),
                key=lambda row: str(row.get("slotTime") or ""),
            )
            eod = next((row for row in day_rows if row.get("kind") == "eod"), None)
            days_out.append({"tradingDate": trading_date, "slots": slots, "eod": eod})
            degraded_count += sum(
                1 for row in [*slots, eod] if row and row.get("status") in ("degraded", "no_data"))
        return {"ok": True, "datasetId": dataset_id, "days": days_out,
                "degradedCount": degraded_count}
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"range_read_failed: {exc}", "days": []}


class JevReviewRulingPayload(BaseModel):
    id: str
    status: str = Field(..., description="rule_right | jev_right | ambiguous | pending")
    note: str = ""


@router.get("/review-list")
def get_jev_review_list() -> dict[str, Any]:
    """复核工作台清单（W1）：三类复核项按日聚合 + 进度统计；清单为空时懒生成。"""
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}", "days": []}
    try:
        from backend.operations.jev_review_list import ensure_review_items

        stats = ensure_review_items(db)
        # 日期降序（2026-10-01 用户指令）：最新待复核日在前
        docs = list(db["phase_monitor"].find({"kind": "review_items"}).sort([("date", -1), ("slot", 1)]))
        docs = [{k: v for k, v in d.items() if k != "_id"} | {"id": str(d["_id"])} for d in docs]
        days: list[dict[str, Any]] = []
        by_date: dict[str, list[dict[str, Any]]] = {}
        for d in docs:
            by_date.setdefault(d["date"], []).append(d)
        for date in sorted(by_date, reverse=True):
            items = by_date[date]
            days.append({"date": date, "items": items,
                         "pending": sum(1 for i in items if i["ruling"]["status"] == "pending")})
        return {"ok": True, "stats": stats, "days": days,
                "progress": {"total": len(docs),
                             "ruled": sum(1 for i in docs if i["ruling"]["status"] != "pending")}}
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"review_list_failed: {exc}", "days": []}


@router.post("/review-ruling")
def post_jev_review_ruling(payload: JevReviewRulingPayload) -> dict[str, Any]:
    """复核裁决回填：幂等更新 ruling（status/note/ruledAt）。"""
    if payload.status not in REVIEW_RULING_STATUSES:
        return {"ok": False, "errorCode": "bad_status",
                "error": f"status must be one of {REVIEW_RULING_STATUSES}"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from datetime import datetime

        result = db["phase_monitor"].update_one(
            {"_id": payload.id, "kind": "review_items"},
            {"$set": {"ruling.status": payload.status, "ruling.note": payload.note,
                      "ruling.ruledAt": datetime.now().isoformat(timespec="seconds")}},
        )
        if result.matched_count == 0:
            return JSONResponse(status_code=404, content={"ok": False, "errorCode": "item_not_found",
                                                          "error": f"no review item {payload.id}"})
        return {"ok": True, "id": payload.id, "status": payload.status}
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"ruling_write_failed: {exc}"}


@router.get("/jiuyan-action")
def get_jiuyan_action(date: str | None = None, kind: str = "final") -> dict[str, Any]:
    """韭研公社异动读口（纯读，不补采）：无 date → 最新 final + 全部日期索引。"""
    if kind not in ("final", "midday"):
        return {"ok": False, "errorCode": "bad_kind", "error": "kind must be final|midday"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.operations.jiuyan_store import get_action_doc, list_action_dates

        dates = list_action_dates(db)
        if not dates:
            return {"ok": True, "dates": [], "doc": None}
        target_date = date or dates[-1]["date"]
        doc = get_action_doc(db, target_date, kind)
        if doc is None and date is None:
            # 最新日可能只有 midday——回落找该日任一 kind
            for k in ("midday", "final"):
                doc = get_action_doc(db, target_date, k)
                if doc:
                    break
        if doc is None:
            return {"ok": True, "dates": dates, "doc": None,
                    "degraded": True, "reason": f"{target_date}:{kind} 未落库"}
        doc = {k: v for k, v in doc.items() if k != "_id"}
        return {"ok": True, "dates": dates, "doc": doc}
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"jiuyan_read_failed: {exc}"}
