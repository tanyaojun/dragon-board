# -*- coding: utf-8 -*-
"""jev 涨停打标 runner（题目集 docs/hotlist-jev/jev-driver-label-v3-questionset.md，2026-10-03 收敛定版）。

生产集合 hotlist_jev_driver_labels（v2 集合已归档 data/backups 后退役，pilot 集合 rename 平移而来）。
架构（C 定版）：个股四题 + Q5 相位题日级独立调用（run_phase_band_day）。历代替换：v1/v2 runner 见 git 历史。差异：
  1) 题目五道（v3.1 三轴原文同题锚 + Q4 买盘逻辑 + Q5 相位强弱分线）；
  2) 弹药三新块全结构化直供（THS 身位块 / 板块地位块 / 分位盘面事实行）——不含规则情绪分（Q5 防锚定污染）。

用法（Git Bash，JEV_CF_TOKEN 取自 .env.local）：
  ./.venv/Scripts/python.exe -m backend.operations.jev_label_pilot \
      --start 2026-09-04 --end 2026-09-29 [--dry-run] [--workers 2]
"""
from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor

from backend.services.jev.jev_client import call_jev, parse_jev_response

# 考题集 §二（2026-10-03 用户逐题确认 + Q5 裁决收官 26d8ddbb）：
# 个股四题（Q1-Q3 与 v2 jev_label_jiuyan.py 逐字一致=同题锚；Q4 买盘逻辑）+ Q5 相位题拆日级独立调用（run_phase_band_day）。
QUESTIONS_STOCK = {
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
    "buy_side_logic": {"type": "choice",
                       "instructions": "该股今日涨停的最主要买盘逻辑是哪一类？只依据所给信息判断，不预测后市。",
                       "criteria": {
                           "independent_catalyst": "自身独立催化：今日涨停主要由该公司自身的公告/订单/事件驱动，解析中存在对应的具体事件行（公告、中标、业绩、产品、重组等）",
                           "sector_follow": "板块联动跟随：同板块多股今日集体异动，该股为跟随位（盘面/板块地位显示该板块今日涨停家数多，且该股封板时间偏晚）",
                           "high_board_relay": "高位卡位/情绪接力：无明确新催化，主要靠连板高度与情绪地位接续资金（身位显示 3 板及以上梯队，且解析中无新增具体事件行）",
                           "pure_sentiment": "纯情绪修复：无板块协同、无连板高度、无新增事件，属情绪性反弹"}},
}

# Q5 相位题：日级独立调用专用（C 架构=日级粗哨兵，强/非强两档实测有效，冷/弱边界信任规则分）
QUESTIONS_PHASE = {"phase_band": {"type": "choice",
                   "instructions": "仅依据所给盘面事实（涨停家数、炸板率、连板梯队、板块效应及各自近 20 日分位），"
                                   "判断当日市场情绪相位落在哪一档？只依据所给信息判断，不预测后市。",
                   "criteria": {
                       "cold_lt40": "冷带：情绪低迷，涨停家数/梯队高度/板块效应处于近 20 日低位区（对应情绪分 40 分线以下）",
                       "weak_40_60": "弱势带：情绪中性偏弱，涨停与梯队处于中位附近（对应情绪分 40-60）",
                       "strong_ge60": "强势带：情绪活跃偏强，涨停家数/梯队高度/板块效应处于近 20 日高位区（对应情绪分 60 分线以上）",
                       "insufficient": "证据不足：所给盘面事实不足以判断，不强行归类"}}}

THS_KEYS = ("one", "two", "three", "four", "high")

_FACTS_CACHE: dict[str, str] = {}
_THS_CACHE: dict[str, dict] = {}


def _strip(code) -> str:
    c = str(code or "")
    return c[2:] if len(c) > 2 and c[:2] in ("sh", "sz", "bj") else c


