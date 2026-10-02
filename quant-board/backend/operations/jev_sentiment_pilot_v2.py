# -*- coding: utf-8 -*-
"""jev 情绪判定问题集 v2 pilot runner（梳理提案 P1-P4 试点，§6 预登记判据先冻结）。

与 v1 链完全并行：v1（hotlist_jev_sentiment）封存不动，v2 落 hotlist_jev_sentiment_v2。
改动三件：①叙事插【近20日参照】段（数据源=v1 槽文档 evidenceRaw 15:00 收盘统计，as-of 仅取 < 当日）；
②问题集换 JEV_SLOT_QUESTIONS_V2 / JEV_DAY_QUESTIONS_V2（crowding 离散归层+温度锚定+五档绑证据）；
③origin=sentiment_v2_pilot。

用法（Git Bash）：
  export JEV_CF_TOKEN=<token>
  ./.venv/Scripts/python.exe -u -m backend.operations.jev_sentiment_pilot_v2 \
      --start 2026-09-07 --end 2026-09-30 --dry-run
"""
from __future__ import annotations

import argparse
import time

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS_V2,
    JEV_SLOT_QUESTIONS_V2,
    build_day_jev_state,
    build_history_anchor,
    build_slot_jev_state,
    collect_slot_evidence,
)
from backend.services.jev.jev_client import call_jev, parse_jev_response
from backend.services.jev.jev_sentiment_compute import (
    _collect_evidence,
    _half_hour_slots,
    _latest_yesterday_rows,
    _load_analysis_by_code,
    _load_frame,
    _load_rows,
    _slots_of_date,
    _yesterday_total_amounts_by_slot,
)

DATASET_DEFAULT = "dragonboard_live"
ANCHOR_SLOTS = 20  # 近 20 交易日
PILOT_DATES = ["2026-09-07", "2026-09-18", "2026-09-30"]  # 打标链同款三天


def _db():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    return get_runtime_mongodb_database()


def build_history_stats(db, dataset_id: str, trading_date: str) -> list[dict]:
    """近 N 交易日收盘统计（as-of 严格 < 当日）：v1 槽文档 15:00 evidenceRaw。

    v2.2 修复（§8）：按 evidenceRaw.limit.ztCount 存在性取数，不限定 status=ok——
    degraded 文档（如缺 token 时段）的 evidenceRaw 市场证据同样有效；锚只需要证据数字。
    """
    docs = db["hotlist_jev_sentiment"].find(
        {"datasetId": dataset_id, "snapshotType": "half_hour", "kind": "slot",
         "slotTime": "15:00", "tradingDate": {"$lt": trading_date},
         "evidenceRaw.limit.ztCount": {"$ne": None}},
        {"tradingDate": 1, "evidenceRaw": 1}).sort("tradingDate", -1).limit(ANCHOR_SLOTS)
    stats = []
    for d in docs:
        ev = d.get("evidenceRaw") or {}
        limit = ev.get("limit") or {}
        amount = (ev.get("totalAmount") or {}).get("amount")
        stats.append({
            "date": str(d.get("tradingDate")),
            "ztCount": limit.get("ztCount"),
            "maxBoard": limit.get("maxBoard"),
            "amountYi": round(amount / 1e8, 1) if isinstance(amount, (int, float)) else None,
            # v1 evidenceRaw 的 zhabanRate 已是百分数（30.30=30.3%），与 fengbanRate 同制
            "zhabanRate": round(limit["zhabanRate"], 1)
                          if isinstance(limit.get("zhabanRate"), (int, float)) else None,
        })
    return list(reversed(stats))


