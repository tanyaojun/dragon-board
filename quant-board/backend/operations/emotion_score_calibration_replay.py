# -*- coding: utf-8 -*-
"""T1.5 校准重放（只读）：jev 聚合口径全槽重放，产出 _CALIB 替换依据与五档可达率。

审计背景（docs/superpowers/specs/2026-09-30-emotion-score-audit.md B1）：
emotion_score._CALIB 现值出处为规则链文档 metrics 口径（change>0 涨、fallback 行计入分子），
而评分输入是 jev 聚合口径（pct>=0 涨、fallback 行不计分子）——平盘行归类与 fallback 行处理
两处系统性差异使校准边界错位。本脚本以与评分完全一致的输入路径（collect_slot_evidence）
重放 hotlist_sentiment 槽位清单，产出：

1. jev 口径全维分位数表 + 建议 _CALIB 锚点（分数锚点继承 v2，raw 边界换实测分位）；
2. score 实测分布与五档可达率（含高潮压制条款触发计数，B3 裁决依据）；
3. riskRowsPct×riskShare、upRatio×attackShare Pearson 相关系数（S3/S4 裁决依据）；
4. join 命中率（fallback 率）；change vs pctChange 一致性；zhabanRate 量纲。

只读：全程 find，不写任何 collection。缺源槽位按 fail-visible 计数上报，不伪造。
用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.emotion_score_calibration_replay
  可选：--dataset dragonboard_live --snapshot-type half_hour --limit-dates 3 --json <path>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from math import isfinite

from backend.analysis.hotlist.emotion_score import compute_emotion_score, map_stage
from backend.analysis.hotlist.jev_state import collect_slot_evidence

# 建议 _CALIB 的锚定关系（分数锚点继承 v2 设计，raw 边界替换为实测分位）：
# (锚点分数, 实测分位)；首尾 clamp 端点保持 0/100 不变。
_ANCHORS = {
    "upRatio": [(10, "P10"), (25, "P25"), (50, "P50"), (75, "P75"), (95, "P95")],
    "attackShare": [(30, "P50"), (50, "P75"), (70, "P90"), (85, "P95"), (95, "P99")],
    "riskShare": [(90, "P10"), (50, "P50"), (10, "P90")],
    "trin": [(90, "P5"), (75, "P25"), (50, "P50"), (25, "P75"), (10, "P90")],
    "yhPositive": [(10, "P10"), (50, "P50"), (90, "P90")],
    "riskRowsPct": [(90, "P10"), (50, "P50"), (10, "P90")],
    "ztCount": [(30, "P50"), (60, "P75"), (90, "P90")],
    "maxBoard": [(25, "P50"), (50, "P75"), (75, "P90")],
    "zhabanRate": [(75, "P25"), (45, "P50"), (15, "P90")],
}

_QUANTILE_KEYS = ("min", "P5", "P10", "P25", "P50", "P75", "P90", "P95", "P99", "max")


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value))


def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * p / 100.0
    low, high = int(rank), min(int(rank) + 1, len(sorted_values) - 1)
    frac = rank - low
    return float(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac)


def _distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    out: dict[str, float | None] = {"n": len(ordered)}
    for key, p in (("min", 0), ("P5", 5), ("P10", 10), ("P25", 25), ("P50", 50),
                   ("P75", 75), ("P90", 90), ("P95", 95), ("P99", 99), ("max", 100)):
        out[key] = round(_percentile(ordered, p), 4) if ordered else None
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return round(cov / (vx * vy) ** 0.5, 4)


# ── 取数（复用 jev 服务层模式，只读 find）──

def _load_rows(db, dataset_id: str, snapshot_id: str) -> list[dict]:
    return list(db["snapshot_stock_rows"].find({"datasetId": dataset_id, "snapshotId": snapshot_id}))


def _load_analysis_by_code(db, dataset_id: str, snapshot_id: str) -> dict:
    rows = db["snapshot_analysis"].find(
        {"datasetId": dataset_id, "snapshotId": snapshot_id},
        {"_id": 0, "code": 1, "analysis": 1},
    )
    return {str(row.get("code")): row.get("analysis") for row in rows if row.get("code")}


def _latest_date_before(db, dataset_id: str, snapshot_type: str, trading_date: str) -> str | None:
    dates = sorted({
        str(f.get("tradingDate"))
        for f in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type}, {"tradingDate": 1})
        if f.get("tradingDate") and str(f.get("tradingDate")) < trading_date
    })
    return dates[-1] if dates else None


def _yesterday_parts(db, dataset_id: str, snapshot_type: str, trading_date: str) -> tuple[list[dict], dict[str, float]]:
    """(上一交易日最新帧行, 昨日各槽 totalAmount 映射)；按调用即查（外层按日缓存）。"""
    latest_date = _latest_date_before(db, dataset_id, snapshot_type, trading_date)
    if latest_date is None:
        return [], {}
    frame = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": latest_date},
        sort=[("timestamp", -1), ("snapshotId", -1)],
    )
    yesterday_rows = _load_rows(db, dataset_id, str(frame.get("snapshotId") or "")) if frame else []
    amounts: dict[str, float] = {}
    for f in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": latest_date},
            {"indices": 1, "slotTime": 1}):
        slot = str(f.get("slotTime") or "")
        entry = (f.get("indices") or {}).get("totalAmount") if isinstance(f.get("indices"), dict) else None
        if len(slot) == 5 and slot[2] == ":" and isinstance(entry, dict) and _finite(entry.get("amount")):
            amounts[slot] = float(entry["amount"])
    return yesterday_rows, amounts


# ── 单槽重放 ──

def _replay_slot(db, dataset_id: str, snapshot_type: str, trading_date: str, slot_time: str,
                 yesterday_rows: list[dict], amounts: dict[str, float]) -> dict:
    base = {"tradingDate": trading_date, "slotTime": slot_time}
    frame = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time},
        sort=[("timestamp", -1), ("snapshotId", -1)],
    )
    if frame is None:
        return {**base, "status": "no_frame"}
    rows = _load_rows(db, dataset_id, str(frame.get("snapshotId") or ""))
    if not rows:
        return {**base, "status": "no_rows"}
    analysis_by_code = _load_analysis_by_code(db, dataset_id, str(frame.get("snapshotId") or ""))
    joined = sum(1 for row in rows if str(row.get("code") or "") in analysis_by_code)

    change_both = change_mismatch = 0
    for row in rows:
        ch, pct = row.get("change"), row.get("pctChange")
        if _finite(ch) and _finite(pct):
            change_both += 1
            if abs(float(ch) - float(pct)) > 0.01:
                change_mismatch += 1

    evidence = collect_slot_evidence(
        frame=frame, rows=rows, yesterday_rows=yesterday_rows,
        analysis_by_code=analysis_by_code, slot_time=slot_time,
        yesterday_same_slot_total_amount=amounts.get(slot_time),
    )
    result = compute_emotion_score(evidence)

    breadth = evidence.get("breadth") or {}
    row_flags = evidence.get("rowFlags") or {}
    total = breadth.get("total") or 0
    judgeable = row_flags.get("judgeable") or 0
    risk_rows_pct = (row_flags.get("risk") or 0) / judgeable * 100 if judgeable else None
    risk_share = (row_flags.get("risk") or 0) / total if total else None
    up_ratio = ((breadth.get("limitUp") or 0) + (breadth.get("up5") or 0) + (breadth.get("up0") or 0)) / total if total else None
    lifecycle = evidence.get("lifecycle") or {}
    attack_share = ((lifecycle.get("ignition") or 0) + (lifecycle.get("expansion") or 0)
                    + (row_flags.get("strongMoney") or 0)) / total if total else None
    limit = evidence.get("limit") or {}

    return {
        **base,
        "status": "ok",
        "score": result.get("score"),
        "skippedDims": result.get("skippedDims") or [],
        "stageCandidateNoSuppress": map_stage(result["score"], None) if result.get("score") is not None else None,
        "riskRowsPct": round(risk_rows_pct, 2) if risk_rows_pct is not None else None,
        "riskShare": round(risk_share, 4) if risk_share is not None else None,
        "upRatio": round(up_ratio, 4) if up_ratio is not None else None,
        "attackShare": round(attack_share, 4) if attack_share is not None else None,
        "trin": breadth.get("trin"),
        "yhPositive": (evidence.get("yesterdayLimit") or {}).get("positiveRate"),
        "ztCount": limit.get("ztCount"),
        "maxBoard": limit.get("maxBoard"),
        "zhabanRate": limit.get("zhabanRate"),
        "amountVsSamePct": (evidence.get("totalAmount") or {}).get("vsSamePct"),
        "rowsTotal": total,
        "joinRate": round(joined / total, 4) if total else None,
        "changeBoth": change_both,
        "changeMismatch": change_mismatch,
    }


# ── 汇总 ──

_DIM_KEYS = ("upRatio", "attackShare", "riskShare", "riskRowsPct", "trin",
             "yhPositive", "ztCount", "maxBoard", "zhabanRate", "amountVsSamePct")


def _slope_pass(records: list[dict]) -> None:
    """日内按槽序补 slope（前值取上一个有效 score；score=None 槽跳过不截断序列）。"""
    by_date: OrderedDict[str, list[dict]] = OrderedDict()
    for rec in records:
        by_date.setdefault(rec["tradingDate"], []).append(rec)
    for slot_records in by_date.values():
        prev: float | None = None
        for rec in sorted(slot_records, key=lambda r: r["slotTime"]):
            if rec.get("status") != "ok" or rec.get("score") is None:
                rec["slope"] = None
                continue
            rec["slope"] = round(rec["score"] - prev, 2) if prev is not None else None
            prev = rec["score"]


def summarize(records: list[dict]) -> dict:
    ok = [rec for rec in records if rec.get("status") == "ok"]
    scored = [rec for rec in ok if rec.get("score") is not None]
    _slope_pass(records)
    scored = [rec for rec in ok if rec.get("score") is not None]

    dims = {}
    for key in _DIM_KEYS:
        values = [float(rec[key]) for rec in scored if _finite(rec.get(key))]
        dims[key] = _distribution(values)

    scores = sorted(float(rec["score"]) for rec in scored)
    score_dist = _distribution(scores)
    stage_counts: dict[str, int] = {}
    for rec in scored:
        stage = map_stage(float(rec["score"]), rec.get("slope"))
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    # 压制条款已删除（审计 B3）；保留"score>=75 且 riskRowsPct>70"计数作为记录项
    legacy_suppress_would_hit = sum(
        1 for rec in scored
        if float(rec["score"]) >= 75 and rec.get("riskRowsPct") is not None
        and float(rec["riskRowsPct"]) > 70)

    def _corr(a: str, b: str) -> float | None:
        pairs = [(float(rec[a]), float(rec[b])) for rec in scored
                 if _finite(rec.get(a)) and _finite(rec.get(b))]
        return _pearson([p[0] for p in pairs], [p[1] for p in pairs]) if pairs else None

    join_rates = [float(rec["joinRate"]) for rec in ok if _finite(rec.get("joinRate"))]
    change_both = sum(int(rec.get("changeBoth") or 0) for rec in ok)
    change_mismatch = sum(int(rec.get("changeMismatch") or 0) for rec in ok)

    suggested: dict[str, list] = {}
    for key, anchors in _ANCHORS.items():
        dist = dims.get(key) or {}
        if not dist.get("n"):
            suggested[key] = []
            continue
        points = [(0.0, 0.0)] if key not in ("riskShare", "riskRowsPct", "trin", "zhabanRate") else []
        for score_anchor, quantile_key in anchors:
            raw = dist.get(quantile_key)
            if raw is None:
                continue
            points.append((float(raw), float(score_anchor)))
        end_score = 100.0 if key not in ("riskShare", "riskRowsPct", "trin", "zhabanRate") else 0.0
        points.append((1.0 if key in ("upRatio", "attackShare", "riskShare", "yhPositive") else 100.0, end_score))
        suggested[key] = [(round(x, 4), y) for x, y in sorted(points)]

    return {
        "slotTotal": len(records),
        "ok": len(ok),
        "scored": len(scored),
        "noFrame": sum(1 for rec in records if rec.get("status") == "no_frame"),
        "noRows": sum(1 for rec in records if rec.get("status") == "no_rows"),
        "scoreNone": len(ok) - len(scored),
        "skippedDimCounts": {
            key: sum(1 for rec in scored if key in (rec.get("skippedDims") or []))
            for key in sorted({key for rec in scored for key in (rec.get("skippedDims") or [])})
        },
        "dims": dims,
        "scoreDist": score_dist,
        "stageCounts": stage_counts,
        "legacyClimaxSuppressWouldHit": legacy_suppress_would_hit,
        "corrRiskRowsPctVsRiskShare": _corr("riskRowsPct", "riskShare"),
        "corrUpRatioVsAttackShare": _corr("upRatio", "attackShare"),
        "joinRate": _distribution(join_rates),
        "changeFields": {"bothPresent": change_both, "mismatchGt001": change_mismatch},
        "suggestedCalib": suggested,
    }


def run_replay(dataset_id: str, snapshot_type: str, limit_dates: int | None) -> tuple[list[dict], dict]:
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    db = get_runtime_mongodb_database()
    slot_docs = db["hotlist_sentiment"].find(
        {"datasetId": dataset_id, "snapshotType": snapshot_type,
         "slotTime": {"$exists": True, "$ne": "EOD"}},
        {"tradingDate": 1, "slotTime": 1},
    )
    by_date: OrderedDict[str, list[str]] = OrderedDict()
    for doc in slot_docs:
        date, slot = str(doc.get("tradingDate") or ""), str(doc.get("slotTime") or "")
        if date and len(slot) == 5 and slot[2] == ":":
            by_date.setdefault(date, []).append(slot)
    dates = sorted(by_date)
    if limit_dates:
        dates = dates[-limit_dates:]
        by_date = OrderedDict((date, sorted(by_date[date])) for date in dates)
    else:
        by_date = OrderedDict((date, sorted(by_date[date])) for date in dates)

    records: list[dict] = []
    yesterday_cache: dict[str, tuple[list[dict], dict[str, float]]] = {}
    for date in dates:
        if date not in yesterday_cache:
            yesterday_cache[date] = _yesterday_parts(db, dataset_id, snapshot_type, date)
        yesterday_rows, amounts = yesterday_cache[date]
        for slot in by_date[date]:
            records.append(_replay_slot(db, dataset_id, snapshot_type, date, slot, yesterday_rows, amounts))
        print(f"[replay] {date}: {len(by_date[date])} slots done", file=sys.stderr)
    return records, summarize(records)


def main() -> int:
    parser = argparse.ArgumentParser(description="emotion score 校准重放（只读）")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--snapshot-type", default="half_hour")
    parser.add_argument("--limit-dates", type=int, default=None, help="只重放最近 N 个交易日（试跑）")
    parser.add_argument("--json", default=None, help="汇总 JSON 输出路径")
    args = parser.parse_args()

    records, summary = run_replay(args.dataset, args.snapshot_type, args.limit_dates)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"summary": summary,
                       "records": records}, fh, ensure_ascii=False, indent=1)
        print(f"[replay] json -> {args.json}", file=sys.stderr)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
