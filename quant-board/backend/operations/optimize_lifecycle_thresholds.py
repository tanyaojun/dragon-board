# -*- coding: utf-8 -*-
"""生命周期分层阈值坐标下降搜索（backend/operations，2026-08-16）。

评估：replay(config) → lifecycle tier 分布 + h8 excess（tier_forward_returns dimension=lifecycle）
目标：lifecycle S/A/B excess 单调 + S 样本 ≥ 500（对比现状：无 S、A/B 反转 0.055/0.097）。
用法：python -m backend.operations.optimize_lifecycle_thresholds [--rounds N]
输出：data/reports/lifecycle-threshold-search.json + 每轮进度打印。
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns
from backend.core.settings import get_settings
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS


def load_frames():
    repo = MongoRepository(get_runtime_mongodb_database())
    return repo.load_frame_bundles(
        "dragonboard_live", snapshot_type="half_hour",
        start_date="2026-04-15", end_date="2026-08-14",
        projection="ranktrend", fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )


def evaluate(config: RankTrendConfig, frames) -> dict:
    """replay + lifecycle tier h8 评估。返回 {score, a_count, b_ex, a_ex, b_ex, spearman, monotone, tiers}。

    lifecycle tier 合法档位 A/B/C/D/E（无 S，_lifecycle_tier 规则）：
    A=allow+ignition/expansion（优选路径）、B=caution+ignition/expansion（谨慎）、
    C=中性、D/E=回避/否决。目标：A_ex > B_ex（优选路径方向区分度，阶段3诊断 A 0.055 < B 0.097 反转）。"""
    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(frames, window_size=50)
    stats = tier_forward_returns(signals, frames, horizon=1, dimension="lifecycle")
    tiers = stats.get("tiers") or {}
    a = tiers.get("A") or {}
    b = tiers.get("B") or {}
    c = tiers.get("C") or {}
    a_count = int(a.get("count") or 0)
    b_count = int(b.get("count") or 0)
    c_count = int(c.get("count") or 0)
    a_ex = float(a.get("excessMeanFutureReturn") or 0)
    b_ex = float(b.get("excessMeanFutureReturn") or 0)
    c_ex = float(c.get("excessMeanFutureReturn") or 0)
    m = stats.get("monotonicity") or {}
    spearman = m.get("spearmanRankCorr")
    # 目标：A > B（优选路径方向区分度）且样本充足；B > C 作为辅助（谨慎 > 中性）
    ab_ok = a_count >= 1000 and b_count >= 1000 and a_ex > b_ex
    bc_ok = b_count >= 1000 and c_count >= 1000 and b_ex > c_ex
    score = (1.0 if ab_ok else 0.0) + (0.5 if bc_ok else 0.0) + min(a_count / 10000.0, 0.5)
    return {
        "score": round(score, 4),
        "monotone": ab_ok,
        "a_count": a_count, "b_count": b_count, "c_count": c_count,
        "a_ex": round(a_ex, 4), "b_ex": round(b_ex, 4), "c_ex": round(c_ex, 4),
        "spearman": spearman,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    args = ap.parse_args()

    frames = load_frames()
    print(f"frames={len(frames)}", file=sys.stderr)

    # 搜索空间：raw_stage 关键阈值（精简：优先影响 ignition/expansion/cooling 分布的 percentile 阈值）
    STEPS = {
        "cycleRawWarmPercentileMin": (55.0, 75.0, 85.0),
        "cycleRawWarmBestRankMax": (15.0, 35.0, 50.0),
        "cycleRawRecoveryPercentileMin": (40.0, 60.0, 70.0),
        "cycleRawRecoveryBestRankMax": (20.0, 40.0),
        "cycleRawExpansionPercentileMin": (60.0, 80.0),
        "cycleRawExpansionBestRankMax": (10.0, 30.0),
        "cycleRawCrowdedHotMin": (2, 4),
        "cycleRawReversalDrawdownMin": (1.5, 3.0),
        "cycleNormCoolingReadyPercentileMax": (65.0, 78.0),
        "cycleNormCrowdedCarryPercentileMin": (78.0, 86.0),
    }

    # 基线评估（锚点：lifecycle A_ex < B_ex 反转，阶段3诊断 A 0.055 < B 0.097）
    base = evaluate(RankTrendConfig(), frames)
    print(f"[baseline] score={base['score']} A={base['a_count']}(ex {base['a_ex']}) "
          f"B={base['b_count']}(ex {base['b_ex']}) C={base['c_count']}(ex {base['c_ex']}) "
          f"monotone={base['monotone']}", file=sys.stderr)

    current = RankTrendConfig()
    best_result = base
    best_params: dict[str, object] = {}
    round_logs = []
    for rnd in range(1, args.rounds + 1):
        improved = False
        for key, candidates in STEPS.items():
            cur_val = getattr(current, key)
            for cand in candidates:
                if abs(float(cand) - float(cur_val)) < 1e-9:
                    continue
                # 继承 current 已采纳的阈值，仅替换 key 为 cand
                trial = RankTrendConfig(**_inherited(current, key, cand))
                result = evaluate(trial, frames)
                if result["score"] > best_result["score"]:
                    print(f"[round{rnd}] {key}={cand} score {result['score']} > {best_result['score']} "
                          f"(A={result['a_count']} ex {result['a_ex']}/{result['b_ex']}/{result['c_ex']})",
                          file=sys.stderr)
                    best_result = result
                    best_params = _inherited(current, key, cand)
                    current = trial
                    improved = True
        round_logs.append({"round": rnd, "best_score": best_result["score"],
                           "best_params": dict(best_params)})
        print(f"[round{rnd}] done best_score={best_result['score']}", file=sys.stderr)
        if not improved:
            break

    report = {
        "baseline": base,
        "best": {**best_result, "params": best_params},
        "rounds": round_logs,
        "note": "候选参数（不自动写回默认）；阈值默认值=原硬编码，golden 不受影响",
    }
    out = Path(r"D:\dragon-board\quant-board\data\reports\lifecycle-threshold-search.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["best"], ensure_ascii=False), file=sys.stderr)
    print("DONE", file=sys.stderr)


def _inherited(current: RankTrendConfig, key: str, cand: object) -> dict:
    """继承 current 已采纳的阈值，仅替换 key 为 cand。"""
    data = {}
    for f in RankTrendConfig.__dataclass_fields__:
        if f.startswith(("cycleRaw", "cycleNorm", "cycleConf")):
            data[f] = getattr(current, f)
    data[key] = cand
    return data


if __name__ == "__main__":
    main()
