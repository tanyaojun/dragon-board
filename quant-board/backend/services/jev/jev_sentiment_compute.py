# -*- coding: utf-8 -*-
"""jev 情绪判定问题集 v2 生产计算服务（2026-10-02 立项：双表并存的 v2 表）。

jev 情绪判定生产计算服务（2026-10-02 V1 退役后唯一情绪链）：温度=锚定近 20 交易日分位的市场热度计，
拥挤=离散归层（证据分级判据），档位=锚定分位判读。token 缺失降级落库不阻断采集链。2026-10-02 单一事实源裁决：gate 环境变量删除（V1 已灭，无双轨可回退）。

锚日历化（Q3 混季归因修复）：窗口按交易日历取严格早于当日的近 20 个交易日（每历日一条，
数据缺失日照实记 None），不再用"最近 20 个有数日"跨季凑数。
"""
from __future__ import annotations

import os
import time
from typing import Any

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS,
    JEV_SLOT_QUESTIONS,
    QUESTION_SET_VERSION,
    build_day_jev_state,
    build_history_anchor,
    build_slot_jev_state,
    collect_slot_evidence,
    extract_history_anchor_range,
)
from backend.services.jev.jev_client import call_jev, parse_jev_response

_DEFAULT_ACCOUNT = "921cf15176f84c90ea49865334af32c6"


def _jev_config() -> tuple[bool, str, str]:
    """(enabled, token, account)。每次调用读取，兼容运行时改环境变量。"""
    enabled = os.environ.get("JEV_SENTIMENT_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    token = os.environ.get("JEV_CF_TOKEN", "").strip()
    account = os.environ.get("JEV_CF_ACCOUNT", _DEFAULT_ACCOUNT).strip() or _DEFAULT_ACCOUNT
    return enabled, token, account


# ── 快照取数（直查快照库；帧→行→analysis join 与规则链同源）──


def _load_frame(db: Any, dataset_id: str, snapshot_type: str, trading_date: str, slot_time: str) -> dict | None:
    return db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time},
        sort=[("timestamp", -1), ("snapshotId", -1)],
    )


def _load_rows(db: Any, dataset_id: str, snapshot_id: str) -> list[dict]:
    return list(db["snapshot_stock_rows"].find({"datasetId": dataset_id, "snapshotId": snapshot_id}))


def _load_analysis_by_code(db: Any, dataset_id: str, snapshot_id: str) -> dict:
    rows = db["snapshot_analysis"].find(
        {"datasetId": dataset_id, "snapshotId": snapshot_id},
        {"_id": 0, "code": 1, "analysis": 1},
    )
    return {str(row.get("code")): row.get("analysis") for row in rows if row.get("code")}


def _half_hour_slots() -> list[str]:
    from backend.snapshot_collector.slots import SLOT_TIMES

    return [str(slot) for slot in SLOT_TIMES.get("half_hour") or []]


def _slots_of_date(db: Any, dataset_id: str, snapshot_type: str, trading_date: str) -> list[str]:
    slots = set()
    for f in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date},
            {"slotTime": 1}):
        slot = str(f.get("slotTime") or "")
        if len(slot) == 5 and slot[2] == ":":
            slots.add(slot)
    return sorted(slots)


def _collect_evidence(db: Any, dataset_id: str, snapshot_type: str, trading_date: str,
                      slot_time: str, yesterday_rows: list,
                      yesterday_amounts: dict[str, float] | None = None) -> dict | None:
    frame = _load_frame(db, dataset_id, snapshot_type, trading_date, slot_time)
    if frame is None:
        return None
    snapshot_id = str(frame.get("snapshotId") or "")
    rows = _load_rows(db, dataset_id, snapshot_id)
    if not rows:
        return None
    return collect_slot_evidence(
        frame=frame, rows=rows, yesterday_rows=yesterday_rows,
        analysis_by_code=_load_analysis_by_code(db, dataset_id, snapshot_id), slot_time=slot_time,
        yesterday_same_slot_total_amount=(yesterday_amounts or {}).get(slot_time))


