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
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

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

# 个股相位分线题（2026-10-04 用户澄清题意后裁决试点：问该股自身本轮行情位置，非市场相位；
# 设计稿见 docs/hotlist-jev/jev-driver-label-v3-questionset.md 尾部。
# v0.5（同日用户令）：量能锚升级对比前 3 日均量+缩量/放量语义按位置与封板质量分化入题；
# 判据改动经用户裁决冻结）
QUESTIONS_STOCK_PHASE = {"stock_phase_position": {"type": "choice",
                          "instructions": "仅依据该股自身证据（价格位置轴：20 日窗口涨幅/距 20 日最高/窗口低点距今交易日数/"
                                          "近 5 日涨幅贡献/量能缩放；结构轴：近 10 日涨停序列=几天几板/断板反包；"
                                          "质量轴：当日板型=一字板/秒板硬板/炸板回封/烂板/触板未封），"
                                          "判断该股当前处在自身本轮行情相位分线的哪个位置？只判位置，不预测后市。"
                                          "判定优先级：质量示警（烂板/炸板收盘/尾盘勉强板/放巨量滞涨）的分歧位 > 位置归层。"
                                          "注意四条：①涨停日现价常即 20 日新高，距高点≈0 不能单独当高位证据；"
                                          "②位置分界看形态不只看涨幅——窗口低点距今 ≤8 日=低位新鲜（即使涨幅 30-50% 也是启动），"
                                          "≥15 日=趋势已久（即使涨幅 <50% 也算高位），中间带由量能与板型定（放量 ≥1.5 倍+强板=放量加速）；"
                                          "③单次炸板回封且封板至收盘=当日弱转强修复（中性偏多），不是分歧示警；"
                                          "④量能语义看封板质量：缩量板=一致锁定惜售（加速/一致佐证），"
                                          "放量板=换手充分——低位放量承接是健康启动、高位放量且封得稳是加速、"
                                          "放量但封不住/反复开板才是分歧出货，同位置缩量与放量结论可能不同。",
                          "criteria": {
                              "divergence": "分歧位（示警优先）：高位或趋势已久（窗口涨幅 ≥50%、3 连板+、或窗口低点距今 ≥15 日）且当日示警——"
                                            "烂板（炸板≥2 次回封）、炸板收盘（触板未封）、尾盘勉强封板、放巨量滞涨（量比 ≥1.5 倍但封不住/反复开板）；"
                                            "判例：趋势爬升一整月后的缩量首板赶顶（窗口低点距今 ≥15 日、平量/缩量）=高位分歧",
                              "climax": "高位加速（一致段）：高位（窗口涨幅 ≥50%、4 连板+、或趋势已久）且加速形态——"
                                        "放量（≥1.5 倍）强板、一字板/秒板/早封硬板、缩量加速或缩量反包（量能萎缩=一致锁定惜售）；"
                                        "高位断板反包且板型硬亦判本层；"
                                        "判例①：高位回撤后再放量强板创新高（窗口低点距今 9-14 日、量比 ≥1.5）=放量加速；"
                                        "判例②：高位断板多日后缩量硬板反包（量比 ≤0.7、秒封）=惜售一致修复",
                              "ferment": "中位发酵：窗口涨幅 30-50% 且低点距今 9-14 日且板型正常；或 2-3 连板晋级顺利",
                              "start": "低位启动：窗口低点距今 ≤8 个交易日（低位新鲜，即使窗口涨幅 30-50%）；或窗口涨幅 <30%；"
                                       "含首板突破长期平台、深回调（距 20 日最高 >20%）后反包首板；低位断板反包=启动确认归本层；"
                                       "低位放量换手板（量比 ≥1.5 倍且封得稳）=承接健康属本层；"
                                       "判例：长期平台后 4 天 2 板突破（低点距今 ≤8 日）=启动确认",
                              "insufficient": "信息不足：位置/结构/质量三轴证据均缺失（如上市窗口过短），不强行归类"}}}

