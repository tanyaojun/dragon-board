# -*- coding: utf-8 -*-
"""跌停复盘读口聚合（2026-10-20 用户需求：JEV 叙事工作台新增【跌停复盘】页）。

页面语义：**当日负反馈名单**（跌停 / 连跌 / 一字跌停 / 大跌 / 触板后深回撤），与
【涨停复盘】（limitup-labels）同一套展示语言（KPI 条 + 板块 chips + 筛选 + 可排序表 +
行展开）。不发起任何模型调用。

**读为主，但非纯读**（2026-10-20 review minor：旧 docstring 称「也不写库」与实现不符）：
`limit_down_count` 在「当日 + 已过收盘截点 + 参考集合 miss」时会懒加载一次东财跌停池并
upsert 家数/逐股文档（1 次/日，受 15:05 截点、30 日窗口、120s 进程内缓存与 429/403 冷却约束）。

## 口径（单一事实源，勿在页面另写一份）

1. **全市场逐股明细**：`market_dieban_pool.rows_for_date` 读 `market_daily_limit_down_stocks`
   （一天一文档，source 优先级 EM > 快照 > TDX，预登记
   docs/hotlist-jev/jev-dieban-fullmarket-preregistration.md）。缺文档 → `fullMarket.rowsMissing`
   结构化披露，页面 KPI 副行标注，**不把采集池名单冒充全市场**。
2. **采集池明细**：`snapshot_stock_rows` 当日 15:00 `half_hour` 快照行（250 只热榜采集池）。
   跌停判定走 `core.limit_rules.is_limit_down_pct`（板块阈值自算，含 0.2pp tick 容差，
   无 ST 特判）——与 `jev_label_jiuyan.dieban_count` / 规则情绪链同一条权威线。
3. **触板回撤池逐股**：同帧 `limitSummary.thsPools.pools.drawdown.items`（同花顺
   「大幅回撤池」；`max_drawdown` 负数字符串统一换成**正幅值**）。缺失/未采集 →
   `degraded` 显式披露，不伪 0。
4. **全市场跌停家数**：`market_dieban_pool.limit_down_count`（东财跌停池主源 →
   行情快照 → 本地日线重算 → 采集池末位降级，`source` 逐值透传）。
5. **连跌（统一定义）**：逐日回溯「该日跌停集合」= 该日全市场逐股 code 集（有则用）
   ∪ 该日采集池跌停 code 集——两者同一条权威阈值线，并集是更接近全市场的覆盖；回溯深度
   `STREAK_LOOKBACK` 个交易日（含当日），`stats.streakDays` 暴露回溯覆盖（逐股日数 / 采集池
   日数 / 15:00 槽可用日数 + 仍缺槽日）。回溯窗不足 → None。
6. **近3日累计跌幅**：当前价 / 3 个交易日前 15:00 价 − 1（仅采集池行有价格史）；基准缺失 → None。
7. **日内回撤**：采集池行 `(high − price) / high`（正幅值）；回撤池行用 `max_drawdown` 幅值。
   两者语义不同，页面分列标注。
8. **盘中**：15:00 帧未到（收盘前）→ 回落当日**最新** `half_hour` 槽，`intraday=True`。
9. **板块字段**（2026-11-06；2026-11-14 粗桶口径）：board = 韭研产业树一级节点经
   jiuyan_industry_root 对照层归一的**打标链粗桶名**（unmapped 节点保留一级原值，
   `services/jev/jiuyan_board`，
   单一事实源 `jiuyan_industry_stocks` 周频全成分快照）；韭研未收录 → board 置空
   （「未分板块」，用户裁决：不回推原板块名/主题材/EM industry/THS industry_block，
   避免单列双口径）；产业库空 → `degraded[jiuyan_board]` 披露。

**口径分域（2026-10-20 review major）**：`stocks[].limitDown` 是**并集判定**（采集池阈值线
∪ 全市场逐股名单），用于徽标/筛选；**采集池口径的统计**（`pool.dieban/deepDrop/deepDropOnly/
oneWord`）另由 `limitDownPool`/来源标记收口，不因全市场行并入而膨胀。

**未知不判否**（同轮 review）：全市场逐股行没有盘中高低价，其一字跌停 = `None`（不可判），
不得写 False（那会把「不可算」呈现成「确认不是一字」）。

fail-visible：只有「无采集池行 + 无回撤池逐股 + 无全市场逐股 + 全市场家数不可算」才报
`noData`；「0 家跌停」是**真读数**（照常返回空名单，不当作缺口）。家数与逐股跨源且逐股更多
→ `fullMarket.countDisputed` + `degraded`（不悄悄把它算进同源分位）。

进程内缓存：家数、逐股文档、逐日 15:00 采集池行各带 120s 缓存（页面 60s 轮询不得变成每分钟
外呼/读库风暴，skills/a-stock-data「东财防封」纪律）；缓存只影响读，不写库。
"""
from __future__ import annotations