def ths_positions(db, date: str) -> dict[str, dict]:
    """(date) → code → THS 身位（连板梯队/首封时间/板块/主力净额），按日缓存。"""
    if date in _THS_CACHE:
        return _THS_CACHE[date]
    f = db["snapshot_frames"].find_one({"tradingDate": date, "slotTime": "15:00"},
                                       {"limitSummary.thsPools.pools": 1})
    out: dict[str, dict] = {}
    for key in THS_KEYS:
        pool = (((f or {}).get("limitSummary") or {}).get("thsPools") or {}).get("pools", {}).get(key) or {}
        for it in pool.get("items") or []:
            out[_strip(it.get("stock_code"))] = {
                "ladder": key, "continueDay": it.get("continue_day"),
                "firstSeal": it.get("limit_up_time"), "industry": it.get("industry_block"),
                "mainNet": it.get("main_net_amount")}
    _THS_CACHE[date] = out
    return out


def dieban_count(db, date: str) -> int | None:
    """跌停家数（收盘口径，按板籍阈值 10/20/30cm 自算——帧内无现成字段，口径如实标注）。"""
    bar_by = {"30": -19.8, "68": -19.8, "43": -29.8, "83": -29.8, "87": -29.8, "92": -29.8}
    seen: set[str] = set()
    n = 0
    for r in db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": date, "slotTime": "15:00",
             "pctChange": {"$exists": True, "$ne": None}}, {"code": 1, "pctChange": 1}):
        code = str(r.get("code") or "")
        if code in seen:
            continue
        seen.add(code)
        pc = r.get("pctChange")
        bar = bar_by.get(code[:2], -9.8)
        if isinstance(pc, (int, float)) and pc <= bar:
            n += 1
    return n if seen else None


def market_metrics(db, date: str) -> dict | None:
    """当日 15:00 盘面事实（涨停/炸板/回撤/梯队/最高板高；跌停另行自算）。"""
    f = db["snapshot_frames"].find_one({"tradingDate": date, "slotTime": "15:00"},
                                       {"limitSummary.zhaban": 1, "limitSummary.continuousBoards": 1,
                                        "limitSummary.thsPools.pools": 1, "limitSummary.drawdown": 1})
    ls = (f or {}).get("limitSummary") or {}
    zb = ls.get("zhaban") or {}
    cb = ls.get("continuousBoards") or {}
    dd = ls.get("drawdown") or {}
    pools = (ls.get("thsPools") or {}).get("pools") or {}
    ladder = {k: (pools.get(k) or {}).get("total") for k in THS_KEYS}
    if not zb.get("ztCount"):
        return None
    return {"ztCount": zb.get("ztCount"), "zhabanCount": zb.get("count"), "zhabanRate": zb.get("rate"),
            "drawdownCount": dd.get("count"), "ladder": ladder, "maxBoard": cb.get("maxBoard")}


def trading_dates_before(db, date: str, n: int = 20) -> list[str]:
    rows = db["snapshot_stock_rows"].find(
        {"type": "half_hour", "tradingDate": {"$lt": date}}, {"tradingDate": 1})
    return sorted({str(r["tradingDate"]) for r in rows if r.get("tradingDate")})[-n:]


def percentile_rank(values: list, cur) -> str:
    """cur 在 values（近20日历史）中的分位（0-100，不含 cur 自身）；样本 <10 不可算（fail-visible）。"""
    vals = [v for v in values if isinstance(v, (int, float))]
    if len(vals) < 10 or not isinstance(cur, (int, float)):
        return "分位不可算"
    return f"{sum(1 for v in vals if v < cur) / len(vals) * 100:.0f}"


