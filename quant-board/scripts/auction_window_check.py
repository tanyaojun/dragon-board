# -*- coding: utf-8 -*-
"""竞价窗晨间体检（只读；零外呼、零写库、零 jev）。

用法（盘前 09:10 / 窗后 09:30 各跑一次）：
    .venv/Scripts/python.exe scripts/auction_window_check.py            # 当日
    .venv/Scripts/python.exe scripts/auction_window_check.py --date 2026-11-18

检查面（验收口径 = density-storage-fix-plan-20261119 §6，取代 prereg §7.13 旧阈值）：
  A 进程在位：:8002 采集服务 / :8001 scheduler（只 GET 本地状态口）
  B 收敛面 flags：sub_staged=False / sub_unique_id=True / unsub_enabled=True /
    ka_mode=off / zt_reasons_subscribed=0 / stock_detail_subs=False
  C 主链 tick 观测：序列档 ticks 时间轴、首 tick 时刻、窗内观测事件数、gap 中位/max
  D 09:26 挂链产物：trialState（source/n_rows/tickN/plateJoinedN）/ mblState /
    bidSupplement / roster pushState
  E 日档完整性：kpl_daban_pool bid 通道 pages_missing / 成员数 / bid_ts
  F 验收四项（pid8 3s 重请求 lane 开火后）：
    ① 首 tick ≤09:15:10          ② 窗内观测事件 ≥150
    ③ gap 中位 ≤4s、max ≤15s（会话轮转上限）
    ④ --wzs：603324 类首开/首加与 Wzs 同日缓存对拍（窗后 1 GET，survey §6 合同，
      预算 1 发；首开差 ≤5%、首加同笔）——默认零外呼，显式 --wzs 才发
  另：posture 翻转率 vs 涨停开盘 3/4 基线（首末帧比较，§7.9 语义）保留作健康度代理
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
    ap.add_argument("--wzs", action="store_true",
                    help="窗后 Wzs 同日缓存对拍（预算 1 GET，survey §6 合同；默认零外呼）")
    ap.add_argument("--wzs-code", default="603324",
                    help="对拍目标股（默认 603324 盛剑科技，11-19 复盘锚）")
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
    # C 主链 tick 观测（2026-11-19 逐 tick 文档化：走 load_bidding_series 唯一读口）
    from backend.services.kpl_daban_archiver import load_bidding_series
    ser = load_bidding_series(db, date) or {}
    ticks = ser.get("ticks") or []
    w_lo, w_hi = WINDOW
    in_win: list[dict] = []
    print(f"\n[C] 序列档 ticks（窗门控 {ser.get('window')}，共 {len(ticks)} 帧）：")
    prev_ts = None
    gaps: list[float] = []
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
                gaps.append(ts - prev_ts)
        prev_ts = ts
        print(f"    {_hhmm(ts)}  n={t.get('n')}  {'窗内' if inwin else '窗外(冻结后)'}")
    first_ts = in_win[0]["ts"] if in_win else None
    gaps_sorted = sorted(gaps)
    gap_med = (gaps_sorted[len(gaps_sorted) // 2] if gaps_sorted else None)
    gap_max = max(gaps) if gaps else 0.0
    v1 = first_ts is not None and dt.datetime.fromtimestamp(first_ts, TZ).strftime("%H:%M:%S") <= "09:15:10"
    v2 = len(in_win) >= 150
    v3 = gap_med is not None and gap_med <= 4.0 and gap_max <= 15.0
    print(f"    首tick={_hhmm(first_ts) if first_ts else '缺席'}  窗内观测事件={len(in_win)}"
          f"  gap中位={f'{gap_med:.1f}s' if gap_med is not None else '—'}  gap_max={gap_max:.0f}s")
    print(f"    ①首tick≤09:15:10: {'✅' if v1 else '❌'}    ②窗内事件≥150: {'✅' if v2 else '❌'}"
          f"    ③gap中位≤4s且max≤15s: {'✅' if v3 else '❌'}")

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
    print(f"\n[F] 判定汇总：①{'✅' if v1 else '❌'} ②{'✅' if v2 else '❌'} ③{'✅' if v3 else '❌'}"
          f" posture翻转率={f'{rate:.0%}' if rate is not None else '—'}"
          f" ④{'见下' if args.wzs else '未跑（--wzs 显式开启，预算 1 GET）'}"
          f" 源头{'✅' if src_ok else '❌'}"
          f" 日档{'✅' if missing in ([], None) else '❌'}")

    # ④ Wzs 同日缓存对拍（窗后 1 GET，survey §6 合同；预算 1 发，不带 refresh）
    if args.wzs:
        v4 = _wzs_compare(date, args.wzs_code, drows)
        print(f"    ④Wzs对拍: {'✅' if v4 else '❌'}")
    return 0


def _wzs_compare(date: str, code: str, drows: dict) -> bool:
    """603324 类首开/首加 vs Wzs 同日缓存（1 GET，fetched 回显披露）。

    值层收敛判据（plan §6）：首开差 ≤5%、首加同笔（相对差 ≤5% 容差，
    观测首帧时点差导致的尾差披露不阻断）。Wzs rank=数值原值（元）。
    """
    url = ("http://wzslinker.top/companys/api-auction.php"
           f"?page=limit_up_bidding&date={date}")
    print(f"\n[W] Wzs 对拍 {code}（预算 1 GET，不带 refresh）：{url}")
    resp = _get(url, timeout=15.0)
    if not isinstance(resp, dict) or resp.get("_error"):
        print(f"    ❌ 请求失败：{resp}")
        return False
    print(f"    fetched={resp.get('fetched')} saved_at={resp.get('saved_at')}"
          f" actual_date={resp.get('actual_date')} is_fallback={resp.get('is_fallback')}")
    try:
        sl = resp["data"]["data"]["stock_list"]
        keys = [h.get("sort_key") for h in sl["head_info"]]
        i_code = keys.index("stock_id")
        i_first = keys.index("first_amount")
        i_add = keys.index("first_add")
    except (KeyError, TypeError, ValueError) as exc:
        print(f"    ❌ 合同解析失败：{type(exc).__name__}: {exc}")
        return False
    wzs_row = None
    for row in sl.get("list") or []:
        cell = row[i_code] if isinstance(row, list) and len(row) > i_code else {}
        if str((cell.get("param") or {}).get("code") or "") == code:
            wzs_row = row
            break
    if wzs_row is None:
        print(f"    ❌ Wzs 当日榜无 {code}（掉池/未顶板均可能，留用户裁决）")
        return False

    def _num(cell):
        try:
            return float(cell.get("rank"))
        except (TypeError, ValueError, AttributeError):
            return None

    w_first, w_add = _num(wzs_row[i_first]), _num(wzs_row[i_add])
    mine = drows.get(code) or {}
    m_first, m_add = mine.get("first_amount"), mine.get("first_add")
    print(f"    Wzs: first={w_first} first_add={w_add}"
          f"（start={wzs_row[keys.index('start_time')].get('rank') if 'start_time' in keys else '--'}）")
    print(f"    我方: first={m_first} first_add={m_add}（start={mine.get('start_time')}）")
    ok = True
    if w_first and m_first is not None:
        diff = abs(m_first - w_first) / w_first
        ok = ok and diff <= 0.05
        print(f"    首开相对差={diff:.2%} {'✅≤5%' if diff <= 0.05 else '❌>5%'}")
    else:
        ok = False
        print("    首开缺一方值 ❌（不伪 0）")
    if w_add is not None and m_add is not None:
        denom = max(abs(w_add), 1.0)
        diff = abs(m_add - w_add) / denom
        ok = ok and diff <= 0.05
        print(f"    首加相对差={diff:.2%} {'✅同笔' if diff <= 0.05 else '❌非同笔'}")
    else:
        ok = False
        print("    首加缺一方值 ❌（不伪 0）")
    return ok


if __name__ == "__main__":
    raise SystemExit(main())
