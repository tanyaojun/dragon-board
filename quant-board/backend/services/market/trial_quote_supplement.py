# -*- coding: utf-8 -*-
"""竞价试盘面板行情补全（2026-11-18 用户裁决：现价实时 / 昨涨幅落库）。

- **现价**：读 MarketQuotesCache 全市场行情共享 Redis 快照（腾讯源，跨进程单源，
  读侧零新增外呼，红线 9）；刷新频率归写侧（≥60s），ts 经 `<key>:ts` 透出披露。
- **昨涨幅**：采集路径 TDX 日线（tdx_daily_bars，与 python-bridge 同款 TDX 协议）
  算 (昨收/前昨收−1)×100 落库 `stock_prev_day_pct` 日档（_id=日期）；archiver
  盘中每轮限量懒取，单写者=:8000 archiver。未复权口径（除权除息罕见失真，披露）。

频控预算（§1.2-9，会话型 TDX + 轮询型 archiver 双形态登记）：
- TDX 日线 ≤ KPL_PREV_PCT_ROUND_LIMIT(30) 只/轮，单档 offset=15、max_probe=3
  （坏节点探测上限 3×5s，socket 10s 兜底，tdx_daily_bars 既有护栏）；
- 日尝试上限 KPL_PREV_PCT_DAILY_CAP(600)（attempts_n 落库，防坏节点无限重试）；
- 连续全失败轮指数退避跳轮（backoff_rounds 上限 8，落库跨重启生效）；
- 进程级 _BARS_CACHE + 日档 rows 双重去重：成功后零重拉；失败码下轮自愈至日上限。
- 宇宙=当日 kpl_bidding_series ∪ kpl_morning_bidding_raw（纯库读）；无宇宙零外呼 skip。
"""
from __future__ import annotations

import os
import time
from typing import Any

COLLECTION_PREV_PCT = "stock_prev_day_pct"
COLLECTION_SERIES = "kpl_bidding_series"
COLLECTION_MBL_RAW = "kpl_morning_bidding_raw"


def _round_limit() -> int:
    return max(1, int(os.environ.get("KPL_PREV_PCT_ROUND_LIMIT", "30")))


def _daily_cap() -> int:
    return max(1, int(os.environ.get("KPL_PREV_PCT_DAILY_CAP", "600")))


def trial_universe_codes(db: Any, date: str) -> list[str]:
    """当日试盘宇宙（序列∪MBL，纯库读零外呼）。"""
    codes: set[str] = set()
    s = db[COLLECTION_SERIES].find_one({"_id": date}, {"ticks": 1}) or {}
    for t in s.get("ticks") or []:
        for it in t.get("it") or []:
            c = str(it.get("s") or "")[-6:]
            if c:
                codes.add(c)
    m = db[COLLECTION_MBL_RAW].find_one({"_id": date}, {"rows": 1}) or {}
    codes.update(str(c)[-6:] for c in (m.get("rows") or {}))
    return sorted(c for c in codes if c)


def collect_prev_day_pct(db: Any, date: str, *, limit: int | None = None) -> dict:
    """昨涨幅限量懒取落库（archiver 单写者调用；失败留痕不抛，§4.0）。"""
    if os.environ.get("KPL_PREV_PCT_ENABLED", "1") == "0":
        return {"state": "disabled"}
    col = db[COLLECTION_PREV_PCT]
    doc = col.find_one({"_id": date}) or {}
    rows = dict(doc.get("rows") or {})
    failed = dict(doc.get("failed") or {})
    attempts = int(doc.get("attempts_n") or 0)
    consec = int(doc.get("consec_fail") or 0)
    backoff = int(doc.get("backoff_rounds") or 0)
    if backoff > 0:
        col.update_one({"_id": date}, {"$set": {"backoff_rounds": backoff - 1}},
                       upsert=True)
        return {"state": "backoff", "remaining": backoff - 1}
    universe = trial_universe_codes(db, date)
    if not universe:
        return {"state": "skipped_no_universe"}
    pending = [c for c in universe if c not in rows]
    base = {"n": len(rows), "pending_n": len(pending), "universe_n": len(universe)}
    if not pending:
        return {**base, "state": "complete"}
    cap = _daily_cap()
    if attempts >= cap:
        return {**base, "state": "daily_cap", "attempts_n": attempts}
    batch = pending[:min(limit or _round_limit(), cap - attempts)]
    from backend.operations.tdx_daily_bars import fetch_daily_bars
    ok_n = 0
    for c in batch:
        attempts += 1
        bars = fetch_daily_bars(c, offset=15, max_probe=3)
        closes = sorted(
            (d, float(b["close"])) for d, b in (bars or {}).items()
            if d < date and isinstance((b or {}).get("close"), (int, float)))
        if len(closes) >= 2 and closes[-2][1] > 0:
            (d1, p1), (d2, p2) = closes[-2], closes[-1]
            rows[c] = {"pct": round((p2 / p1 - 1) * 100.0, 4),
                       "prevDate": d2, "prevClose": p2, "prevPrevClose": p1}
            failed.pop(c, None)
            ok_n += 1
        else:
            failed[c] = "no_two_closes" if bars else "bars_unavailable"
    consec = 0 if ok_n else consec + 1
    new_backoff = min(8, consec) if ok_n == 0 else 0
    col.update_one({"_id": date}, {"$set": {
        "date": date, "rows": rows, "failed": failed,
        "attempts_n": attempts, "consec_fail": consec,
        "backoff_rounds": new_backoff,
        "pending_n": len([c for c in universe if c not in rows]),
        "source": "tdx_daily_bars",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }}, upsert=True)
    return {**base, "state": "ok" if ok_n else "all_failed",
            "batch_n": len(batch), "ok_n": ok_n, "attempts_n": attempts,
            "pending_n": len([c for c in universe if c not in rows]),
            "backoff_rounds": new_backoff}


def read_realtime_prices(codes: list[str]) -> tuple[dict[str, dict], int | None]:
    """现价实时补全读口（共享 Redis 快照 hmget，零外呼）；不可用→({},None) 不伪 0。

    返回 ({code: {"price": f2, "pct": f3}}, fetchedAtMs)。
    """
    if not codes:
        return {}, None
    try:
        from backend.market_proxy.redis_client import get_hotlist_redis_client
        from backend.market_proxy.quotes import market_quotes_redis_key
        client = get_hotlist_redis_client()
        if client is None:
            return {}, None
        key = market_quotes_redis_key()
        raws = client.hmget(key, list(dict.fromkeys(codes)))
        ts_raw = client.get(key + ":ts")
        ts = int(ts_raw) if ts_raw else None
    except Exception:  # noqa: BLE001 — Redis 挂/过期一律缺席，调用方降级
        return {}, None
    out: dict[str, dict] = {}
    import json
    for c, raw in zip(codes, raws):
        try:
            row = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except (TypeError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(row, dict) and row.get("f2") is not None:
            out[c] = {"price": row.get("f2"), "pct": row.get("f3")}
    return out, ts
