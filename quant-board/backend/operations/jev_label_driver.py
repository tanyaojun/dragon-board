# -*- coding: utf-8 -*-
"""jev 阶段3 驱动打标 runner：每日带 reason 的涨停股 → 驱动类型 Choice + 催化-主业匹配 Noul。

用法（Git Bash）：
  export JEV_CF_TOKEN=<token>
  ./.venv/Scripts/python.exe -u -m backend.operations.jev_label_driver \
      --start 2026-08-11 --end 2026-09-24 --dry-run

数据源（全存量）：snapshot_stock_rows.reason（THS limit_up_reason 映射）+
theme_stock_mappings（业务底座，按 stockCode join）。
落库 hotlist_jev_driver_labels，_id={date}:{code}，幂等 upsert。
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor

from backend.analysis.hotlist.jev_state import build_driver_label_narrative
from backend.services.jev.jev_client import call_jev, parse_jev_response


def _db():
    """运行时库入口：经 repository_factory 吃 settings（URI/库名），pytest 下受护栏约束。
    禁止硬编码 MongoClient 直连生产库（2026-09-29 隔离裁决）。"""
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    return get_runtime_mongodb_database()

QUESTIONS = {
    "driver_type": {"type": "choice",
                    "instructions": "该股今日涨停的最主要驱动类型是哪一类？只依据所给信息打标，不预测后市。",
                    "criteria": {
                        "policy": "政策驱动：政策/规划/监管变化直接利好（国家级或地方产业政策、行业规则变化）",
                        "order_earnings": "订单业绩：订单中标、合同签署、业绩预告/财报超预期等经营实质利好",
                        "product_event": "产品事件：产品发布/技术突破/项目落地等公司产品或技术层面事件",
                        "ma_restructure": "重组并购：收购、重组、控制权变更、分拆上市等资本运作",
                        "industry_cycle": "行业周期：行业景气/价格周期驱动（涨价、供需反转、周期回暖），非单一个股事件",
                        "capital_flow": "资金接力：无明确新催化，主要由资金接力/情绪带动/板块联动上涨",
                        "concept_stretch": "蹭概念：催化与公司实际业务的实质关联弱，或明显蹭热点"}},
    "business_match": {"type": "noul",
                       "instructions": "本次涨停催化与公司既有主业的实质关联度（0=纯蹭概念无业务支撑，1=催化直接落在公司既有业务/产品上）"},
}


def _day_population(db, date: str):
    """当日带 reason 的 (code → 当日最晚槽行)。"""
    best = {}
    for r in db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": date, "reason": {"$exists": True, "$ne": None, "$ne": ""}},
            {"code": 1, "name": 1, "rank": 1, "mainTheme": 1, "reason": 1, "slotTime": 1, "snapshotId": 1}):
        slot = r.get("slotTime") or ""
        cur = best.get(r["code"])
        if cur is None or slot > cur.get("slotTime") or "":
            best[r["code"]] = r
    return best


def _label_one(db, labels_col, acc, token, date, code, row, mappings, had_yesterday):
    narrative = build_driver_label_narrative(row["reason"], row, mappings)
    env, ms = call_jev(acc, token, narrative, QUESTIONS)
    parsed = parse_jev_response(env, ms)
    answers = parsed.get("answers") or {}
    doc = {"_id": f"{date}:{code}", "origin": "driver_label", "tradingDate": date, "code": code,
           "name": row.get("name"), "rank": row.get("rank"), "mainTheme": row.get("mainTheme"),
           "reason": row["reason"], "hadReasonYesterday": had_yesterday,
           "status": "ok" if parsed["ok"] else "degraded",
           "narrative": narrative, "questionsRaw": QUESTIONS,
           "label": answers.get("driver_type", {}).get("choice"),
           "driverProbabilities": answers.get("driver_type", {}).get("probabilities"),
           "matchNoul": answers.get("business_match", {}).get("noul"),
           "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
           "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
           "responseRaw": None if parsed["ok"] else env,
           "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
    labels_col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return bool(parsed["ok"])


def run(start: str, end: str, dry_run: bool, token: str, acc: str, workers: int = 2):
    db = _db()
    labels_col = db["hotlist_jev_driver_labels"]
    mappings_col = db["theme_stock_mappings"]
    dates = sorted({d["tradingDate"] for d in db["snapshot_stock_rows"].find(
        {"type": "half_hour", "tradingDate": {"$gte": start, "$lte": end}, "reason": {"$exists": True, "$ne": None, "$ne": ""}},
        {"tradingDate": 1}) if d.get("tradingDate")})
    if dry_run:
        dates = dates[-2:]
    n_ok = n_deg = 0
    for di, date in enumerate(dates):
        pop = _day_population(db, date)
        prev_codes = {r["code"] for r in db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": dates[dates.index(date) - 1] if dates.index(date) else "",
             "reason": {"$exists": True, "$ne": None, "$ne": ""}}, {"code": 1})} if dates.index(date) else set()
        codes = list(pop.keys())
        # 字段适配：theme_stock_mappings(stockCode/themeId/stockReason/stockTags) →
        # 构建器规范形 {themeName, tags, reason}；题材名从 theme_daily_factors join
        theme_names = {d["themeId"]: d.get("themeName") or d["themeId"]
                       for d in db["theme_daily_factors"].find({}, {"themeId": 1, "themeName": 1}) if d.get("themeId")}
        all_maps: dict[str, list] = {}
        for m in mappings_col.find({"stockCode": {"$in": codes}}):
            all_maps.setdefault(m["stockCode"], []).append({
                "themeName": theme_names.get(m.get("themeId"), m.get("themeId")),
                "tags": m.get("stockTags") or [],
                "reason": m.get("stockReason") or "",
            })
        if dry_run:
            sample = codes[0] if codes else None
            if sample:
                print(f"[dry] {date} {pop[sample]['name']} "
                      f"narrative={build_driver_label_narrative(pop[sample]['reason'], pop[sample], all_maps.get(sample, []))[:160]}")
            print(f"[{di + 1}/{len(dates)}] {date} population={len(codes)}")
            continue

        def work(code):
            for attempt in range(2):  # 网络抖动单次重试，幂等无害
                result = _label_one(db, labels_col, acc, token, date, code, pop[code],
                                    all_maps.get(code, []), code in prev_codes)
                if result:
                    return True
                time.sleep(1.0)
            return False

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(work, codes))
        n_ok += sum(results)
        n_deg += len(results) - sum(results)
        print(f"[{di + 1}/{len(dates)}] {date} done n={len(codes)} (cum ok={n_ok} deg={n_deg})")
    print("FINAL:", {"ok": n_ok, "degraded": n_deg})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    token = os.environ.get("JEV_CF_TOKEN") or ""
    acc = os.environ.get("JEV_CF_ACCOUNT", "921cf15176f84c90ea49865334af32c6")
    assert token, "需要 JEV_CF_TOKEN 环境变量"
    run(args.start, args.end, args.dry_run, token, acc, args.workers)
