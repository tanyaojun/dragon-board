# -*- coding: utf-8 -*-
"""趋势因子参数补扫（backend/operations，2026-09-09，阶段 13）。

L1 台账 §2b 缺口：MACD 周期本体（macdFast/Slow/Signal）从未扫描、8.4 只扫金叉侧
（死叉侧 macdDeathGapScaleRatio/macdDeathStrongGapMin/macdRawScoreWeights 全漏）、
zeroCross 合成（momentumZeroWeights/momentumZeroStrongConfirmBonus）未扫、
技术辅助决策阈值（buyScoreThreshold/sellScoreThreshold，runtime 决策合成消费）未扫。
MA5/MA10 为显示字段（technical.py movingAverage 无决策消费方）不在扫描范围。

评估口径与 optimize_gate_denoise_parameters.evaluate_gate 完全一致（单次 replay →
h1 tier 统计 score + WP3.2 三类翻转率）；窗口纪律同（决策 4/15-7/31，FINAL 冻结，
OOS 8/15-8/31 + 9/1-9/9）。

用法：
  python -m backend.operations.optimize_trend_factor_parameters [--start ... --end ...]
      [--purpose scan|report] [--baseline-only] [--overrides '{"macdFast":15}'] [--out <path>]

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

from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, _fmt, evaluate_gate
from backend.operations.optimize_resonance_parameters import load_frames

# 单变量扫描档位（默认档由 baseline 承担；5 档原则=默认两侧各 1-2 档）。
# MACD 周期单变量扫描时其余周期保持默认，均满足 config 校验 macdSlow > macdFast。
PARAM_TRIALS: list[dict[str, Any]] = [
    # A 组：MACD 周期本体（默认 13/21/8）
    {"key": "macdFast=11", "desc": "MACD 快线周期 11", "overrides": {"macdFast": 11}},
    {"key": "macdFast=15", "desc": "MACD 快线周期 15", "overrides": {"macdFast": 15}},
    {"key": "macdSlow=17", "desc": "MACD 慢线周期 17", "overrides": {"macdSlow": 17}},
    {"key": "macdSlow=26", "desc": "MACD 慢线周期 26", "overrides": {"macdSlow": 26}},
    {"key": "macdSignal=5", "desc": "MACD 信号线周期 5", "overrides": {"macdSignal": 5}},
    {"key": "macdSignal=12", "desc": "MACD 信号线周期 12", "overrides": {"macdSignal": 12}},
    # B 组：死叉侧 + rawScore 权重（8.4 只扫金叉侧）
    {"key": "deathScale=0.06", "desc": "死叉 gap 缩放 0.06", "overrides": {"macdDeathGapScaleRatio": 0.06}},
    {"key": "deathScale=0.24", "desc": "死叉 gap 缩放 0.24", "overrides": {"macdDeathGapScaleRatio": 0.24}},
    {"key": "deathStrong=0.10", "desc": "死叉 strong_gap 阈值 0.10", "overrides": {"macdDeathStrongGapMin": 0.10}},
    {"key": "deathStrong=0.26", "desc": "死叉 strong_gap 阈值 0.26", "overrides": {"macdDeathStrongGapMin": 0.26}},
    {"key": "rawW=0.5", "desc": "rawScore 权重 [0.5,0.5]", "overrides": {"macdRawScoreWeights": [0.5, 0.5]}},
    {"key": "rawW=0.9", "desc": "rawScore 权重 [0.9,0.1]", "overrides": {"macdRawScoreWeights": [0.9, 0.1]}},
    # C 组：zeroCross 合成（默认 [0.7,0.3] / bonus 5）
    {"key": "zeroW=0.6", "desc": "zeroCross 权重 [0.6,0.4]", "overrides": {"momentumZeroWeights": [0.6, 0.4]}},
    {"key": "zeroW=0.8", "desc": "zeroCross 权重 [0.8,0.2]", "overrides": {"momentumZeroWeights": [0.8, 0.2]}},
    {"key": "zeroBonus=0", "desc": "strong_confirm bonus 0", "overrides": {"momentumZeroStrongConfirmBonus": 0}},
    {"key": "zeroBonus=10", "desc": "strong_confirm bonus 10", "overrides": {"momentumZeroStrongConfirmBonus": 10}},
    # D 组：技术辅助决策阈值（默认 ±0.12；runtime 决策合成消费）
    {"key": "buyThr=0.08", "desc": "买分阈值 0.08（放宽）", "overrides": {"buyScoreThreshold": 0.08}},
    {"key": "buyThr=0.18", "desc": "买分阈值 0.18（收紧）", "overrides": {"buyScoreThreshold": 0.18}},
    {"key": "sellThr=-0.08", "desc": "卖分阈值 -0.08（放宽）", "overrides": {"sellScoreThreshold": -0.08}},
    {"key": "sellThr=-0.18", "desc": "卖分阈值 -0.18（收紧）", "overrides": {"sellScoreThreshold": -0.18}},
]


def main() -> int:
    parser = argparse.ArgumentParser(description="趋势因子参数补扫（MACD 周期/死叉侧/zeroCross/决策阈值）")
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--purpose", default="scan", choices=["scan", "report"])
    parser.add_argument("--baseline-only", action="store_true", help="只评估默认配置（接线自检）")
    parser.add_argument("--overrides", default="", help="临时组合验证：JSON dict 形式的 config 覆盖")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    from backend.analysis.ranktrend.engine import RankTrendConfig
    from backend.optimization.data_windows import assert_not_frozen

    frames = load_frames(args.start, args.end)
    print(f"[trend-scan] frames={len(frames)} window={args.start}~{args.end} purpose={args.purpose}", file=sys.stderr)
    if not frames:
        print("[trend-scan] no frames loaded — aborting", file=sys.stderr)
        return 1
    assert_not_frozen(frames, args.purpose)

    out_path = Path(args.out) if args.out else REPORT_DIR / f"trend-factor-scan_{args.start}_{args.end}.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] loaded report keys: {list(report.get('trials', {}).keys())}", file=sys.stderr)
    report.setdefault("window", {"start": args.start, "end": args.end, "frameCount": len(frames)})
    report["purpose"] = args.purpose

    if "baseline" not in report:
        print("[trend-scan] evaluating baseline (default config) ...", file=sys.stderr)
        t0 = time.time()
        base = evaluate_gate(RankTrendConfig(), frames)
        base["elapsedSec"] = round(time.time() - t0, 1)
        report["baseline"] = base
        print(f"[baseline] {_fmt(base)} ({base['elapsedSec']}s)", file=sys.stderr)
    else:
        print(f"[baseline] (cached) {_fmt(report['baseline'])}", file=sys.stderr)

    trials = report.setdefault("trials", {})
    if args.overrides:
        run_specs = [{"key": "combo:" + ",".join(f"{k}={v}" for k, v in json.loads(args.overrides).items()),
                      "desc": "ad-hoc combo", "overrides": json.loads(args.overrides)}]
    elif not args.baseline_only:
        run_specs = PARAM_TRIALS
    else:
        run_specs = []

    for spec in run_specs:
        if spec["key"] in trials:
            print(f"[skip] {spec['key']} (cached)", file=sys.stderr)
            continue
        config_kwargs = {**dict(RankTrendConfig().__dict__), **spec["overrides"]}
        trial = RankTrendConfig(**config_kwargs)
        print(f"[trend-scan] {spec['key']} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_gate(trial, frames)
        result["elapsedSec"] = round(time.time() - t0, 1)
        trials[spec["key"]] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        print(f"[trend-scan] {spec['key']} -> {_fmt(result)} ({result['elapsedSec']}s)", file=sys.stderr)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[trend-scan] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
