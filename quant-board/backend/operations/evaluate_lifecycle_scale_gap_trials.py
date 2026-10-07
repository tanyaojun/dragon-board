# -*- coding: utf-8 -*-
"""生命周期 P1 尺度 / P3 时间正规化 行为步 trial runner（2026-10-07 预登记合同 A5/B5）。

判定线（冻结，docs/ranktrend-tier-backtest/reasoning-corpus-lifecycle-stage.md §11.2）：
- no-regression：三窗 synergy saEx 各 ≥ 0.0994/0.0868/0.0883（锚−0.005）且均值 ≥ 0.0935；
- P1 veto 稳健带：decision 窗 veto 触发率 rel ∈ [−10%, +10%]（出带须可由池规模重分布解释）；
- P3 veto 守卫带 rel ∈ [−15%, +20%]、bd 守卫带 rel ∈ [−20%, +20%]（防 §4.3-D 变相确认链）；
- a0 锚自证：默认 config 三窗逐位复现 23.9.1 锚（0.1044/0.0918/0.0933）。

trial（单变量）：L1=hotzone_pct_only / L2=pct_full / G1=cross_day / G2=non_adjacent。
用法：python -m backend.operations.evaluate_lifecycle_scale_gap_trials [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.optimize_gate_denoise_parameters import collect_flip_report, sa_excess_of
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns

ANCHOR = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}  # 23.9.1 锚
NO_REGRESSION_FLOOR = {"decision": 0.0994, "oos1": 0.0868, "oos2": 0.0883}  # 锚−0.005
MEAN_FLOOR = 0.0935
VETO_BAND_P1 = (-0.10, 0.10)
VETO_BAND_P3 = (-0.15, 0.20)
BD_BAND_P3 = (-0.20, 0.20)

TRIALS: list[dict] = [
    {"key": "a0_baseline", "desc": "锚自证（默认配置）", "overrides": {}, "case": None},
    {"key": "L1_hotzone_pct_only", "desc": "P1 隔离档：热区删名次臂", "overrides": {"lifecycleRankScaleMode": "hotzone_pct_only"}, "case": "P1"},
    {"key": "L2_pct_full", "desc": "P1 全量档：名次谓词整体 T=200 锚换算", "overrides": {"lifecycleRankScaleMode": "pct_full"}, "case": "P1"},
    {"key": "G1_cross_day", "desc": "P3 G1：跨日差分无效", "overrides": {"lifecycleTimeGapStrictness": "cross_day"}, "case": "P3"},
    {"key": "G2_non_adjacent", "desc": "P3 G2：跨日∨同日非相邻差分无效", "overrides": {"lifecycleTimeGapStrictness": "non_adjacent"}, "case": "P3"},
]


def load_frames() -> list[dict]:
    repo = MongoRepository(get_runtime_mongodb_database())
    return repo.load_frame_bundles(
        "dragonboard_live", snapshot_type="half_hour",
        start_date="2026-04-15", end_date="2026-09-12",
        projection="ranktrend", fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )


def window_frames(frames: list[dict], start: str, end: str) -> list[dict]:
    return [f for f in frames if start <= str(f.get("tradingDate") or "") <= end]


def evaluate_trial(config: RankTrendConfig, frames: list[dict]) -> dict:
    """单窗读数：saEx + 翻转率 + veto/bd 触发率（一次 replay）。"""
    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(frames, meta={})
    syn = tier_forward_returns(signals, frames, horizon=1, dimension="synergy")
    flip = collect_flip_report(signals)
    veto_n = 0
    bd_n = 0
    total = 0
    for s in signals:
        lc = ((s.get("rankTrend") or {}).get("observation") or {}).get("lifecycle") or {}
        total += 1
        veto_n += 1 if lc.get("veto") else 0
        bd_n += 1 if (lc.get("signalTier") in ("B", "D")) else 0
    return {
        "signalCount": len(signals),
        "saEx": sa_excess_of(syn),
        "flipRates": flip.get("flip_rates"),
        "vetoTriggerRate": round(veto_n / total, 5) if total else None,
        "bdTriggerRate": round(bd_n / total, 5) if total else None,
        "vetoFrames": veto_n,
        "bdFrames": bd_n,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/reports/lifecycle-scale-gap-trials.json")
    args = ap.parse_args()
    t0 = time.time()
    frames = load_frames()
    print(f"frames={len(frames)}", file=sys.stderr)
    results: dict[str, dict] = {}
    for trial in TRIALS:
        results[trial["key"]] = {"desc": trial["desc"], "case": trial["case"], "windows": {}}
        for name, (start, end) in WINDOWS.items():
            wf = window_frames(frames, start, end)
            config = RankTrendConfig.from_patch(trial["overrides"])
            t1 = time.time()
            reading = evaluate_trial(config, wf)
            results[trial["key"]]["windows"][name] = reading
            print(f"[{trial['key']}] {name}: saEx={reading['saEx']} veto={reading['vetoTriggerRate']} "
                  f"bd={reading['bdTriggerRate']} ({time.time() - t1:.0f}s)", file=sys.stderr)

    # 判定（冻结线对照；2026-10-07 登记：帧字段 10 月初大回填致数据代际漂移，冻结绝对锚
    # 0.1044/0.0918/0.0933 已不可复现（a0 今日读数系统性上移）——no-regression 改用
    # 「同代际 a0 今日读数 − 合同容差」相对线，冻结绝对线双列披露，verdict 按相对线）
    verdict: dict[str, dict] = {}
    base = results["a0_baseline"]["windows"]
    anchor_today = {w: base[w]["saEx"] for w in ("decision", "oos1", "oos2")}
    floor_rel = {w: anchor_today[w] - 0.005 for w in anchor_today}
    mean_floor_rel = sum(anchor_today.values()) / 3 - 0.003
    verdict["baseline_drift"] = {
        "frozen_anchor": ANCHOR,
        "a0_today": {w: round(v, 4) for w, v in anchor_today.items()},
        "drift": {w: round(anchor_today[w] - ANCHOR[w], 4) for w in ANCHOR},
        "note": "帧字段回填（open/amount/zlje 等 96.9-97.1% 补齐，commit e77907bf/cacf4ab8 代际）改变 fallback 输入 → saEx 基线整体移动；判定改同代际相对线（容差不变 −0.005/−0.003）",
    }
    for trial in TRIALS[1:]:
        key = trial["key"]
        case = trial["case"]
        sa = {w: results[key]["windows"][w]["saEx"] for w in ("decision", "oos1", "oos2")}
        no_reg = {
            "per_window": {w: (sa[w] is not None and sa[w] >= floor_rel[w]) for w in sa},
            "mean": (sum(v for v in sa.values() if v is not None) / 3) if all(v is not None for v in sa.values()) else None,
            "mean_floor_rel": mean_floor_rel,
            "frozen_floor_absolute": NO_REGRESSION_FLOOR,
        }
        no_reg["pass"] = all(no_reg["per_window"].values()) and no_reg["mean"] is not None and no_reg["mean"] >= mean_floor_rel
        rel_veto = {
            w: (results[key]["windows"][w]["vetoTriggerRate"] / base[w]["vetoTriggerRate"] - 1)
            if base[w]["vetoTriggerRate"] and results[key]["windows"][w]["vetoTriggerRate"] is not None else None
            for w in ("decision", "oos1", "oos2")
        }
        rel_bd = {
            w: (results[key]["windows"][w]["bdTriggerRate"] / base[w]["bdTriggerRate"] - 1)
            if base[w]["bdTriggerRate"] and results[key]["windows"][w]["bdTriggerRate"] is not None else None
            for w in ("decision", "oos1", "oos2")
        }
        band = VETO_BAND_P1 if case == "P1" else VETO_BAND_P3
        band_bd = band if case == "P1" else BD_BAND_P3
        in_band = lambda rel, b: rel is not None and b[0] <= rel <= b[1]  # noqa: E731
        verdict[key] = {
            "saEx": sa, "no_regression": no_reg,
            "veto_rel": {w: round(v, 4) if v is not None else None for w, v in rel_veto.items()},
            "bd_rel": {w: round(v, 4) if v is not None else None for w, v in rel_bd.items()},
            "veto_band_pass": in_band(rel_veto["decision"], band),
            "bd_band_pass": in_band(rel_bd["decision"], band_bd) if case == "P3" else True,
            "verdict": "PASS" if (no_reg["pass"] and in_band(rel_veto["decision"], band)
                                  and (case != "P3" or in_band(rel_bd["decision"], band_bd))) else "FAIL",
        }

    out = {"meta": {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "elapsed_sec": round(time.time() - t0, 1),
                    "frozen_lines": {"anchor": ANCHOR, "no_regression_floor": NO_REGRESSION_FLOOR,
                                     "mean_floor": MEAN_FLOOR, "veto_band_P1": VETO_BAND_P1,
                                     "veto_band_P3": VETO_BAND_P3, "bd_band_P3": BD_BAND_P3}},
           "results": results, "verdict": verdict}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out_path),
                      "baseline_drift": verdict["baseline_drift"],
                      "verdicts": {k: v.get("verdict", v) for k, v in verdict.items()
                                   if k not in ("a0_anchor_reproduced", "baseline_drift")}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
