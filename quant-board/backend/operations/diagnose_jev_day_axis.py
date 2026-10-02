# -*- coding: utf-8 -*-
"""SP5 T1/T2 诊断：jev 日级两轴（温度=机会轴 / 拥挤=风险轴）标定与证据门。

按轴配读数（预登记 2026-10-01，见 ranktrend-position-sp5-plan.md §5a）：
  温度轴（收益题）：主读数 = 帧级 H1（下一帧池收益，复用 T-jev2 框架）
  拥挤轴（回撤题）：主读数 = 帧级 fwdWorst（当日后续任意帧最差池收益）
as-of：前日 eod 为主（hotlist_jev_sentiment kind=eod scores.day_temperature/day_crowding）；
  同槽拥挤降为敏感性重测（修正 T-jev2 用 H1 收益题考风险轴的读数错配）。
分带：全窗样本四分位冻结（禁抄规则四带；禁按月重标——Simpson 纪律）。
门：≥2 月同向且月内 Mann-Whitney p<0.05；反向显著 = REVERSE 只登记观察不立载体。
统计工具复用 backend.operations.diagnose_jev_temp_crowding（Mann-Whitney/Spearman/四分位/帧价格）。

产物：
  data/reports/phase-monitor/jev-day-axis-calibration.json  （T1 标定）
  data/reports/phase-monitor/jev-day-axis-evidence.json     （T2 证据门）
只读：不写库、不调 API、不碰引擎。
"""
from __future__ import annotations

import gzip
import json
import math
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pymongo import MongoClient

from backend.operations.diagnose_jev_temp_crowding import (
    frame_prices,
    mannwhitney_u,
    quartiles,
    spearman,
)

FRAMES = Path("data/reports/b-202610/exit-frames-dragonboard_live-half_hour-20260327-20260930.json.gz")
BASELINE_TRADES = Path("data/reports/b-202610/t6-runs-formal/1-summary.json")
OUT_CAL = Path("data/reports/phase-monitor/jev-day-axis-calibration.json")
OUT_EVID = Path("data/reports/phase-monitor/jev-day-axis-evidence.json")
MIN_SHARED_POOL = 5
MIN_SHARED_TOP = 3
MONTH_MIN_N = 12
GATE_MONTHS = 2
GATE_P = 0.05


# ---------- 纯函数（tests/operations/test_diagnose_jev_day_axis.py 覆盖） ----------

def pool_ret(prev: dict[str, float], cur: dict[str, float], min_shared: int) -> float | None:
    shared = [c for c in prev if c in cur]
    if len(shared) < min_shared:
        return None
    rets = [cur[c] / prev[c] - 1 for c in shared]
    return sum(rets) / len(rets)


def top_codes(stocks: list[dict], share: float = 0.1, minimum: int = 3) -> list[str]:
    """高标子池：帧内热榜 rank 升序前 share（至少 minimum 只）。"""
    ranked = []
    for row in stocks or []:
        r = row.get("rank")
        if isinstance(r, (int, float)):
            ranked.append((float(r), str(row.get("code") or "")))
    ranked.sort()
    take = max(minimum, math.ceil(len(ranked) * share)) if ranked else 0
    return [c for _, c in ranked[:take]]


def quartile_band(v: float, q1: float, q2: float, q3: float) -> str:
    if v <= q1:
        return "Q1"
    if v <= q2:
        return "Q2"
    if v <= q3:
        return "Q3"
    return "Q4"


def day_forward_metrics(
    prices: list[dict[str, float]],
    tops: list[list[str]],
    min_pool: int = MIN_SHARED_POOL,
    min_top: int = MIN_SHARED_TOP,
) -> list[dict]:
    """单日帧序列的前向读数（帧 i 相对当日后续帧）。

    prices[i] = 第 i 帧池价格表；tops[i] = 第 i 帧高标代码表。
    返回每帧 {h1, fwdEnd, fwdWorst, fwdWorstTop}（不适用/样本不足 = None）。
    """
    k = len(prices)
    out: list[dict] = []
    for i in range(k):
        h1 = pool_ret(prices[i - 1], prices[i], min_pool) if i >= 1 else None
        fwd_end = fwd_worst = fwd_worst_top = None
        if i < k - 1:
            rets = [pool_ret(prices[i], prices[j], min_pool) for j in range(i + 1, k)]
            rets = [r for r in rets if r is not None]
            if rets:
                fwd_end = rets[-1]
                fwd_worst = min(rets)
            tops_i = set(tops[i])
            if tops_i:
                trets = [
                    pool_ret({c: prices[i][c] for c in tops_i if c in prices[i]}, prices[j], min_top)
                    for j in range(i + 1, k)
                ]
                trets = [r for r in trets if r is not None]
                if trets:
                    fwd_worst_top = min(trets)
        out.append({"h1": h1, "fwdEnd": fwd_end, "fwdWorst": fwd_worst, "fwdWorstTop": fwd_worst_top})
    return out


