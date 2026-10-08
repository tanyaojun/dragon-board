# -*- coding: utf-8 -*-
"""两市额同期比 vsSamePct 只记录不评分（2026-10-06 用户裁决，评估报告
`docs/hotlist-jev/amountvs-same-dimension-assessment.md` §四建议 2）。

职责：①TDX 综指日线（999999+399106）同步 market_daily_amount 参考集合（增量补新交易日）；
②对全部相邻交易日对计算 vsSamePct=（今额/昨额−1）×100 与设计曲线 sub（**只存不评分**——
第八评分维已于 2026-10-08 永久退役（研究轮出口 b，amountvs-same-recalibration-study-20261008.md），
本字段仅作量能原料存档对照）。

写库目标=market_daily_amount 文档新增字段：`vsSamePct`（百分点）、`amountVsSameSubDesign`
（**设计曲线未校准**，命名自证）、`vsSamePctComputedAt`。幂等全量重算，fail-visible。

用法（Git Bash）：
  cd quant-board
  ./.venv/Scripts/python.exe -m backend.operations.record_amount_vs_same            # dry-run
  ./.venv/Scripts/python.exe -m backend.operations.record_amount_vs_same --apply
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

HOSTS_PATH = Path(r"D:\dragon-board\python-bridge\tdx_hosts.json")
SOURCE = "tdx_index_kline_backfill"
# 设计校准曲线（源曲线 emotion_score._CALIB["amountVsSame"] 已随 2026-10-08 永久退役删除；
# 本副本仅服务 amountVsSameSubDesign 对照字段，不再有单一事实源约束——曲线失准恰是退役理由之一）
CURVE_DESIGN = [(-80, 0), (-30, 25), (0, 50), (30, 80), (80, 100)]
INDEX_SYMBOLS = ("999999", "399106")
SLEEP = 0.22


def _interp(points: list[tuple[float, float]], value: float) -> float:
    if value <= points[0][0]:
        return float(points[0][1])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            ratio = (value - x0) / (x1 - x0) if x1 > x0 else 0.0
            return y0 + (y1 - y0) * ratio
    return float(points[-1][1])


def sync_reference_from_tdx(db, fetch_days: int = 10) -> dict:
    """TDX 综指日线增量同步参考集合（收盘后当日日线已定盘）。"""
    from mootdx.quotes import Quotes

    hosts = json.loads(HOSTS_PATH.read_text(encoding="utf-8"))["candidates"]
    last: Exception | None = None
    for h in hosts:
        ip, port = h.get("ip"), int(h.get("port") or 7709)
        try:
            client = Quotes.factory(market="std", server=(ip, port), timeout=6, bestip=False)
            sh = client.index_bars(symbol=INDEX_SYMBOLS[0], frequency=9, start=0, offset=fetch_days)
            sz = client.index_bars(symbol=INDEX_SYMBOLS[1], frequency=9, start=0, offset=fetch_days)
            if sh is None or sz is None or len(sh) == 0 or len(sz) == 0:
                last = RuntimeError(f"{ip} 空 K 线")
                continue

            def to_map(df) -> dict[str, float]:
                return {f"{int(r['year']):04d}-{int(r['month']):02d}-{int(r['day']):02d}": float(r["amount"])
                        for _, r in df.iterrows()}

            m1, m2 = to_map(sh), to_map(sz)
            now = datetime.now(timezone.utc).isoformat()
            n = 0
            for date in sorted(set(m1) & set(m2)):
                db["market_daily_amount"].update_one(
                    {"_id": date},
                    {"$set": {"totalAmount": m1[date] + m2[date]},
                     "$setOnInsert": {"source": SOURCE, "fetchedAt": now}},
                    upsert=True)
                n += 1
            return {"ok": True, "syncedDates": n, "node": f"{ip}:{port}"}
        except Exception as exc:  # 换下一节点
            last = exc
            time.sleep(SLEEP)
    return {"ok": False, "error": f"全部 TDX 节点不可用: {last}"}


def record_vs_same(db) -> dict:
    """全量重算相邻交易日对的 vsSamePct+设计 sub（幂等，只存不评分）。

    邻接守卫：仅当日历间隔 ≤10 天（覆盖春节/国庆最长连休）才视为「昨日」——参考集合
    若缺某交易日（TDX 断档），跨缺口对比会把 T−2 当 T−1（假同比），必须断链 fail-visible。
    """
    from datetime import date as _date

    ref = {d["_id"]: d.get("totalAmount")
           for d in db["market_daily_amount"].find({}, {"totalAmount": 1})
           if isinstance(d.get("totalAmount"), (int, float)) and not isinstance(d["totalAmount"], bool)}
    dates = sorted(ref)
    now = datetime.now(timezone.utc).isoformat()
    recorded = 0
    skipped_gaps = 0
    latest: dict | None = None
    for i in range(1, len(dates)):
        t, p = dates[i], dates[i - 1]
        gap = (_date.fromisoformat(t) - _date.fromisoformat(p)).days
        if gap > 10:
            skipped_gaps += 1
            continue
        vss = (ref[t] / ref[p] - 1) * 100
        sub = round(_interp(CURVE_DESIGN, vss), 1)
        db["market_daily_amount"].update_one(
            {"_id": t},
            {"$set": {"vsSamePct": round(vss, 4), "amountVsSameSubDesign": sub,
                      "vsSamePctComputedAt": now}})
        recorded += 1
        latest = {"date": t, "vsSamePct": round(vss, 2), "amountVsSameSubDesign": sub}
    return {"ok": True, "datesWithAmount": len(dates), "recordedPairs": recorded,
            "skippedGaps": skipped_gaps, "latest": latest}


def main():
    parser = argparse.ArgumentParser(description="两市额同期比 vsSamePct 只记录不评分")
    parser.add_argument("--apply", action="store_true", help="实际写库（默认 dry-run）")
    parser.add_argument("--skip-sync", action="store_true", help="跳过 TDX 同步（仅重算记录）")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    sync = {"ok": True, "skipped": True, "reason": "skip_sync"} if args.skip_sync \
        else sync_reference_from_tdx(db)
    print(f"[sync] {sync}")
    result = record_vs_same(db)
    result["sync"] = sync
    print("[record]", json.dumps(result, ensure_ascii=False))
    if not args.apply:
        print("dry-run 未写库；确认后加 --apply 执行")


if __name__ == "__main__":
    main()
