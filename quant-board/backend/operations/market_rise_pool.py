# -*- coding: utf-8 -*-
"""全市场「上涨复盘」逐股源：涨幅 > 5% 且未封涨停（本地日线口径，2026-10-31）。

背景：JEV 叙事工作台新增【上涨复盘】页（与【下跌复盘】同展示语言），需要每个交易日
**全市场**涨幅超过 5 个点但未上涨停的逐股名单。该名单没有现成的上游池（东财只有
涨停/炸板/跌停池），唯一可覆盖任意交易日的全市场源是**本地通达信日线**
（`market_dieban_tdx` 同一条读棒链：vipdoc/lday 32 字节定长记录 + 覆盖闸）。

口径（单一事实源，页面/服务不另写判定）：
1. **涨幅闸**：`pct = close/前收 - 1 > 5.0`（严格大于，RISE_MIN_PCT）；
2. **未涨停闸（价格精确）**：`close != limit_up_price(code, 前收)`（0.005 元容差）——
   与 market_dieban_tdx 跌停判定同构的两道闸写法：只排除**收盘封死**的涨停；
3. **触板标记**：`high ≈ limit_up_price` 且收盘未封 → `touchedLimitUp=True`
   （盘中触板未封，上涨复盘的核心徽标之一；无法判定时 None，不写 False——未知不判否）。

fail-visible（AGENTS §4.0，与 market_dieban_tdx 同规）：
- 目录/文件缺失、空文件、记录损坏 → 跳过并计数，绝不伪 0；
- 当日有棒股数低于覆盖闸（峰值×0.9，读窗边缘）→ 该日不出结果，不冒充真实名单；
- 覆盖足但当日 0 只（如冰点日）→ 真读数，照写空名单；
- 「逐股行数 = 家数」同源派生（不保留第二份实现）。

存储：`market_daily_rise_stocks`（一天一文档，_id=date，rows 逐股 + source）。
当日盘后（15:05 截点后）首次页面读会懒加载扫描一次并落库（1 次/日）；历史日由
`backfill` CLI 显式回填（dry-run 默认）。无东财外呼（该名单无 EM 池，零外呼风险）。
"""
from __future__ import annotations

import argparse
import glob
import os
import time
from typing import Any, Iterable

from backend.core.limit_rules import limit_up_price
from backend.operations import market_dieban_tdx as tdx

COLLECTION_ROWS = "market_daily_rise_stocks"

SOURCE_TDX = "tdx_local_bars"               # 本地通达信日线重算（当前唯一全市场源）
FULL_MARKET_SOURCES = (SOURCE_TDX,)
SOURCE_LABELS = {SOURCE_TDX: "全市场·本地日线重算"}


def source_label(source: object) -> str:
    """source → 页面口径文案（单一事实源）。"""
    return SOURCE_LABELS.get(str(source or ""), "口径未知")


RISE_MIN_PCT = 5.0        # 涨幅闸（严格大于）
_PRICE_TOL = 0.005        # 涨停价精确容差（元）：快照/日线价按分取整


def is_sealed_limit_up(close: object, prev_close: object, code: object) -> bool | None:
    """收盘是否封死涨停（价格精确闸）；前收/收盘无效 → None（不可判，不写 False）。"""
    from backend.operations.market_dieban_pool import as_float
    close_f, prev_f = as_float(close), as_float(prev_close)
    if close_f is None or prev_f is None or close_f <= 0 or prev_f <= 0:
        return None
    return abs(close_f - limit_up_price(code, prev_f)) <= _PRICE_TOL


def _scan_file_rise(recs: list[tuple], code: str, dates: set[str]) -> tuple[dict[str, dict], set[str]]:
    """单只股票在 dates 内的「涨幅>5% 且未封涨停」逐股行 → (date → 行, 有棒日期集)。

    与 market_dieban_tdx._scan_file 同构：**有棒日期集在判定闸之前计数**（覆盖闸统计的是
    「该日有棒的文件数」，不是「命中名单的行数」——后者在冰点日为 0，会把真 0 只日误判成
    覆盖不足，2026-10-31 review blocker）。坏行（前收/收盘非正，停牌/除权异常）跳过，
    不伪读数。触板判定：high ≈ 涨停价（±0.005 元）且收盘未封 → touchedLimitUp=True；
    缺 high（理论上日线必有）→ None。
    """
    from backend.operations.market_dieban_pool import as_float
    out: dict[str, dict] = {}
    seen: set[str] = set()
    for i in range(1, len(recs)):
        raw_date = recs[i][0]
        if not raw_date:
            continue
        date = tdx._iso(raw_date)
        if date not in dates:
            continue
        seen.add(date)          # 覆盖闸计数：日期命中即计（涨幅/封板闸之前）
        prev_close = recs[i - 1][4] / 100.0
        close = recs[i][4] / 100.0
        if prev_close <= 0 or close <= 0:
            continue          # 停牌/坏数据：不伪涨幅
        pct = (close / prev_close - 1) * 100
        if not pct > RISE_MIN_PCT:
            continue
        limit_up = limit_up_price(code, prev_close)
        if abs(close - limit_up) <= _PRICE_TOL:
            continue          # 收盘封死涨停 → 不在「未上涨停」名单内
        high = recs[i][2] / 100.0
        touched: bool | None = None
        if as_float(high) is not None and high > 0:
            touched = abs(high - limit_up) <= _PRICE_TOL
        out[date] = {
            "code": code, "name": None, "pctChange": round(pct, 2),
            "price": round(close, 2), "prevClose": round(prev_close, 2),
            "open": round(recs[i][1] / 100.0, 2), "high": round(high, 2),
            "low": round(recs[i][3] / 100.0, 2),
            "limitUpPrice": round(float(limit_up) + 1e-9, 2),
            "touchedLimitUp": touched,
            "amount": recs[i][5], "volume": recs[i][6],
        }
    return out, seen


