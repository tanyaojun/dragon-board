# -*- coding: utf-8 -*-
"""4-6 月槽位 pctChange 历史回填（TDX 5 分钟线，§十四续二 执行件，2026-10-03 用户令）。

背景：snapshot_stock_rows 4/15-6/30 共 116,549 行 pctChange 缺失（历史帧采集链未存）；
TDX 5 分钟线分页可回溯至 2026-03-19（akshare/东财封 8/18、腾讯拒连，探针实测）。
口径验证（7/14、9/15 抽 147 槽位点 vs 库内实采）：中位差 0.030pp、60% ≤0.1pp——研究级可用。

槽位映射（TDX 5 分钟棒时间戳=棒末）：09:30→首棒 open、09:35→首棒 close、
10:00/10:30/11:00/11:30/13:30/14:00/14:30/15:00→同刻棒 close、13:00→11:30 棒（午休结转）。
前收=序列内前一交易日 15:00 棒 close。

写库：pctChange + pctChangeSrc='tdx_5min_backfill'（provenance fail-visible）。
幂等：只处理 pctChange 缺失行。回填不写 3/19 前与范围外。

用法：
  ./.venv/Scripts/python.exe -m backend.operations.backfill_slot_pctchange \
      [--start 2026-04-15] [--end 2026-06-30] [--apply] [--sleep 0.05]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

HOSTS_PATH = Path(r"D:\dragon-board\python-bridge\tdx_hosts.json")
SOURCE = "tdx_5min_backfill"
PAGES = (0, 800, 1600, 2400, 3200, 4000, 4800, 5600)
FLOOR = "2026-03-19"
SLOT_BAR = {"09:30": "first_open", "09:35": "first_close", "10:00": "10:00", "10:30": "10:30",
            "11:00": "11:00", "11:30": "11:30", "13:00": "11:30", "13:30": "13:30",
            "14:00": "14:00", "14:30": "14:30", "15:00": "15:00"}


def fetch_series(client: Any, code: str) -> dict[str, tuple[float, float]]:
    """5 分钟线全序列 {dt: (open, close)}，翻页至 FLOOR 或取尽。"""
    out: dict[str, tuple[float, float]] = {}
    for start in PAGES:
        df = client.bars(symbol=code, frequency=0, start=start, offset=800)
        if df is None or len(df) == 0:
            break
        for _, r in df.iterrows():
            dt = f"{int(r['year']):04d}-{int(r['month']):02d}-{int(r['day']):02d} {int(r['hour']):02d}:{int(r['minute']):02d}"
            out[dt] = (float(r["open"]), float(r["close"]))
        if min(out) < FLOOR:
            break
    return out


def slot_price(series: dict[str, tuple[float, float]], day: str, slot: str) -> float | None:
    """槽位价格（映射见模块 docstring）；缺棒返回 None。"""
    mode = SLOT_BAR.get(slot)
    if mode is None:
        return None
    daybars = {dt[11:]: v for dt, v in series.items() if dt.startswith(day)}
    if not daybars:
        return None
    if mode == "first_open":
        return daybars[min(daybars)][0]
    if mode == "first_close":
        return daybars[min(daybars)][1]
    return daybars.get(mode, (None, None))[1]


def prev_close_of(series: dict[str, tuple[float, float]], day: str) -> float | None:
    """前一交易日 15:00 棒 close（序列内自带，免额外日线调用）。"""
    day_keys = sorted({dt[:10] for dt in series})
    if day not in day_keys:
        return None
    i = day_keys.index(day)
    if i == 0:
        return None
    return series.get(f"{day_keys[i - 1]} 15:00", (None, None))[1]


def main():
    parser = argparse.ArgumentParser(description="槽位 pctChange 历史回填（TDX 5 分钟线）")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.05)
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from pymongo import UpdateOne

    db = get_runtime_mongodb_database()
    q = {"type": "half_hour", "tradingDate": {"$gte": args.start, "$lte": args.end},
         "$or": [{"pctChange": {"$exists": False}}, {"pctChange": None}]}
    rows = list(db["snapshot_stock_rows"].find(q, {"code": 1, "tradingDate": 1, "slotTime": 1}))
    if not rows:
        print("范围内无缺失行，退出")
        return
    by_code: dict[str, list[dict]] = {}
    for r in rows:
        by_code.setdefault(str(r.get("code")), []).append(r)
    print(f"[backfill] {args.start}~{args.end}: {len(rows)} 行 / {len(by_code)} 只代码（{'APPLY' if args.apply else 'DRY-RUN'}）")

    HOSTS = json.loads(HOSTS_PATH.read_text(encoding="utf-8"))["candidates"]
    client = None
    for h in HOSTS[:8]:
        try:
            client = Quotes_factory()(market="std", server=(h["ip"], int(h["port"])), timeout=6, bestip=False)
            if len(client.index_bars(symbol="999999", frequency=9, start=0, offset=10)) > 0:
                print(f"[backfill] TDX 节点 {h['ip']}")
                break
            client = None
        except Exception:
            client = None
    if client is None:
        print("[err] TDX 全节点不可用（fail-visible，不写库）")
        return

    ops: list = []
    done = failed_codes = 0
    filled = no_bar = no_prev = 0
    t0 = time.time()
    for n, (code, crows) in enumerate(sorted(by_code.items()), 1):
        try:
            series = fetch_series(client, code)
        except Exception:
            failed_codes += 1
            continue
        if series:
            for r in crows:
                day = str(r.get("tradingDate"))
                slot = str(r.get("slotTime"))
                price = slot_price(series, day, slot)
                if price is None:
                    no_bar += 1
                    continue
                pc = prev_close_of(series, day)
                if pc is None:
                    no_prev += 1
                    continue
                filled += 1
                if args.apply:
                    ops.append(UpdateOne({"_id": r["_id"]},
                                         {"$set": {"pctChange": round((price / pc - 1) * 100, 2),
                                                   "pctChangeSrc": SOURCE}}))
        if args.apply and len(ops) >= 2000:
            db["snapshot_stock_rows"].bulk_write(ops, ordered=False)
            ops = []
        done += 1
        if n % 200 == 0:
            rate = n / max(time.time() - t0, 1)
            print(f"  进度 {n}/{len(by_code)}（{rate:.1f} 只/秒，已计 {filled} 行）")
        time.sleep(args.sleep)
    if args.apply and ops:
        db["snapshot_stock_rows"].bulk_write(ops, ordered=False)
    print("FINAL:", {"rowsInRange": len(rows), "computable": filled,
                     "noBar": no_bar, "noPrevClose": no_prev,
                     "failedCodes": failed_codes, "applied": args.apply})


def Quotes_factory():
    from mootdx.quotes import Quotes
    return Quotes.factory


if __name__ == "__main__":
    main()
