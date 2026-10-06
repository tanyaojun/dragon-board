# -*- coding: utf-8 -*-
"""7 月前快照行 open/preClose/high/low/amount/pctChange 历史回填（TDX 日线+行内派生）。

v1（2026-10-06，799bee9b）：open/preClose。
v2（2026-10-06 用户裁决「补计算输入」）：增加 high/low（TDX as-traded，引擎 ATR 回退链输入）、
amount←turnover（双字段 12 万行逐行全等实证）、pctChange←price+preClose 派生（全精度）。
写库后由 snapshot_field_backfill 级联派生 limitUp/DownPrice+amplitude（既有工具）。

红线遵守：写库前已完成消费方扫描并经用户裁决（amount=引擎量价因子、high/low=ATR 回退链、
pctChange=breadth 评分输入——golden 与 113 日情绪分同批重生成，见同日提交）。只填缺失值
（分字段 null 守卫，幂等），backfillMeta 来源标记 fail-visible，不建备份集合（只填 NULL 可平凡
复原），migration_audit 留痕。

用法（Git Bash）：
  cd quant-board
  ./.venv/Scripts/python.exe -m backend.operations.backfill_row_daily_prices            # dry-run
  ./.venv/Scripts/python.exe -m backend.operations.backfill_row_daily_prices --apply
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pymongo import UpdateOne

BACKFILL_VERSION = "snapshot_row_daily_prices_v2"
HOSTS_PATH = Path(r"D:\dragon-board\python-bridge\tdx_hosts.json")
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "backups" / "row-price-backfill"
SOURCE_DERIVE = "row_derive_change_v1"
SOURCE_TDX = "tdx_daily_v1"
SLEEP = 0.22


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def derive_pre_close(row: dict) -> tuple[float | None, str | None]:
    """行内派生昨收（与投影层生产规则一致）；无证据返回 (None, None)。"""
    price = _finite(row.get("price"))
    chg = _finite(row.get("change"))
    if chg is None:
        chg = _finite(row.get("pctChange"))
    if price is None or price <= 0 or chg is None or chg == -100:
        return None, None
    return round(price / (1 + chg / 100), 4), SOURCE_DERIVE


def get_client():
    from mootdx.quotes import Quotes

    hosts = json.loads(HOSTS_PATH.read_text(encoding="utf-8"))["candidates"]
    last: Exception | None = None
    for h in hosts:
        ip, port = h.get("ip"), int(h.get("port") or 7709)
        try:
            client = Quotes.factory(market="std", server=(ip, port), timeout=6, bestip=False)
            probe = client.bars(symbol="000001", frequency=9, start=0, offset=5)
            if probe is not None and len(probe) > 0:
                print(f"[tdx] 节点 {ip}:{port} ({h.get('name')})")
                return client
            last = RuntimeError(f"{ip} 空返回")
        except Exception as exc:
            last = exc
            time.sleep(SLEEP)
    raise RuntimeError(f"无可用 TDX 节点: {last}")


def fetch_daily_map(client, codes: list[str], end_date: str) -> dict[str, dict]:
    """{code: {"by_date": {date: {"open","close","high","low"}}, "prev_close": {date: 昨收}}}，带断点缓存。

    缓存键 _daily_ckpt_<end>_v2（含 high/low；v1 缓存无此两列）。
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ckpt_path = CACHE_DIR / f"_daily_ckpt_{end_date}_v2.json"
    ckpt: dict[str, dict] = {}
    if ckpt_path.exists():
        ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
        print(f"[cache] 断点续跑：已有 {len(ckpt)}/{len(codes)} 代码")
    failed_path = CACHE_DIR / f"_daily_failed_{end_date}_v2.json"
    failed: dict[str, str] = {}
    if failed_path.exists():
        failed = json.loads(failed_path.read_text(encoding="utf-8"))
    todo = [c for c in codes if c not in ckpt and c not in failed]
    err_streak = 0
    t0 = time.time()
    for i, code in enumerate(todo, 1):
        try:
            df = client.bars(symbol=code, frequency=9, start=0, offset=160)
        except Exception as exc:
            failed[code] = f"exc:{type(exc).__name__}"
            err_streak += 1
            if err_streak >= 8:
                client = get_client()
                err_streak = 0
            time.sleep(SLEEP)
            continue
        err_streak = 0
        time.sleep(SLEEP)
        if df is None or len(df) == 0:
            failed[code] = "empty"
            continue
        rows = []
        for _, r in df.iterrows():
            date = f"{int(r['year']):04d}-{int(r['month']):02d}-{int(r['day']):02d}"
            rows.append((date, _finite(r.get("open")), _finite(r.get("close")),
                         _finite(r.get("high")), _finite(r.get("low"))))
        rows = [x for x in rows if x[1] and x[2]]
        rows.sort()
        by_date = {d: {"open": o, "close": c, "high": h, "low": l} for d, o, c, h, l in rows}
        prev_close = {rows[k][0]: rows[k - 1][2] for k in range(1, len(rows))}
        ckpt[code] = {"by_date": by_date, "prev_close": prev_close}
        if i % 100 == 0:
            ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False), encoding="utf-8")
            print(f"[prog] {i}/{len(todo)} elapsed={time.time() - t0:.0f}s failed={len(failed)}", flush=True)
    ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False), encoding="utf-8")
    failed_path.write_text(json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")
    if failed:
        print(f"[披露] TDX 拉取失败 {len(failed)} 代码（清单 {failed_path}，对应行保持缺失 fail-visible）")
    return ckpt


def main():
    parser = argparse.ArgumentParser(description="7 月前快照行 open/preClose/high/low/amount/pctChange 回填")
    parser.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    parser.add_argument("--end-date", default="2026-06-30")
    parser.add_argument("--start-date", default="2026-01-01")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    coll = db["snapshot_stock_rows"]
    scope = {"datasetId": "dragonboard_live", "type": "half_hour",
             "tradingDate": {"$gte": args.start_date, "$lte": args.end_date}}
    rows = list(coll.find(scope, {"code": 1, "tradingDate": 1, "price": 1, "change": 1, "pctChange": 1,
                                  "open": 1, "preClose": 1, "high": 1, "low": 1,
                                  "amount": 1, "turnover": 1}))
    print(f"范围行数：{len(rows)}（{args.start_date} → {args.end_date}，type=half_hour）")

    codes = sorted({str(r.get("code")) for r in rows if r.get("code")})
    print(f"唯一代码 {len(codes)}，拉取 TDX 日线 …")
    client = get_client()
    daily = fetch_daily_map(client, codes, args.end_date)

    plan: list[dict] = []
    stats = {"open_tdx": 0, "pre_derive": 0, "pre_tdx": 0, "highlow_tdx": 0,
             "amount_turnover": 0, "pct_derive": 0}
    mism = [0, 0]  # [一致, 不一致]（行内派生 vs TDX 前收 交叉核对）
    for r in rows:
        code = str(r.get("code") or "")
        date = str(r.get("tradingDate") or "")
        entry = daily.get(code) or {}
        by_date = entry.get("by_date") or {}
        prev_close_map = entry.get("prev_close") or {}
        fills: dict[str, float] = {}
        sources: dict[str, str] = {}
        if _finite(r.get("open")) is None:
            o = (by_date.get(date) or {}).get("open")
            if o:
                fills["open"] = o
                sources["open"] = SOURCE_TDX
        if _finite(r.get("preClose")) is None:
            pre, src = derive_pre_close(r)
            tdx_pre = prev_close_map.get(date)
            if pre is not None and tdx_pre:
                mism[0 if abs(pre - tdx_pre) / tdx_pre < 0.005 else 1] += 1
            if pre is None and tdx_pre:
                pre, src = tdx_pre, SOURCE_TDX
            if pre:
                fills["preClose"] = pre
                sources["preClose"] = src or ""
                stats["pre_derive" if src == SOURCE_DERIVE else "pre_tdx"] += 1
        if _finite(r.get("high")) is None or _finite(r.get("low")) is None:
            bar = by_date.get(date) or {}
            h, l = bar.get("high"), bar.get("low")
            if h and l and h >= l:
                fills["high"], fills["low"] = h, l
                sources["high"] = sources["low"] = SOURCE_TDX
                stats["highlow_tdx"] += 1
        if _finite(r.get("amount")) is None:
            tov = _finite(r.get("turnover"))
            if tov and tov > 0:
                fills["amount"] = tov
                sources["amount"] = "row_turnover_equal_v1"
                stats["amount_turnover"] += 1
        if _finite(r.get("pctChange")) is None:
            price = _finite(r.get("price"))
            pre = _finite(r.get("preClose")) or fills.get("preClose")
            if price and price > 0 and pre and pre > 0:
                fills["pctChange"] = round((price / pre - 1) * 100, 6)
                sources["pctChange"] = "row_derive_pre_close_v1"
                stats["pct_derive"] += 1
        if not fills:
            continue
        plan.append({"_id": r["_id"], "fills": fills, "sources": sources})

    print(f"交叉核对（行内派生 vs TDX 前收，±0.5% 内视为一致）：一致 {mism[0]} / 不一致 {mism[1]}"
          f"（不一致=除权日，行内派生=交易所口径优先）")
    print(f"回填计划：{len(plan)} 行 ｜ open←TDX {stats['open_tdx']} ｜ "
          f"preClose←派生 {stats['pre_derive']}/←TDX {stats['pre_tdx']} ｜ high/low←TDX {stats['highlow_tdx']} ｜ "
          f"amount←turnover {stats['amount_turnover']} ｜ pctChange←派生 {stats['pct_derive']}")

    if not args.apply:
        print("dry-run 未写库；确认后加 --apply 执行")
        return
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    for start in range(0, len(plan), 1000):
        batch = plan[start:start + 1000]
        ops = [UpdateOne({"_id": p["_id"],
                          "$and": [{f: None} for f in p["fills"]]},
                         {"$set": {**p["fills"],
                                   "backfillMeta": {"version": BACKFILL_VERSION, "repairedAt": now,
                                                    "fields": sorted(p["fills"]),
                                                    "sources": p["sources"]}}})
               for p in batch]
        bulk = coll.bulk_write(ops, ordered=False)
        updated += int(bulk.modified_count)
    audit_id = f"row-daily-prices-backfill-{uuid4().hex}"
    db["migration_audit"].insert_one({
        "auditId": audit_id, "opType": "snapshot_row_daily_prices_backfill",
        "datasetId": "dragonboard_live", "version": BACKFILL_VERSION, "createdAt": now,
        "startDate": args.start_date, "endDate": args.end_date,
        "plannedRows": len(plan), "updatedRows": updated, "stats": stats,
        "crossCheck": {"match": mism[0], "mismatch": mism[1]},
    })
    print(f"已写库 {updated} 行（backfillMeta.version={BACKFILL_VERSION}）；审计 {audit_id}")


if __name__ == "__main__":
    main()
