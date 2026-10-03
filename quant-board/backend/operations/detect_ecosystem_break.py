# -*- coding: utf-8 -*-
"""涨停生态断层检测（§十三，2026-10-03）：冰点语义规则化，纯数据零 jev token。

用户语义锚（9/4 教学）：冰点=涨停生态断层日——①涨停家数掉出常态带（<近20日 P20）；
②池内涨跌均衡（0.8≤涨跌比≤1.25，没人买也没人卖）；③量能非杀跌（当日成交额较昨日不缩）。
三特征齐=断层日（反弹在即）；①+跌停堆积/单边杀跌=退潮日，不得判冰点。全月预期 1-2 次。

用法：
  ./.venv/Scripts/python.exe -m backend.operations.detect_ecosystem_break --month 2026-09 [--apply]
--apply 时写 hotlist_jev_sentiment EOD 文档 diagnostics.ecosystemBreak（幂等 upsert）。
"""
from __future__ import annotations

import argparse
import time
from typing import Any

BALANCED_LOW, BALANCED_HIGH = 0.8, 1.25


def _trading_dates(db: Any, month: str) -> list[str]:
    rows = db["snapshot_stock_rows"].find(
        {"type": "half_hour", "tradingDate": {"$gte": f"{month}-01", "$lte": f"{month}-31"}},
        {"tradingDate": 1})
    return sorted({str(r["tradingDate"]) for r in rows if r.get("tradingDate")})


def _zt_count(db: Any, date: str) -> int | None:
    f = db["snapshot_frames"].find_one(
        {"type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"limitSummary.zhaban.ztCount": 1})
    zt = ((f or {}).get("limitSummary") or {}).get("zhaban", {}).get("ztCount")
    return zt if isinstance(zt, (int, float)) and zt > 0 else None


def _advdec_ratio(db: Any, date: str) -> float | None:
    up = down = 0
    for r in db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": date, "slotTime": "15:00",
             "pctChange": {"$exists": True, "$ne": None}}, {"pctChange": 1}):
        pc = r.get("pctChange")
        if not isinstance(pc, (int, float)):
            continue
        if pc > 0.1:
            up += 1
        elif pc < -0.1:
            down += 1
    return round(up / max(down, 1), 2) if (up or down) else None


def _amount_yi(db: Any, date: str) -> float | None:
    """当日两市成交额（亿）——优先情绪文档回填值，次取帧 indices（live 帧自带）。"""
    d = db["hotlist_jev_sentiment"].find_one(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "kind": "slot",
         "slotTime": "15:00", "tradingDate": date},
        {"evidenceRaw.totalAmount": 1})
    a = ((d or {}).get("evidenceRaw") or {}).get("totalAmount", {}).get("amount")
    if isinstance(a, (int, float)) and a > 0:
        return round(a / 1e8, 1)
    f = db["snapshot_frames"].find_one(
        {"type": "half_hour", "tradingDate": date, "slotTime": "15:00"},
        {"indices.totalAmount": 1})
    a = ((f or {}).get("indices") or {}).get("totalAmount", {}).get("amount")
    return round(a / 1e8, 1) if isinstance(a, (int, float)) and a > 0 else None


def detect_month(db: Any, month: str) -> list[dict[str, Any]]:
    """月内逐日三特征判定；返回明细（含证据与未触发原因），fail-visible 缺料日如实标注。"""
    dates = _trading_dates(db, month)
    zt_series: list[tuple[str, int]] = []
    for d in dates:
        zt = _zt_count(db, d)
        if zt is not None:
            zt_series.append((d, zt))
    idx = {d: i for i, (d, _) in enumerate(zt_series)}
    out: list[dict[str, Any]] = []
    for d, zt in zt_series:
        i = idx[d]
        hist = [z for dd, z in zt_series[:i]]
        p20 = sorted(hist)[max(0, int(len(hist) * 0.2) - 1)] if hist else None
        ratio = _advdec_ratio(db, d)
        amount = _amount_yi(db, d)
        prev_amount = _amount_yi(db, zt_series[i - 1][0]) if i > 0 else None
        breakout = isinstance(p20, int) and zt < p20
        balanced = isinstance(ratio, float) and BALANCED_LOW <= ratio <= BALANCED_HIGH
        amount_up = (isinstance(amount, (int, float)) and isinstance(prev_amount, (int, float))
                     and amount >= prev_amount)
        is_break = bool(breakout and balanced and amount_up)
        why = []
        if not breakout:
            why.append(f"涨停{zt}未跌破常态带P20={p20}")
        if not balanced:
            why.append(f"涨跌比{ratio}非均衡")
        if not isinstance(amount, (int, float)) or not isinstance(prev_amount, (int, float)):
            why.append("量能缺失")
        elif not amount_up:
            why.append(f"量能缩（{amount}亿 vs 昨{prev_amount}亿）")
        out.append({"date": d, "ztCount": zt, "p20": p20, "advDecRatio": ratio,
                    "amountYi": amount, "prevAmountYi": prev_amount,
                    "breakout": breakout, "balanced": balanced, "amountUp": amount_up,
                    "ecosystemBreak": is_break,
                    "reason": "断层日（反弹在即）" if is_break else "；".join(why) or ""})
    return out


def main():
    parser = argparse.ArgumentParser(description="涨停生态断层检测（§十三）")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--apply", action="store_true", help="写 EOD 文档 diagnostics.ecosystemBreak")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    rows = detect_month(db, args.month)
    breaks = [r for r in rows if r["ecosystemBreak"]]
    print(f"== {args.month} 涨停生态断层检测（{'APPLY' if args.apply else 'DRY-RUN'}）==")
    for r in rows:
        mark = "🔴 断层日" if r["ecosystemBreak"] else ""
        print(f"  {r['date']} 涨停{r['ztCount']:>3}（P20={r['p20']}）涨跌比{r['advDecRatio']}"
              f" 量能{r['amountYi']}亿（昨{r['prevAmountYi']}亿） {mark} {r['reason']}")
    print(f"断层日: {[r['date'] for r in breaks] or '无'}")
    if args.apply and breaks:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        n = 0
        for r in breaks:
            res = db["hotlist_jev_sentiment"].update_one(
                {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
                 "tradingDate": r["date"], "kind": "eod"},
                {"$set": {"diagnostics.ecosystemBreak": {
                    "isBreak": True, "ztCount": r["ztCount"], "p20": r["p20"],
                    "advDecRatio": r["advDecRatio"], "amountYi": r["amountYi"],
                    "prevAmountYi": r["prevAmountYi"], "detectedAt": now,
                    "source": "detect_ecosystem_break"}}})
            n += res.modified_count
        print(f"[apply] 已写 {n} 个 jev EOD 文档 diagnostics.ecosystemBreak")


if __name__ == "__main__":
    main()
