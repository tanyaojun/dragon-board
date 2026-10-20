# -*- coding: utf-8 -*-
"""全市场跌停家数·本地日线重算源（TDX vipdoc/lday，离线；2026-10-17 F7 增补）。

背景（诊断 §9）：东财跌停池只有**近 30 自然日窗口**（`market_dieban_pool._em_window_start`），
09-16 之前 84 个交易日的全市场口径无法外呼回补 → 叙事回退 250 只采集池口径，系统性低估
（10-15 审计实证：池内 6 家 vs 全市场 26 家）。本模块用**本地通达信日线**
（`vipdoc/<market>/lday/*.day`，32 字节定长记录）离线重算全市场跌停家数，供
`backfill_limit_down_tdx.py` 一次性写入参考集合 `market_daily_limit_down`（source=tdx_local_bars）。

判定（两道闸，缺一不可）：
1. 涨跌幅闸：`pct = close/前一根 close - 1` 达跌停线（`core.limit_rules.is_limit_down_pct`，
   容差 0.2）——与快照口径同一权威规则（无 ST 特判，与前端 StockUtils 同规）；
2. **价格精确闸**：`close == limit_down_price(code, 前收)`——剔除「近似跌幅但未封跌停」的
   1 分边界假阳性（603893 收 171.01，跌停价 171.00）与大部分除权日假跌停。

精度（17 个东财对照日实测，2026-10-17）：仅第 1 道闸偏差 +4.41（极值 +1..+10）；加第 2 道闸
后 **+1.65**（极值 +0..+4）。残余偏高来源：①除权日价格巧合（原始日线未复权，除权后前收偏差）；
②北交所目录缺口（`stock_names` 缺 920xxx 新段，如 920162）；③东财池剔除风险警示/退市股
（项目规则不剔除）。相对池内口径（−20 家量级）好一个数量级。

fail-visible（AGENTS §4.0）：目录/文件缺失、空文件、记录损坏一律**跳过并计数**，绝不伪 0；
某日无任何可用棒 → 该日不进结果（调用方按缺口披露，不写 0 行）。

**逐股明细（2026-10-20 立项）**：`scan_rows()` 与家数同一次扫描产出逐股行
（代码/名称/收盘/前收/涨跌幅/精确跌停价），供 `market_daily_limit_down_stocks`
（source=tdx_local_bars）落库；`scan_counts()` 由 `scan_rows()` 派生家数，
**同一实现不漂移**（家数 == 行数）。
"""
from __future__ import annotations

import glob
import os
import re
import struct
from typing import Any, Iterable

from backend.core.limit_rules import is_limit_down_pct, limit_down_price

_RECORD = struct.Struct("<IIIIIfII")   # date, open, high, low, close(×100), amount, vol, reserved
_RECORD_SIZE = 32
DEFAULT_TAKE = 400                     # 约 1.6 年日线：确保回填区间（含分位窗口）不落在读取窗边缘
ENV_ROOT = "QUANT_BOARD_TDX_DIR"
DEFAULT_ROOTS = ("D:/APP_SOFT/TDX", "D:/TDX_PLUS", "C:/new_tdx", "D:/new_tdx")
PROBE = ("sh", "sh600000")             # 探针文件：判目录可用性与新鲜度
COVERAGE_MIN_RATIO = 0.9               # 覆盖闸：当日有棒股数 < 峰值×0.9 → 读出数（防窗边缘静默少算）
_A_SHARE = re.compile(r"^(60|68|00|30|43|83|87|92)\d{4}$")


def candidate_roots() -> list[str]:
    """候选目录：环境变量优先（显式指定不被默认值覆盖），其余按默认序去重。"""
    env = (os.environ.get(ENV_ROOT) or "").strip()
    roots = [env] if env else []
    return roots + [r for r in DEFAULT_ROOTS if r not in roots]


