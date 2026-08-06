# quant-board/backend/analysis/theme/momentum_validation.py
"""题材动量验证：多帧滚动对比基线/调节共振分数与排序位移（研究用，不触回测引擎）。

v2 重构（2026-08-06）：`compare_theme_momentum_v1_v2` 对比旧 v1 融合（fuse_theme_resonance，
已废弃）与 v2 独立维度（compute_theme_momentum_v2）的题材排序/方向，回答
"v2 是否系统性改变题材排序、方向是否与市场一致"。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from backend.analysis.theme.momentum import (
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


def compare_theme_momentum_v1_v2(
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    """对比 v1 融合 vs v2 独立维度的题材排序位移与方向分布（回放验证）。

    输入 frames（含 hotThemes）；输出每题材 v2 score/direction + v1 融合分数代理
    （fuse_theme_resonance 已废弃，v1 代理 = 题材 heatScore 截面排序，用于位移对比）。
    """
    from backend.analysis.theme.daily_series import build_daily_series
    from backend.analysis.theme.momentum import compute_theme_momentum_v2
    from backend.analysis.theme.momentum_config import ThemeMomentumConfig

    sector_rows: list[dict[str, Any]] = []
    for frame in frames:
        for theme in frame.get("hotThemes") or []:
            if isinstance(theme, dict):
                theme = dict(theme)
                theme.setdefault("tradingDate", frame.get("tradingDate"))
                theme.setdefault("slotTime", frame.get("slotTime"))
                sector_rows.append(theme)

    daily = build_daily_series(sector_rows, [])
    result = compute_theme_momentum_v2(list(daily.values()), cfg=ThemeMomentumConfig())
    ranked_v2 = sorted(
        (v for v in result["factors"].values() if v.get("score") is not None),
        key=lambda item: -float(item["score"]),
    )
    rank_v2 = {item["themeId"]: idx for idx, item in enumerate(ranked_v2)}

    # v1 代理：题材 heatScore 截面排序（旧融合的题材强度来源）
    heat_by_theme: dict[str, float] = {}
    last_frame_themes = frames[-1].get("hotThemes") or []
    for theme in last_frame_themes:
        if isinstance(theme, dict):
            tid = str(theme.get("themeId") or theme.get("entityKey") or "")
            heat = theme.get("heatScore")
            if tid and heat is not None:
                heat_by_theme[tid] = float(heat)
    ranked_v1 = sorted(heat_by_theme.items(), key=lambda kv: -kv[1])
    rank_v1 = {tid: idx for idx, (tid, _) in enumerate(ranked_v1)}

    per_theme: dict[str, dict[str, Any]] = {}
    rank_shifts: list[int] = []
    for item in ranked_v2:
        tid = item["themeId"]
        v1_rank = rank_v1.get(tid)
        shift = v1_rank - rank_v2[tid] if v1_rank is not None else None
        if shift is not None:
            rank_shifts.append(shift)
        per_theme[tid] = {
            "themeName": item["themeName"],
            "v2Score": item["score"],
            "v2Direction": item["direction"],
            "v2Rank": rank_v2[tid],
            "v1HeatRank": v1_rank,
            "rankShift": shift,
        }

    return {
        "ok": True,
        "frameCount": len(ranked_v2),
        "meanAbsRankShift": round(_mean([abs(v) for v in rank_shifts]), 2),
        "maxRankShift": max((abs(v) for v in rank_shifts), default=0),
        "directionDistribution": {
            "up": sum(1 for v in result["factors"].values() if v.get("direction") == "up"),
            "neutral": sum(1 for v in result["factors"].values() if v.get("direction") == "neutral"),
            "down": sum(1 for v in result["factors"].values() if v.get("direction") == "down"),
        },
        "qualityFlags": result["qualityFlags"],
        "perTheme": per_theme,
    }
