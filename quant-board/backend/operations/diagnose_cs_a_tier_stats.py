# -*- coding: utf-8 -*-
"""O7 crossSection A 档复核统计（§11.5 触发线核对，只读诊断，2026-09-25 B-202610 演练）。

触发条件（rerun-plan §4 阶段 3 O7 / longterm §11.5）：crossSection A 档样本 >500 且
新窗口 synergy 稳定 >0.05——本脚本产出四窗读数供触发判定，不做参数晋升、不写回默认。

统计口径（每窗 baseline replay 一次）：
- cs 维档位 raw 分布（tier_signal_of 单一入口，缺字段回退 unknown 并如实计数）；
- cs 维 h1 档位统计（tier_forward_returns dimension="crossSection" 全体信号）；
- cs=A 档复核读数：raw 命中数 + h1 有效前瞻数 + A 档 excessDirectionAccuracy
  （触发线 >0.05 的直接读数）+ A 档内 synergy saEx（S/A 合并 excess 方向精度）；
- 双强交叉计数（synA ∩ rtA ∩ csA，与 O8 §2.2 口径衔接）。

harness 范式：WINDOWS 自 data_windows 单一源派生；load_frames 走 harness_common
（冻结守卫内联）；锚校验对照注册表 currentGeneration（gen-2026-10-b202610），
baseline saEx 漂移即 raise 停跑（生产口径）；override 无（纯 baseline，无 patch）。

用法：
  python -m backend.operations.diagnose_cs_a_tier_stats [--window all|decision|oos1|oos2|oos2u]
      [--out <path>] [--skip-anchor-on-missing]   （后者仅供合成帧单测，生产勿用）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns, tier_signal_of
from backend.operations.harness_common import (
    baseline_anchor,
    load_frames,
    sa_excess,
    tier_summary,
)
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate

# 窗口单一事实源派生（含 oos2u 未消费裁决子窗）
from backend.optimization.data_windows import WINDOWS as _STANDARD_WINDOWS

WINDOWS: dict[str, tuple[str, str]] = {
    key: _STANDARD_WINDOWS[key] for key in ("decision", "oos1", "oos2", "oos2u")
}


def anchor_check(window: str, sa_ex: float | None, anchors: dict[str, float]) -> dict[str, Any]:
    """锚比对（jump-confirm 同款语义）：窗口未建锚 → checked=False 跳过；None 不伪装匹配。"""
    expected = anchors.get(window)
    if expected is None:
        return {"checked": False}
    ok = sa_ex is not None and round(float(sa_ex), 4) == round(float(expected), 4)
    return {"checked": True, "expected": expected, "actual": sa_ex, "match": ok}


def cs_tier_counts(signals: list[dict[str, Any]]) -> dict[str, int]:
    """cs 维档位 raw 计数（缺字段回退 unknown，fail-visible 不丢弃样本）。"""
    counts: dict[str, int] = {}
    for signal in signals:
        tier = tier_signal_of(signal, "crossSection")
        counts[tier] = counts.get(tier, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _cs_a_predicate(signal: dict[str, Any]) -> bool:
    return tier_signal_of(signal, "crossSection") == "A"


def _dual_strong_predicate(signal: dict[str, Any]) -> bool:
    return (
        tier_signal_of(signal, "synergy") == "A"
        and tier_signal_of(signal, "rankTrend") == "A"
        and tier_signal_of(signal, "crossSection") == "A"
    )


def _filtered_stats(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    dimension: str,
    pred,
) -> dict[str, Any]:
    """组内 h1 统计：filter 限定样本集后按 dimension 分桶（组内同质档位即 tiers[该档]）。"""
    stats = tier_forward_returns(signals, frames, horizon=1, dimension=dimension, signal_filter=pred)
    tier_a = (stats.get("tiers") or {}).get("A") or {}
    return {
        "h1Count": tier_a.get("count"),
        "excessDirectionAccuracy": tier_a.get("excessDirectionAccuracy"),
        "directionAccuracy": tier_a.get("directionAccuracy"),
        "meanFutureReturn": tier_a.get("meanFutureReturn"),
        "saEx": sa_excess(stats),
    }


def analyze_window(
    window: str,
    frames: list[dict[str, Any]],
    *,
    anchors: dict[str, float] | None = None,
    skip_anchor_on_missing: bool = False,
) -> dict[str, Any]:
    """单窗统计：baseline replay + cs 维/A 档/双强三组读数 + 锚校验。"""
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine

    start, end = WINDOWS[window]
    result: dict[str, Any] = {"window": window, "bounds": {"start": start, "end": end}, "frameCount": len(frames)}
    if not frames:
        result["error"] = "no frames loaded"
        return result
    signals = RankTrendPythonEngine(config=RankTrendConfig()).replay(frames, meta={})
    result["signalCount"] = len(signals)
    if not signals:
        result["error"] = "replay produced no signals"
        return result

    result["csTierCounts"] = cs_tier_counts(signals)
    cs_all = tier_forward_returns(signals, frames, horizon=1, dimension="crossSection")
    result["csDimensionH1"] = tier_summary(cs_all)

    cs_a = _filtered_stats(signals, frames, "crossSection", _cs_a_predicate)
    syn_in_a = _filtered_stats(signals, frames, "synergy", _cs_a_predicate)
    result["csATier"] = {
        "rawHits": cs_tier_counts(signals).get("A", 0),
        "h1Count": cs_a["h1Count"],
        "excessDirectionAccuracy": cs_a["excessDirectionAccuracy"],
        "meanFutureReturnInA": cs_a["meanFutureReturn"],
        "synergySaExInA": syn_in_a["saEx"],
        "synergyMeanRetInA": syn_in_a["meanFutureReturn"],
        "reviewTriggerMet": bool((cs_a["h1Count"] or 0) > 500),
    }
    dual = _filtered_stats(signals, frames, "synergy", _dual_strong_predicate)
    result["dualStrong"] = {
        "rawHits": sum(1 for s in signals if _dual_strong_predicate(s)),
        "h1Count": dual["h1Count"],
        "meanFutureReturn": dual["meanFutureReturn"],
    }

    gate = evaluate_gate(RankTrendConfig(), frames)
    syn_sa = (gate.get("synergy") or {}).get("saEx")
    result["baselineSynergySaEx"] = syn_sa
    check = anchor_check(window, syn_sa, anchors or {})
    if not check["checked"] and skip_anchor_on_missing:
        check = {**check, "skipped": True}
    result["anchor"] = check
    if check.get("checked") and not check.get("match") and not skip_anchor_on_missing:
        raise RuntimeError(
            f"baseline 锚漂移：{window} synergy saEx={check['actual']} != 注册表锚 {check['expected']}"
            f"（gen 漂移或帧数据口径变化），立即停止——先核查再重跑"
        )
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="O7 crossSection A 档复核统计（§11.5 触发线，只读）")
    parser.add_argument("--window", default="all", choices=["all", *WINDOWS])
    parser.add_argument("--out", default=str(REPORT_DIR / "b-202610" / "cs-a-tier-stats-dryrun.json"))
    parser.add_argument("--skip-anchor-on-missing", action="store_true", help="仅供合成帧单测（生产勿用）")
    args = parser.parse_args()

    anchors = baseline_anchor()[1]
    names = list(WINDOWS) if args.window == "all" else [args.window]
    results: dict[str, Any] = {}
    for name in names:
        print(f"[cs-a-stats] {name} loading frames ...", file=sys.stderr)
        t0 = time.time()
        frames = load_frames(*WINDOWS[name], purpose="report")  # 遗留观察项复核=报告用途
        result = analyze_window(name, frames, anchors=anchors, skip_anchor_on_missing=args.skip_anchor_on_missing)
        results[name] = result
        if "error" in result:
            print(f"[cs-a-stats] {name}: {result['error']}", file=sys.stderr)
            continue
        a = result["csATier"]
        print(
            f"[cs-a-stats] {name}: csA(h1={a['h1Count']} raw={a['rawHits']} excessDirAcc="
            f"{a['excessDirectionAccuracy']}) synSaExInA={a['synergySaExInA']} "
            f"dualStrong={result['dualStrong']['rawHits']} anchor={result['anchor']} "
            f"({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(
                {"generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"), "anchorGeneration": baseline_anchor()[0], "results": results},
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    print(f"[cs-a-stats] report -> {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