def scan_rows(dates: Iterable[str], *, root: str | None = None,
              universe: set[str] | None = None, take: int = tdx.DEFAULT_TAKE,
              names: dict[str, str] | None = None) -> tuple[dict[str, list[dict]], dict[str, Any]]:
    """一次性扫全市场日线重算各日「涨幅>5% 未涨停」**逐股名单** → (rows_by_date, meta)。

    覆盖闸/宇宙过滤/缺口语义与 `market_dieban_tdx.scan_rows` 完全一致（同一条读棒链，
    不写第二份实现）：`rows_by_date[d]` 为空列表 = 覆盖足但当日 0 只（真读数）；
    日期缺失 = 缺口（覆盖不足/无棒，不在 dict 里）。
    循环体与 tdx 版逐行同构（刻意镜像）：因 `_scan_file_rise` 判定闸/返回行形状不同
    无法直接共用，改动任一侧须对照另一侧（2026-10-31 review：覆盖闸 seen 语义曾因拷贝走样）。
    """
    wanted = {str(d) for d in dates}
    meta: dict[str, Any] = {"root": root, "last_bar": None, "files": 0, "skipped": 0,
                            "universe_hits": 0, "missing": 0, "coverage_max": 0, "partial": [],
                            "dates_without_bar": [], "zero_days": 0, "take": take}
    rows_by_date: dict[str, list[dict]] = {}
    if not wanted:
        return rows_by_date, meta
    if root is None:
        root, last_bar = tdx.resolve_root()
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
        elif not tdx.looks_like_a_share(code):
            meta["skipped"] += 1
            continue
        seen_codes.add(code)
        meta["files"] += 1
        hits, days = _scan_file_rise(tdx.read_lday(path, take), code, wanted)
        for date in days:
            seen[date] = seen.get(date, 0) + 1
        for date, row in hits.items():
            if names and not row.get("name"):
                row["name"] = names.get(code)
            rows_by_date.setdefault(date, []).append(row)
    if universe is not None:
        meta["universe_hits"] = len(seen_codes)
        meta["missing"] = len(universe - seen_codes)
    meta["coverage_max"] = max(seen.values()) if seen else 0
    floor = meta["coverage_max"] * tdx.COVERAGE_MIN_RATIO
    meta["partial"] = sorted(d for d, c in seen.items() if c < floor)
    for date in seen:
        if date in meta["partial"]:
            rows_by_date.pop(date, None)     # 覆盖不足：不冒充真实名单（fail-visible）
        else:
            rows_by_date.setdefault(date, [])  # 覆盖足 → 空列表是合法 0 只
    meta["zero_days"] = sum(1 for rows in rows_by_date.values() if not rows)
    meta["dates_without_bar"] = sorted(wanted - set(seen))
    return rows_by_date, meta


