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

2026-09-21 改造：harness 工程范式收敛后成为 `harness_common` 第一个使用者（审计文档
§7.1）——帧加载（内联 assert_not_frozen）/信号访问器（dimension_tier_of 走 DIMENSION_PATHS
单一源）/指标装配/报告落盘（schemaVersion 校验 resume）/已知答案校验器全部来自公共库，
本文件只保留本课题特有的 trial 编排。读数与 2026-09-20 f686ada5 干净重跑逐位一致
（回归验证见审计文档）。

用法：
  python -m backend.operations.scan_repool_sample_floor [--window oos1|decision|all]
      [--out <path>]
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns
from backend.operations.harness_common import (
    assert_known_answer,
    assert_overrides_applied,
    cache_frames,
    cached_frames,
    dimension_tier_of,
    load_frames,
    load_resume,
    new_report,
    sample_status_of,
    save_report,
    status_buckets,
)

SCHEMA_VERSION = "repool-scan-v2"

# 档位：baseline(5) 必须首个跑（其余档位的增量样本以它为对照）
FLOORS: list[int] = [5, 3, 4, 7, 10]


def _newly_judged_metrics(
    trial_signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    baseline_status: dict[tuple[str, str], str],
    horizon: int = 1,
) -> dict[str, Any]:
    """新增判定样本（baseline insufficient → 本档 degraded/ok）的 lifecycle 档位与 h{horizon} 质量。

    H0 反面假设的直接检验：这些样本的 lifecycle 档位 forward-return 若与随机无异
    （excessDirectionAccuracy ≈ 0），说明中断历史降级判定产出的是噪声 → 维持现状。
    键名 h{horizon} 动态生成（默认 1 时保持历史键名 h1）。
    """
    def newly_judged(signal: dict[str, Any]) -> bool:
        key = (str(signal.get("snapshotId")), str(signal.get("code")))
        return (
            baseline_status.get(key) == "insufficient"
            and sample_status_of(signal) != "insufficient"
        )

    newly = [signal for signal in trial_signals if newly_judged(signal)]
    # lifecycle.signalTier 统一走 DIMENSION_PATHS 读取器（2026-09-20 事故防线：
    # 误读 signal["observation"] 曾产出「100% unknown」假阴性，见立项文档 §5.1 更正记录）
    tier_dist: dict[str, int] = {}
    for signal in newly:
        tier = dimension_tier_of(signal, "lifecycle")
        tier_dist[tier] = tier_dist.get(tier, 0) + 1
    quality = tier_forward_returns(newly, frames, horizon=horizon, dimension="lifecycle")
    return {
        "newlyJudgedCount": len(newly),
        "lifecycleTierDist": dict(sorted(tier_dist.items(), key=lambda kv: -kv[1])),
        f"h{horizon}": quality,
    }


def _lifecycle_saex(signals: list[dict[str, Any]], frames: list[dict[str, Any]], horizon: int = 1) -> dict[str, Any]:
    return tier_forward_returns(signals, frames, horizon=horizon, dimension="lifecycle")


def run_window(window: str, report: dict[str, Any], horizon: int = 1) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import WINDOWS

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = cached_frames(report, window)
    if frames is None:
        # load_frames 内联 assert_not_frozen（无条件守卫，含 resume 后的重新加载）
        frames = load_frames(start, end)
        cache_frames(report, window, frames)
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[repool-scan] {window} frames={len(frames)}", file=sys.stderr)
    if not frames:
        entry["error"] = "no frames"
        save_report(report)
        return

    trials = entry.setdefault("trials", {})
    baseline_status: dict[tuple[str, str], str] = {}
    _has_missing_non_baseline = any(
        (f"floor{floor}" if floor != FLOORS[0] else "baseline") not in trials
        for floor in FLOORS
        if floor != FLOORS[0]
    )
    if "baseline" in trials and _has_missing_non_baseline:
        # 渐进 resume 防线（2026-09-21 review Critical）：baseline trial 已缓存时循环会
        # skip，但新增判定样本的对照集（baseline insufficient → trial 判 degraded/ok）
        # 不能为空——空对照会把 newlyJudged 全部伪装成 0（「无新增样本」假结论，违反
        # fail-visible）。replay 确定性：重算 status map 与首跑逐位一致，仅不重复落盘。
        overrides = {"degradedSampleFloor": FLOORS[0]}
        config = RankTrendConfig.from_patch(overrides)
        assert_overrides_applied(config, overrides)
        engine = RankTrendPythonEngine(config=config)
        print("[repool-scan] resume: rebuild baseline status map ...", file=sys.stderr)
        baseline_status = {
            (str(signal.get("snapshotId")), str(signal.get("code"))): sample_status_of(signal)
            for signal in engine.replay(frames, meta={})
        }
    for floor in FLOORS:
        key = f"floor{floor}" if floor != 5 else "baseline"
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        overrides = {"degradedSampleFloor": floor}
        desc = "默认（现状）" if floor == 5 else f"degraded 门槛 5 → {floor}"
        print(f"[repool-scan] {window} {key} {overrides} horizon={horizon} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(overrides)
        assert_overrides_applied(config, overrides)
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        buckets = status_buckets(signals)
        result: dict[str, Any] = {
            "desc": desc,
            "overrides": overrides,
            "horizon": horizon,
            "statusBuckets": buckets,
            # 键名按 horizon 动态生成：默认 1 时与历史键名 lifecycleH1/h1 逐字一致（golden 不漂移）
            f"lifecycleH{horizon}": _lifecycle_saex(signals, frames, horizon=horizon),
        }
        if floor == 5:
            baseline_status = {
                (str(signal.get("snapshotId")), str(signal.get("code"))): sample_status_of(signal)
                for signal in signals
            }
            result["isBaseline"] = True
        else:
            result["newlyJudged"] = _newly_judged_metrics(signals, frames, baseline_status, horizon=horizon)
        trials[key] = result
        print(
            f"[repool-scan] {window} {key} -> buckets={buckets} "
            f"({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        save_report(report)


def main() -> int:
    parser = argparse.ArgumentParser(description="P_repool_timeline_gap degradedSampleFloor 中期扫描")
    # 2026-09-25 B-202610 演练：--window 增 oos2u（N8 终判窗，本批次执行属 §2.1 消费禁令
    # 豁免场景；"all" 保持中期扫描语义 [oos1, decision] 不扩）；--horizon 透传（N8 终判要求
    # 补 h8 口径，默认 1 golden 不漂移）。h8 读数须用独立 --out（trial 缓存按 key 冒充防线）。
    parser.add_argument("--window", default="oos1", choices=["oos1", "decision", "oos2u", "all"])
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    windows = ["oos1", "decision"] if args.window == "all" else [args.window]
    out = args.out or "data/reports/repool-midterm/repool-sample-floor-scan.json"

    # 已知答案校验（2026-09-21 纪律）：mini replay 结构断言先于全窗跑
    assert_known_answer()

    report = load_resume(out, schema_version=SCHEMA_VERSION)
    if report is not None:
        print(f"[resume] schema={SCHEMA_VERSION} cached windows: "
              f"{[w for w in windows if w in report]}", file=sys.stderr)
    else:
        report = new_report(
            out,
            schema_version=SCHEMA_VERSION,
            nature="midterm-scan（方向性读数，M3 折扣；终判以 B-202610 批次 oos2u 为准）",
        )
    for window in windows:
        run_window(window, report, horizon=args.horizon)
    print(f"[repool-scan] done -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
