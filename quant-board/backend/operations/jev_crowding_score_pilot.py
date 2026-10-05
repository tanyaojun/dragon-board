# -*- coding: utf-8 -*-
"""拥挤度连续分 v3 双轨 pilot runner（jev-crowding-score-reevaluation.md §四，预登记已冻结）。

用户裁决（2026-10-03）：v2 拥挤离散化需重评——score 判死根因可能是语料不足（判死实验在
无锚、无封板质量弹药环境完成），且解析层从未保留 score 直方图。本 pilot 双问并测定夺：

  双问并测：crowding（离散归层，现行题目原样，自 jev_state import）+ crowding_score
            （0-100 连续分，温度 P3 同款锚定法：以【近20日参照】分位刻度为坐标系）。
  证据/叙事链：与 v2 pilot（jev_sentiment_pilot.py）逐段同源复制（build_history_stats
            直接 import 复用；runner 主体复制不参数化原文件——jev_state.py /
            jev_sentiment_compute.py 有并行在途改动，pilot 一次性实验代码自含更安全）。
  落库：hotlist_jev_crowding_pilot 新集合（v2 生产表 hotlist_jev_sentiment 零改动），
        origin=crowding_score_pilot_v3，questionSetVersion=v3.0-pilot。
        answers.crowding_score 原样含全档位 probabilities 直方图（parse_jev_response
        answers 透传）——S1 方差门直接在直方图上判，解析层零丢失。

门判据（冻结，勿改）：S1 方差 std≥12 且中位区(45-70)占比≤50%；S2 分离 p<0.05；
S3 序数自洽 Spearman≥0.6；S4 归层逃生率≤10% 不回退。判定细则见重评提案文档。

用法（Git Bash）：
  export JEV_CF_TOKEN=<token>
  ./.venv/Scripts/python.exe -u -m backend.operations.jev_crowding_score_pilot \
      --dates 2026-09-07,2026-09-18,2026-09-30 --dry-run
  ... --dates 2026-09-07 --smoke 2        # 冒烟：仅前 2 槽，亲读叙事与双答
  ... --dates 2026-09-07,2026-09-18,2026-09-30 --yes   # 正式开火
"""
from __future__ import annotations

import argparse
import os
import time

from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS,
    JEV_SLOT_QUESTIONS,
    SCORE_ANCHORS_10,
    build_day_jev_state,
    build_history_anchor,
    build_slot_jev_state,
    extract_history_anchor_range,
)
from backend.operations.jev_sentiment_pilot import build_history_stats
from backend.services.jev.jev_client import DEFAULT_ACCOUNT_ID, call_jev, parse_jev_response
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
COLLECTION = "hotlist_jev_crowding_pilot"
ORIGIN = "crowding_score_pilot_v3"
QUESTION_SET_VERSION = "v3.0-pilot"

# v3 新增题目（温度 P3 同款锚定法；crowding 离散归层题目原样复用不重定义）
_CROWD_SCORE_INSTR = (
    "当前高位拥挤程度连续分（0=完全不拥挤，100=极度拥挤）。"
    "以【近20日参照】段的分位刻度为坐标系：涨停数/连板高度相对近20日位置越靠高位、"
    "炸板率相对参照越高、封板质量越弱化，拥挤分越高；"
    "当前证据相对近20日的位置决定落点，不凭绝对语感"
)
_DAY_CROWD_SCORE_INSTR = "今日全天" + _CROWD_SCORE_INSTR.replace("当前高位", "收盘时高位").replace("当前证据", "今日证据")


def _score_question(instructions: str) -> dict:
    return {"type": "score", "instructions": instructions, "criteria": list(SCORE_ANCHORS_10)}


JEV_SLOT_QUESTIONS_V3 = {**JEV_SLOT_QUESTIONS, "crowding_score": _score_question(_CROWD_SCORE_INSTR)}
JEV_DAY_QUESTIONS_V3 = {**JEV_DAY_QUESTIONS, "day_crowding_score": _score_question(_DAY_CROWD_SCORE_INSTR)}


def _db():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    return get_runtime_mongodb_database()


