# -*- coding: utf-8 -*-
"""F3 相位矩阵（融合总纲 ranktrend-phase-fusion-master-plan.md §5 合流点三）。

市场四带 × 个股五档 分层期望表——预登记读数（非交易规则，不接策略不改仓位）：
  市场带 = 标签日前一日 EOD 情绪分的引擎四带（band_of_score 单一事实源）
  个股档 = hotlist_jev_driver_labels.stockPhasePosition（start/ferment/climax/divergence/insufficient）
  结果   = T+1 早盘首槽（09:35/09:30）→ T+3 收盘 15:00 pctChange 差（与 C9 池代理同口径，逐股）

预登记纪律：标签覆盖交易日 < min_days 时拒跑（小样本有幻象，fail-visible 不产退化矩阵）；
当前仅 2026-09-30 单日 64 只 → 必然拒绝，待 F2 扩覆盖后重跑。
用法：./.venv/Scripts/python.exe -m backend.operations.phase_stock_matrix [--min-days 20] [--out ...]
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest.execution import BAND_TAGS, band_of_score

PHASE_TAGS = ("start", "ferment", "climax", "divergence", "insufficient")
ENTRY_SLOTS = ("09:35", "09:30")
EXIT_SLOT = "15:00"


def compute_matrix(cells: list[dict], labeled_days: int, min_days: int) -> dict:
    """纯聚合：cells=[{band, phase, retPct}]，labeled_days=标签覆盖交易日数（覆盖门在纯函数内便于测试）。"""
    if labeled_days < min_days:
        return {"ok": False,
                "reason": f"个股相位标签仅覆盖 {labeled_days} 个交易日（< {min_days}）——拒绝产出退化矩阵"
                          f"（预登记纪律：小样本有幻象）；先扩覆盖（融合总纲 F2）再重跑",
                "labeledDays": labeled_days, "minDays": min_days}
    grid: dict[str, dict[str, dict]] = {b: {p: {"n": 0, "rets": []} for p in PHASE_TAGS} for b in BAND_TAGS}
    for c in cells:
        slot = grid.get(c["band"], {}).get(c["phase"])
        if slot is None:  # 未知带/档（口径漂移防御）——fail-visible 计入 offGrid
            continue
        slot["n"] += 1
        if c.get("retPct") is not None:
            slot["rets"].append(c["retPct"])
    out_grid = {}
    for b in BAND_TAGS:
        out_grid[b] = {}
        for p in PHASE_TAGS:
            rets = grid[b][p]["rets"]
            out_grid[b][p] = {
                "n": grid[b][p]["n"],
                "withRet": len(rets),
                "meanPct": round(st.mean(rets), 2) if rets else None,
                "winRate": round(sum(1 for r in rets if r > 0) / len(rets), 3) if rets else None,
            }
    return {"ok": True, "labeledDays": labeled_days, "minDays": min_days, "cells": len(cells), "grid": out_grid}


def gather(db, start: str = "", end: str = "") -> tuple[list[dict], int, int]:
    """IO 层：标签 × 前日市场带 × T+1→T+3 逐股结果。返回 (cells, labeled_days, missing)。"""
    eod: dict[str, float] = {}
    for d in db["hotlist_sentiment"].find(
            {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD"},
            {"tradingDate": 1, "emotionScore.score": 1}):
        es = d.get("emotionScore")
        if isinstance(es, dict) and isinstance(es.get("score"), (int, float)):
            eod[str(d["tradingDate"])] = float(es["score"])
    dates = sorted(eod)
    prev_score = {dates[i]: dates[i - 1] for i in range(1, len(dates))}  # 前一交易日链

    q: dict = {"stockPhasePosition": {"$exists": True, "$ne": None}}
    if start:
        q["tradingDate"] = {"$gte": start, **({"$lte": end} if end else {})}
    labels = list(db["hotlist_jev_driver_labels"].find(
        q, {"tradingDate": 1, "code": 1, "stockPhasePosition": 1}))

    def snap(date: str, slots: tuple[str, ...]) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in db["snapshot_stock_rows"].find(
                {"type": "half_hour", "tradingDate": date, "slotTime": {"$in": list(slots)},
                 "pctChange": {"$exists": True, "$ne": None}}, {"code": 1, "pctChange": 1}):
            out.setdefault(str(r["code"]), float(r["pctChange"]))
        return out

    def entry_snap(date: str) -> dict[str, float]:
        """入场价=T+1 早盘首槽（ENTRY_SLOTS 序=优先序；同 code 多槽取序首，review P2 消除游标序依赖）。"""
        by_code: dict[str, dict[str, float]] = {}
        for slot in ENTRY_SLOTS:
            for code, pct in snap(date, (slot,)).items():
                by_code.setdefault(code, {})[slot] = pct
        out: dict[str, float] = {}
        for code, by_slot in by_code.items():
            for slot in ENTRY_SLOTS:
                if slot in by_slot:
                    out[code] = by_slot[slot]
                    break
        return out

    cells: list[dict] = []
    missing = 0
    for doc in labels:
        date = str(doc.get("tradingDate") or "")
        code = str(doc.get("code") or "")
        phase = str(doc.get("stockPhasePosition") or "")
        prev = prev_score.get(date)
        if not date or not code or not phase or prev is None:
            missing += 1
            continue
        i = dates.index(prev) if prev in dates else -1
        if i < 0 or i + 3 >= len(dates):
            missing += 1  # 无前日或 T+3 出窗
            continue
        entry_date, exit_date = dates[i + 1], dates[i + 3]
        sin, sout = entry_snap(entry_date), snap(exit_date, (EXIT_SLOT,))
        if code not in sin or code not in sout:
            missing += 1
            continue
        cells.append({"date": date, "code": code, "phase": phase,
                      "band": band_of_score(eod[prev]),
                      "retPct": round(sout[code] - sin[code], 2)})
    labeled_days = len({c["date"] for c in cells}) if cells else len({str(d.get("tradingDate")) for d in labels})
    return cells, labeled_days, missing


def main() -> int:
    parser = argparse.ArgumentParser(description="F3 相位矩阵（市场四带 × 个股五档分层期望表，预登记读数）")
    parser.add_argument("--start", default="", help="标签日起 YYYY-MM-DD（默认全期）")
    parser.add_argument("--end", default="", help="标签日止 YYYY-MM-DD")
    parser.add_argument("--min-days", dest="min_days", type=int, default=20,
                        help="标签覆盖交易日下限（默认 20；低于即拒跑）")
    parser.add_argument("--out", default="data/reports/phase-monitor/phase-stock-matrix.json")
    args = parser.parse_args()

    from backend.data.repositories.repository_factory import get_runtime_mongodb_database

    cells, labeled_days, missing = gather(get_runtime_mongodb_database(), args.start, args.end)
    out = compute_matrix(cells, labeled_days, args.min_days)
    out["missing"] = missing
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if not out["ok"]:
        print(f"[phase-stock-matrix] 拒跑：{out['reason']}", file=sys.stderr)
        return 1
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[phase-stock-matrix] -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
