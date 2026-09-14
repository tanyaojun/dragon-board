# -*- coding: utf-8 -*-
"""方案 B 前置验证：lifecycle 连续环境分（observation.lifecycle.score）三步诊断（只读）。

审计修订稿 §4.3（按序三步，任一失败触发收缩条款）：
1. 步骤 0 分布可行性：decision 窗 score 直方图（5 等宽桶）；单桶 >60% 帧则 5 等宽桶
   不可用，改分位桶（五分位）并在报告注明；
2. 方向内容：按桶算 h1 saEx（分位桶基线桶内重算，与 tier_forward_returns 同公式）+
   每桶样本量，对照 A/B/C/D(E) 档位 saEx（阶段 23.2 多数 None）——单调且样本充足
   → 连续分有档位没有的方向内容，支持 §4.2 推进；不单调 → 收缩为展示语义澄清；
3. 覆盖率/一致性：score ≤ t 扫描对现 action=veto 帧集算召回率/假阳率曲线——合理
   阈值（fpr ≤ 60%）下召回 <80% 即判"分数低尾不承载 veto 信息"，门控迁移条款收缩
   （保持标签驱动）。出场通道（synergyExitOnDanger）影响 saEx 不可见，适用 §5.2
   Track 1 复核义务。

预登记判定规则（本脚本口径，如实输出不修饰）：
- 方向内容 PASS ⇔ 桶序-saEx spearman ≥ 0.9 且各桶 n ≥ 200 且首末桶 saEx 差 ≥ +0.01；
- 覆盖率 PASS ⇔ 存在 t 使 recall(t) ≥ 0.80 且 fpr(t) ≤ 0.60。
score 语义：高分 = 环境优（stageFitness expansion 1.0 → reversal 0.0 + riskSafety），
veto 帧预期落在低分尾（recall 指 P(score ≤ t | veto)）。

用法：
  python -m backend.operations.diagnose_lifecycle_gate_score [--window decision] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.research.tier_monotonicity import _build_lookup, _percentile, _spearman
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR
from backend.operations.optimize_resonance_parameters import load_frames
from backend.operations.evaluate_ts_factor_weights import WINDOWS

SCORE_FIELD = ("rankTrend", "observation", "lifecycle")
BUCKET_MIN_SAMPLES = 200
MONO_SPEARMAN_MIN = 0.9
MONO_SPREAD_MIN = 0.01
RECALL_MIN = 0.80
FPR_MAX = 0.60


def _collect_samples(signals: list[dict[str, Any]], frames: list[dict[str, Any]], horizon: int = 1) -> dict[str, Any]:
    """每信号采集 (score, lc_tier, veto, stage, delta, current_pct)；帧边界/缺股/缺 rank 如实剔除。"""
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    totals = len(frames)
    samples: list[dict[str, Any]] = []
    skipped = {"no_snapshot": 0, "boundary": 0, "missing_stock": 0, "bad_rank": 0}
    for signal in signals:
        obs = ((signal.get("rankTrend") or {}).get("observation") or {})
        lc = obs.get("lifecycle") or {}
        entry = index_by_snapshot.get(str(signal.get("snapshotId")))
        if entry is None:
            skipped["no_snapshot"] += 1
            continue
        if entry + horizon >= totals:
            skipped["boundary"] += 1
            continue
        code = str(signal.get("code") or "")
        current = (stock_by_frame_code[entry] or {}).get(code)
        target = (stock_by_frame_code[entry + horizon] or {}).get(code)
        if not current or not target:
            skipped["missing_stock"] += 1
            continue
        current_pct = _percentile(float(current.get("rank") or 0), len(stock_by_frame_code[entry]))
        future_pct = _percentile(float(target.get("rank") or 0), len(stock_by_frame_code[entry + horizon]))
        if current_pct <= 0 or future_pct <= 0:
            skipped["bad_rank"] += 1
            continue
        samples.append(
            {
                "score": lc.get("score"),
                "lcTier": str(lc.get("signalTier") or "unknown"),
                "veto": bool(lc.get("veto")),
                "stage": str(lc.get("stage") or ""),
                "delta": (future_pct - current_pct) / 100.0,
                "pct": current_pct,
            }
        )
    return {"samples": samples, "skipped": skipped, "frames": totals}


def _saex_by_group(samples: list[dict[str, Any]], key_fn) -> dict[str, dict[str, Any]]:
    """按 key_fn 分组算 h1 saEx（公式同 tier_forward_returns：组 acc − 组内样本分位桶基线 acc 均值）。"""
    valid = [s for s in samples if isinstance(s.get("score"), (int, float))]
    # 全样本分位十桶基线（阶段 3 修复方向 2 同口径）
    bucket_deltas: dict[int, list[float]] = {}
    for s in valid:
        bucket_deltas.setdefault(min(9, int(s["pct"] // 10)), []).append(s["delta"])
    baseline_acc = {
        bucket: (sum(1 for d in deltas if d > 0) / len(deltas) if deltas else None)
        for bucket, deltas in bucket_deltas.items()
    }
    groups: dict[str, list[dict[str, Any]]] = {}
    for s in valid:
        groups.setdefault(str(key_fn(s)), []).append(s)
    out: dict[str, dict[str, Any]] = {}
    for name, members in groups.items():
        count = len(members)
        acc = sum(1 for s in members if s["delta"] > 0) / count
        baseline_accs = [baseline_acc.get(min(9, int(s["pct"] // 10))) for s in members]
        baseline_accs = [v for v in baseline_accs if v is not None]
        group_baseline = sum(baseline_accs) / len(baseline_accs) if baseline_accs else None
        out[name] = {
            "n": count,
            "directionAccuracy": round(acc, 4),
            "saEx": round(acc - group_baseline, 4) if group_baseline is not None else None,
            "meanFutureReturn": round(sum(s["delta"] for s in members) / count, 6),
        }
    return out


def _equal_width_bucket(score: float) -> int:
    return min(4, int(score // 20))


def _quantile_buckets(scores: list[float]) -> tuple[list[float], list[int]]:
    """五分位边界（含 0/100 端点）+ 每样本桶号。"""
    ordered = sorted(scores)
    n = len(ordered)
    edges = [0.0] + [ordered[min(n - 1, int(n * q))] for q in (0.2, 0.4, 0.6, 0.8)] + [100.0]

    def bucket_of(value: float) -> int:
        for i in range(4, 0, -1):
            if value >= edges[i]:
                return i
        return 0

    return edges, [bucket_of(v) for v in scores]


def diagnose(window: str) -> dict[str, Any]:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    frames = load_frames(start, end)
    assert_not_frozen(frames, "scan")
    t0 = time.time()
    engine = RankTrendPythonEngine(config=RankTrendConfig())
    signals = engine.replay(frames, meta={})
    print(f"[lc-score-diag] {window} frames={len(frames)} signals={len(signals)} ({time.time() - t0:.0f}s)", file=sys.stderr)

    collected = _collect_samples(signals, frames)
    samples = collected["samples"]
    report: dict[str, Any] = {
        "window": {"start": start, "end": end, "frameCount": len(frames)},
        "signalCount": len(signals),
        "validSamples": len(samples),
        "skipped": collected["skipped"],
        "scoreMissing": sum(1 for s in samples if not isinstance(s.get("score"), (int, float))),
    }

    # ── 步骤 0：分布可行性 ──
    scores = [float(s["score"]) for s in samples if isinstance(s.get("score"), (int, float))]
    equal_counts = [0] * 5
    for v in scores:
        equal_counts[_equal_width_bucket(v)] += 1
    total = max(1, len(scores))
    equal_share = [round(c / total, 4) for c in equal_counts]
    use_quantile = max(equal_share) > 0.60
    report["step0_distribution"] = {
        "equalWidthCounts": equal_counts,
        "equalWidthShare": equal_share,
        "maxBucketShare": max(equal_share),
        "useQuantileBuckets": use_quantile,
        "quantileEdges": None,
    }
    if use_quantile:
        edges, bucket_ids = _quantile_buckets(scores)
        report["step0_distribution"]["quantileEdges"] = [round(e, 1) for e in edges]
        for s, b in zip([s for s in samples if isinstance(s.get("score"), (int, float))], bucket_ids):
            s["bucket"] = b
        bucket_fn = lambda s: s.get("bucket")  # noqa: E731
        report["step0_distribution"]["bucketingNote"] = "分位桶（等宽桶最大占比 >60%，5 等宽不可用）"
    else:
        for s in samples:
            if isinstance(s.get("score"), (int, float)):
                s["bucket"] = _equal_width_bucket(float(s["score"]))
        bucket_fn = lambda s: s.get("bucket")  # noqa: E731
        report["step0_distribution"]["bucketingNote"] = "5 等宽桶"

    # ── 步骤 1（方向内容）：按桶 saEx + 对照 lc 档位 saEx ──
    bucket_stats = _saex_by_group(samples, bucket_fn)
    ordered_buckets = sorted(bucket_stats.keys(), key=lambda x: int(x))
    saex_seq = [bucket_stats[b]["saEx"] for b in ordered_buckets]
    ns = [bucket_stats[b]["n"] for b in ordered_buckets]
    present = [(i, v) for i, v in enumerate(saex_seq) if v is not None]
    spearman = _spearman([float(i) for i, _ in present], [float(v) for _, v in present]) if len(present) >= 2 else None
    spread = (saex_seq[-1] - saex_seq[0]) if (saex_seq[0] is not None and saex_seq[-1] is not None) else None
    tier_stats = _saex_by_group(samples, lambda s: s["lcTier"])
    direction_pass = bool(
        spearman is not None
        and spearman >= MONO_SPEARMAN_MIN
        and all(n >= BUCKET_MIN_SAMPLES for n in ns)
        and spread is not None
        and spread >= MONO_SPREAD_MIN
    )
    report["step1_direction"] = {
        "buckets": {b: bucket_stats[b] for b in ordered_buckets},
        "saExSequence": saex_seq,
        "spearman": None if spearman is None else round(spearman, 4),
        "spreadLowToHigh": None if spread is None else round(spread, 4),
        "minBucketSamples": min(ns) if ns else 0,
        "lifecycleTierSaEx": tier_stats,
        "rules": {"spearmanMin": MONO_SPEARMAN_MIN, "minBucketSamples": BUCKET_MIN_SAMPLES, "spreadMin": MONO_SPREAD_MIN},
        "verdict": "PASS" if direction_pass else "FAIL",
    }

    # ── 步骤 2（veto 覆盖率）：score ≤ t 扫描召回/假阳曲线 ──
    veto_scores = sorted(float(s["score"]) for s in samples if s.get("veto") and isinstance(s.get("score"), (int, float)))
    non_veto_scores = [float(s["score"]) for s in samples if (not s.get("veto")) and isinstance(s.get("score"), (int, float))]
    curve = []
    best_recall_at_fpr = 0.0
    best_t_at_fpr: float | None = None
    for t in range(0, 105, 5):
        recall = sum(1 for v in veto_scores if v <= t) / len(veto_scores) if veto_scores else None
        fpr = sum(1 for v in non_veto_scores if v <= t) / len(non_veto_scores) if non_veto_scores else None
        curve.append({"t": t, "recall": None if recall is None else round(recall, 4), "fpr": None if fpr is None else round(fpr, 4)})
        if recall is not None and fpr is not None and recall >= RECALL_MIN and fpr <= FPR_MAX and recall > best_recall_at_fpr:
            best_recall_at_fpr = recall
            best_t_at_fpr = float(t)
    coverage_pass = best_t_at_fpr is not None
    report["step2_vetoCoverage"] = {
        "vetoFrames": len(veto_scores),
        "nonVetoFrames": len(non_veto_scores),
        "vetoScoreMedian": round(veto_scores[len(veto_scores) // 2], 1) if veto_scores else None,
        "curve": curve,
        "rules": {"recallMin": RECALL_MIN, "fprMax": FPR_MAX},
        "bestT": best_t_at_fpr,
        "bestRecallAtFprCap": round(best_recall_at_fpr, 4) if best_t_at_fpr is not None else None,
        "verdict": "PASS" if coverage_pass else "FAIL",
        "blindSpotNote": "score 驱动对出场通道（synergyExitOnDanger/downgradeSteps）的影响 saEx 不可见，适用提案 §5.2 Track 1 复核义务",
    }

    report["overall"] = {
        "step0Bucketing": "quantile" if use_quantile else "equal_width",
        "direction": report["step1_direction"]["verdict"],
        "vetoCoverage": report["step2_vetoCoverage"]["verdict"],
        "conclusion": (
            "支持 §4.2 全面推进（连续分有档位没有的方向内容且低尾承载 veto 信息）"
            if direction_pass and coverage_pass
            else ("方向内容不达标 → 方案 B 收缩为展示语义澄清，门控保持标签驱动走方案 A 权重化"
                  if not direction_pass
                  else "方向内容达标但 veto 低尾承载不足 → 门控迁移条款收缩（保持标签驱动）")
        ),
    }
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="方案 B 前置验证：lifecycle.score 三步诊断（只读）")
    parser.add_argument("--window", default="decision", choices=list(WINDOWS.keys()))
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    report = diagnose(args.window)
    out_path = Path(args.out) if args.out else REPORT_DIR / "lifecycle-gate-score-diagnosis.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.get("overall", {}), ensure_ascii=False, indent=2))
    print(f"[lc-score-diag] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
