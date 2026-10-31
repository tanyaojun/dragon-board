# -*- coding: utf-8 -*-
"""上涨复盘读口聚合（2026-10-31 用户需求：JEV 叙事工作台新增【上涨复盘】页）。

页面语义：**当日上涨名单**（涨幅 > 5% 且未封涨停 / 触板未封 / 连涨），与【下跌复盘】
（jev_dieban_review）同一套展示语言（KPI 条 + 板块 chips + 筛选 + 可排序表 + 行展开）。
纯读 + 当日盘后一次懒加载（落 `market_daily_rise_stocks`），不发起任何模型调用。

## 口径（单一事实源，勿在页面另写一份）

1. **全市场逐股明细**：`market_rise_pool.rows_lazy` 读 `market_daily_rise_stocks`
   （一天一文档，本地通达信日线重算：涨幅 > 5% 且收盘未封涨停，价格精确闸 0.005 元）。
   缺文档 → `fullRise.rowsMissing` 结构化披露；当日盘后首次读触发懒加载（1 次/日）。
2. **采集池明细**：`snapshot_stock_rows` 当日 15:00 `half_hour` 快照行（250 只热榜采集池）。
   池内「未涨停」判定同一条价格精确闸（`is_sealed_limit_up`，基于 preClose/price）。
3. **触板未封**：全市场行用日线 `high ≈ 涨停价`（收盘未封）；采集池行用快照 `high`。
   缺高低价 → None（未知不判否，不写 False）。
4. **连涨（统一定义）**：逐日回溯「该日全市场上涨集合」（`market_daily_rise_stocks` 逐日
   code 集），回溯深度 `STREAK_LOOKBACK` 个交易日（含当日）；回溯窗内缺文档日 → 显式披露。
5. **近3日累计涨幅**：当前价 / 3 个交易日前 15:00 价 − 1（仅采集池行有价格史）；基准缺失 → None。
6. **振幅**：`(high − low) / preClose`（全市场日线行与采集池行都可算；缺前收 → None）。
7. **盘中**：15:00 帧未到 → 回落当日最新 `half_hour` 槽，`intraday=True`。

槽位行 / 槽位缓存 / 交易日回溯 / 数值化等基础设施**直接复用 jev_dieban_review 的实现**
（同一条 15:00 槽权威线，不写第二份）；进程内缓存（120s，含负缓存）同样复用其纪律。

fail-visible：只有「无采集池行 + 无全市场逐股文档」才报 `noData`；「0 只上涨」是真读数
（照常返回空名单，不当作缺口）。
"""
from __future__ import annotations

import time
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID, percentile_fraction
from backend.core.limit_rules import limit_up_price
from backend.operations import market_rise_pool as rp
from backend.services.jev import jev_dieban_review as _die

SNAPSHOT_TYPE = _die.SNAPSHOT_TYPE
CLOSE_SLOT = _die.CLOSE_SLOT
STRONG_PCT = 7.0         # 「大涨」展示线（叙事口径；名单基线是 RISE_MIN_PCT=5）
STREAK_LOOKBACK = 10     # 连涨回溯交易日上限（含当日）
RET_WINDOW = 3           # 近 N 日累计涨幅基准
HISTORY_DAYS = 20        # 全市场上涨家数分位窗口

# 进程内缓存：键 (date)；限长防长驻进程跨日累积（与 dieban 读口同纪律）
# 键不含 dataset_id：逐股文档按日期为键（与家数/逐股参考集合同规，不随 dataset 分文档）
# （对齐 dieban._full_market_rows 的键粒度，2026-10-31 review nit）
_RISE_ROWS_TTL = 120.0
_rise_rows_cache: dict[tuple[str], tuple[float, Any]] = {}


def reset_rise_cache() -> None:
    """清上涨逐股/回溯缓存（测试夹具用；进程内缓存跨用例会误导后续断言）。"""
    _rise_rows_cache.clear()


def _num(value: object) -> float | None:
    return _die._num(value)


def _code6(value: object) -> str:
    return _die._code6(value)


def _rise_rows(db: Any, date: str) -> dict[str, Any] | None:
    """全市场上涨逐股文档（含当日懒加载），120s 进程内缓存（含「缺文档」负缓存）。

    负缓存而非 None 哨兵直判：缓存值本身可能是 None（历史日未回填/当日未到截点），
    不缓存会让缺文档日每次 60s 轮询都全宇宙扫一遍日线。
    """
    key = (date,)
    hit = _rise_rows_cache.get(key)
    if hit is not None and time.monotonic() - hit[0] < _RISE_ROWS_TTL:
        return hit[1]
    doc = rp.rows_lazy(db, date)
    if len(_rise_rows_cache) > 512:
        _rise_rows_cache.clear()
    _rise_rows_cache[key] = (time.monotonic(), doc)
    return doc


