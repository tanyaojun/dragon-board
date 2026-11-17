# -*- coding: utf-8 -*-
"""竞价窗晨间体检（只读；零外呼、零写库、零 jev）。

用法（盘前 09:10 / 窗后 09:30 各跑一次）：
    .venv/Scripts/python.exe scripts/auction_window_check.py            # 当日
    .venv/Scripts/python.exe scripts/auction_window_check.py --date 2026-11-18

检查面（验收口径 = prereg §7.13 / 2026-11-17 定案）：
  A 进程在位：:8002 采集服务 / :8001 scheduler（只 GET 本地状态口）
  B 收敛面 flags：sub_staged=False / sub_unique_id=True / unsub_enabled=True /
    ka_mode=off / zt_reasons_subscribed=0 / stock_detail_subs=False
  C 主链 tick 观测：序列档 ticks 时间轴、首 tick 时刻、窗内 tickN、最大空窗
  D 09:26 挂链产物：trialState（source/n_rows/tickN/plateJoinedN）/ mblState /
    bidSupplement / roster pushState
  E 日档完整性：kpl_daban_pool bid 通道 pages_missing / 成员数 / bid_ts
  F 验收四项：
    ① 首 tick ≤09:15:30          ④ 窗内 tickN ≥20
    ③ posture 翻转率 vs 涨停开盘 3/4 基线（首末帧比较，§7.9 用户裁决语义）
    ② first比：Wzs 退役后无真值参照——输出 first/max 值层原始比，参照源留用户裁决
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import urllib.request
import zoneinfo
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")  # Windows GBK 控制台

TZ = zoneinfo.ZoneInfo("Asia/Shanghai")
COL_LABEL = "hotlist_jev_auction_leader_labels"
COL_POOL = "kpl_daban_pool"
COL_SERIES = "kpl_bidding_series"
COL_LIVE = "kpl_live_daily"
WINDOW = (9 * 60 + 15, 9 * 60 + 27)  # 试盘行派生窗（与 collector 门控一致）


def _get(url: str, timeout: float = 5.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 — 体检脚本只报告，不抛
        return {"_error": f"{type(exc).__name__}: {exc}"}


def _hhmm(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, TZ).strftime("%H:%M:%S")


def _db():
    from backend.core.settings import get_settings
    from backend.data.repositories.repository_factory import get_mongodb_database
    s = get_settings()
    return get_mongodb_database(
        s.mongodb_uri, s.mongodb_database,
        connect_timeout_ms=s.mongodb_connect_timeout_ms,
        server_selection_timeout_ms=s.mongodb_server_selection_timeout_ms)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()
    date = args.date or dt.datetime.now(TZ).strftime("%Y-%m-%d")
    print(f"=== 竞价窗体检 {date}（只读） ===")

    # A 进程在位
    col = _get("http://127.0.0.1:8002/api/kpl/status")
    sch = _get("http://127.0.0.1:8001/api/snapshot-collector/scheduler/status")
    ok_col = isinstance(col, dict) and col.get("ok")
    ok_sch = isinstance(sch, dict) and not sch.get("_error")
    print(f"\n[A] 进程: :8002 {'✅' if ok_col else '❌ ' + json.dumps(col, ensure_ascii=False)[:120]}"
          f"  :8001 {'✅' if ok_sch else '❌ ' + json.dumps(sch, ensure_ascii=False)[:120]}")
    if ok_col:
        print(f"    sessions={col.get('sessions')} pushes={col.get('pushes')} errors={col.get('errors')}"
              f" 断连={col.get('server_disconnect_count')} 退避={col.get('reconnect_backoff_s')}"
              f" 连败={col.get('retry_fail_count')}")
        print(f"    死因={col.get('last_death_cause')!r} err_code={col.get('last_session_err_code')}"
              f" last_session_s={col.get('last_session_s')}")

    # B 收敛面 flags
    if ok_col:
        flags_ok = (col.get("sub_staged") is False and col.get("sub_unique_id") is True
                    and col.get("unsub_enabled") is True and col.get("ka_mode") == "off"
                    and not col.get("zt_reasons_subscribed") and not col.get("stock_detail_subs"))
        print(f"\n[B] 收敛面 flags: {'✅ 全部符合' if flags_ok else '❌ 偏离'}"
              f"（staged={col.get('sub_staged')} unique={col.get('sub_unique_id')}"
              f" unsub={col.get('unsub_enabled')} ka={col.get('ka_mode')}"
              f" zt_reason_sub={col.get('zt_reasons_subscribed')} detail={col.get('stock_detail_subs')}）")

    db = _db()
    # C 主链 tick 观测
    ser = db[COL_SERIES].find_one({"date": date}) or {}
    ticks = ser.get("ticks") or []
    w_lo, w_hi = WINDOW
    in_win: list[dict] = []
    print(f"\n[C] 序列档 ticks（窗门控 {ser.get('window')}，共 {len(ticks)} 帧）：")
    prev_ts = None
    max_gap = 0.0
    for t in ticks:
        ts = t.get("ts")
        if not isinstance(ts, (int, float)):
            continue
        hm = dt.datetime.fromtimestamp(ts, TZ)
        mins = hm.hour * 60 + hm.minute
        inwin = w_lo <= mins < w_hi
        if inwin:
            in_win.append(t)
            if prev_ts is not None:
                max_gap = max(max_gap, ts - prev_ts)
        prev_ts = ts
        print(f"    {_hhmm(ts)}  n={t.get('n')}  {'窗内' if inwin else '窗外(冻结后)'}")
    first_ts = in_win[0]["ts"] if in_win else None
    v1 = first_ts is not None and dt.datetime.fromtimestamp(first_ts, TZ).strftime("%H:%M:%S") <= "09:15:30"
    v4 = len(in_win) >= 20
    print(f"    首tick={_hhmm(first_ts) if first_ts else '缺席'}  窗内tickN={len(in_win)}"
          f"  最大空窗={max_gap:.0f}s")
    print(f"    ①首tick≤09:15:30: {'✅' if v1 else '❌'}    ④窗内tickN≥20: {'✅' if v4 else '❌'}")

    # D 挂链产物
    lab = db[COL_LABEL].find_one({"_id": {"$regex": date}}) or {}
    cs = lab.get("corpusState") or {}
    ts_ = cs.get("trialState") or {}
    print(f"\n[D] 挂链 corpusState：")
    print(f"    trialState: {json.dumps(ts_, ensure_ascii=False)[:200]}")
    print(f"    mblState:   {json.dumps(cs.get('mblState'), ensure_ascii=False)[:160]}")
    print(f"    bidLane={cs.get('bidLane')} bidIn={cs.get('bidIn')}"
          f" bidSupplement={cs.get('bidSupplement')} basisState={cs.get('basisState')}")
    src_ok = ts_.get("source") == "kpl_bidding_series_derived"
    print(f"    试盘行源头=socket主链: {'✅' if src_ok else '❌ ' + str(ts_.get('source'))}")
    live = db[COL_LIVE].find_one({"_id": date}, {"auctionPush.pushState": 1, "auctionPush.stocks": 1}) or {}
    ap_ = live.get("auctionPush") or {}
    print(f"    roster pushState={ap_.get('pushState')} 股数={len(ap_.get('stocks') or [])}")

    # ③ posture 翻转率（首末帧比较，§7.9 语义；基线=涨停开盘 3/4）+ ② 值层原始比
    # 用派生层同一实现（auction_trial_derive）从序列档算全量行——与打标链同口径
    try:
        from backend.operations.auction_trial_derive import derive_trial_rows_from_series
        drows, dstate = derive_trial_rows_from_series(db, date)
    except Exception as exc:  # noqa: BLE001 — 体检只报告
        drows, dstate = {}, {"state": f"derive_failed:{type(exc).__name__}: {exc}"}
    dec = mnt = 0
    print(f"    ③/② 派生层全量行 n_rows={len(drows)} state={json.dumps(dstate, ensure_ascii=False)[:120]}")
    # ② max/first：Wzs 出链后无真值参照，作时序健康度代理（前插生效→首 tick 早→趋近 1）
    print(f"    ② first/max 值层抽样（前 8，按 max 降序）：")
    rows_sorted = sorted(drows.values(), key=lambda r: -(r.get("max_amount") or 0))
    for r in rows_sorted[:8]:
        f_, m_, l_ = r.get("first_amount"), r.get("max_amount"), r.get("last_amount")
        ratio = round(m_ / f_, 2) if f_ and m_ and f_ > 0 else None
        print(f"      {r.get('code')} {r.get('name')}: first={f_} max={m_} last={l_} max/first={ratio}")
    for r in drows.values():
        f_, l_ = r.get("first_amount"), r.get("last_amount")
        try:
            f_, l_ = float(f_), float(l_)
        except (TypeError, ValueError):
            continue
        if l_ >= f_:
            mnt += 1
        else:
            dec += 1
    known = dec + mnt
    rate = dec / known if known else None
    print(f"    ③ posture 首末帧: decrease={dec} maintain={mnt}"
          f" 翻转率={f'{rate:.0%}' if rate is not None else '无数据'}"
          f"（基线：涨停开盘 3/4，≤基线即改善）")

    # E 日档完整性
    pool = db[COL_POOL].find_one({"_id": date},
                                 {"bid_items": 1, "bid_pages_missing": 1, "bid_pages": 1,
                                  "bid_pages_expected": 1, "bid_ts": 1, "bid_empty": 1}) or {}
    missing = pool.get("bid_pages_missing")
    bid_ts = pool.get("bid_ts")
    print(f"\n[E] 竞价池日档: 成员={len(pool.get('bid_items') or [])}"
          f" 页={pool.get('bid_pages')}/{pool.get('bid_pages_expected')}"
          f" missing={missing} bid_ts={_hhmm(bid_ts) if isinstance(bid_ts, (int, float)) else bid_ts}"
          f" empty={pool.get('bid_empty')}")
    print(f"    日档页完整: {'✅' if missing == [] or missing is None else '❌ ' + str(missing)}")

    # F 汇总
    print(f"\n[F] 判定汇总：①{'✅' if v1 else '❌'} ③翻转率={f'{rate:.0%}' if rate is not None else '—'}"
          f" ④{'✅' if v4 else '❌'} ②值层见上（参照源留裁决） 源头{'✅' if src_ok else '❌'}"
          f" 日档{'✅' if missing in ([], None) else '❌'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