def read_lday(path: str, take: int = DEFAULT_TAKE) -> list[tuple]:
    """文件尾部 take 根日线（升序）。缺文件/空文件 → []；短文件按实际根数返回。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    total = size // _RECORD_SIZE
    if total <= 0:
        return []
    take = max(1, min(take, total))
    try:
        with open(path, "rb", 0) as fh:
            fh.seek((total - take) * _RECORD_SIZE)
            buf = fh.read(take * _RECORD_SIZE)
    except OSError:
        return []
    return [_RECORD.unpack_from(buf, i * _RECORD_SIZE) for i in range(len(buf) // _RECORD_SIZE)]


def last_bar_date(root: str) -> str | None:
    """探针文件末棒 ISO 日期（判目录新旧/可用）；无探针 → None。"""
    for market, code in (PROBE,):
        recs = read_lday(os.path.join(root, "vipdoc", market, "lday", f"{code}.day"), 1)
        if recs:
            raw = str(recs[-1][0])
            return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return None


def resolve_root(roots: Iterable[str] | None = None) -> tuple[str | None, str | None]:
    """选**末棒最新**的可用本地通达信目录 → (root, last_bar)。都不可用 → (None, None)。"""
    best: tuple[str | None, str | None] = (None, None)
    for root in (list(roots) if roots is not None else candidate_roots()):
        if not root or not os.path.isdir(root):
            continue
        bar = last_bar_date(root)
        if bar and (best[1] is None or bar > best[1]):
            best = (root, bar)
    return best


def looks_like_a_share(code: str) -> bool:
    """无宇宙表时的兜底过滤（排除指数/基金/债/B股）：主板·创业板·科创板·北交所代码段。"""
    return bool(_A_SHARE.match(code))


def universe_from_db(db: Any) -> set[str]:
    """A 股宇宙 = `stock_names` type=stock（SH/SZ/BJ 全段；目录缺口由扫描计数披露）。"""
    return {str(d.get("code") or "").zfill(6)
            for d in db["stock_names"].find({"type": "stock"}, {"code": 1})}


def _iso(raw: int) -> str:
    s = str(raw)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def _scan_file(recs: list[tuple], code: str, dates: set[str]) -> tuple[dict[str, dict], set[str]]:
    """单只股票在 dates 内的 (跌停日 → 逐股行, 有棒日期集)。

    有棒日期集用于**覆盖闸**：日线文件尾部按 take 截断，窗口边缘只少数文件有棒，
    直接计数会把「只读到部分股票」当成真实家数（静默少算）。
    逐股行 = 家数的同一份事实（家数由 `len(rows)` 派生），不另写一套判定。
    """
    out: dict[str, dict] = {}
    seen: set[str] = set()
    for i in range(1, len(recs)):
        raw_date = recs[i][0]
        if not raw_date:
            continue
        date = _iso(raw_date)
        if date not in dates:
            continue
        seen.add(date)
        prev_close = recs[i - 1][4] / 100.0
        close = recs[i][4] / 100.0
        if prev_close <= 0 or close <= 0:
            continue          # 停牌/坏数据：不伪跌停
        pct = (close / prev_close - 1) * 100
        if not is_limit_down_pct(pct, code):
            continue
        exact = limit_down_price(code, prev_close)
        if abs(close - exact) > 0.005:
            continue          # 价格精确闸：近似跌幅不算封跌停
        out[date] = {"code": code, "name": None, "pctChange": round(pct, 2),
                     "price": round(close, 2), "prevClose": round(prev_close, 2),
                     "limitDownPrice": round(float(exact) + 1e-9, 2)}
    return out, seen


def scan_rows(dates: Iterable[str], *, root: str | None = None,
              universe: set[str] | None = None, take: int = DEFAULT_TAKE,
              names: dict[str, str] | None = None) -> tuple[dict[str, list[dict]], dict[str, Any]]:
    """一次性扫全市场日线重算各日跌停**逐股名单** → (rows_by_date, meta)。

    判定/覆盖闸/缺口语义与家数完全一致（同一实现）：`rows_by_date[d]` 为空列表表示
    「覆盖足但当日无股跌停」（真读数 0），日期缺失表示缺口（不在 dict 里）。
    `names` 给定时补 code → 名称（`stock_names`），缺失保持 None（不伪名称）。
    """
    wanted = {str(d) for d in dates}
    meta: dict[str, Any] = {"root": root, "last_bar": None, "files": 0, "skipped": 0,
                            "universe_hits": 0, "missing": 0, "coverage_max": 0, "partial": [],
                            "dates_without_bar": [], "zero_days": 0, "take": take}
    rows_by_date: dict[str, list[dict]] = {}
    if not wanted:
        return rows_by_date, meta
    if root is None:
        root, last_bar = resolve_root()
        meta["last_bar"] = last_bar
    if not root:
        meta["dates_without_bar"] = sorted(wanted)
        return rows_by_date, meta
    paths: list[tuple[str, str]] = []
    for market in ("sh", "sz", "bj"):
        for path in sorted(glob.glob(os.path.join(root, "vipdoc", market, "lday", "*.day"))):
            paths.append((os.path.basename(path)[2:8], path))
    seen: dict[str, int] = {}
    seen_codes: set[str] = set()
    for code, path in paths:
        if universe is not None:
            if code not in universe:
                meta["skipped"] += 1
                continue
        elif not looks_like_a_share(code):
            meta["skipped"] += 1
            continue
        seen_codes.add(code)
        meta["files"] += 1
        hits, days = _scan_file(read_lday(path, take), code, wanted)
        for date in days:
            seen[date] = seen.get(date, 0) + 1
        for date, row in hits.items():
            if names and not row.get("name"):
                row["name"] = names.get(code)
            rows_by_date.setdefault(date, []).append(row)
    if universe is not None:
        # universe_hits = 去重后的宇宙命中代码数（`files` 是文件数：同一代码在 sh/sz 目录
        # 各有一份时会多计 → 与 missing 直接相减会得出矛盾数，2026-10-20 review minor）
        meta["universe_hits"] = len(seen_codes)
        meta["missing"] = len(universe - seen_codes)
    meta["coverage_max"] = max(seen.values()) if seen else 0
    floor = meta["coverage_max"] * COVERAGE_MIN_RATIO
    meta["partial"] = sorted(d for d, c in seen.items() if c < floor)
    for date in seen:
        if date in meta["partial"]:
            rows_by_date.pop(date, None)     # 覆盖不足：不冒充真实名单/家数（fail-visible）
        else:
            rows_by_date.setdefault(date, [])  # 覆盖足 → 空列表是合法 0 家
    meta["zero_days"] = sum(1 for rows in rows_by_date.values() if not rows)
    meta["dates_without_bar"] = sorted(wanted - set(seen))
    return rows_by_date, meta


def names_from_db(db: Any) -> dict[str, str]:
    """code → 名称（`stock_names` type=stock）；同名缺失不补（保持 None 由页面 '--'）。"""
    out: dict[str, str] = {}
    for doc in db["stock_names"].find({"type": "stock"}, {"code": 1, "name": 1}):
        code = str(doc.get("code") or "").zfill(6)
        name = str(doc.get("name") or "").strip()
        if code and name:
            out[code] = name
    return out


def scan_counts(dates: Iterable[str], *, root: str | None = None,
                universe: set[str] | None = None,
                take: int = DEFAULT_TAKE) -> tuple[dict[str, int], dict[str, Any]]:
    """一次性扫全市场日线重算各日跌停家数 → (counts, meta)。

    家数**由逐股名单派生**（`len(rows)`），判定/覆盖闸/缺口/0 值语义全部继承 `scan_rows`，
    不保留第二份扫描实现（2026-10-20 逐股立项：家数与名单必须同源同数）。
    """
    rows_by_date, meta = scan_rows(dates, root=root, universe=universe, take=take)
    return {date: len(rows) for date, rows in rows_by_date.items()}, meta