# 合并同 call 题集（2026-10-04 用户裁决「真合并后再跑」）：四题原样 + 相位题原文，判据逐字不变
# （题目语义零变更仅打包方式变化——同 call 共享 narrative 输入，相位边际成本从 ≈2,420 tokens/只
# 独立调用降至题干+答案数百 tokens）。存量老文档补齐仍走单题 CLI（run_stock_phase_pilot 保留）。
QUESTIONS_STOCK_WITH_PHASE = {**QUESTIONS_STOCK, "stock_phase_position": QUESTIONS_STOCK_PHASE["stock_phase_position"]}

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


_ADVDEC_CACHE: dict[str, tuple] = {}


def advdec_ratio(db, date: str) -> tuple | None:
    """池内涨/跌/平家数与涨跌比（采集池口径，15:00 收盘）——区分「不交易」与「杀跌」的特征。"""
    if date in _ADVDEC_CACHE:
        return _ADVDEC_CACHE[date]
    up = down = flat = 0
    seen = 0
    for r in db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": date, "slotTime": "15:00",
             "pctChange": {"$exists": True, "$ne": None}}, {"pctChange": 1}):
        pc = r.get("pctChange")
        if not isinstance(pc, (int, float)):
            continue
        seen += 1
        if pc > 0.1:
            up += 1
        elif pc < -0.1:
            down += 1
        else:
            flat += 1
    result = (up, down, flat, round(up / max(down, 1), 2)) if seen else None
    _ADVDEC_CACHE[date] = result
    return result


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


def _advdec_segment(db, date: str) -> str:
    ad = advdec_ratio(db, date)
    if not ad:
        return " · 池内涨跌结构 不可算（fail-visible）"
    up, down, flat, ratio = ad
    if 0.8 <= ratio <= 1.25:
        tone = "均衡（没人买也没人卖）"
    elif ratio > 1.25:
        tone = "单边偏强"
    else:
        tone = "单边偏弱"
    return f' · 池内涨跌比 {ratio}（涨{up}/跌{down}，{tone}）'


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
            f' · 最高 {cur["maxBoard"]} 板（{pct([h["maxBoard"] for h in hist], cur["maxBoard"])} 分位）'
            + _advdec_segment(db, date))
    _FACTS_CACHE[date] = line
    return line


# ---- 弹药 6：个股价格位置轴（2026-10-04 用户令接入：距 20 日最高/窗口涨幅/量能缩放——
#      首板单锚判不出高位，龙版传媒 605577 首板但距 20 日高点仅 7.8%/窗口涨幅 62.5% 实锤） ----
_POSITION_LOCK = threading.Lock()
_DAILY_CLIENT: Any = None
_DAILY_BARS_CACHE: dict[str, list[dict]] = {}
TDX_HOSTS_PATH = Path(r"D:\dragon-board\python-bridge\tdx_hosts.json")


def _tdx_daily_client():
    """TDX 日线客户端单例（节点池探测同 backfill_slot_pctchange 模式）；全节点不可用返回 None。"""
    global _DAILY_CLIENT
    with _POSITION_LOCK:
        if _DAILY_CLIENT is not None:
            return _DAILY_CLIENT
        try:
            hosts = json.loads(TDX_HOSTS_PATH.read_text(encoding="utf-8"))["candidates"]
            from mootdx.quotes import Quotes
            for h in hosts[:8]:
                try:
                    client = Quotes.factory(market="std", server=(h["ip"], int(h["port"])),
                                            timeout=6, bestip=False)
                    if len(client.index_bars(symbol="999999", frequency=9, start=0, offset=5)) > 0:
                        _DAILY_CLIENT = client
                        return client
                except Exception:
                    continue
        except Exception:
            return None
    return None


def _daily_bars(code: str) -> list[dict]:
    """日线棒升序（date/high/close/vol），取最近 60 根覆盖 20 日窗口；失败返回 []（调用方 fail-visible）。"""
    cached = _DAILY_BARS_CACHE.get(code)
    if cached is not None:
        return cached
    bars: list[dict] = []
    client = _tdx_daily_client()
    if client is not None:
        try:
            with _POSITION_LOCK:
                df = client.bars(symbol=code, frequency=9, start=0, offset=60)
            if df is not None and len(df) > 0:
                for _, r in df.iterrows():
                    bars.append({
                        "date": f"{int(r['year']):04d}-{int(r['month']):02d}-{int(r['day']):02d}",
                        "high": float(r["high"]), "close": float(r["close"]),
                        "vol": float(r.get("vol") or 0),
                    })
                bars.sort(key=lambda b: b["date"])
        except Exception:
            bars = []
    _DAILY_BARS_CACHE[code] = bars
    return bars