def market_facts_line(db, date: str) -> str:
    """弹药 6：分位盘面事实行（不含规则情绪分——Q5 防锚定污染）。按日缓存。"""
    if date in _FACTS_CACHE:
        return _FACTS_CACHE[date]
    cur = market_metrics(db, date)
    if not cur:
        return f"盘面事实：{date} 盘面指标缺失（fail-visible）"
    prev = trading_dates_before(db, date)
    hist = [m for m in (market_metrics(db, d) for d in prev) if m]
    hist_die = [v for v in (dieban_count(db, d) for d in prev) if isinstance(v, (int, float))]
    cur_die = dieban_count(db, date)

    def pct(vals, cur_v):
        return percentile_rank(vals, cur_v)

    die_txt = (f'跌停 {cur_die} 家（{pct(hist_die, cur_die)} 分位）'
               if isinstance(cur_die, (int, float)) else "跌停 不可算")
    rate = f'{cur["zhabanRate"]:.1f}%' if isinstance(cur["zhabanRate"], (int, float)) else "缺"
    three_plus = (cur["ladder"].get("three") or 0) + (cur["ladder"].get("four") or 0) + (cur["ladder"].get("high") or 0)
    line = (f'盘面事实：涨停 {cur["ztCount"]} 家（{pct([h["ztCount"] for h in hist], cur["ztCount"])} 分位）'
            f' · {die_txt}'
            f' · 炸板率 {rate}（{pct([h["zhabanRate"] for h in hist], cur["zhabanRate"])} 分位，炸板 {cur["zhabanCount"] or 0} 家）'
            f' · 大幅回撤 {cur["drawdownCount"] if cur["drawdownCount"] is not None else "?"} 家'
            f'（{pct([h["drawdownCount"] for h in hist], cur["drawdownCount"])} 分位）'
            f' · 连板梯队 一板{cur["ladder"].get("one") or 0}/二板{cur["ladder"].get("two") or 0}/三板+{three_plus}'
            f' · 最高 {cur["maxBoard"]} 板（{pct([h["maxBoard"] for h in hist], cur["maxBoard"])} 分位）')
    _FACTS_CACHE[date] = line
    return line


def board_position(jiuyan_doc, code: str) -> str:
    """弹药 5：板块地位（所属韦研板块今日涨停家数 + 该股按涨停时间的封板序）。"""
    best = None
    for fl in jiuyan_doc.get("fields") or []:
        stocks = fl.get("stocks") or []
        for i, s in enumerate(stocks):
            if _strip(s.get("code")) == code:
                times = sorted(str(x.get("time") or "") for x in stocks)
                pos = times.index(str(s.get("time") or "")) + 1 if str(s.get("time") or "") in times else None
                cand = {"board": fl.get("name"), "n": len(stocks), "pos": pos}
                if best is None or (pos or 999) < (best["pos"] or 999):
                    best = cand
    if not best:
        return "板块地位：未在韭研板块结构中定位（fail-visible）"
    pos = f'第 {best["pos"]} 封板' if best["pos"] else "封板序不可考"
    return f'板块地位：所属韭研板块「{best["board"]}」今日涨停 {best["n"]} 家，该股板块内 {pos}'


def build_pilot_narrative(db, date: str, code: str, stock: dict, board: str, rank) -> str:
    """v3 弹药叙事：盘面事实行（无情绪分）+ 个股解析 + THS 身位块 + 板块地位块 + 热榜。"""
    jy = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
    ths = ths_positions(db, date).get(code)
    if ths:
        ladder_txt = str(ths["continueDay"]) if ths["continueDay"] is not None else "?"
        if "连板" not in ladder_txt and "板" not in ladder_txt:
            ladder_txt += "连板"
        ths_line = (f'THS 封板梯队：{ladder_txt} · 首封 {ths["firstSeal"]}'
                    f' · 所属板块 {ths["industry"] or "缺"} · 主力净额 {ths["mainNet"]}')
    else:
        ths_line = "未进 THS 封板池（今日触板未封/炸板口径）"
    expound = str(stock.get("expound") or "").strip()
    expound_line = expound if expound else "（韦研解析缺失，fail-visible）"
    day_txt = str(stock.get("day") or "")
    if day_txt and "天" not in day_txt:
        day_txt += "天"
    num_txt = str(stock.get("num") or "")
    if num_txt and "板" not in num_txt:
        num_txt += "板"
    if num_txt and "天" in num_txt:  # 韦研 num 可能自带「2天2板」完整口径，与 day 拼接会重复
        day_num = f'，{num_txt}'
    else:
        day_num = f'，{day_txt}{num_txt}' if (day_txt or num_txt) else ""
    hot = f"今日热榜最高排名第 {rank} 位" if rank else "未进热榜"
    return "\n".join([
        f"{date} 交易日 · {market_facts_line(db, date)}",
        f"该股：{stock.get('name')}（{code}），今日涨停价 {stock.get('price')}{day_num}，涨停时间 {stock.get('time')}；{hot}",
        f"身位：{ths_line}",
        board_position(jy, code),
        "韭研解析全文：",
        expound_line,
    ])