def _save_doc(db, doc: dict) -> None:
    db[COLLECTION].replace_one({"_id": doc["_id"]}, doc, upsert=True)


def compute_slot(db, dataset_id: str, trading_date: str, slot_time: str,
                 history_anchor: str, token: str, account: str, dry_run: bool) -> dict:
    """v3 槽位评判：叙事链同 v2，题目=v3 双问并测，落 pilot 集合。"""
    snapshot_type = "half_hour"
    frame = _load_frame(db, dataset_id, snapshot_type, trading_date, slot_time)
    rows = _load_rows(db, dataset_id, str(frame.get("snapshotId") or "")) if frame else []
    doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:{slot_time}"
    if frame is None or not rows:
        if not dry_run:
            _save_doc(db, {"_id": doc_id, "kind": "slot", "origin": ORIGIN,
                           "questionSetVersion": QUESTION_SET_VERSION,
                           "datasetId": dataset_id, "snapshotType": snapshot_type,
                           "tradingDate": trading_date, "slotTime": slot_time,
                           "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
                           "status": "no_data",
                           "errorDetail": f"frame={'present' if frame else 'missing'} rows={len(rows)}"})
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
    current_evidence = collect_current(db, dataset_id, snapshot_type, trading_date, slot_time,
                                       frame, rows, yesterday_rows, yesterday_amounts)
    narrative = build_slot_jev_state(
        trading_date=trading_date, slot_time=slot_time,
        current=current_evidence or {}, priors=priors, missing_slots=missing_slots,
        history_anchor=history_anchor)
    if dry_run:
        return {"status": "dry", "narrative": narrative}
    envelope, latency_ms = call_jev(account, token, state=narrative, questions=JEV_SLOT_QUESTIONS_V3)
    parsed = parse_jev_response(envelope, latency_ms)
    doc = {"_id": doc_id, "kind": "slot", "origin": ORIGIN,
           "questionSetVersion": QUESTION_SET_VERSION,
           "datasetId": dataset_id, "snapshotType": snapshot_type,
           "tradingDate": trading_date, "slotTime": slot_time,
           "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
           "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": current_evidence, "narrativeRaw": narrative,
           "questionsRaw": JEV_SLOT_QUESTIONS_V3, "responseRaw": envelope,
           "answers": parsed.get("answers"), "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "historyAnchorRange": extract_history_anchor_range(history_anchor)}
    _save_doc(db, doc)
    return {"status": doc["status"]}


def collect_current(db, dataset_id: str, snapshot_type: str, trading_date: str, slot_time: str,
                    frame, rows, yesterday_rows, yesterday_amounts):
    from backend.analysis.hotlist.jev_state import collect_slot_evidence

    return collect_slot_evidence(
        frame=frame, rows=rows, yesterday_rows=yesterday_rows,
        analysis_by_code=_load_analysis_by_code(db, dataset_id, str(frame.get("snapshotId") or "")),
        slot_time=slot_time,
        yesterday_same_slot_total_amount=yesterday_amounts.get(slot_time))


def compute_day(db, dataset_id: str, trading_date: str, history_anchor: str,
                token: str, account: str, dry_run: bool) -> dict:
    """v3 日级评判：同构换装。"""
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
    envelope, latency_ms = call_jev(account, token, state=narrative, questions=JEV_DAY_QUESTIONS_V3)
    parsed = parse_jev_response(envelope, latency_ms)
    doc = {"_id": doc_id, "kind": "eod", "origin": ORIGIN,
           "questionSetVersion": QUESTION_SET_VERSION,
           "datasetId": dataset_id, "snapshotType": snapshot_type,
           "tradingDate": trading_date, "slotTime": "EOD",
           "asOf": f"{trading_date} EOD+08:00", "computedAt": int(time.time()),
           "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": None, "narrativeRaw": narrative,
           "questionsRaw": JEV_DAY_QUESTIONS_V3, "responseRaw": envelope,
           "answers": parsed.get("answers"), "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "anchoredSlotTime": slots[-1],
           "historyAnchorRange": extract_history_anchor_range(history_anchor)}
    _save_doc(db, doc)
    return {"status": doc["status"]}


def _planned_calls(db, dataset_id: str, dates: list[str], smoke: int | None) -> int:
    if smoke is not None:
        # 多日期冒烟：每日各前 smoke 槽，预算按实际调用数报（禁止首日 early-return 低报）
        return sum(min(smoke, len(_slots_of_date(db, dataset_id, "half_hour", date))) for date in dates)
    return sum(len(_slots_of_date(db, dataset_id, "half_hour", date)) + 1 for date in dates)  # + EOD


def run(dates: list[str], dry_run: bool, smoke: int | None, yes: bool,
        token: str, account: str, dataset_id: str) -> int:
    db = _db()
    # 预算守卫（执行纪律：开火前核对窗口范围，V2.1 超支 19 万 tokens 教训）
    calls = _planned_calls(db, dataset_id, dates, smoke)
    # 单价系数按 2026-10-03 基线实测校准（≈4.0k tokens/调用，双题 v3 叙事比 v2 长）
    est_tokens = calls * 4000
    print(f"窗口 {dates} smoke={smoke}：将执行 {calls} 次模型调用，预估 ≈{est_tokens} tokens"
          f"（落 {COLLECTION}，生产表零改动）")
    if not dry_run and not (yes or smoke is not None):
        print("预览模式：加 --yes 正式开火；--dry-run 只看叙事；--smoke N 先冒烟亲读")
        return 0
    counts = {"ok": 0, "degraded": 0, "no_data": 0}
    usage_totals = {"input": 0, "output": 0}
    for date in dates:
        anchor = build_history_anchor(build_history_stats(db, dataset_id, date))
        if dry_run:
            print(f"===== {date} history anchor =====\n{anchor[:800]}")
            sample = compute_slot(db, dataset_id, date, "09:30", anchor, token, account, dry_run=True)
            print(f"----- {date} 09:30 叙事样例（前 800）-----\n{(sample.get('narrative') or '')[:800]}")
            continue
        slots = sorted(_slots_of_date(db, dataset_id, "half_hour", date))
        if smoke is not None:
            slots = slots[:smoke]
        for slot in slots:
            r = compute_slot(db, dataset_id, date, slot, anchor, token, account, dry_run)
            counts[r.get("status", "unknown")] = counts.get(r.get("status", "unknown"), 0) + 1
        if smoke is None:
            r = compute_day(db, dataset_id, date, anchor, token, account, dry_run)
            counts[r.get("status", "unknown")] = counts.get(r.get("status", "unknown"), 0) + 1
        print(f"[{date}] done (cum {counts})")
    if not dry_run:
        for d in db[COLLECTION].find({"origin": ORIGIN}, {"usage": 1}):
            u = d.get("usage") or {}
            usage_totals["input"] += int(u.get("input_tokens") or 0)
            usage_totals["output"] += int(u.get("output_tokens") or 0)
        print(f"FINAL: {counts} usage={usage_totals}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="拥挤度连续分 v3 双轨 pilot（预登记冻结）")
    ap.add_argument("--dates", required=True,
                    help="显式逗号分隔交易日列表（禁止隐式区间，防超支）")
    ap.add_argument("--dry-run", action="store_true", help="只看叙事与锚，零调用")
    ap.add_argument("--smoke", type=int, default=None, help="每日仅跑前 N 槽（冒烟亲读用，≥1）")
    ap.add_argument("--yes", action="store_true", help="确认预算后正式开火")
    ap.add_argument("--dataset", default=DATASET_DEFAULT)
    args = ap.parse_args()
    tok = ""
    acc = ""
    if args.smoke is not None and args.smoke < 1:
        ap.error("--smoke 必须 ≥1（负数/0 会绕过 --yes 预算确认执行近全日槽位）")
    if args.smoke is not None or args.yes:
        tok = os.environ.get("JEV_CF_TOKEN") or ""
        assert tok, "需要 JEV_CF_TOKEN 环境变量"
        acc = os.environ.get("JEV_CF_ACCOUNT", DEFAULT_ACCOUNT_ID)
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    raise SystemExit(run(dates, args.dry_run, args.smoke, args.yes, tok, acc, args.dataset))
