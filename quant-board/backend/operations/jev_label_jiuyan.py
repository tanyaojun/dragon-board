# -*- coding: utf-8 -*-
"""jev 涨停打标 v2 runner：韭研异动全量名单 → 驱动三轴（driver_type/catalyst_depth/catalyst_freshness）。

设计依据 docs/hotlist-jev/jev-driver-label-v2-design.md：
  population = 韭研当日 final 全量涨停名单（含未进热榜股票，如实标注）；
  判定语料 = 心照链命中子集（报告脚本负责 join，本脚本只打标）；
  落 hotlist_jev_driver_labels_v2（2026-10-02 单一事实源裁决：旧链 jev_label_driver.py 与 hotlist_jev_driver_labels 已删除）。

用法（Git Bash）：
  export JEV_CF_TOKEN=<token>
  ./.venv/Scripts/python.exe -u -m backend.operations.jev_label_jiuyan \
      --start 2026-09-05 --end 2026-09-30 --dry-run
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor

from backend.analysis.hotlist.jev_state import build_jiuyan_label_narrative
from backend.services.jev.jev_client import call_jev, parse_jev_response

# 题目 v3（pilot3，设计文档 §9）：新业务按动词七级序列切两桶（scaling/early）+ T3 证据硬规则 +
# driver 口径对齐 + freshness 锚日期。供货节奏判据锚定：研发<送样<验证<认证<小批量<量产<规模出货。
QUESTIONS = {
    "driver_type": {"type": "choice",
                    "instructions": "该股今日涨停的最主要驱动类型是哪一类？只依据所给信息打标，不预测后市。",
                    "criteria": {
                        "policy": "政策驱动：政策/规划/监管变化直接利好（国家级或地方产业政策、行业规则变化）",
                        "order_earnings": "订单业绩：订单中标、合同签署、业绩预告/财报超预期等经营实质利好",
                        "product_event": "产品事件：产品发布/技术突破/项目落地等公司产品或技术层面事件",
                        "ma_restructure": "重组并购：收购、重组、控制权变更、分拆上市等资本运作",
                        "industry_cycle": "行业周期：行业景气/价格周期驱动（涨价、供需反转、周期回暖），非单一个股事件",
                        "capital_flow": "资金接力：无明确新催化或催化本身无新意，主要由资金接力/情绪带动/板块联动上涨",
                        "concept_stretch": "蹭概念：催化与公司实际业务的实质关联弱或明显蹭热点；注意：催化所指业务若已是公司主业或已有实质承接，不应判此类（那是其他驱动类型）"}},
    "catalyst_depth": {"type": "choice",
                       "instructions": "以解析中最主要的涨停催化为准，该催化所指的业务/事件，在解析所述的公司业务版图中落在哪一层？"
                                       "依据解析中给出的收入占比、订单、项目、参股关系等证据判断，不预测后市。"
                                       "注意：供货节奏动词（研发→送样→验证→认证→小批量→批量量产→规模出货）与证据可信度规则"
                                       "（公告/定期报告最高，研报/权威媒体次之，网传/传闻/未证实仅作线索且不得支撑放量层）"
                                       "仅用于区分新业务的两层；催化所指业务若已是公司主要收入来源，无论叙事如何描述其节奏，一律判核心主业承接。"
                                       "并购重组类催化：标的公司业务与公司现有主业同业或紧密上下游按第一层判，跨行业转型按第二/三层判，"
                                       "纯控制权变更/壳资源运作且无明确业务注入按第五层判；"
                                       "解析给出收入占比/金额证据时，以大额业务为业务版图重心。",
                       "criteria": {
                           "core_main_business": "核心主业承接：催化所指业务是公司当前主要收入来源（解析明确的主业或占比最高的业务），且催化事件直接作用于该业务（政策/景气作用于它、订单落在它、产品属于它）；供货节奏描述不改变本层判定",
                           "new_business_scaling": "新业务放量承接：催化所指新业务已有越过认证线的实质证据——小批量供货、批量交付、中标、形成实质收入（周交付、订单加单、产能爬坡均属此层）；且支撑证据须为公告/定期报告/权威研报级，网传传闻级证据不得支撑本层",
                           "new_business_early": "新业务早期承接：催化所指新业务处于研发、送样、验证、认证阶段，或仅有合作意向/框架协议/网传订单；前提是催化所指业务与公司存在真实业务关系（研发/送样/认证的是公司自身或其并购/参股实体的业务）——仅靠名称/地域/概念联想的归概念组装层",
                           "equity_or_affiliate": "股权关联传导：催化主要经由参股公司、控股股东或兄弟公司、参股基金等间接传导，公司自身报表业务不直接承接",
                           "concept_assembly": "概念组装弱关联：催化与公司业务的实质联系弱——主要靠名称/地域/行业大概念联想、经营范围变更、极小规模贸易型业务等组装而成，解析所述主业与催化所指业务明显不同",
                           "insufficient_evidence": "信息不足：解析未提供足以判断催化落点的业务信息，不强行归类"}},
    "catalyst_freshness": {"type": "choice",
                           "instructions": "该股本次涨停对应的催化事件处于什么阶段？只依据所给信息打标，不预测后市。"
                                           "以解析中标注的具体日期为准判断：催化事件首次出现距今≤2 个交易日判今日新催化；"
                                           "日期不可考时才依据信息模糊程度判信息不足。",
                           "criteria": {
                               "fresh_catalyst": "今日新催化：解析日期证据显示事件首次出现距今≤2 个交易日（今日公告、今日发布、昨日盘后新消息）",
                               "continuing": "老催化续命：解析日期证据显示事件首次出现距今>2 个交易日（近 3-30 天已知事件/题材的延续发酵）",
                               "none": "无明确催化：无具体事件，主要由资金接力/情绪/板块联动带动",
                               "unclear": "信息不足：解析未提供可判断催化新旧的事件日期，不强行归类"}},
}


def _db():
    """运行时库入口：经 repository_factory 吃 settings（URI/库名），pytest 下受护栏约束。"""
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    return get_runtime_mongodb_database()


def day_population(db, date: str) -> list[dict]:
    """韭研当日 final 全量名单：[{stock, board}]；无 final 文档返回空（fail-visible 由调用方披露）。"""
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"})
    if not doc:
        return []
    out = []
    for field in doc.get("fields") or []:
        board = field.get("name") or ""
        for stock in field.get("stocks") or []:
            out.append({"stock": stock, "board": board})
    return out


def hotlist_ranks(db, date: str, plain_codes: list[str]) -> dict[str, int]:
    """(date, code) → 当日热榜最优（min）rank；未命中不进返回值。"""
    ranks: dict[str, int] = {}
    for r in db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": date, "code": {"$in": plain_codes}, "rank": {"$exists": True}},
            {"code": 1, "rank": 1}):
        rank, code = r.get("rank"), r.get("code")
        if isinstance(rank, int) and rank > 0 and (code not in ranks or rank < ranks[code]):
            ranks[code] = rank
    return ranks


def _label_one(db, labels_col, acc, token, date, code, stock, board, rank):
    narrative = build_jiuyan_label_narrative(stock, board, rank, trading_date=date)
    env, ms = call_jev(acc, token, narrative, QUESTIONS)
    parsed = parse_jev_response(env, ms)
    answers = parsed.get("answers") or {}
    doc = {"_id": f"{date}:{code}", "origin": "driver_label_jiuyan", "tradingDate": date,
           "code": code, "name": stock.get("name"),
           "jiuyanContext": {"board": board, "day": stock.get("day"), "num": stock.get("num"),
                             "time": stock.get("time"), "inHotlist": rank is not None, "rank": rank},
           "status": "ok" if parsed["ok"] else "degraded",
           "narrative": narrative, "questionsRaw": QUESTIONS,
           "label": answers.get("driver_type", {}).get("choice"),
           "driverProbabilities": answers.get("driver_type", {}).get("probabilities"),
           "catalystDepth": answers.get("catalyst_depth", {}).get("choice"),
           "catalystDepthProbabilities": answers.get("catalyst_depth", {}).get("probabilities"),
           "freshness": answers.get("catalyst_freshness", {}).get("choice"),
           "freshnessProbabilities": answers.get("catalyst_freshness", {}).get("probabilities"),
           "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
           "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
           "responseRaw": None if parsed["ok"] else env,
           "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
    labels_col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return bool(parsed["ok"])


def run(start: str, end: str, dry_run: bool, token: str, acc: str, workers: int = 2,
        skip_existing: bool = False):
    db = _db()
    labels_col = db["hotlist_jev_driver_labels_v2"]
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end}},
        {"tradingDate": 1}) if d.get("tradingDate")})
    if not dates:
        print(f"窗口 {start}~{end} 无 jiuyan_action final 文档，退出（fail-visible：不伪造空跑成功）")
        return
    if dry_run:
        dates = dates[-2:]
    n_ok = n_deg = n_skipped = 0
    for di, date in enumerate(dates):
        pop = day_population(db, date)
        if not pop:
            print(f"[{di + 1}/{len(dates)}] {date} 无韭研 final 文档，跳过（披露）")
            continue
        # 条件剥前缀（与叙事构建器同规则：仅 sh/sz/bj 前缀才剥，无前缀 code 不截残）；
        # 同股跨板块重复时保留后者（既有覆盖语义不变），但如实披露不再静默
        items: dict[str, dict] = {}
        dupes: list[str] = []
        for entry in pop:
            raw = str(entry["stock"].get("code") or "")
            code = raw[2:] if len(raw) > 2 and raw[:2] in ("sh", "sz", "bj") else raw
            if code in items:
                dupes.append(f"{code}({items[code]['board']}→{entry['board']})")
            items[code] = entry
        if dupes:
            print(f"[{di + 1}/{len(dates)}] {date} 跨板块重复 code {len(dupes)} 只（后者覆盖，披露）："
                  f"{'; '.join(dupes)}")
        codes = list(items.keys())
        if skip_existing:
            done = {d["code"] for d in labels_col.find({"tradingDate": date, "status": "ok"}, {"code": 1})}
            if done:
                before = len(codes)
                codes = [c for c in codes if c not in done]
                n_skipped += before - len(codes)
        if not codes:
            print(f"[{di + 1}/{len(dates)}] {date} 全部已打，跳过")
            continue
        ranks = hotlist_ranks(db, date, list(items.keys()))
        if dry_run:
            sample = items[codes[0]]
            print(f"[dry] {date} {sample['stock'].get('name')} rank={ranks.get(codes[0])}\n"
                  f"      narrative={build_jiuyan_label_narrative(sample['stock'], sample['board'], ranks.get(codes[0]), trading_date=date)[:200]}")
            print(f"[{di + 1}/{len(dates)}] {date} population={len(codes)} hotlistHit={len(ranks)}")
            continue

        def work(code):
            entry = items[code]
            for attempt in range(2):  # 网络抖动单次重试，幂等无害
                result = _label_one(db, labels_col, acc, token, date, code, entry["stock"],
                                    entry["board"], ranks.get(code))
                if result:
                    return True
                time.sleep(1.0)
            return False

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(work, codes))
        n_ok += sum(results)
        n_deg += len(results) - sum(results)
        print(f"[{di + 1}/{len(dates)}] {date} done n={len(codes)} (cum ok={n_ok} deg={n_deg} skipped={n_skipped})")
    print("FINAL:", {"ok": n_ok, "degraded": n_deg, "skipped": n_skipped})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--skip-existing", action="store_true",
                    help="断点续跑：跳过当日已有 ok 标签的股票（degraded 重试）")
    args = ap.parse_args()
    tok = os.environ.get("JEV_CF_TOKEN") or ""
    assert tok, "需要 JEV_CF_TOKEN 环境变量"
    run(args.start, args.end, args.dry_run, tok,
        os.environ.get("JEV_CF_ACCOUNT", "921cf15176f84c90ea49865334af32c6"),
        args.workers, args.skip_existing)