def _db():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    return get_runtime_mongodb_database()


def day_population(db, date: str) -> list[dict]:
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"})
    if not doc:
        return []
    out = []
    for field in doc.get("fields") or []:
        for stock in field.get("stocks") or []:
            out.append({"stock": stock, "board": field.get("name") or ""})
    return out


def hotlist_ranks(db, date: str, codes: list[str]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for r in db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": date, "code": {"$in": codes}, "rank": {"$exists": True}},
            {"code": 1, "rank": 1}):
        rank, code = r.get("rank"), r.get("code")
        if isinstance(rank, int) and rank > 0 and (code not in ranks or rank < ranks[code]):
            ranks[code] = rank
    return ranks


def _label_one(db, col, acc, token, date, code, stock, board, rank):
    narrative = build_pilot_narrative(db, date, code, stock, board, rank)
    env, ms = call_jev(acc, token, narrative, QUESTIONS_STOCK)
    parsed = parse_jev_response(env, ms)
    answers = parsed.get("answers") or {}
    doc = {"_id": f"{date}:{code}", "origin": "driver_label_jiuyan_v3_pilot", "tradingDate": date,
           "code": code, "name": stock.get("name"),
           "jiuyanContext": {"board": board, "day": stock.get("day"), "num": stock.get("num"),
                             "time": stock.get("time"), "inHotlist": rank is not None, "rank": rank},
           "status": "ok" if parsed["ok"] else "degraded",
           "narrative": narrative, "questionsRaw": QUESTIONS_STOCK,
           "label": answers.get("driver_type", {}).get("choice"),
           "driverProbabilities": answers.get("driver_type", {}).get("probabilities"),
           "catalystDepth": answers.get("catalyst_depth", {}).get("choice"),
           "catalystDepthProbabilities": answers.get("catalyst_depth", {}).get("probabilities"),
           "freshness": answers.get("catalyst_freshness", {}).get("choice"),
           "buySideLogic": answers.get("buy_side_logic", {}).get("choice"),
           "buySideProbabilities": answers.get("buy_side_logic", {}).get("probabilities"),
           "phaseBand": answers.get("phase_band", {}).get("choice"),
           "phaseBandProbabilities": answers.get("phase_band", {}).get("probabilities"),
           "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
           "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
           "responseRaw": None if parsed["ok"] else env,
           "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return bool(parsed["ok"])


def run(start: str, end: str, dry_run: bool, token: str, acc: str, workers: int = 2):
    db = _db()
    col = db["hotlist_jev_driver_labels"]
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end}},
        {"tradingDate": 1}) if d.get("tradingDate")})
    if not dates:
        print(f"窗口 {start}~{end} 无 jiuyan_action final 文档，退出（fail-visible）")
        return
    n_ok = n_deg = 0
    total_usage = 0
    for di, date in enumerate(dates):
        pop = day_population(db, date)
        if not pop:
            print(f"[{di + 1}/{len(dates)}] {date} 无韭研 final 文档，跳过（披露）")
            continue
        items: dict[str, dict] = {}
        for entry in pop:
            code = _strip(entry["stock"].get("code"))
            items[code] = entry
        codes = list(items.keys())
        done = {d["code"] for d in col.find({"tradingDate": date, "status": "ok"}, {"code": 1})
                if d.get("code")}  # PHASE 日级文档无 code，跳过防 KeyError
        codes = [c for c in codes if c not in done]
        if not codes:
            print(f"[{di + 1}/{len(dates)}] {date} 全部已打，跳过")
            continue
        ranks = hotlist_ranks(db, date, list(items.keys()))
        if dry_run:
            sample = items[codes[0]]
            print(f"[dry] {date} {sample['stock'].get('name')}\n" + build_pilot_narrative(
                db, date, codes[0], sample["stock"], sample["board"], ranks.get(codes[0])))
            print(f"[{di + 1}/{len(dates)}] {date} population={len(codes)} hotlistHit={len(ranks)}")
            continue

        def work(code):
            entry = items[code]
            for attempt in range(2):
                result = _label_one(db, col, acc, token, date, code, entry["stock"],
                                    entry["board"], ranks.get(code))
                if result:
                    return True
                time.sleep(1.0)
            return False

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(work, codes))
        n_ok += sum(results)
        n_deg += len(results) - sum(results)
        print(f"[{di + 1}/{len(dates)}] {date} done n={len(codes)} (cum ok={n_ok} deg={n_deg})")
    if not dry_run:
        for d in col.find({}, {"usage": 1}):
            u = d.get("usage") or {}
            if isinstance(u, dict) and isinstance(u.get("total_tokens"), (int, float)):
                total_usage += int(u["total_tokens"])
        print("FINAL:", {"ok": n_ok, "degraded": n_deg, "totalTokens": total_usage})


