# -*- coding: utf-8 -*-
"""M2 北极星读数 harness（ranktrend-phase-acceptance-design.md §3 分相位双线）。

好相位（offense，进攻职责）：wrxpf ≥ 0.78 ∧ 累计笔数 ≥ 60 ∧ 段内 maxDD ≤ 10%。
差相位（defense，防守职责）：不设 wrxpf 线；段内回撤或净损优于满仓穿越（二者其一）。
neutral：防守线宽松版同款计算，单列不判 pass（M3 适配的观察面）。
全部机械线自动产出；读数判定≠验收判定（验收走月度走廊，连续 3 期达线）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.operations.phase_trade_slice import round_trips_of, slice_trades

OFFENSE_LINE = {"wrxpf": 0.78, "trades": 60, "maxDD": -0.10}  # maxDD 为负值，段内 ≥ -0.10 为过


def worst_drawdown(equities: list[float]) -> float:
    """峰谷最大回撤（负数；空/单点 → 0.0）。"""
    peak = float("-inf")
    dd = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            dd = min(dd, (e - peak) / peak)
    return dd


def equity_phase_slices(equity_curve: list[dict], daily: dict[str, str]) -> dict:
    """equityCurve（帧对齐 1071 点）按入场日相位切段：每段 segReturn/段内 maxDD/点数。

    unknown 日不入任何段（fail-visible：unknown 点数单列）。
    """
    buckets: dict[str, list[float]] = {}
    unknown_points = 0
    for pt in equity_curve:
        day = str(pt.get("tradingDate") or "")
        phase = daily.get(day, "unknown")
        if phase == "unknown":
            unknown_points += 1
            continue
        buckets.setdefault(phase, []).append(float(pt.get("equity") or 0.0))
    out: dict = {"unknownPoints": unknown_points}
    for phase, eq in sorted(buckets.items()):
        out[phase] = {
            "equityPoints": len(eq),
            "segReturn": round(eq[-1] / eq[0] - 1, 4) if len(eq) >= 2 else None,
            "maxDD": round(worst_drawdown(eq), 4) if len(eq) >= 2 else None,
        }
    return out


def evaluate_northstar(by_phase: dict, slices: dict, full_window: dict) -> dict:
    """机械线判定（单期读数，非走廊判定）。

    by_phase: 相位桶交易读数（slice_trades 输出）；slices: equity_phase_slices 输出；
    full_window: {"maxDD", "segReturn"} 满仓穿越对照（equity_curve 全窗两指标）。
    """
    out: dict = {}
    for phase, tr in sorted(by_phase.items()):
        sl = slices.get(phase) or {}
        entry: dict = dict(tr)
        entry["maxDD"] = sl.get("maxDD")
        entry["segReturn"] = sl.get("segReturn")
        entry["equityPoints"] = sl.get("equityPoints")
        if phase == "offense":
            line = {
                "wrxpf": (tr.get("wrxpf") or 0) >= OFFENSE_LINE["wrxpf"],
                "trades": (tr.get("trades") or 0) >= OFFENSE_LINE["trades"],
                "maxDD": (sl.get("maxDD") is not None) and (sl["maxDD"] >= OFFENSE_LINE["maxDD"]),
            }
            entry["line"] = line
            entry["pass"] = all(line.values())
        elif phase in ("defense", "neutral"):
            dd_better = (sl.get("maxDD") is not None and full_window.get("maxDD") is not None
                         and sl["maxDD"] > full_window["maxDD"])
            loss_better = (tr.get("sumNetReturn") is not None and full_window.get("segReturn") is not None
                           and tr["sumNetReturn"] > full_window["segReturn"])
            entry["defenseLine"] = {"ddBetter": dd_better, "lossBetter": loss_better}
            entry["pass"] = dd_better or loss_better
        out[phase] = entry
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="M2 分相位北极星读数（只读）")
    parser.add_argument("--summary", default="data/reports/b-202610/t6-runs-formal/1-summary.json")
    parser.add_argument("--labels", default="data/reports/phase-monitor/phase-labels-v1.json")
    parser.add_argument("--candidate", default="sentiment_2b")
    parser.add_argument("--out", default="data/reports/phase-monitor/phase-northstar-v1.json")
    args = parser.parse_args()

    summary = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    trades = round_trips_of(summary)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    cand = labels["candidates"][args.candidate]
    daily = cand["dailyByMajority"]
    equity_curve = summary.get("equityCurve") or []
    daily_final = dict(daily)  # equity 段用 dailyByMajority（equity 无"入场时点"语义，段=日切片）

    by_phase = slice_trades(trades, daily_final, "phase")
    slices = equity_phase_slices(equity_curve, daily_final)
    full_eq = [float(pt.get("equity") or 0.0) for pt in equity_curve]
    full_window = {
        "maxDD": round(worst_drawdown(full_eq), 4) if len(full_eq) >= 2 else None,
        "segReturn": round(full_eq[-1] / full_eq[0] - 1, 4) if len(full_eq) >= 2 else None,
    }
    report = {
        "meta": {
            "candidate": args.candidate,
            "thresholds": cand.get("thresholds"),
            "summaryFile": Path(args.summary).name,
            "labelsGeneratedAt": (labels.get("meta") or {}).get("generatedAt"),
            "tradeCount": len(trades),
            "equityPoints": len(equity_curve),
        },
        "fullWindow": full_window,
        "byPhase": by_phase,
        "equitySlices": slices,
        "northstar": evaluate_northstar(by_phase, slices, full_window),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # Mongo 落库（前端可见化数据源；失败不阻断研究链，本地 JSON 仍是即时产物）
    from backend.operations.phase_monitor_persistence import persist_northstar

    persist_northstar(report, key=f"gen7-{args.candidate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