def trade_observed_mae(
    frames_seq: list[dict],
    start_idx: int,
    code: str,
    entry_price: float,
    exit_date: str,
) -> dict:
    """持仓期池内可观测最差价 → MAE（票掉出池 = 右截断，计数不伪装）。"""
    worst = None
    observed = 0
    censored = 0
    for f in frames_seq[start_idx:]:
        if str(f.get("tradingDate") or "") > exit_date:
            break
        p = f.get("_prices") or {}
        if code in p:
            observed += 1
            v = p[code] / entry_price - 1 if entry_price else None
            if v is not None and (worst is None or v < worst):
                worst = v
        else:
            censored += 1
    return {"observedFrames": observed, "censoredFrames": censored, "mae": worst}


# ---------- 报告工具 ----------

def sep(a: list[float], b: list[float]) -> dict:
    if not a or not b:
        return {"nA": len(a), "nB": len(b)}
    med = lambda v: sorted(v)[len(v) // 2]  # noqa: E731
    return {
        "nA": len(a),
        "nB": len(b),
        "meanA": round(sum(a) / len(a), 5),
        "meanB": round(sum(b) / len(b), 5),
        "medianA": round(med(a), 5),
        "medianB": round(med(b), 5),
        "meanDiff": round(sum(a) / len(a) - sum(b) / len(b), 5),
        "p": mannwhitney_u(a, b),
    }


def band_sep(rows: list[dict], predictor: str, readout: str, lo: str = "Q1", hi: str = "Q4") -> dict:
    sel = [r for r in rows if isinstance(r.get(predictor + "_band"), str) and isinstance(r.get(readout), (int, float))]
    a = [r[readout] for r in sel if r[predictor + "_band"] == lo]
    b = [r[readout] for r in sel if r[predictor + "_band"] == hi]
    return sep(a, b)


def per_month_band_sep(rows: list[dict], predictor: str, readout: str) -> dict:
    months = sorted({r["month"] for r in rows})
    out = {}
    for m in months:
        ms = [r for r in rows if r["month"] == m]
        if len(ms) < MONTH_MIN_N:
            continue
        s = band_sep(ms, predictor, readout)
        s["month"] = m
        out[m] = s
    return out


def band_means(rows: list[dict], predictor: str, readout: str) -> dict:
    out = {}
    for b in ("Q1", "Q2", "Q3", "Q4"):
        v = [r[readout] for r in rows if r.get(predictor + "_band") == b and isinstance(r.get(readout), (int, float))]
        out[b] = {"n": len(v), "mean": round(sum(v) / len(v), 6) if v else None}
    return out


def month_stratified(rows: list[dict], predictor: str, readout: str, min_days: int = 8) -> dict:
    """探索性去混杂：月内中位分割 hi vs lo（冻结带-月份混杂的直接解法；day 级无帧聚类）。

    meanDiff 沿用约定 = mean(lo) − mean(hi)；hiMinusLo > 0 = 高分日该读数更优。
    方向一致性 = 逐月 hiMinusLo 符号计数 + 双侧二项 p（不设门，仅描述）。
    """
    per_month: dict = {}
    for m in sorted({r["month"] for r in rows}):
        ms = [r for r in rows if r["month"] == m and isinstance(r.get(predictor), (int, float)) and isinstance(r.get(readout), (int, float))]
        if len(ms) < min_days:
            per_month[m] = {"n": len(ms), "skipped": f"insufficient days (<{min_days})"}
            continue
        med = sorted(r[predictor] for r in ms)[len(ms) // 2]
        lo = [r[readout] for r in ms if r[predictor] <= med]
        hi = [r[readout] for r in ms if r[predictor] > med]
        s = sep(lo, hi)
        s["n"] = len(ms)
        s["hiMinusLo"] = round(-s["meanDiff"], 6) if isinstance(s.get("meanDiff"), (int, float)) else None
        per_month[m] = s
    diffs = [s["hiMinusLo"] for s in per_month.values() if isinstance(s.get("hiMinusLo"), (int, float))]
    pos = sum(1 for v in diffs if v > 0)
    neg = sum(1 for v in diffs if v < 0)
    n = len(diffs)
    binom_p = None
    if n >= 4:
        k = max(pos, neg)
        binom_p = round(min(1.0, sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n * 2), 4)
    return {"note": "exploratory deconfound（月内中位分割，非预登记门）", "perMonth": per_month,
            "hiBetterMonths": pos, "loBetterMonths": neg, "monthsTested": n, "binomTwoSidedP": binom_p}


def gate_verdict(per_month: dict, full: dict, direction: float) -> dict:
    """direction = 预登记假设中 (hi − lo) 的符号；meanDiff 按约定 = mean(lo) − mean(hi)。
    支持月 = 月内 p<GATE_P 且 (−meanDiff) 与 direction 同号（hi 优于 lo）。"""
    def is_support(diff: float | None) -> bool:
        return isinstance(diff, (int, float)) and (-diff) * direction > 0

    support = [m for m, s in per_month.items() if isinstance(s.get("p"), (int, float)) and s["p"] < GATE_P and is_support(s.get("meanDiff"))]
    reverse = [m for m, s in per_month.items() if isinstance(s.get("p"), (int, float)) and s["p"] < GATE_P and (-s.get("meanDiff", 0)) * direction < 0]
    full_rev = isinstance(full.get("p"), (int, float)) and full["p"] < GATE_P and (-full.get("meanDiff", 0)) * direction < 0
    if len(support) >= GATE_MONTHS and len(support) > len(reverse):
        verdict = "PASS"
    elif len(reverse) >= GATE_MONTHS or full_rev:
        verdict = "REVERSE"
    else:
        verdict = "FAIL"
    return {"verdictHint": verdict, "supportMonths": support, "reverseMonths": reverse,
            "fullWindow": {"meanDiff": full.get("meanDiff"), "p": full.get("p")}}


def dist_stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0}
    q1, q2, q3 = quartiles(vals)
    s = sorted(vals)
    return {"n": len(vals), "mean": round(sum(vals) / len(vals), 2), "median": q2,
            "p25": q1, "p75": q3, "min": s[0], "max": s[-1]}


# ---------- 主流程 ----------

def load_frames(path: Path) -> list[dict]:
    text = gzip.open(path, "rt", encoding="utf-8").read()
    dec = json.JSONDecoder()
    idx = text.index("[") + 1
    out = []
    while True:
        while idx < len(text) and text[idx] in " \t\r\n,":
            idx += 1
        if idx >= len(text) or text[idx] == "]":
            break
        frame, idx = dec.raw_decode(text, idx)
        out.append(frame)
    return out


def main() -> int:
    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]

    # jev 分数（eod 113 日 / slot 1070 槽）
    day_sc: dict[str, dict] = {}
    for doc in db["hotlist_jev_sentiment_v2"].find({"kind": "eod", "status": "ok"}, {"tradingDate": 1, "scores": 1}):
        sc = doc.get("scores") or {}
        t, c = sc.get("day_temperature"), sc.get("day_crowding")
        if isinstance(t, (int, float)) or isinstance(c, (int, float)):
            day_sc[str(doc.get("tradingDate"))] = {
                "day_temperature": float(t) if isinstance(t, (int, float)) else None,
                "day_crowding": float(c) if isinstance(c, (int, float)) else None,
            }
    slot_sc: dict[tuple[str, str], dict] = {}
    slot_crowd_by_day: dict[str, list[float]] = {}
    slot_temp_by_day: dict[str, list[float]] = {}
    for doc in db["hotlist_jev_sentiment_v2"].find({"kind": "slot", "status": "ok"}, {"tradingDate": 1, "slotTime": 1, "scores": 1}):
        sc = doc.get("scores") or {}
        t, c = sc.get("temperature"), sc.get("crowding")
        d, s = str(doc.get("tradingDate")), str(doc.get("slotTime"))
        if isinstance(t, (int, float)) or isinstance(c, (int, float)):
            slot_sc[(d, s)] = {
                "temperature": float(t) if isinstance(t, (int, float)) else None,
                "crowding": float(c) if isinstance(c, (int, float)) else None,
            }
            if isinstance(t, (int, float)):
                slot_temp_by_day.setdefault(d, []).append(float(t))
            if isinstance(c, (int, float)):
                slot_crowd_by_day.setdefault(d, []).append(float(c))

    # 冻结阈值：全窗（113 eod 日）四分位
    temp_vals = [v["day_temperature"] for v in day_sc.values() if isinstance(v.get("day_temperature"), (int, float))]
    crowd_vals = [v["day_crowding"] for v in day_sc.values() if isinstance(v.get("day_crowding"), (int, float))]
    t_q = quartiles(temp_vals)
    c_q = quartiles(crowd_vals)

    # frames 按日分组（帧内按 slotTime 升序）
    frames = load_frames(FRAMES)
    frames.sort(key=lambda f: (str(f.get("tradingDate")), str(f.get("slotTime"))))
    for f in frames:
        f["_prices"] = frame_prices(f)
        f["_top"] = top_codes(f.get("stocks") or [])
    day_frames: dict[str, list[dict]] = {}
    for f in frames:
        day_frames.setdefault(str(f.get("tradingDate")), []).append(f)
    dates = sorted(day_frames)
    prev_day = {dates[i]: dates[i - 1] for i in range(1, len(dates))}

    excluded = {"beforeFirstEod": 0, "noPrevScore": 0, "noForwardWindow": 0, "sharedInsufficient": 0, "topSharedInsufficient": 0}

    # 同槽拥挤分位（敏感性用，一次算好）
    sc_q = quartiles([v["crowding"] for v in slot_sc.values() if isinstance(v.get("crowding"), (int, float))])

    # ---------- T1：标定 ----------
    months = sorted({d[:7] for d in day_sc})
    calibration: dict = {"day_temperature": {}, "day_crowding": {}}
    for axis, vals, qs in (("day_temperature", temp_vals, t_q), ("day_crowding", crowd_vals, c_q)):
        by_day = {d: v[axis] for d, v in day_sc.items() if isinstance(v.get(axis), (int, float))}
        per_month = {m: dist_stats([v for d, v in by_day.items() if d[:7] == m]) for m in months}
        occupancy = {}
        for m in months:
            md = [quartile_band(v, *qs) for d, v in by_day.items() if d[:7] == m]
            occupancy[m] = {b: md.count(b) for b in ("Q1", "Q2", "Q3", "Q4")}
        calibration[axis] = {"fullWindow": dist_stats(vals), "frozenQuartiles": {"p25": qs[0], "p50": qs[1], "p75": qs[2]},
                             "perMonth": per_month, "bandOccupancyByMonth": occupancy}

    def day_pairs(ax_a: str, ax_b: str) -> tuple[list[float], list[float]]:
        xs, ys = [], []
        for d, v in sorted(day_sc.items()):
            a, b = v.get(ax_a), v.get(ax_b)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                xs.append(float(a))
                ys.append(float(b))
        return xs, ys

    # 规则分前日 EOD（正交性对照）
    rule_eod: dict[str, float] = {}
    for doc in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD"},
        {"tradingDate": 1, "emotionScore.score": 1},
    ):
        es = doc.get("emotionScore")
        if isinstance(es, dict) and isinstance(es.get("score"), (int, float)):
            rule_eod[str(doc.get("tradingDate"))] = float(es["score"])

    xs, ys = day_pairs("day_temperature", "day_crowding")
    corr_day_temp_crowd = spearman(xs, ys)
    xs, ys = [], []
    for d, v in sorted(day_sc.items()):
        pd_ = prev_day.get(d)
        rs = rule_eod.get(pd_) if pd_ else None
        if isinstance(v.get("day_temperature"), (int, float)) and isinstance(rs, (int, float)):
            xs.append(v["day_temperature"])
            ys.append(rs)
    corr_temp_rule = spearman(xs, ys)
    xs, ys = [], []
    for d, v in sorted(day_sc.items()):
        pd_ = prev_day.get(d)
        rs = rule_eod.get(pd_) if pd_ else None
        if isinstance(v.get("day_crowding"), (int, float)) and isinstance(rs, (int, float)):
            xs.append(v["day_crowding"])
            ys.append(rs)
    corr_crowd_rule = spearman(xs, ys)

    def corr_day_slotmean(day_ax: str, slot_map: dict[str, list[float]]) -> float | None:
        xs, ys = [], []
        for d, v in sorted(day_sc.items()):
            if isinstance(v.get(day_ax), (int, float)) and slot_map.get(d):
                xs.append(v[day_ax])
                ys.append(sum(slot_map[d]) / len(slot_map[d]))
        return spearman(xs, ys)

    correlations = {
        "dayTemp_vs_dayCrowding": corr_day_temp_crowd,
        "dayTemp_vs_prevRuleScore": corr_temp_rule,
        "dayCrowd_vs_prevRuleScore": corr_crowd_rule,
        "dayTemp_vs_meanSlotTemp": corr_day_slotmean("day_temperature", slot_temp_by_day),
        "dayCrowd_vs_meanSlotCrowd": corr_day_slotmean("day_crowding", slot_crowd_by_day),
    }
    independence = "independent" if (corr_day_temp_crowd is not None and abs(corr_day_temp_crowd) < 0.5) else (
        "high_correlation" if (corr_day_temp_crowd is not None and abs(corr_day_temp_crowd) >= 0.7) else "moderate")

    # ---------- T2：帧级证据 ----------
    frame_rows: list[dict] = []
    day_rows: list[dict] = []
    first_eod = min(day_sc)
    for d in dates:
        fs = day_frames[d]
        prices = [f["_prices"] for f in fs]
        tops = [f["_top"] for f in fs]
        metrics = day_forward_metrics(prices, tops)
        pd_ = prev_day.get(d)
        ds = day_sc.get(pd_) if pd_ else None
        if d < first_eod:
            excluded["beforeFirstEod"] += len(fs)
        elif not ds:
            excluded["noPrevScore"] += len(fs)
        # 帧级行
        for i, f in enumerate(fs):
            if d < first_eod or not ds:
                continue
            m = metrics[i]
            if i >= len(fs) - 1:
                excluded["noForwardWindow"] += 1
            row: dict = {"month": d[:7], "date": d, "slot": str(f.get("slotTime"))}
            if isinstance(ds.get("day_temperature"), (int, float)):
                row["day_temperature"] = ds["day_temperature"]
                row["day_temperature_band"] = quartile_band(ds["day_temperature"], *t_q)
            if isinstance(ds.get("day_crowding"), (int, float)):
                row["day_crowding"] = ds["day_crowding"]
                row["day_crowding_band"] = quartile_band(ds["day_crowding"], *c_q)
            ss = slot_sc.get((d, str(f.get("slotTime"))))
            if ss and isinstance(ss.get("crowding"), (int, float)):
                row["slot_crowding"] = ss["crowding"]
                row["slot_crowding_band"] = quartile_band(ss["crowding"], *sc_q)
            has_fwd = i < len(fs) - 1
            for k2 in ("h1", "fwdEnd", "fwdWorst", "fwdWorstTop"):
                if m[k2] is None and k2 in ("fwdEnd", "fwdWorst") and has_fwd:
                    excluded["sharedInsufficient"] += 1
                if m[k2] is None and k2 == "fwdWorstTop" and has_fwd:
                    excluded["topSharedInsufficient"] += 1
                row[k2] = m[k2]
            frame_rows.append(row)
        # 日级行（聚类稳健性）
        if ds and len(fs) >= 2:
            dayret = pool_ret(prices[0], prices[-1], MIN_SHARED_POOL)
            dayworst = None
            rets = [pool_ret(prices[0], prices[j], MIN_SHARED_POOL) for j in range(1, len(fs))]
            rets = [r for r in rets if r is not None]
            if rets:
                dayworst = min(rets)
            drow: dict = {"month": d[:7], "date": d, "dayRet": dayret, "dayWorst": dayworst}
            if isinstance(ds.get("day_temperature"), (int, float)):
                drow["day_temperature"] = ds["day_temperature"]
                drow["day_temperature_band"] = quartile_band(ds["day_temperature"], *t_q)
            if isinstance(ds.get("day_crowding"), (int, float)):
                drow["day_crowding"] = ds["day_crowding"]
                drow["day_crowding_band"] = quartile_band(ds["day_crowding"], *c_q)
            day_rows.append(drow)
        # 次日缺口挂在下一日的日行
    for i, drow in enumerate(day_rows):
        d = drow["date"]
        di = dates.index(d)
        if di + 1 < len(dates) and day_frames[dates[di + 1]]:
            nxt = day_frames[dates[di + 1]][0]["_prices"]
            drow["nextOpen"] = pool_ret(day_frames[d][-1]["_prices"], nxt, MIN_SHARED_POOL)

    # 温度轴（收益题，主读数 H1；加仓端检验 Q4 vs Q2）
    temp_main = band_sep(frame_rows, "day_temperature", "h1")
    temp_main_pm = per_month_band_sep(frame_rows, "day_temperature", "h1")
    temp_gate = gate_verdict(temp_main_pm, temp_main, direction=+1)
    temp_evidence = {
        "main": {"readout": "h1", "predictor": "prevEod day_temperature", "q4_vs_q1": temp_main,
                 "perMonth": temp_main_pm, "gate": temp_gate},
        "sensitivity": {
            "q4_vs_q2_h1": band_sep(frame_rows, "day_temperature", "h1", lo="Q2", hi="Q4"),
            "fwdEnd_q4_vs_q1": band_sep(frame_rows, "day_temperature", "fwdEnd"),
            "bandMeans_h1": band_means(frame_rows, "day_temperature", "h1"),
            "dayLevel_dayRet_q4_vs_q1": band_sep(day_rows, "day_temperature", "dayRet"),
            "dayLevel_dayWorst_q4_vs_q1": band_sep(day_rows, "day_temperature", "dayWorst"),
        },
    }

    # 拥挤轴（回撤题，主读数 fwdWorst）
    crowd_main = band_sep(frame_rows, "day_crowding", "fwdWorst")
    crowd_main_pm = per_month_band_sep(frame_rows, "day_crowding", "fwdWorst")
    crowd_gate = gate_verdict(crowd_main_pm, crowd_main, direction=-1)
    crowd_evidence = {
        "main": {"readout": "fwdWorst", "predictor": "prevEod day_crowding", "q4_vs_q1": crowd_main,
                 "perMonth": crowd_main_pm, "gate": crowd_gate},
        "sensitivity": {
            "fwdEnd_q4_vs_q1": band_sep(frame_rows, "day_crowding", "fwdEnd"),
            "fwdWorstTop_q4_vs_q1": band_sep(frame_rows, "day_crowding", "fwdWorstTop"),
            "slotCrowd_fwdWorst_q4_vs_q1": band_sep(frame_rows, "slot_crowding", "fwdWorst"),
            "slotCrowd_fwdWorst_perMonth": per_month_band_sep(frame_rows, "slot_crowding", "fwdWorst"),
            "bandMeans_fwdWorst": band_means(frame_rows, "day_crowding", "fwdWorst"),
            "dayLevel_dayWorst_q4_vs_q1": band_sep(day_rows, "day_crowding", "dayWorst"),
            "dayLevel_nextOpen_q4_vs_q1": band_sep(day_rows, "day_crowding", "nextOpen"),
        },
    }

    # 探索性去混杂：月内中位分割（day 级）——裁决"全窗反向是否纯月份混杂"（与 T-jev2 月内重标口径对齐）
    deconfound = {
        "temperature_dayRet": month_stratified(day_rows, "day_temperature", "dayRet"),
        "temperature_dayWorst": month_stratified(day_rows, "day_temperature", "dayWorst"),
        "crowding_dayWorst": month_stratified(day_rows, "day_crowding", "dayWorst"),
        "crowding_dayRet": month_stratified(day_rows, "day_crowding", "dayRet"),
    }

    # 交易层对照（次要证据）：基线 54 笔回联 frames
    trade_level: dict = {"source": str(BASELINE_TRADES), "trades": []}
    snap_idx = {str(f.get("snapshotId")): i for i, f in enumerate(frames)}
    try:
        rt = json.loads(BASELINE_TRADES.read_text(encoding="utf-8")).get("roundTripTrades") or []
    except Exception:
        rt = []
    for t in rt:
        start = snap_idx.get(str(t.get("entrySnapshotId")))
        ep = t.get("entryPrice")
        if start is None or not ep:
            continue
        r = trade_observed_mae(frames, start, str(t.get("code")), float(ep), str(t.get("exitTradingDate") or t.get("entryTradingDate")))
        d = str(frames[start].get("tradingDate"))
        pd_ = prev_day.get(d)
        ds = day_sc.get(pd_) if pd_ else None
        if ds and isinstance(ds.get("day_crowding"), (int, float)):
            r["day_crowding_band"] = quartile_band(ds["day_crowding"], *c_q)
        r["code"] = t.get("code")
        r["entryTradingDate"] = d
        r["netReturn"] = t.get("netReturn")
        trade_level["trades"].append(r)
    band_groups: dict[str, list[float]] = {}
    for r in trade_level["trades"]:
        if isinstance(r.get("mae"), (int, float)) and r.get("day_crowding_band"):
            band_groups.setdefault(r["day_crowding_band"], []).append(r["mae"])
    trade_level["byCrowdBand"] = {
        b: {"n": len(v), "meanMae": round(sum(v) / len(v), 4),
            "medianMae": round(sorted(v)[len(v) // 2], 4),
            "censoredRatio": round(sum(1 for r in trade_level["trades"] if r.get("day_crowding_band") == b and r.get("censoredFrames", 0) > 0) / max(1, sum(1 for r in trade_level["trades"] if r.get("day_crowding_band") == b)), 3)}
        for b, v in sorted(band_groups.items())
    }
    if "Q1" in band_groups and "Q4" in band_groups:
        trade_level["q4_vs_q1_mae"] = sep(band_groups["Q4"], band_groups["Q1"])

    try:
        git_commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        git_commit = None

    cal_report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"), "purpose": "SP5 T1：jev 日级两轴标定（分布/冻结分位/逐月稳定性/相关矩阵）",
                 "gitCommit": git_commit, "eodDays": len(day_sc)},
        "axes": calibration,
        "correlations": correlations,
        "twoAxisIndependence": independence,
    }
    evid_report = {
        "meta": {"generatedAt": datetime.now().isoformat(timespec="seconds"), "purpose": "SP5 T2：按轴配读数证据门（温度=H1 收益题 / 拥挤=fwdWorst 回撤题）",
                 "gitCommit": git_commit, "framesJoined": len(frame_rows), "daysJoined": len(day_rows),
                 "hypothesis": {"temperature": "Q4 H1 > Q1（热→强）", "crowding": "Q4 fwdWorst < Q1（高拥挤→更深不利偏移）"},
                 "gateRule": f">= {GATE_MONTHS} 月同向且 p<0.05；REVERSE=反向显著只登记观察",
                 "exclusions": excluded},
        "temperatureAxis": temp_evidence,
        "crowdingAxis": crowd_evidence,
        "deconfoundExploratory": deconfound,
        "tradeLevel": trade_level,
    }
    OUT_CAL.parent.mkdir(parents=True, exist_ok=True)
    OUT_CAL.write_text(json.dumps(cal_report, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_EVID.write_text(json.dumps(evid_report, ensure_ascii=False, indent=1), encoding="utf-8")

    summary = {
        "thresholds": {"day_temperature": cal_report["axes"]["day_temperature"]["frozenQuartiles"],
                       "day_crowding": cal_report["axes"]["day_crowding"]["frozenQuartiles"]},
        "correlations": correlations,
        "twoAxisIndependence": independence,
        "temperatureGate": temp_gate,
        "crowdingGate": crowd_gate,
        "tempQ4vsQ2": temp_evidence["sensitivity"]["q4_vs_q2_h1"],
        "crowdSlotSensitivity": crowd_evidence["sensitivity"]["slotCrowd_fwdWorst_q4_vs_q1"],
        "deconfound": {k: {"hiBetterMonths": v["hiBetterMonths"], "loBetterMonths": v["loBetterMonths"], "binomTwoSidedP": v["binomTwoSidedP"]} for k, v in deconfound.items()},
        "tradeLevelBands": {b: {"n": v["n"], "meanMae": v["meanMae"]} for b, v in trade_level.get("byCrowdBand", {}).items()},
        "exclusions": excluded,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"-> {OUT_CAL}")
    print(f"-> {OUT_EVID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