def _rise_sets_for_dates(db: Any, dates: list[str]) -> tuple[dict[str, set[str]], int]:
    """逐日上涨集合（market_daily_rise_stocks，一次 $in 批量读）→ ({date: set(code)}, 有文档日数)。"""
    out: dict[str, set[str]] = {}
    docs = db[rp.COLLECTION_ROWS].find({"_id": {"$in": list(dates)}}, {"rows.code": 1}) if dates else []
    for doc in docs:
        out[str(doc["_id"])] = {_code6(r.get("code")) for r in (doc.get("rows") or []) if r.get("code")}
    return out, len(out)


def collect_rise_review(db: Any, date: str,
                        dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, Any]:
    """单日上涨名单聚合（涨幅>5% 未涨停 / 触板未封 / 连涨）。"""
    frame = _die._latest_slot(db, date, dataset_id)
    slot = str((frame or {}).get("slotTime") or CLOSE_SLOT)
    intraday = slot != CLOSE_SLOT
    rows = _die._slot_rows_cached(db, date, slot, dataset_id) if frame else {}

    # ── 连涨回溯 + 近 N 日基准（历史一律取 15:00 收盘槽）──
    prior = _die._prior_trading_dates(db, date, max(STREAK_LOOKBACK, HISTORY_DAYS + 1), dataset_id)
    rise_sets_by_date, hist_days = _rise_sets_for_dates(db, prior[-STREAK_LOOKBACK + 1:])
    price_by_date: dict[str, dict[str, float | None]] = {}
    slot_days = 0
    for d in prior:
        hist_rows = _die._slot_rows_cached(db, d, CLOSE_SLOT, dataset_id)
        if hist_rows:
            slot_days += 1
        price_by_date[d] = {c: _num(r.get("price")) for c, r in hist_rows.items()}
    base_date = prior[-RET_WINDOW] if len(prior) >= RET_WINDOW else None
    rise_hist = [rise_sets_by_date.get(d, set()) for d in prior[-STREAK_LOOKBACK + 1:]]

    full_today = _rise_rows(db, date)
    full_rows = (full_today or {}).get("rows") or []
    full_set = {_code6(r.get("code")) for r in full_rows if r.get("code")}
    pool_rise_set: set[str] = set()
    today_set = set(full_set)

    def _ret_since_base(code: str, price: float | None) -> float | None:
        if base_date is None or price is None or price <= 0:
            return None
        base = price_by_date.get(base_date, {}).get(code)
        if base is None or base <= 0:
            return None
        return round((price / base - 1) * 100, 2)

    # ── 采集池口径：涨幅>5% 且未封涨停（价格精确闸同一条线）────────────────────
    up = down = flat = 0
    stocks: dict[str, dict[str, Any]] = {}
    for code, row in rows.items():
        pct = _num(row.get("pctChange"))
        if pct is not None:
            if pct > 0.1:
                up += 1
            elif pct < -0.1:
                down += 1
            else:
                flat += 1
        pre_close = _num(row.get("preClose"))
        price = _num(row.get("price"))
        sealed = rp.is_sealed_limit_up(price, pre_close, code)
        limit_up = (_num(limit_up_price(code, pre_close)) if sealed is not None else None)
        rise = bool(pct is not None and pct > rp.RISE_MIN_PCT and sealed is not True)
        if rise:
            pool_rise_set.add(code)
            today_set.add(code)
        high = _num(row.get("high"))
        # 触板未封 = 盘中触及涨停价且收盘未封（事实判定，与是否入上涨名单无关：
        # 收盘回落到 +5% 以下的股也可能触板，2026-10-31 review minor）；
        # 封死涨停 → False（明确非「未封」）；缺 high/涨停价 → None（未知不判否）
        if sealed is True:
            touched = False
        elif high is not None and limit_up is not None:
            touched = abs(high - limit_up) <= 0.005
        else:
            touched = None
        low = _num(row.get("low"))
        stocks[code] = {
            "code": code,
            "name": row.get("name"),
            "board": row.get("sectorLabel") or row.get("mainTheme") or None,
            "themes": row.get("themes") or [],
            "pctChange": pct,
            "price": price,
            "preClose": pre_close,
            "high": high,
            "low": low,
            "open": _num(row.get("open")),
            "turnoverRate": _num(row.get("turnoverRate")),
            "volumeRatio": _num(row.get("volumeRatio")),
            "amount": _num(row.get("amount")),
            "mainNet": _num(row.get("zlje")),
            "mainNetRatio": _num(row.get("zljzb")),
            "limitUpPrice": limit_up,
            "rise": rise,
            "risePool": rise,
            # 并集判定（rise=池 ∪ 全市场）与池口径（risePool=统计用）分域，同 dieban 口径分域
            "sealedLimitUp": sealed,
            "touchedLimitUp": touched,
            "strong": bool(pct is not None and pct > STRONG_PCT and rise),
            "streak": None,
            "ret3d": _ret_since_base(code, price),
            "intradayDrawdownPct": _die._intraday_drawdown_pct(row),
            "amplitudePct": (round((high - low) / pre_close * 100, 2)
                             if None not in (high, low, pre_close) and pre_close > 0 and high >= low else None),
            "sources": ["pool"],
            "raw": _die._compact_row(row),
        }

    # ── 全市场逐股明细（本地日线重算；该源即「当日上涨名单」权威判定）──────────
    for item in full_rows:
        code = _code6(item.get("code"))
        if not code:
            continue
        pct = _num(item.get("pctChange"))
        price = _num(item.get("price"))
        stock = stocks.get(code)
        if stock is None:
            high, low, pre_close = _num(item.get("high")), _num(item.get("low")), _num(item.get("prevClose"))
            stocks[code] = {
                "code": code,
                "name": item.get("name"),
                "board": None,
                "themes": [],
                "pctChange": pct,
                "price": price,
                "preClose": pre_close,
                "high": high,
                "low": low,
                "open": _num(item.get("open")),
                "turnoverRate": None,
                "volumeRatio": None,
                "amount": _num(item.get("amount")),
                "mainNet": None,
                "mainNetRatio": None,
                "limitUpPrice": _num(item.get("limitUpPrice")),
                "rise": True,                 # 全市场逐股源即「当日上涨名单」（并集判定）
                "risePool": None,             # 非采集池行：池口径不适用（不冒充）
                "sealedLimitUp": False,       # 扫描层已按收盘封板排除（价格精确闸）
                "touchedLimitUp": item.get("touchedLimitUp"),
                "strong": bool(pct is not None and pct > STRONG_PCT),
                "streak": None,
                "ret3d": None,                # 全市场源无价格史（不冒充）
                "intradayDrawdownPct": None,
                "amplitudePct": (round((high - low) / pre_close * 100, 2)
                                 if None not in (high, low, pre_close) and pre_close > 0 and high >= low else None),
                "sources": ["full_market"],
                "raw": item,
            }
        else:
            # 与采集池行合并：全市场源是权威上涨名单 → 采信其判定（同 dieban review major）
            if "full_market" not in stock["sources"]:
                stock["sources"] = stock["sources"] + ["full_market"]
            stock["rise"] = True
            stock["sealedLimitUp"] = False   # 扫描层价格精确闸已排除收盘封板（review nit）
            stock["strong"] = bool((stock["pctChange"] is not None and stock["pctChange"] > STRONG_PCT))
            if stock.get("touchedLimitUp") is None:
                stock["touchedLimitUp"] = item.get("touchedLimitUp")
            if item.get("name") and not stock.get("name"):
                stock["name"] = item["name"]

    # ── 连涨：全市场并集逐日回溯 ─────────────────────────────────────────────
    streak: dict[str, int] = {}
    for code in today_set:
        count = 1
        for hist in reversed(rise_hist):
            if code in hist:
                count += 1
            else:
                break
        streak[code] = count
    for code, s in stocks.items():
        s["streak"] = streak.get(code) if s.get("rise") else None

    # ── 全市场上涨家数分位（同源 = 本地日线；缺文档日剔除并披露）────────────────
    history_dates = prior[-HISTORY_DAYS:]
    hist_docs = {str(d["_id"]): d for d in
                 (db[rp.COLLECTION_ROWS].find({"_id": {"$in": list(history_dates)}},
                                              {"count": 1, "source": 1}) if history_dates else [])}
    history: list[int] = []
    missing_hist: list[str] = []
    for d in history_dates:
        doc = hist_docs.get(d)
        if doc is None or not isinstance(doc.get("count"), int) or isinstance(doc.get("count"), bool):
            missing_hist.append(d)
            continue
        history.append(doc["count"])
    full_count = (full_today or {}).get("count")
    full_source = str((full_today or {}).get("source") or "") or None
    full_rise = {
        "count": full_count,
        "source": full_source,
        "sourceLabel": rp.source_label(full_source) if full_source else None,
        "fullMarketScope": full_source in rp.FULL_MARKET_SOURCES if full_source else False,
        "rowsCount": len(full_rows) if full_today is not None else None,
        "rowsDocCount": (full_today or {}).get("count"),
        "rowsSource": full_source,
        "rowsSourceLabel": rp.source_label(full_source) if full_source else None,
        "rowsMissing": (None if full_today is not None else "no_rows_doc"),
        "history": history,
        "historyDays": len(history),
        "historyMissing": missing_hist,
        "percentile": percentile_fraction(history, full_count) if history else None,
    }

    # ── 汇总统计（pool.* 一律采集池口径）─────────────────────────────────────
    stock_list = sorted(stocks.values(), key=lambda s: (
        -(s["pctChange"] if s["pctChange"] is not None else -99.0)))
    pool_rise = [s for s in stock_list if s["risePool"]]
    pool_strong = [s for s in stock_list if "pool" in s["sources"] and s["strong"]]
    pool_touch = [s for s in stock_list if "pool" in s["sources"] and s["touchedLimitUp"]]
    streak_rows = [s for s in stock_list if (s["streak"] or 0) >= 2]
    max_streak_row = max(streak_rows, key=lambda s: s["streak"] or 0, default=None)
    biggest_gain = max((s for s in stock_list if s["pctChange"] is not None),
                       key=lambda s: s["pctChange"], default=None)
    # 主力净额（zlje）为正 = 净流入；只有采集池行带资金字段（全市场日线行无）→ 显式披露
    positive = [s for s in stock_list if s["rise"] or s["touchedLimitUp"]]
    net_rows = [s for s in positive if "pool" in s["sources"] and s["mainNet"] is not None]
    net_total = round(sum(s["mainNet"] for s in net_rows), 2) if net_rows else None
    net_top = max(net_rows, key=lambda s: s["mainNet"], default=None)
    board_dist: dict[str, int] = {}
    for s in positive:
        key = s["board"] or "未分板块"
        board_dist[key] = board_dist.get(key, 0) + 1
    top_boards = sorted(board_dist.items(), key=lambda kv: -kv[1])

    degraded: list[dict[str, Any]] = []
    if frame is None:
        degraded.append({"scope": "snapshot_frame", "reason": "no_half_hour_frame"})
    elif not rows:
        degraded.append({"scope": "snapshot_stock_rows", "reason": "no_rows_in_slot"})
    if full_today is None:
        degraded.append({"scope": "full_market_rise", "reason": "no_rows_doc"})
    if prior and slot_days < len(prior):
        degraded.append({"scope": "streak_lookback",
                         "reason": f"prior_slot_missing:{len(prior) - slot_days}"})
    if missing_hist:
        degraded.append({"scope": "rise_history",
                         "reason": f"history_doc_missing:{len(missing_hist)}"})
    if base_date is None:
        degraded.append({"scope": "ret3d", "reason": "insufficient_history"})

    no_data = (not rows) and full_today is None
    reason = None
    if no_data:
        reason = (f"{date} 无 {SNAPSHOT_TYPE} 快照行、无全市场上涨逐股文档"
                  f"（未回填 / 当日未到 15:05 截点 / 覆盖不足；fail-visible，不伪 0）")

    return {
        "ok": True,
        "date": date,
        "datasetId": dataset_id,
        "slotTime": slot,
        "intraday": intraday,
        "noData": no_data,
        "reason": reason,
        "fullRise": full_rise,
        "pool": {
            "rows": len(rows),
            "up": up,
            "down": down,
            "flat": flat,
            "ratio": round(up / max(down, 1), 2) if rows else None,
            "rise": len(pool_rise),
            "strong": len(pool_strong),
            "touch": len(pool_touch),
            "streak2": len(streak_rows),
            "maxStreak": (max_streak_row or {}).get("streak"),
            "maxStreakCode": (max_streak_row or {}).get("code"),
            "maxStreakName": (max_streak_row or {}).get("name"),
        },
        "positive": {
            "count": len(positive),
            "netInflowTotal": net_total,           # 元；仅采集池行有资金字段
            "netInflowTop": ({"code": net_top["code"], "name": net_top["name"],
                              "mainNet": net_top["mainNet"]} if net_top else None),
            "topBoards": [{"board": b, "count": c} for b, c in top_boards[:8]],
        },
        "stats": {
            "biggestGain": ({"code": biggest_gain["code"], "name": biggest_gain["name"],
                             "pctChange": biggest_gain["pctChange"],
                             "board": biggest_gain["board"],
                             "sources": list(biggest_gain["sources"])}
                            if biggest_gain else None),
            "strongPct": STRONG_PCT,
            "riseMinPct": rp.RISE_MIN_PCT,
            "streakLookback": STREAK_LOOKBACK,
            "streakHistDays": len(rise_hist),
            # 字段名与 dieban 的 fullMarket（集合非空日数）刻意区分：rise 的逐日文档
            # 「0 只空名单」也是有效回溯资料，按「有文档日数」计（2026-10-31 review nit）
            "streakDays": {"riseDocs": hist_days, "pool": None,
                           "slotDays": slot_days, "priorDays": len(prior)},
            "retWindow": RET_WINDOW if base_date else None,
        },
        "degraded": degraded,
        "stocks": stock_list,
    }
