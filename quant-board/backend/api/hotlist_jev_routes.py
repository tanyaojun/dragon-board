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
- GET  /api/hotlist-jev/relay-band：连板指数**分带实测读数**读口（2026-10-18）——
  数据源 = `scripts/jev_relay_band_diagnostic.py --emit-json <PATH>` 的产物（离线零模型调用，
  含逐日 D→次日实测 + 分带/五区/相关表 + provenance）。本读口**不加工不重算**：
  文件缺失/损坏 → ok=False + reason + hint（fail-visible：前端显式标注「分带表未生成」，
  不静默给空表，也不拿前端序列直算冒充实测）。
- GET/POST /api/hotlist-jev/relay-band/refresh（2026-10-19，用户需求）：页面【分带观察】
  滞后/缺失时一键重算分带表。**零模型调用**（只读 Mongo + 本地通达信日线），并后台子进程跑
  `scripts/jev_relay_band_diagnostic.py --emit-json`；POST 起任务，GET 轮询状态，产物经临时文件
  原子替换（刷新期间旧表可读、不读到半成品）。

读口只返回 hotlist_jev_sentiment 原文档（独立观察轨道），不与规则情绪文档合并。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.analysis.hotlist.jev_relay_ammo import QUESTIONS_RELAY
from backend.data.repositories import repository_factory
from backend.services.jev.relay_band import (
    RELAY_BAND_REFRESH_LOG_ENV,      # 再导出：测试与运维引用 routes.<name>
    RELAY_BAND_TABLE_ENV,            # 再导出：读口 env 覆盖名
    band_refresh_command,
    discard_tmp,
    quant_board_root,
    relay_band_refresh_log_path,
    relay_band_script_path,
    relay_band_table_path,
    replace_artifact,
    smoke_artifact_path,
    tmp_artifact_path,
)

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev"])

# ── 展示投影派生（2026-10-24 A1/A2，slot-eod-corpus-confidence-audit-20261024.md）──
# 拥挤度数值口径（拥挤三层概率合计）此前只在前端 hotlistJevApi.ts::jevCrowdingProbability
# 实现（单一事实源债，questionset-review §〇.3/§七登记）——提后端为唯一权威口径；
# 前端改为优先消费读口值、缺字段回退本地同式计算（旧路径兼容）。
CROWDING_PROBABILITY_LAYERS = ("top_acceleration", "late_seal_weakness", "breadth_climax")


def _crowding_probability_sum(answer: Any) -> float | None:
    """choice 答案 → 拥挤三层概率合计（0-1）。非 choice/缺分布/三层全缺 → None 不伪造 0。"""
    if not isinstance(answer, dict) or answer.get("type") != "choice":
        return None
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict):
        return None
    total, seen = 0.0, False
    for layer in CROWDING_PROBABILITY_LAYERS:
        value = probabilities.get(layer)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            total += float(value)
            seen = True
    return total if seen else None


def _attach_crowding_probability(doc: Any, answer_key: str) -> Any:
    """文档浅拷贝附 crowdingProbability 派生字段（不改库内原文档；缺答案 → None）。"""
    if not isinstance(doc, dict):
        return doc
    answer = (doc.get("answers") or {}).get(answer_key)
    return {**doc, "crowdingProbability": _crowding_probability_sum(answer)}