# 情绪周期段位题（questionset-review §十二，2026-10-03 用户批准 3 天试点不全量；归宿=情绪轨道，
# 试点期借打标 runner 的弹药层执行，落 hotlist_jev_cycle_stage_pilot 临时集合）。
QUESTIONS_CYCLE = {"cycle_stage": {"type": "choice",
                   "instructions": "以下是最近 10 个交易日的盘面序列与今日盘面事实。请判断：今日市场情绪处于情绪周期的哪一段？"
                                   "判段以「今日各项指标在近 10 日序列中的相对位置」为主锚（峰值区/谷值区/回升/回落），先读摆动锚：峰值距今几天决定今日处于回落段还是回升段、谷值距今几天决定是否冰点区，"
                                   "游资语境参考：退潮初期是高度刚回落、亏钱效应开始扩散；冰点是退潮末期——涨停缩到地量、"
                                   "首板堆积、老周期高标出清，反弹在即反而是积极信号。只依据所给信息判断，不预测后市。",
                   "criteria": {
                       "ebb_early": "退潮初期：涨停家数/最高板自近 10 日峰值回落的前 1-3 天，炸板率/回撤自低位抬升，亏钱效应开始扩散",
                       "ice_end": "冰点（退潮末期）：涨停家数处于近 10 日地量档，跌停/回撤/炸板率处于高位（不必已回落），首板堆积、高标独苗或断板——反弹在即",
                       "repair": "修复启动：涨停家数自近 10 日谷值明显回升、炸板率自高位回落，但家数/高度尚未贴近窗口峰值",
                       "ferment": "发酵主升：涨停家数与梯队连日走高、贴近窗口峰值且炸板率不高",
                       "climax": "高潮：涨停家数或最高板创近 10 日新高或贴近窗口峰值，且炸板率未失控",
                       "divergence": "高潮分歧：家数/高度仍在窗口高位，但炸板率快速抬升、龙头烂板",
                       "insufficient": "证据不足：所给序列不足以判断，不强行归类"}}}


