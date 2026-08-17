# -*- coding: utf-8 -*-
"""趋势（rankTrend）信号参数搜索（backend/operations，2026-08-17）。

与共振搜索同模式（用户决策：主目标改善趋势维对 synergy 投票的贡献，产出建议参数不写回默认值）：
- 评估：replay(config) → tier_forward_returns(dimension=rankTrend/synergy, horizon=1)；
  评分 = 2×clamp(synergy saEx,0,0.15) + 0.5×synergy passHard − 0.8×synergy fail
        + 10×clamp(rankTrend saEx,0,0.05) + 0.2×rankTrend passHard − 0.5×max(0, trend unknown − 0.10)。
- 搜索空间：档位阈值 `tierRankTrendStrongMin`（0.5 默认）/ `tierRankTrendConfirmMin`（0.25 默认），
  约束 0 < confirm < strong <= 1。趋势维无独立连续分权重（档位只消费 base.signal + |combinedScore|）。
- Phase 1：单维敏感性（8 次 evaluate）；Phase 2：定向组合网格；Phase 3：walk-forward 样本外复核。
- 基线（769 帧，校准诊断）：rankTrend h1 S/A/B excess +0.064/+0.037/−0.013（S/A 加权 0.0455，
  边缘 <0.05，passHard=False）；synergy saEx 0.0651（passHard=True）。

输出：data/reports/ranktrend-parameter-search.json
fail-visible：样本不足/缺维如实输出，不伪造 0。
"""
from __future__ import annotations

import argparse
import json
import math
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
from backend.optimization.validation import split_frames

REPORT_PATH = Path(r"D:\dragon-board\quant-board\data\reports\ranktrend-parameter-search.json")
DIMENSION = "rankTrend"

# ── 搜索空间（档位阈值；约束 0 < confirm < strong <= 1）──────────────────────────
TIER_STEPS: dict[str, list[Any]] = {
    "tierRankTrendStrongMin": [0.3, 0.4, 0.5, 0.6, 0.7],
    "tierRankTrendConfirmMin": [0.15, 0.2, 0.25, 0.3, 0.35],
}
# Phase 2 定向组合（Phase 1 结论驱动的 strong × confirm 网格，均满足 confirm < strong）
JOINT_COMBOS: list[tuple[str, dict[str, Any]]] = [
    ("strong_0.4 + confirm_0.2", {"tierRankTrendStrongMin": 0.4, "tierRankTrendConfirmMin": 0.2}),
    ("strong_0.4 + confirm_0.3", {"tierRankTrendStrongMin": 0.4, "tierRankTrendConfirmMin": 0.3}),
    ("strong_0.6 + confirm_0.2", {"tierRankTrendStrongMin": 0.6, "tierRankTrendConfirmMin": 0.2}),
    ("strong_0.6 + confirm_0.3", {"tierRankTrendStrongMin": 0.6, "tierRankTrendConfirmMin": 0.3}),
    ("strong_0.7 + confirm_0.3", {"tierRankTrendStrongMin": 0.7, "tierRankTrendConfirmMin": 0.3}),
    ("strong_0.7 + confirm_0.35", {"tierRankTrendStrongMin": 0.7, "tierRankTrendConfirmMin": 0.35}),
]
# Phase 3 复核配置
WALKFORWARD_CONFIGS: list[tuple[str, dict[str, Any]]] = [
    ("baseline", {}),
    ("strong_0.6", {"tierRankTrendStrongMin": 0.6}),
    ("strong_0.4", {"tierRankTrendStrongMin": 0.4}),
    ("strong_0.6 + confirm_0.3", {"tierRankTrendStrongMin": 0.6, "tierRankTrendConfirmMin": 0.3}),
]


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def evaluate(config: RankTrendConfig, frames: list[dict[str, Any]]) -> dict[str, Any]:
    """replay + rankTrend/synergy h1 tier 统计。返回评分与主/次指标。"""
    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(frames, window_size=50)
    trend = tier_forward_returns(signals, frames, horizon=1, dimension=DIMENSION)
    syn = tier_forward_returns(signals, frames, horizon=1, dimension="synergy")

    trend_sa = sa_excess_of(trend)
    syn_sa = sa_excess_of(syn)
    trend_unknown = float(trend.get("unknownRate") or 0)
    syn_pass = bool((syn.get("monotonicity") or {}).get("passHardConstraint"))
    trend_pass = bool((trend.get("monotonicity") or {}).get("passHardConstraint"))

    score = 0.0
    if syn_sa is not None:
        score += 2.0 * _clamp(syn_sa, 0.0, 0.15)
    score += 0.5 if syn_pass else -0.8
    if trend_sa is not None:
        score += 1.0 * _clamp(trend_sa, 0.0, 0.05) * 10.0
    score += 0.2 if trend_pass else 0.0
    score -= 0.5 * max(0.0, trend_unknown - 0.10)
    return {
        "score": round(score, 4),
        "synergy": _tier_summary(syn),
        "rankTrend": _tier_summary(trend),
        "signalCount": len(signals),
    }


