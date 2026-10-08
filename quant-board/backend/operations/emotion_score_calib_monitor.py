# -*- coding: utf-8 -*-
"""校准漂移监控（D 项，advisory）：滚动窗口各维 raw 分布 vs _CALIB 分位锚，|漂移|>10 告警。

设计/冻结线：docs/hotlist-jev/emotion-score-calib-monitor-design.md（2026-10-08，audit P2-4）。
- 窗口=最近 20 交易日非 EOD 槽位文档；分位 {P10,P25,P50,P75,P95}；
- 单一事实源：直接 import emotion_score._CALIB/_interp，零曲线副本；
- 只探测不重写：月度重校准/第八维重启均走预登记裁决（设计文档 §2），本模块不改评分口径；
- fail-visible：raw 恒 null 的复合维（limitStruct）结构性排除登记；窗口样本 <30 该维 skip；
- 落库：phase_monitor kind=calib_drift _id=calib_drift:<YYYY-MM> 月度幂等 upsert。

用法（quant-board 目录）：
  ./.venv/Scripts/python.exe -m backend.operations.emotion_score_calib_monitor --date 2026-10-08 [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist.emotion_score import _CALIB, _interp

WINDOW_TRADING_DAYS = 20
# 锚定网格（权威源=.tmp/emotion-score-calibration.json〔1068 槽分布〕与 _CALIB 锚点逐位对照确认，
# 2026-10-08 实证：主维 P10/P25/P50/P75/P95→10/25/50/75/95；反向维镜像网格用 P90 代 P95：
# riskShare 0.9777=P90→10、trin 0.5056=P5→90/1.6815=P90→10、riskRowsPct 98.014=P90→10）
MAIN_ANCHORS: tuple[tuple[str, float, float], ...] = (
    ("P10", 10.0, 10.0), ("P25", 25.0, 25.0), ("P50", 50.0, 50.0), ("P75", 75.0, 75.0), ("P95", 95.0, 95.0))
REVERSED_ANCHORS: tuple[tuple[str, float, float], ...] = (
    ("P10", 10.0, 90.0), ("P25", 25.0, 75.0), ("P50", 50.0, 50.0), ("P75", 75.0, 25.0), ("P90", 90.0, 10.0))
ALERT_THRESHOLD = 10.0
MIN_SAMPLE = 30
# 有 stored raw 的检测维（limitStruct raw 恒 null=复合维，结构性排除）
MONITORED_DIMS = ("upRatio", "attackShare", "riskShare", "trin", "yhPositive", "riskRowsPct")
EXCLUDED_DIMS = {"limitStruct": "composite_dim_raw_null", "amountVsSame": "frozen_gate_a1"}
READY_DAYS_THRESHOLD = 20


# ---------------------------------------------------------------- 纯函数

def percentile(sorted_vals: list[float], p: float) -> float | None:
    """线性插值分位（输入需已升序）；单点样本直接返回该值。"""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _is_reversed(curve: list[tuple[float, float]]) -> bool:
    return curve[0][1] > curve[-1][1]


def _expected_sub(curve: list[tuple[float, float]], p: float) -> float:
    """锚定期望分：按曲线方向取锚定网格（主维 P_p→p；反向维镜像 P10→90/P25→75/P50→50/P75→25/P90→10）。"""
    anchors = REVERSED_ANCHORS if _is_reversed(curve) else MAIN_ANCHORS
    for _name, ap, expected in anchors:
        if ap == p:
            return expected
    return p  # 未锚定分位（不应到达）：退化为镜像外推


def drifts_of(raws: list[float], calib_curve: list[tuple[float, float]]) -> dict[str, float] | None:
    """窗口 raws → 各锚分位漂移（_interp(curve, P 分位值) − 锚定期望分）。样本不足返回 None。"""
    if len(raws) < MIN_SAMPLE:
        return None
    vals = sorted(float(v) for v in raws)
    anchors = REVERSED_ANCHORS if _is_reversed(calib_curve) else MAIN_ANCHORS
    out: dict[str, float] = {}
    for name, p, expected in anchors:
        v = percentile(vals, p)
        if v is None:
            continue
        out[name] = round(_interp(calib_curve, v) - expected, 1)
    return out or None


def build_calib_drift_report(
    slot_docs: list[dict[str, Any]],
    *,
    trading_dates: list[str],
    amount_recorded_days: int,
) -> dict[str, Any]:
    """纯函数：槽位文档（含 emotionScore.dims[].raw）→ 漂移报告。"""
    raws_by_dim: dict[str, list[float]] = {name: [] for name in MONITORED_DIMS}
    for doc in slot_docs:
        dims = ((doc.get("emotionScore") or {}).get("dims")) or {}
        for name in MONITORED_DIMS:
            raw = (dims.get(name) or {}).get("raw")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                raws_by_dim[name].append(float(raw))
    dims_out: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    alerts: list[dict[str, Any]] = []
    for name in MONITORED_DIMS:
        raws = raws_by_dim[name]
        drifts = drifts_of(raws, _CALIB[name])
        if drifts is None:
            skipped[name] = f"insufficient_sample: {len(raws)}<{MIN_SAMPLE}"
            continue
        max_abs = max(abs(v) for v in drifts.values())
        entry: dict[str, Any] = {"sample": len(raws), "drifts": drifts,
                                 "maxAbsDrift": round(max_abs, 1), "alert": max_abs > ALERT_THRESHOLD}
        p50_raw = percentile(sorted(float(v) for v in raws), 50.0)
        if p50_raw is not None:
            entry["p50Raw"] = round(p50_raw, 4)
        dims_out[name] = entry
        for pname, drift in drifts.items():
            if abs(drift) > ALERT_THRESHOLD:
                alerts.append({"dim": name, "percentile": pname, "drift": drift})
    month = (trading_dates[-1] if trading_dates else datetime.now().strftime("%Y-%m-%d"))[:7]
    return {
        "month": month,
        "window": {"tradingDays": len(trading_dates), "slots": len(slot_docs),
                   "first": trading_dates[0] if trading_dates else None,
                   "last": trading_dates[-1] if trading_dates else None},
        "dims": dims_out,
        "alerts": alerts,
        "skipped": skipped,
        "excluded": dict(EXCLUDED_DIMS),
        "amountVsSame": {"recordedDays": amount_recorded_days,
                         "ready": amount_recorded_days >= READY_DAYS_THRESHOLD,
                         "note": "重校准就绪≠启用：A-① 冻结门重启须随预登记重放一并裁决；"
                                 "该 vsSamePct=相邻交易日对日级口径，槽级口径是否另采由重校准预登记裁决"},
        "meta": {"windowTradingDays": WINDOW_TRADING_DAYS,
                 "mainAnchors": [n for n, _p, _e in MAIN_ANCHORS],
                 "reversedAnchors": [n for n, _p, _e in REVERSED_ANCHORS],
                 "alertThreshold": ALERT_THRESHOLD, "minSample": MIN_SAMPLE,
                 "generatedAt": datetime.now().isoformat(timespec="seconds")},
    }


# ---------------------------------------------------------------- IO（可 monkeypatch 边界）

def _get_db() -> Any:
    from backend.data.repositories import repository_factory

    return repository_factory.get_runtime_mongodb_database()


def load_window_slot_docs(db: Any, today: str) -> tuple[list[dict[str, Any]], list[str]]:
    """最近 WINDOW_TRADING_DAYS 个交易日的非 EOD 槽位文档（升序）+ 参与交易日列表。"""
    dates = sorted({str(d["tradingDate"]) for d in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
         "tradingDate": {"$lte": today}, "slotTime": {"$ne": "EOD"}},
        {"tradingDate": 1})})
    window_dates = dates[-WINDOW_TRADING_DAYS:]
    if not window_dates:
        return [], []
    docs = list(db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
         "tradingDate": {"$in": window_dates}, "slotTime": {"$ne": "EOD"}},
        {"emotionScore.dims": 1}))
    return docs, window_dates


def load_amount_recorded_days(db: Any) -> int:
    try:
        return int(db["market_daily_amount"].count_documents({"vsSamePct": {"$exists": True}}))
    except Exception:  # noqa: BLE001 — 就绪通知取数失败不阻断漂移报告
        return 0


def run_calib_drift_monitor(today: str, *, apply: bool = False) -> dict[str, Any]:
    """产出当月漂移报告。apply=False 只打印不落库（dry）。"""
    db = _get_db()
    docs, dates = load_window_slot_docs(db, today)
    if not docs:
        return {"ok": False, "errorCode": "no_window_docs",
                "message": f"{today} 前 {WINDOW_TRADING_DAYS} 交易日内无槽位情绪文档"}
    report = build_calib_drift_report(docs, trading_dates=dates,
                                      amount_recorded_days=load_amount_recorded_days(db))
    persisted = None
    if apply:
        from backend.operations.phase_monitor_persistence import persist_calib_drift

        persisted = persist_calib_drift(report)
        report["persistedId"] = persisted
    return {"ok": True, "alertCount": len(report["alerts"]), "report": report,
            "skippedDims": list(report["skipped"]), "persisted": persisted}


def main() -> int:
    parser = argparse.ArgumentParser(description="校准漂移监控（默认 dry 只打印零写库）")
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="YYYY-MM-DD（默认今天）")
    parser.add_argument("--apply", action="store_true", help="落库 phase_monitor calib_drift:<month>")
    args = parser.parse_args()
    result = run_calib_drift_monitor(args.date, apply=args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
