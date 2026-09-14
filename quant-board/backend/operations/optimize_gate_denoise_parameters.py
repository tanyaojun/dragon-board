# -*- coding: utf-8 -*-
"""WP2 2c 门控去噪参数扫描（backend/operations，2026-09-09）。

三参数单变量扫描（spec 2026-09-06-ranktrend-gate-denoise-design §2c，longterm-test 8 步流程）：
- lifecycleConfirmFrames ∈ {2,3}（K；spec 显式三档 {1,2,3}，1=默认即 baseline）
- regimeScoreEmaAlpha ∈ {0.9, 0.75, 0.5, 0.25}（5 档含默认 1.0）
- regimeStateHysteresis=True × regimeStrongHysteresisBand ∈ {2.5, 5.0, 7.5}（迟滞 3 档；默认关）

评估口径：单次 replay(config) → WP3.2 翻转率（collect_flip_report，三类门控）
+ longterm-test 口径 h1 tier 统计（synergy 主 + focus=rankTrend）。效果度量=翻转率下降；
采纳判定=证实类（干净窗口样本外 synergy saEx ≥0.05 且 passHard、跨窗口稳健）才动默认值。

窗口纪律（data_windows）：
- 决策扫描默认 2026-04-15~2026-07-31（TRAIN/VAL/TEST）；FINAL（8/1-8/14）冻结，
  仅 --purpose report 允许（默认配置 8/1-8/31 复现 WP3.2 基线属报告用途，作接线自检）。
- OOS：2026-08-15~2026-08-31（决策期后生成，准样本外）+ 2026-09-01~2026-09-09（未见窗口；
  9/7 前无槽位情绪文档，sentiment 为 EOD stale 回退——各档一致，不影响相对比较；
  且 meta={} 默认 research 模式本就不注入 sentiment）。

用法：
  python -m backend.operations.optimize_gate_denoise_parameters [--start ... --end ...]
      [--purpose scan|report] [--baseline-only] [--overrides '{"lifecycleConfirmFrames":2}']
      [--out <path>]

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
from backend.analysis.ranktrend.research.regime_saex import regime_saex_stats
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns
from backend.operations.diagnose_gate_flip_rate import collect_flip_report
from backend.operations.optimize_core_signal_parameters import _clamp
from backend.operations.optimize_resonance_parameters import _tier_summary, load_frames, sa_excess_of

REPORT_DIR = Path(r"D:\dragon-board\quant-board\data\reports")

# 单变量扫描档位（含默认档由 baseline 承担，不重复跑）。K 显式三档来自 spec §2c。
PARAM_TRIALS: list[dict[str, Any]] = [
    {"key": "K=2", "desc": "lifecycle 门控 2 帧确认", "overrides": {"lifecycleConfirmFrames": 2}},
    {"key": "K=3", "desc": "lifecycle 门控 3 帧确认", "overrides": {"lifecycleConfirmFrames": 3}},
    {"key": "alpha=0.9", "desc": "regime score EMA α=0.9", "overrides": {"regimeScoreEmaAlpha": 0.9}},
    {"key": "alpha=0.75", "desc": "regime score EMA α=0.75", "overrides": {"regimeScoreEmaAlpha": 0.75}},
    {"key": "alpha=0.5", "desc": "regime score EMA α=0.5", "overrides": {"regimeScoreEmaAlpha": 0.5}},
    {"key": "alpha=0.25", "desc": "regime score EMA α=0.25", "overrides": {"regimeScoreEmaAlpha": 0.25}},
    {"key": "hyst-band2.5", "desc": "迟滞开 band=2.5", "overrides": {"regimeStateHysteresis": True, "regimeStrongHysteresisBand": 2.5}},
    {"key": "hyst-band5.0", "desc": "迟滞开 band=5.0（默认带宽）", "overrides": {"regimeStateHysteresis": True, "regimeStrongHysteresisBand": 5.0}},
    {"key": "hyst-band7.5", "desc": "迟滞开 band=7.5", "overrides": {"regimeStateHysteresis": True, "regimeStrongHysteresisBand": 7.5}},
]


def evaluate_gate(config: RankTrendConfig, frames: list[dict[str, Any]]) -> dict[str, Any]:
    """单次 replay 同时产出翻转率 + h1 tier 统计。

    score 公式与 optimize_core_signal_parameters.evaluate 保持一致（第 2/3 轮口径）；
    如该处升级需同步本函数。
    """
    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(frames, meta={})
    trend = tier_forward_returns(signals, frames, horizon=1, dimension="rankTrend")
    syn = tier_forward_returns(signals, frames, horizon=1, dimension="synergy")
    # 分状态视图（阶段 14 盲区闭环）：ALL 口径被大状态体量稀释，桶内失效不可见。
    # 只对 synergy 主口径分桶（rankTrend 关注维不重复，控制扫描成本）；
    # 桶内 passHard 为桶内口径，样本不足（S<30）如实判 False，区分看 _tier_summary.distribution。
    regime = regime_saex_stats(signals, frames, horizon=1, dimension="synergy")
    regime_view = {state: _tier_summary(stats) for state, stats in regime["states"].items()}

    syn_sa = sa_excess_of(syn)
    trend_sa = sa_excess_of(trend)
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

    flip = collect_flip_report(signals)
    return {
        "score": round(score, 4),
        "synergy": _tier_summary(syn),
        "rankTrend": _tier_summary(trend),
        "regimeView": regime_view,
        "regimeStateCounts": regime["stateCounts"],
        "signalCount": len(signals),
        "flipRates": flip["flip_rates"],
        "flipCounts": flip["flip_counts"],
        "stageFlipRates": flip.get("stage_flip_rates"),
        "comparablePairs": flip["comparable_pairs"],
        "missingFields": flip.get("missing_fields"),
    }


def _fmt(result: dict[str, Any]) -> str:
    flips = result["flipRates"]
    # 分状态摘要（regimeView 为 2026-09-10 新增字段，旧缓存报告 resume 时缺省不打印）
    states = " ".join(
        f"{state}(saEx={summary['saEx']} pass={summary['passHard']})"
        for state, summary in (result.get("regimeView") or {}).items()
    )
    return (
        f"score={result['score']} syn(saEx={result['synergy']['saEx']} pass={result['synergy']['passHard']}) "
        f"flip(veto={flips['veto']:.5f} bd={flips['bd_downgrade']:.5f} regime={flips['regime_state']:.5f})"
        + (f" | {states}" if states else "")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="WP2 2c 门控去噪参数扫描（翻转率 + h1 tier 双口径）")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--purpose", default="scan", choices=["scan", "report"],
                        help="scan=参数决策（禁 FINAL 窗口）；report=报告用途（允许 8 月对齐复现）")
    parser.add_argument("--baseline-only", action="store_true", help="只评估默认配置（接线自检）")
    parser.add_argument("--overrides", default="", help="临时组合验证：JSON dict 形式的 config 覆盖")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from backend.optimization.data_windows import assert_not_frozen

    frames = load_frames(args.start, args.end)
    print(f"[gate-scan] frames={len(frames)} window={args.start}~{args.end} purpose={args.purpose}", file=sys.stderr)
    if not frames:
        print("[gate-scan] no frames loaded — aborting", file=sys.stderr)
        return 1
    # 冻结守卫：参数决策（scan）禁止 FINAL（8/1-8/14）帧进入
    assert_not_frozen(frames, args.purpose)

    out_path = Path(args.out) if args.out else REPORT_DIR / f"gate-denoise-scan_{args.start}_{args.end}.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] loaded report keys: {list(report.get('trials', {}).keys())}", file=sys.stderr)
    report.setdefault("window", {"start": args.start, "end": args.end, "frameCount": len(frames)})
    report["purpose"] = args.purpose

    if "baseline" not in report:
        print("[gate-scan] evaluating baseline (default config) ...", file=sys.stderr)
        t0 = time.time()
        base = evaluate_gate(RankTrendConfig(), frames)
        base["elapsedSec"] = round(time.time() - t0, 1)
        report["baseline"] = base
        print(f"[baseline] {_fmt(base)} ({base['elapsedSec']}s)", file=sys.stderr)
    else:
        print(f"[baseline] (cached) {_fmt(report['baseline'])}", file=sys.stderr)

    trials = report.setdefault("trials", {})
    run_specs: list[dict[str, Any]] = []
    if args.overrides:
        overrides = json.loads(args.overrides)
        key = "combo:" + ",".join(f"{k}={v}" for k, v in overrides.items())
        run_specs.append({"key": key, "desc": "ad-hoc combo", "overrides": overrides})
    elif not args.baseline_only:
        run_specs = PARAM_TRIALS

    for spec in run_specs:
        if spec["key"] in trials:
            print(f"[skip] {spec['key']} (cached)", file=sys.stderr)
            continue
        config_kwargs = {**dict(RankTrendConfig().__dict__), **spec["overrides"]}
        trial = RankTrendConfig(**config_kwargs)
        print(f"[gate-scan] {spec['key']} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_gate(trial, frames)
        result["elapsedSec"] = round(time.time() - t0, 1)
        trials[spec["key"]] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        print(f"[gate-scan] {spec['key']} -> {_fmt(result)} ({result['elapsedSec']}s)", file=sys.stderr)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[gate-scan] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