def _answer_confidence(answers: Any, key: str) -> float | None:
    answer = (answers or {}).get(key) if isinstance(answers, dict) else None
    value = (answer or {}).get("confidence") if isinstance(answer, dict) else None
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

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
    """单日 jev 观察轨道读口：槽位文档升序 + eod 文档；无任何文档时不报错不伪造。

    盘中回退（2026-10-27 用户裁决）：指定日全日无槽位/EOD 文档（盘前/节假日）→
    回退 < 指定日最新有档交易日，date 字段透出实际生效日并带 dateFallback 标记；
    盘中当日已有槽位帧时照常返回当日（实时读数优先于回退）。
    """
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}

    try:
        trading_date = date or _latest_date(db, dataset_id)
        if not trading_date:
            return {"ok": True, "date": None, "slots": [], "eod": None, "degradedCount": 0}
        date_fallback = None
        if date:
            from backend.api.jev_view_date import resolve_view_date
            trading_date, date_fallback = resolve_view_date(
                _slots_collection(db), trading_date, {"datasetId": dataset_id})
        rows = list(_slots_collection(db).find(
            {"datasetId": dataset_id, "tradingDate": trading_date}))
        slots = sorted(
            (_attach_crowding_probability(row, "crowding")
             for row in rows if row.get("kind") == "slot"),
            key=lambda row: str(row.get("slotTime") or ""),
        )
        eod = next((row for row in rows if row.get("kind") == "eod"), None)
        eod = _attach_crowding_probability(eod, "day_crowding") if eod else None
        degraded_count = sum(
            1 for row in [*slots, eod] if row and row.get("status") in ("degraded", "no_data"))
        return {"ok": True, "date": trading_date, "slots": slots, "eod": eod,
                "degradedCount": degraded_count,
                **({"dateFallback": date_fallback} if date_fallback else {})}
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
                (_attach_crowding_probability(row, "crowding")
                 for row in day_rows if row.get("kind") == "slot"),
                key=lambda row: str(row.get("slotTime") or ""),
            )
            eod = next((row for row in day_rows if row.get("kind") == "eod"), None)
            eod = _attach_crowding_probability(eod, "day_crowding") if eod else None
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
        # 盘中回退（2026-10-27 用户裁决）：relay-index 是收盘池口径（15:30 后出数），
        # 盘中查当日必无档 → 回退 < 指定日的最新存档，接力四卡/今日连板情绪主表
        # 盘中看上一交易日读数（date 字段透出实际生效日，带 dateFallback 标记）
        date_fallback = None
        if day_doc is None and latest:
            day_doc = col.find_one({"tradingDate": {"$lt": latest, "$ne": None}},
                                   sort=[("tradingDate", -1)])
            if day_doc:
                date_fallback = {"requested": latest, "served": day_doc.get("tradingDate")}
                latest = str(day_doc.get("tradingDate"))
        series = list(col.find(
            {"tradingDate": {"$ne": None}},
            # v6 投影边界：relayStructure 只供选中日卡片，序列（≤400 天）不返——
            # 避免载荷膨胀；缺字段的 v5 旧档由前端显「旧代未采集」（fail-visible）
            {"narrative": 0, "responseRaw": 0, "questionsRaw": 0, "relayStructure": 0},
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
        # 弱转强节点信号（2026-10-21 立项，用户需求：列表直观看节点）：单源
        # analysis/hotlist/weak_to_strong.classify_series；失败降级不连坐读口（SF5 纪律）
        wzs_error: str | None = None
        wzs_map: dict[str, dict] = {}
        try:
            from backend.analysis.hotlist.weak_to_strong import classify_series
            wzs_map = classify_series(db, dataset_id)
        except Exception as exc:
            import sys
            print(f"[relay-index] weak_to_strong classify failed: {exc}", file=sys.stderr)
            wzs_error = f"weak_to_strong_classify_failed: {exc}"
        for r in [*series, day_doc]:
            if r:
                r["wzs"] = wzs_map.get(str(r.get("tradingDate")))
        # 全史基线延续率透传（审查 SF-2：前端不得硬编码 3/18 快照数字，现算为准）
        wzs_baseline = None
        try:
            from backend.analysis.hotlist.weak_to_strong import weak_to_strong_baseline
            b = weak_to_strong_baseline(db, dataset_id) or {}
            if b.get("contTotal"):
                wzs_baseline = {"contOk": b["contOk"], "contTotal": b["contTotal"]}
        except Exception as exc:
            import sys
            print(f"[relay-index] weak_to_strong baseline failed: {exc}", file=sys.stderr)
        payload = {
            "ok": True, "datasetId": dataset_id, "date": latest,
            "day": day_doc,
            "series": series,
            "degradedCount": sum(1 for r in [*series, day_doc] if r and r.get("status") != "ok"),
            "wzsBaseline": wzs_baseline,
        }
        if date_fallback:
            payload["dateFallback"] = date_fallback
        if join_error:
            payload["dayTemperatureDegraded"] = join_error
        if wzs_error:
            payload["wzsDegraded"] = wzs_error
        return payload
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"relay_index_read_failed: {exc}"}


@router.get("/sector-nodes")
def get_sector_nodes(
    date: str | None = None,
    days: int = 60,
) -> dict[str, Any]:
    """板块节点读口（2026-10-24 v1，预登记 sector-nodes-v1-preregistration.md）：

    单日全行（date 给定或最新）+ 近 N 日序列摘要（节点分布/弱转强名单，不含重载荷行）；
    fail-visible：文档缺失/降级日原样透出 status=degraded 与 degraded 原因，不伪造。
    盘中回退（2026-10-27 用户裁决）：指定日文档 16:20 盘后链才落库，查不到时回退
    < 指定日的最新存档并带 dateFallback 标记，主表盘中可看最近可得节点（前端不加
    横幅，KPI 卡自带「{tradingDate} 收盘定档」即实际档期）。
    """
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        col = db["hotlist_jev_sector_nodes"]
        capped_days = max(1, min(int(days), 400))
        latest = date
        if not latest:
            newest = col.find_one({}, {"tradingDate": 1}, sort=[("tradingDate", -1)])
            latest = str(newest.get("tradingDate")) if newest else None
        day_doc = col.find_one({"tradingDate": latest}) if latest else None
        # 盘中回退：指定日无档（16:20 盘后链未跑）→ 取 < 指定日的最新存档，
        # 响应带 dateFallback 标记（$ne None 与序列查询同守卫，防 null 档期混入）
        date_fallback = None
        if day_doc is None and latest:
            day_doc = col.find_one({"tradingDate": {"$lt": latest, "$ne": None}},
                                   sort=[("tradingDate", -1)])
            if day_doc:
                date_fallback = {"requested": latest, "served": day_doc.get("tradingDate")}
                latest = str(day_doc.get("tradingDate"))
        series = list(col.find(
            {"tradingDate": {"$ne": None}},
            # 序列只带节点分布原料（rows 的 board/node/count 子集），全行仅选中日返回
            {"tradingDate": 1, "version": 1, "status": 1, "degraded": 1,
             "rows.board": 1, "rows.node": 1, "rows.count": 1, "rows.promN": 1},
        ).sort("tradingDate", -1).limit(capped_days))
        series.reverse()
        # 序列摘要：pop 掉 rows 子集换算节点分布（day_doc 不进此循环——
        # 它是选中日全量文档，rows 必须原样保留给前端主表，2026-10-24 review 修复）
        for s in series:
            if not s:
                continue
            dist: dict[str, int] = {}
            wzs_boards: list[str] = []
            for r in s.pop("rows", None) or []:
                node = r.get("node")
                if node:
                    dist[node] = dist.get(node, 0) + 1
                if node == "wzs":
                    wzs_boards.append(str(r.get("board") or ""))
            s["nodeDist"] = dist
            s["wzsBoards"] = wzs_boards
        if day_doc:
            dist: dict[str, int] = {}
            wzs_boards: list[str] = []
            for r in day_doc.get("rows") or []:
                node = r.get("node")
                if node:
                    dist[node] = dist.get(node, 0) + 1
                if node == "wzs":
                    wzs_boards.append(str(r.get("board") or ""))
            day_doc["nodeDist"] = dist
            day_doc["wzsBoards"] = wzs_boards
        # 审计 P3：series 含选中日、doc 也是选中日，直接相加会双计——按交易日去重
        degraded_dates = {str(r.get("tradingDate")) for r in [*series, day_doc]
                          if r and r.get("status") != "ok"}
        return {"ok": True, "date": latest, "days": capped_days,
                "series": series, "doc": day_doc,
                "degradedCount": len(degraded_dates),
                **({"dateFallback": date_fallback} if date_fallback else {})}
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"sector_nodes_read_failed: {exc}"}


