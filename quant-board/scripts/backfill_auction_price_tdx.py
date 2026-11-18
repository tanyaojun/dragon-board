# -*- coding: utf-8 -*-
"""TDX 日线回补 kpl_auction_price.s0925（历史日 09:25 开盘价/涨幅）。

背景（2026-11-18 用户裁决）：3006 现有流归档自上线日起新增；上线前的系列日档
（kpl_bidding_series）无 s0925，derive 回退旧链时掉池股 jj_percent 是早退值（错）。
收盘后本地 TDX 日线已落 → open/prevclose 零外呼回补 09:25 开盘涨幅（=App「匹配价」
09:25 冻结同源语义）；s0915 无本地源，保持缺席（fail-visible，不伪造）。

纪律：
- 只填缺失：live 3006 已收的 s0925 不覆盖；s0915 一律不碰。
- 回补行带 src=tdx_lday 审计标记（与 live 快照区分）。
- 停牌/缺棒/坏价：跳过并计数披露，不伪 0。
- **除权 band 校验（review 2026-11-18 B1）**：TDX lday 不复权，除权日 raw 前收算出的
  pct 系统性错误（如 10 送 10 → 伪 -50%）且会压过 MBL 冻结值进打分链。用
  limit_rules 单源真实涨/跌停价校验 open：越界=除权/无涨跌幅限制新股嫌疑 →
  跳过并计 bandSuspectN 披露（宁缺勿错，fail-visible）。
- 当日盘中禁跑（单写者=live collector）：main 入口拒绝 15:00 CST 前的当日日期。
- 用法：.venv python -m scripts.backfill_auction_price_tdx [YYYY-MM-DD ...]
  （缺省 = 全部 kpl_bidding_series 日档）
"""
from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.limit_rules import limit_down_price, limit_up_price  # noqa: E402
from backend.operations.market_dieban_tdx import _iso, read_lday, resolve_root  # noqa: E402
from backend.services.kpl_daban_archiver import archive_auction_price, load_auction_price  # noqa: E402

TAKE = 30  # 回补日必在尾部 30 棒内；多读 1 棒保 prevclose（目标日恰为窗首时不保守漏填）


def _lday_path(root: str, code: str) -> str | None:
    # review n3：92→北交所（镜像 limit_rules 43/8/92 前缀单源；早期 9 笼统归 sh 误路由 920）
    mkt = "bj" if code.startswith(("4", "8", "92")) else (
        "sh" if code.startswith(("6", "9", "5")) else "sz")
    path = os.path.join(root, "vipdoc", mkt, "lday", f"{mkt}{code}.day")
    return path if os.path.isfile(path) else None


def open_pct_for_date(path: str, date: str) -> dict | None:
    """目标日 open/prevclose → {price, pct, prevClose}；缺棒/停牌/坏价 → None（不伪值）。

    prevClose 供调用方做除权 band 校验（review B1），落库前由 backfill 剔除。
    不复权局限：除权日 pct 错，由 band 校验拦截；本函数不单独对外承诺 pct 正确。"""
    total = max(os.path.getsize(path) // 32, 1)  # 新上市股总棒数可能 < TAKE，防负 seek
    recs = read_lday(path, min(TAKE + 1, total))
    for i, rec in enumerate(recs):
        if _iso(rec[0]) != date:
            continue
        open_ = rec[1] / 100.0
        prev = recs[i - 1][4] / 100.0 if i > 0 else 0.0
        if open_ <= 0 or prev <= 0:
            return None
        return {"price": round(open_, 4), "pct": round((open_ / prev - 1) * 100, 4),
                "prevClose": round(prev, 4), "src": "tdx_lday"}
    return None


def _intraday_forbidden(date: str, now: Any = None) -> bool:
    """当日 15:00 CST 前禁跑（单写者=live collector，盘中回补会竞态）。"""
    from datetime import datetime, timedelta, timezone
    dt = now or datetime.now(timezone(timedelta(hours=8)))
    return date == dt.strftime("%Y-%m-%d") and dt.hour < 15


def backfill(db: Any, dates: list[str] | None = None, *, root: str | None = None) -> dict:
    """逐日回补 s0925 缺失股 → 汇总 {date: {filled, skippedLive, noBar, samples}}。"""
    if dates is None:
        dates = sorted(d["_id"] for d in db["kpl_bidding_series"].find({}, {"_id": 1}))
    if root is None:
        root, _ = resolve_root()
    summary: dict[str, dict] = {}
    for date in dates:
        universe: set[str] = set()
        for doc in db["kpl_bidding_series"].find({"_id": date}, {"ticks": 1}):
            for tick in doc.get("ticks") or []:
                for it in tick.get("it") or []:
                    c = str(it.get("s") or "")[-6:]
                    if c:
                        universe.add(c)
        existing = (load_auction_price(db, date) or {}).get("s0925") or {}
        filled: dict[str, dict] = {}
        no_bar: list[str] = []
        band_suspect: list[dict] = []
        for code in sorted(universe):
            if code in existing:
                continue  # live 3006 已收，不覆盖
            if not root:
                no_bar.append(code)
                continue
            path = _lday_path(root, code)
            rec = open_pct_for_date(path, date) if path else None
            if rec is None:
                no_bar.append(code)
                continue
            # review B1：除权/无限制新股 band 校验（limit_rules 单源真实涨/跌停价，
            # 含低价股 tick 取整浮动）：越界 → 宁缺勿错，不写值只披露
            prev = rec.pop("prevClose")
            if (rec["price"] > limit_up_price(code, prev) + 0.001
                    or rec["price"] < limit_down_price(code, prev) - 0.001):
                band_suspect.append({"code": code, "pct": rec["pct"]})
                continue
            filled[code] = rec
        r: dict = {"ok": True, "n25": 0}   # 无可填=无操作成功（与真失败区分，review n2）
        err = None
        if filled:
            try:
                r = archive_auction_price(db, date, s0925=filled)
            except Exception as exc:  # noqa: BLE001 — 逐日隔离，一日失败不中断整轮
                r, err = {"ok": False}, f"{type(exc).__name__}: {exc}"
        summary[date] = {"universe": len(universe), "filled": r.get("n25", 0) if r.get("ok") else 0,
                         "skippedLive": len(universe & set(existing)),
                         "noBar": len(no_bar), "noBarSamples": no_bar[:8],
                         "bandSuspectN": len(band_suspect), "bandSuspectSamples": band_suspect[:8],
                         "writeOk": bool(r.get("ok")),
                         **({"writeError": err} if err else {})}
    return summary


def main() -> None:
    from backend.data.repositories import repository_factory
    db = repository_factory.get_runtime_mongodb_database()
    dates = sys.argv[1:] or None
    if dates is None:
        dates = sorted(d["_id"] for d in db["kpl_bidding_series"].find({}, {"_id": 1}))
    run = [d for d in dates if not _intraday_forbidden(d)]
    for d in dates:
        if d not in run:
            print(d, {"skipped": "intraday_forbidden（当日 15:00 CST 前禁跑，单写者=live collector）"})
    for date, s in backfill(db, run).items():
        print(date, s)


if __name__ == "__main__":
    main()
