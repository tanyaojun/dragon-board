# -*- coding: utf-8 -*-
"""C10 高峰兑现月度复验（镜像 deep_valley_revalidate，方案 ranktrend-c10-peak-exit-plan.md §4）。

信号（冻结 v1）：EOD 收盘 ≥75 高峰日 → 次日涨停池逐股 T+1 首槽进、T+3 收盘出，按 T+1 开盘缺口
三分组（<1% / 1~3% / ≥3%）累积读数——V3 强单调（<1% +3.2% / 1~3% +0.67% / ≥3% -3.55% 四市况全负）
是 T2「大高开兑现」的核心证据流；盘后链 advisory 步每日自动积累，晋升门镜像 C9（≥10 事件样本/
相对基线 ≥+1pp/连续 3 失效降级），激活前零交易路径。

对照口径：全期 T+1→T+3 池等权日均值（基线）。fail-visible：无高峰日/原料缺失如实标注。

用法：
  ./.venv/Scripts/python.exe -m backend.operations.peak_revalidate --month 2026-09 [--apply]
"""
from __future__ import annotations

import argparse
import re
import statistics as st
import time
from typing import Any

PEAK = 75.0  # 主锚=用户裁决 ≥75（方案 §2.1）；敏感层 ≥70 不入库
POOL_MIN = 30
_STRIP = re.compile(r"^(sh|sz|bj)")


def _strip(code: Any) -> str:
    return _STRIP.sub("", str(code or ""))