import time
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID, percentile_fraction
from backend.core.limit_rules import is_limit_down_pct
from backend.operations.market_dieban_pool import (
    FULL_MARKET_SOURCES,
    limit_down_count,
    reference_counts,
    rows_for_date,
    source_label,
)
from backend.services.jev import jiuyan_board
from backend.services.jev.shape_types import shape_fields

SNAPSHOT_TYPE = "half_hour"
CLOSE_SLOT = "15:00"
DEEP_DROP_PCT = -7.0      # 大跌判定线（叙事口径；跌停线仍由 core.limit_rules 判）
STREAK_LOOKBACK = 10      # 连跌回溯交易日上限（含当日）
RET_WINDOW = 3            # 近 N 日累计跌幅基准
HISTORY_DAYS = 20         # 全市场跌停家数分位窗口（与 market_facts 同窗）

_ROW_FIELDS = ("code", "name", "pctChange", "price", "preClose", "high", "low", "open",
               "limitDownPrice", "turnoverRate", "volumeRatio", "amount", "zlje", "zljzb",
               "sectorLabel", "mainTheme", "themes", "leadStatus")
_ROW_PROJ = {k: 1 for k in _ROW_FIELDS}

# 缓存：键 (dataset, date[, slot])；限长防长驻进程跨日累积
_FULL_MARKET_TTL = 120.0
_MISS = object()
_full_market_cache: dict[tuple[str, str], tuple[float, Any]] = {}
_full_rows_cache: dict[tuple[str, str], tuple[float, dict[str, Any] | None]] = {}
_slot_rows_cache: dict[tuple[str, str, str], tuple[float, dict[str, dict[str, Any]]]] = {}