def _fmt(result: dict[str, Any]) -> str:
    s, t = result["synergy"], result["rankTrend"]
    return (
        f"score={result['score']} syn(saEx={s['saEx']} pass={s['passHard']}) "
        f"trend(saEx={t['saEx']} pass={t['passHard']} unk={t['unknownRate']})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="趋势（rankTrend）信号参数搜索（只读，不写回默认值）")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--phase", type=int, default=1, choices=(1, 2, 3), help="1=单维敏感性, 2=定向组合, 3=walk-forward 复核")
    parser.add_argument("--resume", action="store_true", help="复用已有报告已完成候选")
    args = parser.parse_args()

    report: dict[str, Any] = {}
    if args.resume and REPORT_PATH.exists():
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        print(f"[resume] loaded report with {len(report.get('sensitivity', {}))} sensitivity entries", file=sys.stderr)

    frames = load_frames(args.start, args.end)
    print(f"[search] frames={len(frames)} window={args.start}~{args.end}", file=sys.stderr)
    if not frames:
        print("[search] no frames loaded — aborting", file=sys.stderr)
        return 1

    if "baseline" not in report:
        print("[search] evaluating baseline ...", file=sys.stderr)
        t0 = time.time()
        base = evaluate(RankTrendConfig(), frames)
        base["elapsedSec"] = round(time.time() - t0, 1)
        print(f"[baseline] {_fmt(base)} ({base['elapsedSec']}s)", file=sys.stderr)
        report["baseline"] = base
    else:
        print(f"[baseline] (cached) {_fmt(report['baseline'])}", file=sys.stderr)

    if args.phase == 1:
        sensitivity = report.setdefault("sensitivity", {})
        for key, candidates in TIER_STEPS.items():
            entries = sensitivity.setdefault(key, {})
            for cand in candidates:
                cand_key = json.dumps(cand)
                if args.resume and cand_key in entries:
                    print(f"[skip] {key}={cand} (cached)", file=sys.stderr)
                    continue
                if cand == getattr(RankTrendConfig(), key):
                    entries[cand_key] = {"note": "= default, skipped"}
                    continue
                trial = RankTrendConfig(**{**dict(RankTrendConfig().__dict__), key: cand})
                print(f"[phase1] {key}={cand} ...", file=sys.stderr)
                t0 = time.time()
                result = evaluate(trial, frames)
                result["elapsedSec"] = round(time.time() - t0, 1)
                entries[cand_key] = result
                print(f"[phase1] {key}={cand} -> {_fmt(result)} ({result['elapsedSec']}s)", file=sys.stderr)
                REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
                REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    elif args.phase == 2:
        base_score = report["baseline"]["score"]
        combos: dict[str, Any] = {}
        best_score, best_params = base_score, {}
        for label, params in JOINT_COMBOS:
            trial = RankTrendConfig(**{**dict(RankTrendConfig().__dict__), **params})
            print(f"[phase2] {label} -> {params} ...", file=sys.stderr)
            t0 = time.time()
            result = evaluate(trial, frames)
            result["elapsedSec"] = round(time.time() - t0, 1)
            combos[label] = {"params": params, "result": result}
            print(f"[phase2] {label} -> {_fmt(result)} ({result['elapsedSec']}s)", file=sys.stderr)
            if result["score"] > best_score:
                best_score, best_params = result["score"], params
        report["phase2"] = {
            "baseScore": base_score,
            "combos": combos,
            "bestParams": best_params,
            "bestScore": round(best_score, 4),
            "improvementVsBaseline": round(best_score - base_score, 4),
        }
        print(f"[phase2] best={best_params} score={best_score} (baseline {base_score})", file=sys.stderr)

    elif args.phase == 3:
        split = split_frames(frames, {"validation_mode": "chronological", "validation_ratio": 0.3})
        train_frames = split["train_frames"]
        validation_frames = split["validation_frames"]
        meta = split["metadata"]
        print(
            f"[phase3] split: train={len(train_frames)} ({meta['train']['startDate']}~{meta['train']['endDate']}) / "
            f"validation={len(validation_frames)} ({meta['validation']['startDate']}~{meta['validation']['endDate']})",
            file=sys.stderr,
        )
        wf = report.setdefault("walkforward", {})
        wf["split"] = meta
        for label, params in WALKFORWARD_CONFIGS:
            trial = RankTrendConfig(**{**dict(RankTrendConfig().__dict__), **params})
            print(f"[phase3] {label} replay ...", file=sys.stderr)
            t0 = time.time()
            signals = RankTrendPythonEngine(config=trial).replay(frames, window_size=50)
            entry: dict[str, Any] = {"params": params, "replaySec": round(time.time() - t0, 1)}
            for seg_name, seg_frames in (("train", train_frames), ("validation", validation_frames)):
                t1 = time.time()
                trend = tier_forward_returns(signals, seg_frames, horizon=1, dimension=DIMENSION)
                syn = tier_forward_returns(signals, seg_frames, horizon=1, dimension="synergy")
                entry[seg_name] = {"synergy": _tier_summary(syn), "rankTrend": _tier_summary(trend)}
                entry[seg_name + "ElapsedSec"] = round(time.time() - t1, 1)
            wf[label] = entry
            v = entry["validation"]
            print(
                f"[phase3] {label}: train syn saEx={entry['train']['synergy']['saEx']} "
                f"trend saEx={entry['train']['rankTrend']['saEx']} | "
                f"validation syn saEx={v['synergy']['saEx']} trend saEx={v['rankTrend']['saEx']}",
                file=sys.stderr,
            )
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        base_v = (wf.get("baseline") or {}).get("validation") or {}
        base_trend = base_v.get("rankTrend") or {}
        verdicts: dict[str, str] = {}
        for label, entry in wf.items():
            if label == "split":
                continue
            v = entry.get("validation") or {}
            trend = v.get("rankTrend") or {}
            t_sa = trend.get("saEx")
            if t_sa is None:
                verdicts[label] = "no_validation_samples"
            elif base_trend.get("saEx") is not None and t_sa >= float(base_trend.get("saEx")) - 1e-9:
                verdicts[label] = "outperform_or_hold"
            else:
                verdicts[label] = "underperform_baseline"
        wf["verdicts"] = verdicts
        print(f"[phase3] verdicts: {verdicts}", file=sys.stderr)

    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[search] report written to {REPORT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
