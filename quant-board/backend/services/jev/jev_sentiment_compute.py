# -*- coding: utf-8 -*-
"""jev 双问题编排服务（观察轨道 v3）。

原始快照证据 → 叙事字符串 → jev（/ai/run）→ hotlist_jev_sentiment 落库。
合同与 fail-visible 边界见 quant-board/docs/hotlist-jev/hotlist-jev-emotion-observe-design.md：
- 零规则输出：不读 hotlist_sentiment，叙事与文档均无规则五档/摘要/信号；
- 三态：ok / degraded（errorCode+errorDetail+responseRaw，不伪造档位）/ no_data（显式落库）；
- gate=JEV_SENTIMENT_ENABLED 默认关（关闭即跳过不写不告警）；手动调用不受 gate 限制由调用方保证。
"""
from __future__ import annotations

import os
import time
from typing import Any

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS,
    JEV_SLOT_QUESTIONS,
    build_day_jev_state,
    build_slot_jev_state,
    collect_slot_evidence,
)
from backend.services.jev.jev_client import call_jev, parse_jev_response

_JEV_TIMEOUT_SECONDS = 30
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
            {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date}):
        slot = str(f.get("slotTime") or "")
        if len(slot) == 5 and slot[2] == ":":
            slots.add(slot)
    return sorted(slots)


def _collect_evidence(db: Any, dataset_id: str, snapshot_type: str, trading_date: str,
                      slot_time: str, yesterday_rows: list) -> dict | None:
    frame = _load_frame(db, dataset_id, snapshot_type, trading_date, slot_time)
    if frame is None:
        return None
    snapshot_id = str(frame.get("snapshotId") or "")
    rows = _load_rows(db, dataset_id, snapshot_id)
    if not rows:
        return None
    return collect_slot_evidence(
        frame=frame, rows=rows, yesterday_rows=yesterday_rows,
        analysis_by_code=_load_analysis_by_code(db, dataset_id, snapshot_id), slot_time=slot_time)


def _latest_yesterday_rows(db: Any, dataset_id: str, snapshot_type: str, trading_date: str) -> list:
    """上一交易日最新 half_hour 帧行（昨日承接/新进淘汰的对比基线）。"""
    dates = sorted({
        str(f.get("tradingDate"))
        for f in db["snapshot_frames"].find({"datasetId": dataset_id, "type": snapshot_type})
        if f.get("tradingDate") and str(f.get("tradingDate")) < trading_date
    })
    if not dates:
        return []
    frame = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": dates[-1]},
        sort=[("timestamp", -1), ("snapshotId", -1)],
    )
    if not frame:
        return []
    return _load_rows(db, dataset_id, str(frame.get("snapshotId") or ""))


# ── 落库 ──


def _persist(db: Any, doc: dict) -> None:
    db["hotlist_jev_sentiment"].replace_one({"_id": doc["_id"]}, doc, upsert=True)


def _base_doc(*, dataset_id: str, snapshot_type: str, trading_date: str, slot_label: str,
              kind: str, origin: str, status: str, evidence: dict | None, narrative: str | None,
              questions: dict, anchored_slot: str | None = None) -> dict:
    doc: dict[str, Any] = {
        "_id": f"{dataset_id}:{snapshot_type}:{trading_date}:{slot_label}",
        "kind": kind,
        "origin": origin,
        "datasetId": dataset_id,
        "snapshotType": snapshot_type,
        "tradingDate": trading_date,
        "slotTime": "EOD" if kind == "eod" else slot_label,
        "asOf": f"{trading_date} {slot_label}+08:00",
        "computedAt": int(time.time()),
        "evidenceRaw": evidence,
        "narrativeRaw": narrative,
        "questionsRaw": questions,
        "status": status,
        "errorCode": None,
        "errorDetail": None,
        "answers": None,
        "scores": None,
        "usage": None,
        "latencyMs": None,
        "model": None,
        "responseRaw": None,
        "quality": {"degradedSources": list(((evidence or {}).get("quality") or {}).get("degradedSources") or [])},
    }
    if anchored_slot is not None:
        doc["anchoredSlotTime"] = anchored_slot
    return doc


def _no_data_doc(base: dict, detail: str) -> dict:
    return {**base, "status": "no_data", "errorDetail": detail}


# ── 槽位评判（Q1 当前帧 + Q2 当日序列，一次调用四问）──


