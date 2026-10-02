# -*- coding: utf-8 -*-
"""jev 情绪判定问题集 v2 生产计算服务（2026-10-02 立项：双表并存的 v2 表）。

与 v1（jev_sentiment_compute）并行的第二支表：温度=锚定近 20 交易日分位的市场热度计，
拥挤=离散归层（证据分级判据），档位=锚定分位判读。gate=JEV_SENTIMENT_V2_ENABLED（默认开，
可回退）；token 缺失降级落库不阻断采集链。

锚日历化（Q3 混季归因修复）：窗口按交易日历取严格早于当日的近 20 个交易日（每历日一条，
数据缺失日照实记 None），不再用"最近 20 个有数日"跨季凑数。
"""
from __future__ import annotations

import os
import time
from typing import Any

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS_V2,
    build_day_jev_state,
    build_history_anchor,
)
from backend.services.jev.jev_client import call_jev, parse_jev_response
from backend.services.jev.jev_sentiment_compute import (
    _collect_evidence,
    _half_hour_slots,
    _jev_config,
    _latest_yesterday_rows,
    _load_analysis_by_code,
    _load_frame,
    _load_rows,
    _slots_of_date,
    _yesterday_total_amounts_by_slot,
)

ANCHOR_WINDOW = 20


def v2_enabled() -> bool:
    """gate：JEV_SENTIMENT_V2_ENABLED 默认开（"0"/"false" 关），可回退。"""
    return os.environ.get("JEV_SENTIMENT_V2_ENABLED", "1").lower() not in ("0", "false")


def build_history_stats_calendar(db: Any, dataset_id: str, trading_date: str,
                                 window: int = ANCHOR_WINDOW) -> list[dict]:
    """近 window 个交易日（日历口径，严格 < 当日）收盘统计，每历日一条。

    数据源=v1 15:00 槽文档 evidenceRaw（与 pilot 同源）；当日文档缺失或指标缺失
    → 该历日相应字段 None（fail-visible：锚段会标注有效样本数，不跨季凑数）。
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
        # 伪 0 防线（v2.3 教训）：ztCount=0 视为缺失而非零值
        stats.append({
            "date": date,
            "ztCount": zt if isinstance(zt, (int, float)) and zt > 0 else None,
            "maxBoard": limit.get("maxBoard"),
            "amountYi": round(amount / 1e8, 1) if isinstance(amount, (int, float)) else None,
            "zhabanRate": round(limit["zhabanRate"], 1)
                          if isinstance(limit.get("zhabanRate"), (int, float)) else None,
        })
    return stats


def compute_and_upsert_for_day_v2(db: Any, *, dataset_id: str, trading_date: str,
                                  snapshot_type: str = "half_hour", origin: str = "collector_v2",
                                  dry_run: bool = False, force: bool = True) -> dict[str, Any]:
    """v2 日级 EOD 计算+落库（hotlist_jev_sentiment_v2）。异常向上抛，由链捕获为 warning。"""
    if not v2_enabled() and not force:
        return {"written": False, "skipped": True, "reason": "v2_disabled"}
    _, token, account = _jev_config()
    slots = _slots_of_date(db, dataset_id, snapshot_type, trading_date)
    doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:EOD"
    base = {"_id": doc_id, "kind": "eod", "origin": origin, "datasetId": dataset_id,
            "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": "EOD",
            "asOf": f"{trading_date} EOD+08:00", "computedAt": int(time.time()),
            "questionsRaw": JEV_DAY_QUESTIONS_V2, "anchoredSlotTime": slots[-1] if slots else None,
            "errorCode": None, "errorDetail": None}
    if not slots:
        if not dry_run:
            db["hotlist_jev_sentiment_v2"].replace_one(
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
            db["hotlist_jev_sentiment_v2"].replace_one(
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
        db["hotlist_jev_sentiment_v2"].replace_one(
            {"_id": doc_id}, {**base, "status": "degraded", "errorCode": "missing_token",
                              "errorDetail": "JEV_CF_TOKEN not configured",
                              "evidenceRaw": None, "narrativeRaw": narrative,
                              "answers": None, "scores": None, "usage": None, "model": None,
                              "responseRaw": None, "latencyMs": None}, upsert=True)
        return {"written": True, "status": "degraded", "errorCode": "missing_token"}

    envelope, latency_ms = call_jev(account, token, state=narrative, questions=JEV_DAY_QUESTIONS_V2)
    parsed = parse_jev_response(envelope, latency_ms)
    doc = {**base, "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": None, "narrativeRaw": narrative,
           "responseRaw": envelope, "answers": parsed.get("answers"), "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "historyAnchorRange": anchor.split("\n")[0][len("【近20日参照】（"):-1] or None}
    db["hotlist_jev_sentiment_v2"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return {"written": True, "status": doc["status"],
            "dayTemperature": (parsed.get("scores") or {}).get("day_temperature")}