def stock_position_line(date: str, code: str) -> str:
    """弹药 6 行：价格位置轴原始可数锚（不给档位标签防预判，阈值锚在判据里）。
    fail-visible：TDX 不可用/缺今日棒/数据不足如实标注，不伪造数字。"""
    try:
        bars = _daily_bars(code)
        if not bars:
            return "个股位置：TDX 日线不可用（fail-visible，价格位置轴缺失）"
        window = [b for b in bars if b["date"] <= date]
        today = next((b for b in window if b["date"] == date), None)
        if today is None:
            return f"个股位置：{date} 无当日日线棒（停牌或数据缺口，fail-visible）"
        if len(window) < 2:
            return "个股位置：上市数据不足 2 根日线（fail-visible）"
        last20 = window[-20:]
        high20 = max(b["high"] for b in last20)
        closes20 = [b["close"] for b in last20]
        low_close = min(closes20)
        low_ago = len(closes20) - 1 - closes20.index(low_close)
        gap_pct = (high20 - today["close"]) / high20 * 100
        chg_pct = (today["close"] - low_close) / low_close * 100
        # 形态锚（v0.4 用户判例校准：位置分界看低点新鲜度不只看涨幅）
        prev5_close = closes20[-6] if len(closes20) >= 6 else closes20[0]
        contrib_pct = (today["close"] - prev5_close) / (today["close"] - low_close) * 100 \
            if today["close"] > low_close else None
        contrib_txt = f"{contrib_pct:.0f}%" if contrib_pct is not None else "不可算"
        # 量能锚（v0.5 用户令：对比前三日均量——缩量涨停/放量涨停语义不同）
        prev3_vols = [b["vol"] for b in last20[-4:-1]]
        avail = [v for v in prev3_vols if v > 0]
        if avail:
            base = sum(avail) / len(avail)
            ratio = today["vol"] / base
            tag = "放量" if ratio >= 1.5 else ("缩量" if ratio <= 0.7 else "平量")
            base_txt = "前 3 日均量" if len(avail) == 3 else f"前 {len(avail)} 日均量（缺 {3 - len(avail)} 日）"
            vol_txt = f"今日为{base_txt}的 {ratio:.2f} 倍（{tag}）"
        else:
            vol_txt = "前 3 日量能缺失（fail-visible）"
        note = "" if len(last20) >= 20 else f"（上市窗口仅 {len(last20)} 根）"
        return (f"个股位置：现价 {today['close']:.2f} · 距 20 日最高 {high20:.2f} 差 {gap_pct:.1f}%"
                f" · 20 日窗口涨幅 {chg_pct:+.1f}%（最低收盘 {low_close:.2f}，距今 {low_ago} 个交易日）"
                f" · 近 5 日贡献 {contrib_txt}{note}"
                f" · 量能：{vol_txt}")
    except Exception as e:
        return f"个股位置：计算失败 {e}（fail-visible）"


def _limit_pct_of(code: str, name: str | None) -> float:
    """板籍涨停幅度档（近似判定容差 0.2pp 由调用方取整涨停价吸收）：北交所 30/创业科创 20/ST 5/其余 10。"""
    c = str(code or "")
    if c.startswith(("83", "87", "88", "43", "92")):
        return 0.298
    if c.startswith(("300", "301", "302", "688", "689")):
        return 0.198
    if "ST" in str(name or "").upper():
        return 0.048
    return 0.098


