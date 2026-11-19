# -*- coding: utf-8 -*-
"""竞价试盘面板行情补全（2026-11-18 用户裁决：现价实时 / 昨涨幅落库）。

- **现价**：读 MarketQuotesCache 全市场行情共享 Redis 快照（腾讯源，跨进程单源，
  读侧零新增外呼，红线 9）；刷新频率归写侧（≥60s），ts 经 `<key>:ts` 透出披露。
- **昨涨幅**：采集路径 TDX 日线（tdx_daily_bars，与 python-bridge 同款 TDX 协议）
  算 (昨收/前昨收−1)×100，**落库 kpl_bidding_series 加字段**（2026-11-18 用户裁决：
  不建新集合；prev_pct=code→行 map，prev_pct_state=采集审计 meta；字段级 $set
  单写者=:8000 archiver，collector 写 ticks 各写各字段，绝不触碰 ticks）。
  未复权口径（除权除息罕见失真，披露）。stock_prev_day_pct 与 auction_trial_raw
  均已 mongodump 归档 data/backups/ 后单集合 drop（红线 4，用户裁决退役）。
- **开盘涨幅（2026-11-19 修复）**：同一次 TDX 日线取数**顺带**读当日棒 open
  （盘中 socket 日线已含当日开盘，11-19 机制核实：301391 open=50.9==MBL 09:28
  冻结==真开盘），算 (open/昨收−1)×100 落库同档 `open_pct` 加字段（+open_pct_state
  审计 meta，bandSuspect 除权越界名单宁缺勿错不重试）。**零新增外呼**（复用
  prev_pct 既有 fetch_daily_bars 调用与频控预算）。背景：kpl_auction_price live
  归档覆盖⊆浏览器驱动 3006 订阅面（竞价试盘页不并宇宙入订阅面→竞价窗内零捕获），
  而 MBL/bid 成员制掉池股留早退值（11-16 预登记缺陷定案）不得作开盘涨幅回退；
  TDX 当日棒非成员制、全宇宙覆盖，故为盘中开盘涨幅兜底权威（存档 s0925 仍第一权威）。
  当日 09:25 CST 前 open 未撮合→不列 pending 不烧预算（fail-visible 缺席）。

频控预算（§1.2-9，会话型 TDX + 轮询型 archiver 双形态登记）：
- TDX 日线 ≤ KPL_PREV_PCT_ROUND_LIMIT(30) 只/轮，单档 offset=15、max_probe=3
  （坏节点探测上限 3×5s，socket 10s 兜底，tdx_daily_bars 既有护栏）；
- 日尝试上限 KPL_PREV_PCT_DAILY_CAP(1200)（prev_pct_state.attempts_n 落库；
  2026-11-19 自 600 上调：open_pct 顺带取数最坏=2×宇宙（prev 先于 09:25 完成时
  open 需独立一轮遍历），正常同批顺带=1×宇宙；TDX 会话型预算重登记）；
- 连续全失败轮指数退避跳轮（backoff_rounds 上限 8，落库跨重启生效）；
- 进程级 _BARS_CACHE + prev_pct rows 双重去重：成功后零重拉；失败码下轮自愈至日上限。
- 宇宙=当日 kpl_bidding_series ∪ kpl_morning_bidding_raw（纯库读）；无宇宙零外呼 skip。
"""
from __future__ import annotations

import os
import time
from typing import Any

COLLECTION_SERIES = "kpl_bidding_series"
COLLECTION_MBL_RAW = "kpl_morning_bidding_raw"


def _round_limit() -> int:
    return max(1, int(os.environ.get("KPL_PREV_PCT_ROUND_LIMIT", "30")))


def _daily_cap() -> int:
    return max(1, int(os.environ.get("KPL_PREV_PCT_DAILY_CAP", "1200")))


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


