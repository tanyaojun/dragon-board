# -*- coding: utf-8 -*-
"""7 月前快照行 open/preClose 历史回填（TDX 日线 + 行内派生，2026-10-06 用户令）。

范围：snapshot_stock_rows type=half_hour、tradingDate ≤ end-date，仅填缺失值（不覆盖非空）。

字段与来源（优先级）：
- preClose：① 行内派生（price+change→pctChange，round(price/(1+chg/100),4)——与
  snapshot_derivation/projection._derive_pre_close_from_price_change 生产规则逐字一致）；
  ② TDX 日线前收（上一根日线 close，不复权口径，除权日与交易所昨收有差，回退来源标记可辨）。
- open：TDX 日线当日 open（集合竞价开盘价，精确）。

红线遵守：open/preClose 无任何计算链消费方（ranktrend 引擎/回测/golden 不读），
回填不触 golden；amount/high/low/limitUpPrice/pctChange 等引擎/评分输入字段**有意不补**
（会打漂 golden 与已落库评分口径，待用户单独裁决）。备份不建集合（红线：备份只走
mongodump 归档；本工具只填 NULL，原值=null 可平凡复原），写 migration_audit 审计。

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

BACKFILL_VERSION = "snapshot_row_daily_prices_v1"
HOSTS_PATH = Path(r"D:\dragon-board\python-bridge\tdx_hosts.json")
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "backups" / "row-price-backfill"
SOURCE_DERIVE = "row_derive_change_v1"
SOURCE_TDX = "tdx_daily_v1"
SLEEP = 0.22


def _finite(value) -> float | None:
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
    """{code: {"by_date": {date: {"open","close"}}, "prev_close": {date: 昨收}}}，带断点缓存。"""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ckpt_path = CACHE_DIR / f"_daily_ckpt_{end_date}.json"
    ckpt: dict[str, dict] = {}
    if ckpt_path.exists():
        ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
        print(f"[cache] 断点续跑：已有 {len(ckpt)}/{len(codes)} 代码")
    failed: dict[str, str] = {}
    todo = [c for c in codes if c not in ckpt]
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
            rows.append((date, _finite(r.get("open")), _finite(r.get("close"))))
        rows = [x for x in rows if x[1] and x[2]]
        rows.sort()
        by_date = {d: {"open": o, "close": c} for d, o, c in rows}
        prev_close = {rows[k][0]: rows[k - 1][2] for k in range(1, len(rows))}
        ckpt[code] = {"by_date": by_date, "prev_close": prev_close}
        if i % 100 == 0:
            ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False), encoding="utf-8")
            el = time.time() - t0
            print(f"[prog] {i}/{len(todo)} elapsed={el:.0f}s failed={len(failed)}")
    ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False), encoding="utf-8")
    if failed:
        (CACHE_DIR / f"_daily_failed_{end_date}.json").write_text(
            json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[披露] TDX 拉取失败 {len(failed)} 代码（清单已落缓存目录，对应行保持缺失 fail-visible）")
    return ckpt


def main():
    parser = argparse.ArgumentParser(description="7 月前快照行 open/preClose 回填")
    parser.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    parser.add_argument("--end-date", default="2026-06-30")
    parser.add_argument("--start-date", default="2026-01-01")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    coll = db["snapshot_stock_rows"]
    scope = {"datasetId": "dragonboard_live", "type": "half_hour",
             "tradingDate": {"$gte": args.start_date, "$lte": args.end_date}}
    rows = list(coll.find(scope, {"code": 1, "name": 1, "tradingDate": 1, "price": 1,
                                  "change": 1, "pctChange": 1, "open": 1, "preClose": 1}))
    print(f"范围行数：{len(rows)}（{args.start_date} → {args.end_date}，type=half_hour）")

    codes = sorted({str(r.get("code")) for r in rows if r.get("code")})
    print(f"唯一代码 {len(codes)}，拉取 TDX 日线 …")
    client = get_client()
    daily = fetch_daily_map(client, codes, args.end_date)

    plan: list[dict] = []
    stats = {"open_tdx": 0, "pre_derive": 0, "pre_tdx": 0, "skip_no_tdx": 0}
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
            else:
                stats["skip_no_tdx"] += 1
        if _finite(r.get("preClose")) is None:
            pre, src = derive_pre_close(r)
            tdx_pre = prev_close_map.get(date)
            if pre is not None and tdx_pre:
                ok = abs(pre - tdx_pre) / tdx_pre < 0.005
                mism[0 if ok else 1] += 1
            if pre is None and tdx_pre:
                pre, src = tdx_pre, SOURCE_TDX
            if pre:
                fills["preClose"] = pre
                sources["preClose"] = src or ""
                stats["pre_derive" if src == SOURCE_DERIVE else "pre_tdx"] += 1
        if not fills:
            continue
        if fills:
            plan.append({"_id": r["_id"], "fills": fills, "sources": sources})
    stats["open_tdx"] = sum(1 for p in plan if "open" in p["fills"])
    total_mism = sum(mism)
    print(f"交叉核对（行内派生 vs TDX 前收，±0.5% 内视为一致）：一致 {mism[0]} / 不一致 {mism[1]}"
          f"（不一致=除权日或取整差，行内派生优先，符合交易所口径）")
    print(f"回填计划：{len(plan)} 行 ｜ open←TDX {stats['open_tdx']} ｜ "
          f"preClose←行内派生 {stats['pre_derive']} / ←TDX {stats['pre_tdx']} ｜ 无 TDX 证据跳过 {stats['skip_no_tdx']}")

    if not args.apply:
        print("dry-run 未写库；确认后加 --apply 执行")
        return
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    for start in range(0, len(plan), 1000):
        batch = plan[start:start + 1000]
        ops = [UpdateOne({"_id": p["_id"], "open": None, "preClose": None},
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
        "plannedRows": len(plan), "updatedRows": updated, "stats": stats, "crossCheck": {"match": mism[0], "mismatch": mism[1]},
    })
    print(f"已写库 {updated} 行（backfillMeta.version={BACKFILL_VERSION}）；审计 {audit_id}")


if __name__ == "__main__":
    main()
