# -*- coding: utf-8 -*-
"""jev 情绪判定问题集 v2 生产计算服务（2026-10-02 立项：双表并存的 v2 表）。

jev 情绪判定生产计算服务（2026-10-02 V1 退役后唯一情绪链）：温度=锚定近 20 交易日分位的市场热度计，
拥挤=离散归层（证据分级判据），档位=锚定分位判读。token 缺失降级落库不阻断采集链。2026-10-02 单一事实源裁决：gate 环境变量删除（V1 已灭，无双轨可回退）。

锚日历化（Q3 混季归因修复）：窗口按交易日历取严格早于当日的近 20 个交易日（每历日一条，
数据缺失日照实记 None），不再用"最近 20 个有数日"跨季凑数。
"""
from __future__ import annotations

import logging
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
from backend.services.jev.jev_client import (DEFAULT_ACCOUNT_ID, call_jev, call_jev_typesafe,
                                             parse_jev_response)

_DEFAULT_ACCOUNT = DEFAULT_ACCOUNT_ID


def _dispatch_jev(state, questions: dict) -> tuple[dict, int]:
    """传输选择：JEV_TYPESAFE_KEY 存在 → 官方直连（可经代理）；否则 CF 网关。
    两条通道返回同形状 envelope，parse_jev_response 下游零改动。"""
    ts_key = os.environ.get("JEV_TYPESAFE_KEY", "").strip()
    if ts_key:
        proxy = os.environ.get("JEV_TYPESAFE_PROXY", "").strip() or None
        return call_jev_typesafe(ts_key, state=state, questions=questions, proxy=proxy)
    _enabled, token, account = _jev_config()
    return call_jev(account, token, state=state, questions=questions)


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


def load_market_daily_amount_map(db: Any) -> dict[str, float]:
    """market_daily_amount 参考集合 → {tradingDate: 两市合计额}（TDX 综指口径，backfill 工具维护）。

    15:00 槽 evidenceRaw.totalAmount 的重算保护源（2026-10-06 根治：此前回填值被
    replace_one 全量重建冲掉，v2.5 九月重跑实测冲掉 20 文档）。集合缺失/为空 → 空映射，
    计算链行为回退为历史原样（amount=None，fail-visible 不伪造）。
    """
    rows = db["market_daily_amount"].find({}, {"_id": 1, "totalAmount": 1})
    return {str(row["_id"]): float(row["totalAmount"]) for row in rows
            if isinstance(row.get("totalAmount"), (int, float)) and not isinstance(row["totalAmount"], bool)}


def _collect_evidence(db: Any, dataset_id: str, snapshot_type: str, trading_date: str,
                      slot_time: str, yesterday_rows: list,
                      yesterday_amounts: dict[str, float] | None = None,
                      daily_total_amount_fallback: float | None = None) -> dict | None:
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
        yesterday_same_slot_total_amount=(yesterday_amounts or {}).get(slot_time),
        daily_total_amount_fallback=daily_total_amount_fallback)


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


# ── C2 锚供给逃生率告警（jev-temp-crowding-confidence-deepening.md 提案C2，2026-10-02 重评版）──
# 单日槽位逃生率（crowding=insufficient_evidence 的 ok 槽占比）>25% 连续 2 日 → 排查锚供给
# （v2.2/v2.3 教训：逃生率飙升几乎总是锚数据源问题而非题目问题：status=ok 限定、伪 0、
# limitSummary 损坏三类历史事故）。告警只上报、不得阻断采集/写入/读取链路（数据链路硬门禁禁令）；
# 基线只以现行代（QUESTION_SET_VERSION）文档计，跨代口径不可比。
ANCHOR_ALERT_ESCAPE_RATE = 0.25