def _latest_yesterday_rows(db: Any, dataset_id: str, snapshot_type: str, trading_date: str) -> list:
    """上一交易日最新 half_hour 帧行（昨日承接/新进淘汰的对比基线）。"""
    latest_date = _latest_date_before(db, dataset_id, snapshot_type, trading_date)
    if latest_date is None:
        return []
    frame = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": latest_date},
        sort=[("timestamp", -1), ("snapshotId", -1)],
    )
    if not frame:
        return []
    return _load_rows(db, dataset_id, str(frame.get("snapshotId") or ""))


def _latest_date_before(db: Any, dataset_id: str, snapshot_type: str, trading_date: str) -> str | None:
    dates = sorted({
        str(f.get("tradingDate"))
        for f in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type}, {"tradingDate": 1})
        if f.get("tradingDate") and str(f.get("tradingDate")) < trading_date
    })
    return dates[-1] if dates else None


def _yesterday_slot_total_amount(db: Any, dataset_id: str, snapshot_type: str,
                                 trading_date: str, slot_time: str) -> float | None:
    return _yesterday_total_amounts_by_slot(db, dataset_id, snapshot_type, trading_date).get(slot_time)


def _yesterday_total_amounts_by_slot(db: Any, dataset_id: str, snapshot_type: str,
                                     trading_date: str) -> dict[str, float]:
    """上一交易日各槽位帧的两市总成交额（同期量能基线映射）；缺失槽位不在结果中。"""
    latest_date = _latest_date_before(db, dataset_id, snapshot_type, trading_date)
    if latest_date is None:
        return {}
    out: dict[str, float] = {}
    for f in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": latest_date}, {"indices": 1, "slotTime": 1}):
        slot = str(f.get("slotTime") or "")
        entry = (f.get("indices") or {}).get("totalAmount") if isinstance(f.get("indices"), dict) else None
        if len(slot) == 5 and slot[2] == ":" and isinstance(entry, dict):
            amount = entry.get("amount")
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                out[slot] = float(amount)
    return out

ANCHOR_WINDOW = 20


def build_history_stats_calendar(db: Any, dataset_id: str, trading_date: str,
                                 window: int = ANCHOR_WINDOW) -> list[dict]:
    """近 window 个交易日（日历口径，严格 < 当日）收盘统计，每历日一条。

    数据源=v2 15:00 槽文档 evidenceRaw（2026-10-02 用户裁决 V1 退役后锚自供：
    v2 槽文档与 v1 同为 collect_slot_evidence 产物，字段同构）；当日文档缺失或
    指标缺失 → 该历日相应字段 None（fail-visible：锚段会标注有效样本数，不跨季凑数）。
    """
    dates = sorted({
        str(r["tradingDate"]) for r in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": "half_hour",
             "tradingDate": {"$lt": trading_date, "$gt": "2020-01-01"}},
            {"tradingDate": 1}) if r.get("tradingDate")
    })[-window:]
    stats: list[dict] = []
    for date in dates:
        doc = db["hotlist_jev_sentiment"].find_one(
            {"datasetId": dataset_id, "snapshotType": "half_hour", "kind": "slot",
             "slotTime": "15:00", "tradingDate": date},
            {"evidenceRaw": 1})
        ev = (doc or {}).get("evidenceRaw") or {}
        limit = ev.get("limit") or {}
        amount = (ev.get("totalAmount") or {}).get("amount")
        zt = limit.get("ztCount")
        # 伪 0 防线（v2.3 教训）：limitSummary 损坏时代 ztCount/maxBoard 记 0 视为缺失而非零值；
        # ztCount 无效=同源 limit 块整体不可信，zhabanRate 联动置 None
        zt_ok = isinstance(zt, (int, float)) and zt > 0
        mb = limit.get("maxBoard")
        zhaban = limit.get("zhabanRate")
        stats.append({
            "date": date,
            "ztCount": zt if zt_ok else None,
            "maxBoard": mb if isinstance(mb, (int, float)) and mb > 0 else None,
            "amountYi": round(amount / 1e8, 1) if isinstance(amount, (int, float)) else None,
            "zhabanRate": round(zhaban, 1) if zt_ok and isinstance(zhaban, (int, float)) else None,
        })
    return stats