@router.get("/market-cycle")
def get_market_cycle(date: str | None = None, days: int = 60) -> dict[str, Any]:
    """市场情绪周期读口（第4课 P2，预登记 market-cycle-preregistration-20261112.md）。

    单日全文档（date 给定或最新）+ 近 N 日轻量序列（态/天花板/事件类型/转折/参照）。
    fail-visible：降级日原样透出 status；盘中回退 < 指定日最新存档 + dateFallback。
    零 token 确定性轨道（状态机输入=事件流，参照并列无预设权威，裁决 1A）。
    """
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        col = db["hotlist_jev_market_cycle"]
        capped = max(1, min(int(days), 400))
        latest = date
        if not latest:
            newest = col.find_one({}, {"tradingDate": 1}, sort=[("tradingDate", -1)])
            latest = str(newest.get("tradingDate")) if newest else None
        day_doc = col.find_one({"tradingDate": latest}) if latest else None
        date_fallback = None
        if day_doc is None and latest:
            day_doc = col.find_one({"tradingDate": {"$lt": latest, "$ne": None}},
                                   sort=[("tradingDate", -1)])
            if day_doc:
                date_fallback = {"requested": latest, "served": day_doc.get("tradingDate")}
                latest = str(day_doc.get("tradingDate"))
        series = list(col.find(
            {"tradingDate": {"$ne": None}},
            {"tradingDate": 1, "status": 1, "state": 1, "daysInState": 1,
             "ceiling.maxBoard": 1, "ceiling.threePlusN": 1,
             "events.type": 1, "transition.trigger": 1, "transition.to": 1,
             "reference": 1}).sort("tradingDate", -1).limit(capped))
        series.reverse()
        for s in series:
            s["eventTypes"] = [e.get("type") for e in s.pop("events", None) or []]
        degraded = {str(r.get("tradingDate")) for r in [*series, day_doc]
                    if r and r.get("status") != "ok"}
        return {"ok": True, "date": latest, "days": capped, "series": series,
                "doc": day_doc, "degradedCount": len(degraded),
                **({"dateFallback": date_fallback} if date_fallback else {})}
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"market_cycle_read_failed: {exc}"}


class MarketCycleRerunPayload(BaseModel):
    date: str
    force: bool = False
    datasetId: str = "dragonboard_live"


@router.post("/market-cycle/rerun")
def post_market_cycle_rerun(payload: MarketCycleRerunPayload) -> dict[str, Any]:
    """市场情绪周期单日复跑（第4课 P2，**零 token 确定性**，不受 jev gate 限制）。

    复用生产入口 omc.settle_day（不另写调用链）；prev_state 自动读前一日库态。降级照常
    落痕透出（fail-visible）。注：状态机有链依赖——若复跑改变当日事件，其后各日态需
    `--replay-state` 重放方一致（单日 rerun 不级联，与 relay-index/rerun 单日语义同）。
    """
    date = (payload.date or "").strip()
    if not date:
        return {"ok": False, "errorCode": "bad_date", "error": "date required"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.operations import market_cycle as omc
        doc = omc.settle_day(db, date, payload.datasetId, force=bool(payload.force))
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"market_cycle_rerun_failed: {exc}"}
    return {"ok": doc.get("status") == "ok", "date": date, "day": doc,
            "status": doc.get("status"), "state": doc.get("state"),
            "events": len(doc.get("events") or [])}


