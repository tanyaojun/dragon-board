# -*- coding: utf-8 -*-
"""jev 阶段1 回放 runner：历史锚定帧重建 state → jev → hotlist_jev_sentiment。

用法（Git Bash，令牌经环境变量传入、不入仓库）：
  export JEV_CF_TOKEN=<token>
  ./.venv/Scripts/python.exe -m backend.operations.jev_replay \
      --start 2026-08-11 --end 2026-09-24 --dry-run      # 先 2 天验证
  ./.venv/Scripts/python.exe -m backend.operations.jev_replay \
      --start 2026-08-11 --end 2026-09-24                # 全量 ~300 次

幂等：upsert _id={datasetId}:half_hour:{tradingDate}:{slotKey}，origin=replay。
fail-visible：帧/行/情绪桶任一缺失 → no_data 文档如实落库；调用失败 → degraded 带原始错误。
注意：实际库名 dragon_board_quant（settings.py 默认 DragonBoardData 与生产不符）。
"""
from __future__ import annotations

import argparse
import json
import os
import time

from pymongo import MongoClient

from backend.analysis.hotlist.jev_state import build_replay_state
from backend.services.jev.jev_client import SCORE_ANCHORS, call_jev, parse_jev_response

QUESTIONS = {
    # 档位口径对齐 backend/analysis/hotlist/sentiment.py 级联与 src/types/emotion.ts EMOTION_STAGE_RULES：
    # 判定核心是边际方向（启动=从弱基线修复；退潮=从强势转弱），不是绝对热度水平。
    "stage": {"type": "choice", "instructions": "当前A股短线情绪处于哪一档？判定核心是边际方向：正在从弱修复，还是正在从强转弱。",
              "criteria": {"ice": "冰点：亏钱效应占优，上涨比例低、热榜池收缩、机会稀少，尚无修复迹象",
                           "start": "启动：从冰点/弱势基线开始修复——绝对水平仍不高，但上涨比例改善、跌停与风险减少、新点火线索增多、热榜池扩张（边际改善是关键）",
                           "ferment": "发酵：主线扩散形成合力，点火与主升状态增多，昨日强票留榜较好，上涨承接优于下跌承接",
                           "climax": "高潮：涨停与高涨幅高度集中，高位拥挤增加，成交额与换手显著放大，风险尚未失控",
                           "retreat": "退潮：从强势转弱——炸板率较近期抬升、晋级率走弱、昨日强票承接失败、高位股批量走弱（边际恶化是关键，高绝对热度不等于高潮）"}},
    "heating_30m": {"type": "noul", "instructions": "未来30分钟市场短线情绪升温（赚钱效应边际改善）的概率"},
    "retreat_eod": {"type": "noul", "instructions": "收盘前出现明显退潮加剧（炸板潮/高位批量开板）的概率"},
    "temperature": {"type": "score", "instructions": "短线情绪温度（0=彻底冰点，100=极度亢奋）",
                    "criteria": SCORE_ANCHORS},
    "crowding": {"type": "score", "instructions": "高位拥挤度（0=无人问津，100=极度拥挤危险）",
                 "criteria": SCORE_ANCHORS},
}
SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"]


def _load_slot(db, date: str, slot: str):
    frame = db["snapshot_frames"].find_one({"type": "half_hour", "tradingDate": date, "slotTime": slot})
    sent = db["hotlist_sentiment"].find_one({"snapshotType": "half_hour", "tradingDate": date, "slotTime": slot})
    rows = list(db["snapshot_stock_rows"].find({"type": "half_hour", "tradingDate": date, "slotTime": slot}))
    return frame, sent, rows


def _analysis_by_code(db, rows: list) -> dict:
    snap_ids = list({r.get("snapshotId") for r in rows if r.get("snapshotId")})
    if not snap_ids:
        return {}
    return {a["code"]: ((a.get("analysis") or {}).get("displayStatus") or {}).get("stage")
            for a in db["snapshot_analysis"].find({"snapshotId": {"$in": snap_ids}},
                                                  {"code": 1, "analysis.displayStatus.stage": 1})
            if a.get("code")}


