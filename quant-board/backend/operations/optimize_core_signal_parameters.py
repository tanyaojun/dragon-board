# -*- coding: utf-8 -*-
"""核心信号参数逐参数 5 档扫描（backend/operations，2026-08-17）。

第 2 轮：**【共振】Jump 跳跃值参数构成**逐参数 5 档扫描（趋势研究已收敛 §8.4-§8.7）。
jumpDeltaPct（触发阈值）/ jumpResetLookback（重置窗口）/ jumpSustainCount（持续判定）
各 5 档候选（含当前默认，多档位防过拟合——观察单调性/峰值稳定性）。

评估：replay(config) → rankTrend/resonance/synergy h1 tier 统计；
score 以 synergy 合并档为主、focus 维（resonance）次之（沿用阶段 7 口径）。

输出：data/reports/core-signal-parameter-jump.json
fail-visible：样本不足/缺维如实输出，不伪造 0。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns
from backend.operations.optimize_resonance_parameters import (
    load_frames,
    sa_excess_of,
    _tier_summary,
)

REPORT_PATH = Path(r"D:\dragon-board\quant-board\data\reports\core-signal-parameter-volumeprice.json")

# 每个参数 5 档候选（含当前默认，防过拟合——多档位观察单调性/峰值稳定性）。
# dimension = 该参数主要影响的单维（评估 focus）。第 3 轮：**【量价】因子参数**（2026-08-17）。
PARAM_TRIALS: list[dict[str, Any]] = [
    {"param": "volumePriceBase", "desc": "量价：基准分", "dimension": "volumePrice", "levels": [40.0, 45.0, 50.0, 55.0, 60.0]},
    {
        "param": "volumePriceOverVolumeRatio",
        "desc": "量价：过度放量阈值",
        "dimension": "volumePrice",
        "levels": [1.5, 2.0, 2.5, 3.0, 3.5],
    },
    {
        "param": "volumePriceAbnormalFundRatio",
        "desc": "量价：资金对倒阈值（zljzb%）",
        "dimension": "volumePrice",
        "levels": [10.0, 15.0, 20.0, 25.0, 30.0],
    },
    {
        "param": "volumePriceShrinkRatio",
        "desc": "量价：缩量阈值",
        "dimension": "volumePrice",
        "levels": [0.75, 0.85, 0.95, 1.05, 1.15],
    },
    {
        "param": "volumePriceMildRatio",
        "desc": "量价：温和放量阈值",
        "dimension": "volumePrice",
        "levels": [0.95, 1.0, 1.05, 1.1, 1.15],
    },
    {
        "param": "volumePriceNormalRatio",
        "desc": "量价：量比正常上限（2026-08-17 参数化）",
        "dimension": "volumePrice",
        "levels": [1.5, 1.75, 2.0, 2.25, 2.5],
    },
    {
        "param": "volumePriceDirectionBuckets",
        "desc": "量价：方向八档分值缩放（×0.8/0.9/1.0/1.1/1.2）",
        "dimension": "volumePrice",
        "levels": [
            [12.0, 9.6, 8.0, 6.4, 4.8, 3.2, 1.6, 0.8],
            [13.5, 10.8, 9.0, 7.2, 5.4, 3.6, 1.8, 0.9],
            [15.0, 12.0, 10.0, 8.0, 6.0, 4.0, 2.0, 1.0],
            [16.5, 13.2, 11.0, 8.8, 6.6, 4.4, 2.2, 1.1],
            [18.0, 14.4, 12.0, 9.6, 7.2, 4.8, 2.4, 1.2],
        ],
    },
]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def evaluate(config: RankTrendConfig, frames: list[dict[str, Any]], focus_dim: str) -> dict[str, Any]:
    """replay + rankTrend/resonance/volumePrice/synergy h1 统计。score 以 synergy 合并档为主、focus 维次之。"""
    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(frames, window_size=50)
    trend = tier_forward_returns(signals, frames, horizon=1, dimension="rankTrend")
    res = tier_forward_returns(signals, frames, horizon=1, dimension="resonance")
    vp = tier_forward_returns(signals, frames, horizon=1, dimension="volumePrice")
    syn = tier_forward_returns(signals, frames, horizon=1, dimension="synergy")

    focus = {"rankTrend": trend, "resonance": res, "volumePrice": vp}.get(focus_dim, trend)
    focus_sa = sa_excess_of(focus)
    syn_sa = sa_excess_of(syn)
    focus_unknown = float(focus.get("unknownRate") or 0)
    syn_pass = bool((syn.get("monotonicity") or {}).get("passHardConstraint"))
    focus_pass = bool((focus.get("monotonicity") or {}).get("passHardConstraint"))

    score = 0.0
    if syn_sa is not None:
        score += 2.0 * _clamp(syn_sa, 0.0, 0.15)
    score += 0.5 if syn_pass else -0.8
    if focus_sa is not None:
        score += 1.0 * _clamp(focus_sa, 0.0, 0.05) * 10.0
    score += 0.2 if focus_pass else 0.0
    score -= 0.5 * max(0.0, focus_unknown - 0.10)
    return {
        "score": round(score, 4),
        "synergy": _tier_summary(syn),
        "rankTrend": _tier_summary(trend),
        "resonance": _tier_summary(res),
        "signalCount": len(signals),
    }


def _fmt(result: dict[str, Any], focus_dim: str) -> str:
    focus = result["rankTrend"] if focus_dim == "rankTrend" else result["resonance"]
    return (
        f"score={result['score']} syn(saEx={result['synergy']['saEx']} pass={result['synergy']['passHard']}) "
        f"focus[{focus_dim}](saEx={focus['saEx']} pass={focus['passHard']} unk={focus['unknownRate']})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="核心信号参数逐参数 3 档扫描（趋势 3 子维度 + 共振 Jump）")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    report: dict[str, Any] = {}
    if args.resume and REPORT_PATH.exists():
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        print(f"[resume] loaded report params: {list(report.get('params', {}).keys())}", file=sys.stderr)

    frames = load_frames(args.start, args.end)
    print(f"[param-trials] frames={len(frames)} window={args.start}~{args.end}", file=sys.stderr)
    if not frames:
        print("[param-trials] no frames loaded — aborting", file=sys.stderr)
        return 1

    if "baseline" not in report:
        print("[param-trials] evaluating baseline (default config) ...", file=sys.stderr)
        t0 = time.time()
        base = evaluate(RankTrendConfig(), frames, "rankTrend")
        base["elapsedSec"] = round(time.time() - t0, 1)
        print(f"[baseline] {_fmt(base, 'rankTrend')} ({base['elapsedSec']}s)", file=sys.stderr)
        report["baseline"] = base
    else:
        print(f"[baseline] (cached) {_fmt(report['baseline'], 'rankTrend')}", file=sys.stderr)

    params = report.setdefault("params", {})
    for spec in PARAM_TRIALS:
        param = spec["param"]
        entry = params.setdefault(param, {"desc": spec["desc"], "dimension": spec["dimension"], "levels": {}})
        for level in spec["levels"]:
            level_key = json.dumps(level)
            if level_key in entry["levels"]:
                print(f"[skip] {param}={level} (cached)", file=sys.stderr)
                continue
            if level == getattr(RankTrendConfig(), param):
                entry["levels"][level_key] = {"level": level, "result": "= default (baseline)"}
                continue
            trial = RankTrendConfig(**{**dict(RankTrendConfig().__dict__), param: level})
            print(f"[param-trials] {param}={level} ...", file=sys.stderr)
            t0 = time.time()
            result = evaluate(trial, frames, spec["dimension"])
            result["elapsedSec"] = round(time.time() - t0, 1)
            entry["levels"][level_key] = {"level": level, "result": result}
            print(f"[param-trials] {param}={level} -> {_fmt(result, spec['dimension'])} ({result['elapsedSec']}s)", file=sys.stderr)
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[param-trials] report written to {REPORT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