@router.get("/sector-pulse")
def get_sector_pulse(date: str | None = None) -> dict[str, Any]:
    """V2c 盘中红盘提示读口（2026-10-25，预登记 sector-nodes-v2c-intraday-preregistration.md）：

    当日=实时计算（60s 缓存 + 交易日 ≥15:05 落 15:00 帧）；历史日只读 stored 帧
    （盘中报价不可回放，重算会拿当前价错标读数）。fail-visible：TDX 不可用/成员
    不可考原因透出，不伪 0。提示列不进节点判定（预登记 §六 冻结）。
    """
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.operations.sector_pulse import COLLECTION_PULSE, get_pulse_cached
        today = datetime.now().strftime("%Y-%m-%d")
        target = date or today
        if target != today:
            frame = db[COLLECTION_PULSE].find_one({"_id": f"{target}:PULSE"})
            return {"ok": True, "source": "stored", "date": target, "doc": frame,
                    "reason": None if frame else "该日无收盘帧（15:05 后无请求 / 非交易日 / 早于 V2c 投产日）"}
        return get_pulse_cached(db, target)
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"sector_pulse_read_failed: {exc}"}


class JevRelayRerunPayload(BaseModel):
    date: str
    force: bool = True   # 默认重判（含已 ok 日）；false 时交给 run_relay_index_day 的幂等跳过
    datasetId: str = "dragonboard_live"


@router.post("/relay-index/rerun")
def post_relay_index_rerun(payload: JevRelayRerunPayload) -> dict[str, Any]:
    """连板情绪指数**单日复跑**（2026-10-19 用户需求）：网络抖动/降级日手动重判。

    - 显式用户意图（同 /evaluate：不受 JEV_SENTIMENT_ENABLED gate 限制），origin 仍由
      ``run_relay_index_day`` 落 ``relay_index_daily``（不新增 origin，保持存储单主链）。
    - 复用生产判定入口（叙事拼装 + ``_dispatch_jev`` 退避重试），**不另写一份调用链**。
    - 失败照常落 degraded 文档，响应透出 ``errorCode/errorDetail``，不伪造读数（§4.0）。
    - 「本次是否真重判」以 ``computedAt`` 是否刷新为准（评审 F6）：入口对韭研 final 缺失只跳过
      不写文档，若该日已有旧档，旧档状态不得冒充本次结果 → ``errorCode=not_rerun``。
    - 返回落库后的完整单日文档（与 GET ``day`` 同形，含 relayStructure/narrative）。
    """
    if not ((os.environ.get("JEV_TYPESAFE_KEY") or "").strip()
            or (os.environ.get("JEV_CF_TOKEN") or "").strip()):
        return {"ok": False, "errorCode": "missing_token",
                "error": "JEV_TYPESAFE_KEY / JEV_CF_TOKEN not configured"}
    date = (payload.date or "").strip()
    if not date:
        return {"ok": False, "errorCode": "bad_date", "error": "date required"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.operations.jev_relay_index import COLLECTION, run_relay_index_day

        # 重算新鲜度基线：入口对「韭研 final 缺失」只跳过不写文档，若该日已有旧档，
        # 旧 computedAt 会被反推成「本次重跑结果」——必须区分「本次真重判」与「本次被跳过」
        # （2026-10-19 评审 F6：否则会用旧档冒充成功，且把「原料缺失」误报成「网络抖动」）。
        before = db[COLLECTION].find_one({"_id": f"{date}:RELAY"}, {"computedAt": 1})
        before_at = (before or {}).get("computedAt")
        run_relay_index_day(db, [date], force=bool(payload.force),
                            dataset_id=payload.datasetId)
        day_doc = db[COLLECTION].find_one({"_id": f"{date}:RELAY"})
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"relay_rerun_failed: {exc}"}
    if day_doc is None:
        # run_relay_index_day 对「韭研 final 缺失」只跳过不写文档 → 显式报错，不伪装成功
        return {"ok": False, "errorCode": "not_written",
                "error": f"no relay doc for {date}（非交易日或韭研 final 缺失）"}
    if before is not None and day_doc.get("computedAt") == before_at:
        # 该日**本已有档**且 computedAt 未刷新 ⇒ 入口本次没重判（韭研 final 缺失而跳过）。
        # 旧档状态不能代表本次结果：既不能用它报 ok，也不能把「原料缺失」说成「网络抖动」。
        return {"ok": False, "errorCode": "not_rerun", "date": date, "day": day_doc,
                "status": day_doc.get("status"),
                "error": ("入口未重判（当日韭研 final 缺失，已按旧档保留）；"
                          "旧档状态不代表本次结果")}
    return {"ok": day_doc.get("status") == "ok", "date": date, "day": day_doc,
            "status": day_doc.get("status"), "relayIndex": day_doc.get("relayIndex"),
            "relayPhase": day_doc.get("relayPhase"), "errorCode": day_doc.get("errorCode"),
            "errorDetail": day_doc.get("errorDetail")}


class JevSlotRerunPayload(BaseModel):
    tradingDate: str
    slotTime: str
    snapshotType: str = "half_hour"
    datasetId: str = "dragonboard_live"