def _num(value: object) -> float | None:
    """数值化（bool/NaN 一律 None；字符串数字（THS 池全是字符串）能解析则用）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return number


def _code6(value: object) -> str:
    return str(value or "").strip()[-6:]


def _cache_get(cache: dict, key: tuple) -> Any:
    """命中（含缓存的 None/空结果）→ 缓存值；未命中或过期 → `_MISS` 哨兵。

    哨兵而非 None：缓存值本身可能就是 None（「该日无逐股文档」「家数不可算」），
    用 None 表示未命中会让缺文档日每次请求都重打 Mongo/上游（2026-10-20 review minor）。
    """
    hit = cache.get(key)
    if hit is None or time.monotonic() - hit[0] >= _FULL_MARKET_TTL:
        return _MISS
    return hit[1]


def _cache_put(cache: dict, key: tuple, value: Any) -> None:
    if len(cache) > 512:
        cache.clear()
    cache[key] = (time.monotonic(), value)


def reset_full_market_cache() -> None:
    """清全市场家数/逐股/槽位缓存（测试夹具用；进程内缓存跨用例会误导后续断言）。"""
    _full_market_cache.clear()
    _full_rows_cache.clear()
    _slot_rows_cache.clear()


def _full_market_count(db: Any, date: str, dataset_id: str) -> tuple[Any, str]:
    """全市场跌停家数 → (count, source)，带 120s 进程内缓存（含「不可算」负缓存）。

    `market_dieban_pool.limit_down_count` 的懒加载只在「当日 + 已过收盘截点」发生；页面每
    60s 轮询一次，不加缓存会在上游持续不可用时每分钟重试（东财 IP 级封禁前科）。
    """
    key = (dataset_id, date)
    hit = _cache_get(_full_market_cache, key)
    if hit is not _MISS:
        return hit
    value = limit_down_count(db, date, dataset_id)
    _cache_put(_full_market_cache, key, value)
    return value


def _full_market_rows(db: Any, date: str) -> dict[str, Any] | None:
    """全市场逐股文档（`rows_for_date`），带 120s 进程内缓存；无 → None（调用方披露）。

    逐股文档按日期为键（与家数参考集合同规，不随 dataset 分文档），故缓存键只含日期。
    """
    key = ("", date)
    hit = _cache_get(_full_rows_cache, key)
    if hit is not _MISS:
        return hit
    doc = rows_for_date(db, date)
    _cache_put(_full_rows_cache, key, doc)
    return doc


def _latest_slot(db: Any, date: str, dataset_id: str) -> dict[str, Any] | None:
    """当日最新 half_hour 帧（15:00 收盘帧优先；未到则盘中最新槽）。"""
    return db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": SNAPSHOT_TYPE, "tradingDate": date},
        {"slotTime": 1, "timestamp": 1, "limitSummary.drawdown": 1, "limitSummary.thsPools": 1},
        sort=[("slotTime", -1), ("timestamp", -1), ("snapshotId", -1)])


def _slot_rows(db: Any, date: str, slot: str, dataset_id: str) -> dict[str, dict[str, Any]]:
    """某日某槽的采集池行（code → 行；同码多快照取 snapshotId 最大的一条）。"""
    rows: dict[str, dict[str, Any]] = {}
    for row in db["snapshot_stock_rows"].find(
            {"datasetId": dataset_id, "type": SNAPSHOT_TYPE, "tradingDate": date, "slotTime": slot},
            _ROW_PROJ, sort=[("snapshotId", -1)]):
        code = _code6(row.get("code"))
        if code and code not in rows:
            rows[code] = row
    return rows


def _slot_rows_cached(db: Any, date: str, slot: str, dataset_id: str) -> dict[str, dict[str, Any]]:
    """`_slot_rows` + 120s 缓存：21 日回溯每天一次全量拉取会被 60s 轮询放大成读库风暴。"""
    key = (dataset_id, date, slot)
    hit = _cache_get(_slot_rows_cache, key)
    if hit is not _MISS:
        return hit
    rows = _slot_rows(db, date, slot, dataset_id)
    _cache_put(_slot_rows_cache, key, rows)
    return rows


def _prior_trading_dates(db: Any, date: str, n: int, dataset_id: str) -> list[str]:
    """严格早于 date 的最近 n 个 half_hour 快照交易日（升序）。"""
    rows = db["snapshot_frames"].find(
        {"datasetId": dataset_id, "type": SNAPSHOT_TYPE, "tradingDate": {"$lt": date}},
        {"tradingDate": 1})
    dates = sorted({str(r["tradingDate"]) for r in rows if r.get("tradingDate")})
    return dates[-n:]


def _dieban_set(rows: dict[str, dict[str, Any]]) -> set[str]:
    return {code for code, row in rows.items() if is_limit_down_pct(row.get("pctChange"), code)}


def _is_one_word_limit_down(row: dict[str, Any]) -> bool:
    """一字跌停：全天最高价 = 跌停价（开盘即封、全天未打开）——有高/低价才算，缺则 False。"""
    limit_down = _num(row.get("limitDownPrice"))
    high = _num(row.get("high"))
    price = _num(row.get("price"))
    if limit_down is None or limit_down <= 0 or high is None or price is None:
        return False
    # 1e-3 元容差：快照价按分取整，一字板 high/price/limitDownPrice 三者应同值
    return high <= limit_down + 1e-3 and price <= limit_down + 1e-3


def _intraday_drawdown_pct(row: dict[str, Any]) -> float | None:
    """日内回撤（正幅值）：自当日最高价回落到最新价的比例；无效最高价 → None。"""
    high = _num(row.get("high"))
    price = _num(row.get("price"))
    if high is None or price is None or high <= 0 or price > high:
        return None
    return round((high - price) / high * 100, 2)


def _drawdown_items(frame: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    """回撤池逐股明细（THS 大幅回撤池）。返回 (items, degradedReason)；未采集 → (None, 原因)。"""
    limit_summary = (frame or {}).get("limitSummary") or {}
    pools = ((limit_summary.get("thsPools") or {}).get("pools") or {})
    pool = pools.get("drawdown")
    if not isinstance(pool, dict):
        return None, "drawdown_pool_missing"
    if pool.get("ok") is False:
        return None, "drawdown_pool_upstream_failed"
    items = pool.get("items")
    if not isinstance(items, list):
        return None, "drawdown_pool_missing"
    return items, None


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    """采集池行 → 读口行（保留可核字段，页面行展开用；不含 _id/datasetId 等簿记字段）。"""
    return {k: row.get(k) for k in ("pctChange", "price", "preClose", "high", "low", "open",
                                    "limitDownPrice", "turnoverRate", "volumeRatio",
                                    "amount", "zlje", "zljzb", "leadStatus")}


def _compact_ths_item(item: dict[str, Any]) -> dict[str, Any]:
    return {k: item.get(k) for k in ("stock_code", "stock_name", "change", "price",
                                     "max_drawdown", "amplitude", "industry_block",
                                     "main_net_amount", "effective_turnover_ratio",
                                     "volume", "time_preview")}


def _count_disputed(rows_doc: dict[str, Any] | None, full_source: str,
                    full_count: Any) -> bool:
    """家数存疑：逐股名单来自**别的**全市场源且多于当日家数。

    典型形态是 EM 窗口边界/限流返空池被写成 0 家（09-16：家数 EM=0 vs 同日 TDX 逐股 4 行）。
    2026-10-20 review major：不可悄悄把这种 0 算进同源分位窗，须结构化披露。
    """
    if not rows_doc:
        return False
    src = str(rows_doc.get("source") or "")
    rows_count = rows_doc.get("count")
    if not src or src == full_source or not isinstance(rows_count, int) or isinstance(rows_count, bool):
        return False
    return rows_count > (full_count or 0)


def collect_dieban_review(db: Any, date: str,
                          dataset_id: str = DEFAULT_DATASET_ID) -> dict[str, Any]:
    """单日负反馈名单聚合（跌停 / 连跌 / 一字跌停 / 大跌 / 触板回撤）。"""
    frame = _latest_slot(db, date, dataset_id)
    slot = str((frame or {}).get("slotTime") or CLOSE_SLOT)
    intraday = slot != CLOSE_SLOT
    rows = _slot_rows_cached(db, date, slot, dataset_id) if frame else {}

    # ── 家数优先读：懒加载可能刚写下逐股文档，先读逐股会拿到过期缓存并误报 rowsMissing ──
    full_count, full_source = _full_market_count(db, date, dataset_id)

    # ── 连跌回溯 + 近 N 日基准（历史一律取 15:00 收盘槽，不与盘中槽混比较）──
    # 回溯窗取两用最大值：连跌看 STREAK_LOOKBACK 日，全市场跌停分位看 HISTORY_DAYS 日
    prior = _prior_trading_dates(db, date, max(STREAK_LOOKBACK, HISTORY_DAYS + 1), dataset_id)
    die_sets: list[set[str]] = []
    price_by_date: dict[str, dict[str, float | None]] = {}
    streak_full_days = streak_pool_days = slot_days = 0
    prior_rows_docs: dict[str, dict[str, Any] | None] = {}
    for d in prior:
        hist_rows = _slot_rows_cached(db, d, CLOSE_SLOT, dataset_id)
        if hist_rows:
            slot_days += 1
        pool_set = _dieban_set(hist_rows)
        full_doc = _full_market_rows(db, d)
        prior_rows_docs[d] = full_doc
        full_set = {_code6(r.get("code")) for r in (full_doc or {}).get("rows") or []
                    if r.get("code")}
        if full_set:
            streak_full_days += 1
        if pool_set:
            streak_pool_days += 1
        die_sets.append(full_set | pool_set)
        price_by_date[d] = {c: _num(r.get("price")) for c, r in hist_rows.items()}
    # 连跌只看最近 STREAK_LOOKBACK 个交易日的并集（回溯窗更长是为分位分位历史）
    die_hist = die_sets[-STREAK_LOOKBACK + 1:]
    base_date = prior[-RET_WINDOW] if len(prior) >= RET_WINDOW else None

    die_pool = _dieban_set(rows)
    full_today = _full_market_rows(db, date)
    die_today = die_pool | {_code6(r.get("code"))
                            for r in (full_today or {}).get("rows") or [] if r.get("code")}
    streak: dict[str, int] = {}
    for code in die_today:
        count = 1
        for hist in reversed(die_hist):
            if code in hist:
                count += 1
            else:
                break
        streak[code] = count

    def _ret_since_base(code: str, price: float | None) -> float | None:
        if base_date is None or price is None or price <= 0:
            return None
        base = price_by_date.get(base_date, {}).get(code)
        if base is None or base <= 0:
            return None
        return round((price / base - 1) * 100, 2)

    # ── 采集池口径：跌停 / 大跌 / 下跌结构 ───────────────────────────────────
    stocks: dict[str, dict[str, Any]] = {}
    up = down = flat = 0
    for code, row in rows.items():
        pct = _num(row.get("pctChange"))
        if pct is not None:
            if pct > 0.1:
                up += 1
            elif pct < -0.1:
                down += 1
            else:
                flat += 1
        limit_down = code in die_pool
        price = _num(row.get("price"))
        stocks[code] = {
            "code": code,
            "name": row.get("name"),
            "board": row.get("sectorLabel") or row.get("mainTheme") or None,
            "themes": row.get("themes") or [],
            "pctChange": pct,
            "price": price,
            "preClose": _num(row.get("preClose")),
            "high": _num(row.get("high")),
            "low": _num(row.get("low")),
            "open": _num(row.get("open")),
            "turnoverRate": _num(row.get("turnoverRate")),
            "volumeRatio": _num(row.get("volumeRatio")),
            "amount": _num(row.get("amount")),
            "mainNet": _num(row.get("zlje")),
            "mainNetRatio": _num(row.get("zljzb")),
            "limitDownPrice": _num(row.get("limitDownPrice")),
            # 并集判定（徽标/筛选用）与采集池口径（统计用）分域，见模块 docstring
            "limitDown": limit_down,
            "limitDownPool": limit_down,
            "oneWordLimitDown": limit_down and _is_one_word_limit_down(row),
            "deepDrop": bool(limit_down or (pct is not None and pct <= DEEP_DROP_PCT)),
            "streak": streak.get(code) if limit_down else None,
            "ret3d": _ret_since_base(code, price),
            "intradayDrawdownPct": _intraday_drawdown_pct(row),
            "maxDrawdownPct": None,          # THS 回撤池口径（下方合并）
            "emStreakDays": None,            # EM 自报连跌天数（原始字段，非本页口径）
            "openNum": None,
            "lastSealTime": None,
            "sources": ["pool"],
            "raw": _compact_row(row),
            "ths": None,
        }

    # ── 全市场逐股明细（EM/快照/本地日线，源优先级见 market_dieban_pool）──────
    full_rows = (full_today or {}).get("rows") or []
    for item in full_rows:
        code = _code6(item.get("code"))
        if not code:
            continue
        pct = _num(item.get("pctChange"))
        price = _num(item.get("price"))
        stock = stocks.get(code)
        if stock is None:
            stocks[code] = {
                "code": code,
                "name": item.get("name"),
                "board": item.get("industry") or None,
                "themes": [],
                "pctChange": pct,
                "price": price,
                "preClose": _num(item.get("prevClose")),
                "high": None,
                "low": None,
                "open": None,
                "turnoverRate": _num(item.get("turnoverRate")),
                "volumeRatio": None,
                "amount": _num(item.get("amount")),
                "mainNet": None,
                "mainNetRatio": None,
                "limitDownPrice": _num(item.get("limitDownPrice")),
                "limitDown": True,            # 全市场逐股源即「当日跌停名单」（并集判定）
                "limitDownPool": None,        # 非采集池行：池口径不适用（不冒充）
                # 无盘中高低价 → 不可判，留 None（不得写 False 把未知呈现成「确认不是一字」）
                "oneWordLimitDown": None,
                "deepDrop": bool(pct is not None and pct <= DEEP_DROP_PCT),
                "streak": streak.get(code),
                "ret3d": None,                # 全市场源无价格史（不冒充）
                "intradayDrawdownPct": None,
                "maxDrawdownPct": None,
                "emStreakDays": _num(item.get("emStreakDays")),
                "openNum": _num(item.get("openNum")),
                "lastSealTime": item.get("lastSealTime"),
                "sources": ["full_market"],
                "raw": item.get("raw"),
                "ths": None,
            }
        else:
            # 与采集池行合并：全市场源是权威跌停名单 → 采信其判定（否则同一行在不同来源
            # 组合下 limitDown 不一致：2026-10-20 review major）；池口径标记保留供统计
            if "full_market" not in stock["sources"]:
                stock["sources"] = stock["sources"] + ["full_market"]
            stock["limitDown"] = True
            stock["streak"] = streak.get(code)
            stock["deepDrop"] = True
            stock["emStreakDays"] = _num(item.get("emStreakDays"))
            stock["openNum"] = _num(item.get("openNum"))
            stock["lastSealTime"] = item.get("lastSealTime")
            if item.get("name") and not stock.get("name"):
                stock["name"] = item["name"]
            if item.get("industry") and not stock.get("board"):
                stock["board"] = item["industry"]

    # ── 触板回撤池逐股（与采集池行按 code 合并；池外股单独入列）────────────────
    items, drawdown_degraded = _drawdown_items(frame if frame else {})
    merged_dd = 0
    for item in items or []:
        if not isinstance(item, dict):
            continue
        code = _code6(item.get("stock_code"))
        if not code:
            continue
        raw_dd = _num(item.get("max_drawdown"))
        drawdown_pct = round(-raw_dd, 2) if raw_dd is not None else None
        merged_dd += 1
        stock = stocks.get(code)
        if stock is None:
            stock = {
                "code": code,
                "name": item.get("stock_name"),
                "board": item.get("industry_block") or None,
                "themes": [],
                "pctChange": _num(item.get("change")),
                "price": _num(item.get("price")),
                "preClose": None,
                "high": None,
                "low": None,
                "open": None,
                "turnoverRate": _num(item.get("effective_turnover_ratio")),
                "volumeRatio": None,
                "amount": None,
                "mainNet": _num(item.get("main_net_amount")),
                "mainNetRatio": None,
                "limitDownPrice": None,
                "limitDown": False,
                "limitDownPool": None,
                "oneWordLimitDown": None,     # 无高低价，不可判（不写 False）
                "deepDrop": bool((_num(item.get("change")) or 0) <= DEEP_DROP_PCT),
                "streak": None,
                "ret3d": None,
                "intradayDrawdownPct": None,
                "maxDrawdownPct": drawdown_pct,
                "emStreakDays": None,
                "openNum": None,
                "lastSealTime": None,
                "sources": ["ths_drawdown"],
                "raw": None,
                "ths": _compact_ths_item(item),
            }
            stocks[code] = stock
        else:
            stock["maxDrawdownPct"] = drawdown_pct
            if "ths_drawdown" not in stock["sources"]:
                stock["sources"] = stock["sources"] + ["ths_drawdown"]
            stock["ths"] = _compact_ths_item(item)

    # ── 日线形态分型（2026-10-31 用户裁决：游资复盘口径，shape_types 单一实现）──
    # 封板股（收盘跌停名单/封涨停）shape=None，由既有跌停/一字徽标表达；触板事实按日线 high 自算
    for s in stocks.values():
        s.update(shape_fields(s["code"], s["pctChange"], s["price"], s["preClose"],
                              s["high"], s["low"], sealed_down=bool(s.get("limitDown"))))

    # ── 板块字段 = 韭研产业名（2026-11-06 用户裁决，与上涨复盘同规同源）─────
    # 单一事实源 = jiuyan_industry_stocks（产业树 stock-tree 周频全成分快照）；
    # 韭研未收录 → board 置空（「未分板块」，不回推主题材/EM industry/THS
    # industry_block，避免单列双口径）；产业库空 → degraded 结构化披露。
    jy_index, jy_meta = jiuyan_board.board_index(db)
    jiuyan_board.apply_boards(list(stocks.values()), jy_index)
    jy_empty = bool(stocks) and not jy_meta["codes"]

    # ── 全市场跌停家数（同源分位；跨源存疑日剔除出分位窗并披露）────────────────
    history_all = (reference_counts(db, prior[-HISTORY_DAYS:], full_source)
                   if full_source in FULL_MARKET_SOURCES and prior else {})
    disputed_days = {d for d, doc in prior_rows_docs.items()
                     if _count_disputed(doc, full_source, history_all.get(d))}
    window = [d for d in prior[-HISTORY_DAYS:] if d in history_all]
    history = [history_all[d] for d in window if d not in disputed_days]
    percentile = percentile_fraction(history, full_count)
    rows_doc = full_today
    count_disputed = _count_disputed(rows_doc, full_source, full_count)
    full_market = {
        "count": full_count,
        "source": full_source,
        "sourceLabel": source_label(full_source),
        "fullMarketScope": full_source in FULL_MARKET_SOURCES,
        "history": history,
        "historyDays": len(history),
        "historyExcluded": sorted(d for d in window if d in disputed_days),
        "percentile": percentile,
        # 逐股「行数」= 实际可用行数；家数（count）另列，截断/坏行日两者不等且各自标注
        "rowsCount": (len((rows_doc or {}).get("rows") or []) if rows_doc is not None else None),
        "rowsDocCount": (rows_doc or {}).get("count"),
        "rowsSource": ((rows_doc or {}).get("source") or None),
        "rowsSourceLabel": (source_label((rows_doc or {}).get("source"))
                            if rows_doc else None),
        "rowsTruncated": bool((rows_doc or {}).get("truncated")),
        "rowsBad": (rows_doc or {}).get("badRows") or 0,
        "rowsMissing": (None if rows_doc is not None else "no_rows_doc"),
        # 跨源日（EM 窗口滑出：家数权威源 ≠ 逐股源）→ 结构化披露，两读数各自自洽不互改
        "crossSource": bool(rows_doc and (rows_doc.get("source") or "") != full_source
                            and (rows_doc.get("count") or 0) != (full_count or 0)),
        # 家数存疑（跨源且逐股更多，典型为 EM 空池伪 0）→ 已剔出分位窗，页面标「家数存疑」
        "countDisputed": count_disputed,
    }

    # ── 汇总统计（pool.* 一律采集池口径）─────────────────────────────────────
    stock_list = sorted(stocks.values(), key=lambda s: (
        s["pctChange"] if s["pctChange"] is not None else 0.0))
    pool_dieban = [s for s in stock_list if s["limitDownPool"]]
    pool_deep_drop = [s for s in stock_list
                      if "pool" in s["sources"] and s["deepDrop"]]
    pool_deep_drop_only = [s for s in pool_deep_drop if not s["limitDownPool"]]
    streak_rows = [s for s in stock_list if (s["streak"] or 0) >= 2]
    max_streak_row = max(streak_rows, key=lambda s: s["streak"] or 0, default=None)
    biggest_drop = min((s for s in stock_list if s["pctChange"] is not None),
                       key=lambda s: s["pctChange"], default=None)
    # 主力净额（zlje）为负 = 净流出；只统计负反馈视野内的股（跌停 ∪ 大跌 ∪ 回撤）
    negative = [s for s in stock_list
                if s["limitDown"] or s["deepDrop"] or s["maxDrawdownPct"] is not None]
    net_rows = [s for s in negative if s["mainNet"] is not None]
    net_total = round(sum(s["mainNet"] for s in net_rows), 2) if net_rows else None
    net_worst = min(net_rows, key=lambda s: s["mainNet"], default=None)
    board_dist: dict[str, int] = {}
    for s in negative:
        key = s["board"] or "未分板块"
        board_dist[key] = board_dist.get(key, 0) + 1
    top_boards = sorted(board_dist.items(), key=lambda kv: -kv[1])

    limit_summary = (frame or {}).get("limitSummary") or {}
    dd_block = limit_summary.get("drawdown") or {}
    dd_counts = [s["maxDrawdownPct"] for s in stock_list if s["maxDrawdownPct"] is not None]
    drawdown = {
        "count": (dd_block.get("count") if isinstance(dd_block.get("count"), int)
                  else (len(items) if items is not None else None)),
        "avgDrawdownPct": (dd_block.get("avgDrawdownPct")
                           if _num(dd_block.get("avgDrawdownPct")) is not None
                           else (round(sum(dd_counts) / len(dd_counts), 2) if dd_counts else None)),
        "deepestDrawdownPct": (dd_block.get("deepestDrawdownPct")
                               if _num(dd_block.get("deepestDrawdownPct")) is not None
                               else (max(dd_counts) if dd_counts else None)),
        "itemCount": merged_dd if items is not None else None,
        "degraded": drawdown_degraded,
    }

    degraded: list[dict[str, Any]] = []
    if jy_empty:
        degraded.append({"scope": "jiuyan_board",
                         "reason": jy_meta.get("reason") or "industry_stocks_empty"})
    if drawdown_degraded:
        degraded.append({"scope": "ths_drawdown_pool", "reason": drawdown_degraded})
    if frame is None:
        degraded.append({"scope": "snapshot_frame", "reason": "no_half_hour_frame"})
    elif not rows:
        degraded.append({"scope": "snapshot_stock_rows", "reason": "no_rows_in_slot"})
    if full_source not in FULL_MARKET_SOURCES:
        degraded.append({"scope": "full_market_limit_down",
                         "reason": f"degraded_to_pool_scope:{full_source}"})
    if rows_doc is None:
        degraded.append({"scope": "full_market_rows", "reason": "no_rows_doc"})
    elif count_disputed:
        degraded.append({"scope": "full_market_count_disputed",
                         "reason": f"rows={(rows_doc.get('source') or '')}"
                                   f"({rows_doc.get('count')}) > count={full_source}({full_count})"})
    elif full_market["crossSource"]:
        degraded.append({"scope": "full_market_rows_cross_source",
                         "reason": f"rows={(rows_doc.get('source') or '')}({rows_doc.get('count')}) "
                                   f"count={full_source}({full_count})"})
    if prior and slot_days < len(prior):
        # 回溯窗内缺 15:00 采集池行的日会被静默截断连跌 → 显式披露（不是伪 0）
        degraded.append({"scope": "streak_lookback",
                         "reason": f"prior_slot_missing:{len(prior) - slot_days}"})
    if base_date is None:
        degraded.append({"scope": "ret3d", "reason": "insufficient_history"})

    no_data = (not rows) and (items is None) and (full_count is None) and not full_rows
    reason = None
    if no_data:
        reason = (f"{date} 无 {SNAPSHOT_TYPE} 快照行、无全市场逐股、无可用回撤池逐股、"
                  f"全市场跌停家数亦不可算（fail-visible，不伪 0）")

    return {
        "ok": True,
        "date": date,
        "datasetId": dataset_id,
        "slotTime": slot,
        "intraday": intraday,
        "noData": no_data,
        "reason": reason,
        "fullMarket": full_market,
        # 韭研板块归属口径披露：batchDate=成分快照批次、codes=可归属个股数（页面提示用）
        "jiuyanBoard": jy_meta,
        "pool": {
            "rows": len(rows),
            "up": up,
            "down": down,
            "flat": flat,
            "ratio": round(up / max(down, 1), 2) if rows else None,
            "dieban": len(pool_dieban),
            "deepDrop": len(pool_deep_drop),
            "deepDropOnly": len(pool_deep_drop_only),
            "oneWord": sum(1 for s in pool_dieban if s["oneWordLimitDown"]),
            "streak2": len(streak_rows),
            "maxStreak": (max_streak_row or {}).get("streak"),
            "maxStreakCode": (max_streak_row or {}).get("code"),
            "maxStreakName": (max_streak_row or {}).get("name"),
        },
        "drawdown": drawdown,
        "negative": {
            "count": len(negative),
            "netOutflowTotal": net_total,          # 元；负=净流出
            "netOutflowWorst": ({"code": net_worst["code"], "name": net_worst["name"],
                                 "mainNet": net_worst["mainNet"]} if net_worst else None),
            "topBoards": [{"board": b, "count": c} for b, c in top_boards[:8]],
        },
        "stats": {
            "biggestDrop": ({"code": biggest_drop["code"], "name": biggest_drop["name"],
                             "pctChange": biggest_drop["pctChange"],
                             "board": biggest_drop["board"],
                             # 供页面判断副行文案（池内 vs 全市场逐股名单），不臆称池内最深
                             "sources": list(biggest_drop["sources"])}
                            if biggest_drop else None),
            "deepDropPct": DEEP_DROP_PCT,
            # 含当日最多可回溯 STREAK_LOOKBACK 个交易日（die_hist 已切到 LOOKBACK-1 个前置日）
            "streakLookback": STREAK_LOOKBACK,
            "streakHistDays": len(die_hist),
            "streakDays": {"fullMarket": streak_full_days, "pool": streak_pool_days,
                           "slotDays": slot_days, "priorDays": len(prior)},
            "retWindow": RET_WINDOW if base_date else None,
        },
        "degraded": degraded,
        "stocks": stock_list,
    }