def evaluate_anchor_escape_alert(db: Any, *, dataset_id: str, trading_date: str) -> dict:
    """当日+上一交易日槽位逃生率与连续告警判定（纯读，不写库不阻断）。"""
    def _day_rate(date: str) -> float | None:
        n_ok = n_escape = 0
        for doc in db["hotlist_jev_sentiment"].find(
                {"kind": "slot", "status": "ok", "datasetId": dataset_id,
                 "snapshotType": "half_hour",
                 "tradingDate": date, "questionSetVersion": QUESTION_SET_VERSION},
                {"answers.crowding.choice": 1}):
            n_ok += 1
            if ((doc.get("answers") or {}).get("crowding") or {}).get("choice") == "insufficient_evidence":
                n_escape += 1
        return round(n_escape / n_ok, 3) if n_ok else None

    today_rate = _day_rate(trading_date)
    prev_docs = db["hotlist_jev_sentiment"].find(
        {"kind": "slot", "datasetId": dataset_id, "snapshotType": "half_hour",
         "tradingDate": {"$lt": trading_date}},
        {"tradingDate": 1})
    prev_date = max((d.get("tradingDate") for d in prev_docs if d.get("tradingDate")),
                    default=None)
    prev_rate = _day_rate(prev_date) if prev_date else None
    alert = (today_rate is not None and today_rate > ANCHOR_ALERT_ESCAPE_RATE
             and prev_rate is not None and prev_rate > ANCHOR_ALERT_ESCAPE_RATE)
    return {"alert": alert, "tradingDate": trading_date, "todayRate": today_rate,
            "prevDate": prev_date, "prevRate": prev_rate,
            "threshold": ANCHOR_ALERT_ESCAPE_RATE}


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
    market_amounts = load_market_daily_amount_map(db)
    evidences = []
    for slot in slots:
        evidence = _collect_evidence(db, dataset_id, snapshot_type, trading_date, slot,
                                     yesterday_rows, yesterday_amounts,
                                     daily_total_amount_fallback=market_amounts.get(trading_date))
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

    if not token and not os.environ.get("JEV_TYPESAFE_KEY", "").strip():
        # review M8：无 token 重跑的降级 replace 不得抹掉既往 ok 链路写入的锚告警字段
        prior = db["hotlist_jev_sentiment"].find_one(
            {"_id": doc_id}, {"anchorEscapeRate": 1, "anchorEscapeAlert": 1}) or {}
        carry = {k: prior[k] for k in ("anchorEscapeRate", "anchorEscapeAlert")
                 if prior.get(k) is not None}
        db["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id}, {**base, "status": "degraded", "errorCode": "missing_token",
                              "errorDetail": "JEV_CF_TOKEN / JEV_TYPESAFE_KEY not configured",
                              "evidenceRaw": None, "narrativeRaw": narrative,
                              "answers": None, "scores": None, "usage": None, "model": None,
                              "responseRaw": None, "latencyMs": None, **carry}, upsert=True)
        return {"written": True, "status": "degraded", "errorCode": "missing_token"}

    envelope, latency_ms = _dispatch_jev(narrative, JEV_DAY_QUESTIONS)
    # 缺题=partial_answers（degraded）：缺哪题结构化留档，幂等重跑可补（2026-10-05 批次A C2）
    parsed = parse_jev_response(envelope, latency_ms, expected_keys=set(JEV_DAY_QUESTIONS))
    # C2 锚供给告警（只上报不阻断）：评估自身异常也不得影响 EOD 主链路
    try:
        escape_alert = evaluate_anchor_escape_alert(db, dataset_id=dataset_id,
                                                    trading_date=trading_date)
    except Exception as exc:  # noqa: BLE001 — 告警机制故障不得阻断链路
        logging.warning("anchor escape alert eval failed for %s: %s", trading_date, exc)
        escape_alert = None
    else:
        if escape_alert.get("alert"):
            logging.warning(
                "anchor escape alert %s: today=%.2f prev(%s)=%.2f threshold=%.2f —— 排查锚供给",
                trading_date, escape_alert["todayRate"], escape_alert["prevDate"],
                escape_alert["prevRate"], escape_alert["threshold"])
    doc = {**base, "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": None, "narrativeRaw": narrative,
           "responseRaw": envelope, "answers": parsed.get("answers"), "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "historyAnchorRange": extract_history_anchor_range(anchor),
           "anchorEscapeRate": escape_alert.get("todayRate") if escape_alert else None,
           "anchorEscapeAlert": escape_alert if escape_alert and escape_alert.get("alert") else None}
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
    market_amounts = load_market_daily_amount_map(db)
    present_slots = _slots_of_date(db, dataset_id, snapshot_type, trading_date)
    prior_slots = [slot for slot in present_slots if slot < slot_time]
    missing_slots = [slot for slot in _half_hour_slots() if slot < slot_time and slot not in prior_slots]
    priors = []
    for slot in prior_slots:
        evidence = _collect_evidence(db, dataset_id, snapshot_type, trading_date, slot,
                                     yesterday_rows, yesterday_amounts,
                                     daily_total_amount_fallback=market_amounts.get(trading_date))
        if evidence is not None:
            priors.append(evidence)
    current_evidence = collect_slot_evidence(
        frame=frame, rows=rows, yesterday_rows=yesterday_rows,
        analysis_by_code=_load_analysis_by_code(db, dataset_id, str(frame.get("snapshotId") or "")),
        slot_time=slot_time,
        yesterday_same_slot_total_amount=yesterday_amounts.get(slot_time),
        daily_total_amount_fallback=market_amounts.get(trading_date))
    anchor = build_history_anchor(build_history_stats_calendar(db, dataset_id, trading_date))
    narrative = build_slot_jev_state(
        trading_date=trading_date, slot_time=slot_time,
        current=current_evidence or {}, priors=priors, missing_slots=missing_slots,
        history_anchor=anchor)
    if dry_run:
        return {"status": "dry", "narrative": narrative}

    if not token and not os.environ.get("JEV_TYPESAFE_KEY", "").strip():
        db["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id},
            {"_id": doc_id, "kind": "slot", "origin": origin, "datasetId": dataset_id,
             "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time,
             "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
             "questionSetVersion": QUESTION_SET_VERSION,
             "status": "degraded", "errorCode": "missing_token",
             "errorDetail": "JEV_CF_TOKEN / JEV_TYPESAFE_KEY not configured",
             "questionsRaw": JEV_SLOT_QUESTIONS, "evidenceRaw": current_evidence,
             "narrativeRaw": narrative, "responseRaw": None, "answers": None, "scores": None,
             "usage": None, "model": None, "latencyMs": None, "historyAnchorRange": None},
            upsert=True)
        return {"written": True, "status": "degraded", "errorCode": "missing_token"}

    envelope, latency_ms = _dispatch_jev(narrative, JEV_SLOT_QUESTIONS)
    # 缺题=partial_answers（degraded）：缺哪题结构化留档，幂等重跑可补（2026-10-05 批次A C2）
    parsed = parse_jev_response(envelope, latency_ms, expected_keys=set(JEV_SLOT_QUESTIONS))
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
    # errorCode 必须随返回透出（2026-10-09 实障）：采集 warning 与 /evaluate 补评响应
    # 都消费本返回，漏带时只显示 `hotlist_jev_degraded: None`，排障被迫查库
    return {"written": True, "status": doc["status"], "errorCode": parsed.get("errorCode")}
