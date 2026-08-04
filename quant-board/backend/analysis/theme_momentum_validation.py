# quant-board/backend/analysis/theme_momentum_validation.py
"""题材动量验证：多帧滚动对比基线/调节共振分数与排序位移（研究用，不触回测引擎）。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.analysis.theme_momentum import (
    THEME_SERIES_MIN_BARS,
    compute_theme_momentum_series,
    fuse_theme_resonance,
    stock_theme_exposure,
)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compare_theme_momentum_rolling(
    frames: list[dict[str, Any]],
    base_resonance_by_frame: list[dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    """逐帧（bars >= THEME_SERIES_MIN_BARS）滚动对比基线/调节分数与排序位移。

    base_resonance_by_frame 与 frames 等长，每项为 {code: 该帧基础共振}。"""
    momentum_series = compute_theme_momentum_series(frames)
    if not momentum_series["frames"]:
        return {"ok": False, "reason": "empty_frames"}
    aggregate: dict[str, Any] = {
        "adjustedCount": 0,
        "insufficientCount": 0,
        "adjustments": [],
        "rankShifts": [],
        "adjustmentByLifecycle": defaultdict(list),
        "directionDistribution": defaultdict(int),
    }
    per_frame: list[dict[str, Any]] = []
    for index, frame in enumerate(frames):
        if index < THEME_SERIES_MIN_BARS - 1:
            continue
        frame_momentum = momentum_series["frames"][index]
        base_by_code = (
            base_resonance_by_frame[index]
            if index < len(base_resonance_by_frame)
            else {}
        )
        rows: list[dict[str, Any]] = []
        for stock in frame.get("stocks") or []:
            code = str(stock.get("code") or "")
            base = base_by_code.get(code)
            if not base:
                continue
            exposure = stock_theme_exposure(stock, frame.get("hotThemes") or [])
            fused = fuse_theme_resonance(base, exposure, frame_momentum)
            theme = fused.get("theme") or {}
            rows.append({
                "code": code,
                "baseScore": round(float(base.get("score") or 0)),
                "fusedScore": round(float(fused.get("score") or 0)),
                "adjustment": float(theme.get("adjustment") or 0),
                "themeStatus": str(theme.get("status") or "insufficient"),
                "lifecycle": str(theme.get("themeLifecycle") or "neutral"),
                "direction": str(theme.get("themeMomentumDirection") or "hold"),
            })
        rows.sort(key=lambda item: item["fusedScore"], reverse=True)
        base_order = sorted(rows, key=lambda item: item["baseScore"], reverse=True)
        base_index = {item["code"]: position for position, item in enumerate(base_order)}
        for position, item in enumerate(rows):
            aggregate["adjustments"].append(item["adjustment"])
            aggregate["rankShifts"].append(base_index[item["code"]] - position)
            aggregate["adjustmentByLifecycle"][item["lifecycle"]].append(item["adjustment"])
            aggregate["directionDistribution"][item["direction"]] += 1
            if item["themeStatus"] == "ok":
                aggregate["adjustedCount"] += 1
            else:
                aggregate["insufficientCount"] += 1
        per_frame.append({
            "frameKey": f"{frame.get('tradingDate')} {frame.get('slotTime')}".strip(),
            "themeSampleCount": frame_momentum["themeSampleCount"],
            "rows": rows,
        })
    adjustments = aggregate["adjustments"]
    rank_shifts = aggregate["rankShifts"]
    return {
        "ok": True,
        "frameCount": len(per_frame),
        "themeSampleCountMin": min(
            (item["themeSampleCount"] for item in per_frame), default=0
        ),
        "adjustedCount": aggregate["adjustedCount"],
        "insufficientCount": aggregate["insufficientCount"],
        "meanAdjustment": round(_mean(adjustments), 2),
        "meanAbsAdjustment": round(_mean([abs(value) for value in adjustments]), 2),
        "meanAbsRankShift": round(_mean([abs(value) for value in rank_shifts]), 2),
        "maxRankShift": max((abs(value) for value in rank_shifts), default=0),
        "adjustmentByLifecycle": {
            lifecycle: round(_mean(values), 2)
            for lifecycle, values in aggregate["adjustmentByLifecycle"].items()
        },
        "directionDistribution": dict(aggregate["directionDistribution"]),
        "frames": per_frame,
    }