def _eod_scores(db: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    for d in db["hotlist_sentiment"].find(
            {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD"},
            {"tradingDate": 1, "emotionScore.score": 1}):
        es = d.get("emotionScore")
        if isinstance(es, dict) and isinstance(es.get("score"), (int, float)):
            out[str(d["tradingDate"])] = float(es["score"])
    return out


def _snap(db: Any, d: str, slots: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for r in db["snapshot_stock_rows"].find(
            {"type": "half_hour", "tradingDate": d, "slotTime": {"$in": slots},
             "pctChange": {"$exists": True, "$ne": None}}, {"code": 1, "pctChange": 1}):
        out.setdefault(str(r["code"]), float(r["pctChange"]))
    return out


def _entry_prices(db: Any, d: str) -> dict[str, float]:
    """T+1 入场价：09:35 可成交口径优先（与 C9 冻结协议统一），缺失回退 09:30。

    确定性槽解析（review P1-1）：逐槽独立查询按显式优先序取值，不依赖 $in 游标序
    （phase_stock_matrix.entry_snap 同款模式）；C9 工具 deep_valley_revalidate 仍为游标序，
    口径统一登记于方案 §7 A6，待用户点头后另改（一次一变量）。
    """
    by_slot = {s: _snap(db, d, [s]) for s in ("09:35", "09:30")}
    out: dict[str, float] = {}
    for code in set(by_slot["09:35"]) | set(by_slot["09:30"]):
        for s in ("09:35", "09:30"):
            if code in by_slot[s]:
                out[code] = by_slot[s][code]
                break
    return out


def _peak_population(db: Any, date: str) -> set[str]:
    """高峰日涨停池（jiuyan_action final 人口，与打标轨道同源）。"""
    pop = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, {"fields.stocks.code": 1})
    return {_strip(s.get("code")) for f in (pop or {}).get("fields") or []
            for s in f.get("stocks") or []}


def compute_peak_summary(month: str, samples: list[dict], baseline_mean: float | None) -> dict:
    """纯聚合：samples=[{date, eodScore, n, gapLt1, gap1to3, gapGe3}]（各组=逐股 T+1→T+3 收益%）。"""

    def agg(vals: list[float]) -> dict:
        return {"n": len(vals), "mean": round(st.mean(vals), 2) if vals else None,
                "win": sum(1 for v in vals if v > 0)}

    flat = {k: [v for s in samples for v in s.get(k) or []] for k in ("gapLt1", "gap1to3", "gapGe3")}
    ge3 = agg(flat["gapGe3"])
    total = sum(s.get("n") or 0 for s in samples)
    summary: dict[str, Any] = {
        "month": month, "peakDays": len(samples), "samples": total,
        "gapLt1": agg(flat["gapLt1"]), "gap1to3": agg(flat["gap1to3"]), "gapGe3": ge3,
        "baselineMean": baseline_mean,
        "edgeGe3VsBaseline": (round(baseline_mean - ge3["mean"], 2)
                              if baseline_mean is not None and ge3["mean"] is not None else None),
    }
    summary["noData"] = not samples
    summary["reason"] = None if samples else f"{month} 无高峰状态日（≥{PEAK}）"
    return summary


def revalidate_month(db: Any, month: str) -> dict[str, Any]:
    eod = _eod_scores(db)
    dates = sorted(eod)
    # 月度账本=当月高峰日（与 C9 同款月过滤；基线仍用全期对照）；月末 T+3 出窗截断显式登记
    deep_dates = [d for d in dates if d.startswith(month) and eod[d] >= PEAK]
    truncated = [d for d in deep_dates
                 if dates.index(d) + 3 >= len(dates)]  # review P1-2：月末截断留痕（C9 同款字段）
    samples = []
    population_missing: list[str] = []
    for d in deep_dates:
        i = dates.index(d)  # 全期轴下标（T+1/T+3 跨月取窗）；deep_dates 是月内过滤列表，勿用其枚举下标
        if i + 3 >= len(dates):
            continue  # 截断日不进样本，truncated 登记如上（fail-visible）
        t1, t3 = dates[i + 1], dates[i + 3]
        codes = _peak_population(db, d)
        if not codes:
            population_missing.append(d)  # review P2-2：人口缺失与「真涨停池空」可区分
        sin = _entry_prices(db, t1)
        sout = _snap(db, t3, ["15:00"])
        gap_all = _snap(db, t1, ["09:30"])
        groups: dict[str, list[float]] = {"gapLt1": [], "gap1to3": [], "gapGe3": []}
        n = 0
        gap_missing = 0
        for c in sorted(codes):
            if c not in sin or c not in sout:
                continue
            n += 1
            ret = round(sout[c] - sin[c], 2)
            gap = gap_all.get(c)
            if gap is None:
                gap_missing += 1  # review P2-1：缺开盘缺口的股计入 n 不入组，显式计数
                continue
            key = "gapLt1" if gap < 1 else ("gap1to3" if gap < 3 else "gapGe3")
            groups[key].append(ret)
        samples.append({"date": d, "eodScore": eod[d], "n": n, "gapMissing": gap_missing, **groups})
    # 基线：全期 T+1→T+3 池等权日均值（与 C9 同法）
    base = []
    for i in range(len(dates) - 3):
        a, b = _snap(db, dates[i + 1], ["09:30", "09:35"]), _snap(db, dates[i + 3], ["15:00"])
        common = set(a) & set(b)
        if len(common) >= POOL_MIN:
            base.append(round(st.mean(b[c] - a[c] for c in common), 2))
    baseline_mean = round(st.mean(base), 2) if base else None
    summary = compute_peak_summary(month, samples, baseline_mean)
    summary["truncatedPeakDays"] = truncated  # 月末跨月高峰日（T+3 出窗），fail-visible 留痕
    summary["populationMissing"] = population_missing
    return {"ok": True, "month": month, "summary": summary, "samples": samples,
            "noData": not samples, "reason": None if samples else f"{month} 无高峰状态日（≥{PEAK}）"}


def main():
    parser = argparse.ArgumentParser(description="C10 高峰兑现月度复验")
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--apply", action="store_true", help="写 phase_monitor kind=c10（幂等）")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    out = revalidate_month(db, args.month)
    s = out["summary"]
    print(f"== C10 月度复验 {args.month}（{'APPLY' if args.apply else 'DRY-RUN'}）==")
    print("summary:", {k: s[k] for k in ("peakDays", "samples", "baselineMean", "edgeGe3VsBaseline")})
    for k in ("gapLt1", "gap1to3", "gapGe3"):
        g = s[k]
        print(f"  {k}: n={g['n']} mean={g['mean']}% win={g['win']}/{g['n']}")
    for x in out["samples"]:
        print(f"  {x['date']} EOD={x['eodScore']} 池 {x['n']} 只｜大高开 {len(x['gapGe3'])} 只")
    if out["noData"]:
        print(f"  无高峰状态日（{out['reason']}）")
    if args.apply:
        # 无高峰日也写 noData 档（账本月份齐全，"当月无高峰"与"未跑"可区分；重跑幂等覆盖旧档）
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        # kind=c10 与 northstar/monthly/pulse/c9 同款集合判别键（board 读口按 kind 分流）
        db["phase_monitor"].update_one(
            {"_id": f"c10:{args.month}"},
            {"$set": {**out, "kind": "c10", "updatedAt": now}}, upsert=True)
        print(f"[apply] 已写 phase_monitor c10:{args.month}（样本 {s['samples']}）")


if __name__ == "__main__":
    main()
