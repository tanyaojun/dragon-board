# -*- coding: utf-8 -*-
"""P_repool_timeline_gap 中期扫描 harness：出池回池重建期三档门槛（degradedSampleFloor）5 档单变量。

立项：`docs/ranktrend-tier-backtest/ranktrend-repool-timeline-gap-research-proposal.md`
（2026-09-20 用户立项；观察池 `config/ranktrend-observation-pool.yaml` → P_repool_timeline_gap）。
参数空间（A1 修正后）：三档判定中档线 `degradedSampleFloor`（原硬编码 5，已参数化 af9aa818，
默认值=原值 golden 不漂移）。档位：3 / 4 / **5(默认=baseline)** / 7 / 10。

本 harness 是**中期扫描**：窗口只用 decision + oos1；oos2/oos2u 保留给 10 月上旬 B-202610
批次终判（oos2u 消费禁令见 data_windows.py §2.1）。中期读数一律标注 M3 折扣与
「中期=方向性判断，终判以批次为准」。

监控量（每 trial 每窗）：
- **三桶占比**（本课题第一观察项）：meta.sampleQuality.status 的 ok/degraded/insufficient
  分布——degraded 占比升幅 = 重建期缩短的直接读数；
- lifecycle 维 h1 `tier_forward_returns`（saEx 语义：excessDirectionAccuracy 分档）；
- **新增判定样本质量**（本课题特有）：baseline 判 insufficient、本档判 degraded/ok 的
  (snapshotId, code) 增量集合的 lifecycle 档位分布与 h1 质量——回答「放开门槛后新进
  判定的样本到底是信号还是噪声」（H0 反面假设的直接检验）。

harness 纪律（8 项清单）：WINDOWS import 零日期字面量；`_assert_overrides_applied` 逐键断言；
`assert_not_frozen` 无条件执行；零默认值改动（扫描只读）；报告缓存 resume（帧缓存不落盘）。

用法：
  python -m backend.operations.scan_repool_sample_floor [--window oos1|decision|all]
      [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

REPORT_DIR = Path("data/reports/repool-midterm")

# 档位：baseline(5) 必须首个跑（其余档位的增量样本以它为对照）
FLOORS: list[int] = [5, 3, 4, 7, 10]


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """逐键断言 override 真正落到 config（防静默失效产出假结论，harness 清单 2）。"""
    for key, value in overrides.items():
        actual = getattr(config, key, None)
        if actual != value:
            raise RuntimeError(f"override 未生效：{key} 期望 {value}，实际 {actual}")


def _sample_status_of(signal: dict[str, Any]) -> str:
    meta = ((signal.get("rankTrend") or {}).get("meta") or {}).get("sampleQuality") or {}
    return str(meta.get("status") or "insufficient")


def _status_buckets(signals: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = {"ok": 0, "degraded": 0, "insufficient": 0}
    for signal in signals:
        status = _sample_status_of(signal)
        buckets[status] = buckets.get(status, 0) + 1
    total = sum(buckets.values())
    shares = {k: round(v / total, 4) for k, v in buckets.items()} if total else {}
    return {**buckets, "total": total, "share": shares}


def _status_key_map(signals: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    return {
        (str(signal.get("snapshotId")), str(signal.get("code"))): _sample_status_of(signal)
        for signal in signals
    }


def _newly_judged_metrics(
    trial_signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    baseline_status: dict[tuple[str, str], str],
) -> dict[str, Any]:
    """新增判定样本（baseline insufficient → 本档 degraded/ok）的 lifecycle 档位与 h1 质量。

    H0 反面假设的直接检验：这些样本的 lifecycle 档位 forward-return 若与随机无异
    （excessDirectionAccuracy ≈ 0），说明中断历史降级判定产出的是噪声 → 维持现状。
    """
    from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns

    def newly_judged(signal: dict[str, Any]) -> bool:
        key = (str(signal.get("snapshotId")), str(signal.get("code")))
        return (
            baseline_status.get(key) == "insufficient"
            and _sample_status_of(signal) != "insufficient"
        )

    newly = [signal for signal in trial_signals if newly_judged(signal)]
    tier_dist: dict[str, int] = {}
    for signal in newly:
        tier = str(
            ((signal.get("observation") or {}).get("lifecycle") or {}).get("signalTier") or "unknown"
        )
        tier_dist[tier] = tier_dist.get(tier, 0) + 1
    quality = tier_forward_returns(newly, frames, horizon=1, dimension="lifecycle")
    return {
        "newlyJudgedCount": len(newly),
        "lifecycleTierDist": dict(sorted(tier_dist.items(), key=lambda kv: -kv[1])),
        "h1": quality,
    }


def _lifecycle_saex(signals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> dict[str, Any]:
    from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns

    return tier_forward_returns(signals, frames, horizon=1, dimension="lifecycle")


def run_window(window: str, report: dict[str, Any]) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import WINDOWS, assert_not_frozen
    from backend.operations.optimize_resonance_parameters import load_frames

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    cache = report.get("__frames__") or {}
    if window not in cache:
        cache[window] = load_frames(start, end)
        report["__frames__"] = cache
    frames = cache[window]
    assert_not_frozen(frames, "scan")  # 无条件执行（含 resume 路径，harness 清单 3）
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[repool-scan] {window} frames={len(frames)}", file=sys.stderr)
    if not frames:
        entry["error"] = "no frames"
        _save(report)
        return

    trials = entry.setdefault("trials", {})
    baseline_status: dict[tuple[str, str], str] = {}
    for floor in FLOORS:
        key = f"floor{floor}" if floor != 5 else "baseline"
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        overrides = {"degradedSampleFloor": floor}
        desc = "默认（现状）" if floor == 5 else f"degraded 门槛 5 → {floor}"
        print(f"[repool-scan] {window} {key} {overrides} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(overrides)
        _assert_overrides_applied(config, overrides)
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        buckets = _status_buckets(signals)
        result: dict[str, Any] = {
            "desc": desc,
            "overrides": overrides,
            "statusBuckets": buckets,
            "lifecycleH1": _lifecycle_saex(signals, frames),
        }
        if floor == 5:
            baseline_status = _status_key_map(signals)
            result["isBaseline"] = True
        else:
            result["newlyJudged"] = _newly_judged_metrics(signals, frames, baseline_status)
        trials[key] = result
        print(
            f"[repool-scan] {window} {key} -> buckets={buckets} "
            f"({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = list(report.get("__frames__") or {})  # 审计 M3
    report["nature"] = "midterm-scan（方向性读数，M3 折扣；终判以 B-202610 批次 oos2u 为准）"
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "repool-sample-floor-scan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}  # 帧缓存不落盘
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="P_repool_timeline_gap degradedSampleFloor 中期扫描")
    parser.add_argument("--window", default="oos1", choices=["oos1", "decision", "all"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    windows = ["oos1", "decision"] if args.window == "all" else [args.window]
    report: dict[str, Any] = {"__out__": args.out, "__frames__": {}}
    if Path(args.out).exists() if args.out else False:
        try:
            cached = json.loads(Path(args.out).read_text(encoding="utf-8"))
            cached_frames = cached.pop("windowsConsumed", None)
            report.update(cached)
            print(f"[resume] cached windows: {list(cached.get('trials', {}))}", file=sys.stderr)
        except (OSError, json.JSONDecodeError):
            pass
    for window in windows:
        run_window(window, report)
    print(f"[repool-scan] done -> {args.out or REPORT_DIR / 'repool-sample-floor-scan.json'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
