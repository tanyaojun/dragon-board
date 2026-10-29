# -*- coding: utf-8 -*-
"""jev 涨停打标 runner（题目集 docs/hotlist-jev/jev-driver-label-v3-questionset.md，2026-10-03 收敛定版）。

生产集合 hotlist_jev_driver_labels（v2 集合已归档 data/backups 后退役，pilot 集合 rename 平移而来）。
架构（C 定版）：个股四题 + Q5 相位题日级独立调用（run_phase_band_day）。历代替换：v1/v2 runner 见 git 历史。差异：
  1) 题目五道（v3.1 三轴原文同题锚 + Q4 买盘逻辑 + Q5 相位强弱分线；判据代际
     v3.2/v3.3/v4.0 演进见 jev_driver_ammo.QUESTION_SET_VERSION_DRIVER 注释）；
  2) 弹药三新块全结构化直供（THS 身位块 / 板块地位块 / 分位盘面事实行）——不含规则情绪分（Q5 防锚定污染）。

用法（Git Bash，JEV_CF_TOKEN 取自 .env.local）：
  ./.venv/Scripts/python.exe -m backend.operations.jev_label_jiuyan \
      --start 2026-09-04 --end 2026-09-29 [--dry-run] [--workers 2]
  # 午盘槽位（12:30 调度投喂午盘名单，收盘链幂等跳过）：
  ./.venv/Scripts/python.exe -m backend.operations.jev_label_jiuyan \
      --start 2026-10-20 --end 2026-10-20 --slot midday --confirm-budget
"""
from __future__ import annotations

import argparse
import contextlib
import contextvars
import datetime
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import (
    AMMO_VERSION,
    DEFAULT_DATASET_ID,
    QUESTION_SET_VERSION_CYCLE,
    QUESTION_SET_VERSION_DRIVER,
    QUESTIONS_CYCLE,
    QUESTION_SET_VERSION_PHASE_BAND,
    QUESTIONS_PHASE,
    QUESTIONS_STOCK,
    QUESTIONS_STOCK_BUYSIDE,
    QUESTIONS_STOCK_BUYSIDE_WITH_PHASE,
    QUESTIONS_STOCK_PHASE,
    QUESTIONS_STOCK_WITH_PHASE,
    THS_KEYS,
    _limit_pct_of,
    _questions_hash,
    _strip,
    _usage_tokens,
    percentile_rank,
)
from backend.analysis.hotlist import jev_driver_ammo as ammo
from backend.analysis.hotlist import jev_carry_forward as carry_mod
from backend.analysis.hotlist.jev_carry_forward import (
    CARRY_KEYS,
    MAX_GAP_TRADING_DAYS,
    carry_decision,
    compress_narrative,
    expound_signature,
)
from backend.core.limit_rules import is_limit_down_pct, limit_ratio
from backend.operations import jiuyan_store
from backend.operations.market_dieban_pool import (
    FULL_MARKET_SOURCES,
    SOURCE_EM,
    SOURCE_POOL,
    SOURCE_SNAPSHOT,
    limit_down_count,
    reference_counts,
    source_label,
)
from backend.operations.market_dieban_tdx import DEFAULT_TAKE as _TDX_DEFAULT_TAKE
from backend.services.jev.jev_client import DEFAULT_ACCOUNT_ID, parse_jev_response
from backend.services.jev.jev_sentiment_compute import _dispatch_jev








# THS 身位缓存（IO 侧，键=(dataset, date)；批次D I14 自题集区拆回保留）
_THS_CACHE: dict[tuple[str, str], dict] = {}


def ths_positions(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, dict]:
    """(date) → code → THS 身位（连板梯队/首封时间/板块/主力净额），按 (dataset, 日) 缓存。"""
    cache_key = (dataset_id, date)
    if cache_key in _THS_CACHE:
        return _THS_CACHE[cache_key]
    # 批次B I8：带 datasetId/type 并取最新帧（同槽多 snapshotId 时结果确定）
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"limitSummary.thsPools.pools": 1},
        sort=[("timestamp", -1), ("snapshotId", -1)])
    out: dict[str, dict] = {}
    for key in THS_KEYS:
        pool = (((f or {}).get("limitSummary") or {}).get("thsPools") or {}).get("pools", {}).get(key) or {}
        for it in pool.get("items") or []:
            out[_strip(it.get("stock_code"))] = {
                "ladder": key, "continueDay": it.get("continue_day"),
                "firstSeal": it.get("limit_up_time"), "industry": it.get("industry_block"),
                "mainNet": it.get("main_net_amount")}
    _THS_CACHE[cache_key] = out
    return out