def save_rise_rows(db: Any, date: str, rows: list[dict[str, Any]], source: str = SOURCE_TDX) -> bool:
    """写逐股明细文档（一天一文档）；返回是否写入。

    - `rows` 为空且**覆盖缺口**（日期不在扫描结果里）不得落库 → 调用方只对覆盖足的日子
      调本函数；空列表 + 显式调用 = 「覆盖足、当日 0 只」的真读数，照写；
    - source 一律 TDX（当前唯一源）；重复写幂等（replace）。
    """
    col = db[COLLECTION_ROWS]
    col.replace_one({"_id": date}, {
        "_id": date, "source": source, "count": len(rows), "rows": rows,
        "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }, upsert=True)
    return True


def rows_for_date(db: Any, date: str) -> dict[str, Any] | None:
    """逐股明细文档（一天一文档）；无 → None（调用方披露，不伪 0）。"""
    return db[COLLECTION_ROWS].find_one({"_id": date})


def today_str() -> str:
    """上海时区当日（懒加载只服务「当日」）。"""
    from backend.operations.market_dieban_pool import today_str as _today
    return _today()


def _after_close() -> bool:
    """是否已过收盘截点（15:05，与 market_dieban_pool 同一截点纪律：盘中值不落库）。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return (now.hour, now.minute) >= (15, 5)


def rows_lazy(db: Any, date: str) -> dict[str, Any] | None:
    """读当日/历史日逐股文档；「当日 + 已过 15:05 + 文档缺」→ 懒加载扫描一次并落库。

    历史日不懒加载（与 market_dieban_pool 同规：回填显式走 CLI，防止一次页面读变成
    全史扫描）。扫描单日 = 全宇宙读棒（约数千文件），调用方必须带进程内缓存
    （见 services/jev/jev_rise_review 的 120s 负缓存）。
    """
    doc = rows_for_date(db, date)
    if doc is not None:
        return doc
    if date != today_str() or not _after_close():
        return None
    universe = tdx.universe_from_db(db)
    names = tdx.names_from_db(db)
    rows_by_date, meta = scan_rows([date], universe=universe, names=names)
    if date not in rows_by_date:
        return None   # 覆盖不足/无棒：不写不伪（页面按 rowsMissing 披露）
    save_rise_rows(db, date, rows_by_date[date])
    return rows_for_date(db, date)


def backfill(db: Any, start: str, end: str, *, apply: bool = False) -> None:
    """区间回填（dry-run 默认）：日轴 = snapshot_frames 交易日，逐日扫描落库。

    - 已有文档的日期跳过（幂等，不重复扫描）；`--rebuild` 强制重算覆写；
    - 覆盖不足/无棒日 → 披露缺口，**绝不写 0 行**；
    - 覆盖足但 0 只 → 真读数，照写空名单。
    """
    dates = sorted({str(r["tradingDate"]) for r in db["snapshot_frames"].find({}, {"tradingDate": 1})
                    if r.get("tradingDate") and start <= str(r["tradingDate"]) <= end})
    have = {str(d["_id"]) for d in db[COLLECTION_ROWS].find({"_id": {"$in": dates}}, {"_id": 1})}
    todo = [d for d in dates if d not in have]
    print(f"== 全市场「涨幅>{RISE_MIN_PCT}% 未涨停」逐股回填核查（{start}~{end}）："
          f"日轴 {len(dates)} 日，已有 {len(have)} 日，待处理 {len(todo)} 日 ==")
    if not todo:
        print("== 无待回填日 ==")
        return
    root, last_bar = tdx.resolve_root()
    print(f"本地通达信目录：{root or '未找到'}（末棒 {last_bar or '?'}）")
    if not root:
        raise SystemExit("未找到可用本地日线目录 → 不回填（fail-visible，不伪 0）")
    if last_bar and last_bar < todo[-1]:
        print(f"[警告] 目录末棒 {last_bar} 早于待回填末日 {todo[-1]}：该段将列缺口")
    universe = tdx.universe_from_db(db)
    names = tdx.names_from_db(db)
    rows_by_date, meta = scan_rows(todo, root=root, universe=universe, names=names)
    print(f"扫描：宇宙 {len(universe)} 只（命中日线 {meta.get('universe_hits', 0)} 只，"
          f"缺日线 {meta['missing']} 只）；有读数 {len(rows_by_date)} 日，"
          f"逐股行 {sum(len(r) for r in rows_by_date.values())} 行，"
          f"0 只日 {meta['zero_days']} 日")
    gaps = [d for d in todo if d not in rows_by_date]
    if gaps:
        print(f"[缺口] {len(gaps)} 日覆盖不足/无棒（不写 0）：{' '.join(gaps[:12])}"
              f"{' …' if len(gaps) > 12 else ''}")
    n_written = 0
    for d in todo:
        if d not in rows_by_date:
            continue
        rows = rows_by_date[d]
        if apply:
            save_rise_rows(db, d, rows)
        n_written += 1
        print(f"  [{'回填' if apply else '待回填'}] {d}: {len(rows):>4} 只"
              f"（触板未封 {sum(1 for r in rows if r.get('touchedLimitUp'))}）")
    print(f"== 完成：{'已落库' if apply else 'dry-run（加 --apply 落库）'} "
          f"{n_written} 日，缺口 {len(gaps)} 日 ==")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="全市场涨幅>5% 未涨停逐股（本地日线）回填/核查")
    ap.add_argument("--start", required=True, help="起始交易日 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="截止交易日 YYYY-MM-DD")
    ap.add_argument("--apply", action="store_true", help="落库（默认 dry-run 只披露）")
    args = ap.parse_args()

    def _db():
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database
        return get_runtime_mongodb_database()

    backfill(_db(), args.start, args.end, apply=args.apply)