def limitup_sequence_line(date: str, code: str, name: str | None, n: int = 10) -> str:
    """弹药 7：近 n 日涨停序列（收盘口径，板籍阈值判定）——几天几板/断板反包（隔日弱转强）机械锚。
    fail-visible：日线缺当日棒/窗口不足如实标注；除权日 prev_close 失真属已知边缘（登记）。"""
    try:
        bars = _daily_bars(code)
        window = [b for b in bars if b["date"] <= date]
        if not window or window[-1]["date"] != date:
            return "板序：当日日线棒缺失（fail-visible）"
        seq: list[int] = []
        i = len(window) - 1
        while i >= 1 and len(seq) < n:
            up = window[i]["close"] >= round(window[i - 1]["close"] * (1 + _limit_pct_of(code, name)), 2) - 1e-6
            seq.append(1 if up else 0)
            i -= 1
        if not seq:
            return "板序：窗口不足无法判定（fail-visible）"
        seq.reverse()
        marks = "".join("●" if v else "○" for v in seq)
        streak = 0
        for v in reversed(seq):
            if not v:
                break
            streak += 1
        rewrap = seq[-1] == 1 and (len(seq) < 2 or seq[-2] == 0) and any(seq[:-1])
        tag = " · 今日=断板反包（隔日弱转强）" if rewrap else ""
        return (f"板序：近 {len(seq)} 日 {marks}（●=涨停，末位今日） · 当前连板 {streak}"
                f" · 窗口内 {sum(seq)} 板{tag}")
    except Exception as e:
        return f"板序：计算失败 {e}（fail-visible）"


_INTRA_CACHE: dict[str, list[dict]] = {}


def _intraday_bars(code: str) -> list[dict]:
    """5 分钟棒（date/hm/open/high/close），最近 800 根 ≈16 个交易日；失败返回 []（调用方 fail-visible）。"""
    cached = _INTRA_CACHE.get(code)
    if cached is not None:
        return cached
    out: list[dict] = []
    client = _tdx_daily_client()
    if client is not None:
        try:
            with _POSITION_LOCK:
                df = client.bars(symbol=code, frequency=0, start=0, offset=800)
            if df is not None and len(df) > 0:
                for _, r in df.iterrows():
                    out.append({
                        "date": f"{int(r['year']):04d}-{int(r['month']):02d}-{int(r['day']):02d}",
                        "hm": f"{int(r['hour']):02d}:{int(r['minute']):02d}",
                        "open": float(r["open"]), "high": float(r["high"]),
                        "close": float(r["close"]),
                    })
        except Exception:
            out = []
    _INTRA_CACHE[code] = out
    return out


def _prev_close_of_date(date: str, code: str) -> float | None:
    bars = [b for b in _daily_bars(code) if b["date"] <= date]
    if len(bars) >= 2 and bars[-1]["date"] == date:
        return bars[-2]["close"]
    return None


def stock_board_shape_line(date: str, code: str, name: str | None,
                           prev_close: float | None) -> str:
    """弹药 8：当日板型（TDX 5 分钟线机械判定）——首触/炸板波次/末封/一字，烂板回封=当日弱转强。
    fail-visible：昨收缺失/5 分钟棒缺失/未触板（与涨停人口矛盾=数据缺口）如实标注。"""
    try:
        if not prev_close or prev_close <= 0:
            return "板型：昨收缺失无法判定涨停价（fail-visible）"
        bars = [b for b in _intraday_bars(code) if b["date"] == date]
        if not bars:
            return "板型：当日 5 分钟棒缺失（fail-visible）"
        lp = round(prev_close * (1 + _limit_pct_of(code, name)), 2)
        tol = 1e-6
        touches = [b for b in bars if b["high"] >= lp - tol]
        if not touches:
            return "板型：当日未触板（与涨停人口矛盾，数据缺口 fail-visible）"
        first_touch = touches[0]["hm"]
        sealed_flags = [b["close"] >= lp - tol for b in bars]
        waves = 0
        for k in range(1, len(sealed_flags)):
            if sealed_flags[k - 1] and not sealed_flags[k]:
                waves += 1
        sealed_to_close = bool(sealed_flags[-1])
        last_seal = next((bars[k]["hm"] for k in range(len(bars) - 1, -1, -1)
                          if sealed_flags[k]), "--")
        one_word = bars[0]["open"] >= lp - tol and all(sealed_flags)
        if one_word:
            shape = "一字板"
        elif not sealed_to_close:
            shape = "触板未封/炸板收盘"
        elif waves == 0:
            shape = "秒板/硬板（一波封住）" if first_touch <= "10:30" else "一波封住（首触偏晚）"
        elif waves == 1:
            shape = "炸板回封（当日弱转强）"
        else:
            shape = "烂板（炸板≥2 次回封）"
        return (f"当日板型：首触 {first_touch} · 炸板 {waves} 次 · 末封 {last_seal}"
                f" · {'封板至收盘' if sealed_to_close else '收盘未封'} · 板型={shape}")
    except Exception as e:
        return f"板型：计算失败 {e}（fail-visible）"


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
    """v3 弹药叙事：盘面事实行（无情绪分）+ 个股解析 + THS 身位块 + 个股位置行（价格轴）+ 板序行（几天几板/断板反包）+ 当日板型行（炸板波次/回封）+ 板块地位块 + 热榜。"""
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
        stock_position_line(date, code),
        limitup_sequence_line(date, code, stock.get("name")),
        stock_board_shape_line(date, code, stock.get("name"), _prev_close_of_date(date, code)),
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