@router.post("/slots/rerun")
def post_slot_rerun(payload: JevSlotRerunPayload) -> dict[str, Any]:
    """jev 帧级槽位情绪**单日单槽复跑**（2026-10-19 用户需求）：网络抖动/降级槽手动重判。

    - 显式用户意图（同 /evaluate：不受 JEV_SENTIMENT_ENABLED gate 限制），origin=manual
      （与 /evaluate 手动补评同源，不新增 origin）。
    - 复用生产计算入口 ``compute_and_upsert_for_slot``（帧/行/锚装配 + jev 退避重试），
      不另写一份调用链；``snapshotType`` 显式透传，防 quarter_hour 槽被按 half_hour 重判。
    - 失败照常落 degraded/no_data 文档，响应透出 ``errorCode/errorDetail``，不伪造读数（§4.0）。
    - 返回落库后的完整槽位文档（与 GET ``/series`` 的槽位同形，含 narrative/answers）。
    """
    if not ((os.environ.get("JEV_TYPESAFE_KEY") or "").strip()
            or (os.environ.get("JEV_CF_TOKEN") or "").strip()):
        return {"ok": False, "errorCode": "missing_token",
                "error": "JEV_TYPESAFE_KEY / JEV_CF_TOKEN not configured"}
    trading_date = (payload.tradingDate or "").strip()
    slot_time = (payload.slotTime or "").strip()
    if not trading_date or not slot_time:
        return {"ok": False, "errorCode": "bad_slot",
                "error": "tradingDate and slotTime required"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.services.jev.jev_sentiment_compute import compute_and_upsert_for_slot

        compute_and_upsert_for_slot(
            db, dataset_id=payload.datasetId, snapshot_type=payload.snapshotType,
            trading_date=trading_date, slot_time=slot_time, origin="manual")
        doc = _slots_collection(db).find_one(
            {"_id": f"{payload.datasetId}:{payload.snapshotType}:{trading_date}:{slot_time}"})
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"slot_rerun_failed: {exc}"}
    if doc is None:
        return {"ok": False, "errorCode": "not_written",
                "error": f"no slot doc for {trading_date} {slot_time}"}
    return {"ok": doc.get("status") == "ok", "slot": doc, "status": doc.get("status"),
            "errorCode": doc.get("errorCode"), "errorDetail": doc.get("errorDetail")}


class JevEodRerunPayload(BaseModel):
    tradingDate: str
    snapshotType: str = "half_hour"
    datasetId: str = "dragonboard_live"


