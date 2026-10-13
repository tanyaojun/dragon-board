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
    # 2026-10-02 用户裁决 V1 退役：观察轨道读口全线切 v2 表（槽位答案键与 v1 同构，
    # 叙事含锚段+封板质量/触板回撤池证据行；v1 集合保留磁盘档案，生产零消费）
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
    # 2026-10-02 用户裁决 V1 退役：手工评判走唯一情绪链（叙事带锚段+新证据行，落 hotlist_jev_sentiment）
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
                db, dataset_id=payload.datasetId, trading_date=payload.tradingDate, origin="manual")
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
            slot_time=slot_time, origin="manual")
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
    capped_days = max(1, min(int(days), 60))  # 2026-10-10 30→60：relay_page 区间图表温度轴跟随（仍只取标量温度消费）
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


@router.get("/relay-index")
def get_relay_index(
    dataset_id: str = "dragonboard_live",  # 预留：hotlist_jev_relay_index 单库不落 datasetId，暂不过滤（review M1）
    date: str | None = None,
    days: int = 15,
) -> dict[str, Any]:
    """连板情绪指数读口：单日（date 给定）+ 近 N 日序列；fail-visible 不伪造。"""
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        col = db["hotlist_jev_relay_index"]
        # 2026-10-10 上限 60→400：relay_page 判定明细日期区间筛选需全量序列（客户端过滤，
        # 文档 ~1KB/日；400 天≈一年+，超长区间未来再议服务端分页）
        capped_days = max(1, min(int(days), 400))
        latest = date
        if not latest:
            newest = col.find_one({}, {"tradingDate": 1}, sort=[("tradingDate", -1)])
            latest = str(newest.get("tradingDate")) if newest else None
        day_doc = col.find_one({"tradingDate": latest}) if latest else None
        series = list(col.find(
            {"tradingDate": {"$ne": None}},
            {"narrative": 0, "responseRaw": 0, "questionsRaw": 0},
        ).sort("tradingDate", -1).limit(capped_days))
        series.reverse()
        # 2026-10-11 指数分区三色原料：join EOD day_temperature（唯一来源 hotlist_jev_sentiment），
        # 缺温度日 dayTemperature=None 原样透传（fail-visible，前端无温度不判黄）；
        # 温度原始值不取整（55.96 就是 55.96，前端 ≥56 判黄与研究脚本口径一致）。
        # join 失败只降级温度字段，不连坐 relay 序列读口（§4.0 部分失败不阻断）
        relay_dates = [str(r.get("tradingDate")) for r in [*series, day_doc] if r and r.get("tradingDate")]
        temps: dict[str, float] = {}
        join_error: str | None = None
        if relay_dates:
            try:
                for e in db["hotlist_jev_sentiment"].find(
                        {"kind": "eod", "status": "ok", "tradingDate": {"$in": relay_dates}},
                        {"tradingDate": 1, "scores.day_temperature": 1}):
                    t = (e.get("scores") or {}).get("day_temperature")
                    if isinstance(t, (int, float)) and not isinstance(t, bool):
                        temps[str(e["tradingDate"])] = float(t)
            except Exception as exc:
                temps, join_error = {}, f"day_temperature_join_failed: {exc}"
        for r in [*series, day_doc]:
            if r:
                r["dayTemperature"] = temps.get(str(r.get("tradingDate")))
        payload = {
            "ok": True, "datasetId": dataset_id, "date": latest,
            "day": day_doc,
            "series": series,
            "degradedCount": sum(1 for r in [*series, day_doc] if r and r.get("status") != "ok"),
        }
        if join_error:
            payload["dayTemperatureDegraded"] = join_error
        return payload
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"relay_index_read_failed: {exc}"}


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
        # 日期降序（2026-10-01 用户指令）：最新待复核日在前；
        # legacyCriteria=窗外旧判据代已裁项（2026-10-02 版本分段裁决），留档不进工作台
        docs = list(db["phase_monitor"].find(
            {"kind": "review_items", "legacyCriteria": {"$ne": True}}).sort([("date", -1), ("slot", 1)]))
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


@router.get("/sentiment-overview")
def get_hotlist_jev_sentiment_overview(date: str | None = None) -> dict[str, Any]:
    """情绪概览读口：jev EOD（市场热度计）+ 规则 EOD 同包返回。

    无 date → 最新可用 jev EOD 日；rule 为当日规则分（hotlist_sentiment emotionScore），
    任一表缺失如实标注（degraded 注记），不做兜底计算。
    """
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        jev_col = db["hotlist_jev_sentiment"]
        if date:
            doc = jev_col.find_one({"kind": "eod", "tradingDate": date})
            if doc is not None and doc.get("status") == "no_data":
                # 已落库但当日无可用帧：与"确未落库"区分，errorDetail 供排查
                return {"ok": True, "date": date, "jev": None, "rule": None, "degraded": True,
                        "reason": f"jev_eod 该日 no_data（errorDetail={doc.get('errorDetail') or '未知'}）"}
        else:
            doc = jev_col.find_one({"kind": "eod"}, sort=[("tradingDate", -1)])
            if doc is not None and doc.get("status") == "no_data":
                return {"ok": True, "date": str(doc.get("tradingDate")), "jev": None, "rule": None,
                        "degraded": True,
                        "reason": f"最新日 {doc.get('tradingDate')} jev_eod no_data"
                                  f"（errorDetail={doc.get('errorDetail') or '未知'}）"}
            if doc is not None and doc.get("status") not in ("ok", "degraded"):
                doc = None
        if doc is None:
            return {"ok": True, "date": date, "jev": None, "rule": None,
                    "degraded": True, "reason": f"jev_eod 未落库{f'：{date}' if date else ''}"}
        trading_date = str(doc.get("tradingDate"))
        rule_doc = db["hotlist_sentiment"].find_one(
            {"datasetId": doc.get("datasetId") or "dragonboard_live",
             "snapshotType": doc.get("snapshotType") or "half_hour",
             "slotTime": "EOD", "tradingDate": trading_date},
            {"emotionScore": 1})
        rule = rule_doc.get("emotionScore") if rule_doc else None
        answers = doc.get("answers") or {}
        scores = doc.get("scores") or {}

        def _choice(key: str) -> str | None:
            return (answers.get(key) or {}).get("choice")

        def _probs(key: str) -> dict | None:
            return (answers.get(key) or {}).get("probabilities")

        return {"ok": True, "date": trading_date,
                "jev": {"status": doc.get("status"),
                       "dayTemperature": scores.get("day_temperature"),
                       "dayStage": _choice("day_stage"),
                       "dayStageProbability": ((answers.get("day_stage") or {}).get("probabilities") or {}).get(_choice("day_stage") or ""),
                       "dayCrowding": _choice("day_crowding"),
                       "dayCrowdingProbabilities": _probs("day_crowding"),
                       "historyAnchorRange": doc.get("historyAnchorRange"),
                       "computedAt": doc.get("computedAt")},
                "rule": None if rule is None else {
                    "score": rule.get("score"),
                    "stageCandidate": rule.get("stageCandidate"),
                    "slope": rule.get("slope"),
                    "version": rule.get("version")},
                "degraded": bool(doc.get("status") != "ok" or rule is None),
                "reason": None if (doc.get("status") == "ok" and rule is not None)
                          else ("规则 EOD 未落库" if rule is None else f"v2 status={doc.get('status')}")}
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"sentiment_overview_read_failed: {exc}"}