def _label_one(db, col, acc, token, date, code, stock, board, rank,
               include_stock_phase: bool = False):
    """单只个股打标一次 jev 调用；include_stock_phase=True 时题目集升级为五题合并同 call
    （QUESTIONS_STOCK_WITH_PHASE，2026-10-04 用户裁决），相位答案随主 doc 同落——共享 narrative
    输入，相位边际成本≈题干+答案。usage/latency 为五题整 call 实付口径（stockPhaseUsage 同值）。"""
    questions = QUESTIONS_STOCK_WITH_PHASE if include_stock_phase else QUESTIONS_STOCK
    narrative = build_pilot_narrative(db, date, code, stock, board, rank)
    env, ms = call_jev(acc, token, narrative, questions)
    parsed = parse_jev_response(env, ms)
    answers = parsed.get("answers") or {}
    doc = {"_id": f"{date}:{code}", "origin": "driver_label_jiuyan_v3_pilot", "tradingDate": date,
           "code": code, "name": stock.get("name"),
           "jiuyanContext": {"board": board, "day": stock.get("day"), "num": stock.get("num"),
                             "time": stock.get("time"), "inHotlist": rank is not None, "rank": rank},
           "status": "ok" if parsed["ok"] else "degraded",
           "narrative": narrative, "questionsRaw": questions,
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
    if include_stock_phase:
        # 相位答案随主 call 落档（字段与单题版 run_stock_phase_pilot 逐字段对齐，聚合层无感）；
        # 相位答案缺失时 Position=None（聚合层 no_data fail-visible 已处理，不整 call 降级）
        ans_p = answers.get("stock_phase_position") or {}
        doc.update({
            "stockPhasePosition": ans_p.get("choice"),
            "stockPhaseProbabilities": ans_p.get("probabilities"),
            "stockPhaseQuestionsRaw": QUESTIONS_STOCK_PHASE,
            "stockPhaseModel": parsed.get("model"),
            "stockPhaseUsage": parsed.get("usage"),
            "stockPhaseLatencyMs": ms,
            "stockPhaseErrorCode": parsed.get("errorCode"),
            "stockPhaseErrorDetail": parsed.get("errorDetail"),
            "stockPhaseComputedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return bool(parsed["ok"])


def run(start: str, end: str, dry_run: bool, token: str, acc: str, workers: int = 2,
        with_stock_phase: bool = False):
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
                                    entry["board"], ranks.get(code),
                                    include_stock_phase=with_stock_phase)
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
                                   "首板堆积、老周期高标出清，反弹在即反而是积极信号。"
                                   "特别注意：冰点是稀缺事件（全月仅 1-2 次）——判冰点必须同时满足「涨停家数掉出常态带（断层）」与「池内涨跌均衡（没人买也没人卖，非单边杀跌）」；"
                                   "跌停堆积+单边下跌+缩量大面的日子是杀跌退潮，不是冰点。只依据所给信息判断，不预测后市。",
                   "criteria": {
                       "ebb_early": "退潮初期/杀跌：涨停家数/最高板自近 10 日峰值回落的前 1-3 天，或跌停堆积+池内涨跌单边偏弱（跌比涨多、人在卖）+缩量大面，亏钱效应扩散中",
                       "ice_end": "冰点（退潮末期·断层日）：涨停家数掉出常态带（显著低于近 10 日日常水平）且池内涨跌均衡（涨跌比接近 1，没人买也没人卖），首板堆积、高标独苗或断板——反弹在即；此状态全月仅 1-2 次",
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
        ad = advdec_ratio(db, r["d"])
        ad_txt = f'{ad[3]}' if ad else "?"
        rows.append(f'{r["d"][5:]}|涨停{zt_txt}({delta})|跌停{die_txt}|炸板{r["rate"]}|回撤{dd_txt}|板{mb_txt}|涨跌比{ad_txt}')
    head = f'近{len(rows)}个交易日序列（日期|涨停(较昨日Δ)|跌停|炸板率|大幅回撤|最高板|池内涨跌比）：'
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


def run_stock_phase_pilot(db, dates: list[str], token: str, acc: str,
                          dry_run: bool = False, workers: int = 2) -> None:
    """个股相位分线试点（2026-10-04 用户裁决「先跑 9/30 看效果」）：单题补跑路径。

    与 run() 的 replace_one 整文档替换不同：对已有个股文档只 $set stockPhase* 字段
    （upsert=False），已定版四题标签与文档其余部分不动（全月代际一致不破）；
    缺个股文档的股票跳过并披露（不建平行集合）。判据冻结稿=QUESTIONS_STOCK_PHASE，
    同判据已判个股幂等跳过（防重复烧 token），判据变更（改门须点头）后自然重跑。
    """
    col = db["hotlist_jev_driver_labels"]
    n_ok = n_deg = n_skip = n_nodoc = 0
    tokens_used = 0
    for date in dates:
        pop = day_population(db, date)
        if not pop:
            print(f"[stock-phase] {date} 无韭研 final 文档，跳过（fail-visible）")
            continue
        items: dict[str, dict] = {}
        for entry in pop:
            code = _strip(entry["stock"].get("code"))
            items[code] = entry
        codes = list(items.keys())
        ranks = hotlist_ranks(db, date, codes)
        if dry_run:
            sample = items[codes[0]]
            narrative = build_pilot_narrative(db, date, codes[0], sample["stock"],
                                              sample["board"], ranks.get(codes[0]))
            print(f"[dry][stock-phase] {date} population={len(codes)} hotlistHit={len(ranks)} "
                  f"narrativeChars={len(narrative)}")
            print(narrative)
            continue

        def work(code):
            entry = items[code]
            done = col.find_one({"_id": f"{date}:{code}"},
                                {"stockPhasePosition": 1, "stockPhaseQuestionsRaw": 1})
            if done and done.get("stockPhasePosition") and \
                    done.get("stockPhaseQuestionsRaw") == QUESTIONS_STOCK_PHASE:
                return ("skip", 0)
            narrative = build_pilot_narrative(db, date, code, entry["stock"],
                                              entry["board"], ranks.get(code))
            env, ms = call_jev(acc, token, narrative, QUESTIONS_STOCK_PHASE)
            parsed = parse_jev_response(env, ms)
            answers = parsed.get("answers") or {}
            ans = answers.get("stock_phase_position") or {}
            u = parsed.get("usage") or {}
            used = int(u.get("input_tokens") or 0) + int(u.get("output_tokens") or 0)
            payload = {
                "stockPhasePosition": ans.get("choice"),
                "stockPhaseProbabilities": ans.get("probabilities"),
                "stockPhaseQuestionsRaw": QUESTIONS_STOCK_PHASE,
                "stockPhaseModel": parsed.get("model"),
                "stockPhaseUsage": parsed.get("usage"),
                "stockPhaseLatencyMs": ms,
                "stockPhaseErrorCode": parsed.get("errorCode"),
                "stockPhaseErrorDetail": parsed.get("errorDetail"),
                "stockPhaseComputedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            result = col.update_one({"_id": f"{date}:{code}", "status": "ok"},
                                    {"$set": payload}, upsert=False)
            if result.matched_count == 0:
                return ("nodoc", used)
            return ("ok" if parsed["ok"] else "degraded", used)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(work, codes))
        n_ok += sum(1 for s, _ in results if s == "ok")
        n_deg += sum(1 for s, _ in results if s == "degraded")
        n_skip += sum(1 for s, _ in results if s == "skip")
        n_nodoc += sum(1 for s, _ in results if s == "nodoc")
        tokens_used += sum(t for _, t in results)
        print(f"[stock-phase] {date} n={len(codes)} (cum ok={n_ok} degraded={n_deg} "
              f"skip={n_skip} noDoc={n_nodoc})")
    print("FINAL:", {"ok": n_ok, "degraded": n_deg, "skipped": n_skip,
                     "noDoc": n_nodoc, "tokens": tokens_used})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=False)
    ap.add_argument("--end", required=False)
    ap.add_argument("--phase-band-day", dest="phase_band_day", required=False,
                    help="日级相位哨兵：只对指定交易日跑一次盘面事实判档（盘后链步骤 5）")
    ap.add_argument("--cycle-stage-day", dest="cycle_stage_day", action="append", default=[],
                    help="情绪周期段位试点：指定交易日判游资周期段位（可多次传参）")
    ap.add_argument("--stock-phase-date", dest="stock_phase_date", required=False,
                    help="个股相位分线试点：对指定交易日已有个股文档单题补跑 stockPhase*（只 $set 不碰四题标签）")
    ap.add_argument("--stock-phase-month", dest="stock_phase_month", required=False,
                    help="个股相位分线月度回填（融合总纲 F2）：对月内全部交易日已有个股文档补跑——"
                         "烧 token（≈3-5 万/日合并口径），须经用户批准后手动执行，不挂自动链")
    ap.add_argument("--with-stock-phase", dest="with_stock_phase", action="store_true",
                    help="合并同 call（真合并）：相位题并入主 call 题目集，同一 narrative 五题一次调用"
                         "（增量边际≈题干+答案数百 tokens/只）——默认关；"
                         "排程经 JIUYAN_STOCK_PHASE_ENABLED=1 门控（用户批准成本后开启）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    tok = os.environ.get("JEV_CF_TOKEN") or ""
    assert tok, "需要 JEV_CF_TOKEN 环境变量"
    acc = os.environ.get("JEV_CF_ACCOUNT", "921cf15176f84c90ea49865334af32c6")
    if args.stock_phase_date:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        run_stock_phase_pilot(get_runtime_mongodb_database(), [args.stock_phase_date], tok, acc,
                              dry_run=args.dry_run, workers=args.workers)
    elif args.stock_phase_month:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        db = get_runtime_mongodb_database()
        # 日期轴=已有个股四题文档（与回填对象同源，review P2：此前用 sentiment EOD 轴会静默漏
        # 「final 有而 EOD 缺」的打标日）
        dates = sorted({str(d.get("tradingDate")) for d in db["hotlist_jev_driver_labels"].find(
            {"origin": {"$ne": "phase_band_daily"}, "status": "ok",
             "tradingDate": {"$regex": f"^{args.stock_phase_month}"}}, {"tradingDate": 1})})
        print(f"[stock-phase-month] {args.stock_phase_month} 共 {len(dates)} 个已打标交易日待补跑")
        run_stock_phase_pilot(db, dates, tok, acc, dry_run=args.dry_run, workers=args.workers)
    elif args.cycle_stage_day:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        run_cycle_stage_day(get_runtime_mongodb_database(), args.cycle_stage_day, tok, acc)
    elif args.phase_band_day:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        run_phase_band_day(get_runtime_mongodb_database(), [args.phase_band_day], tok, acc)
    else:
        assert args.start and args.end, "个股模式需要 --start/--end"
        # --with-stock-phase=真合并同 call（2026-10-04 用户裁决）：相位题并入主 call 题目集，
        # 同一 narrative 五题一次调用（边际成本≈题干+答案）；排程经 JIUYAN_STOCK_PHASE_ENABLED=1 门控
        run(args.start, args.end, args.dry_run, tok, acc, args.workers,
            with_stock_phase=args.with_stock_phase)
