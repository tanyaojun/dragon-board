# -*- coding: utf-8 -*-
"""jev 阶段2 打标 runner：每日 15:00 收盘槽 top20 股的五维叙事 → jev Choice 形态标签。

用法（Git Bash）：
  export JEV_CF_TOKEN=<token>
  ./.venv/Scripts/python.exe -u -m backend.operations.jev_label_stocks \
      --start 2026-08-11 --end 2026-09-24 --dry-run

落库 hotlist_jev_stock_labels，_id={snapshotId}:{code}，含 ruleTier（信号层）供分层增量检验。
不预测：只让 jev 对当前五维配置打形态标签；验证由 jev_label_report 用次日 pctChange 分组完成。
"""
from __future__ import annotations

import argparse
import json
import os
import time

from pymongo import MongoClient

from backend.analysis.hotlist.jev_state import build_stock_config_narrative
from backend.services.jev.jev_client import call_jev, parse_jev_response

QUESTIONS = {
    "config": {"type": "choice",
               "instructions": "该股当前五维配置最接近哪一类操作形态？只依据所给状态打标，不预测后市。",
               "criteria": {
                   "breakout": "突破主升：共振强（60分以上）且趋势向上，MACD金叉/多头排列，周期处于点火或扩散，题材动量为正",
                   "pullback": "强势回踩：中期趋势仍向上，短线回调缩量（MACD未深度死叉），周期扩散未被破坏——回踩低吸形态",
                   "bottom_reversal": "超跌修复：前期深跌或长期弱势，近期共振拐头/跳变新鲜度高，周期点火或反转初期",
                   "chase_risk": "高位过热：周期拥挤或高潮，热度榜前列但共振钝化或出现反转征兆，追高风险大",
                   "weak_drift": "弱势漂移：各维中性偏弱，趋势向下无拐点，周期冷却，缺乏事件驱动",
                   "mixed_noise": "信号矛盾：多维方向冲突（如共振强但周期冷却、题材负而个股强），难以归入上述形态"}},
}
STOCK_LIMIT = 20


def run(start: str, end: str, dry_run: bool, token: str, acc: str):
    db = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)["dragon_board_quant"]
    labels = db["hotlist_jev_stock_labels"]
    dates = sorted({d["tradingDate"] for d in db["snapshot_frames"].find(
        {"type": "half_hour", "tradingDate": {"$gte": start, "$lte": end}}, {"tradingDate": 1})
        if d.get("tradingDate")})
    if dry_run:
        dates = dates[-2:]
    n_ok = n_deg = n_skip = 0
    for di, date in enumerate(dates):
        rows = list(db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": date, "slotTime": "15:00"}).sort("rank", 1).limit(STOCK_LIMIT))
        if not rows:
            print(f"[{di + 1}/{len(dates)}] {date} 15:00 无行，跳过")
            n_skip += 1
            continue
        snap_ids = list({r.get("snapshotId") for r in rows if r.get("snapshotId")})
        ana_by_code = {a["code"]: a.get("analysis") or {}
                       for a in db["snapshot_analysis"].find({"snapshotId": {"$in": snap_ids}}) if a.get("code")}
        for r in rows:
            analysis = ana_by_code.get(r.get("code"))
            _id = f"{r.get('snapshotId')}:{r.get('code')}"
            if not analysis:
                labels.replace_one({"_id": _id},
                                   {"_id": _id, "origin": "label", "tradingDate": date, "code": r.get("code"),
                                    "status": "no_data", "detail": "analysis 缺失"}, upsert=True)
                n_skip += 1
                continue
            narrative = build_stock_config_narrative(analysis, r)
            rule_tier = ((analysis.get("observation") or {}).get("rankTrend") or {}).get("signalTier")
            if dry_run:
                print(f"[dry] {date} {r.get('name')} narrative_bytes={len(narrative)} tier={rule_tier}")
                continue
            env, ms = call_jev(acc, token, narrative, QUESTIONS)
            parsed = parse_jev_response(env, ms)
            labels.replace_one({"_id": _id}, {
                "_id": _id, "origin": "label", "tradingDate": date, "code": r.get("code"),
                "name": r.get("name"), "rank": r.get("rank"), "snapshotId": r.get("snapshotId"),
                "status": "ok" if parsed["ok"] else "degraded",
                "narrative": narrative, "questionsRaw": QUESTIONS,
                "label": parsed["answers"]["config"]["choice"] if parsed["ok"] else None,
                "probabilities": parsed["answers"]["config"].get("probabilities") if parsed["ok"] else None,
                "confidence": parsed["answers"]["config"].get("confidence") if parsed["ok"] else None,
                "ruleTier": rule_tier, "model": parsed.get("model"),
                "usage": parsed.get("usage"), "latencyMs": ms,
                "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
                "responseRaw": None if parsed["ok"] else env,
                "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}, upsert=True)
            n_ok += bool(parsed["ok"])
            n_deg += not parsed["ok"]
            time.sleep(0.3)
        print(f"[{di + 1}/{len(dates)}] {date} done (ok={n_ok} deg={n_deg} skip={n_skip})")
    print("FINAL:", {"ok": n_ok, "degraded": n_deg, "skipped": n_skip})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    token = os.environ.get("JEV_CF_TOKEN") or ""
    acc = os.environ.get("JEV_CF_ACCOUNT", "921cf15176f84c90ea49865334af32c6")
    assert token, "需要 JEV_CF_TOKEN 环境变量"
    run(args.start, args.end, args.dry_run, token, acc)