def collect_prev_day_pct(db: Any, date: str, *, limit: int | None = None,
                         now: float | None = None) -> dict:
    """昨涨幅+开盘涨幅限量懒取 → kpl_bidding_series.prev_pct/open_pct 加字段
    （archiver 单写者；失败留痕不抛，§4.0；字段级 $set 不覆盖 ticks）。
    同一次 fetch_daily_bars 顺带读当日棒 open（零新增外呼，2026-11-19）。"""
    if os.environ.get("KPL_PREV_PCT_ENABLED", "1") == "0":
        return {"state": "disabled"}
    from datetime import datetime, timedelta, timezone
    now_dt = datetime.fromtimestamp(now if now is not None else time.time(),
                                    timezone(timedelta(hours=8)))
    # 当日 09:25 撮合前 open不存在→open 不列 pending（不烧日预算）；历史日全天可取
    open_active = (date != now_dt.strftime("%Y-%m-%d")
                   or (now_dt.hour * 3600 + now_dt.minute * 60 + now_dt.second)
                   >= 9 * 3600 + 25 * 60)
    col = db[COLLECTION_SERIES]
    doc = col.find_one({"_id": date}, {"prev_pct": 1, "prev_pct_state": 1,
                                      "open_pct": 1, "open_pct_state": 1}) or {}
    rows = dict(doc.get("prev_pct") or {})
    meta = dict(doc.get("prev_pct_state") or {})
    open_rows = dict(doc.get("open_pct") or {})
    open_meta = dict(doc.get("open_pct_state") or {})
    band_suspect = set(open_meta.get("bandSuspect") or [])
    # review 2026-11-19 minor：取数成功但当日棒缺（停牌等）→ 披露并退出 pending 面，
    # 不再逐轮烧日预算（fail-visible；当日棒后现不在此列——已排除，次日档新开重算）
    open_no_bar = set(open_meta.get("openNoBar") or [])
    failed = dict(meta.get("failed") or {})
    attempts = int(meta.get("attempts_n") or 0)
    consec = int(meta.get("consec_fail") or 0)
    backoff = int(meta.get("backoff_rounds") or 0)
    if backoff > 0:
        meta["backoff_rounds"] = backoff - 1
        col.update_one({"_id": date}, {"$set": {"prev_pct_state": meta}},
                       upsert=True)
        return {"state": "backoff", "remaining": backoff - 1}
    universe = trial_universe_codes(db, date)
    if not universe:
        return {"state": "skipped_no_universe"}
    prev_pending = [c for c in universe if c not in rows]
    open_pending = ([c for c in universe
                     if c not in open_rows and c not in band_suspect
                     and c not in open_no_bar]
                    if open_active else [])
    # open 缺位优先（用户面开盘涨幅列），prev -only 缺位殿后；同股一次取数双字段
    open_set = set(open_pending)
    pending = open_pending + [c for c in prev_pending if c not in open_set]
    base = {"n": len(rows), "pending_n": len(pending), "universe_n": len(universe),
            "open_n": len(open_rows), "open_pending_n": len(open_pending)}
    if not pending:
        return {**base, "state": "complete"}
    cap = _daily_cap()
    if attempts >= cap:
        return {**base, "state": "daily_cap", "attempts_n": attempts}
    batch = pending[:min(limit or _round_limit(), cap - attempts)]
    from backend.operations.tdx_daily_bars import fetch_daily_bars
    from backend.core.limit_rules import limit_down_price, limit_up_price
    ok_n = 0
    open_ok_n = 0
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
        # 开盘涨幅顺带取数：当日棒 open/昨收；除权 band 校验镜像 backfill B1
        # （limit_rules 单源真实涨/跌停价，越界=除权/无限制新股嫌疑→宁缺勿错不重试）
        if (open_active and c not in open_rows and c not in band_suspect
                and c not in open_no_bar):
            ob = (bars or {}).get(date) or {}
            if not ob and bars:
                open_no_bar.add(c)   # 当日棒缺（停牌等）：披露+退出 pending，不烧预算
            try:
                open_ = float(ob.get("open") or 0)
            except (TypeError, ValueError):
                open_ = 0.0
            prev_close = closes[-1][1] if closes else 0.0
            if open_ > 0 and prev_close > 0:
                if (open_ > limit_up_price(c, prev_close) + 0.001
                        or open_ < limit_down_price(c, prev_close) - 0.001):
                    band_suspect.add(c)
                else:
                    open_rows[c] = {"price": round(open_, 4),
                                    "pct": round((open_ / prev_close - 1) * 100.0, 4),
                                    "src": "tdx_bar"}
                    open_ok_n += 1
    consec = 0 if ok_n else consec + 1
    new_backoff = min(8, consec) if ok_n == 0 else 0
    meta.update({
        "failed": failed, "attempts_n": attempts, "consec_fail": consec,
        "backoff_rounds": new_backoff,
        "pending_n": len([c for c in universe if c not in rows]),
        "source": "tdx_daily_bars",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    open_meta.update({
        "n": len(open_rows), "bandSuspect": sorted(band_suspect),
        "bandSuspectN": len(band_suspect), "open_ok_n": open_ok_n,
        "openNoBar": sorted(open_no_bar), "openNoBarN": len(open_no_bar),
        "pending_n": len([c for c in universe
                          if c not in open_rows and c not in band_suspect
                          and c not in open_no_bar]),
        "source": "tdx_daily_bars",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    col.update_one({"_id": date}, {"$set": {
        "prev_pct": rows, "prev_pct_state": meta,
        "open_pct": open_rows, "open_pct_state": open_meta,
    }}, upsert=True)
    return {**base, "state": "ok" if ok_n else "all_failed",
            "batch_n": len(batch), "ok_n": ok_n, "open_ok_n": open_ok_n,
            "attempts_n": attempts,
            "pending_n": meta["pending_n"], "backoff_rounds": new_backoff}


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
