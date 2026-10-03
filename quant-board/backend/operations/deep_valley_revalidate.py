# -*- coding: utf-8 -*-
"""C9 深谷状态月度复验（§十四/position-plan §8，2026-10-03 协议冻结）。

信号（冻结）：EOD 收盘 <25/<30 深谷状态 → 出手窗 T+1 开盘进、T+3 收盘出。
月度复验产出：当月深谷状态日清单 + 3 日内 EOD 反弹 + 池等权代理收益（T+1/T+3 两槽交集
pctChange 差均值）→ phase_monitor kind=c9（_id=c9:{date}，幂等 upsert）。

对照口径：当月全部可用交易代理日均值（基线）。fail-visible：无深谷日/槽位数据缺失如实标注。

用法：
  ./.venv/Scripts/python.exe -m backend.operations.deep_valley_revalidate --month 2026-09 [--apply]
"""
from __future__ import annotations

import argparse
import statistics as st
import time
from typing import Any

DEEP = 25.0
DEEP_WIDE = 30.0
POOL_MIN = 30


def _eod_scores(db: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for d in db["hotlist_sentiment"].find(
            {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD"},
            {"tradingDate": 1, "emotionScore.score": 1}):
        es = d.get("emotionScore")
        if isinstance(es, dict) and isinstance(es.get("score"), (int, float)):
            out[str(d["tradingDate"])] = float(es["score"])
    return out


def _pool_ret(db: Any, d_in: str, d_out: str) -> tuple[float | None, int]:
    """进场=T+1 早盘首槽（09:35/09:30），出场=T+3 收盘 15:00（协议：T+1 开盘进、T+3 收盘出）。"""
    def snap(d: str, slots: list[str]) -> dict[str, float]:
        return {r["code"]: r["pctChange"] for r in db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": d,
             "slotTime": {"$in": slots},
             "pctChange": {"$exists": True, "$ne": None}}, {"code": 1, "pctChange": 1})}
    sin, sout = snap(d_in, ["09:35", "09:30"]), snap(d_out, ["15:00"])
    common = set(sin) & set(sout)
    if len(common) < POOL_MIN:
        return None, len(common)
    return round(st.mean(sout[c] - sin[c] for c in common), 2), len(common)


def revalidate_month(db: Any, month: str) -> dict[str, Any]:
    eod = _eod_scores(db)
    dates = sorted(d for d in eod if d.startswith(month))
    deep_days = [d for d in dates if eod[d] < DEEP_WIDE and dates.index(d) + 3 < len(dates)]
    samples = []
    for d in deep_days:
        i = dates.index(d)
        fut = dates[i + 1:i + 4]
        peak = max(eod[x] for x in fut)
        ret, pool_n = _pool_ret(db, fut[0], fut[-1])
        samples.append({
            "date": d, "eodScore": eod[d],
            "rebound3d": round(peak - eod[d], 1),
            "rebound3dHit": bool(peak - eod[d] >= 15),
            "poolRetPct": ret, "poolN": pool_n,
        })
    base = []
    for i, d in enumerate(dates):
        if i + 3 >= len(dates):
            continue
        ret, _ = _pool_ret(db, dates[i + 1], dates[i + 3])
        if ret is not None:
            base.append(ret)
    rets = [s["poolRetPct"] for s in samples if s["poolRetPct"] is not None]
    summary = {
        "month": month,
        "deepSamples": len(samples),
        "reboundHit": f"{sum(1 for s in samples if s['rebound3dHit'])}/{len(samples)}" if samples else "0/0",
        "poolMean": round(st.mean(rets), 2) if rets else None,
        "baselineMean": round(st.mean(base), 2) if base else None,
        "edge": round(st.mean(rets) - st.mean(base), 2) if rets and base else None,
    }
    return {"ok": True, "month": month, "summary": summary, "samples": samples,
            "noData": not samples, "reason": None if samples else f"{month} 无深谷状态日（<30）"}


def main():
    parser = argparse.ArgumentParser(description="C9 深谷状态月度复验")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--apply", action="store_true", help="写 phase_monitor kind=c9（幂等）")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    out = revalidate_month(db, args.month)
    print(f"== C9 月度复验 {args.month}（{'APPLY' if args.apply else 'DRY-RUN'}）==")
    print("summary:", out["summary"])
    for s in out["samples"]:
        print(f"  {s['date']} EOD={s['eodScore']} 3日反弹 +{s['rebound3d']}（{'✓' if s['rebound3dHit'] else '✗'}）"
              f" 代理收益 {s['poolRetPct']}%（池 {s['poolN']}）")
    if out["noData"]:
        print(f"  无深谷状态日（{out['reason']}）")
    if args.apply and out["samples"]:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        db["phase_monitor"].update_one(
            {"_id": f"c9:{args.month}"},
            {"$set": {**out, "updatedAt": now}}, upsert=True)
        print(f"[apply] 已写 phase_monitor c9:{args.month}")


if __name__ == "__main__":
    main()