def compute_and_upsert_for_slot(
    db: Any,
    *,
    dataset_id: str,
    trading_date: str,
    slot_time: str,
    snapshot_type: str = "half_hour",
    origin: str = "collector",
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """force=True 时不检查 gate（手动 API 显式意图）；token 缺失仍 degraded。"""
    enabled, token, account = _jev_config()
    if not enabled and not force:
        return {"written": False, "skipped": True, "reason": "jev_disabled"}
    frame = _load_frame(db, dataset_id, snapshot_type, trading_date, slot_time)
    rows = _load_rows(db, dataset_id, str(frame.get("snapshotId") or "")) if frame else []
    base = _base_doc(dataset_id=dataset_id, snapshot_type=snapshot_type, trading_date=trading_date,
                     slot_label=slot_time, kind="slot", origin=origin, status="no_data",
                     evidence=None, narrative=None, questions=JEV_SLOT_QUESTIONS)
    if frame is None or not rows:
        doc = _no_data_doc(base, f"frame={'present' if frame else 'missing'} rows={len(rows)}")
        if not dry_run:
            _persist(db, doc)
        return {"written": True, "status": "no_data", "reason": "frame_or_rows_missing"}

    yesterday_rows = _latest_yesterday_rows(db, dataset_id, snapshot_type, trading_date)
    present_slots = _slots_of_date(db, dataset_id, snapshot_type, trading_date)
    prior_slots = [slot for slot in present_slots if slot < slot_time]
    missing_slots = [slot for slot in _half_hour_slots() if slot < slot_time and slot not in prior_slots]
    priors = []
    for slot in prior_slots:
        evidence = _collect_evidence(db, dataset_id, snapshot_type, trading_date, slot, yesterday_rows)
        if evidence is not None:
            priors.append(evidence)
    current_evidence = _collect_evidence(db, dataset_id, snapshot_type, trading_date, slot_time, yesterday_rows)
    narrative = build_slot_jev_state(
        trading_date=trading_date, slot_time=slot_time,
        current=current_evidence or {}, priors=priors, missing_slots=missing_slots)

    if not token:
        doc = {**base, "status": "degraded", "errorCode": "missing_token",
               "errorDetail": "JEV_CF_TOKEN not configured",
               "evidenceRaw": current_evidence, "narrativeRaw": narrative}
        if not dry_run:
            _persist(db, doc)
        return {"written": True, "status": "degraded", "errorCode": "missing_token"}

    envelope, latency_ms = call_jev(account, token, state=narrative, questions=JEV_SLOT_QUESTIONS,
                                    timeout=_JEV_TIMEOUT_SECONDS)
    parsed = parse_jev_response(envelope, latency_ms)
    doc = {**base,
           "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": current_evidence,
           "narrativeRaw": narrative,
           "responseRaw": envelope,
           "answers": parsed.get("answers"),
           "scores": parsed.get("scores"),
           "usage": parsed.get("usage"),
           "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"),
           "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail")}
    if not dry_run:
        _persist(db, doc)
    result: dict[str, Any] = {"written": True, "status": doc["status"]}
    if doc["errorCode"]:
        result["errorCode"] = doc["errorCode"]
    return result


# ── 日级评判（盘后固定当日总体，一次调用四问）──


def compute_and_upsert_for_day(
    db: Any,
    *,
    dataset_id: str,
    trading_date: str,
    snapshot_type: str = "half_hour",
    origin: str = "collector",
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    enabled, token, account = _jev_config()
    if not enabled and not force:
        return {"written": False, "skipped": True, "reason": "jev_disabled"}
    slots = [slot for slot in _slots_of_date(db, dataset_id, snapshot_type, trading_date)]
    base = _base_doc(dataset_id=dataset_id, snapshot_type=snapshot_type, trading_date=trading_date,
                     slot_label="eod", kind="eod", origin=origin, status="no_data",
                     evidence=None, narrative=None, questions=JEV_DAY_QUESTIONS,
                     anchored_slot=slots[-1] if slots else None)
    if not slots:
        doc = _no_data_doc(base, "no half_hour frames for date")
        if not dry_run:
            _persist(db, doc)
        return {"written": True, "status": "no_data", "reason": "no_frames"}

    yesterday_rows = _latest_yesterday_rows(db, dataset_id, snapshot_type, trading_date)
    evidences = []
    for slot in slots:
        evidence = _collect_evidence(db, dataset_id, snapshot_type, trading_date, slot, yesterday_rows)
        if evidence is not None:
            evidences.append(evidence)
    if not evidences:
        doc = _no_data_doc(base, "frames present but no rows")
        if not dry_run:
            _persist(db, doc)
        return {"written": True, "status": "no_data", "reason": "no_rows"}

    narrative = build_day_jev_state(trading_date=trading_date, evidences=evidences)
    if not token:
        doc = {**base, "status": "degraded", "errorCode": "missing_token",
               "errorDetail": "JEV_CF_TOKEN not configured",
               "narrativeRaw": narrative}
        if not dry_run:
            _persist(db, doc)
        return {"written": True, "status": "degraded", "errorCode": "missing_token"}

    envelope, latency_ms = call_jev(account, token, state=narrative, questions=JEV_DAY_QUESTIONS,
                                    timeout=_JEV_TIMEOUT_SECONDS)
    parsed = parse_jev_response(envelope, latency_ms)
    doc = {**base,
           "status": "ok" if parsed["ok"] else "degraded",
           "narrativeRaw": narrative,
           "responseRaw": envelope,
           "answers": parsed.get("answers"),
           "scores": parsed.get("scores"),
           "usage": parsed.get("usage"),
           "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"),
           "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail")}
    if not dry_run:
        _persist(db, doc)
    result: dict[str, Any] = {"written": True, "status": doc["status"]}
    if doc["errorCode"]:
        result["errorCode"] = doc["errorCode"]
    return result


# ── 采集链分派入口 ──


def run_jev_post_persist(db: Any, *, dataset_id: str, snapshot_type: str,
                         trading_date: str, slot_time: str) -> dict[str, Any]:
    """collector 后处理链分派：half_hour → 槽位评判；daily → 日级评判；其余跳过。

    异常向上抛出，由调用方（链）捕获为 warning——本函数绝不阻断采集。
    """
    if snapshot_type == "half_hour":
        return compute_and_upsert_for_slot(
            db, dataset_id=dataset_id, trading_date=trading_date, slot_time=slot_time, origin="collector")
    if snapshot_type == "daily":
        return compute_and_upsert_for_day(db, dataset_id=dataset_id, trading_date=trading_date, origin="collector")
    return {"written": False, "skipped": True, "reason": "snapshot_type_not_applicable"}