def trajectory_line(db, date: str, n: int = 10) -> str:
    """近 n 个交易日逐日序列：日期|涨停(较昨日Δ)|跌停|炸板率%|大幅回撤|最高板。"""
    window = trading_dates_before(db, date, n + 1)  # 首日仅为算首格 Δ
    series = []
    for d in window:
        m = market_metrics(db, d) or {}
        die = dieban_count(db, d)
        rate = m.get("zhabanRate")
        rate_txt = f'{round(rate, 1)}%' if isinstance(rate, (int, float)) else "?"
        zt = m.get("ztCount") if isinstance(m.get("ztCount"), (int, float)) else None
        dd = m.get("drawdownCount")
        mb = m.get("maxBoard")
        series.append({"d": d, "zt": zt, "die": die, "rate": rate_txt,
                       "dd": dd if isinstance(dd, (int, float)) else None,
                       "mb": mb if isinstance(mb, (int, float)) else None})
    rows = []
    for i, r in enumerate(series[1:]):
        prev = series[i]
        if r["zt"] is not None and prev["zt"] is not None:
            delta = f'{r["zt"] - prev["zt"]:+d}'
        else:
            delta = "?"
        die_txt = r["die"] if r["die"] is not None else "?"
        dd_txt = r["dd"] if r["dd"] is not None else "?"
        mb_txt = r["mb"] if r["mb"] is not None else "?"
        zt_txt = r["zt"] if r["zt"] is not None else "?"
        rows.append(f'{r["d"][5:]}|涨停{zt_txt}({delta})|跌停{die_txt}|炸板{r["rate"]}|回撤{dd_txt}|板{mb_txt}')
    head = f'近{len(rows)}个交易日序列（日期|涨停(较昨日Δ)|跌停|炸板率|大幅回撤|最高板）：'
    return head + " ； ".join(rows)




def swing_summary_line(db, date: str, n: int = 10) -> str:
    """摆动锚：窗口峰值/谷值（家数、日期、距今交易日数）+ 今日较昨日 Δ 与距峰值幅度。"""
    prev = trading_dates_before(db, date, n)
    vals = []
    for d in prev:
        m = market_metrics(db, d) or {}
        if isinstance(m.get("ztCount"), (int, float)):
            vals.append((d, int(m["ztCount"])))
    m_cur = market_metrics(db, date) or {}
    cur_zt = m_cur.get("ztCount") if isinstance(m_cur.get("ztCount"), (int, float)) else None
    if len(vals) < 5 or cur_zt is None:
        return "摆动锚：窗口数据不足（fail-visible）"
    all_days = vals + [(date, cur_zt)]
    ordered = [d for d, _ in all_days]
    peak_d, peak = max(all_days, key=lambda x: (x[1], x[0]))
    trough_d, trough = min(all_days, key=lambda x: (x[1], x[0]))
    peak_ago = len(ordered) - 1 - ordered.index(peak_d)
    trough_ago = len(ordered) - 1 - ordered.index(trough_d)
    delta = cur_zt - vals[-1][1]
    return (f'摆动锚：近{len(all_days)}个交易日涨停峰值 {peak} 家（{peak_d[5:]}，距今 {peak_ago} 个交易日）'
            f'；谷值 {trough} 家（{trough_d[5:]}，距今 {trough_ago} 个交易日）'
            f'；今日 {cur_zt} 家（较昨日 {delta:+d}，距峰值 {cur_zt - peak:+d} 家）')


def build_cycle_narrative(db, date: str) -> str:
    lines = [
        f"{date} 交易日",
        market_facts_line(db, date),
        swing_summary_line(db, date),
        trajectory_line(db, date),
    ]
    return chr(10).join(lines)


