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

from backend.analysis.hotlist.jev_driver_ammo import (
    AMMO_VERSION,
    DEFAULT_DATASET_ID,
    QUESTION_SET_VERSION_DRIVER,
    QUESTIONS_CYCLE,
    QUESTIONS_PHASE,
    QUESTIONS_STOCK,
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
from backend.core.limit_rules import is_limit_down_pct
from backend.services.jev.jev_client import DEFAULT_ACCOUNT_ID, call_jev, parse_jev_response
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


def _jiuyan_board_count(stock: dict) -> int | None:
    """韭研 num 字段「N天M板」解析出真实板数 M（2026-10-10 口径修正）。

    实测：day 字段存的是 N（跨度天数）而非板数——「9天9板」两者巧合相等，
    「16天8板」day=16 但真实 8 板；与 THS maxBoard 对齐验证。num 无法解析
    返回 None（宁缺毋猜）。"""
    num = str(stock.get("num") or "").strip()
    if not num:
        return None
    import re
    m = re.match(r"^(\d+)天(\d+)板", num)
    if not m:
        return None
    boards = int(m.group(2))
    return boards if boards > 0 else None


def _jiuyan_ladder(db, date: str) -> dict | None:
    """韭研主源连板梯队（2026-10-10 双源改造）：final 的 fields[].stocks num 板数分布聚合。

    口径（2026-10-10 实测验证）：
    - 板数 = num「N天M板」的 M（day 字段是跨度天数，不可用作板数）；
    - num=null 且不在昨日涨停池 → 韭研首板口径（首板不标），入 one 桶；
    - num=null 且在昨日池 → 真连板被漏标，计入 _dayUnmarkedPrev，不猜高度（fail-visible）；
    - final 缺失/无个股 → None（回退 THS，不伪造零梯队）；
    - 桶口径与 THS_KEYS 对齐：one(≤1)/two/three/four/high(≥5)。
    """
    doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields.stocks": 1})
    fields = (doc or {}).get("fields") or []
    if not any(field.get("stocks") for field in fields):
        return None
    prev_dates = trading_dates_before(db, date, 1)
    prev_codes: set[str] = set()
    if prev_dates:
        prev_doc = db["jiuyan_action"].find_one(
            {"_id": f"{prev_dates[-1]}:final"}, {"fields.stocks.code": 1})
        for field in (prev_doc or {}).get("fields") or []:
            for stock in field.get("stocks") or []:
                code = stock.get("code")
                if code:
                    prev_codes.add(str(code)[-6:])
    buckets = {k: 0 for k in THS_KEYS}
    total = unmarked = unmarked_prev = 0
    for field in fields:
        for stock in field.get("stocks") or []:
            total += 1
            boards = _jiuyan_board_count(stock)
            if boards is not None:
                if boards <= 1:
                    buckets["one"] += 1
                elif boards == 2:
                    buckets["two"] += 1
                elif boards == 3:
                    buckets["three"] += 1
                elif boards == 4:
                    buckets["four"] += 1
                else:
                    buckets["high"] += 1
            else:
                unmarked += 1
                code = str(stock.get("code") or "")[-6:]
                if code and code in prev_codes:
                    unmarked_prev += 1  # 昨日涨停今日在池但未标 num：真连板，高度未知
                else:
                    buckets["one"] += 1  # 韭研口径：首板不标 num
    buckets["_poolTotal"] = total
    buckets["_dayUnmarked"] = unmarked
    buckets["_dayUnmarkedPrev"] = unmarked_prev
    return buckets


def _ths_failed_items(db, date: str) -> tuple[dict[str, dict], bool]:
    """THS 15:00 帧炸板池 code→item（2026-10-11 触板二分用，方案A）。

    item 含 open_num（开板次数）/change_rate 等，炸板卡「反复开板」消费；
    返回 (items, found)：found=False = 帧缺失/池降级，调用方必须 fail-visible 结构化降级，
    不得把触板名单静默当涨停名单；failed 池为空且 ok=True 是合法状态（当日无炸板）。
    """
    f = db["snapshot_frames"].find_one(
        {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": date,
         "slotTime": "15:00"},
        {"limitSummary.thsPools": 1}, sort=[("timestamp", -1), ("snapshotId", -1)])
    tp = ((f or {}).get("limitSummary") or {}).get("thsPools") or {}
    if not tp or not tp.get("ok") or tp.get("degraded"):
        return {}, False
    items = (tp.get("pools") or {}).get("failed", {}).get("items") or []
    return {str(i.get("code") or "")[-6:]: i for i in items if i.get("code")}, True


def _ths_failed_codes(db, date: str) -> tuple[set[str], bool]:
    items, found = _ths_failed_items(db, date)
    return set(items), found


_BSE_CODE_PREFIXES = ("92", "43", "83", "87")


def _official_exclude(stock_name: Any, code: str) -> str | None:
    """官方简图剔除口径（footer：不含 st 和未开板新股）：ST 或北交所 → 排除原因，否则 None。"""
    if "ST" in str(stock_name or "").upper():
        return "st"
    if code[:2] in _BSE_CODE_PREFIXES:
        return "bse"
    return None


def jiuyan_board_info(db, date: str) -> tuple[dict[str, dict], dict]:
    """韭研个股高度/封板时间/板块 join + 触板二分（2026-10-11 方案A，用户裁决）。

    韭研 final fields.stocks = 盘中曾触板名单（封板+炸板，10-09 实测 82=69涨停+13炸板），
    与官方简图「涨停家数」差炸板股；doc 内无可靠封板标记（time 空≠炸板），必须借
    THS 15:00 炸板池二分：
    - zhaban=True：在今日炸板池 → 非涨停股（断板/触板未封），不进涨停口径；
      openNum=THS 开板次数（open_num，None 不透传）随 zhaban 附带；
    - excluded：'st'|'bse'（官方简图不计入涨停家数的 5 只差额，10-09 实测 3 ST + 2 北交所）；
    - boardUnmarked=True：num 空且昨日在「昨日涨停池」（昨日触板-昨日炸板）→ 真漏标连板；
      昨日炸板股今日涨停=首板，不得误标（10-09 金健米业/东亚药业教训）；
    - 同 code 多板块取首现；boards=_jiuyan_board_count(num「N天M板」的 M)，None=宁缺毋猜。
    meta = {jiuyanFinalFound, prevPoolFound, thsPoolFound, prevThsPoolFound}：
    任一池缺失时二分不可用（boardUnmarked/zhaban 缺席），调用方必须结构化降级。
    """
    doc = db["jiuyan_action"].find_one(
        {"_id": f"{date}:final"},
        {"fields.stocks.code": 1, "fields.stocks.num": 1, "fields.stocks.time": 1,
         "fields.stocks.name": 1, "fields.name": 1})
    fields = (doc or {}).get("fields") or []
    final_found = any(field.get("stocks") for field in fields)
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
                boards = _jiuyan_board_count(stock)
                info = {"boards": boards, "limitUpTime": stock.get("time"),
                        "boardName": field.get("name")}
                if ths_found and code in failed_today:
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
            # THS 炸板池总数（含韭研未收录股）：前端炸板卡注记「榜外」差额，fail-visible
            "thsZhabanTotal": len(failed_today) if ths_found else None}
    return out, meta