@router.post("/eod/rerun")
def post_eod_rerun(payload: JevEodRerunPayload) -> dict[str, Any]:
    """日级 EOD 情绪**单日复跑**（2026-10-19 用户需求）：网络抖动/降级 EOD 手动重判。

    - 显式用户意图（同 /evaluate：不受 JEV_SENTIMENT_ENABLED gate 限制），origin=manual。
    - 复用生产计算入口 ``compute_and_upsert_for_day``（当日槽位证据汇总 + 锚装配 + jev 退避重试），
      不另写一份调用链；``snapshotType`` 显式透传，与「当日逐槽」表消费的槽口径一致。
    - 失败照常落 degraded/no_data 文档，响应透出 ``errorCode/errorDetail``，不伪造读数（§4.0）。
    - 返回落库后的完整 EOD 文档（与 GET ``/series`` 的 ``eod`` 同形，含 narrative/answers）。
    """
    if not ((os.environ.get("JEV_TYPESAFE_KEY") or "").strip()
            or (os.environ.get("JEV_CF_TOKEN") or "").strip()):
        return {"ok": False, "errorCode": "missing_token",
                "error": "JEV_TYPESAFE_KEY / JEV_CF_TOKEN not configured"}
    trading_date = (payload.tradingDate or "").strip()
    if not trading_date:
        return {"ok": False, "errorCode": "bad_date", "error": "tradingDate required"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.services.jev.jev_sentiment_compute import compute_and_upsert_for_day

        compute_and_upsert_for_day(
            db, dataset_id=payload.datasetId, snapshot_type=payload.snapshotType,
            trading_date=trading_date, origin="manual")
        doc = _slots_collection(db).find_one(
            {"_id": f"{payload.datasetId}:{payload.snapshotType}:{trading_date}:EOD"})
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"eod_rerun_failed: {exc}"}
    if doc is None:
        return {"ok": False, "errorCode": "not_written",
                "error": f"no EOD doc for {trading_date}"}
    return {"ok": doc.get("status") == "ok", "eod": doc, "status": doc.get("status"),
            "errorCode": doc.get("errorCode"), "errorDetail": doc.get("errorDetail")}


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
        date_fallback = None
        doc = get_action_doc(db, target_date, kind)
        if doc is None and date is None:
            # 最新日可能只有 midday——回落找该日任一 kind
            for k in ("midday", "final"):
                doc = get_action_doc(db, target_date, k)
                if doc:
                    break
        elif doc is None and date is not None:
            # 生效日回退（2026-10-29 隔日看盘）：先同日回落另一 kind（请求日有 midday
            # 无 final → 午间名单照显，更新）；同日全缺 → 跨日回退 < 请求日最新有档日；
            # dateFallback 仅跨日时透出。
            for k in ("final", "midday"):
                if k != kind:
                    doc = get_action_doc(db, target_date, k)
                    if doc:
                        break
            if doc is None:
                earlier = [d["date"] for d in dates if d["date"] < target_date]
                if earlier:
                    served = earlier[-1]
                    for k in (kind, "final", "midday"):
                        doc = get_action_doc(db, served, k)
                        if doc:
                            break
                    if doc:
                        date_fallback = {"requested": target_date, "served": served}
        if doc is None:
            return {"ok": True, "dates": dates, "doc": None,
                    "degraded": True, "reason": f"{target_date}:{kind} 未落库"}
        doc = {k: v for k, v in doc.items() if k != "_id"}
        result = {"ok": True, "dates": dates, "doc": doc}
        if date_fallback:
            result["dateFallback"] = date_fallback
        return result
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

        def _prob(key: str) -> float | None:
            probs = _probs(key) or {}
            value = probs.get(_choice(key) or "")
            return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

        return {"ok": True, "date": trading_date,
                "jev": {"status": doc.get("status"),
                       "dayTemperature": scores.get("day_temperature"),
                       "dayStage": _choice("day_stage"),
                       "dayStageProbability": _prob("day_stage"),
                       "dayStageConfidence": _answer_confidence(answers, "day_stage"),
                       "dayPattern": _choice("day_pattern"),
                       "dayPatternProbability": _prob("day_pattern"),
                       "dayPatternConfidence": _answer_confidence(answers, "day_pattern"),
                       "dayTemperatureConfidence": _answer_confidence(answers, "day_temperature"),
                       "dayCrowding": _choice("day_crowding"),
                       "dayCrowdingProbabilities": _probs("day_crowding"),
                       "dayCrowdingProbability": _crowding_probability_sum(answers.get("day_crowding")),
                       "dayCrowdingConfidence": _answer_confidence(answers, "day_crowding"),
                       "historyAnchorRange": doc.get("historyAnchorRange"),
                       "computedAt": doc.get("computedAt"),
                       # 2026-10-22 日级语料修复：覆盖度/代际戳进概览读口（前端角标用；
                       # 旧文档字段缺失 → null，不伪造）
                       "anchoredSlotTime": doc.get("anchoredSlotTime"),
                       "frameCoverage": doc.get("frameCoverage"),
                       "corpusCaliberVersion": doc.get("corpusCaliberVersion"),
                       "evidenceRawUnavailable": doc.get("evidenceRawUnavailable")},
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


# 分带实测读数（离线诊断产物；不加工不重算，缺失/损坏 fail-visible）。
# 路径/命令/原子替换的单一事实源 = backend/services/jev/relay_band.py（盘后链共用）。
_relay_band_table_path = relay_band_table_path   # 保留模块级别名（测试可 monkeypatch）


@router.get("/relay-questions")
def get_relay_questions() -> dict[str, Any]:
    """连板指数题目集 criteria 只读快照（2026-10-18 SSOT 收敛，review B1/B2）。

    单一事实源 = backend/analysis/hotlist/jev_relay_ammo.py 的 QUESTIONS_RELAY。
    前端 KPI 档位描述与判定明细行 tooltip 消费本读口的**全文**；页面内静态 DESC 表
    仅作读口失败时的回落（页面注释已声明为摘要，不再声称逐字）。
    纯读、零计算、零模型调用。
    """
    questions: dict[str, dict[str, str]] = {}
    for qid, spec in QUESTIONS_RELAY.items():
        if spec.get("type") == "choice" and isinstance(spec.get("criteria"), dict):
            questions[qid] = dict(spec["criteria"])
    return {"ok": True, "questions": questions}


@router.get("/relay-band")
def get_relay_band() -> dict[str, Any]:
    """连板指数分带实测读数（离线诊断产物；fail-visible，不重算不伪造）。"""
    path = _relay_band_table_path()
    hint = (f"未生成：点页面【分带表未就绪】提示内的刷新按钮，或 cd quant-board 后跑 "
            f"python scripts/jev_relay_band_diagnostic.py --emit-json {path}"
            f"（零模型调用，全窗约 5–9 分钟）")
    if not path.exists():
        return {"ok": False, "degraded": True, "reason": "band_table_missing",
                "hint": hint, "artifactPath": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"band_table_unreadable: {exc}",
                "hint": hint, "artifactPath": str(path)}
    # days 必须是**非空列表**：2026-10-18 review P2-4——旧式 `not payload.get("days")`
    # 会放行 `"days": "x"` / 字典等损坏产物，页面 `bandDoc()` 因 `Array.isArray` 失败返回 null，
    # 而 `bandDiagMissing` 见 `ok===true` 返回空串 → 落到「无分带读数」且不显示 reason/hint（fail-visible 退化）。
    if not isinstance(payload, dict) or not isinstance(payload.get("days"), list) or not payload["days"]:
        return {"ok": False, "degraded": True, "reason": "band_table_empty",
                "hint": hint, "artifactPath": str(path)}
    payload = dict(payload)
    payload["artifactPath"] = str(path)
    payload["artifactMtime"] = path.stat().st_mtime
    return payload


# ── 分带表刷新任务（2026-10-19 用户需求）────────────────────────────────────
# 页面【分带观察】滞后/缺失时一键重算：零模型调用（只读 Mongo + 本地通达信日线，
# 全窗约 5–9 分钟）。后台子进程跑 scripts/jev_relay_band_diagnostic.py --emit-json，
# POST 起任务、GET 轮询状态；产物先写临时文件、成功退出后原子替换，
# 保证刷新期间旧表仍可读、不会读到半成品（fail-visible：失败保留旧表 + 日志尾部）。
_BAND_REFRESH: dict[str, Any] = {
    "proc": None, "startedAt": None, "finishedAt": None, "returncode": None,
    "error": None, "days": 0, "logPath": None, "tmpPath": None, "targetPath": None,
}
_BAND_REFRESH_LOCK = threading.Lock()


# API 侧后台任务的最长运行时间（评审 uncertain U1）：裸 Popen 无 timeout，若诊断脚本挂死，
# 页面会无限 5s 轮询「刷新中…」且无失败出口。须 > 盘后链 sync 路径的 900s（同脚本同窗）。
_BAND_REFRESH_MAX_RUNTIME_SECONDS = 1200


def _band_now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _band_refresh_view(running: bool) -> dict[str, Any]:
    """任务状态视图（调用方持锁）。logTail 便于页面直接看到失败原因/进度。"""
    st = _BAND_REFRESH
    log = Path(st["logPath"]) if st.get("logPath") else relay_band_refresh_log_path()
    out: dict[str, Any] = {
        "running": running,
        "ok": bool(not running and st.get("returncode") == 0 and not st.get("error")),
        "startedAt": st.get("startedAt"), "finishedAt": st.get("finishedAt"),
        "returncode": st.get("returncode"), "error": st.get("error"),
        "days": st.get("days", 0),
        # 任务视图报**本次任务**的产物路径（days>0 冒烟走另存路径，不能报正式读数路径）
        "logPath": str(log),
        "artifactPath": str(st.get("targetPath") or _relay_band_table_path()),
    }
    if log.exists():
        try:
            out["logTail"] = log.read_text(encoding="utf-8", errors="replace")[-1500:]
        except Exception:
            pass
    return out


def _band_refresh_poll() -> dict[str, Any]:
    """轮询任务；子进程结束则**恰好一次**收尾（成功→原子替换产物；失败→撤掉临时文件）。"""
    with _BAND_REFRESH_LOCK:
        proc = _BAND_REFRESH.get("proc")
        if proc is None:
            return _band_refresh_view(running=False)
        if proc.poll() is None:
            # 挂死保护（评审 uncertain U1）：超过预算即 kill 并结构化收尾，避免页面无限轮询。
            started = _BAND_REFRESH.get("startedAt") or ""
            try:
                elapsed = (datetime.now() - datetime.fromisoformat(started)).total_seconds()
            except Exception:
                elapsed = 0.0
            if elapsed > _BAND_REFRESH_MAX_RUNTIME_SECONDS:
                try:
                    proc.kill()
                except Exception:
                    pass
                _BAND_REFRESH["returncode"] = proc.poll()
                _BAND_REFRESH["finishedAt"] = _band_now_iso()
                _BAND_REFRESH["error"] = f"band_refresh_timeout: {_BAND_REFRESH_MAX_RUNTIME_SECONDS}s"
                tmp = _BAND_REFRESH.get("tmpPath")
                if tmp:
                    discard_tmp(Path(tmp))
                _BAND_REFRESH["proc"] = None
                return _band_refresh_view(running=False)
            return _band_refresh_view(running=True)
        rc = proc.returncode
        _BAND_REFRESH["returncode"] = rc
        _BAND_REFRESH["finishedAt"] = _band_now_iso()
        tmp = _BAND_REFRESH.get("tmpPath")
        target = _BAND_REFRESH.get("targetPath")
        if rc == 0 and tmp and target and Path(tmp).exists():
            replaced = replace_artifact(Path(tmp), Path(target))   # 旧表到此刻一直完整可读
            if not replaced.get("ok"):
                _BAND_REFRESH["error"] = replaced["error"]
                discard_tmp(Path(tmp))   # 替换失败同样撤半成品（评审 F3）
        else:
            # 失败照常如实上报，旧表不动；清掉半成品临时文件（不落 0/空表冒充）
            _BAND_REFRESH["error"] = (f"script_exit_{rc}" if rc else "artifact_missing")
            if tmp:
                discard_tmp(Path(tmp))
        _BAND_REFRESH["proc"] = None
        return _band_refresh_view(running=False)


class JevBandRefreshPayload(BaseModel):
    days: int = 0   # 0=全窗口；>0 只取最近 N 个判定日（冒烟用）


@router.post("/relay-band/refresh")
def post_relay_band_refresh(payload: JevBandRefreshPayload | None = None) -> dict[str, Any]:
    """启动分带表重算后台任务（零模型调用）。已运行时不重复起（防并发）。"""
    days = int(payload.days) if payload else 0
    if days < 0:
        return {"ok": False, "reason": "bad_days", "error": "days must be >= 0"}
    script = relay_band_script_path()
    if not script.exists():
        return {"ok": False, "reason": "script_missing", "scriptPath": str(script)}
    target = _relay_band_table_path()
    if days:
        # days>0 = 冒烟跑（截断窗口），产物另存，不得覆盖正式读数（评审 F5）
        target = smoke_artifact_path(target, days)
    log = relay_band_refresh_log_path()
    with _BAND_REFRESH_LOCK:
        proc = _BAND_REFRESH.get("proc")
        if proc is not None and proc.poll() is None:
            return {"ok": False, "reason": "already_running", "running": True,
                    "startedAt": _BAND_REFRESH.get("startedAt")}
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return {"ok": False, "reason": f"log_dir_failed: {exc}"}
        tmp = tmp_artifact_path(target, str(os.getpid()))
        try:
            with open(log, "w", encoding="utf-8") as fh:
                p = subprocess.Popen(                      # noqa: S603 - 固定脚本+固定参数
                    band_refresh_command(tmp, days), cwd=str(quant_board_root()),
                    stdout=fh, stderr=subprocess.STDOUT,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"})
        except Exception as exc:
            return {"ok": False, "reason": f"spawn_failed: {exc}"}
        _BAND_REFRESH.update({
            "proc": p, "startedAt": _band_now_iso(), "finishedAt": None,
            "returncode": None, "error": None, "days": days, "logPath": str(log),
            "tmpPath": str(tmp), "targetPath": str(target),
        })
        return {"ok": True, "running": True, "startedAt": _BAND_REFRESH["startedAt"],
                "pid": p.pid, "days": days, "scriptPath": str(script),
                "artifactPath": str(target), "logPath": str(log)}


@router.get("/relay-band/refresh")
def get_relay_band_refresh() -> dict[str, Any]:
    """分带表刷新任务状态（页面 5s 轮询；纯读，零模型调用）。"""
    return _band_refresh_poll()


_KPL_RANKING_EMPTY_MEMO: dict[str, float] = {}   # 空结果 10 分钟 memo（防非交易日反复打上游）

@router.get("/sector-name-check")
def get_sector_name_check(date: str | None = None) -> dict[str, Any]:
    """韭研 ↔ KPL 板块名录每日匹配诊断（2026-11-01 用户需求）：

    KPL 名录=当日板块排行全量（kpl_ranking_service，带上游缓存）；匹配规则
    单一事实源=theme_event_digest（归一+ALIASES+后缀桥）。未匹配清单即
    ALIASES 维护候选。fail-visible：任一侧不可用如实报错，不静默空表。
    """
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.operations.sector_name_check import check_sector_names
        from backend.services import kpl_ranking_service
    except Exception as exc:
        return {"ok": False, "reason": f"import_failed: {exc}"}
    target = (date or "").strip() or datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(target, "%Y-%m-%d")
    except ValueError:
        return {"ok": False, "reason": f"invalid_date: {target}"}
    # 非交易日/盘前回退：目标日无数据 → 逐日回退最多 7 天找最近有数据交易日
    # （与前端 kplFetchSectorUniverse 同哲学）；空结果短 memo 10 分钟，防反复打上游
    now_ts = time.time()
    if len(_KPL_RANKING_EMPTY_MEMO) > 256:   # 卫生：淘汰已过期条目防无界增长
        for k in [k for k, v in _KPL_RANKING_EMPTY_MEMO.items() if v <= now_ts]:
            _KPL_RANKING_EMPTY_MEMO.pop(k, None)
    ranking = None
    for i in range(8):
        d = (datetime.strptime(target, "%Y-%m-%d")
             - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in _KPL_RANKING_EMPTY_MEMO and _KPL_RANKING_EMPTY_MEMO[d] > now_ts:
            continue
        try:
            r = kpl_ranking_service.get_sector_ranking(d)
        except Exception:
            # 单日上游抖动不整段失败：记空 memo 后继续回退更早日（review 2026-11-01）
            _KPL_RANKING_EMPTY_MEMO[d] = time.time() + 600
            continue
        if (r or {}).get("items"):
            ranking = r
            break
        _KPL_RANKING_EMPTY_MEMO[d] = time.time() + 600
    if ranking is None:
        return {"ok": False,
                "reason": f"kpl_ranking_empty: 目标日 {target} 起 7 天内均无排行数据"}
    try:
        out = check_sector_names(db, target, kpl_ranking=ranking)
    except Exception as exc:
        return {"ok": False, "reason": f"sector_name_check_failed: {exc}"}
    if out.get("ok"):
        out["kplDate"] = ranking.get("date")
        if out.get("kplDate") and out.get("date") and out["kplDate"] != out["date"]:
            out["dateMixed"] = True   # 两侧名录日期不同，前端如实标注
    return out


@router.get("/watchlist")
def get_watchlist_route(date: str | None = None) -> dict[str, Any]:
    """V4-G 盯盘票清单读口（2026-11-01，预登记 v4f 文档 §六；提示层不进判据）：

    板块=当日弱转强候选；票=昨日空间龙一（含断板反包候选）+ 昨日连板≥2 核心票。
    仅支持当日（盘中工具：历史日无盘中报价，重算会拿当前价错标读数，不提供）。
    fail-visible：候选空/龙一基线缺失/报价不可考逐层透出。
    """
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "reason": f"mongodb_unavailable: {exc}"}
    from backend.operations.sector_pulse import get_watchlist
    target = (date or "").strip() or datetime.now().strftime("%Y-%m-%d")
    if target != datetime.now().strftime("%Y-%m-%d"):
        return {"ok": False,
                "reason": "watchlist_live_only: 盯盘清单仅支持当日（历史日无盘中报价，不重算错标）"}
    try:
        return get_watchlist(db, target)
    except Exception as exc:
        return {"ok": False, "reason": f"watchlist_failed: {exc}"}