def compute_and_upsert_for_day(db: Any, *, dataset_id: str, trading_date: str,
                                  snapshot_type: str = "half_hour", origin: str = "collector",
                                  dry_run: bool = False) -> dict[str, Any]:
    """日级 EOD 计算+落库（hotlist_jev_sentiment）。异常向上抛，由链捕获为 warning。
    """
    _, token, account = _jev_config()
    slots = _slots_of_date(db, dataset_id, snapshot_type, trading_date)
    doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:EOD"
    base = {"_id": doc_id, "kind": "eod", "origin": origin, "datasetId": dataset_id,
            "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": "EOD",
            "asOf": f"{trading_date} EOD+08:00", "computedAt": int(time.time()),
            "questionsRaw": JEV_DAY_QUESTIONS, "anchoredSlotTime": slots[-1] if slots else None,
            "questionSetVersion": QUESTION_SET_VERSION,
            "errorCode": None, "errorDetail": None}
    if not slots:
        if not dry_run:
            db["hotlist_jev_sentiment"].replace_one(
                {"_id": doc_id}, {**base, "status": "no_data", "errorDetail": "no half_hour frames",
                                  "answers": None, "scores": None, "usage": None, "model": None,
                                  "evidenceRaw": None, "narrativeRaw": None, "responseRaw": None,
                                  "latencyMs": None}, upsert=True)
        return {"written": True, "status": "no_data"}

    yesterday_rows = _latest_yesterday_rows(db, dataset_id, snapshot_type, trading_date)
    yesterday_amounts = _yesterday_total_amounts_by_slot(db, dataset_id, snapshot_type, trading_date)
    evidences = []
    for slot in slots:
        evidence = _collect_evidence(db, dataset_id, snapshot_type, trading_date, slot,
                                     yesterday_rows, yesterday_amounts)
        if evidence is not None:
            evidences.append(evidence)
    if not evidences:
        if not dry_run:
            db["hotlist_jev_sentiment"].replace_one(
                {"_id": doc_id}, {**base, "status": "no_data", "errorDetail": "frames present but no rows",
                                  "answers": None, "scores": None, "usage": None, "model": None,
                                  "evidenceRaw": None, "narrativeRaw": None, "responseRaw": None,
                                  "latencyMs": None}, upsert=True)
        return {"written": True, "status": "no_data"}

    anchor = build_history_anchor(build_history_stats_calendar(db, dataset_id, trading_date))
    narrative = build_day_jev_state(
        trading_date=trading_date, evidences=evidences,
        yesterday_close_total_amount=yesterday_amounts.get("15:00"),
        history_anchor=anchor)
    if dry_run:
        return {"status": "dry", "narrative": narrative}

    if not token:
        db["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id}, {**base, "status": "degraded", "errorCode": "missing_token",
                              "errorDetail": "JEV_CF_TOKEN not configured",
                              "evidenceRaw": None, "narrativeRaw": narrative,
                              "answers": None, "scores": None, "usage": None, "model": None,
                              "responseRaw": None, "latencyMs": None}, upsert=True)
        return {"written": True, "status": "degraded", "errorCode": "missing_token"}

    envelope, latency_ms = call_jev(account, token, state=narrative, questions=JEV_DAY_QUESTIONS)
    parsed = parse_jev_response(envelope, latency_ms)
    doc = {**base, "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": None, "narrativeRaw": narrative,
           "responseRaw": envelope, "answers": parsed.get("answers"), "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "historyAnchorRange": extract_history_anchor_range(anchor)}
    db["hotlist_jev_sentiment"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return {"written": True, "status": doc["status"],
            "dayTemperature": (parsed.get("scores") or {}).get("day_temperature")}


def compute_and_upsert_for_slot(db: Any, *, dataset_id: str, trading_date: str, slot_time: str,
                                   snapshot_type: str = "half_hour", origin: str = "collector",
                                   dry_run: bool = False) -> dict[str, Any]:
    """v2 槽级计算+落库（hotlist_jev_sentiment_v2，2026-10-02 V1 退役后生产槽位唯一评判）。

    与 pilot（operations/jev_sentiment_pilot.compute_slot）同构：锚=日历口径近 20
    交易日（生产坐标系）。异常向上抛，由链捕获为 warning。
    """
    _, token, account = _jev_config()
    frame = _load_frame(db, dataset_id, snapshot_type, trading_date, slot_time)
    rows = _load_rows(db, dataset_id, str(frame.get("snapshotId") or "")) if frame else []
    doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:{slot_time}"
    if frame is None or not rows:
        if not dry_run:
            db["hotlist_jev_sentiment"].replace_one(
                {"_id": doc_id},
                {"_id": doc_id, "kind": "slot", "origin": origin, "datasetId": dataset_id,
                 "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time,
                 "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
                 "questionSetVersion": QUESTION_SET_VERSION,
                 "status": "no_data", "errorCode": None,
                 "errorDetail": f"frame={'present' if frame else 'missing'} rows={len(rows)}",
                 "questionsRaw": None, "evidenceRaw": None, "narrativeRaw": None,
                 "responseRaw": None, "answers": None, "scores": None, "usage": None,
                 "model": None, "latencyMs": None, "historyAnchorRange": None},
                upsert=True)
        return {"written": True, "status": "no_data"}

    yesterday_rows = _latest_yesterday_rows(db, dataset_id, snapshot_type, trading_date)
    yesterday_amounts = _yesterday_total_amounts_by_slot(db, dataset_id, snapshot_type, trading_date)
    present_slots = _slots_of_date(db, dataset_id, snapshot_type, trading_date)
    prior_slots = [slot for slot in present_slots if slot < slot_time]
    missing_slots = [slot for slot in _half_hour_slots() if slot < slot_time and slot not in prior_slots]
    priors = []
    for slot in prior_slots:
        evidence = _collect_evidence(db, dataset_id, snapshot_type, trading_date, slot,
                                     yesterday_rows, yesterday_amounts)
        if evidence is not None:
            priors.append(evidence)
    current_evidence = collect_slot_evidence(
        frame=frame, rows=rows, yesterday_rows=yesterday_rows,
        analysis_by_code=_load_analysis_by_code(db, dataset_id, str(frame.get("snapshotId") or "")),
        slot_time=slot_time,
        yesterday_same_slot_total_amount=yesterday_amounts.get(slot_time))
    anchor = build_history_anchor(build_history_stats_calendar(db, dataset_id, trading_date))
    narrative = build_slot_jev_state(
        trading_date=trading_date, slot_time=slot_time,
        current=current_evidence or {}, priors=priors, missing_slots=missing_slots,
        history_anchor=anchor)
    if dry_run:
        return {"status": "dry", "narrative": narrative}

    if not token:
        db["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id},
            {"_id": doc_id, "kind": "slot", "origin": origin, "datasetId": dataset_id,
             "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time,
             "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
             "questionSetVersion": QUESTION_SET_VERSION,
             "status": "degraded", "errorCode": "missing_token",
             "errorDetail": "JEV_CF_TOKEN not configured",
             "questionsRaw": JEV_SLOT_QUESTIONS, "evidenceRaw": current_evidence,
             "narrativeRaw": narrative, "responseRaw": None, "answers": None, "scores": None,
             "usage": None, "model": None, "latencyMs": None, "historyAnchorRange": None},
            upsert=True)
        return {"written": True, "status": "degraded", "errorCode": "missing_token"}

    envelope, latency_ms = call_jev(account, token, state=narrative, questions=JEV_SLOT_QUESTIONS)
    parsed = parse_jev_response(envelope, latency_ms)
    doc = {"_id": doc_id, "kind": "slot", "origin": origin, "datasetId": dataset_id,
           "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time,
           "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
           "questionSetVersion": QUESTION_SET_VERSION,
           "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": current_evidence, "narrativeRaw": narrative,
           "questionsRaw": JEV_SLOT_QUESTIONS, "responseRaw": envelope,
           "answers": parsed.get("answers"), "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "historyAnchorRange": extract_history_anchor_range(anchor)}
    db["hotlist_jev_sentiment"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return {"written": True, "status": doc["status"]}