def compute_slot_v2(db, dataset_id: str, trading_date: str, slot_time: str,
                    history_anchor: str, token: str, account: str, dry_run: bool) -> dict:
    """v2 槽位评判：叙事+问题集换 v2，落 hotlist_jev_sentiment_v2。"""
    snapshot_type = "half_hour"
    frame = _load_frame(db, dataset_id, snapshot_type, trading_date, slot_time)
    rows = _load_rows(db, dataset_id, str(frame.get("snapshotId") or "")) if frame else []
    doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:{slot_time}"
    if frame is None or not rows:
        if not dry_run:
            db["hotlist_jev_sentiment_v2"].replace_one(
                {"_id": doc_id},
                {"_id": doc_id, "kind": "slot", "origin": "sentiment_v2_pilot", "datasetId": dataset_id,
                 "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time,
                 "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
                 "status": "no_data", "errorDetail": f"frame={'present' if frame else 'missing'} rows={len(rows)}"},
                upsert=True)
        return {"status": "no_data"}

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
    narrative = build_slot_jev_state(
        trading_date=trading_date, slot_time=slot_time,
        current=current_evidence or {}, priors=priors, missing_slots=missing_slots,
        history_anchor=history_anchor)
    if dry_run:
        return {"status": "dry", "narrative": narrative}
    envelope, latency_ms = call_jev(account, token, state=narrative, questions=JEV_SLOT_QUESTIONS_V2)
    parsed = parse_jev_response(envelope, latency_ms)
    doc = {"_id": doc_id, "kind": "slot", "origin": "sentiment_v2_pilot", "datasetId": dataset_id,
           "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time,
           "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
           "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": current_evidence, "narrativeRaw": narrative,
           "questionsRaw": JEV_SLOT_QUESTIONS_V2, "responseRaw": envelope,
           "answers": parsed.get("answers"), "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "historyAnchorRange": history_anchor.split("\n")[0][len("【近20日参照】（"):-1] or None}
    db["hotlist_jev_sentiment_v2"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return {"status": doc["status"]}


def compute_day_v2(db, dataset_id: str, trading_date: str, history_anchor: str,
                   token: str, account: str, dry_run: bool) -> dict:
    """v2 日级评判：同构换装。"""
    snapshot_type = "half_hour"
    slots = _slots_of_date(db, dataset_id, snapshot_type, trading_date)
    doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:EOD"
    if not slots:
        return {"status": "no_data"}
    yesterday_rows = _latest_yesterday_rows(db, dataset_id, snapshot_type, trading_date)
    yesterday_amounts = _yesterday_total_amounts_by_slot(db, dataset_id, snapshot_type, trading_date)
    evidences = []
    for slot in slots:
        evidence = _collect_evidence(db, dataset_id, snapshot_type, trading_date, slot,
                                     yesterday_rows, yesterday_amounts)
        if evidence is not None:
            evidences.append(evidence)
    if not evidences:
        return {"status": "no_data"}
    yesterday_close_amount = yesterday_amounts.get("15:00")
    narrative = build_day_jev_state(trading_date=trading_date, evidences=evidences,
                                    yesterday_close_total_amount=yesterday_close_amount,
                                    history_anchor=history_anchor)
    if dry_run:
        return {"status": "dry", "narrative": narrative}
    envelope, latency_ms = call_jev(account, token, state=narrative, questions=JEV_DAY_QUESTIONS_V2)
    parsed = parse_jev_response(envelope, latency_ms)
    doc = {"_id": doc_id, "kind": "eod", "origin": "sentiment_v2_pilot", "datasetId": dataset_id,
           "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": "EOD",
           "asOf": f"{trading_date} EOD+08:00", "computedAt": int(time.time()),
           "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": None, "narrativeRaw": narrative,
           "questionsRaw": JEV_DAY_QUESTIONS_V2, "responseRaw": envelope,
           "answers": parsed.get("answers"), "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "anchoredSlotTime": slots[-1],
           "historyAnchorRange": history_anchor.split("\n")[0][len("【近20日参照】（"):-1] or None}
    db["hotlist_jev_sentiment_v2"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return {"status": doc["status"]}


def run(start: str, end: str, dry_run: bool, token: str, account: str, dataset_id: str) -> int:
    db = _db()
    dates = sorted({str(r["tradingDate"]) for r in db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": {"$gte": start, "$lte": end}},
        {"tradingDate": 1}) if r.get("tradingDate")})
    if not dates:
        print(f"窗口 {start}~{end} 无 half_hour 帧，退出")
        return 1
    counts = {"ok": 0, "degraded": 0, "no_data": 0}
    for di, date in enumerate(dates, 1):
        anchor = build_history_anchor(build_history_stats(db, dataset_id, date))
        if dry_run:
            print(f"===== {date} history anchor =====\n{anchor}")
            sample = compute_slot_v2(db, dataset_id, date, "09:30", anchor, token, account, dry_run=True)
            print(f"----- {date} 09:30 叙事样例（前600）-----\n{(sample.get('narrative') or '')[:600]}")
            continue
        for slot in sorted(_slots_of_date(db, dataset_id, "half_hour", date)):
            r = compute_slot_v2(db, dataset_id, date, slot, anchor, token, account, dry_run)
            counts[r.get("status", "unknown")] = counts.get(r.get("status", "unknown"), 0) + 1
        r = compute_day_v2(db, dataset_id, date, anchor, token, account, dry_run)
        counts[r.get("status", "unknown")] = counts.get(r.get("status", "unknown"), 0) + 1
        print(f"[{di}/{len(dates)}] {date} done (cum {counts})")
    print("FINAL:", counts)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="jev 情绪判定问题集 v2 pilot")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dataset", default=DATASET_DEFAULT)
    args = ap.parse_args()
    tok = ""
    acc = ""
    if not args.dry_run:
        import os

        tok = os.environ.get("JEV_CF_TOKEN") or ""
        assert tok, "需要 JEV_CF_TOKEN 环境变量"
        acc = os.environ.get("JEV_CF_ACCOUNT", "921cf15176f84c90ea49865334af32c6")
    raise SystemExit(run(args.start, args.end, args.dry_run, tok, acc, args.dataset))
