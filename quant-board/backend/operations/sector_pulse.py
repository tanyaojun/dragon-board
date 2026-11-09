# -*- coding: utf-8 -*-
"""板块节点 V2c 盘中红盘提示（sector-pulse，2026-10-25）：昨日封窗 N10 + 批量实时报价。

预登记：docs/hotlist-jev/sector-nodes-v2c-intraday-preregistration.md（四项用户拍板：
成员=昨日封窗 N10 冻结 / 8000 按需读口 / 弱转强候选优先 / 每日 15:00 帧落库）。
证据基线：sector-agg-replay-study-20261024.md §三（真 N10：早盘分离 +8~13pp 温和、
午后 +18~20pp 强；组内离散大 → 提示列不进节点判定，预登记 §六 冻结）。

- 成员口径：昨日（最近上一交易日）封窗 N10 并集——以昨日为 target 取
  「昨日+最近 9 个池 ok 日」，盘中不变；今日新涨停股不在内（前端注记披露，
  16:20 正式判档链归位）。窗口池直查 `day_leader_rows`（**不走
  `_window_pool_of`**：其 `_POOL_CACHE` 无版本键，审计 2026-10-24 P3 约束
  长驻进程禁用，本模块常驻 8000 读口）。
- 报价：mootdx `client.quotes` 批量（80/批，price/last_close/amount 现成）；客户端复用
  `_tdx_daily_client`（内含 SetupCmd3 握手补丁）；60s 进程内缓存共享上游取数。
- fail-visible：报价不可考（全节点负缓存 / quotes 全批次异常）→ pulse=None+原因；
  成员缺报价计 missingN；全缺统计值 None 不伪 0。
- 15:00 帧：交易日 ≥15:05 首次请求幂等 upsert `hotlist_jev_sector_pulse`
  （`_id={date}:PULSE`），攒前向校准样本；非交易日 / 报价不可考不落帧。
- V4-E 日内量能（2026-11-01，用户 A 拍板，预登记
  sector-nodes-v4e-intraday-vol-preregistration.md）：quotes 增抓当日累计
  成交额 amount（元）；30 分钟机会式帧序列（帧末+5 分钟捕获窗）落
  `doc.frames[frameKey]`（帧内板块红盘读数+成员级 amount 明细）；量比=
  成员级「今日帧累计/昨日同帧累计」配对中位（V4-D 教训：合计比混成员漂移
  噪声不用；昨日同帧缺/成员缺任一侧则剔除，不铸 0）；候选层 volTag
  「量能确认/缩量翻红」提示（回放实测 102 日翻红&量比≥1.0 命中率 47% vs
  翻红基线 38%、全程缩量 27%）——**提示层不进节点判定、不改收盘档**
  （V2c §六 冻结延续）。历史帧经 lc5 回填（src=lc5_backfill，量比基线
  立即可用）。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, time
from typing import Any, Callable

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
from backend.operations.jev_label_jiuyan import (
    _POSITION_LOCK,
    _tdx_daily_client,
    jiuyan_streak_map,
    trading_dates_before,
)
from backend.operations.theme_leader_baseline import day_leader_rows
from backend.operations.leader_wzs import window_changes_for

PULSE_VERSION = "2026-11-02a"   # v4f: 核心票翻红率（昨日连板≥2 子集）+ 成交额量级分位
COLLECTION_PULSE = "hotlist_jev_sector_pulse"
COLLECTION_NODES = "hotlist_jev_sector_nodes"
_QUOTES_BATCH = 80          # tdxpy get_security_quotes 单批上限
_CACHE_TTL_SECONDS = 60
_WEAK_CANDIDATE_NODES = {"weakening", "collapse"}

# V4-E 30 分钟帧序列：帧键=帧末时标；捕获窗=帧末~+5 分钟内的请求幂等落该帧
# （保证帧读数≈帧末累计语义）；15:00 帧沿用 V2c ≥15:05 条款。
_FRAME_KEYS = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
_FRAME_TOLERANCE_MIN = 5
_VOL_CONFIRM_RATIO = 1.0    # 回放实测分离界（≥1.0 命中率 47% vs 基线 38%）

# 60s 读口缓存 {date: (ts, payload)}——多端轮询共享一次上游取数；键含日期，
# 历史日走 stored 帧不进本缓存。窗口池不走 `_POOL_CACHE`（无版本键，审计
# 2026-10-24 P3：长驻进程禁用），本模块每次直查 `day_leader_rows`。
_PULSE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _day_pool_direct(db: Any, date: str, dataset_id: str
                     ) -> dict[str, set[str]] | None:
    """单日 {板块: 封板 code 集}，直查不缓存（与 `_window_pool_of` 同语义的
    无缓存版：THS 池缺失 / final 缺失 → None 不进窗口）。"""
    rows, meta = day_leader_rows(db, date, dataset_id)
    if rows is None or not meta.get("jiuyanFinalFound", True):
        return None
    pool: dict[str, set[str]] = {}
    for r in rows:
        b = str(r.get("board") or "")
        if b:
            pool[b] = {str(c) for c in (r.get("boardCodes") or [])}
    return pool


def _frozen_union(db: Any, today: str, dataset_id: str = DEFAULT_DATASET_ID
                  ) -> tuple[dict[str, set[str]], str | None]:
    """昨日封窗 N10 成员并集：{board: codes} + 根因（昨日交易日不存在时 None）。

    以昨日为 target 取「昨日+最近 9 个池 ok 日」（trading_dates_before 升序
    返回旧→新，须 reversed——同 operations._agg_rows_compute 取窗教训）。
    """
    prevs = trading_dates_before(db, today, 1, dataset_id=dataset_id)
    if not prevs:
        return {}, "无昨日交易日，封窗成员不可考"
    prev = prevs[-1]
    candidates = [prev] + list(reversed(
        trading_dates_before(db, prev, 15, dataset_id=dataset_id)))
    pools: list[tuple[str, dict[str, set[str]]]] = []
    for d in candidates:
        pool = _day_pool_direct(db, d, dataset_id)
        if pool is not None:
            pools.append((d, pool))
        if len(pools) >= 10:
            break
    members: dict[str, set[str]] = {}
    for _d, pool in pools:
        for board, codes in pool.items():
            members.setdefault(board, set()).update(codes)
    return members, None


def _prev_nodes(db: Any, today: str, dataset_id: str = DEFAULT_DATASET_ID
                ) -> dict[str, str]:
    """昨日节点（sector-nodes 文档读口）；昨日文档缺失 → 空 dict（候选层缺位如实降级）。"""
    prevs = trading_dates_before(db, today, 1, dataset_id=dataset_id)
    if not prevs:
        return {}
    doc = db[COLLECTION_NODES].find_one({"_id": f"{prevs[-1]}:SECTOR_NODES"},
                                        {"rows.node": 1, "rows.board": 1})
    if not doc:
        return {}
    return {str(r["board"]): str(r["node"]) for r in doc.get("rows") or []
            if r.get("board") and r.get("node")}


def _amount_sum_history(db: Any, today: str, days: int = 60,
                        dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, list[float]]:
    """V4-F 量级分位基线：近 days 个交易日各板块活跃股聚合成交额序列
    （历史 nodes doc rows[].aggN10.amountSum，V2d 回填全史在档）。
    口径注意：历史值=全天累计，盘中实时额对比全天分位早盘天然偏低（随时间
    逼近真实分位），调用方 tooltip 如实标注。档缺=该日缺口，不插值。
    """
    dates = trading_dates_before(db, today, days, dataset_id=dataset_id)
    out: dict[str, list[float]] = {}
    for d in dates:
        try:
            doc = db[COLLECTION_NODES].find_one(
                {"_id": f"{d}:SECTOR_NODES"},
                {"rows.board": 1, "rows.aggN10.amountSum": 1})
        except Exception:
            continue
        if not doc:
            continue
        for r in doc.get("rows") or []:
            v = ((r.get("aggN10") or {}).get("amountSum"))
            if v is not None:
                out.setdefault(str(r["board"]), []).append(float(v))
    return out


def _amount_pct(hist: list[float], value: float | None,
                min_n: int = 20) -> tuple[float | None, int]:
    """量级分位（值在历史序列中的占比位置，0~1）；样本 <min_n / 值不可考 →
    (None, n) 如实（不硬算不铸 0）。"""
    if value is None or value <= 0 or len(hist) < min_n:
        return None, len(hist)
    below = sum(1 for v in hist if v < value)
    return round(below / len(hist), 3), len(hist)


def _strong_stats(quotes_map: dict[str, tuple[float, float, float | None]] | None,
                  codes: set[str]) -> dict[str, Any]:
    """V4-F 核心票子集实时翻红率（方法论：强势股集体翻红才是信号，全体红盘率
    混入普通跟风票；子集=昨日连板≥2，连板高度取 jiuyan_streak_map 单一事实源）。
    口径与 _pulse_stats 同（price/last_close−1>0 计红盘）。空子集=全 None。"""
    pcts: list[float] = []
    for code in sorted(codes):
        q = (quotes_map or {}).get(code)
        if q is None:
            continue
        pcts.append((q[0] / q[1] - 1) * 100)
    quoted = len(pcts)
    out: dict[str, Any] = {"strongN": len(codes), "strongQuotedN": quoted,
                           "strongRedN": None, "strongRedRatio": None}
    if quoted:
        out["strongRedN"] = sum(1 for p in pcts if p > 0)
        out["strongRedRatio"] = round(out["strongRedN"] / quoted, 3)
    return out


def _fetch_quotes(codes: set[str]) -> dict[str, tuple[float, float, float | None]] | None:
    """批量实时报价 {code: (price, last_close, amount)}；不可考 → None。

    None 两种成因（调用方合并披露）：客户端不可用（全节点负缓存）/ 全批次
    quotes 异常且零成交（网络/主站断）。price/last_close ≤0（退市/无效/未开盘
    无昨收）不入表，调用方按缺报价披露；部分批次异常按缺报价披露不整段判死。
    amount=当日累计成交额（元，TDX quotes 现成）：缺列/NaN → None（fail-visible，
    不铸 0）；0 是真读数（冷门股盘中零成交）保留，量比配对时 >0 要求自然剔除。
    """
    client = _tdx_daily_client()
    if client is None:
        return None
    ordered = sorted(codes)
    out: dict[str, tuple[float, float, float | None]] = {}
    batch_error = False
    for i in range(0, len(ordered), _QUOTES_BATCH):
        batch = ordered[i:i + _QUOTES_BATCH]
        try:
            with _POSITION_LOCK:
                df = client.quotes(symbol=batch)
        except Exception:
            batch_error = True
            continue
        if df is None or len(df) == 0:
            continue
        for _, r in df.iterrows():
            try:
                price, last_close = float(r["price"]), float(r["last_close"])
            except (KeyError, TypeError, ValueError):
                continue
            if price > 0 and last_close > 0:
                try:
                    amt = float(r["amount"])
                    if amt != amt:      # NaN
                        amt = None
                except (KeyError, TypeError, ValueError):
                    amt = None
                out[str(r["code"])] = (price, last_close, amt)
    if not out and batch_error:
        return None
    return out


def _member_amounts(quotes_map: dict[str, tuple[float, float, float | None]] | None,
                    codes: set[str]) -> dict[str, float]:
    """帧内成员 amount 明细 {code: 元}；amount 不可考的成员不入表（由
    amountMissingN 披露），不铸 0（fail-visible）。"""
    if quotes_map is None:
        return {}
    out: dict[str, float] = {}
    for code in sorted(codes):
        q = quotes_map.get(code)
        if q is not None and q[2] is not None:
            out[code] = q[2]
    return out


def _board_vol_ratio(prev_boards: dict[str, Any] | None, board: str,
                     amounts: dict[str, float]) -> tuple[float | None, int]:
    """成员级量比中位（V4-D 口径）：今日帧累计 / 昨日同帧累计，配对样本。

    配对要求两侧均存在且 >0（昨日缺该成员/缺帧/零成交 → 该成员整体剔除，
    不铸 0 不偏估）；配对空 → (None, 0)（调用方透出 volBasis 原因）。
    """
    prev_amounts = (((prev_boards or {}).get(board) or {}).get("amounts")) or {}
    ratios: list[float] = []
    for code, amt in amounts.items():
        pa = prev_amounts.get(code)
        if pa is not None and pa > 0 and amt > 0:
            ratios.append(amt / pa)
    if not ratios:
        return None, 0
    ratios.sort()
    n = len(ratios)
    med = ratios[n // 2] if n % 2 else (ratios[n // 2 - 1] + ratios[n // 2]) / 2
    return round(med, 3), n


def _pulse_stats(quotes_map: dict[str, tuple[float, float, float | None]] | None,
                 codes: set[str]) -> dict[str, Any]:
    """单板块盘中统计（与回放研究 §三 同口径：price/last_close−1）。

    quotes_map=None → 整板块不可考（pulse 本体 None 由调用方置）；全成员缺报价
    → 统计值 None 不伪 0。红盘率=price>last_close 占比（收盘红盘率语义，
    非盘中绿转红——键名沿用落库 redRatio）。V4-E 增 amountSum/amountQuotedN/
    amountMissingN（当日累计成交额聚合，元；amount 不可考成员不计入，
    amountQuotedN+amountMissingN=quotedN 对账）。
    """
    pcts: list[float] = []
    amount_sum = 0.0
    amount_quoted = 0
    for code in sorted(codes):
        q = (quotes_map or {}).get(code)
        if q is None:
            continue
        pcts.append((q[0] / q[1] - 1) * 100)
        if q[2] is not None:
            amount_sum += q[2]
            amount_quoted += 1
    quoted = len(pcts)
    stats: dict[str, Any] = {"memberN": len(codes), "quotedN": quoted,
                             "missingN": len(codes) - quoted,
                             "amountSum": round(amount_sum, 2) if amount_quoted else None,
                             "amountQuotedN": amount_quoted,
                             "amountMissingN": quoted - amount_quoted}
    if quoted == 0:
        stats.update({"pctMean": None, "pctMedian": None, "redRatio": None})
        return stats
    ordered = sorted(pcts)
    stats["pctMean"] = round(sum(pcts) / quoted, 2)
    stats["pctMedian"] = round(ordered[quoted // 2] if quoted % 2
                               else (ordered[quoted // 2 - 1]
                                     + ordered[quoted // 2]) / 2, 2)
    stats["redRatio"] = round(sum(1 for p in pcts if p > 0) / quoted, 3)
    return stats


def _evidence_stage(now: datetime) -> str:
    """时点证据段（回放研究 §三：早盘 +8~13pp 温和 / 13:30 后 +18~20pp 强）。"""
    hm = now.strftime("%H:%M")
    if hm < "09:30":
        return "pre_open"       # 盘前报价=昨收，读数无意义
    if hm < "13:30":
        return "early"
    if hm < "15:00":
        return "strong"
    return "closed"


_EVIDENCE_CN = {"pre_open": "盘前（报价=昨收，读数无意义）",
                "early": "早盘（历史证据 +8~13pp，温和）",
                "strong": "午后（历史证据 +18~20pp，强）",
                "closed": "收盘读数（15:00 后）"}


def _frame_key_of(now: datetime) -> str | None:
    """V4-E 机会式帧捕获窗：请求落在帧末~+5 分钟内 → 落该帧（帧读数≈帧末累计）。

    15:00 帧沿用 V2c ≥15:05 条款。窗外的请求不落帧（frameSkip 披露，不污染
    帧末语义）；午休（11:35~13:30）与 14:35~15:05 天然无窗。
    """
    minutes = now.hour * 60 + now.minute
    for key in _FRAME_KEYS:
        end_h, end_m = key.split(":")
        end = int(end_h) * 60 + int(end_m)
        if key == "15:00":
            lo, hi = 15 * 60 + 5, 10 ** 9
        else:
            lo, hi = end, end + _FRAME_TOLERANCE_MIN
        if lo <= minutes <= hi:
            return key
    return None


def _latest_frame_stats(db: Any, today: str) -> tuple[str | None, dict[str, Any] | None]:
    """当日 doc 中最近已落帧（含 lc5 回填帧）：供候选层 volTag 装配。"""
    try:
        doc = db[COLLECTION_PULSE].find_one({"_id": f"{today}:PULSE"},
                                            {"frames": 1})
    except Exception:
        return None, None
    frames = (doc or {}).get("frames") or {}
    for key in reversed(_FRAME_KEYS):
        if key in frames:
            return key, frames[key]
    return None, None


def _vol_tag_of(frame_board: dict[str, Any] | None) -> str | None:
    """帧内红盘 & 量比可考 → vol_confirm（≥界）/ vol_thin（<界）；
    缺帧/帧内不红/量比不可考 → None（不注记，fail-visible）。"""
    if not frame_board:
        return None
    pct_mean, red_ratio, vr = frame_board.get("pctMean"), frame_board.get("redRatio"), \
        frame_board.get("volRatioMedian")
    if pct_mean is None or pct_mean <= 0 or (red_ratio or 0) < 0.5:
        return None
    if vr is None:
        return None
    return "vol_confirm" if vr >= _VOL_CONFIRM_RATIO else "vol_thin"


def compute_pulse(db: Any, today: str, dataset_id: str = DEFAULT_DATASET_ID,
                  *, now: datetime | None = None,
                  quotes_fetcher: Callable[[set[str]],
                                           dict[str, tuple[float, float, float | None]] | None]
                  | None = None) -> dict[str, Any]:
    """盘中读数全量计算（routes 唯一入口；quotes_fetcher 注入供测试/重放）。

    候选层=昨日节点∈{转弱,退潮}（弱转强候选，置顶）；全量层=封窗 N10 全部板块。
    V4-E：候选层 volTag「量能确认/缩量翻红」基于当日最近已落帧（live/回填），
    提示层不进节点判定；帧捕获窗内幂等落帧（盘中帧+15:00 帧）。
    非交易日当日读数=最近交易日收盘口径（报价停留在收盘价），证据段强制
    closed 并注记——不按钟表误标「早盘/盘前」（2026-10-25 用户验收反馈）。
    """
    now = now or datetime.now()
    stage = _evidence_stage(now)
    meta: dict[str, Any] = {"reason": None, "framesSaved": False}
    is_trading_day = True
    try:
        import datetime as _dt
        from backend.snapshot_collector.trading_calendar import is_trading_day_cached
        is_trading_day, td_source = is_trading_day_cached(_dt.date.fromisoformat(today))
        if not is_trading_day:
            stage = "closed"
            meta["tradingDayNote"] = f"今日非交易日（{td_source}），读数为最近交易日收盘口径"
    except Exception as exc:   # 判定不可用：按钟表分段 + 注记（fail-visible）
        meta["tradingDayNote"] = f"交易日判定不可用：{exc}"
    payload: dict[str, Any] = {
        "ok": True, "kind": "sector_pulse", "version": PULSE_VERSION,
        "date": today, "computedAt": now.isoformat(timespec="seconds"),
        "evidenceStage": stage,
        "candidates": [], "all": [],
        "meta": meta,
    }
    members, root = _frozen_union(db, today, dataset_id)
    if root:
        payload["meta"]["reason"] = root
        return payload
    if not members:
        payload["meta"]["reason"] = "昨日封窗无任何池 ok 日，成员集为空"
        return payload
    prev_nodes = _prev_nodes(db, today, dataset_id)
    # V4-E 量比基线：昨日同帧 boards（live/回填均可，口径同为帧末累计）
    prev_frame_boards: dict[str, Any] | None = None
    prevs = trading_dates_before(db, today, 1, dataset_id=dataset_id)
    if prevs:
        try:
            prev_doc = db[COLLECTION_PULSE].find_one(
                {"_id": f"{prevs[-1]}:PULSE"}, {"frames": 1})
            prev_frame_boards = (prev_doc or {}).get("frames") or {}
        except Exception:
            prev_frame_boards = None
    fetch = quotes_fetcher or _fetch_quotes
    # V4-F 原料：核心票子集（昨日连板≥2，jiuyan_streak_map 单一事实源）+
    # 量级分位基线（近 60 日 aggN10.amountSum）；不可考时如实空（fail-visible）
    streak_map: dict = {}
    if prevs:
        try:
            streak_map = jiuyan_streak_map(db, prevs[-1],
                                           dataset_id=dataset_id) or {}
        except Exception:
            streak_map = {}
    try:
        amt_hist = _amount_sum_history(db, today, days=60)
    except Exception:
        amt_hist = {}
    all_codes: set[str] = set()
    for codes in members.values():
        all_codes |= codes
    quotes_map = fetch(all_codes)
    hint_chip = False
    for board in sorted(members):
        codes = members[board]
        if quotes_map is None:
            pulse = None
        else:
            pulse = _pulse_stats(quotes_map, codes)
            if (pulse["pctMean"] is not None and pulse["pctMean"] > 0
                    and (pulse["redRatio"] or 0) >= 0.5):
                hint_chip = True
        entry: dict[str, Any] = {"board": board,
                                 "yesterdayNode": prev_nodes.get(board),
                                 "pulse": pulse}
        strong_codes = {c for c in codes
                        if (streak_map.get(c) or 0) >= 2}
        entry.update(_strong_stats(quotes_map, strong_codes))
        # V4-G 盯盘票清单：核心票明细（code→昨日连板高度），缺 3 子集的展开
        entry["strongCodes"] = sorted(strong_codes)
        entry["strongStreaks"] = {c: streak_map[c] for c in strong_codes}
        apct, apct_n = _amount_pct(amt_hist.get(board) or [],
                                   (pulse or {}).get("amountSum") if pulse else None)
        entry["amountPct"], entry["amountPctN"] = apct, apct_n
        payload["all"].append(entry)
        if prev_nodes.get(board) in _WEAK_CANDIDATE_NODES:
            cand = dict(entry)
            cand["hint"] = bool(pulse and pulse.get("pctMean") is not None
                                and pulse["pctMean"] > 0
                                and (pulse.get("redRatio") or 0) >= 0.5)
            payload["candidates"].append(cand)
    if quotes_map is None:
        payload["meta"]["reason"] = ("TDX 盘中报价不可考（全节点不可用负缓存 / "
                                     "quotes 全批次异常且零成交）")
    payload["hintAny"] = hint_chip
    payload["evidenceStageCN"] = _EVIDENCE_CN[payload["evidenceStage"]]
    if quotes_map is None:
        # 报价不可考不落帧：全 None 帧进校准样本集是污染；TDX 恢复后同日再请求
        # 即可正常落帧（幂等同键）。
        payload["meta"]["frameSkip"] = "报价不可考，不落帧（校准样本不入 null 帧）"
    else:
        _maybe_save_frame(db, payload, now, is_trading_day, prev_frame_boards,
                          members, quotes_map)
    # V4-E volTag：落帧后取当日最近帧（含本请求刚落的 live 帧/回填帧）
    # 全部行透出量比数值（用户观察位：直显放量/缩量，不只候选 chip）
    latest_key, latest_frame = _latest_frame_stats(db, today)
    for e in payload["all"]:
        fb = (latest_frame or {}).get("boards", {}).get(e["board"])
        vr = (fb or {}).get("volRatioMedian")
        e["volRatioMedian"] = vr
        e["volFrame"] = latest_key if vr is not None else None
    for cand in payload["candidates"]:
        fb = (latest_frame or {}).get("boards", {}).get(cand["board"])
        cand["volTag"] = _vol_tag_of(fb)
        cand["volTagFrame"] = latest_key if cand["volTag"] else None
        # 量比数值无条件透出（与 all 行同款；review 2026-11-01：条件赋值导致
        # 量比可考但不红的候选在盯盘清单显示「量能 --」，与 all 行不一致）
        cand["volRatioMedian"] = (fb or {}).get("volRatioMedian")
    return payload


def _maybe_save_frame(db: Any, payload: dict[str, Any], now: datetime,
                      is_trading_day: bool,
                      prev_frame_boards: dict[str, Any] | None,
                      members: dict[str, set[str]],
                      quotes_map: dict[str, tuple[float, float, float | None]]) -> None:
    """V4-E 帧落库：帧捕获窗内幂等落帧（盘中 30 分钟帧 + 15:00 帧）。

    - 帧捕获窗：_frame_key_of（帧末+5 分钟；15:00 帧 ≥15:05）；窗外请求
      frameSkip 披露不落帧（保帧末语义）；非交易日不落帧。
    - 帧数据：板块红盘读数 + 成员级 amount 明细 + 量比（昨日同帧配对中位，
      volBasis 披露基线成因）；与 lc5 回填帧同结构（src 区分）。
    - 写入：update_one $set upsert——顶层字段仅 15:00 帧更新（保留盘中帧
      与其他帧键），盘中帧只写 frames.{key}；写库失败不抛（读口展示数据
      不因次要写库连坐降级），frameSkip 如实披露。
    """
    key = _frame_key_of(now)
    if key is None:
        payload["meta"]["frameSkip"] = "非帧捕获窗（帧末+5 分钟），不落帧"
        return
    if not is_trading_day:
        payload["meta"]["framesSaved"] = False
        payload["meta"]["frameSkip"] = "非交易日不落帧"
        return
    vol_basis = "prev_frame" if prev_frame_boards else "prev_frame_missing"
    # 昨日同帧 boards（同帧自比，控日内节奏）；昨日无该帧 → 基线缺失如实降级
    prev_same_frame_boards = (prev_frame_boards or {}).get(key, {}).get("boards")
    boards: dict[str, Any] = {}
    for board in sorted(members):
        codes = members[board]
        if quotes_map is None:
            continue
        stats = _pulse_stats(quotes_map, codes)
        amounts = _member_amounts(quotes_map, codes)
        vol_med, vol_n = _board_vol_ratio(prev_same_frame_boards, board, amounts)
        boards[board] = {**stats, "amounts": amounts,
                         "volRatioMedian": vol_med, "volRatioQuotedN": vol_n}
    frame_data: dict[str, Any] = {
        "at": now.isoformat(timespec="seconds"), "src": "live",
        "volBasis": vol_basis, "boards": boards,
    }
    # 乐观值先行（写库失败则回滚，update_one 抛异常=未写入）
    payload["meta"]["framesSaved"] = True
    payload["meta"]["frameSavedKey"] = key
    set_doc: dict[str, Any] = {f"frames.{key}": frame_data}
    if key == "15:00":   # 顶层语义=收盘读数，仅 15:00 帧更新（保留 frames 其他键）
        for k in ("kind", "version", "date", "computedAt", "evidenceStage",
                  "candidates", "all", "hintAny", "meta"):
            if k in payload:
                set_doc[k] = payload[k]
    try:
        db[COLLECTION_PULSE].update_one({"_id": f"{payload['date']}:PULSE"},
                                        {"$set": set_doc}, upsert=True)
    except Exception as exc:
        payload["meta"]["framesSaved"] = False
        payload["meta"]["frameSkip"] = f"帧写入失败：{exc}"
        return


def get_pulse_cached(db: Any, today: str, dataset_id: str = DEFAULT_DATASET_ID,
                     *, now: datetime | None = None) -> dict[str, Any]:
    """60s 缓存壳（routes 调用）：同日 60s 内共享 payload，过期重算。"""
    now = now or datetime.now()
    hit = _PULSE_CACHE.get(today)
    if hit and now.timestamp() - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    payload = compute_pulse(db, today, dataset_id, now=now)
    _PULSE_CACHE[today] = (now.timestamp(), payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    """CLI 冒烟/重放：--day 缺省=今日；历史日只读 stored 帧。"""
    import argparse
    ap = argparse.ArgumentParser(description="V2c 盘中红盘提示（零 token）")
    ap.add_argument("--day", help="目标日（缺省=今天）；历史日读 stored 帧")
    args = ap.parse_args(argv)
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    db = get_runtime_mongodb_database()
    today = datetime.now().strftime("%Y-%m-%d")
    day = args.day or today
    if day != today:
        frame = db[COLLECTION_PULSE].find_one({"_id": f"{day}:PULSE"})
        print(json.dumps({"ok": True, "source": "stored", "doc": frame},
                         ensure_ascii=False, default=str))
        return 0
    print(json.dumps(get_pulse_cached(db, day), ensure_ascii=False, default=str))
    return 0




# ══════════ V4-G 盯盘票清单（第 5 课缺口 4；Q1a/Q2a/Q3a/Q4a 用户拍板）══════════

def _code6(code: str | None) -> str:
    """code 归一（与前端 lbCode 同规则）：剥交易所前缀取尾 6 位；无法归一返回原串。"""
    m = re.search(r"(\d{6})\s*$", str(code or ""))
    return m.group(1) if m else str(code or "")


def _jiuyan_name_map(db: Any, dates: list[str | None]) -> dict[str, str]:
    """韭研档 stocks → {6位code: name}（龙一/核心票名称单一来源；档缺失日跳过）。"""
    from backend.operations.jiuyan_store import get_action_doc
    out: dict[str, str] = {}
    for d in dates:
        if not d:
            continue
        doc = get_action_doc(db, d, "final") or get_action_doc(db, d, "midday")
        for f in (doc or {}).get("fields") or []:
            for s in f.get("stocks") or []:
                c6 = _code6(s.get("code"))
                if c6 and s.get("name"):
                    out.setdefault(c6, str(s["name"]))
    return out


def _watch_ticket(code: str, name: str | None, role: str, *, streak=None,
                  segment=None, gain10=None, leader_sealed=None,
                  quotes_map: dict | None = None,
                  window_k: int | None = None,
                  window_changes: list[dict] | None = None) -> dict[str, Any]:
    """票行：实时 pct/red 由 TDX 报价现算；报价不可考 → 全 None（fail-visible）。

    v5 预登记 P1：断板龙一带窗位 k（严格 3 日回溯）与窗内逐日涨跌幅
    （逆势表现，缺日如实缺失）。"""
    c6 = _code6(code)
    price = last_close = pct = None
    red: bool | None = None
    q = (quotes_map or {}).get(code) or (quotes_map or {}).get(c6)
    if q:
        price, last_close = q[0], q[1]
        if price and last_close:
            pct = round((price / last_close - 1) * 100, 2)
            red = pct > 0
    return {"code": c6, "name": name, "role": role, "streak": streak,
            "segment": segment, "gain10": gain10,
            "leaderSealedToday": leader_sealed,
            "windowK": window_k, "windowChanges": window_changes,
            "price": price, "lastClose": last_close, "pct": pct, "red": red}


def get_watchlist(db: Any, today: str, dataset_id: str = DEFAULT_DATASET_ID, *,
                  now: datetime | None = None,
                  quotes_fetcher: Callable[[set[str]],
                                           dict[str, tuple[float, float, float | None]] | None]
                  | None = None) -> dict[str, Any]:
    """V4-G 盯盘票清单读口（提示层，不进判据；预登记 v4f 文档 §六）。

    板块=当日弱转强候选（pulse candidates，Q2a）；票=①观察窗内分轨空间龙一
    （space_mode 含断板反包候选、segment 分轨，Q4a；候选窗=v5 预登记裁决 4：
    严格回溯 3 个封板日，窗位 k=T−S−1 随行披露，断板候选须真连板高度≥2、
    断板日未跌停）②昨日连板≥2 的 N10 冻结成员（缺口 3 核心票子集展开，Q1a）。方法论：炒作中预纳入自选，盘中看强势股集体翻红博弈
    收盘涨停数增多（第 5 课）。fail-visible：候选空/龙一基线缺失/报价不可考逐层
    如实透出，不伪 0 不静默。
    """
    now = now or datetime.now()
    pulse = get_pulse_cached(db, today, dataset_id, now=now)
    if not pulse.get("ok"):
        return {"ok": False, "reason": f"pulse_unavailable: {pulse.get('reason')}"}
    cand_rows = pulse.get("candidates") or []
    if not cand_rows:
        return {"ok": True, "today": today, "groups": [],
                "reason": "今日无弱转强候选板块（candidates 空，非异常）"}
    prevs = trading_dates_before(db, today, 3, dataset_id=dataset_id)
    prev_date = prevs[-1] if prevs else None
    leader_reason = None
    leader_rows: list[dict] = []
    leader_errors: list[dict[str, Any]] = []   # space 模式板块级缺料披露（review 2026-11-01）
    if prev_date:
        # v5 预登记裁决 4（2026-11-01）：盯盘池同步 3 日窗（严格回溯 3 个封板日），
        # 窗位 k=T−S−1 随行披露（k=0 今日断板候选提示；k=1/2 可反包末窗 k=2）；
        # 早间 T+1 收紧裁决被取代——实质根因修复均保留：height≥2 过滤、徽标措辞、
        # 窗外股不再滞留（k≥3 出池）。day_leader_rows 内部仍做 height≥2/未跌停过滤
        pool_dates = trading_dates_before(db, prev_date, 3, dataset_id=dataset_id)
        rows, meta = day_leader_rows(
            db, prev_date, dataset_id,
            # review P2：prev_date 须为 prev_date 的前一交易日（prevs[-2]），传 prevs[-1]
            # 会自指（prevPeers/prevTotal/prevStill 全部自比，事实行错误）
            prev_date=prevs[-2] if len(prevs) >= 2 else None,
            space_mode=True, pool_dates=pool_dates)
        if rows is None:
            leader_reason = f"昨日({prev_date}) THS 池缺失，龙一不可算（fail-visible）"
        else:
            # v5.1 三链合一锚定（2026-11-09 用户裁决）：昨日节点档存在（v5）时龙一行按档
            # 过滤；无档/历史回放保持原推导并披露未锚定
            from backend.operations.sector_nodes import (
                anchor_rows_to_ledger, ledger_leaders)
            try:
                _ledger = ledger_leaders(db, prev_date)
            except Exception as exc:
                _ledger = None   # advisory 锚定容错（mock/无节点集合）：未锚定，不阻断
                leader_reason = f"龙一台账读取异常（{type(exc).__name__}），按未锚定处理"
            rows, _anchor_info = anchor_rows_to_ledger(rows, _ledger)
            leader_rows = rows
            # v5.1 锚定落痕（P1-3 评审）：锚定/未锚定/剔除/漂移全披露，不静默
            if not _anchor_info.get("anchored"):
                leader_reason = leader_reason or "昨日节点档缺失/非 v5，龙一行未锚定（原推导口径）"
            elif _anchor_info.get("dropped") or _anchor_info.get("missing"):
                leader_errors.append({"board": "_ledgerAnchor",
                                      "reason": f"dropped={_anchor_info['dropped']} missing={_anchor_info['missing']}"})
            # space 模式「单板块 10 日涨幅全缺→板块跳过」的静默缺位如实透出
            # （meta["spaceErrors"] = {board: reason}，theme_leader_baseline 同源）
            for se_board, se_reason in ((meta or {}).get("spaceErrors") or {}).items():
                leader_errors.append({"board": se_board, "reason": se_reason})
    else:
        leader_reason = "无前一交易日，龙一不可算"
    name_by_code = _jiuyan_name_map(db, [prev_date, today])
    fetch = quotes_fetcher or _fetch_quotes
    # 票全集（原始 code 形式传 fetch，与 compute_pulse 同口径）
    raw_codes: set[str] = set()
    for e in cand_rows:
        raw_codes.update(e.get("strongCodes") or [])
        for lr in leader_rows:
            if lr.get("board") == e["board"]:
                raw_codes.add(str(lr.get("code") or ""))
    raw_codes.discard("")
    quotes_map = fetch(raw_codes) if raw_codes else None
    groups: list[dict[str, Any]] = []
    for e in cand_rows:
        board = e["board"]
        tickets: list[dict[str, Any]] = []
        seen: set[str] = set()
        for lr in leader_rows:
            if lr.get("board") != board:
                continue
            c6 = _code6(lr.get("code"))
            if c6 in seen:
                continue
            seen.add(c6)
            # 窗位（v5 预登记裁决 4）：pool_dates 升序 [P-3,P-2,P-1]，
            # k=(len-1)-index；k=0 今日断板候选提示，k=1/2 可反包（k=2 末窗）
            wk: int | None = None
            wchg: list[dict] | None = None
            pd_ = lr.get("poolDay")
            if not lr.get("leaderSealedToday") and pd_ in (pool_dates or []):
                wk = (len(pool_dates) - 1) - pool_dates.index(pd_)
                wchg = window_changes_for(c6, pd_, prev_date)
            tickets.append(_watch_ticket(
                lr.get("code"), lr.get("name") or name_by_code.get(c6), "leader",
                streak=lr.get("streak"), segment=lr.get("segment"),
                gain10=lr.get("gain10"), leader_sealed=lr.get("leaderSealedToday"),
                quotes_map=quotes_map, window_k=wk, window_changes=wchg))
        for c in e.get("strongCodes") or []:
            c6 = _code6(c)
            if c6 in seen:
                continue   # 龙一同时也是连板≥2 成员 → 只保留 leader 角色
            seen.add(c6)
            tickets.append(_watch_ticket(
                c, name_by_code.get(c6), "strong",
                streak=(e.get("strongStreaks") or {}).get(c),
                quotes_map=quotes_map))
        groups.append({
            "board": board, "hint": e.get("hint"),
            "yesterdayNode": e.get("yesterdayNode"),
            "strongN": e.get("strongN"), "strongQuotedN": e.get("strongQuotedN"),
            "strongRedN": e.get("strongRedN"),
            "strongRedRatio": e.get("strongRedRatio"),
            "amountPct": e.get("amountPct"), "amountPctN": e.get("amountPctN"),
            "volRatioMedian": e.get("volRatioMedian"),
            "volFrame": e.get("volFrame"), "tickets": tickets})
    out: dict[str, Any] = {"ok": True, "today": today, "prevDate": prev_date,
                           "groups": groups}
    if leader_reason:
        out["leaderReason"] = leader_reason
    if leader_errors:
        out["leaderErrors"] = leader_errors
    if not quotes_map and raw_codes:
        out["reason"] = "盘中报价不可考（TDX 全批次异常/空结果），票涨幅不可考（fail-visible）"
    return out

if __name__ == "__main__":
    import sys
    sys.exit(main())