def dieban_count(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> int | None:
    """跌停家数（收盘口径，pctChange 判定线自算——帧内无现成字段，口径如实标注）。

    2026-10-05 二次修正（用户裁决「阈值公共函数，禁硬编码副本」）：
    唯一权威 = core/limit_rules.is_limit_down_pct（ratio×100 − 0.2pp → -9.8/-19.8/-29.8）；
    并撤销批次B 的 ST ±5% 特判——2026-09 新规主板 ST 亦 ±10%，全市场无 ST 特判。
    容差 -0.2pp：tick 取整致真实跌停 pctChange 有 ±0.2pp 浮动（pct-only 检测的已知边界）。
    批次B I8：带 datasetId。
    """
    seen: set[str] = set()
    n = 0
    for r in db["snapshot_stock_rows"].find(
            {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00",
             "pctChange": {"$exists": True, "$ne": None}}, {"code": 1, "pctChange": 1}):
        code = str(r.get("code") or "")
        if code in seen:
            continue
        seen.add(code)
        if is_limit_down_pct(r.get("pctChange"), code):
            n += 1
    return n if seen else None


# 盘面事实行缓存（IO 侧，键=(dataset, date)；批次D I14 恢复）
_FACTS_CACHE: dict[tuple[str, str], str] = {}
_ADVDEC_CACHE: dict[tuple[str, str], tuple] = {}


def advdec_ratio(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> tuple | None:
    """池内涨/跌/平家数与涨跌比（采集池口径，15:00 收盘）——区分「不交易」与「杀跌」的特征。"""
    cache_key = (dataset_id, date)
    if cache_key in _ADVDEC_CACHE:
        return _ADVDEC_CACHE[cache_key]
    up = down = flat = 0
    seen = 0
    for r in db["snapshot_stock_rows"].find(
            {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00",
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
    _ADVDEC_CACHE[cache_key] = result
    return result


def _jiuyan_days_boards(stock: dict) -> tuple[int | None, int | None]:
    """韭研 num「N天M板」解析（跨度天数 N，区间板数 M）；无法解析 (None, None) 宁缺毋猜。

    N==M = 纯连板（8天8板）；N>M = 中间有断板（10天8板）。
    2026-10-16 口径修正（预登记 jev-relay-caliber-fix-preregistration.md §2.2）：M/N 是
    **区间高度**（区间标注用，龙序/龙头选择仍按 M），**连板语义**（最高板/梯队/连板中）
    一律取 jiuyan_streak_map 真连板，不再拿 M 冒充——澳弘电子 19天11板（10-14 已炸板）
    真连板=1，旧口径写成最高 11 板并进三板+ 桶。
    """
    num = str(stock.get("num") or "").strip()
    if not num:
        return None, None
    import re
    m = re.match(r"^(\d+)天(\d+)板", num)
    if not m:
        return None, None
    days = int(m.group(1))
    boards = int(m.group(2))
    return (days if days > 0 else None), (boards if boards > 0 else None)


def expound_reason(stock: dict) -> str | None:
    """韭研「异动解析」首行 = 涨停原因（2026-10-20 用户需求：涨停复盘加【原因】列）。

    实测（603278 大业股份 10-16/10-19/10-20 三天）：`expound` 首行就是题材归因短句
    「人形机器人（金属腱绳）+商业航天+光伏+轮胎」，次行起才是 1/2/3 逐条核实段落，
    因此取**第一条非空行原样输出**，不做启发式改写、不裁剪长度（前端按列宽截断+title 展示全文）。
    `expound` 缺失时才回退文档内同义字段 `reason`（历史 schema 有此键，实测恒为 None）；
    两者皆空 → None（前端显示 '-'，不伪造原因，AGENTS §4.0）。
    """
    for line in str(stock.get("expound") or "").splitlines():
        text = line.strip()
        if text:
            return text
    fallback = str(stock.get("reason") or "").strip()
    return fallback or None


def _range_height_text(entry: dict) -> str:
    """区间高度文案「名 N天M板」（与 relay_page heightText 同规：days 缺失回落 M板，
    boards≤1/缺失=首板，不伪造天数）。entry 需带 name/boards/days。"""
    name = entry.get("name") or entry.get("code") or "?"
    boards, days = entry.get("boards"), entry.get("days")
    if not boards or boards <= 1:
        return f"{name} 首板"
    return f"{name} {days}天{boards}板" if days else f"{name} {boards}板"


def dragon_rows(stocks: list[dict], top: int = 3,
                streaks: dict[str, int | None] | None = None) -> list[dict]:
    """板块龙一/二/三排序，单一事实源（relay 题材梯队表与 limitup 读口「领涨」共用）。

    龙序=高度优先/封板时间次之：板数（num「N天M板」的 M）降序，同板数按封板时间
    升序；num 缺失=韭研首板口径（不标 num）视作无板数垫在同板数之后；
    time 缺失排序垫底、输出 None（前端显示 ?）。跨板块重复归属按原样各排各的
    （与 relay 题材梯队表 _boards_of 分组口径一致，不做跨板块去重）。

    code 随行输出（2026-10-15 增补）：涨停复盘「领涨」列据此把个股匹配到**自己**的
    龙序，只显示「龙一/龙二/龙三」，不再把板块三个龙* 全塞进一格； relay 梯队表
    只消费 name/boards/time，新增字段对其无影响。code 与 jiuyan_board_info /
    _jiuyan_ladder 同规取末 6 位（韭研 code 可能带交易所前缀），前端才能与行 code 对上。

    2026-10-16 口径修正：输出补 days（跨度 N）与 streak（真连板；streaks={code: streak}
    传入时按 code 挂载，未传=None）。龙序仍按区间高度 M（14天10板 本就是该板块最显
    高位股），但「连板」语义由消费方随行展示 streak，不再拿 M 冒充。
    """
    ranked = sorted(stocks,
                    key=lambda s: (-(_jiuyan_board_count(s) or 0), str(s.get("time") or "99:99")))
    out: list[dict] = []
    for i, s in enumerate(ranked[:top]):
        code = (str(c)[-6:] if (c := s.get("code")) else None)
        days, boards = _jiuyan_days_boards(s)
        out.append({"role": f"龙{'一二三'[i]}",
                    "code": code,
                    "name": s.get("name"),
                    "boards": boards,
                    "days": days,
                    "streak": (streaks or {}).get(code) if code else None,
                    "time": str(s["time"])[:5] if s.get("time") else None})
    return out


def jiuyan_board_dragons(db, date: str, top: int = 3,
                         allow_midday_fallback: bool = False) -> dict[str, list[dict]]:
    """韭研 final 各板块龙一/二/三：{板块名: [dragon_rows]}；final 缺失/无个股 → {}。

    调用方 fail-visible：空 map 时「领涨」列缺省，降级原因由既有
    boardJoinDegraded=jiuyan_final_missing 旗标注记，不在此重复。
    allow_midday_fallback（2026-10-21）：final 缺失时回退 `{date}:midday` 午盘名单——
    与 jiuyan_board_info 同参同口径（盘中「领涨」列同病同修），口径注记由 board_info
    的 meta（jiuyanSlot/middayFallbackUsed）承担，本函数不重复标记。
    """
    doc = db["jiuyan_action"].find_one(
        {"_id": f"{date}:final"}, {"fields.name": 1, "fields.stocks": 1})
    if allow_midday_fallback and not any(
            f.get("stocks") for f in (doc or {}).get("fields") or []):
        doc = db["jiuyan_action"].find_one(
            {"_id": f"{date}:{SLOT_MIDDAY}"}, {"fields.name": 1, "fields.stocks": 1})
    out: dict[str, list[dict]] = {}
    for field in (doc or {}).get("fields") or []:
        name = field.get("name")
        if name and field.get("stocks"):
            out[str(name)] = dragon_rows(field["stocks"], top)
    return out


def _jiuyan_board_count(stock: dict) -> int | None:
    """韭研 num 字段「N天M板」解析出真实板数 M（2026-10-10 口径修正）。

    实测：day 字段存的是 N（跨度天数）而非板数——「9天9板」两者巧合相等，
    「16天8板」day=16 但真实 8 板；与 THS maxBoard 对齐验证。num 无法解析
    返回 None（宁缺毋猜）。"""
    return _jiuyan_days_boards(stock)[1]


def _ladder_bucket(boards: int | None) -> str:
    """连板高度 → 梯队桶（与 THS_KEYS 对齐：one(≤1)/two/three/four/high(≥5)）。"""
    if boards is None or boards <= 1:
        return "one"
    if boards == 2:
        return "two"
    if boards == 3:
        return "three"
    if boards == 4:
        return "four"
    return "high"


def _jiuyan_ladder(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict | None:
    """韭研主源连板梯队（2026-10-16 口径修正：**真连板**分桶，只桶封板股）。

    口径（预登记 docs/hotlist-jev/jev-relay-caliber-fix-preregistration.md §2.1）：
    - 板数 = jiuyan_streak_map 真连板（N==M 直取 M；N>M 回溯；不可算 → 不入桶只披露）；
    - 只桶今日真实封板股（韭研触板 − THS 炸板池二分）；炸板/触板未封不进涨停梯队
      （2026-10-10 旧口径桶的是触板池，炸板股被计成首板——10-15 审计 6 只，问题 #4/#7）；
    - THS 炸板池缺失日 → 回退触板池按 M 分桶，_caliber="touch_range"（旧口径，叙事披露）；
    - final 缺失/无个股 → None（回退 THS，不伪造零梯队）。
    """
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields.stocks": 1})
    fields = (doc or {}).get("fields") or []
    if not any(field.get("stocks") for field in fields):
        return None
    buckets = {k: 0 for k in THS_KEYS}
    info, meta = jiuyan_board_info(db, date)
    if not meta.get("thsPoolFound"):
        # 旧口径回退：触板池按 M 分桶（炸板股会混入），显式标注供叙事披露
        unmarked = 0
        for i in info.values():
            if i.get("boards") is None:
                unmarked += 1
            buckets[_ladder_bucket(i.get("boards"))] += 1
        buckets.update({"_poolTotal": len(info), "_caliber": "touch_range",
                        "_dayUnmarked": unmarked, "_dayUnmarkedPrev": None,
                        "_heightUnknown": None})
        return buckets
    streaks = jiuyan_streak_map(db, date, dataset_id)
    prev_dates = trading_dates_before(db, date, 1)
    prev_sealed: set[str] | None = None
    prev_touch: set[str] = set()
    if prev_dates:
        prev_sealed = _sealed_codes(db, prev_dates[-1], dataset_id)
        prev_doc = db["jiuyan_action"].find_one(
            {"_id": f"{prev_dates[-1]}:final"}, {"fields.stocks.code": 1})
        for field in (prev_doc or {}).get("fields") or []:
            for stock in field.get("stocks") or []:
                if stock.get("code"):
                    prev_touch.add(str(stock["code"])[-6:])
    # 昨日封板集合不可得（THS 池缺失）时回退触板集合，保持旧口径的保守披露
    prev_limit = prev_sealed if prev_sealed is not None else prev_touch
    total = unmarked = unmarked_prev = unknown = 0
    for code, i in info.items():
        if i.get("zhaban"):
            continue  # 今日炸板 → 非涨停，不进梯队
        s = streaks.get(code)
        if s is None:
            unknown += 1  # 高度不可算（回溯撞 THS 池缺日）：不按 M 伪算，只披露
            continue
        if i.get("boards") is None:
            unmarked += 1
            if code in prev_limit:
                unmarked_prev += 1  # 真连板被漏标（num 空且昨日封板）：高度未知，不入桶
                continue
        buckets[_ladder_bucket(s)] += 1
        total += 1
    buckets.update({"_poolTotal": total, "_caliber": "streak", "_dayUnmarked": unmarked,
                    "_dayUnmarkedPrev": unmarked_prev, "_heightUnknown": unknown})
    return buckets


def _ths_failed_items(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> tuple[dict[str, dict], bool]:
    """THS 15:00 帧炸板池 code→item（2026-10-11 触板二分用，方案A）。

    item 含 open_num（开板次数）/change_rate 等，炸板卡「反复开板」消费；
    返回 (items, found)：found=False = 帧缺失/池降级，调用方必须 fail-visible 结构化降级，
    不得把触板名单静默当涨停名单；failed 池为空且 ok=True 是合法状态（当日无炸板）。
    2026-10-16：补 dataset_id 参数（默认不变），供 relay 侧同口径委托，消双实现。
    """
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date,
         "slotTime": "15:00"},
        {"limitSummary.thsPools": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    tp = ((f or {}).get("limitSummary") or {}).get("thsPools") or {}
    if not tp or not tp.get("ok") or tp.get("degraded"):
        return {}, False
    items = (tp.get("pools") or {}).get("failed", {}).get("items") or []
    return {str(i.get("code") or "")[-6:]: i for i in items if i.get("code")}, True


def _ths_pool_counts(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> tuple[dict | None, bool]:
    """THS 池**家数级**回退（旧采集 schema，2026-10-17 IE 修复 F1）。

    2026-07-30..09-23 共 16 天的 15:00 帧存旧形态：只有 `limitSummary.thsPools.poolCounts`
    （failed/rushing/drawdown 家数）+ `maxDrawdown/avgDrawdown`，**没有** `pools.*.items`（个股）。
    读口原实现只认 items → 这些天整段写「不可算」，把同帧已有的家数一并丢弃
    （AGENTS §4.0「有可用数据就必须展示可计算部分」）。本函数供调用方做同源家数级降级。

    返回 (counts, found)：found=False = 连家数都没有（帧缺失/池未拉取/占位零降级）。
    口径：`poolCounts.failed` 与 `len(pools.failed.items)` 同为 THS 炸板池家数（同源字段）。
    2026-10-18 review P1-3：`degraded:true` 且三池家数全 0 = 上游整池拉取失败的**占位零**，
    found=False（不得输出「炸板 0 家」，§4.0）；只要任一池非零则视为合法读数（部分池失败可用）。
    """
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date,
         "slotTime": "15:00"},
        {"limitSummary.thsPools": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    tp = ((f or {}).get("limitSummary") or {}).get("thsPools") or {}
    counts = tp.get("poolCounts")
    if not isinstance(counts, dict) or not counts:
        return None, False
    # 占位零判别（2026-10-18 review P1-3，§4.0）：旧采集 schema 在 THS 整池拉取失败时写
    # `degraded:true` + **poolCounts 全 0**（`src/services/DragonBreathAnalyzer.ts` 的
    # `degraded = unavailable || ...` 分支）。这些 0 是占位，不是「炸板 0 家」——直接当读数
    # 会把「取不到」写成「炸板 0 家」（实测库中存在 35 帧此种形态）。
    # 保留合法降级：只要**任一**池有非零家数，说明本次确实取到了池（部分池失败可接受）。
    if tp.get("degraded") and not any(
            counts.get(k) for k in ("failed", "rushing", "drawdown")):
        return None, False
    return {"failed": counts.get("failed"), "rushing": counts.get("rushing"),
            "drawdown": counts.get("drawdown"), "maxDrawdown": tp.get("maxDrawdown"),
            "avgDrawdown": tp.get("avgDrawdown"), "source": tp.get("source")}, True


def _ths_failed_codes(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> tuple[set[str], bool]:
    items, found = _ths_failed_items(db, date, dataset_id)
    return set(items), found


_BSE_CODE_PREFIXES = ("92", "43", "83", "87")


def _official_exclude(stock_name: Any, code: str) -> str | None:
    """官方简图剔除口径（footer：不含 st 和未开板新股）：ST 或北交所 → 排除原因，否则 None。"""
    if "ST" in str(stock_name or "").upper():
        return "st"
    if code[:2] in _BSE_CODE_PREFIXES:
        return "bse"
    return None


def _reseal_verdict(date: str, code: str) -> str:
    """THS 炸板池命中股的 TDX 日线收盘复核（尾盘回封补证，2026-10-29 光洋股份实测）。

    THS 15:00 帧的炸板池是**快照时点口径**：尾盘集合竞价（14:57-15:00）回封的股在帧内
    仍带 LIMIT_FAILED 标（光洋股份 10-29 latest=20.82 差 1 tick，15:00:00 集合竞价回封
    20.83，韭研 num=4天4板/time=15:00:00 与 TDX 日线收盘 +9.98% 双自证），照搬会把真
    涨停错杀成炸板。收盘价权威补证：当日收盘落在涨停价（ammo.closed_at_limit 同一
    板籍阈值）→ sealed，炸板池判定被回封打穿。

    返回 _bar_verdict 口径：sealed=回封（不标 zhaban）；broken/suspended/unknown=
    维持炸板判定——日线不可用时行为与旧版完全一致（宁维持原口径，不让数据洞改判）。
    """
    try:
        bars = _daily_bars(code)
    except Exception:
        return "unknown"
    if not bars:
        return "unknown"
    try:
        adj = _adj_prev_series(date, code, bars)
    except Exception:
        adj = {}
    return _bar_verdict(code, date, bars, adj)


def jiuyan_board_info(db, date: str,
                      allow_midday_fallback: bool = False) -> tuple[dict[str, dict], dict]:
    """韭研个股高度/封板时间/板块 join + 触板二分（2026-10-11 方案A，用户裁决）。

    韭研 final fields.stocks = 盘中曾触板名单（封板+炸板，10-09 实测 82=69涨停+13炸板），
    与官方简图「涨停家数」差炸板股；doc 内无可靠封板标记（time 空≠炸板），必须借
    THS 15:00 炸板池二分：
    - zhaban=True：在今日炸板池 → 非涨停股（断板/触板未封），不进涨停口径；
      openNum=THS 开板次数（open_num，None 不透传）随 zhaban 附带；
    - zhabanResealed=True：在今日炸板池但 TDX 日线证实尾盘回封（2026-10-29 光洋股份）
      → 收盘价权威补证，不标 zhaban（按涨停计）；日线不可用 → 维持 zhaban（同旧版）；
    - excluded：'st'|'bse'（官方简图不计入涨停家数的 5 只差额，10-09 实测 3 ST + 2 北交所）；
    - boardUnmarked=True：num 空且昨日在「昨日涨停池」（昨日触板-昨日炸板）→ 真漏标连板；
      昨日炸板股今日涨停=首板，不得误标（10-09 金健米业/东亚药业教训）；
    - 同 code 多板块取首现；boards=_jiuyan_board_count(num「N天M板」的 M)，None=宁缺毋猜。
    meta = {jiuyanFinalFound, prevPoolFound, thsPoolFound, prevThsPoolFound}：
    任一池缺失时二分不可用（boardUnmarked/zhaban 缺席），调用方必须结构化降级。

    allow_midday_fallback（2026-10-21 用户报障：盘中涨停复盘无封板时间/原因/领涨）：
    final 缺失时回退读 `{date}:midday` 午盘名单（12:30 投喂槽）——盘中涨停复盘页的
    时间/原因/板块/高度全部来自本 join，不回退则盘中四列恒空。回退是**显式口径**：
    meta 补 jiuyanSlot（实际取数槽位）与 middayFallbackUsed=True，调用方必须把
    「午盘名单口径」透传展示，不得冒充收盘口径；默认 False，EOD 消费方零变化。
    """
    doc = db["jiuyan_action"].find_one(
        {"_id": f"{date}:final"},
        {"fields.stocks.code": 1, "fields.stocks.num": 1, "fields.stocks.time": 1,
         "fields.stocks.name": 1, "fields.stocks.expound": 1, "fields.stocks.reason": 1,
         "fields.name": 1, "fetchedAt": 1})
    fields = (doc or {}).get("fields") or []
    final_found = any(field.get("stocks") for field in fields)
    slot_used = SLOT_FINAL
    midday_fallback_used = False
    if not final_found and allow_midday_fallback:
        doc = db["jiuyan_action"].find_one(
            {"_id": f"{date}:{SLOT_MIDDAY}"},
            {"fields.stocks.code": 1, "fields.stocks.num": 1, "fields.stocks.time": 1,
             "fields.stocks.name": 1, "fields.stocks.expound": 1, "fields.stocks.reason": 1,
             "fields.name": 1, "fetchedAt": 1})
        fields = (doc or {}).get("fields") or []
        midday_fallback_used = any(field.get("stocks") for field in fields)
        if midday_fallback_used:
            slot_used = SLOT_MIDDAY
    failed_today, ths_found = _ths_failed_items(db, date)
    prev_dates = trading_dates_before(db, date, 1)
    prev_sealed: set[str] = set()
    prev_ths_found: bool | None = None
    if prev_dates:
        prev_doc = db["jiuyan_action"].find_one(
            {"_id": f"{prev_dates[-1]}:final"}, {"fields.stocks.code": 1})
        prev_touch = {str(s.get("code") or "")[-6:]
                      for field in (prev_doc or {}).get("fields") or []
                      for s in field.get("stocks") or [] if s.get("code")}
        prev_failed, prev_ths_found = _ths_failed_codes(db, prev_dates[-1])
        # 昨日炸板池缺失 → prev_sealed 不可信，置空（宁漏标不误标，meta 显式降级）
        prev_sealed = (prev_touch - prev_failed) if prev_ths_found else set()
    out: dict[str, dict] = {}
    for field in fields:
        for stock in field.get("stocks") or []:
            code = str(stock.get("code") or "")[-6:]
            if code and code not in out:
                days, boards = _jiuyan_days_boards(stock)
                info = {"boards": boards, "days": days, "limitUpTime": stock.get("time"),
                        "boardName": field.get("name"),
                        # 涨停复盘【原因】列（2026-10-20）：异动解析首行，缺失 None 不伪造
                        "reason": expound_reason(stock)}
                if ths_found and code in failed_today:
                    if _reseal_verdict(date, code) == "sealed":
                        # 尾盘集合竞价回封（2026-10-29 光洋股份实测）：THS 15:00 帧炸板池
                        # 是快照时点口径，会被收盘前最后一笔回封打穿。收盘价权威补证 →
                        # 不进炸板口径，只标 zhabanResealed 注记（fail-visible：不静默
                        # 吞掉炸板池命中事实）；openNum 对回封股无炸板卡语义，不透传。
                        info["zhabanResealed"] = True
                    else:
                        info["zhaban"] = True
                        if failed_today[code].get("open_num") is not None:
                            info["openNum"] = failed_today[code]["open_num"]
                excl = _official_exclude(stock.get("name"), code)
                if excl:
                    info["excluded"] = excl
                if boards is None and prev_ths_found and code in prev_sealed:
                    info["boardUnmarked"] = True
                out[code] = info
    meta = {"jiuyanFinalFound": final_found, "prevPoolFound": bool(prev_dates),
            "thsPoolFound": ths_found, "prevThsPoolFound": prev_ths_found,
            # 取数槽位（2026-10-21）：middayFallbackUsed=True = final 缺失、午盘名单兜底
            # （盘中涨停复盘口径注记，调用方必须透传展示，不冒充收盘）；jiuyanSlot=实际槽位
            "jiuyanSlot": slot_used, "middayFallbackUsed": midday_fallback_used,
            # THS 炸板池总数（含韭研未收录股）：前端炸板卡注记「榜外」差额，fail-visible
            "thsZhabanTotal": len(failed_today) if ths_found else None,
            # 源文档版本戳（2026-10-23 事故）：final 被重采覆写后，进程内缓存键据此换代，
            # 否则长驻进程（8000）会永选命中旧名单算出的真连板/事实行
            "sourceFetchedAt": repr((doc or {}).get("fetchedAt"))}
    return out, meta


def _touch_codes(db, date: str) -> set[str] | None:
    """date 当日韭研触板名单原样（封板+炸板，不减 THS 炸板池）；final 缺失 → None。

    与 `_sealed_codes` 同源不同口径，存在的唯一理由是回答一个关键问题：**该股当日
    到底有没有交易**。停牌日不可能出现在触板名单里，所以「TDX 日线缺棒 + 名字在
    名单内」= TDX 数据洞而非停牌（002860 09-22~10-13 十日无棒同款）——按停牌跳过
    续算会把断板日算成连板日、虚报高度，正是本次要修的病族反向。
    """
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields.stocks.code": 1})
    fields = (doc or {}).get("fields") or []
    if not any(field.get("stocks") for field in fields):
        return None
    return {str(s.get("code") or "")[-6:]
            for field in fields for s in field.get("stocks") or [] if s.get("code")}


def _sealed_codes(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> set[str] | None:
    """date 当日真实封板集合（韭研触板 − THS 炸板池二分，与 jiuyan_board_info 同口径）。

    韱研 final 缺失或 THS 池缺失 → None（不可验证，调用方宁缺毋猜，不得把炸板当封板）。
    2026-10-16：补 dataset_id 参数（默认不变），relay 侧同口径函数改委托本函数。"""
    touch = _touch_codes(db, date)
    if touch is None:
        return None
    failed, found = _ths_failed_codes(db, date)
    if not found:
        return None
    return touch - failed


def _bar_verdict(code: str, date: str, bars: list[dict],
                 adj: dict[str, float]) -> str:
    """该股 date 日的 TDX 日线独立判定，返回值 ∈ {sealed, broken, suspended, unknown}。

    封板链回溯的兜底信号（池二分覆盖不到的两个歧义场景）：
    - sealed：收盘落在涨停价 → 封板到收盘（与 ammo.closed_at_limit 同一板籍阈值）；
    - broken：有交易但未收在涨停价 → 断板（炸板/触板未封对连板同义）；
    - suspended：已覆段内无棒 → 停牌，**该日不是交易日、不构成断板**（2026-10-16 用户裁决）；
    - unknown：无前棒可判 / 日期早于最早可用棒 → 不可验（调用方宁缺毋猜）。

    bars/adj 由调用方按股预计算（_daily_bars + _adj_prev_series），避免逐日重取。
    """
    idx = next((i for i, b in enumerate(bars) if b["date"] == date), None)
    if idx is None:
        # 落在已覆段内却无棒 = 停牌；早于最早可用棒 = 回溯越界，不可验
        # （不假设 bars 有序：取 min/max，_daily_bars 升序但调用方不该被隐性契约咬）
        if bars and min(b["date"] for b in bars) < date <= max(b["date"] for b in bars):
            return "suspended"
        return "unknown"
    if idx == 0:
        return "unknown"          # 无前棒，判不出涨停
    prev = adj.get(date) or bars[idx - 1]["close"]
    return "sealed" if ammo.closed_at_limit(code, bars[idx]["close"], prev) else "broken"


def day_status_of(code: str, date: str, *, sealed: set[str] | None,
                  touch: set[str] | None, bars: list[dict] | None,
                  adj: dict[str, float] | None = None) -> str:
    """该股 date 日接力状态（连板口径单一事实源，2026-10-16 v4 抽取）。

    返回值 ∈ {sealed, broken, suspended, unknown}。池权威 + 日线补洞（用户裁决
    「停牌不算断板、跳过续算」），决策表：

    | 池 sealed（None=池缺失） | TDX 日线 | 触板名单 touch | 判定 |
    |---|---|---|---|
    | 含 code | — | — | sealed（池为既定权威） |
    | 不含 code | 无棒 | 不含 code | suspended（停牌跳过） |
    | 不含 code | 无棒 | 含 code | unknown（TDX 数据洞，非停牌） |
    | 不含 code | 有棒 | — | broken（断板） |
    | None | 无棒 | 不含 code | suspended |
    | None | 无棒 | 含 code | unknown |
    | None | 收涨停 | — | sealed（日线补证） |
    | None | 有棒未封 | — | broken |
    | None | 日线整体不可用 | — | unknown（宁缺毋猜，不让步为停牌） |

    消费方（禁双实现）：`jiuyan_consecutive_streaks` 真连板回溯、
    `jev_relay_index` 三日晋级链 / 晋级断板 / 高位股多日轨迹（停牌股既不进晋级
    也不进断板集合）。
    """
    if sealed is not None and code in sealed:
        return "sealed"
    verdict = _bar_verdict(code, date, bars, adj or {}) if bars else "unknown"
    if verdict == "suspended":
        # 无棒：停牌？还是 TDX 数据洞（当日确实交易过）？触板名单在册=数据洞，不可验
        return "unknown" if (touch is not None and code in touch) else "suspended"
    if sealed is None:
        return verdict            # 池缺失日走日线补证：sealed / broken / unknown
    return "broken"              # 池权威说未封且日线无停牌佐证 → 断板


def jiuyan_consecutive_streaks(db, date: str, targets: dict[str, int],
                               today_sealed: set[str] | None) -> dict[str, int | None]:
    """断板股真实连续高度（连板口径，2026-10-13 用户需求）：逐交易日回溯封板链。

    targets={code: 区间板数 M}；today_sealed=今日封板集合（None=今日不可二分，全返 None）。
    连续高度=今日起往前连续封板的交易日数，封顶 M（连续高度不可能超区间总板数）；
    任一历史日既不能由池证实也不能由日线证实 → None（宁缺毋猜）。
    消费方：涨停复盘 limitup-labels（board join 透传 streak）；原「热榜行情
    quotes-review」页面已于 2026-10-29 随页删除（消费链已移除，函数保留）。

    2026-10-16 停牌分辨（用户裁决「不算断板，跳过续算」）：**停牌日不是交易日、
    不构成断板**。600825 新华传媒 14天11板，10-13/14/15 上交所停牌（TDX 日线该三日
    无棒），韭研/THS 池回溯里「昨日不在池」与「昨日炸板」完全同形，旧口径据此把真连板
    11 误判成 1，连带最高板/梯队/首板占比/ladder_health 全错。

    池权威、日线补洞的分工（逐日决策表）：
    | 池（_sealed_codes）        | TDX 日线            | 判定                       |
    | 封板                      | —                  | 连板 +1（池为既定权威）      |
    | 未封                      | 已覆段内无棒        | 停牌 → 跳过（不算断板）      |
    | 未封                      | 有棒/无日线可用     | 断板 → 链终止               |
    | 缺失（炸板池缺失日）       | 已覆段内无棒        | 停牌 → 跳过                 |
    | 缺失                      | 有棒且收在涨停价    | 封板 → +1（日线补证）        |
    | 缺失                      | 有棒未收在涨停价    | 断板 → 链终止               |
    | 缺失                      | 无日线可用          | 不可验 → None（不按 M 伪算） |
    600825 链上的 2026-09-23 正是炸板池缺失日，只靠池会在那里整链不可验、最高板退回 4 板。
    TDX 日线不可用（客户端挂/北交所 920xxx 不覆盖）时不让步到「当停牌」——那正是要修的 bug。

    两条边界（2026-10-16 code review 补，均有测试锁定）：
    - **无棒 ≠ 一律停牌**：该日韭研触板名单里**有**这只股 = 当日确实交易过，TDX 缺棒
      是数据洞。按停牌跳过会把断板日算成连板日、虚报高度 → 不可验返 None。
    - **回溯窗耗尽 ≠ 连板数**：所需步数 = M + 窗内停牌日数，可能超过窗口上限；此时
      streak 是被截断的偏小值，返回它会与板序行（无帽实测）自相矛盾 → 不可验返 None。
    """
    if today_sealed is None:
        return {code: None for code in targets}
    # 回溯窗取固定上限而非 max(M)：停牌日不推进连板数，所需步数 = M + 窗内停牌日数
    # （600825 M=11 实需回溯 14 个交易日），按 M 定窗会把链起点截在窗外、把 11 板误判
    # 成 1 板。上限与 _daily_bars 的 60 棒窗口对齐——再往前 TDX 已无棒，停牌不可验。
    prev_dates = list(reversed(trading_dates_before(db, date, _STREAK_WALK_MAX_DATES)))
    sealed_cache: dict[str, set[str] | None] = {}
    touch_cache: dict[str, set[str] | None] = {}

    def sealed_set(d: str) -> set[str] | None:
        if d not in sealed_cache:
            sealed_cache[d] = _sealed_codes(db, d)
        return sealed_cache[d]

    def touch_set(d: str) -> set[str] | None:
        if d not in touch_cache:
            touch_cache[d] = _touch_codes(db, d)
        return touch_cache[d]

    out: dict[str, int | None] = {}
    for code, m in targets.items():
        if code not in today_sealed:
            out[code] = None  # 今日未封板 → 无「至今日」连续高度
            continue
        bars = _daily_bars(code)
        adj = _adj_prev_series(date, code, bars) if bars else {}
        streak = 1  # 今日已封
        verifiable = True
        for d in prev_dates:
            if streak >= m:
                break  # 封顶：连续高度不可能超区间总板数
            # 池权威 + 日线补洞的唯一判定入口（day_status_of，禁双实现；行为与旧内联逻辑等价）
            st = day_status_of(code, d, sealed=sealed_set(d), touch=touch_set(d),
                               bars=bars, adj=adj)
            if st == "sealed":
                streak += 1          # 池证实封板（池可用时以池为既定权威）/ 池缺失日线补证
                continue
            if st == "suspended":
                continue             # 停牌日不是交易日，不构成断板，跳过续算
            if st == "broken":
                break                # 断板，链终点
            verifiable = False       # unknown（TDX 数据洞/无日线可用）：不可验，宁缺毋猜
            break
        else:
            # 回溯窗耗尽。streak == m 时链已在窗口内走完（今日 + m-1 个已证封板日），
            # 是合法完整链；只有 streak < m 才是被窗口截断的偏小值——返回它会与同段板序行
            # （无帽实测）给出两个连板数，也违背本函数「宁缺毋猜」的契约 → 不可算。
            if streak < m:
                verifiable = False
        out[code] = min(streak, m) if verifiable else None
    return out


# 真连板缓存（IO 侧，键=(dataset, date)；盘后批量语义与 _FACTS_CACHE 同款）
_STREAK_CACHE: dict[tuple[str, str], dict[str, int | None]] = {}

# 封板链回溯窗上限（交易日数）。停牌日不推进连板数，回溯步数 = M + 窗内停牌日数，
# 按 max(M) 定窗会截断链起点（600825 M=11 实需 14 步）；取固定上限并与 _daily_bars
# 的 60 棒窗口对齐——再往前 TDX 已无棒，停牌不可验（宁缺毋猜返 None）。
_STREAK_WALK_MAX_DATES = 60


def jiuyan_streak_map(db, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                      allow_midday_fallback: bool = False) -> dict[str, int | None]:
    """当日触板池每股真实连板高度（连板口径单一事实源，2026-10-16 口径修正）。

    审计背景（docs/hotlist-jev/jev-relay-caliber-fix-preregistration.md §1）：区间板数 M
    （韭研 num「N天M板」的 M）被当连板数用——澳弘电子 19天11板（10-14 已炸板）真连板=1，
    却写成最高 11 板并进三板+ 桶；同花顺 limit_up_pool 的 continue_day 同病（其 hotspot_focus
    连板层才是真连板，两接口互相矛盾）。本函数把「连板高度」与「区间高度」分离：
    M/N 只作区间标注（N天M板），连板语义一律取本函数。

    取数规则（省回溯 + 宁缺毋猜）：
    - num N==M → 韭研自证纯连板（N 天 M 板=窗口内每日封板），streak=M，不回溯；
    - num N>M → 中间有断板**或停牌**，走封板链回溯（jiuyan_consecutive_streaks）得真连板；
     回溯内借 TDX 日线分辨二者：无棒=停牌→跳过续算，有棒未封=断板→链终止；
    - num=None → 韭研首板口径（不标 num），streak=1；
    - 回溯撞上 THS 炸板池缺失日 → None（不可算，不按 M 伪算）；
    - 今日未封板（炸板/触板未封）→ None；今日 THS 池缺失（封板不可二分）→ 全股 None。

    返回 {code: streak|None}；韭研 final 缺失 → {}（allow_midday_fallback=True 时回退
    午盘名单；盘中 THS 15:00 池不存在 → 全股 None，真连板不可算不冒充）。缓存键含
    fallback 旗标与源文档版本戳入键，两种口径/新旧名单不互串。**缓存只在 final 已落档时写入**（2026-10-21
    review P1）：盘中/transitional 状态（final 未出、THS 池未落）不落缓存——否则
    12:35 写入的「全股 None」会锁存到收盘后，final+15:00 帧已更新仍命中陈旧值，
    同响应内 boards/limitUpTime 已是 final 口径而 streak 恒 None（混口径直到进程重启）。
    消费方：market_metrics 连板梯队、relay 三日链/龙头档案/题材梯队表。
    """
    info, meta = jiuyan_board_info(db, date, allow_midday_fallback=allow_midday_fallback)
    # 缓存键含源文档版本戳（2026-10-23 事故）：15:35 过期 final 落档后 8000 长驻进程
    # 首算缓存，18:0x 重采覆写 final 后键不变 → 复盘页永选命中旧名单算出的真连板
    #（大业股份 16天8板 显示 8 连板，实际 6）。final 重采 → fetchedAt 变 → 键换代重算。
    cache_key = (dataset_id, date, bool(allow_midday_fallback),
                 str(meta.get("sourceFetchedAt")))
    if cache_key in _STREAK_CACHE:
        return _STREAK_CACHE[cache_key]
    # transitional（final 未落档）不落缓存：盘后 final 到位后重算即得终口径，不锁存盘中态
    if not info:
        return {}
    if not meta.get("jiuyanFinalFound"):
        # 午盘兑底口径（info 非空但来自 midday）：final 未落档、午盘名单口径=已触板，
        # 「至今日」封板二分不可得 → N>M 回溯链不可算维持 None（不冒充）。
        # 但韭研**自证**直取规则不依赖封板二分：N==M → M、num=None → 1，照常直取
        # （v3.2b2 2026-10-21 用户报障：一刀切 None 把自证规则也误杀，连板股全显
        # 「真连板未定」）。口径由 meta.middayFallbackUsed / boardJoinSlot=midday 注记承担；
        # transitional 不落缓存（final 落档后重算即得终口径，不锁存盘中值）。
        out = {}
        for code, i in info.items():
            boards, days = i.get("boards"), i.get("days")
            if boards is not None and days is not None and days == boards:
                out[code] = boards       # 韭研自证纯连板（num 含今日），直取不回溯
            elif boards is None:
                out[code] = 1            # 韭研首板口径（同 final 规则）
            else:
                out[code] = None         # N>M：今日封板不可二分，不按 M 伪算不猜链
        return out
    if not meta.get("thsPoolFound"):
        # 今日 THS 炸板池缺失 → 封板不可二分，全部不可算（不把触板当封板，fail-visible）；
        # final 已在但 15:00 帧可能晚到 → 同样不落缓存，帧落库后重算
        return {code: None for code in info}
    today_sealed = {c for c, i in info.items() if not i.get("zhaban")}
    walk_targets: dict[str, int] = {}
    out = {}
    for code, i in info.items():
        boards, days = i.get("boards"), i.get("days")
        if boards is not None and days is not None and days > boards:
            walk_targets[code] = boards  # 断板股：回溯求真连板
        else:
            out[code] = boards if boards else 1  # N==M 直取 M；num=None 首板口径
    if walk_targets:
        out.update(jiuyan_consecutive_streaks(db, date, walk_targets, today_sealed))
    for code in list(out):
        if code not in today_sealed:
            out[code] = None  # 今日炸板/触板未封 → 无「至今日」连续高度
    _STREAK_CACHE[cache_key] = out
    return out


def _range_top_stock(db, date: str) -> dict | None:
    """区间高度最高股（num「N天M板」M 最大、同板数封板最早）——区间标注用，非连板口径。

    排序键与 dragon_rows 单一事实源（M 降序 → 封板时间升序），避免两处龙序规则漂移。
    """
    doc = db["jiuyan_action"].find_one(
        {"_id": f"{date}:final"}, {"fields.stocks.code": 1, "fields.stocks.name": 1,
                                   "fields.stocks.num": 1, "fields.stocks.time": 1})
    stocks = [s for f in (doc or {}).get("fields") or [] for s in (f.get("stocks") or [])]
    rows = dragon_rows(stocks, top=1)
    return rows[0] if rows else None


def market_metrics(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict | None:
    """当日 15:00 盘面事实（涨停/炸板/回撤/梯队/最高板高；跌停另行自算）。批次B I8：带 datasetId/type 并取最新帧。
    2026-10-10 梯队双源：jiuyan final 聚合为主源（103 天池史稳定），THS thsPools
    交叉验证兼回退；ladderSource 标注实际来源（jiuyan/jiuyan_touch/ths/missing），供叙事透明披露。
    2026-10-16 口径修正（预登记 jev-relay-caliber-fix-preregistration.md §2）：maxBoard 与
    ladder 改**真连板**口径（jiuyan_streak_map），区间板数 M 移至 maxBoardRange/maxBoardStock
    作区间标注——10-15 审计：澳弘电子 19天11板（10-14 已炸板）真连板=1，旧口径写成最高 11 板。"""
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"limitSummary.zhaban": 1, "limitSummary.continuousBoards": 1,
         "limitSummary.thsPools": 1, "limitSummary.drawdown": 1,
         "limitSummary.sealQuality": 1},
        sort=[("timestamp", -1), ("snapshotId", -1)])
    ls = (f or {}).get("limitSummary") or {}
    zb = ls.get("zhaban") or {}
    cb = ls.get("continuousBoards") or {}
    dd = ls.get("drawdown") or {}
    tp = ls.get("thsPools") or {}
    pools = tp.get("pools") or {}
    ths_ok = bool(tp.get("ok")) and not tp.get("degraded")
    ths_ladder = {k: (pools.get(k) or {}).get("total") for k in THS_KEYS}
    jiuyan_ladder = _jiuyan_ladder(db, date, dataset_id)
    if jiuyan_ladder is not None:
        ladder = {k: jiuyan_ladder[k] for k in THS_KEYS}
        ladder_source = "jiuyan" if jiuyan_ladder.get("_caliber") == "streak" else "jiuyan_touch"
        ladder_pool_total = jiuyan_ladder["_poolTotal"]
        ladder_day_unmarked = jiuyan_ladder["_dayUnmarked"]
        ladder_day_unmarked_prev = jiuyan_ladder["_dayUnmarkedPrev"]
        ladder_height_unknown = jiuyan_ladder.get("_heightUnknown")
        range_top = _range_top_stock(db, date)
    elif any(isinstance(v, (int, float)) for v in ths_ladder.values()):
        ladder = ths_ladder
        ladder_source = "ths"
        ladder_pool_total = sum(v for v in ths_ladder.values() if isinstance(v, (int, float)))
        ladder_day_unmarked = None
        ladder_day_unmarked_prev = None
        ladder_height_unknown = None
        range_top = None
    else:
        ladder = ths_ladder  # 全 None（fail-visible：双源皆缺不伪造零梯队）
        ladder_source = "missing"
        ladder_pool_total = None
        ladder_day_unmarked = None
        ladder_day_unmarked_prev = None
        ladder_height_unknown = None
        range_top = None
    if not zb.get("ztCount"):
        return None
    # 真连板最高板：只认可验证链（N==M 直取 / N>M 回溯），不可算 → None（不拿区间 M 冒充）
    streaks = jiuyan_streak_map(db, date, dataset_id)
    max_streak = max((v for v in streaks.values() if isinstance(v, int)), default=None)
    # 冲刺池（盘中冲板未封，与炸板池并列第三池）+ 封板质量（烂板等）——2026-10-16 补投影，
    # relay 炸板面双口径与烂板段消费。池级 ok 且 items 空 = 当日无冲刺股，合法 0；
    # 池未拉取（非 EOD 槽）/自身上游失败 → None（「取不到」≠「真的 0」，AGENTS §4.0）
    rush_pool = pools.get("rushing") or {}
    rush_count = (len(rush_pool.get("items") or [])
                  if ths_ok and rush_pool.get("ok") else None)
    sq = ls.get("sealQuality") or {}
    seal_quality = ({k: sq.get(k) for k in ("byzCount", "hardCount", "rottenCount",
                                            "rottenShare", "avgSucRate")} if sq else None)
    return {"ztCount": zb.get("ztCount"), "zhabanCount": zb.get("count"), "zhabanRate": zb.get("rate"),
            "drawdownCount": dd.get("count"), "ladder": ladder, "maxBoard": max_streak,
            "maxBoardRange": cb.get("maxBoard"), "maxBoardStock": range_top,
            "rushingCount": rush_count, "sealQuality": seal_quality,
            "ladderSource": ladder_source, "ladderPoolTotal": ladder_pool_total,
            "ladderDayUnmarked": ladder_day_unmarked,
            "ladderDayUnmarkedPrev": ladder_day_unmarked_prev,
            "ladderHeightUnknown": ladder_height_unknown,
            "thsLadder": ths_ladder if any(isinstance(v, (int, float)) for v in ths_ladder.values()) else None}


def trading_dates_before(db, date: str, n: int = 20,
                         dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    """严格早于 date 的最近 n 个快照交易日（升序）。批次B I9：改查 snapshot_frames
    （行数少两个数量级）且带 datasetId；不再全表扫 snapshot_stock_rows。"""
    rows = db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": {"$lt": date}},
        {"tradingDate": 1})
    return sorted({str(r["tradingDate"]) for r in rows if r.get("tradingDate")})[-n:]




def _advdec_segment(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    ad = advdec_ratio(db, date, dataset_id)
    if not ad:
        return " · 池内涨跌结构 不可算（fail-visible）"
    up, down, flat, ratio = ad
    # 2026-10-16 语气词修正（审计问题 #9）：0.82 的跌多涨少日旧口径显示「没人买也没人买」，
    # 26 家全市场跌停的日子这句语气词会把退潮读成僵持。band 语义按 ratio<1 即偏弱重划。
    if ratio > 1.25:
        tone = "单边偏强"
    elif ratio >= 1.0:
        tone = "均衡"
    else:
        tone = "跌多涨少（偏弱）"
    return f' · 池内涨跌比 {ratio}（涨{up}/跌{down}，{tone}）'


def market_facts_line(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """弹药 6：分位盘面事实行（不含规则情绪分——Q5 防锚定污染）。按 (dataset, 日, 源版本) 缓存。

    缓存键含 final fetchedAt 版本戳（2026-10-23 事故）：final 被重采覆写后旧行
    「最高 8 板」会永选命中，长驻进程不重启则不自愈。戳读取失败按 None 入键
    （退化为旧行为，不阻断主链）。
    """
    try:
        stamp_doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fetchedAt": 1})
        stamp = repr((stamp_doc or {}).get("fetchedAt"))
    except Exception:
        stamp = "?"
    cache_key = (dataset_id, date, stamp)
    if cache_key in _FACTS_CACHE:
        return _FACTS_CACHE[cache_key]
    cur = market_metrics(db, date, dataset_id)
    if not cur:
        return f"盘面事实：{date} 盘面指标缺失（fail-visible）"
    prev = trading_dates_before(db, date, dataset_id=dataset_id)
    hist = [m for m in (market_metrics(db, d, dataset_id) for d in prev) if m]

    # 跌停=全市场口径（2026-10-16 口径修正，审计问题 #1）：东财跌停池为主源、全市场行情
    # 快照兜底，当日允许懒加载；历史样本只读参考集合（一次 find 批量同源，防逐日 20 连发
    # 外呼）。参考集合缺失 → 回退 250 只采集池口径并显式标注——池口径会漏掉池外跌停
    # （10-15 实证：池内 6 vs 全市场 26）。
    cur_die, die_src = limit_down_count(db, date, dataset_id)
    if die_src in FULL_MARKET_SOURCES:
        # 同源采样：同一列内不得混口径（采集池 vs 全市场差 4 倍量级）；全市场家族内部
        # （东财池/快照/本地日线重算）也只采当日同源，避免把源差读成情绪摆动
        die_hist = reference_counts(db, prev, die_src)
        hist_die = [die_hist[d] for d in prev if d in die_hist]
        die_scope = source_label(die_src)
    else:
        hist_die = [v for v in (dieban_count(db, d, dataset_id) for d in prev)
                    if isinstance(v, int) and not isinstance(v, bool)]
        die_scope = (source_label(SOURCE_POOL) + "，全市场源缺失"
                     if die_src == SOURCE_POOL else None)
    if isinstance(cur_die, int) and not isinstance(cur_die, bool) and die_scope:
        die_txt = f'跌停 {cur_die} 家（{die_scope}，{_pct_txt(hist_die, cur_die)}）'
    else:
        die_txt = "跌停 不可算"
    rate = f'{cur["zhabanRate"]:.1f}%' if isinstance(cur["zhabanRate"], (int, float)) else "缺"
    # 炸板率双口径（2026-10-16 补供，审计问题 #6）：曾封后开板（THS 炸板池）｜触板未封
    # （炸板池+冲刺池）。旧语料只给前者，「炸板面健康」判据看不到触板未封那一半
    zb_n = cur.get("zhabanCount") if isinstance(cur.get("zhabanCount"), int) else None
    zt_n = cur.get("ztCount") if isinstance(cur.get("ztCount"), int) else None
    rush_n = cur.get("rushingCount") if isinstance(cur.get("rushingCount"), int) else None
    unsealed_txt = ""
    if None not in (zb_n, zt_n, rush_n):
        unsealed = zb_n + rush_n
        touch_total = zt_n + unsealed
        rate2 = round(unsealed / touch_total * 100, 1) if touch_total else 0.0
        unsealed_txt = (f" · 触板未封 {unsealed} 家（含冲刺 {rush_n} 家），"
                        f"未封率 {rate2}%（{unsealed}/{touch_total}）")
    three_plus = (cur["ladder"].get("three") or 0) + (cur["ladder"].get("four") or 0) + (cur["ladder"].get("high") or 0)
    ladder_txt = (f'一板{cur["ladder"].get("one") or 0}/二板{cur["ladder"].get("two") or 0}/三板+{three_plus}')
    src = cur.get("ladderSource")
    if src == "jiuyan":
        # 真连板口径（2026-10-16）：只桶封板股；漏标/不可算分别披露，不按 M 伪算
        un_prev = cur.get("ladderDayUnmarkedPrev") or 0
        un_note = f'，{un_prev}只连板未标高度未计入' if un_prev else ''
        hu = cur.get("ladderHeightUnknown")
        hu_note = f'，{hu}只高度不可算未入桶' if isinstance(hu, int) and hu else ''
        ladder_seg = f'连板梯队（韭研{cur.get("ladderPoolTotal")}只封板，真连板口径{un_note}{hu_note}）{ladder_txt}'
        ths = cur.get("thsLadder")
        if ths:
            ladder_seg += (f'（THS交叉 {ths.get("one")}/{ths.get("two")}/{ths.get("three")}'
                           f'/{ths.get("four")}/{ths.get("high")}）')
    elif src == "jiuyan_touch":
        # THS 炸板池缺失日：回退触板池按 M 分桶（旧口径，炸板股会混入），显式披露
        ladder_seg = f'连板梯队（THS炸板池缺失，按触板口径，炸板股混入）{ladder_txt}'
    elif src == "ths":
        ladder_seg = f'连板梯队（THS回退）{ladder_txt}'
    else:
        ladder_seg = '连板梯队 不可算（韭研 final 与 THS 双源皆缺）'
    # 最高板=真连板；区间最高（N天M板 的 M 最大股）作标注，两者不同才附（10-15：5 板 vs 澳弘 19天11板）
    mb, mb_range, mb_stock = cur.get("maxBoard"), cur.get("maxBoardRange"), cur.get("maxBoardStock")
    if isinstance(mb, int):
        board_txt = f'最高 {mb} 板（{_pct_txt([h["maxBoard"] for h in hist], mb)}）'
        if mb_stock and isinstance(mb_stock.get("boards"), int) and mb_stock["boards"] != mb:
            board_txt += f'（区间最高 {_range_height_text(mb_stock)}）'
    elif isinstance(mb_range, int):
        board_txt = f'最高 不可算（THS炸板池缺失，真连板不可验证；区间最高 {mb_range} 板）'
    else:
        board_txt = '最高 不可算（THS炸板池缺失，真连板不可验证）'
    line = (f'盘面事实：涨停 {cur["ztCount"]} 家（{_pct_txt([h["ztCount"] for h in hist], cur["ztCount"])}）'
            f' · {die_txt}'
            f' · 炸板率 {rate}（{_pct_txt([h["zhabanRate"] for h in hist], cur["zhabanRate"])}，'
            f'炸板 {zb_n if zb_n is not None else cur["zhabanCount"] or 0} 家）{unsealed_txt}'
            f' · 大幅回撤 {cur["drawdownCount"] if cur["drawdownCount"] is not None else "?"} 家'
            f'（{_pct_txt([h["drawdownCount"] for h in hist], cur["drawdownCount"])}）'
            f' · {ladder_seg}'
            f' · {board_txt}'
            + _advdec_segment(db, date, dataset_id))
    _FACTS_CACHE[cache_key] = line
    return line


def _pct_txt(vals, cur_v) -> str:
    """分位文本：样本空（percentile_fraction 返 None）→「分位不可算」，不拼成「分位不可算 分位」。

    2026-10-16：跌停改同源采样后，EM 窗口（30 自然日）之前的历史日没有同源样本，
    「分位不可算」从罕见过渡到常态，原来 f-string 里手写「 分位」的拼法会产出
    「（全市场·东财跌停池，分位不可算 分位）」这种病句。
    """
    rank = percentile_rank(vals, cur_v)
    return rank if rank == "分位不可算" else f"{rank} 分位"


# ── v3.2 语料瘦身/增益（2026-10-20 预注册 docs/hotlist-jev/jev-driver-label-v32-preregistration.md）──
# 盘点结论（只读生产库实测）：个股四题判据对【盘面事实行】零独有字段引用，却每只重复投喂
# 135 字（68 只/日 ≈9.2k tokens 同文重复）；而判据真正需要、语料却缺席的四项证据是：
#   ① `catalyst_freshness`「≤2 个交易日」的交易日轴（语料只有公历日期）；
#   ② `buy_side_logic`「封板时间偏晚」的分布基线（只有 09:36 这种绝对值）；
#   ③ freshness/driver 需要的「解析是不是新的」跨日对比（只有当日解析）；
#   ④ `buy_side`「同板块多股集体异动」的昨日对照（只有今日家数）。
# 分工红线：`market_facts_line` 是 relay v7 / cycle / theme_leader 共用的**打分坐标系**，
# 一行不改（否则 relay v7 语料连带漂移、验收门作废）；个股链改用下列轻量行。
_MKT_COORD_CACHE: dict[tuple, str] = {}
_DATE_AXIS_CACHE: dict[tuple, str] = {}
_JIYAN_EXPOUND_CACHE: dict[tuple, dict[str, str]] = {}
_BOARD_PREV_CACHE: dict[tuple, dict] = {}
_THS_STATE_CACHE: dict[tuple, dict] = {}
# v3.2b（2026-10-21）：解析首现回溯/板块 T-2 回看用多日轴记忆化（(dataset,date,n)），
# 逐股调用不能每股一次查询；conftest `_JEV_RUNNER_CACHES` 同步注册。
# （v3.2 旧单日缓存 `_PREV_TRADING_DATE_CACHE` 随 D8 回看扩展退役删除，多日轴单源。）
_PREV_TRADING_DATES_CACHE: dict[tuple, list[str]] = {}
_WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


def _weekday_cn(date: str) -> str:
    """YYYY-MM-DD → 周一..周日；非法日期返回空串（不猜）。"""
    try:
        return _WEEKDAY_CN[datetime.date.fromisoformat(str(date)).weekday()]
    except Exception:
        return ""


def market_coordinate_line(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """个股叙事用的轻量市场坐标（v3.2 D5-B，三数）。

    与 `market_facts_line` 的分工：后者是 relay/PHASE 的**打分坐标系**（涨停/跌停/炸板率/
    回撤/梯队各带近 20 日分位），个股四题判据实测 0 处引用其独有字段；整行逐股投喂既浪费
    又给模型一个跨轨锚（拿市场温度当个股驱动）。本行只留「退潮日」的最低语境，**不带分位**。
    """
    key = (dataset_id, date)
    if key in _MKT_COORD_CACHE:
        return _MKT_COORD_CACHE[key]
    cur = market_metrics(db, date, dataset_id)
    if not cur:
        line = f"市场坐标：{date} 盘面指标缺失（fail-visible）"
    else:
        zt, mb = cur.get("ztCount"), cur.get("maxBoard")
        parts = [f"涨停 {zt} 家" if isinstance(zt, int) and not isinstance(zt, bool)
                 else "涨停 不可算",
                 f"最高 {mb} 板" if isinstance(mb, int) and not isinstance(mb, bool)
                 else "最高板 不可算"]
        ad = advdec_ratio(db, date, dataset_id)
        parts.append(f"池内涨跌比 {ad[3]}（涨{ad[0]}/跌{ad[1]}）" if ad else "池内涨跌比 不可算")
        line = "市场坐标：" + " · ".join(parts)
    _MKT_COORD_CACHE[key] = line
    return line


def date_axis_line(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """交易日轴（v3.2 D6）：让 `catalyst_freshness` 的「≤2 个交易日」可数。

    语料只给公历日期，跨周末/长假（如 10-17 周五 → 10-20 周一）时「2 个交易日」需要模型
    自行查日历；本行直接给出前 1/前 2 个交易日的日期与星期，**判据一字不改**。
    """
    key = (dataset_id, date)
    if key in _DATE_AXIS_CACHE:
        return _DATE_AXIS_CACHE[key]
    prev = trading_dates_before(db, date, 2, dataset_id=dataset_id)
    wd = _weekday_cn(date)
    parts = [f"今日 {date}" + (f"（{wd}）" if wd else "")]
    for i in (1, 2):
        if len(prev) >= i:
            d = prev[-i]
            w = _weekday_cn(d)
            parts.append(f"前{i}交易日 {d}" + (f"（{w}）" if w else ""))
        else:
            parts.append(f"前{i}交易日 不可算")
    line = "交易日轴：" + " · ".join(parts)
    _DATE_AXIS_CACHE[key] = line
    return line


def _jiuyan_expound_map(db, date: str, slot: str = "final") -> dict[str, str]:
    """某日韭研名单 code→解析正文（按 (日, 槽位) 缓存，零额外外呼）。缺失日返回 {}。"""
    key = (date, slot)
    if key in _JIYAN_EXPOUND_CACHE:
        return _JIYAN_EXPOUND_CACHE[key]
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:{slot}"}, {"fields": 1}) or {}
    out: dict[str, str] = {}
    for fl in doc.get("fields") or []:
        for s in fl.get("stocks") or []:
            code = _strip(s.get("code"))
            text = str(s.get("expound") or "").strip()
            if code and text and code not in out:
                out[code] = text
    _JIYAN_EXPOUND_CACHE[key] = out
    return out


def _prev_trading_dates(db, date: str, n: int,
                        dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    """date 之前 n 个交易日（升序；(dataset, date, n) 记忆化，v3.2b 新增）。

    P0-2 解析首现回溯与 P1-1 板块 T-2 回看都逐股调用多日轴，不能每股一次查询；
    复用同一 `trading_dates_before`（单一事实源），只加缓存。"""
    key = (dataset_id, date, n)
    if key not in _PREV_TRADING_DATES_CACHE:
        _PREV_TRADING_DATES_CACHE[key] = trading_dates_before(
            db, date, n, dataset_id=dataset_id)
    return _PREV_TRADING_DATES_CACHE[key]


def _first_line(text: str, limit: int = 24) -> str:
    """解析正文首个非空行（截断到 limit 字）——「上日首行」类文案的唯一取法。"""
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line:
            return line if len(line) <= limit else line[:limit] + "…"
    return ""


EXPOUND_TRACE_LOOKBACK = 10


def expound_trace_line(db, date: str, code: str, today_expound: str | None,
                       slot: str = "final",
                       dataset_id: str = DEFAULT_DATASET_ID) -> str | None:
    """解析续期/首现（v3.2 D8；v3.2b 扩展为近 10 个交易日回看）。

    `slot` 参数=对比基准文档的槽位（默认 final，权威口径）：所有调用点（收盘/午盘/承接）
    都用「昨日 final」作基准，与当日投喂槽位无关（审查 nit14：参数语义在此显式声明）。

    `catalyst_freshness`（「持续/新催化」）与 `driver_type`（「催化本身无新意」）都要回答
    「今天这句解析是不是新的」，而语料只给当日解析（含日期率 91.6%，但无跨日可比锚）。
    v3.2b 实证缺陷（2026-10-21 午盘 002368）：D8 只与上一交易日比对，而反复股（3天2板等）
    上一交易日往往不在名单 → 锚恰好丢失。扩展：回看近 10 个交易日，
    - 存在逐字相同记录 → 锚=最早相同记录：「该解析最早见于 {d}（距今 {gap} 个交易日，
      回看 {lookback} 交易日）」——对齐判据「催化事件首次出现距今 ≤2 个交易日」的首现语义；
    - 无相同记录但有更早解析 → 锚=最近一次记录：「较 {d}（距今 {gap} 个交易日）有更新」；
    - 近 10 个交易日无任何记录 → 不出行（裁决 5B：省字；「首次进榜」不构成新旧证据，
      催化可能早于窗口存在，不写「首现」冒充）。
    对比用上一交易日的 `final` 收盘名单（权威口径），与当日投喂槽位无关。
    """
    today_txt = str(today_expound or "").strip()
    if not today_txt:
        return None
    prev_dates = _prev_trading_dates(db, date, EXPOUND_TRACE_LOOKBACK, dataset_id)
    if not prev_dates:
        return None
    sig = expound_signature(today_txt)
    identical: tuple[str, int] | None = None   # 最早逐字相同记录 (日, 距今交易日数)
    latest_any: tuple[str, int, str] | None = None  # 最近一次有解析的记录 (日, 距今, 文本)
    for d in prev_dates:
        prev_txt = _jiuyan_expound_map(db, d, slot).get(_strip(code))
        if not prev_txt:
            continue
        gap = len(prev_dates) - prev_dates.index(d)
        if identical is None and expound_signature(prev_txt) == sig:
            identical = (d, gap)
        # 升序遍历，不设 None 卫冕 → 循环结束后留下的是最近一次记录
        latest_any = (d, gap, prev_txt)
    if identical:
        d, gap = identical
        axis_txt = f"回看 {len(prev_dates)} 个交易日"
        if latest_any and latest_any[0] == d:
            return (f"解析续期：该解析最早见于 {d}（距今 {gap} 个交易日，{axis_txt}），"
                    f"此后逐字相同（无新增事项）")
        # 中间有更新：不得写「此后逐字相同」（审查 SF9：边界措辞失实）
        d2, gap2, latest_txt = latest_any
        return (f"解析续期：该解析最早见于 {d}（距今 {gap} 个交易日，{axis_txt}）逐字相同；"
                f"最近一次记录 {d2}（距今 {gap2} 个交易日）已有更新 · 当时首行「{_first_line(latest_txt)}」")
    if latest_any:
        d, gap, prev_txt = latest_any
        return (f"解析续期：较 {d}（距今 {gap} 个交易日）有更新"
                f" · 当时首行「{_first_line(prev_txt)}」")
    return None


def _minutes_of(hhmmss: Any) -> int | None:
    """'09:36:14' / '09:36' → 当日分钟数；不可解析返回 None（不猜）。"""
    m = _TIME_RE.match(str(hhmmss or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return h * 60 + mi


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _median_minutes(vals: list[int]) -> int:
    s = sorted(vals)
    return s[len(s) // 2]


def seal_time_line(jiuyan_doc, code: str, scope: str = "final") -> str:
    """封板时间坐标（v3.2 D7）：给 `buy_side_logic`「该股封板时间偏晚」一把尺子。

    旧语料只给绝对时刻（该股 09:36:14），「偏晚」没有基线——实测 10-19 名单中位 11:28，
    同一时刻在早盘密集日与午后集中日含义完全不同。本行给「全名单中位 + 第 N 早 + 板块内中位」，
    全部来自当日韭研名单（time 字段覆盖率 78%，缺失不参与分位并如实标注样本数）。
    """
    label = "午盘名单" if scope == "midday" else "当日名单"
    rows: list[tuple[str, int | None]] = []
    board_of_mine: str | None = None
    mine: int | None = None
    for fl in jiuyan_doc.get("fields") or []:
        board = str(fl.get("name") or "")
        for s in fl.get("stocks") or []:
            mins = _minutes_of(s.get("time"))
            rows.append((board, mins))
            if board_of_mine is None and _strip(s.get("code")) == _strip(code):
                board_of_mine, mine = board, mins
    vals = [m for _, m in rows if m is not None]
    if not vals:
        return f"封板时间坐标（{label}）：名单无可用时间（fail-visible）"
    total = len(rows)
    med = _median_minutes(vals)
    if mine is None or board_of_mine is None:
        return (f"封板时间坐标（{label}）：该股时间缺失（fail-visible）"
                f" · 名单中位 {_hhmm(med)}（{len(vals)}/{total} 只可算）")
    parts = [f"封板时间坐标（{label}）：该股 {_hhmm(mine)}（第 "
             f"{sum(1 for v in vals if v < mine) + 1} 早/{len(vals)} 只）",
             f"名单中位 {_hhmm(med)}"]
    board_vals = [m for b, m in rows if b == board_of_mine and m is not None]
    parts.append(f"板块内中位 {_hhmm(_median_minutes(board_vals))}" if board_vals
                 else "板块内中位 不可算")
    tail = f"（{len(vals)}/{total} 只可算）" if len(vals) < total else ""
    return " · ".join(parts) + tail


def board_prev_info(db, date: str, board: str,
                    dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    """上一交易日同一韭研板块的涨停家数（v3.2 D7；v3.2b 增 T-2 回看）。

    `buy_side_logic` 判据写「同板块多股今日集体异动」（板块跟随）与「无板块协同」，
    但语料只给今日家数 → 「板块启动中的跟随」与「板块退潮中的跟随」无法区分。
    v3.2b 实证缺陷（2026-10-21 午盘 002368）：韭研板块命名昨今漂移/题材隔日体断
    （同名可比率 65.9%），只看 T-1 会把「T-1 无同名板块、T-2 有」误写成不可比
    （10-21 午盘 51 只中 8 只因此丢锚）。回看顺序：T-1 命中直接用；T-1 无同名板块
    再看 T-2，命中则 `reason="t2_fallback"` + `day=T-2`（文案显式标口径，不冒充昨日）。
    返回 `{ok, count, reason, day}`：reason 区分两种不可比（**不补 0 冒充**）：
    - `no_prev_doc`：回看窗内名单缺失（fail-visible）；
    - `board_absent`：T-1/T-2 名单里都没有同名板块（韭研板块命名昨今会漂移，
      实测同名可比率 65.9%）。
    """
    if not board:
        return {"ok": False, "count": None, "reason": "no_board", "day": None}
    key = (dataset_id, date, board)
    if key in _BOARD_PREV_CACHE:
        return _BOARD_PREV_CACHE[key]

    def _count_in(doc: dict | None) -> int | None:
        if doc is None:
            return None
        for fl in doc.get("fields") or []:
            if str(fl.get("name") or "") == board:
                return len(fl.get("stocks") or [])
        return None

    prev = _prev_trading_dates(db, date, 2, dataset_id)
    miss: dict = {"ok": False, "count": None, "reason": "no_prev_doc", "day": None,
                  "t1Found": None, "t2Found": None}
    if not prev:
        info = miss
    else:
        t1 = prev[-1]
        t2 = prev[-2] if len(prev) >= 2 else None
        doc1 = db["jiuyan_action"].find_one({"_id": f"{t1}:final"}, {"fields": 1})
        c1 = _count_in(doc1)
        if c1 is not None:
            info = {"ok": True, "count": c1, "reason": None, "day": t1,
                    "t1Found": True, "t2Found": None}
        elif t2 is not None:
            doc2 = db["jiuyan_action"].find_one({"_id": f"{t2}:final"}, {"fields": 1})
            c2 = _count_in(doc2)
            if c2 is not None:
                info = {"ok": True, "count": c2, "reason": "t2_fallback", "day": t2,
                        "t1Found": doc1 is not None, "t2Found": True}
            elif doc1 is None and doc2 is None:
                info = dict(miss, t1Found=False, t2Found=False)   # 两日名单都缺失
            else:
                # doc1 在但无同名板块、doc2 名单缺失 → 不可比（不是「两日都无同名板块」，
                # 审查 SF6：混合态不得冒充成纯 board_absent 语义）
                info = {"ok": False, "count": None, "reason": "board_absent", "day": None,
                        "t1Found": True, "t2Found": False}
        elif doc1 is None:
            info = miss
        else:
            info = {"ok": False, "count": None, "reason": "board_absent", "day": None,
                    "t1Found": True, "t2Found": False}
    _BOARD_PREV_CACHE[key] = info
    return info


def board_prev_count(db, date: str, board: str,
                     dataset_id: str = DEFAULT_DATASET_ID) -> int | None:
    """只取家数（None=不可比）；口径与 `board_prev_info` 同一实现，禁双轨。"""
    return board_prev_info(db, date, board, dataset_id)["count"]


def ths_ladder_state(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict:
    """THS **封板梯队池**可用性（v3.2 D2）——区分「整池未采集」与「该股真未进池」。

    实测缺陷：`ths_positions` 对两种语义返回同一个空结果，叙事无从分辨，旧文案把整池缺失日
    （7/30 天、457 只 = 21.2%）的**当日涨停股**一律写成「未进 THS 封板池（今日触板未封/炸板
    口径）」——这是事实错误的文案，且与同段「今日涨停价…」自相矛盾。
    实测池形（10-19 全池 / 10-08 只有 failed+rushing+drawdown / 09-02 pools 空）。
    """
    key = (dataset_id, date)
    if key in _THS_STATE_CACHE:
        return _THS_STATE_CACHE[key]
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date,
         "slotTime": "15:00"},
        {"limitSummary.thsPools": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    tp = ((f or {}).get("limitSummary") or {}).get("thsPools") or {}
    pools = tp.get("pools") or {}
    # 对齐 relay 先例（jev_relay_index `_relay_...`）：池自身 ok=False 不算「采集到」，
    # 否则一个上游失败的空池会被当成「该股真未进池」（P2 审查 Nit-5）
    present = [k for k in THS_KEYS
               if isinstance(pools.get(k), dict) and (pools.get(k) or {}).get("ok") is not False]
    if f is None:
        state = {"ok": False, "reason": "15:00 帧缺失"}
    elif not pools:
        state = {"ok": False, "reason": "THS 池未拉取（旧 schema/占位零）"}
    elif not present:
        state = {"ok": False, "reason": "封板梯队池未采集（仅炸板/冲刺池）"}
    elif tp.get("degraded") and not any((pools.get(k) or {}).get("items") for k in present):
        state = {"ok": False, "reason": "封板梯队池占位零降级"}
    else:
        state = {"ok": True, "reason": None}
    _THS_STATE_CACHE[key] = state
    return state


# ---- 弹药 6：个股价格位置轴（2026-10-04 用户令接入：距 20 日最高/窗口涨幅/量能缩放——
#      首板单锚判不出高位，龙版传媒 605577 首板但距 20 日高点仅 7.8%/窗口涨幅 62.5% 实锤） ----
_POSITION_LOCK = threading.Lock()

_DIV_LOCK = threading.Lock()
_DIV_LIST_CACHE: dict[str, dict[str, tuple[float, float]]] = {}
_DIV_FAIL_UNTIL: dict[str, float] = {}  # 失败负缓存（5 分钟退避，防重试风暴 review P1-2）
_DIV_FAIL_TTL = 300.0
_DAILY_CLIENT: Any = None
_DAILY_BARS_CACHE: dict[tuple, list[dict]] = {}
_TDX_DOWN_UNTIL = 0.0
_TDX_RETRY_SECONDS = 300
_BARS_OFFSET_DEFAULT = 250

# 2026-10-18「开长窗」落地：日线原料改**本地优先**（通达信 vipdoc 全历史）。
# 动因（三条均为实测/已记录缺陷，非推测）：
#   ① 线上 mootdx 取数不可靠——2026-10-18 实测 offset 60/250/400 全返回 0 根，而 v5 重放的
#      58 天钱效数字偏偏来自线上窗 → 同一历史日的证据依赖「重放那一刻外网是否通」；
#   ② 线上 60 根窗使早于 ~07-16 的历史日钱效/隔日溢价/连板高度全不可算（诊断文档 §7）；
#   ③ 同一天在不同时间点/进程取到的棒不同 → 叙事不可复现（与 F6 同类的确定性缺陷）。
# 本地 vipdoc 为定长二进制全历史，零外呼、可复现，且与 F7 全市场跌停回填同一数据源
# （单一事实源 §1.2.1）；线上保留为**回退**（本机无通达信目录/目录内无该股文件）。
# 每股读取根数：单一事实源 = market_dieban_tdx.DEFAULT_TAKE（2026-10-18 review P2-2，
# 原先手抄 400 易与回填端漂移；两者必须同口径「≈1.6 年，覆盖回放区间」）。
_LOCAL_TAKE = _TDX_DEFAULT_TAKE
_LOCAL_ROOT_CACHE: list[Any] = []   # 进程内惰性解析的通达信目录
_LOCAL_MISS: set[str] = set()       # 本地无文件/不可用的 code（进程内，免反复 stat）
_BARS_LOCK = threading.Lock()
# 线上补尾（2026-10-20 实测缺陷）：本地 vipdoc 末棒落后于叙事目标日时（闭市后未跑通达信
# 盘后下载），旧逻辑是「本地文件存在即用」→ 今日断板钱效/隔日溢价/分时位置/板序/板型
# 全部不可算，而线上 mootdx 当天已有棒。现在按「只补本地没有的日期」合并：
# 重叠日期一律以本地为准（本地是全历史定长源，历史数字不被线上改写 → 保持可复现）。
_BARS_TAIL_ENV = "JEV_BARS_ONLINE_TAIL"
_TAIL_FAIL_UNTIL: dict[str, float] = {}   # 补尾失败负缓存（防逐 code 重试风暴）
_TAIL_FAIL_TTL = 60.0
_TAIL_MERGED: dict[str, str] = {}         # code → 合并进来的最后日期（溯源用）
_TAIL_FAIL_CODES: set[str] = set()        # 补尾失败且线上也无该日期的 code（fail-visible 计数）
_TAIL_VOL_SOURCE: dict[str, str] = {}     # code → 量纲校准来源（overlap=实测比值 / assumed=兜底 100）
_ONLINE_VOL_TO_LOCAL_DEFAULT = 100.0      # 线上 vol=手、本地 vipdoc vol=股（实测恒 100）
# 「本次叙事要用到的最新交易日」上下文：由 `bars_need_upto(date)` 在叙事组装期间声明。
# 用上下文变量而非逐调用点传参：`_daily_bars` 在生产有 6+ 调用点、测试普遍把它打成
# 单参 lambda（conftest 离线护栏）——加参数会同时改生产签名与全库测试夹具（2026-10-20 实测）。
_BARS_NEED_UPTO: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "jev_bars_need_upto", default=None)


@contextlib.contextmanager
def bars_need_upto(date: str | None):
    """声明「本次要用到的最新交易日」→ 本地末棒落后时按需线上补尾（§_daily_bars）。"""
    token = _BARS_NEED_UPTO.set(date)
    try:
        yield
    finally:
        _BARS_NEED_UPTO.reset(token)
# 溯源：本进程各来源实际供数**次数**（逐 code 首次命中计 1，跨日/跨请求累加，非「本次构成」）。
# 2026-10-18 review P2-5：① 语义是 process 级累计，字段名/注释须写明，不得被读成 per-run；
# ② 自增非原子 —— FastAPI 线程池下并发叙事会丢增量 → 统一走 _BARS_LOCK。
_BARS_SOURCE_COUNTS: dict[str, int] = {}


def _bars_count(src: str) -> None:
    """来源计数自增（进程级累计，加锁防并发丢增量；P2-5）。"""
    with _BARS_LOCK:
        _BARS_SOURCE_COUNTS[src] = _BARS_SOURCE_COUNTS.get(src, 0) + 1
_LOCAL_MARKETS = (("60", "sh"), ("68", "sh"), ("00", "sz"), ("30", "sz"),
                  ("43", "bj"), ("83", "bj"), ("87", "bj"), ("92", "bj"))


def _bars_offset() -> int:
    """线上回退日线棒根数（默认 250）。

    2026-10-17 IE 修复 F5 引入 `JEV_BARS_OFFSET`；2026-10-18「开长窗」把默认 60→250：
    60 根使早于窗起的历史日 TDX 指标（断板亏钱/隔日溢价/连板高度）全不可算（诊断 §7），
    而 `_close_pct` 按**日期取棒**（`bars[date]`）→ 加长只增证据、不改已有数字（单调安全）。
    **本地优先生效时本值不参与**（本地全历史）；本值只决定无本地通达信时的回退窗。
    """
    raw = os.environ.get("JEV_BARS_OFFSET")
    try:
        return max(20, int(raw)) if raw else _BARS_OFFSET_DEFAULT
    except (TypeError, ValueError):
        return _BARS_OFFSET_DEFAULT


def _local_root() -> str | None:
    """本机通达信目录（末棒最新者；进程内缓存）；无 → None（走线上回退）。"""
    if not _LOCAL_ROOT_CACHE:
        root: str | None = None
        try:
            from backend.operations.market_dieban_tdx import resolve_root
            root = resolve_root()[0]
        except Exception:
            root = None
        _LOCAL_ROOT_CACHE.append(root)
    return _LOCAL_ROOT_CACHE[0]


def _local_bar_file(root: str, code: str) -> str | None:
    """6 位 A 股代码 → 本地 `.day` 路径（市场段判法同 `market_dieban_tdx._A_SHARE`）。"""
    digits = "".join(ch for ch in str(code) if ch.isdigit())[-6:]
    if len(digits) != 6:
        return None
    for prefix, market in _LOCAL_MARKETS:
        if digits.startswith(prefix):
            return os.path.join(root, "vipdoc", market, "lday", f"{market}{digits}.day")
    return None


def _local_daily_bars(code: str) -> list[dict] | None:
    """本地 vipdoc 日线（升序，尾 `_LOCAL_TAKE` 根）。

    返回 None = 本地不可用（无目录/无该股文件/空文件）→ 调用方走线上回退（不缓存 None）。
    语义与 F7 覆盖闸一致：本地缺该股文件只意味着「来源退回线上」，不是「该股无数据」。
    """
    root = _local_root()
    if not root:
        return None
    path = _local_bar_file(root, code)
    if not path or not os.path.exists(path):
        return None
    try:
        from backend.operations.market_dieban_tdx import _iso, read_lday
        recs = read_lday(path, take=_LOCAL_TAKE)
        if not recs:
            return None
        bars = [{"date": _iso(r[0]), "high": r[2] / 100.0, "close": r[4] / 100.0,
                 "vol": float(r[6])} for r in recs]
    except Exception:
        return None
    bars.sort(key=lambda b: b["date"])
    return bars or None


def bars_source_provenance() -> dict[str, Any]:
    """本进程日线原料溯源（落 relay 文档 `barsSource`，不入 prompt）：哪个来源供了多少只股
    + 本地目录/末棒/回退窗——供日后核对某日叙事是否拿的是全历史本地棒（fail-visible 溯源）。
    """
    root = _local_root()
    last = None
    if root:
        try:
            from backend.operations.market_dieban_tdx import last_bar_date
            last = last_bar_date(root)
        except Exception:
            last = None
    return {"counts": dict(_BARS_SOURCE_COUNTS), "countsScope": "process_cumulative",
            "localRoot": root, "localLastBar": last,
            "onlineFallbackOffset": _bars_offset(), "localTake": _LOCAL_TAKE,
            # 线上补尾溯源（2026-10-20）：本地末棒落后于叙事日时补了哪些日期、漏了哪些股。
            "tailEnabled": _tail_enabled(),
            "tailMergedUpTo": max(_TAIL_MERGED.values()) if _TAIL_MERGED else None,
            "tailMergedCodes": len(_TAIL_MERGED), "tailMissCodes": len(_TAIL_FAIL_CODES),
            "tailVolCalib": {"overlap": sum(1 for v in _TAIL_VOL_SOURCE.values() if v == "overlap"),
                             "assumed": sum(1 for v in _TAIL_VOL_SOURCE.values() if v == "assumed")}}


def _tdx_hosts_path() -> Path:
    """节点池配置路径：环境变量优先，否则仓库同级 python-bridge/tdx_hosts.json
    （批次B M4：不再写死 D:\ 绝对路径，换 worktree/机器不失效）。"""
    env = os.environ.get("TDX_HOSTS_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "python-bridge" / "tdx_hosts.json"


_TDX_SETUP_PATCHED = False


def _ensure_tdx_setup_patch() -> None:
    """tdxpy 握手身份 patch（python-bridge/main.py 2026-09-23 生产同款）：跳过
    SetupCmd3 旧客户端标识，官方现行主站不再软拒绝（4 字节空响应）。懒执行、
    每进程一次；本模块日线链此前本地 vipdoc 优先未暴露，V2c 盘中报价（quotes）
    只走线上，不打补丁全节点返回空（2026-10-24 回放研究实测）。设
    TDX_KEEP_TDXPY_SETUP3=1 恢复 tdxpy 原始三连握手（回退开关）。"""
    global _TDX_SETUP_PATCHED
    if _TDX_SETUP_PATCHED:
        return
    _TDX_SETUP_PATCHED = True
    if os.getenv("TDX_KEEP_TDXPY_SETUP3", "") in ("1", "true", "True"):
        return
    try:
        def _setup_without_legacy_identity(self):
            from tdxpy.parser.setup_commands import SetupCmd1, SetupCmd2
            SetupCmd1(self.client).call_api()
            SetupCmd2(self.client).call_api()
        from tdxpy.hq import TdxHq_API
        TdxHq_API.setup = _setup_without_legacy_identity
    except Exception:
        pass


def _tdx_daily_client():
    """TDX 日线客户端单例（节点池探测同 backfill_slot_pctchange 模式）；全节点不可用返回 None。

    批次C I4：全节点探测失败进入 5 分钟负缓存——旧实现每股每次重探（8 节点 ×6s），
    100 只股票最坏小时级，会撞 schedule 2700s 整步超时；现在最坏每 5 分钟一次。
    """
    global _DAILY_CLIENT, _TDX_DOWN_UNTIL
    _ensure_tdx_setup_patch()
    with _POSITION_LOCK:
        if _DAILY_CLIENT is not None:
            return _DAILY_CLIENT
        if time.time() < _TDX_DOWN_UNTIL:
            return None
        try:
            hosts = json.loads(_tdx_hosts_path().read_text(encoding="utf-8"))["candidates"]
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
            pass
        # 全节点不可用或配置缺失：负缓存 5 分钟（fail-visible 由调用方如实标注）
        _TDX_DOWN_UNTIL = time.time() + _TDX_RETRY_SECONDS
        return None


def _daily_bars(code: str) -> list[dict]:
    """日线棒升序（date/high/close/vol）——**本地 vipdoc 优先，线上 mootdx 回退**（2026-10-18）。

    线上补尾（2026-10-20 修复）：叙事组装期间由 `bars_need_upto(date)` 声明「本次要用到的
    最新交易日」；若本地末棒早于它（闭市后没跑通达信盘后下载），只从线上补「比本地末棒更新的
    日期」并合并，重叠日期一律以本地为准（历史数字不被线上改写）。未声明日期 → 不补（旧行为）。
    `JEV_BARS_ONLINE_TAIL=0` 可关（纯本地可复现/离线重放）。

    瞬时失败**不落空缓存**：一次客户端抖动若把 [] 缓存住，而 `_DAILY_CLIENT` 已缓存使
    `_TDX_DOWN_UNTIL` 负缓存不会介入，整轮回溯就永久降级成池口径、进程内再无恢复路径
    （2026-10-16 code review 实测）。合法空（新上市/当日无棒）仍缓存，避免逐股重取。

    2026-10-17：根数改由 `_bars_offset()`（`JEV_BARS_OFFSET`），缓存键含来源。
    2026-10-18 本地优先：缓存键 `("local", code)` / `("online:<offset>", code)`；本地不可用记入
    `_LOCAL_MISS`（免反复 stat，不落空棒），线上成功（含合法空）才落缓存。
    """
    if code not in _LOCAL_MISS:
        cached_local = _DAILY_BARS_CACHE.get(("local", code))
        local = cached_local if cached_local is not None else _local_daily_bars(code)
        if local:
            if cached_local is None:
                _DAILY_BARS_CACHE[("local", code)] = local
                _bars_count("local")
            if _tail_enabled():
                need = _BARS_NEED_UPTO.get()
                if need and local[-1]["date"] < need:
                    merged = _merged_with_online_tail(code, local, need)
                    if merged is not None:
                        return merged
            return local
        _LOCAL_MISS.add(code)   # 不铸造「空棒」：只是本地无此股文件，证据需求交线上回退
    return _online_daily_bars(code)


def _tail_enabled() -> bool:
    """线上补尾开关（默认开；`JEV_BARS_ONLINE_TAIL=0` 关 → 纯本地/离线可复现）。"""
    raw = os.environ.get(_BARS_TAIL_ENV)
    if raw is None or str(raw).strip() == "":
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _online_daily_bars(code: str) -> list[dict]:
    """线上 mootdx 日线（升序，尾 `_bars_offset()` 根）——本地不可用时的回退 / 补尾源。

    瞬时失败返回 [] 且**不缓存**（下一次调用重试），不把一次抖动变成整轮回调。
    """
    offset = _bars_offset()
    key = (f"online:{offset}", code)
    cached = _DAILY_BARS_CACHE.get(key)
    if cached is not None:
        return cached
    bars: list[dict] = []
    client = _tdx_daily_client()
    if client is not None:
        try:
            with _POSITION_LOCK:
                df = client.bars(symbol=code, frequency=9, start=0, offset=offset)
            if df is not None and len(df) > 0:
                for _, r in df.iterrows():
                    bars.append({
                        "date": f"{int(r['year']):04d}-{int(r['month']):02d}-{int(r['day']):02d}",
                        "high": float(r["high"]), "close": float(r["close"]),
                        "vol": float(r.get("vol") or 0),
                    })
                bars.sort(key=lambda b: b["date"])
                _bars_count(f"online:{offset}")
        except Exception:
            return []   # 不缓存：下次调用重试，不把一次抖动变成整轮回调
    _DAILY_BARS_CACHE[key] = bars
    return bars


def _merged_with_online_tail(code: str, local: list[dict], need_upto: str) -> list[dict] | None:
    """本地棒 + 线上尾部（只取 `> 本地末棒` 的日期）合并；拿不到补尾 → None（调用方保留本地）。

    口径：重叠日期**一律本地为准**（线上只当“今天这根”的补丁，不改历史数字）。
    拿不到就如实不补（调用方照旧 fail-visible 标不可算），并计 `tailMiss` 供溯源；
    失败按 code 负缓存 `_TAIL_FAIL_TTL` 秒，避免完整叙事里逐股重生线上重试。

    **量纲归一（必须）**：线上 `vol` 单位=手，本地 vipdoc `vol` 单位=股（实测比值恒 100）——
    直接拼接会把“量能”算成 1/100（实测 002242 曾被算出“今日为前3日均量的 0.01 倍”）。
    故用重叠日期的中位比值反推每只股的换算系数，只对尾部做归一；重叠不足时兜底 100
    并在 `_TAIL_VOL_SOURCE` 标 assumed（fail-visible，不静默假造一致）。
    """
    key = (f"local+tail:{need_upto}", code)
    cached = _DAILY_BARS_CACHE.get(key)
    if cached is not None:
        return cached
    if time.time() < _TAIL_FAIL_UNTIL.get(code, 0.0):
        return None
    last_local = local[-1]["date"]
    online_all = _online_daily_bars(code)
    tail = [b for b in online_all if b["date"] > last_local]
    if not tail:
        _TAIL_FAIL_UNTIL[code] = time.time() + _TAIL_FAIL_TTL
        _TAIL_FAIL_CODES.add(code)
        return None
    factor, src = _online_vol_factor(local, online_all)
    tail = [{**b, "vol": b["vol"] * factor} for b in tail]
    merged = local + tail
    _DAILY_BARS_CACHE[key] = merged
    with _BARS_LOCK:
        _BARS_SOURCE_COUNTS["local+onlineTail"] = _BARS_SOURCE_COUNTS.get("local+onlineTail", 0) + 1
        _TAIL_MERGED[code] = tail[-1]["date"]
        _TAIL_VOL_SOURCE[code] = src
    return merged


def _online_vol_factor(local: list[dict], online: list[dict]) -> tuple[float, str]:
    """线上 vol → 本地 vol 的换算系数（用重叠日期中位比值；无重叠时兜底 100 并标 assumed）。"""
    lo = {b["date"]: b for b in local}
    ratios = sorted(lo[b["date"]]["vol"] / b["vol"] for b in online
                    if b.get("date") in lo and b.get("vol") and lo[b["date"]].get("vol"))
    if ratios:
        med = ratios[len(ratios) // 2]
        if 0.01 <= med <= 1000:
            return round(med, 6), "overlap"
    return _ONLINE_VOL_TO_LOCAL_DEFAULT, "assumed"


def _div_num(v: Any) -> float:
    """'3.00元'/'5股'/'-' → float（百度日程每10股口径原值）；不可解析 → 0.0。"""
    import re

    if v is None:
        return 0.0
    s = re.sub(r"[^0-9.]", "", str(v))
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _div_event_list(date: str) -> dict[str, tuple[float, float]]:
    """date 当日 A 股除权除息事件 {code: (每股分红, 每股送转合计)}——P1-1 因子源
    （预登记 jev-ammo-p1-preregistration.md §一；百度除权除息日程 × 交易所公式）。

    百度口径=每10股（603337 XD杰克科 实证：分红 3.00 元 → 参考价按 /10 扣，35.00→34.70）；
    此处归一为每股口径。仅收 SH/SZ；配股（无配股价字段）不进公式→该股回退原口径。
    失败/空日/解析失败 → {}（fail-visible，调用方原口径）；空 {}=拉取成功确证无事件才进缓存，失败不缓存下次重试（review I-3）。
    """
    with _DIV_LOCK:
        if date in _DIV_LIST_CACHE:
            return _DIV_LIST_CACHE[date]
        if time.time() < _DIV_FAIL_UNTIL.get(date, 0.0):
            return {}  # 失败退避窗内：静默回退原口径（I-3 语义不变，防每链接重试风暴）
    out: dict[str, tuple[float, float]] = {}
    try:
        import akshare as ak

        df = ak.news_trade_notify_dividend_baidu(date=date.replace("-", ""))
        if df is not None and len(df) > 0 and not {"股票代码", "交易所", "分红", "送股", "转增"} <= set(df.columns):
            # review P2-2：百度改版列漂移 → 按失败处理（负缓存重试），不得静默当「无事件」
            raise ValueError(f"除权日程列漂移: {list(df.columns)[:8]}")
        for _, r in (df.iterrows() if df is not None and len(df) > 0 else []):
            if str(r.get("交易所") or "") not in ("SH", "SZ"):
                continue
            code = str(r.get("股票代码") or "")
            div, bonus = _div_num(r.get("分红")) / 10.0, _div_num(r.get("送股")) / 10.0 \
                + _div_num(r.get("转增")) / 10.0
            if code and (div or bonus):
                out[code] = (div, bonus)
    except Exception as exc:  # noqa: BLE001 — review I-3：失败与「当日真无事件」必须区分
        # 网络抖动等失败 → 直接返回不缓存（下次调用重试）、留痕；缓存空 {} 只允许出现在
        # 拉取成功但当日确无事件（原实现把失败永久缓存为 {}，当日若真有除权事件，
        # 板序/位置轴会用错参考价且无任何标记）。
        print(f"[div-events] {date} 除权日程拉取失败（负缓存 {_DIV_FAIL_TTL:.0f}s 后重试）："
              f"{type(exc).__name__}: {str(exc)[:150]}")
        with _DIV_LOCK:
            _DIV_FAIL_UNTIL[date] = time.time() + _DIV_FAIL_TTL
        return {}
    with _DIV_LOCK:
        _DIV_LIST_CACHE[date] = out
    return out


_ADJ_LOOKBACK = 45   # 除权参考价只算最近 N 个链接日


def _adj_prev_series(date: str, code: str, bars: list[dict]) -> dict[str, float]:
    """窗口内逐链接的除权参考价 {链接日 t: 交易所参考价}——仅 t 为该股除权日才有键（P1-1）。

    参考价 = round((原始前收 − 每股分红) / (1 + 每股送转), 2)（交易所除权除息公式）。

    2026-10-18（「开长窗」配套）：只算最近 `_ADJ_LOOKBACK` 个链接。本函数为**每个链接日**
    查一次百度除权日程（akshare 无批量口），而本地全历史棒把窗口从 60 → 400 根，外呼被放大
    6.7×（实测单日重算卡在日程拉取 >18 分钟）。消费方只用近端键——`_bar_verdict` 取
    `adj.get(date)`（末链接）、`jiuyan_consecutive_streaks` 回溯链路 ≤ 区间板数（实测 ≤12），
    `position/sequence_line_from_bars` ≤10 天——45 有 3.75× 余量。再远的链接回退原口径
    （与旧 60 根窗时代一致：窗口外的链接本来也没有除权修正）。
    """
    window = [b for b in bars if b["date"] <= date]
    out: dict[str, float] = {}
    band = limit_ratio(code) + 0.05
    start = max(1, len(window) - _ADJ_LOOKBACK)
    for i in range(start, len(window)):
        ev = _div_event_list(window[i]["date"]).get(code)
        prev_close = window[i - 1]["close"]
        cur_close = window[i].get("close")
        if (ev and isinstance(prev_close, (int, float)) and not isinstance(prev_close, bool)
                and prev_close > 0):
            div, bonus = ev
            ref = round((prev_close - div) / (1 + bonus), 2)
            # review P1-3 可信带（预登记 §一防线的逐链接实现）：当日真实涨跌幅（close/参考价）
            # 不得超涨跌幅板+5pp——配股混合事件（百度表无配股价）会算出越界参考价，回退原口径
            if (ref > 0 and isinstance(cur_close, (int, float)) and not isinstance(cur_close, bool)
                    and cur_close > 0 and abs(cur_close / ref - 1) <= band):
                out[window[i]["date"]] = ref
    return out


def stock_position_line(date: str, code: str) -> str:
    """弹药 6 壳：TDX 取数 → ammo.position_line_from_bars（纯计算，批次D I14）。
    P1-1：附除权参考价递推（窗口价格归一至今日基准），无事件/取数失败=原口径。"""
    try:
        bars = _daily_bars(code)
        adj = _adj_prev_series(date, code, bars) if bars else None
        return ammo.position_line_from_bars(date, code, bars, adj or None)
    except Exception as e:
        return f"个股位置：计算失败 {e}（fail-visible）"


def limitup_sequence_line(date: str, code: str, name: str | None, n: int = 10) -> str:
    """弹药 7 壳：TDX 取数 → ammo.sequence_line_from_bars（纯计算，批次D I14）。
    P1-1：逐链接用除权参考价（交易所公式精确昨收，板序假阴根治），
    无事件/取数失败回退原口径（原已知边缘语义）。"""
    try:
        bars = _daily_bars(code)
        adj = _adj_prev_series(date, code, bars) if bars else None
        return ammo.sequence_line_from_bars(date, code, name, n, bars, adj or None)
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
        # P1-1：优先除权参考价（交易所公式），非除权日/取数失败回退原始前收
        adj = _adj_prev_series(date, code, bars)
        if date in adj:
            return adj[date]
        return bars[-2]["close"]
    return None


def stock_board_shape_line(date: str, code: str, name: str | None,
                           prev_close: float | None) -> str:
    """弹药 8 壳：TDX 取数 → ammo.board_shape_line_from_bars（纯计算，批次D I14）。"""
    try:
        return ammo.board_shape_line_from_bars(date, code, name, prev_close,
                                               _intraday_bars(code))
    except Exception as e:
        return f"板型：计算失败 {e}（fail-visible）"


def board_position(jiuyan_doc, code: str, db=None, date: str | None = None,
                   dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """弹药 5：板块地位（所属韭研板块今日涨停家数 + 该股按涨停时间的封板序）。

    v3.2 D7：传入 db/date 时附「昨日同板块家数」——`buy_side_logic` 的「同板块多股集体
    异动」与「无板块协同」判据需要昨日对照才能区分板块启动中的跟随与退潮中的跟随。
    """
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
    prev_txt = ""
    if db is not None and date:
        info = board_prev_info(db, date, str(best["board"] or ""), dataset_id)
        if info["ok"]:
            if info.get("reason") == "t2_fallback":
                if info.get("t1Found") is False:
                    # T-1 名单整体缺失（非「无同名板块」，审查 SF6：两种混合态分开措辞）
                    prev_txt = (f'（T-1 名单缺失，取前 2 交易日（{info["day"]}）'
                                f'同板块涨停 {info["count"]} 家）')
                else:
                    # v3.2b：T-1 名单在但无同名板块、T-2 命中 → 显式标口径，不冒充「昨日」
                    prev_txt = (f'（前 2 交易日（{info["day"]}）同板块涨停 {info["count"]} 家'
                                f' · T-1 无同名板块）')
            else:
                prev_txt = f'（昨日同板块涨停 {info["count"]} 家）'
        elif info["reason"] == "no_prev_doc":
            prev_txt = "（昨日同板块 不可比：上一交易日名单缺失）"
        elif info["reason"] == "board_absent":
            # 韭研板块命名昨今会漂移（实测同名可比率 65.9%）——不可比就写不可比
            prev_txt = "（昨日同板块 不可比：昨日无该板块名）"
    return (f'板块地位：所属韭研板块「{best["board"]}」今日涨停 {best["n"]} 家{prev_txt}，'
            f'该股板块内 {pos}')


# ── 投喂槽位（2026-10-20 用户裁决：12:30 午盘投喂 + 16:00 收盘幂等跳过） ──────────
# 单日每股只投喂一次：两个槽位共用 `_id={date}:{code}` 与同一 `done` 判据（status=ok），
# 午盘已投喂的股票在收盘链自动跳过（幂等），不靠额外状态表。
SLOT_FINAL = "final"
SLOT_MIDDAY = "midday"
_SLOTS = (SLOT_FINAL, SLOT_MIDDAY)
# 午盘可投喂窗（fetchedAt 的 HH:MM）：唯一来源 = jiuyan_store.MIDDAY_NOON_WINDOW
# （存储层的「午盘事实源保护」与这里的投喂门控必须同一口径，否则会出现
#  「入库时认为是真午盘、投喂时又认为不是」的漂移）。
_MIDDAY_FETCH_WINDOW = jiuyan_store.MIDDAY_NOON_WINDOW


def midday_source_state(db, date: str) -> dict:
    """午盘名单可投喂性（2026-10-20）：`{date}:midday` 存在且 fetchedAt 落在午盘窗内。

    实测缺陷（2026-10-14/10-16/10-19）：采集进程若在收盘后才启动，当日「午盘尝试」会用
    **收盘数据**补写 `midday` 文档（fetchedAt=15:20/20:04/20:23，名单与 final 逐字相同）。
    拿这种文档做「12:30 午盘投喂」等于把收盘数据冒充午盘证据，因此按 fetchedAt 窗口判定：
    窗口外一律 fail-visible 拒绝（交收盘链投喂），不靠「文档存在」冒充时点。
    """
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:{SLOT_MIDDAY}"}, {"fetchedAt": 1})
    if not doc:
        return {"ok": False, "found": False, "fetchedAt": None,
                "reason": "no_midday_doc", "detail": f"{date}:midday 缺失"}
    fetched = str(doc.get("fetchedAt") or "")
    import re  # 局部 import 与 _jiuyan_days_boards 同规（避免模块顶部再引入未用符号）
    m = re.search(r"(\d{2}):(\d{2})", fetched[:19])
    hhmm = f"{m.group(1)}:{m.group(2)}" if m else ""
    lo, hi = _MIDDAY_FETCH_WINDOW
    if not hhmm or not (lo <= hhmm <= hi):
        return {"ok": False, "found": True, "fetchedAt": fetched,
                "reason": "midday_doc_not_noon",
                "detail": f"fetchedAt={fetched or '?'} 不在午盘窗 {lo}~{hi}"}
    return {"ok": True, "found": True, "fetchedAt": fetched, "reason": None, "detail": None}


def build_midday_narrative(db, date: str, code: str, stock: dict, board: str, rank,
                           dataset_id: str = DEFAULT_DATASET_ID,
                           jiuyan_doc: dict | None = None,
                           expound_trace: bool = True) -> str:
    """午盘投喂弹药（12:30 槽位）：只写午盘确实拿得到的证据，缺的明确标注不可得。

    午盘（11:30-13:00）与收盘的可得证据差：
    - 盘面事实行（market_facts_line/market_metrics）依赖 15:00 帧 → 午盘不存在；
    - THS 封板梯队仅在 15:00 帧生成 → 午盘不可得；
    - 当日板型需收盘 5 分钟棒 → 午盘不可判。
    **v3.2 D10（2026-10-20 用户裁决）：位置轴/板序改用 T-1 收盘口径**——旧口径把这两项
    也判「午盘不可得」，但它们只依赖历史日线（20 日窗口），T-1 收盘就能完整算出；
    唯一物理不可得的是「当日盘中棒」。行内显式标 T-1，**不拿 T-1 冒充当日**（§4.0）。
    同时把 4 行「不可得」声明压成首行 1 处，省 ≈90 字/只。
    **v3.2b（2026-10-21 缺陷修复）：D6 交易日轴 + D8 解析续期接线进午盘槽位**——
    v3.2 只把这两条日期锚接进了收盘叙事，午盘 51 只实测 0/51，导致午盘
    `catalyst_freshness` 比 收盘少两条日期证据、unclear 率 13.7% vs 收盘 3.9%
    （半接线复现，同 §3-① 家族）。位置/板序/交易日轴/解析续期均为 T-1 及更早的
    历史日线/名单数据，午盘真实可得，不属于「不可得项」。
    """
    jy = jiuyan_doc or {}
    fetched = str(jy.get("fetchedAt") or "")
    noon = fetched[11:16] if len(fetched) >= 16 else "时点未知"
    num_txt = str(stock.get("num") or "").strip()
    if num_txt and "板" not in num_txt:
        num_txt += "板"
    day_txt = str(stock.get("day") or "").strip()
    if day_txt and "天" not in day_txt:
        day_txt += "天"
    if num_txt and "天" in num_txt:   # 韭研 num 自带「2天2板」完整口径，与 day 拼接会重复
        day_num = f"，{num_txt}"
    else:
        day_num = f"，{day_txt}{num_txt}" if (day_txt or num_txt) else ""
    expound = str(stock.get("expound") or "").strip()
    # 位置轴/板序：T-1 收盘口径（历史日线可得，当日盘中值不可得）
    prev = trading_dates_before(db, date, 1, dataset_id=dataset_id)
    t1 = prev[-1] if prev else None
    if t1:
        # T-1 也可能本地未落棒（本地落后 ≥2 日）：声明后线上可补 T-1，仍不碰当日
        with bars_need_upto(t1):
            pos_raw = stock_position_line(t1, code)
            seq_raw = limitup_sequence_line(t1, code, stock.get("name"))
        pos = (f"个股位置：上一交易日（{t1}）收盘口径 · {pos_raw.split('：', 1)[1]}"
               if "fail-visible" not in pos_raw
               else f"个股位置：上一交易日（{t1}）日线不可用（fail-visible，今日盘中值亦不可得）")
        # 纯计算层文案写的是「末位今日」——午盘用 T-1 口径时必须换掉，否则行内自相矛盾
        seq_body = seq_raw.split("：", 1)[1].replace("末位今日", f"末位={t1}")
        seq = (f"板序：上一交易日（{t1}）收盘口径 · {seq_body}"
               if "fail-visible" not in seq_raw
               else f"板序：上一交易日（{t1}）日线不可用（fail-visible，今日盘中值亦不可得）")
    else:
        pos = "个股位置：上一交易日不可算（交易日轴缺失，fail-visible）"
        seq = "板序：上一交易日不可算（交易日轴缺失，fail-visible）"
    trace = (expound_trace_line(db, date, code, expound, dataset_id=dataset_id)
             if expound_trace else None)
    lines = [
        f"{date} 交易日午盘 · 打标时点=韭研 {noon} 午盘名单 · 午盘不可得项：收盘盘面事实行/"
        f"THS 封板梯队/当日板型（fail-visible）",
        date_axis_line(db, date, dataset_id),
        f"该股：{stock.get('name')}（{code}），午盘涨停价 {stock.get('price')}{day_num}，"
        f"触板时间 {stock.get('time')}",
        f"身位：韭研午盘名单口径 {num_txt or '首板（韭研未标 N天M板）'}",
        pos,
        seq,
        f"（午盘名单口径，家数=已触板）{board_position(jy, code, db=db, date=date, dataset_id=dataset_id)}",
        seal_time_line(jy, code, scope="midday"),
        "韭研解析全文：",
        expound if expound else "（韭研解析缺失，fail-visible）",
    ]
    if trace:
        lines.insert(-2, trace)   # 解析续期行紧贴「韭研解析全文：」之前（与收盘槽位同序）
    return "\n".join(lines)


def build_pilot_narrative(db, date: str, code: str, stock: dict, board: str, rank,
                          dataset_id: str = DEFAULT_DATASET_ID,
                          jiuyan_doc: dict | None = None,
                          slot: str = SLOT_FINAL,
                          expound_trace: bool = True) -> str:
    """v3.2 弹药叙事（2026-10-20 语料代际）：市场坐标 + 交易日轴 + 该股 + 身位 + 个股位置
    + 板序 + 当日板型 + 板块地位（含昨日家数）+ 封板时间坐标 + 解析续期 + 解析全文。

    v3.2 瘦身/增益（预注册 `docs/hotlist-jev/jev-driver-label-v32-preregistration.md`）：
    - 删：整行盘面事实（四题零独有引用）→ 轻量市场坐标；热榜最高排名（零引用且跨轨）；
      THS 主力净额（零引用且无单位）；
    - 增：交易日轴（freshness 判据的「≤2 交易日」）、封板时间分位（buy_side「偏晚」）、
      同板块昨日家数（板块联动）、解析续期（freshness/driver 的新意锚）；
    - 修：THS 整池未采集日不再写成「今日触板未封/炸板」（事实错误文案）。
    `expound_trace=False`（承接路径）：解析逐字相同已由承接压缩标记声明，不再多给一行。

    批次C I10（顺手）：jiuyan_doc 由调用方传入（day_population 已读过同一文档），
    缺省时兼容旧路径自行读取——消除每股一次整日文档的 N+1 查询。

    2026-10-20（用户裁决「12:30 午盘投喂 + 收盘幂等跳过」）：`slot=midday` 分流到
    `build_midday_narrative`。
    """
    if slot == SLOT_MIDDAY:
        jy_mid = jiuyan_doc if jiuyan_doc is not None else db["jiuyan_action"].find_one(
            {"_id": f"{date}:{SLOT_MIDDAY}"}, {"fields": 1, "fetchedAt": 1}) or {}
        # v3.2b：承接路径（expound_trace=False）对午盘同样生效——解析逐字相同已由承接
        # 压缩标记声明，不重复给 trace 行（与收盘槽位同口径）。
        return build_midday_narrative(db, date, code, stock, board, rank,
                                      dataset_id=dataset_id, jiuyan_doc=jy_mid,
                                      expound_trace=expound_trace)
    jy = jiuyan_doc if jiuyan_doc is not None else db["jiuyan_action"].find_one(
        {"_id": f"{date}:final"}, {"fields": 1}) or {}
    ths = ths_positions(db, date, dataset_id).get(code)
    day_txt = str(stock.get("day") or "")
    if day_txt and "天" not in day_txt:
        day_txt += "天"
    num_txt = str(stock.get("num") or "")
    if num_txt and "板" not in num_txt:
        num_txt += "板"
    if num_txt and "天" in num_txt:  # 韭研 num 可能自带「2天2板」完整口径，与 day 拼接会重复
        day_num = f'，{num_txt}'
    else:
        day_num = f'，{day_txt}{num_txt}' if (day_txt or num_txt) else ""
    if ths:
        ladder_txt = str(ths["continueDay"]) if ths["continueDay"] is not None else "?"
        if "连板" not in ladder_txt and "板" not in ladder_txt:
            ladder_txt += "连板"
        # v3.2 D4b：删「主力净额」——四题零引用、无单位、无可比基线（73794032 裸数字）
        ths_line = (f'THS 封板梯队：{ladder_txt} · 首封 {ths["firstSeal"]}'
                    f' · 所属板块 {ths["industry"] or "缺"}')
    else:
        if limit_ratio(code) == 0.30:
            # 北交所：THS 连板封板池结构性不覆盖（10-16/19/20 三日 327 只 0 只 bj）——
            # 真涨停的 bj 股落「池 ok 未入」分支会被写成触板未封嫌疑，且缓冲句
            # 「与板序冲突以板序为准」对 bj 常落空（北交所日线无源，板序行 fail-visible）。
            # 身位直接改韭研口径（同 D2 回退哲学）；不写前缀副本，判定单源 = limit_ratio。
            ths_line = ("THS 封板梯队：THS 池不覆盖北交所（覆盖边界，非触板未封口径）"
                        f"· 身位证据改用韭研口径 "
                        f"{num_txt or '首板（韭研未标 N天M板）'}")
        else:
            state = ths_ladder_state(db, date, dataset_id)
            if state["ok"]:
                ths_line = ("未进 THS 封板池（梯队池已采集，该股未入；可能触板未封/炸板口径，"
                            "与下方板序冲突时以板序为准）")
            else:
                # v3.2 D2：整池未采集≠该股未进池。旧文案把 457 只当日涨停股写成「今日触板未封/炸板」
                ths_line = (f'THS 封板梯队未采集（{state["reason"]}，fail-visible，'
                            f'非「触板未封」）· 身位证据改用韭研口径 '
                            f'{num_txt or "首板（韭研未标 N天M板）"} + 下方板序行「当前连板」')
    expound = str(stock.get("expound") or "").strip()
    expound_line = expound if expound else "（韭研解析缺失，fail-visible）"
    # v3.2 D1：声明「本次叙事要用到的最新交易日」→ 本地 vipdoc 末棒落后时按需线上补尾。
    # 必须在叙事组装处声明（不是 run() 外层）：`_BARS_NEED_UPTO` 是 ContextVar，
    # `ThreadPoolExecutor` **不复制**调用方上下文 → 写在 work() 外对 worker 线程无效。
    # 实测缺陷：10-20 当日 77/77 只位置/板序/板型全灭，而同日 relay（已接线）三行齐全。
    with bars_need_upto(date):
        lines = [
            f"{date} 交易日 · {market_coordinate_line(db, date, dataset_id)}",
            date_axis_line(db, date, dataset_id),
            f"该股：{stock.get('name')}（{code}），今日涨停价 {stock.get('price')}{day_num}，"
            f"涨停时间 {stock.get('time')}",
            f"身位：{ths_line}",
            stock_position_line(date, code),
            limitup_sequence_line(date, code, stock.get("name")),
            stock_board_shape_line(date, code, stock.get("name"),
                                   _prev_close_of_date(date, code)),
            board_position(jy, code, db=db, date=date, dataset_id=dataset_id),
            seal_time_line(jy, code),
        ]
    if expound_trace:
        trace = expound_trace_line(db, date, code, expound, dataset_id=dataset_id)
        if trace:
            lines.append(trace)
    lines += ["韭研解析全文：", expound_line]
    return "\n".join(lines)


def _db():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    return get_runtime_mongodb_database()


def carry_forward_enabled() -> bool:
    """A+B 承接/压缩开关（2026-10-20 用户裁决；默认开，`JEV_CARRY_FORWARD_ENABLED=0` 关闭）。"""
    return os.environ.get("JEV_CARRY_FORWARD_ENABLED", "1") != "0"


# 反包板池承接窗：反包股在候选窗（前 2~5 交易日在板）内必有打标记录，取 5 个交易日
# 内最近一次判定复制（2026-10-21 用户裁决「池内反包股免投喂，直接复制前日打标结果」）。
_REWRAP_CARRY_MAX_GAP = 5


def _rewrap_carry_one(db, col, date: str, code: str, entry: dict, slot: str,
                      dataset_id: str, full_qs_hash: str,
                      include_stock_phase: bool, jy_doc: dict | None,
                      rank: int | None) -> bool:
    """反包板池免投喂承接（2026-10-21 用户裁决）：池内股直接复制前日打标结果，零 jev 调用。

    与 A+B 承接（carry_decision）的区别：**不要求解析逐字相同、不要求原料代际一致**——
    用户裁决反包股（前几日有过连板、已被打标过）跳过重判以省成本；为不静默伪装成当日
    独立判定，文档显式盖 `labelSource="rewrap_carry"` / `carriedFrom` / `rewrapCarry=True`。
    守卫（任一不满足 → 返回 False 回落全量实判，不静默降级）：
    - 窗内（≤`_REWRAP_CARRY_MAX_GAP` 交易日）存在 status=ok 的前日标签；
    - 前日 `answers` 四题齐全（choice 均在）；
    - 前日 freshness∉{unclear, fresh_catalyst}（2026-10-22 用户裁决：日期相对题跨日失真，
      unclear 承接=信息缺失复制）；
    - 前日 `questionSetHash` == 当前完整题集 hash（答案形状兼容；判据换代日自动回落实判）。
    """
    prev_dates = trading_dates_before(db, date, _REWRAP_CARRY_MAX_GAP, dataset_id=dataset_id)
    if not prev_dates:
        return False
    order = {d: i for i, d in enumerate(prev_dates)}
    prev: dict | None = None
    # 排除 labelSource=rewrap_carry 的前标（审查 SF7）：防链式承接放大——只承接
    # fresh_judgment / carry_forward 的原生判定，判定年龄不超窗
    for d in col.find({"code": code, "status": "ok",
                       "tradingDate": {"$in": prev_dates},
                       "labelSource": {"$ne": "rewrap_carry"}}, _CARRY_PREV_PROJECTION):
        if prev is None or order.get(str(d.get("tradingDate")), -1) > order.get(
                str(prev.get("tradingDate")), -1):
            prev = d
    if not prev:
        return False
    prev_answers = prev.get("answers") or {}
    need = list(CARRY_KEYS) + ["buy_side_logic"]
    if any(not (prev_answers.get(k) or {}).get("choice") for k in need):
        return False
    # 新鲜度守卫（2026-10-22 用户裁决）：freshness 是日期相对题，跨日承接语义失真——
    # ① 前标判 unclear =「没判出来」，承接等于把信息不足复制到新一天（当日叙事的
    #   交易日轴/解析续期日期锚往往可解，例：2026-10-22 林州重机承接 10-16 unclear）；
    # ② 前标判 fresh_catalyst =「事件首现距今≤2 个交易日」，该距离随承接日漂移，
    #   跨日复制后「今日新催化」必然失真。
    # 任一命中 → 回落全量实判，不静默降级。
    if (prev_answers.get("catalyst_freshness") or {}).get("choice") in (
            "unclear", "fresh_catalyst"):
        return False
    # 相位题守卫（审查 MF1）：产线已开相位题时，承接文档的 questionsRaw 含相位题；
    # 前标无相位答案 → 回落实判，不得盖 ok 戳静默给 None（正常路径缺题=degraded 契约）
    if include_stock_phase and not (prev_answers.get("stock_phase_position") or {}).get("choice"):
        return False
    if prev.get("questionSetHash") and prev["questionSetHash"] != full_qs_hash:
        return False
    stock = entry["stock"]
    answers = dict(prev_answers)
    doc = {"_id": f"{date}:{code}", "origin": "driver_label_jiuyan_v3_pilot", "tradingDate": date,
           "code": code, "name": stock.get("name"), "ammoVersion": AMMO_VERSION,
           "labelSlot": slot, "jiuyanSourceId": f"{date}:{slot}",
           "jiuyanFetchedAt": (jy_doc or {}).get("fetchedAt"),
           "questionSetVersion": QUESTION_SET_VERSION_DRIVER,
           "questionSetHash": full_qs_hash,
           "askedQuestionSetHash": None,   # 未下发任何题集（免投喂）
           "expoundSignature": expound_signature(stock.get("expound")),
           "jiuyanContext": {"board": entry["board"], "day": stock.get("day"),
                             "num": stock.get("num"), "time": stock.get("time"),
                             "inHotlist": rank is not None, "rank": rank},
           "status": "ok",
           # 叙事=当日口径证据（人类复核用；零 token 成本），判题结论=前日承接
           "narrative": build_pilot_narrative(db, date, code, stock, entry["board"], rank,
                                              dataset_id=dataset_id, jiuyan_doc=jy_doc,
                                              slot=slot),
           "questionsRaw": (QUESTIONS_STOCK_WITH_PHASE if include_stock_phase else QUESTIONS_STOCK),
           "answers": answers,
           "label": answers.get("driver_type", {}).get("choice"),
           "driverProbabilities": answers.get("driver_type", {}).get("probabilities"),
           "catalystDepth": answers.get("catalyst_depth", {}).get("choice"),
           "catalystDepthProbabilities": answers.get("catalyst_depth", {}).get("probabilities"),
           "freshness": answers.get("catalyst_freshness", {}).get("choice"),
           "buySideLogic": answers.get("buy_side_logic", {}).get("choice"),
           "buySideProbabilities": answers.get("buy_side_logic", {}).get("probabilities"),
           "model": "rewrap-carry", "usage": {"input_tokens": 0, "output_tokens": 0},
           "latencyMs": 0, "errorCode": None, "errorDetail": None, "responseRaw": None,
           "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
    doc.update({
        "labelSource": "rewrap_carry",
        "rewrapCarry": True,
        "carriedFrom": str(prev.get("tradingDate") or ""),
        "carriedLabelSlot": prev.get("labelSlot"),   # 审查 SF8：前标槽位可追溯（午盘口径证据行更少）
        "carriedOriginDate": (prev.get("carriedOriginDate")
                              or prev.get("carriedFrom")
                              or prev.get("tradingDate")),  # 原始判定日（防链式年龄失真）
        "carriedQuestionKeys": need,
        "reevaluatedQuestionKeys": [],
        "carriedQuestionSetHash": prev.get("questionSetHash"),
    })
    if include_stock_phase:
        ans_p = prev_answers.get("stock_phase_position") or {}
        doc.update({
            "stockPhasePosition": ans_p.get("choice"),
            "stockPhaseProbabilities": ans_p.get("probabilities"),
            "stockPhaseConfidence": ans_p.get("confidence"),
            "stockPhaseQuestionSetHash": _questions_hash(QUESTIONS_STOCK_PHASE),
            "stockPhaseAmmoVersion": AMMO_VERSION,
            "stockPhaseModel": "rewrap-carry",
            "stockPhaseUsage": {"input_tokens": 0, "output_tokens": 0},
            "stockPhaseLatencyMs": 0,
        })
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return True


# 承接候选读取的字段（只取判定与合并所需，不拉全套大字段）
_CARRY_PREV_PROJECTION = {
    "code": 1, "tradingDate": 1, "status": 1, "questionSetHash": 1, "ammoVersion": 1,
    "expoundSignature": 1, "narrative": 1, "answers": 1, "label": 1, "labelSlot": 1,
    "driverProbabilities": 1, "catalystDepth": 1, "catalystDepthProbabilities": 1,
    "freshness": 1, "buySideLogic": 1, "buySideProbabilities": 1, "origin": 1,
}


def _carry_prev_docs(db, col, date: str, dataset_id: str = DEFAULT_DATASET_ID,
                     max_gap: int = MAX_GAP_TRADING_DAYS) -> tuple[dict[str, dict], list[str]]:
    """最近 max_gap 个交易日的已判文档 {code: doc}（同 code 取最近一日）+ 交易日轴（升序）。

    承接只看**真·最近一次判定**：超过 max_gap 个交易日的旧判定不再承接（题材可能已换代）。
    PHASE 哨兵日级文档无 code，自然被过滤。
    """
    prev_dates = trading_dates_before(db, date, max_gap, dataset_id)
    if not prev_dates:
        return {}, prev_dates
    order = {d: i for i, d in enumerate(prev_dates)}
    pool: dict[str, dict] = {}
    for d in col.find({"tradingDate": {"$in": prev_dates}, "status": "ok"},
                      _CARRY_PREV_PROJECTION):
        code = str(d.get("code") or "")
        if not code:
            continue
        cur = pool.get(code)
        if cur is None or order.get(str(d.get("tradingDate")), -1) > order.get(
                str(cur.get("tradingDate")), -1):
            pool[code] = d
    return pool, prev_dates


def _carry_gap(prev_doc: dict | None, prev_dates: list[str]) -> int | None:
    """上一标签日距当日几个交易日（1=前一日）——不在轴内返回 None（不承接）。"""
    if not prev_doc or not prev_dates:
        return None
    d = str(prev_doc.get("tradingDate") or "")
    try:
        return len(prev_dates) - prev_dates.index(d)
    except ValueError:
        return None


def day_population(db, date: str, slot: str = SLOT_FINAL) -> list[dict]:
    """当日名单人口（个股 × 板块）。slot=midday 读午盘名单、final 读收盘名单（2026-10-20）。"""
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:{slot}"})
    if not doc:
        return []
    out = []
    for field in doc.get("fields") or []:
        for stock in field.get("stocks") or []:
            out.append({"stock": stock, "board": field.get("name") or ""})
    return out


def hotlist_ranks(db, date: str, codes: list[str],
                  dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, int]:
    ranks: dict[str, int] = {}
    for r in db["snapshot_stock_rows"].find(
            {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date,
             "code": {"$in": codes}, "rank": {"$exists": True}},
            {"code": 1, "rank": 1}):
        rank, code = r.get("rank"), r.get("code")
        if isinstance(rank, int) and rank > 0 and (code not in ranks or rank < ranks[code]):
            ranks[code] = rank
    return ranks


def _label_one(db, col, acc, token, date, code, stock, board, rank,
               include_stock_phase: bool = False,
               dataset_id: str = DEFAULT_DATASET_ID, jiuyan_doc: dict | None = None,
               slot: str = SLOT_FINAL,
               carry: dict | None = None) -> tuple[bool, int]:
    """单只个股打标一次 jev 调用；include_stock_phase=True 时题目集升级为五题合并同 call
    （QUESTIONS_STOCK_WITH_PHASE，2026-10-04 用户裁决），相位答案随主 doc 同落——共享 narrative
    输入，相位边际成本≈题干+答案。usage/latency 为五题整 call 实付口径（stockPhaseUsage 同值）。
    批次B：新文档盖 ammoVersion 戳（原料代际，缺戳=旧代，fail-visible）。
    批次C：返回 (ok, 本次实付 tokens)（I12 成本口径=本次运行，不再全集合扫描）；
    doc 盖 questionSetVersion/questionSetHash（I15 判据代际）。
    2026-10-20：slot=midday 时叙事换午盘口径（build_midday_narrative），文档盖
    labelSlot/jiuyanSourceId/jiuyanFetchedAt，供追溯「这条标签用的是午盘还是收盘名单」。
    2026-10-20 A+B（carry 非空时）：只问 `buy_side_logic`（+相位），叙事走 B 压缩；
    driver/depth/freshness 从 `carry['prev']` 承接，文档盖 labelSource/carriedFrom/
    carriedQuestionKeys/reevaluatedQuestionKeys（承接可追溯、可分组，不伪装成当日独立判定）。
    """
    if carry:
        questions = (QUESTIONS_STOCK_BUYSIDE_WITH_PHASE if include_stock_phase
                     else QUESTIONS_STOCK_BUYSIDE)
    else:
        questions = QUESTIONS_STOCK_WITH_PHASE if include_stock_phase else QUESTIONS_STOCK
    narrative = build_pilot_narrative(db, date, code, stock, board, rank,
                                      dataset_id=dataset_id, jiuyan_doc=jiuyan_doc,
                                      slot=slot,
                                      # 承接路径：解析逐字相同已由 B 压缩标记声明，不再多给一行
                                      expound_trace=not carry)
    compression: dict | None = None
    if carry:
        narrative, compression = compress_narrative(narrative, carry["prevDate"])
    # 2026-10-10 起走 _dispatch_jev 分流（JEV_TYPESAFE_KEY 优先官方直连，否则 CF）；
    # acc/token 参数仅为调用方签名兼容，通道配置统一由 dispatch 自取 env。
    env, ms = _dispatch_jev(narrative, questions)
    # 缺题=partial_answers（degraded）：done 集合不视为已完成，下轮重跑补齐（2026-10-05 批次A C2）
    parsed = parse_jev_response(env, ms, expected_keys=set(questions))
    used = _usage_tokens(parsed.get("usage"))
    answers = parsed.get("answers") or {}
    carried_answers: dict = {}
    if carry:
        prev_answers = (carry.get("prev") or {}).get("answers") or {}
        carried_answers = {k: prev_answers[k] for k in CARRY_KEYS if prev_answers.get(k)}
        # 承接题 + 本次实判题合并：顶层字段/answers 均为完整四题口径，下游消费零变化；
        # 来源差异由 labelSource/carriedQuestionKeys 显式标注
        answers = {**carried_answers, **answers}
    doc = {"_id": f"{date}:{code}", "origin": "driver_label_jiuyan_v3_pilot", "tradingDate": date,
           "code": code, "name": stock.get("name"), "ammoVersion": AMMO_VERSION,
           # 投喂槽位（2026-10-20）：midday=12:30 午盘投喂（收盘幂等不重复投喂）、final=收盘投喂；
           # jiuyanSourceId/jiuyanFetchedAt 记原料文档与抓取时点，追溯「标签用的哪一版名单」
           "labelSlot": slot, "jiuyanSourceId": f"{date}:{slot}",
           "jiuyanFetchedAt": (jiuyan_doc or {}).get("fetchedAt"),
           "questionSetVersion": QUESTION_SET_VERSION_DRIVER,
           # questionSetHash 始终=完整四题集（判据代际，承接文档与实判文档可比）；
           # 本次实际下发的题集另记 askedQuestionSetHash（承接路径=单题集）
           "questionSetHash": _questions_hash(
               QUESTIONS_STOCK_WITH_PHASE if include_stock_phase else QUESTIONS_STOCK),
           "askedQuestionSetHash": _questions_hash(questions),
           "expoundSignature": expound_signature(stock.get("expound")),
           "jiuyanContext": {"board": board, "day": stock.get("day"), "num": stock.get("num"),
                             "time": stock.get("time"), "inHotlist": rank is not None, "rank": rank},
           "status": "ok" if parsed["ok"] else "degraded",
           "narrative": narrative, "questionsRaw": questions,
           # answers 原样落库（P0-2/P0-3，jev-questionset-ammo-confidence-review.md §五）：
           # 对齐情绪链先例，保全模型自报 confidence/缺失 probabilities/未来新字段，
           # 只向前生效，历史文档不可回补。
           # 承接路径下 `answers` = 承接题（carriedAnswers 同值）+ 本次实判题的完整四题口径。
           "answers": answers,
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
    if carry:
        # 承接痕迹（A）：来源、上一标签日、承接/实判分别哪些题、上一判定题集 hash、压缩统计
        doc.update({
            "labelSource": "carry_forward",
            "carriedFrom": carry["prevDate"],
            "carriedQuestionKeys": list(CARRY_KEYS),
            "reevaluatedQuestionKeys": (["buy_side_logic", "stock_phase_position"]
                                        if include_stock_phase else ["buy_side_logic"]),
            "carriedQuestionSetHash": (carry.get("prev") or {}).get("questionSetHash"),
            "carriedAnswers": carried_answers,
            "narrativeCompression": compression,
        })
    else:
        doc["labelSource"] = "fresh_judgment"
    if include_stock_phase:
        # 相位答案随主 call 落档（字段与单题版 run_stock_phase_pilot 逐字段对齐，聚合层无感）；
        # 相位答案缺失时 Position=None（聚合层 no_data fail-visible 已处理，不整 call 降级）
        ans_p = answers.get("stock_phase_position") or {}
        doc.update({
            "stockPhasePosition": ans_p.get("choice"),
            "stockPhaseProbabilities": ans_p.get("probabilities"),
            "stockPhaseConfidence": ans_p.get("confidence"),
            "stockPhaseQuestionsRaw": QUESTIONS_STOCK_PHASE,
            "stockPhaseQuestionSetHash": _questions_hash(QUESTIONS_STOCK_PHASE),
            "stockPhaseAmmoVersion": AMMO_VERSION,
            "stockPhaseModel": parsed.get("model"),
            "stockPhaseUsage": parsed.get("usage"),
            "stockPhaseLatencyMs": ms,
            "stockPhaseErrorCode": parsed.get("errorCode"),
            "stockPhaseErrorDetail": parsed.get("errorDetail"),
            "stockPhaseComputedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    col.replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return bool(parsed["ok"]), used


def run(start: str, end: str, dry_run: bool, token: str, acc: str, workers: int = 2,
        with_stock_phase: bool = False, dataset_id: str = DEFAULT_DATASET_ID,
        confirm_budget: bool = False, max_stocks: int | None = None,
        force: bool = False, only_codes: set[str] | None = None,
        slot: str = SLOT_FINAL, carry_forward: bool | None = None):
    """个股驱动打标主循环。

    slot（2026-10-20 用户裁决）：
    - `final`（默认）：收盘链（16:00 盘后链）投喂收盘涨停名单；
    - `midday`：12:30 午盘投喂午盘涨停名单，叙事走午盘口径（build_midday_narrative），
      并以 `midday_source_state` 卡住「收盘后才补写的伪午盘文档」。
    **两个槽位共用 `_id={date}:{code}` 与同一 done 判据（status=ok）** → 午盘已投喂的
    个股在收盘运行时自动跳过（幂等），单日每股只烧一次 token。`force=True`（口径代际
    重放）是唯一例外，不受幂等约束。

    carry_forward（A+B，2026-10-20 用户裁决）：None=读环境开关（`JEV_CARRY_FORWARD_ENABLED`，
    默认开），True/False 显式覆盖；`force=True` 时一律全量实判（不承接、不压缩）。
    """
    db = _db()
    col = db["hotlist_jev_driver_labels"]
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end},
         "_id": {"$regex": f":{slot}$"}},
        {"tradingDate": 1}) if d.get("tradingDate")})
    if not dates:
        print(f"窗口 {start}~{end} 无 jiuyan_action {slot} 文档，退出（fail-visible）")
        return
    n_ok = n_deg = 0
    n_carried = n_rejudged = 0   # A+B 口径计数（承接 vs 全量实判）
    n_rewrap_carried = n_rewrap_miss = 0   # 反包板池免投喂承接 vs 回落实判（2026-10-21）
    carry_on = (carry_forward_enabled() if carry_forward is None else bool(carry_forward)) and not force
    run_tokens: list[int] = []  # 批次C I12：本次运行实付（total_tokens 优先，否则 input+output）
    for di, date in enumerate(dates):
        if slot == SLOT_MIDDAY:
            state = midday_source_state(db, date)
            if not state["ok"]:
                # 午盘名单不可信/缺失：绝不拿收盘补写的「伪午盘」或昨日数据冒充（AGENTS §4.0）
                print(f"[{di + 1}/{len(dates)}] {date} 午盘名单不可投喂"
                      f"（{state['reason']}：{state['detail']}），跳过——收盘链会另行投喂")
                continue
        pop = day_population(db, date, slot)
        if not pop:
            print(f"[{di + 1}/{len(dates)}] {date} 无韭研 {slot} 文档，跳过（披露）")
            continue
        # 反包板池一日两更（2026-10-21 用户裁决）：每个 date 先更池再打标——12:30 午盘链
        # 自然更新 `{date}:midday`（触板口径）、16:00 盘后链更新 `{date}:final`（封板口径）；
        # dry-run 零写入纪律：不落库，池内股免投喂跳过同样不生效（dry-run 只看叙事）。
        rewrap_codes: set[str] = set()
        if not dry_run:
            from backend.operations.rewrap_pool import update_rewrap_pool
            pool_doc = update_rewrap_pool(db, date, slot, dataset_id)
            rewrap_codes = set(pool_doc.get("rewrapCodes") or [])
            if rewrap_codes:
                print(f"[{di + 1}/{len(dates)}] {date} [{slot}] 反包板池更新：候选"
                      f" {pool_doc.get('candidateN')} 反包 {len(rewrap_codes)}（率"
                      f" {pool_doc.get('rewrapRate')}）")
        items: dict[str, dict] = {}
        for entry in pop:
            code = _strip(entry["stock"].get("code"))
            items[code] = entry
        codes = list(items.keys())
        done = {d["code"] for d in col.find({"tradingDate": date, "status": "ok"}, {"code": 1})
                if d.get("code")}  # PHASE 日级文档无 code，跳过防 KeyError
        # 单日每股只投喂一次（2026-10-20 用户裁决）：done 不区分槽位——午盘已投喂的
        # 个股在收盘（或重跑）时自动幂等跳过，不额外维护「已投喂」状态表
        skipped_labeled = [c for c in codes if c in done and not force]
        # force=口径代际升级重放（2026-10-16 连板口径修正回填）：已 ok 也重判，
        # replace_one 幂等覆盖；不带 force 维持增量补跑语义（已 ok 跳过）
        codes = [c for c in codes if force or c not in done]
        if only_codes:
            missing = [c for c in only_codes if c not in items]
            # 已 ok 且未带 force：codes 已被上面的 done 过滤清空，若不再披露一层，
            # 用户 `--codes X` 会只看到「无需打的股票」而不知道 X 被跳过的原因
            already = [c for c in only_codes if c in items and c in done and not force]
            codes = [c for c in codes if c in only_codes]
            for c in missing:
                print(f"[{di + 1}/{len(dates)}] {date} --codes {c} 不在当日韭研池，跳过（披露）")
            for c in already:
                print(f"[{di + 1}/{len(dates)}] {date} --codes {c} 当日已 status=ok，"
                      f"跳过（披露）；口径代际回放请加 --force")
        if not codes:
            skip_txt = f"（{len(skipped_labeled)} 只当日已投喂，幂等跳过）" if skipped_labeled else ""
            print(f"[{di + 1}/{len(dates)}] {date} 无需打的股票，跳过{skip_txt}")
            continue
        if max_stocks is not None and len(codes) > max_stocks:
            print(f"[{di + 1}/{len(dates)}] {date} {len(codes)} 只超上限 {max_stocks}，"
                  f"截断到前 {max_stocks} 只（其余明日记账，fail-visible）")
            codes = codes[:max_stocks]
        if not dry_run and not confirm_budget:
            # 批次C I13：开火前预算确认（AGENTS §1.2-7）。排程链由 --confirm-budget 携带
            # 2026-10-03 挂链裁决的常态批准；手动多日回填必须显式确认。
            raise SystemExit(
                f"预算护栏：本窗口（{slot} 槽位）预计至少 {len(codes)} 次 jev 真实调用"
                f"（首日 {date}，全量口径参考 ≈21 万 tokens/交易日）。确认预算请加 --confirm-budget；"
                f"或先 --dry-run 查看叙事。")
        ranks = hotlist_ranks(db, date, list(items.keys()), dataset_id)
        # 批次C I10（顺手）：整日韭研文档只读一次，传给每只股票的叙事构造（原每股重读一次）
        jy_doc = db["jiuyan_action"].find_one(
            {"_id": f"{date}:{slot}"}, {"fields": 1, "fetchedAt": 1}) or {}

        # A+B：承接候选池（最近 MAX_GAP_TRADING_DAYS 个交易日的已判文档；force/关闭时为空）
        prev_pool: dict[str, dict] = {}
        prev_dates: list[str] = []
        if carry_on:
            prev_pool, prev_dates = _carry_prev_docs(db, col, date, dataset_id)
        full_qs_hash = _questions_hash(
            QUESTIONS_STOCK_WITH_PHASE if with_stock_phase else QUESTIONS_STOCK)

        def carry_of(code: str) -> dict | None:
            """单股承接判定（A）：不可承接返回 None（条件不满足则全量实判，不静默降级）。"""
            if not carry_on:
                return None
            prev_doc = prev_pool.get(code)
            decision = carry_decision(
                today_expound=items[code]["stock"].get("expound"),
                prev_doc=prev_doc,
                today_question_set_hash=full_qs_hash,
                today_ammo_version=AMMO_VERSION,
                gap_trading_days=_carry_gap(prev_doc, prev_dates))
            return decision if decision["eligible"] else None

        if dry_run:
            sample = items[codes[0]]
            carry_sample = carry_of(codes[0])
            narrative = build_pilot_narrative(
                db, date, codes[0], sample["stock"], sample["board"], ranks.get(codes[0]),
                dataset_id=dataset_id, jiuyan_doc=jy_doc, slot=slot,
                # 与实跑同口径：承接样本不会出「解析续期」行（否则 dry-run 字符数虚高）
                expound_trace=not carry_sample)
            if carry_sample:
                narrative, cmp_stats = compress_narrative(narrative, carry_sample["prevDate"])
                print(f"[dry] A 可承接：上标签日 {carry_sample['prevDate']}；B 压缩={cmp_stats}")
            print(f"[dry] {date} [{slot}] {sample['stock'].get('name')}\n" + narrative)
            print(f"[{di + 1}/{len(dates)}] {date} population={len(codes)} hotlistHit={len(ranks)}"
                  f" carryEligible={sum(1 for c in codes if carry_of(c))}")
            continue

        rewrap_hit: list = []
        rewrap_miss: list = []

        def work(code):
            entry = items[code]
            # 反包板池免投喂承接（2026-10-21 用户裁决）：池内股零 jev 调用复制前日标签；
            # 守卫不满足（窗内无前标/答案缺失/前标 freshness∈{unclear, fresh_catalyst}/题集换代/相位答案缺失）
            # → 回落全量实判（不静默降级）。
            # 计数用 list.append（append 原子；审查 nit12：`list[0] += 1` 非原子）。
            if code in rewrap_codes:
                if _rewrap_carry_one(db, col, date, code, entry, slot, dataset_id,
                                     full_qs_hash, with_stock_phase, jy_doc,
                                     ranks.get(code)):
                    run_tokens.append(0)
                    rewrap_hit.append(1)
                    return True
                rewrap_miss.append(1)
            carry = carry_of(code)
            last_err: str | None = None
            for attempt in range(2):
                try:
                    ok, used = _label_one(db, col, acc, token, date, code, entry["stock"],
                                          entry["board"], ranks.get(code),
                                          include_stock_phase=with_stock_phase,
                                          dataset_id=dataset_id, jiuyan_doc=jy_doc, slot=slot,
                                          carry=carry)
                    run_tokens.append(used)
                    if ok:
                        return True
                except Exception as exc:  # noqa: BLE001 — 批次C I3：单股隔离，异常不炸整日/后续日期
                    last_err = f"{type(exc).__name__}: {exc}"
                time.sleep(1.0)
            print(f"[label] {date} {code} degraded（last_error={last_err or 'jev returned not-ok'}）")
            return False

        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(work, codes))
        n_ok += sum(results)
        n_deg += len(results) - sum(results)
        n_rewrap_carried += len(rewrap_hit)
        n_rewrap_miss += len(rewrap_miss)
        carried_today = sum(1 for c in codes if carry_of(c))
        n_carried += carried_today
        n_rejudged += len(codes) - carried_today
        skip_txt = f" skippedLabeled={len(skipped_labeled)}" if skipped_labeled else ""
        carry_txt = f" carried={carried_today}" if carry_on else ""
        print(f"[{di + 1}/{len(dates)}] {date} [{slot}] done n={len(codes)}{skip_txt}{carry_txt}"
              f" (cum ok={n_ok} deg={n_deg})")
    if not dry_run:
        # 批次C I12：FINAL 口径=本次运行实付（不再全集合扫历史 usage，不再 total_tokens/input+output 键名漂移）
        # v3.2 D1：补 tailMiss/补尾溯源——线上补尾失败时不再静默（2026-10-20 教训：
        # 「机制修好了但没人知道它在哪些股上失败」导致三轴全灭被当成数据缺口锁存三个月）
        prov = bars_source_provenance()
        print("FINAL:", {"slot": slot, "ok": n_ok, "degraded": n_deg,
                         "carried": n_carried, "rejudged": n_rejudged,
                         "rewrapCarried": n_rewrap_carried, "rewrapMiss": n_rewrap_miss,
                         "totalTokens": sum(run_tokens), "calls": len(run_tokens),
                         "barsSource": {k: prov.get(k) for k in
                                        ("counts", "tailMergedCodes", "tailMissCodes")}})




def trajectory_line(db, date: str, n: int = 10,
                    dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """近 n 个交易日（含当日）逐日序列：日期|涨停(较昨日Δ)|跌停|炸板率%|大幅回撤|最高板。

    轴 = `trading_dates_before(date, n-1) + [date]`（与同族 `high_position_trajectory_lines`
    `jev_relay_index.py:611` 同式）——**必须含当日**。
    2026-10-18 review P1-2：旧式 `trading_dates_before(date, n+1)` 查 `tradingDate < date`
    （严格早于），当日永不入列 → 序列实际截止昨日，head 却写「近 N 个交易日」且无语境提示；
    批次2 的当日口径标注（`d == date` / `day_is_pool` / 行尾「当日格」）在真库**不可达**。
    """
    hist = trading_dates_before(db, date, max(n - 1, 1), dataset_id=dataset_id)
    if hist and hist[-1] == date:      # 防御：调用方传入未来日/异常时不让日重复
        hist = hist[:-1]
    axis = hist + ([date] if date not in hist else [])
    window = axis
    # 跌停=全市场口径（2026-10-16 口径修正；2026-10-17 F7 补本地日线重算源）：历史窗口一次
    # find 批量读参考集合（禁逐日连发），当日允许懒加载。**同一列内不得混口径**——
    # pool_rows（250 只采集池）与全市场差 4 倍量级，混采会让「跌停翻六倍」这种观感其实
    # 只是换了个源（10-15=26 全市场 vs 09-10=6 采集池并排，模型无从分辨）。
    # 全市场家族内部（东财池/快照/本地日线重算）逐日回退，并在行尾列明本列实际用到的源
    # （跨 09-15/09-16 切换的窗口会同时用到「本地日线重算＋东财池」，不许默默并排）。
    # 参考集合 miss 且无全市场源的历史日才回落采集池口径，逐格打 * 并在行尾注明。
    # 当日同理：`limit_down_count` 可能在 EM/快照都不可用时回落采集池（src=pool_rows），
    # 此时当日格也是采集池口径，必须和历史降级格一样打 * 并在行尾列明——
    # 旧版 `degraded = d != date and ...` 让当日恒 False，行尾写「跌停列=全市场·…」，
    # 而当日数字其实是 250 只采集池（差 4 倍量级），模型会把口径切换读成情绪暴跌。
    die, src = limit_down_count(db, date, dataset_id)
    day_is_pool = src not in FULL_MARKET_SOURCES
    by_src = {s: reference_counts(db, window, s) for s in FULL_MARKET_SOURCES}
    used_srcs = [s for s in FULL_MARKET_SOURCES
                 if s == src or any(d in by_src[s] for d in window)]
    die_ref: dict[str, int] = {}
    die_ref_src: dict[str, str] = {}        # 逐格归属（P2-2）：本格数字实际来自哪个源
    for s in FULL_MARKET_SOURCES:            # 源内优先级 = FULL_MARKET_SOURCES 顺序（EM 最权威）
        for d, v in by_src[s].items():
            if d not in die_ref:
                die_ref[d] = v
                die_ref_src[d] = s
    die_scope = "＋".join(source_label(s) for s in used_srcs) if used_srcs else source_label(SOURCE_POOL)
    pool_fallback = {d: dieban_count(db, d, dataset_id) for d in window
                     if d not in die_ref and d != date}
    degraded = False
    series = []
    for d in window:
        m = market_metrics(db, d, dataset_id) or {}
        if d == date:
            cur_die = die
            row_degraded = day_is_pool
            cell_src = src
        elif d in die_ref:
            cur_die = die_ref[d]
            row_degraded = False
            cell_src = die_ref_src.get(d)
        else:
            cur_die = pool_fallback.get(d)
            row_degraded = cur_die is not None
            cell_src = SOURCE_POOL if row_degraded else None
        degraded = degraded or row_degraded
        rate = m.get("zhabanRate")
        rate_txt = f'{round(rate, 1)}%' if isinstance(rate, (int, float)) else "?"
        zt = m.get("ztCount") if isinstance(m.get("ztCount"), (int, float)) else None
        dd = m.get("drawdownCount")
        mb = m.get("maxBoard")
        series.append({"d": d, "zt": zt, "die": cur_die, "rate": rate_txt,
                       "dd": dd if isinstance(dd, (int, float)) else None,
                       "mb": mb if isinstance(mb, (int, float)) else None,
                       "src": cell_src,
                       "degraded": row_degraded})
    # 列内通常源 = 出现最多的全市场源（平票按 FULL_MARKET_SOURCES 序）；非通常源的格打 ^。
    # P2-2：跨源并排靠整列头注区分不够——TDX−EM 实测均值 +1.65（+0..+4），读者需知道
    # **哪些天**换了源才不会被源差读成情绪摆动。
    full_cells = [r["src"] for r in series
                  if r["die"] is not None and r["src"] in FULL_MARKET_SOURCES]
    col_src = None
    if full_cells:
        col_src = max(FULL_MARKET_SOURCES,
                      key=lambda s: (full_cells.count(s), -FULL_MARKET_SOURCES.index(s)))
    rows = []
    for i, r in enumerate(series):
        prev = series[i - 1] if i > 0 else None      # 首格无昨日基线 → Δ 记 ?
        if prev is not None and r["zt"] is not None and prev["zt"] is not None:
            delta = f'{r["zt"] - prev["zt"]:+d}'
        else:
            delta = "?"
        die_txt = f'{r["die"]}*' if r["degraded"] and r["die"] is not None else (
            r["die"] if r["die"] is not None else "?")
        # 跨源格标记 ^（P2-2）：与列内通常源不同（且不是采集池降级格）——降级格已打 *
        if (not r["degraded"] and r["die"] is not None and col_src
                and r["src"] in FULL_MARKET_SOURCES and r["src"] != col_src):
            die_txt = f'{die_txt}^'
        dd_txt = r["dd"] if r["dd"] is not None else "?"
        mb_txt = r["mb"] if r["mb"] is not None else "?"
        zt_txt = r["zt"] if r["zt"] is not None else "?"
        ad = advdec_ratio(db, r["d"], dataset_id)
        ad_txt = f'{ad[3]}' if ad else "?"
        rows.append(f'{r["d"][5:]}|涨停{zt_txt}({delta})|跌停{die_txt}|炸板{r["rate"]}|回撤{dd_txt}|板{mb_txt}|涨跌比{ad_txt}')
    head = f'近{len(rows)}个交易日序列（含当日；日期|涨停(较昨日Δ)|跌停|炸板率|大幅回撤|最高板|池内涨跌比）：'
    # 口径头注（2026-10-16 review 补）：跌停列的源 + 降级格标记。没有这行，跨源混采的
    # 序列会被读成真实情绪摆动。当日回落采集池时必须单独点名：否则头注的 die_scope
    # （由历史窗推导）会让读者以为当日也是全市场口径（2026-10-18 review B4）。
    parts = [f"跌停列={die_scope}"]
    if day_is_pool:
        parts.append(f"当日格={source_label(SOURCE_POOL)}（全市场源不可用，已打 *）")
    if degraded:
        parts.append("* 为采集池降级格，全市场源缺失")
    # 跨源并排的区间式说明（P2-2）：列内出现与通常源不同的全市场源时列出该源所占日期段
    if col_src:
        others = {}
        for r in series:
            if (r["die"] is not None and r["src"] in FULL_MARKET_SOURCES
                    and r["src"] != col_src):
                others.setdefault(r["src"], []).append(r["d"][5:])
        for s, ds in others.items():
            which = ds[0] if len(ds) == 1 else f"{ds[0]}~{ds[-1]}（{len(ds)} 日）"
            parts.append(f"^ {which}={source_label(s)}（非列内主要源 {source_label(col_src)}，"
                         "源间存在系统性差，勿读作情绪摆动）")
    note = "（" + "；".join(parts) + "）"
    return head + " ； ".join(rows) + note




def swing_summary_line(db, date: str, n: int = 10,
                       dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """摆动锚：窗口峰值/谷值（家数、日期、距今交易日数）+ 今日较昨日 Δ 与距峰值幅度。"""
    prev = trading_dates_before(db, date, n, dataset_id)
    vals = []
    for d in prev:
        m = market_metrics(db, d, dataset_id) or {}
        if isinstance(m.get("ztCount"), (int, float)):
            vals.append((d, int(m["ztCount"])))
    m_cur = market_metrics(db, date, dataset_id) or {}
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


def _cycle_energy_line(db, date: str) -> str:
    """cycle v5 行①：量能方向（market_daily_amount 存量，今日 vs 上一交易日 + 近 20 日分位）。

    fail-visible：当日/前日缺失 → 数据缺口（预登记 jev-cycle-v5 §二）。"""
    series = sorted((d["_id"], d.get("totalAmount")) for d in db["market_daily_amount"].find({}, {"totalAmount": 1})
                    if isinstance(d.get("_id"), str) and len(d["_id"]) == 10)
    by_date = dict(series)
    cur = by_date.get(date)
    prior = [(i, v) for i, v in series if i < date and isinstance(v, (int, float))
             and not isinstance(v, bool) and v > 0]
    if not (isinstance(cur, (int, float)) and not isinstance(cur, bool) and cur > 0) or not prior:
        return "量能方向：数据缺口（fail-visible）"
    prev_date, prev = prior[-1]
    pct = (cur - prev) / prev * 100
    pctl = ammo.percentile_rank([v for _, v in prior[-20:]], cur)
    direction = "放量" if pct > 0 else ("缩量" if pct < 0 else "持平")
    return (f"量能方向：两市成交额 {cur / 1e8:.0f} 亿，较上一交易日（{prev_date}）{pct:+.1f}%"
            f"（{direction}），近 20 日量能分位 {pctl}")


def _cycle_breadth_line(db, date: str, dataset_id: str) -> str:
    """cycle v5 行②：全市场涨跌（帧 marketStats；7-9 月历史碎裂如实 fail-visible）。"""
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"marketStats": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    ms = (f or {}).get("marketStats") or {}
    up, dn, dt = ms.get("upCount"), ms.get("downCount"), ms.get("dtCount")
    if not (isinstance(up, (int, float)) and not isinstance(up, bool)
            and isinstance(dn, (int, float)) and not isinstance(dn, bool)):
        return "全市场涨跌：marketStats 缺口（fail-visible）"
    if up <= 0 or dn <= 0:
        # 7-9 月历史碎裂帧存的是 0 而非缺字段（review A-P3）：0 不可信读数如实区分注记
        return "全市场涨跌：读数为 0（历史碎裂，fail-visible）"
    dt_txt = f"，跌停 {dt:.0f} 家" if isinstance(dt, (int, float)) and not isinstance(dt, bool) else ""
    return f"全市场涨跌：上涨 {up:.0f} 家／下跌 {dn:.0f} 家{dt_txt}"


def _cycle_drawdown_line(db, date: str, dataset_id: str) -> str:
    """cycle v5 行③：大面规模（limitSummary.drawdown，111/112 覆盖）。"""
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"limitSummary.drawdown": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    dd = ((f or {}).get("limitSummary") or {}).get("drawdown") or {}
    n, avg, deep = dd.get("count"), dd.get("avgDrawdownPct"), dd.get("deepestDrawdownPct")
    if not (isinstance(n, (int, float)) and not isinstance(n, bool)):
        return "大面规模：drawdown 缺口（fail-visible）"
    avg_txt = f"，平均回撤 {avg:.1f}%" if isinstance(avg, (int, float)) and not isinstance(avg, bool) else ""
    deep_txt = f"，最深 {deep:.1f}%" if isinstance(deep, (int, float)) and not isinstance(deep, bool) else ""
    return f"大面规模：回撤池 {n:.0f} 家{avg_txt}{deep_txt}"


def build_cycle_narrative(db, date: str,
                          dataset_id: str = DEFAULT_DATASET_ID) -> str:
    lines = [
        f"{date} 交易日",
        market_facts_line(db, date, dataset_id),
        # cycle v5 三件套接线（预登记 jev-cycle-v5 §二）：判据引用的证据必须在叙事里（铁律 3/4）
        _cycle_energy_line(db, date),
        _cycle_breadth_line(db, date, dataset_id),
        _cycle_drawdown_line(db, date, dataset_id),
        swing_summary_line(db, date, dataset_id=dataset_id),
        trajectory_line(db, date, dataset_id=dataset_id),
    ]
    return chr(10).join(lines)


def run_cycle_stage_day(db, dates: list[str], token: str, acc: str,
                        dataset_id: str = DEFAULT_DATASET_ID) -> None:
    """情绪周期段位试点：日级独立调用，落 hotlist_jev_cycle_stage_pilot（_id={date}:CYCLE）。"""
    col = db["hotlist_jev_cycle_stage_pilot"]
    for date in dates:
        done = col.find_one({"_id": f"{date}:CYCLE", "status": "ok"})
        if done:
            print(f"[cycle] {date} 已判（{done.get('cycleStage')}），跳过")
            continue
        narrative = build_cycle_narrative(db, date, dataset_id)
        env, ms = _dispatch_jev(narrative, QUESTIONS_CYCLE)
        parsed = parse_jev_response(env, ms, expected_keys=set(QUESTIONS_CYCLE))
        answers = parsed.get("answers") or {}
        doc = {"_id": f"{date}:CYCLE", "origin": "cycle_stage_daily", "tradingDate": date,
               "ammoVersion": AMMO_VERSION,
               # cycle v5 独立版本戳（预登记 §四修旧债：v1-v4 共用 driver 戳，换代不动戳违规）
               "questionSetVersion": QUESTION_SET_VERSION_CYCLE,
               "questionSetHash": _questions_hash(QUESTIONS_CYCLE),
               "status": "ok" if parsed["ok"] else "degraded",
               "narrative": narrative, "questionsRaw": QUESTIONS_CYCLE,
               "answers": parsed.get("answers"),
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


def _board_effect_stats(jiuyan_doc) -> dict | None:
    """韭研板块结构统计（**按 code 去重**，防同一只股在两个板块里被合计两次）。

    2026-10-20 审查 Nit-4：旧版分母用「各 field 成员数之和」，一只股出现在两个板块时
    「占 X%」会超过真实占比。去重后 total=当日涨停只数，占比=占当日涨停只数的份额。
    """
    seen: set[str] = set()
    per_board: dict[str, int] = {}
    for fl in jiuyan_doc.get("fields") or []:
        board = str(fl.get("name") or "")
        for s_ in fl.get("stocks") or []:
            code = _strip(s_.get("code"))
            if not code or code in seen:
                continue
            seen.add(code)
            if board:
                per_board[board] = per_board.get(board, 0) + 1
    if not seen or not per_board:
        return None
    total = len(seen)
    ordered = sorted(per_board.values(), reverse=True)
    top_board = max(per_board.items(), key=lambda kv: kv[1])[0]
    return {"boards": len(per_board), "total": total, "top_board": top_board,
            "top_n": ordered[0], "top_share": ordered[0] / total * 100,
            "top3_share": sum(ordered[:3]) / total * 100}


def phase_band_extra_lines(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> list[str]:
    """日级哨兵补料（v3.2 D9）：判据引用「板块效应」与「梯队总量近 20 日分位」而旧语料没有。

    `QUESTIONS_PHASE` 的判断段写「涨停家数、炸板率、连板梯队、**板块效应**及各自**近 20 日
    分位**」，`cold_lt40`/`strong_ge60` 更是直接引用「板块效应处于近 20 日低位区/高位区」——
    而 `market_facts_line` 里既没有板块效应、也没有梯队总量分位（只有逐桶家数与最高板分位）。
    本函数补三行客观事实（1 次/日）：板块效应绝对值 + **板块集中度近 20 日分位** + 梯队总量分位。
    2026-10-20 审查 P2-1：首版只给了板块效应绝对值，判据里的「低位区/高位区」仍半空洞，
    故补分位（历史 20 日韭研板块结构，零额外外呼）。
    **不改 `market_facts_line`**（relay v7 段 1 / cycle / theme_leader 共用，改了会连带漂移）。
    """
    lines: list[str] = []
    jy = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
    cur_stats = _board_effect_stats(jy)
    if cur_stats is None:
        lines.append("板块效应：韭研板块结构缺失（fail-visible）")
    else:
        lines.append(f"板块效应：今日涨停 {cur_stats['total']} 只分布于 {cur_stats['boards']} 个"
                     f"韭研板块，最大「{cur_stats['top_board']}」{cur_stats['top_n']} 家"
                     f"（占 {cur_stats['top_share']:.0f}%），前三合计 {cur_stats['top3_share']:.0f}%")
        shares: list[float] = []
        for d in trading_dates_before(db, date, dataset_id=dataset_id):
            prev_jy = db["jiuyan_action"].find_one({"_id": f"{d}:final"}, {"fields": 1}) or {}
            prev_stats = _board_effect_stats(prev_jy)
            if prev_stats:
                shares.append(prev_stats["top_share"])
        rank = percentile_rank(shares, cur_stats["top_share"])
        lines.append(f"板块集中度：最大板块占 {cur_stats['top_share']:.0f}%"
                     f"（{rank if rank == '分位不可算' else rank + ' 分位'}，近 {len(shares)} 日样本）")
    cur = market_metrics(db, date, dataset_id)
    pool_total = (cur or {}).get("ladderPoolTotal")
    if isinstance(pool_total, int) and not isinstance(pool_total, bool):
        hist = [m["ladderPoolTotal"]
                for m in (market_metrics(db, d, dataset_id)
                          for d in trading_dates_before(db, date, dataset_id=dataset_id))
                if m and isinstance(m.get("ladderPoolTotal"), int)
                and not isinstance(m.get("ladderPoolTotal"), bool)]
        rank = percentile_rank(hist, pool_total)
        lines.append(f"梯队总量：{pool_total} 只（{rank if rank == '分位不可算' else rank + ' 分位'}）")
    else:
        lines.append("梯队总量：不可算（梯队池缺失，fail-visible）")
    return lines


def run_phase_band_day(db, dates: list[str], token: str, acc: str,
                       dataset_id: str = DEFAULT_DATASET_ID) -> None:
    """方案 A：Q5 拆日级独立调用——每交易日一次、只喂盘面事实行不喂个股解析（去语境污染）。
    判定落同一 pilot 集合，_id={date}:PHASE、origin=phase_band_daily，与个股文档显式区隔。"""
    col = db["hotlist_jev_driver_labels"]
    for date in dates:
        done = col.find_one({"_id": f"{date}:PHASE", "status": "ok"})
        if done:
            print(f"[phase] {date} 已判（{done.get('phaseBand')}），跳过")
            continue
        narrative = "\n".join([f"{date} 交易日 · {market_facts_line(db, date, dataset_id)}",
                              *phase_band_extra_lines(db, date, dataset_id)])
        env, ms = _dispatch_jev(narrative, QUESTIONS_PHASE)
        parsed = parse_jev_response(env, ms, expected_keys=set(QUESTIONS_PHASE))
        answers = parsed.get("answers") or {}
        doc = {"_id": f"{date}:PHASE", "origin": "phase_band_daily", "tradingDate": date,
               "ammoVersion": AMMO_VERSION,
               "questionSetVersion": QUESTION_SET_VERSION_PHASE_BAND,
               "questionSetHash": _questions_hash(QUESTIONS_PHASE),
               "status": "ok" if parsed["ok"] else "degraded",
               "narrative": narrative, "questionsRaw": QUESTIONS_PHASE,
               "answers": parsed.get("answers"),
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
                          dry_run: bool = False, workers: int = 2,
                          dataset_id: str = DEFAULT_DATASET_ID) -> None:
    """个股相位分线试点（2026-10-04 用户裁决「先跑 9/30 看效果」）：单题补跑路径。

    与 run() 的 replace_one 整文档替换不同：对已有个股文档只 $set stockPhase* 字段
    （upsert=False），已定版四题标签与文档其余部分不动（全月代际一致不破）；
    缺个股文档的股票跳过并披露（不建平行集合）。判据冻结稿=QUESTIONS_STOCK_PHASE，
    同判据已判个股幂等跳过（防重复烧 token），判据变更（改门须点头）后自然重跑。
    """
    col = db["hotlist_jev_driver_labels"]
    n_ok = n_deg = n_skip = n_nodoc = n_err = 0
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
        ranks = hotlist_ranks(db, date, codes, dataset_id)
        jy_doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
        if dry_run:
            sample = items[codes[0]]
            narrative = build_pilot_narrative(db, date, codes[0], sample["stock"],
                                              sample["board"], ranks.get(codes[0]),
                                              dataset_id=dataset_id, jiuyan_doc=jy_doc)
            print(f"[dry][stock-phase] {date} population={len(codes)} hotlistHit={len(ranks)} "
                  f"narrativeChars={len(narrative)}")
            print(narrative)
            continue

        def work(code):
            entry = items[code]
            try:
                done = col.find_one({"_id": f"{date}:{code}"},
                                    {"stockPhasePosition": 1, "stockPhaseQuestionsRaw": 1,
                                     "stockPhaseQuestionSetHash": 1})
                phase_hash = _questions_hash(QUESTIONS_STOCK_PHASE)
                same_generation = (
                    (done or {}).get("stockPhaseQuestionSetHash") == phase_hash
                    # 批次C I15 兼容：旧代文档无哈希，退回整 dict 比对
                    or (done or {}).get("stockPhaseQuestionsRaw") == QUESTIONS_STOCK_PHASE)
                if done and done.get("stockPhasePosition") and same_generation:
                    return ("skip", 0)
                narrative = build_pilot_narrative(db, date, code, entry["stock"],
                                                  entry["board"], ranks.get(code),
                                                  dataset_id=dataset_id, jiuyan_doc=jy_doc)
                env, ms = _dispatch_jev(narrative, QUESTIONS_STOCK_PHASE)
                parsed = parse_jev_response(env, ms, expected_keys=set(QUESTIONS_STOCK_PHASE))
            except Exception as exc:  # noqa: BLE001 — 批次C I3：单股隔离
                print(f"[stock-phase] {date} {code} error（{type(exc).__name__}: {exc}）")
                return ("error", 0)
            answers = parsed.get("answers") or {}
            ans = answers.get("stock_phase_position") or {}
            used = _usage_tokens(parsed.get("usage"))
            payload = {
                "stockPhasePosition": ans.get("choice"),
                "stockPhaseProbabilities": ans.get("probabilities"),
                # 单题 $set 路径不写 answers 整包（防覆盖主 call 的五题 answers），只补置信字段
                "stockPhaseConfidence": ans.get("confidence"),
                "stockPhaseQuestionsRaw": QUESTIONS_STOCK_PHASE,
                "stockPhaseQuestionSetHash": _questions_hash(QUESTIONS_STOCK_PHASE),
                "stockPhaseAmmoVersion": AMMO_VERSION,
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
        n_err += sum(1 for s, _ in results if s == "error")
        tokens_used += sum(t for _, t in results)
        print(f"[stock-phase] {date} n={len(codes)} (cum ok={n_ok} degraded={n_deg} "
              f"skip={n_skip} noDoc={n_nodoc} error={n_err})")
    print("FINAL:", {"ok": n_ok, "degraded": n_deg, "skipped": n_skip,
                     "noDoc": n_nodoc, "error": n_err, "tokens": tokens_used})


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
    ap.add_argument("--dataset-id", dest="dataset_id", default=DEFAULT_DATASET_ID,
                    help=f"快照数据集隔离（批次B I8，默认 {DEFAULT_DATASET_ID}）")
    ap.add_argument("--confirm-budget", dest="confirm_budget", action="store_true",
                    help="批次C I13：确认本次真实调用的 token 预算（排程链常态携带=挂链裁决；"
                         "手动多日回填必须显式确认，否则拒绝开火）")
    ap.add_argument("--force", action="store_true",
                    help="口径代际升级重放：已 status=ok 的个股也重新判定（replace_one 幂等覆盖）")
    ap.add_argument("--max-stocks", dest="max_stocks", type=int, default=None,
                    help="批次C I13：单日打标上限（超出部分截断并披露），不给=不限")
    ap.add_argument("--no-carry-forward", dest="no_carry_forward", action="store_true",
                    help="关闭 A+B（承接 + 解析去重压缩）：强制全量实判。默认读环境开关"
                         "JEV_CARRY_FORWARD_ENABLED（默认为开）；需重测或对比基线时用。"
                         "口径代际回放（--force）本就全量实判，不需本开关")
    ap.add_argument("--codes", dest="codes", default=None,
                    help="只打指定股票（逗号分隔，如 600825,002343）。口径修正只影响个别股时"
                         "用——避免为改一行共享语料把整日 100+ 只全部重烧一遍")
    ap.add_argument("--slot", dest="slot", choices=list(_SLOTS), default=SLOT_FINAL,
                    help="投喂槽位（2026-10-20 用户裁决）：final=收盘链（默认，名单取 "
                         "{date}:final）；midday=12:30 午盘投喂（名单取 {date}:midday，叙事午盘口径）。"
                         "两槽位共享 _id={date}:{code} + status=ok 幂等判据：午盘已投喂的个股在"
                         "收盘运行自动跳过，单日每股只投喂一次")
    args = ap.parse_args()
    tok = os.environ.get("JEV_CF_TOKEN") or ""
    # 2026-10-10：官方直连（JEV_TYPESAFE_KEY）为合法替代通道，护栏二选一即可
    if not tok and not (os.environ.get("JEV_TYPESAFE_KEY") or "").strip():
        raise SystemExit("需要 JEV_CF_TOKEN 或 JEV_TYPESAFE_KEY 环境变量")
    acc = os.environ.get("JEV_CF_ACCOUNT", DEFAULT_ACCOUNT_ID)
    if args.stock_phase_date:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        run_stock_phase_pilot(get_runtime_mongodb_database(), [args.stock_phase_date], tok, acc,
                              dry_run=args.dry_run, workers=args.workers,
                              dataset_id=args.dataset_id)
    elif args.stock_phase_month:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        db = get_runtime_mongodb_database()
        # 日期轴=已有个股四题文档（与回填对象同源，review P2：此前用 sentiment EOD 轴会静默漏
        # 「final 有而 EOD 缺」的打标日）
        dates = sorted({str(d.get("tradingDate")) for d in db["hotlist_jev_driver_labels"].find(
            {"origin": {"$ne": "phase_band_daily"}, "status": "ok",
             "tradingDate": {"$regex": f"^{args.stock_phase_month}"}}, {"tradingDate": 1})})
        print(f"[stock-phase-month] {args.stock_phase_month} 共 {len(dates)} 个已打标交易日待补跑")
        run_stock_phase_pilot(db, dates, tok, acc, dry_run=args.dry_run, workers=args.workers,
                              dataset_id=args.dataset_id)
    elif args.cycle_stage_day:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        run_cycle_stage_day(get_runtime_mongodb_database(), args.cycle_stage_day, tok, acc,
                            dataset_id=args.dataset_id)
    elif args.phase_band_day:
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        run_phase_band_day(get_runtime_mongodb_database(), [args.phase_band_day], tok, acc,
                           dataset_id=args.dataset_id)
    else:
        if not (args.start and args.end):
            raise SystemExit("个股模式需要 --start/--end")
        # --with-stock-phase=真合并同 call（2026-10-04 用户裁决）：相位题并入主 call 题目集，
        # 同一 narrative 五题一次调用（边际成本≈题干+答案）；排程经 JIUYAN_STOCK_PHASE_ENABLED=1 门控
        run(args.start, args.end, args.dry_run, tok, acc, args.workers,
            with_stock_phase=args.with_stock_phase, dataset_id=args.dataset_id,
            confirm_budget=args.confirm_budget, max_stocks=args.max_stocks,
            force=args.force,
            only_codes={c.strip()[-6:] for c in args.codes.split(",") if c.strip()}
            if args.codes else None,
            slot=args.slot,
            carry_forward=False if args.no_carry_forward else None)