def run_cycle_stage_day(db, dates: list[str], token: str, acc: str) -> None:
    """情绪周期段位试点：日级独立调用，落 hotlist_jev_cycle_stage_pilot（_id={date}:CYCLE）。"""
    col = db["hotlist_jev_cycle_stage_pilot"]
    for date in dates:
        done = col.find_one({"_id": f"{date}:CYCLE", "status": "ok"})
        if done:
            print(f"[cycle] {date} 已判（{done.get('cycleStage')}），跳过")
            continue
        narrative = build_cycle_narrative(db, date)
        env, ms = call_jev(acc, token, narrative, QUESTIONS_CYCLE)
        parsed = parse_jev_response(env, ms)
        answers = parsed.get("answers") or {}
        doc = {"_id": f"{date}:CYCLE", "origin": "cycle_stage_daily", "tradingDate": date,
               "status": "ok" if parsed["ok"] else "degraded",
               "narrative": narrative, "questionsRaw": QUESTIONS_CYCLE,
               "cycleStage": answers.get("cycle_stage", {}).get("choice"),
               "cycleStageProbabilities": answers.get("cycle_stage", {}).get("probabilities"),
               "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
               "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
               "responseRaw": None if parsed["ok"] else env,
               "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
        col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        u = parsed.get("usage") or {}
        print(f"[cycle] {date} → {doc['cycleStage']} ok={parsed['ok']} "
              f"tokens={(u.get('input_tokens') or 0) + (u.get('output_tokens') or 0)}")


def run_phase_band_day(db, dates: list[str], token: str, acc: str) -> None:
    """方案 A：Q5 拆日级独立调用——每交易日一次、只喂盘面事实行不喂个股解析（去语境污染）。
    判定落同一 pilot 集合，_id={date}:PHASE、origin=phase_band_daily，与个股文档显式区隔。"""
    col = db["hotlist_jev_driver_labels"]
    for date in dates:
        done = col.find_one({"_id": f"{date}:PHASE", "status": "ok"})
        if done:
            print(f"[phase] {date} 已判（{done.get('phaseBand')}），跳过")
            continue
        narrative = f"{date} 交易日 · {market_facts_line(db, date)}"
        env, ms = call_jev(acc, token, narrative, QUESTIONS_PHASE)
        parsed = parse_jev_response(env, ms)
        answers = parsed.get("answers") or {}
        doc = {"_id": f"{date}:PHASE", "origin": "phase_band_daily", "tradingDate": date,
               "status": "ok" if parsed["ok"] else "degraded",
               "narrative": narrative, "questionsRaw": QUESTIONS_PHASE,
               "phaseBand": answers.get("phase_band", {}).get("choice"),
               "phaseBandProbabilities": answers.get("phase_band", {}).get("probabilities"),
               "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
               "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
               "responseRaw": None if parsed["ok"] else env,
               "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
        col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
        u = parsed.get("usage") or {}
        print(f"[phase] {date} → {doc['phaseBand']} ok={parsed['ok']} "
              f"tokens={(u.get('input_tokens') or 0) + (u.get('output_tokens') or 0)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=False)
    ap.add_argument("--end", required=False)
    ap.add_argument("--phase-band-day", dest="phase_band_day", required=False,
                    help="日级相位哨兵：只对指定交易日跑一次盘面事实判档（盘后链步骤 5）")
    ap.add_argument("--cycle-stage-day", dest="cycle_stage_day", action="append", default=[],
                    help="情绪周期段位试点：指定交易日判游资周期段位（可多次传参）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    tok = os.environ.get("JEV_CF_TOKEN") or ""
    assert tok, "需要 JEV_CF_TOKEN 环境变量"
    acc = os.environ.get("JEV_CF_ACCOUNT", "921cf15176f84c90ea49865334af32c6")
    if args.cycle_stage_day:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        run_cycle_stage_day(get_runtime_mongodb_database(), args.cycle_stage_day, tok, acc)
    elif args.phase_band_day:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        run_phase_band_day(get_runtime_mongodb_database(), [args.phase_band_day], tok, acc)
    else:
        assert args.start and args.end, "个股模式需要 --start/--end"
        run(args.start, args.end, args.dry_run, tok, acc, args.workers)