def market_metrics(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> dict | None:
    """当日 15:00 盘面事实（涨停/炸板/回撤/梯队/最高板高；跌停另行自算）。批次B I8：带 datasetId/type 并取最新帧。
    2026-10-10 梯队双源：jiuyan final day 分布为主源（103 天池史稳定），THS thsPools
    交叉验证兼回退；ladderSource 标注实际来源（jiuyan/ths/missing），供叙事透明披露。"""
    f = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"limitSummary.zhaban": 1, "limitSummary.continuousBoards": 1,
         "limitSummary.thsPools.pools": 1, "limitSummary.drawdown": 1},
        sort=[("timestamp", -1), ("snapshotId", -1)])
    ls = (f or {}).get("limitSummary") or {}
    zb = ls.get("zhaban") or {}
    cb = ls.get("continuousBoards") or {}
    dd = ls.get("drawdown") or {}
    pools = (ls.get("thsPools") or {}).get("pools") or {}
    ths_ladder = {k: (pools.get(k) or {}).get("total") for k in THS_KEYS}
    jiuyan_ladder = _jiuyan_ladder(db, date)
    if jiuyan_ladder is not None:
        ladder = {k: jiuyan_ladder[k] for k in THS_KEYS}
        ladder_source = "jiuyan"
        ladder_pool_total = jiuyan_ladder["_poolTotal"]
        ladder_day_unmarked = jiuyan_ladder["_dayUnmarked"]
        ladder_day_unmarked_prev = jiuyan_ladder["_dayUnmarkedPrev"]
    elif any(isinstance(v, (int, float)) for v in ths_ladder.values()):
        ladder = ths_ladder
        ladder_source = "ths"
        ladder_pool_total = sum(v for v in ths_ladder.values() if isinstance(v, (int, float)))
        ladder_day_unmarked = None
        ladder_day_unmarked_prev = None
    else:
        ladder = ths_ladder  # 全 None（fail-visible：双源皆缺不伪造零梯队）
        ladder_source = "missing"
        ladder_pool_total = None
        ladder_day_unmarked = None
        ladder_day_unmarked_prev = None
    if not zb.get("ztCount"):
        return None
    return {"ztCount": zb.get("ztCount"), "zhabanCount": zb.get("count"), "zhabanRate": zb.get("rate"),
            "drawdownCount": dd.get("count"), "ladder": ladder, "maxBoard": cb.get("maxBoard"),
            "ladderSource": ladder_source, "ladderPoolTotal": ladder_pool_total,
            "ladderDayUnmarked": ladder_day_unmarked,
            "ladderDayUnmarkedPrev": ladder_day_unmarked_prev,
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
    if 0.8 <= ratio <= 1.25:
        tone = "均衡（没人买也没人卖）"
    elif ratio > 1.25:
        tone = "单边偏强"
    else:
        tone = "单边偏弱"
    return f' · 池内涨跌比 {ratio}（涨{up}/跌{down}，{tone}）'


def market_facts_line(db, date: str, dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """弹药 6：分位盘面事实行（不含规则情绪分——Q5 防锚定污染）。按 (dataset, 日) 缓存。"""
    cache_key = (dataset_id, date)
    if cache_key in _FACTS_CACHE:
        return _FACTS_CACHE[cache_key]
    cur = market_metrics(db, date, dataset_id)
    if not cur:
        return f"盘面事实：{date} 盘面指标缺失（fail-visible）"
    prev = trading_dates_before(db, date, dataset_id=dataset_id)
    hist = [m for m in (market_metrics(db, d, dataset_id) for d in prev) if m]
    hist_die = [v for v in (dieban_count(db, d, dataset_id) for d in prev) if isinstance(v, (int, float))]
    cur_die = dieban_count(db, date, dataset_id)

    def pct(vals, cur_v):
        return percentile_rank(vals, cur_v)

    die_txt = (f'跌停 {cur_die} 家（{pct(hist_die, cur_die)} 分位）'
               if isinstance(cur_die, (int, float)) else "跌停 不可算")
    rate = f'{cur["zhabanRate"]:.1f}%' if isinstance(cur["zhabanRate"], (int, float)) else "缺"
    three_plus = (cur["ladder"].get("three") or 0) + (cur["ladder"].get("four") or 0) + (cur["ladder"].get("high") or 0)
    ladder_txt = (f'一板{cur["ladder"].get("one") or 0}/二板{cur["ladder"].get("two") or 0}/三板+{three_plus}')
    src = cur.get("ladderSource")
    if src == "jiuyan":
        un_prev = cur.get("ladderDayUnmarkedPrev") or 0
        un_note = f'，{un_prev}只连板未标高度未计入' if un_prev else ''
        ladder_seg = f'连板梯队（韭研{cur.get("ladderPoolTotal")}只，首板不标板数按首板计{un_note}）{ladder_txt}'
        ths = cur.get("thsLadder")
        if ths:
            ladder_seg += (f'（THS交叉 {ths.get("one")}/{ths.get("two")}/{ths.get("three")}'
                           f'/{ths.get("four")}/{ths.get("high")}）')
    elif src == "ths":
        ladder_seg = f'连板梯队（THS回退）{ladder_txt}'
    else:
        ladder_seg = '连板梯队 不可算（韭研 final 与 THS 双源皆缺）'
    line = (f'盘面事实：涨停 {cur["ztCount"]} 家（{pct([h["ztCount"] for h in hist], cur["ztCount"])} 分位）'
            f' · {die_txt}'
            f' · 炸板率 {rate}（{pct([h["zhabanRate"] for h in hist], cur["zhabanRate"])} 分位，炸板 {cur["zhabanCount"] or 0} 家）'
            f' · 大幅回撤 {cur["drawdownCount"] if cur["drawdownCount"] is not None else "?"} 家'
            f'（{pct([h["drawdownCount"] for h in hist], cur["drawdownCount"])} 分位）'
            f' · {ladder_seg}'
            f' · 最高 {cur["maxBoard"]} 板（{pct([h["maxBoard"] for h in hist], cur["maxBoard"])} 分位）'
            + _advdec_segment(db, date, dataset_id))
    _FACTS_CACHE[cache_key] = line
    return line


# ---- 弹药 6：个股价格位置轴（2026-10-04 用户令接入：距 20 日最高/窗口涨幅/量能缩放——
#      首板单锚判不出高位，龙版传媒 605577 首板但距 20 日高点仅 7.8%/窗口涨幅 62.5% 实锤） ----
_POSITION_LOCK = threading.Lock()

_DIV_LOCK = threading.Lock()
_DIV_LIST_CACHE: dict[str, dict[str, tuple[float, float]]] = {}
_DAILY_CLIENT: Any = None
_DAILY_BARS_CACHE: dict[str, list[dict]] = {}
_TDX_DOWN_UNTIL = 0.0
_TDX_RETRY_SECONDS = 300


def _tdx_hosts_path() -> Path:
    """节点池配置路径：环境变量优先，否则仓库同级 python-bridge/tdx_hosts.json
    （批次B M4：不再写死 D:\ 绝对路径，换 worktree/机器不失效）。"""
    env = os.environ.get("TDX_HOSTS_PATH")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "python-bridge" / "tdx_hosts.json"


def _tdx_daily_client():
    """TDX 日线客户端单例（节点池探测同 backfill_slot_pctchange 模式）；全节点不可用返回 None。

    批次C I4：全节点探测失败进入 5 分钟负缓存——旧实现每股每次重探（8 节点 ×6s），
    100 只股票最坏小时级，会撞 schedule 2700s 整步超时；现在最坏每 5 分钟一次。
    """
    global _DAILY_CLIENT, _TDX_DOWN_UNTIL
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
    out: dict[str, tuple[float, float]] = {}
    try:
        import akshare as ak

        df = ak.news_trade_notify_dividend_baidu(date=date.replace("-", ""))
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
        print(f"[div-events] {date} 除权日程拉取失败（不缓存，将重试）：{type(exc).__name__}: {str(exc)[:150]}")
        return {}
    with _DIV_LOCK:
        _DIV_LIST_CACHE[date] = out
    return out


def _adj_prev_series(date: str, code: str, bars: list[dict]) -> dict[str, float]:
    """窗口内逐链接的除权参考价 {链接日 t: 交易所参考价}——仅 t 为该股除权日才有键（P1-1）。

    参考价 = round((原始前收 − 每股分红) / (1 + 每股送转), 2)（交易所除权除息公式）。
    """
    window = [b for b in bars if b["date"] <= date]
    out: dict[str, float] = {}
    for i in range(1, len(window)):
        ev = _div_event_list(window[i]["date"]).get(code)
        prev_close = window[i - 1]["close"]
        if (ev and isinstance(prev_close, (int, float)) and not isinstance(prev_close, bool)
                and prev_close > 0):
            div, bonus = ev
            out[window[i]["date"]] = round((prev_close - div) / (1 + bonus), 2)
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


def build_pilot_narrative(db, date: str, code: str, stock: dict, board: str, rank,
                          dataset_id: str = DEFAULT_DATASET_ID,
                          jiuyan_doc: dict | None = None) -> str:
    """v3 弹药叙事：盘面事实行（无情绪分）+ 个股解析 + THS 身位块 + 个股位置行（价格轴）+ 板序行（几天几板/断板反包）+ 当日板型行（炸板波次/回封）+ 板块地位块 + 热榜。

    批次C I10（顺手）：jiuyan_doc 由调用方传入（day_population 已读过同一文档），
    缺省时兼容旧路径自行读取——消除每股一次整日文档的 N+1 查询。
    """
    jy = jiuyan_doc if jiuyan_doc is not None else db["jiuyan_action"].find_one(
        {"_id": f"{date}:final"}, {"fields": 1}) or {}
    ths = ths_positions(db, date, dataset_id).get(code)
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
        f"{date} 交易日 · {market_facts_line(db, date, dataset_id)}",
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
               dataset_id: str = DEFAULT_DATASET_ID, jiuyan_doc: dict | None = None) -> tuple[bool, int]:
    """单只个股打标一次 jev 调用；include_stock_phase=True 时题目集升级为五题合并同 call
    （QUESTIONS_STOCK_WITH_PHASE，2026-10-04 用户裁决），相位答案随主 doc 同落——共享 narrative
    输入，相位边际成本≈题干+答案。usage/latency 为五题整 call 实付口径（stockPhaseUsage 同值）。
    批次B：新文档盖 ammoVersion 戳（原料代际，缺戳=旧代，fail-visible）。
    批次C：返回 (ok, 本次实付 tokens)（I12 成本口径=本次运行，不再全集合扫描）；
    doc 盖 questionSetVersion/questionSetHash（I15 判据代际）。"""
    questions = QUESTIONS_STOCK_WITH_PHASE if include_stock_phase else QUESTIONS_STOCK
    narrative = build_pilot_narrative(db, date, code, stock, board, rank,
                                      dataset_id=dataset_id, jiuyan_doc=jiuyan_doc)
    # 2026-10-10 起走 _dispatch_jev 分流（JEV_TYPESAFE_KEY 优先官方直连，否则 CF）；
    # acc/token 参数仅为调用方签名兼容，通道配置统一由 dispatch 自取 env。
    env, ms = _dispatch_jev(narrative, questions)
    # 缺题=partial_answers（degraded）：done 集合不视为已完成，下轮重跑补齐（2026-10-05 批次A C2）
    parsed = parse_jev_response(env, ms, expected_keys=set(questions))
    used = _usage_tokens(parsed.get("usage"))
    answers = parsed.get("answers") or {}
    doc = {"_id": f"{date}:{code}", "origin": "driver_label_jiuyan_v3_pilot", "tradingDate": date,
           "code": code, "name": stock.get("name"), "ammoVersion": AMMO_VERSION,
           "questionSetVersion": QUESTION_SET_VERSION_DRIVER,
           "questionSetHash": _questions_hash(questions),
           "jiuyanContext": {"board": board, "day": stock.get("day"), "num": stock.get("num"),
                             "time": stock.get("time"), "inHotlist": rank is not None, "rank": rank},
           "status": "ok" if parsed["ok"] else "degraded",
           "narrative": narrative, "questionsRaw": questions,
           # answers 原样落库（P0-2/P0-3，jev-questionset-ammo-confidence-review.md §五）：
           # 对齐情绪链先例，保全模型自报 confidence/缺失 probabilities/未来新字段，
           # 只向前生效，历史文档不可回补
           "answers": parsed.get("answers"),
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
        confirm_budget: bool = False, max_stocks: int | None = None):
    db = _db()
    col = db["hotlist_jev_driver_labels"]
    dates = sorted({str(d["tradingDate"]) for d in db["jiuyan_action"].find(
        {"kind": "jiuyan_action", "tradingDate": {"$gte": start, "$lte": end}},
        {"tradingDate": 1}) if d.get("tradingDate")})
    if not dates:
        print(f"窗口 {start}~{end} 无 jiuyan_action final 文档，退出（fail-visible）")
        return
    n_ok = n_deg = 0
    run_tokens: list[int] = []  # 批次C I12：本次运行实付（total_tokens 优先，否则 input+output）
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
        if max_stocks is not None and len(codes) > max_stocks:
            print(f"[{di + 1}/{len(dates)}] {date} {len(codes)} 只超上限 {max_stocks}，"
                  f"截断到前 {max_stocks} 只（其余明日记账，fail-visible）")
            codes = codes[:max_stocks]
        if not dry_run and not confirm_budget:
            # 批次C I13：开火前预算确认（AGENTS §1.2-7）。排程链由 --confirm-budget 携带
            # 2026-10-03 挂链裁决的常态批准；手动多日回填必须显式确认。
            raise SystemExit(
                f"预算护栏：本窗口预计至少 {len(codes)} 次 jev 真实调用（首日 {date}，"
                f"全量口径参考 ≈21 万 tokens/交易日）。确认预算请加 --confirm-budget；"
                f"或先 --dry-run 查看叙事。")
        ranks = hotlist_ranks(db, date, list(items.keys()), dataset_id)
        # 批次C I10（顺手）：整日韭研文档只读一次，传给每只股票的叙事构造（原每股重读一次）
        jy_doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields": 1}) or {}
        if dry_run:
            sample = items[codes[0]]
            print(f"[dry] {date} {sample['stock'].get('name')}\n" + build_pilot_narrative(
                db, date, codes[0], sample["stock"], sample["board"], ranks.get(codes[0]),
                dataset_id=dataset_id, jiuyan_doc=jy_doc))
            print(f"[{di + 1}/{len(dates)}] {date} population={len(codes)} hotlistHit={len(ranks)}")
            continue

        def work(code):
            entry = items[code]
            last_err: str | None = None
            for attempt in range(2):
                try:
                    ok, used = _label_one(db, col, acc, token, date, code, entry["stock"],
                                          entry["board"], ranks.get(code),
                                          include_stock_phase=with_stock_phase,
                                          dataset_id=dataset_id, jiuyan_doc=jy_doc)
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
        print(f"[{di + 1}/{len(dates)}] {date} done n={len(codes)} (cum ok={n_ok} deg={n_deg})")
    if not dry_run:
        # 批次C I12：FINAL 口径=本次运行实付（不再全集合扫历史 usage，不再 total_tokens/input+output 键名漂移）
        print("FINAL:", {"ok": n_ok, "degraded": n_deg,
                         "totalTokens": sum(run_tokens), "calls": len(run_tokens)})




def trajectory_line(db, date: str, n: int = 10,
                    dataset_id: str = DEFAULT_DATASET_ID) -> str:
    """近 n 个交易日逐日序列：日期|涨停(较昨日Δ)|跌停|炸板率%|大幅回撤|最高板。"""
    window = trading_dates_before(db, date, n + 1, dataset_id=dataset_id)  # 首日仅为算首格 Δ
    series = []
    for d in window:
        m = market_metrics(db, d, dataset_id) or {}
        die = dieban_count(db, d, dataset_id)
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
        ad = advdec_ratio(db, r["d"], dataset_id)
        ad_txt = f'{ad[3]}' if ad else "?"
        rows.append(f'{r["d"][5:]}|涨停{zt_txt}({delta})|跌停{die_txt}|炸板{r["rate"]}|回撤{dd_txt}|板{mb_txt}|涨跌比{ad_txt}')
    head = f'近{len(rows)}个交易日序列（日期|涨停(较昨日Δ)|跌停|炸板率|大幅回撤|最高板|池内涨跌比）：'
    return head + " ； ".join(rows)




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


def build_cycle_narrative(db, date: str,
                          dataset_id: str = DEFAULT_DATASET_ID) -> str:
    lines = [
        f"{date} 交易日",
        market_facts_line(db, date, dataset_id),
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
               "questionSetVersion": QUESTION_SET_VERSION_DRIVER,
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
        narrative = f"{date} 交易日 · {market_facts_line(db, date, dataset_id)}"
        env, ms = _dispatch_jev(narrative, QUESTIONS_PHASE)
        parsed = parse_jev_response(env, ms, expected_keys=set(QUESTIONS_PHASE))
        answers = parsed.get("answers") or {}
        doc = {"_id": f"{date}:PHASE", "origin": "phase_band_daily", "tradingDate": date,
               "ammoVersion": AMMO_VERSION,
               "questionSetVersion": QUESTION_SET_VERSION_DRIVER,
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
    ap.add_argument("--max-stocks", dest="max_stocks", type=int, default=None,
                    help="批次C I13：单日打标上限（超出部分截断并披露），不给=不限")
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
            confirm_budget=args.confirm_budget, max_stocks=args.max_stocks)