def run(start: str, end: str, dry_run: bool, token: str, acc: str, limit_days: int | None):
    db = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)["dragon_board_quant"]
    jev_col = db["hotlist_jev_sentiment"]
    dates = sorted({d["tradingDate"] for d in db["hotlist_sentiment"].find(
        {"snapshotType": "half_hour"}, {"tradingDate": 1})
        if d.get("tradingDate") and start <= d["tradingDate"] <= end})
    if dry_run:
        dates = dates[-2:]
    if limit_days:
        dates = dates[-limit_days:]
    n_ok = n_deg = n_skip = 0
    cost_in = cost_out = 0
    for di, date in enumerate(dates):
        prev_counts = prev_codes = None
        for slot in SLOTS:
            frame, sent, rows = _load_slot(db, date, slot)
            _id = f"dragonboard_live:half_hour:{date}:{slot}"
            if not frame or not rows or not sent:
                jev_col.replace_one({"_id": _id},
                                    {"_id": _id, "origin": "replay", "tradingDate": date, "slotKey": slot,
                                     "status": "no_data",
                                     "detail": {"frame": bool(frame), "rows": len(rows), "sentiment": bool(sent)}},
                                    upsert=True)
                n_skip += 1
                continue
            state = build_replay_state(frame, rows, _analysis_by_code(db, rows),
                                       sent, prev_counts, prev_codes)
            if dry_run and slot == SLOTS[0]:
                print(f"[dry] {date} {slot} state_bytes={len(json.dumps(state, ensure_ascii=False))} "
                      f"degraded={len(state['quality']['degraded'])}")
            env, ms = call_jev(acc, token, state, QUESTIONS)
            parsed = parse_jev_response(env, ms)
            usage = parsed.get("usage") or {}
            cost_in += usage.get("input_tokens") or 0
            cost_out += usage.get("output_tokens") or 0
            doc = {"_id": _id, "origin": "replay", "datasetId": "dragonboard_live",
                   "snapshotType": "half_hour", "tradingDate": date, "slotKey": slot,
                   "asOf": state["asOf"], "status": "ok" if parsed["ok"] else "degraded",
                   "ruleStage": sent.get("stage"), "ruleConfidence": sent.get("confidence"),
                   "stateRaw": state, "questionsRaw": QUESTIONS,
                   "responseRaw": None if parsed["ok"] else env,
                   "answers": parsed.get("answers"), "scores": parsed.get("scores"),
                   "model": parsed.get("model"), "usage": usage, "latencyMs": ms,
                   "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
                   "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
            if not dry_run:
                jev_col.replace_one({"_id": _id}, doc, upsert=True)
            n_ok += bool(parsed["ok"])
            n_deg += not parsed["ok"]
            layers = (sent.get("metrics") or {}).get("layers") or {}
            prev_counts = (layers.get("top50") or {}).get("stageCounts")
            prev_codes = {r.get("code") for r in rows if r.get("code")}
            time.sleep(0.3)
        print(f"[{di + 1}/{len(dates)}] {date} done (ok={n_ok} deg={n_deg} skip={n_skip})")
    print("FINAL:", {"ok": n_ok, "degraded": n_deg, "skipped": n_skip,
                     "tokens_in": cost_in, "tokens_out": cost_out})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit-days", type=int)
    args = ap.parse_args()
    token = os.environ.get("JEV_CF_TOKEN") or ""
    acc = os.environ.get("JEV_CF_ACCOUNT", "921cf15176f84c90ea49865334af32c6")
    assert token, "需要 JEV_CF_TOKEN 环境变量"
    run(args.start, args.end, args.dry_run, token, acc, args.limit_days)
