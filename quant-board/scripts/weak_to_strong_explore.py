# -*- coding: utf-8 -*-
"""研究验证 harness：'弱转强'特征（低横截面百分位 + percentileDelta 转正/加速）的增量 alpha 探索。

不做任何新收益口径 —— 前视收益、去趋势分位桶基线、档位单调性全部复用
backend/analysis/ranktrend/tier_monotonicity.py::tier_forward_returns 同一套机制：

- 前视收益 = 该股在信号帧 index 未来 horizon 帧的 percentileDelta
  （percentile(future_rank) - percentile(current_rank)，0-1 刻度；_percentile 同引擎 percentile_rank 公式）。
- 去趋势基线 = 样本所在'当前 percentile 分位桶'（0-10 桶）全体样本的前视收益均值 / 方向精度 acc(>0)。
  excess α = 分组均值 − 样本匹配的分位桶基线均值（消除均值回归后分组自身的增量信息）。
- 分层维度（来自 engine replay 信号，fail-visible）：
    p = rankTrend.observation.crossSection.percentile      （当前横截面强弱 0-100）
    d = rankTrend.observation.crossSection.percentileDelta （热度排名变化，正=上升；无历史/非法 → None）
- 前视收益与基线的 current_pct 用 frames 内 rank 复算（与 tier_forward_returns 完全一致）。

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe scripts\\weak_to_strong_explore.py --type half_hour
      [--dataset dragonboard_live] [--start 2026-07-01] [--end 2026-08-14]
      [--horizon 1 8] [--out data/reports/weak-to-strong-explore.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_SELF_DIR = Path(__file__).resolve().parent
if str(_SELF_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SELF_DIR.parent))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.tier_monotonicity import (
    MIN_S_SAMPLES,
    MIN_SA_EXCESS_ACCURACY,
    _build_lookup,
    _percentile,
    tier_forward_returns,
)
from backend.core.settings import get_settings
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

# ── 二维分层参数（任务给定）───────────────────────────────────────────────
# 当前 percentile p（0-100）：low l = <30；mid m = 30~70；high h = >70
P_BUCKETS = {"l": (0.0, 30.0), "m": (30.0, 70.0), "h": (70.0, 100.0)}
# percentileDelta d（0-100 刻度变化）：neg n = <=-5；flat f = (-5,5)；pos p = [5,15)；strong s = >=15
D_BUCKETS = {"n": (-1e9, -5.0), "f": (-5.0, 5.0), "p": (5.0, 15.0), "s": (15.0, 1e9)}


def _load_frames(dataset_id: str, start_date: str, end_date: str, snapshot_type: str) -> list[dict[str, Any]]:
    settings = get_settings()
    print(
        f"[explore] mongodb={settings.storage_backend} db={settings.mongodb_database} "
        f"dataset={dataset_id} snapshot={snapshot_type} window={start_date}~{end_date}",
        file=sys.stderr,
    )
    repo = MongoRepository(get_runtime_mongodb_database())
    frames = repo.load_frame_bundles(
        dataset_id,
        snapshot_type=snapshot_type,
        start_date=start_date,
        end_date=end_date,
        projection="ranktrend",
        fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )
    return frames


def _run_replay(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    engine = RankTrendPythonEngine(config=RankTrendConfig())
    return engine.replay(frames, window_size=50)


def _cross_section(signal: dict[str, Any]) -> dict[str, Any]:
    return (((signal or {}).get("rankTrend") or {}).get("observation") or {}).get("crossSection") or {}


def _finite(x: Any) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if x == x else None  # NaN → None


def _p_bucket(p: float) -> str | None:
    for name, (lo, hi) in P_BUCKETS.items():
        if lo <= p < hi:
            return name
    return None


def _d_bucket(d: float | None) -> str | None:
    if d is None:
        return None
    for name, (lo, hi) in D_BUCKETS.items():
        if lo <= d < hi:
            return name
    return None


def _build_records(
    signals: list[dict[str, Any]], frames: list[dict[str, Any]], horizon: int
) -> list[dict[str, Any]]:
    """构建前视收益记录：delta_fwd（前视 percentileDelta，0-1 刻度）+ cur_pct + p + d。

    与 tier_forward_returns 口径一致：帧边界不足/股票缺失/rank 非法 → 该样本 skip（fail-visible）。
    p/d 缺失 → p None 该样本跳过（不在横截面）；d None 保留（d_bucket=unknown，可观测占比）。
    """
    frame_index, by_code = _build_lookup(frames)
    totals = len(frames)
    records: list[dict[str, Any]] = []
    for signal in signals:
        code = str(signal.get("code") or "")
        entry = frame_index.get(str(signal.get("snapshotId") or ""))
        if entry is None or entry + horizon >= totals:
            continue
        future = entry + horizon
        current = (by_code[entry] or {}).get(code)
        target = (by_code[future] or {}).get(code)
        if not current or not target:
            continue
        current_pct = _percentile(float(current.get("rank") or 0), len(by_code[entry]))
        future_pct = _percentile(float(target.get("rank") or 0), len(by_code[future]))
        if current_pct <= 0 or future_pct <= 0:
            continue
        delta_fwd = (future_pct - current_pct) / 100.0

        cs = _cross_section(signal)
        p = _finite(cs.get("percentile"))
        d = _finite(cs.get("percentileDelta"))
        if p is None:
            continue  # 不在横截面 → 无 p，跳过（fail-visible）
        pb = _p_bucket(float(p))
        db = _d_bucket(d) if d is not None else "unknown"
        records.append(
            {
                "delta_fwd": delta_fwd,
                "cur_pct": current_pct,
                "p": float(p),
                "d": d,
                "pb": pb,
                "db": db,
                "sid": str(signal.get("snapshotId") or ""),
                "code": code,
            }
        )
    return records


def _bucket_baselines(records: list[dict[str, Any]]) -> dict[int, dict[str, float]]:
    """当前 percentile 分位桶（0-10）的全体前视收益均值 + acc(>0)。"""
    buckets: dict[int, list[float]] = defaultdict(list)
    for r in records:
        buckets[min(9, int(r["cur_pct"] // 10))].append(r["delta_fwd"])
    out: dict[int, dict[str, float]] = {}
    for bucket, deltas in buckets.items():
        if deltas:
            out[bucket] = {
                "mean": sum(deltas) / len(deltas),
                "acc": sum(1 for x in deltas if x > 0) / len(deltas),
                "n": len(deltas),
            }
    return out


def _bucket_excess(
    records: list[dict[str, Any]],
    baselines: dict[int, dict[str, float]],
    key_fn: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    """按 key_fn 分组，统计 count / meanFutureReturn / acc / 相对分位桶基线的 excess。

    excess_mean = 组均值 − 组内样本各自匹配的分位桶基线均值（平均）。
    excess_acc  = 组 acc(>0) − 组内样本各自匹配的分位桶基线 acc（平均）。
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        k = key_fn(r)
        if k is not None:
            groups[k].append(r)

    result: dict[str, dict[str, Any]] = {}
    for key, items in groups.items():
        deltas = [r["delta_fwd"] for r in items]
        mean = sum(deltas) / len(deltas)
        acc = sum(1 for x in deltas if x > 0) / len(deltas)
        base_means = [baselines[min(9, int(r["cur_pct"] // 10))]["mean"] for r in items]
        base_accs = [baselines[min(9, int(r["cur_pct"] // 10))]["acc"] for r in items]
        base_mean = sum(base_means) / len(base_means)
        base_acc = sum(base_accs) / len(base_accs)
        result[key] = {
            "count": len(items),
            "meanFutureReturn": round(mean, 6),
            "directionAccuracy": round(acc, 4),
            "bucketBaselineMean": round(base_mean, 6),
            "bucketBaselineAccuracy": round(base_acc, 4),
            # excess α（增量）—— 与 tier_forward_returns 口径一致
            "excessMeanFutureReturn": round(mean - base_mean, 6),
            "excessDirectionAccuracy": round(acc - base_acc, 4),
            "minSamplesOk": len(items) >= MIN_S_SAMPLES,
            "excessAccAbove": (acc - base_acc) >= MIN_SA_EXCESS_ACCURACY,
        }
    return result


def _print_report(result: dict[str, Any]) -> None:
    lines = [
        f"[report] frameCount={result['frameCount']} signalCount={result['signalCount']} "
        f"records={result['recordCount']} (d-unknown {result['deltaUnknownCount']})"
    ]
    lines.append("=== (p,d) bucket α table ===")
    lines.append("  pb db   n   meanFwd   baseMean  exMean   acc   baseAcc  exAcc  ok")
    for horizon, bd in sorted(result["bucketTable"].items()):
        lines.append(f"  [horizon h{horizon}]")
        for key, st in sorted(bd.items()):
            pb, db = key.split("_", 1)
            lines.append(
                f"  {pb}  {db:>4}  {st['count']:>5}  {st['meanFutureReturn']:>8.4f} "
                f"{st['bucketBaselineMean']:>8.4f} {st['excessMeanFutureReturn']:>+8.4f} "
                f"{st['directionAccuracy']:>5.3f} {st['bucketBaselineAccuracy']:>6.3f} "
                f"{st['excessDirectionAccuracy']:>+7.4f} {'Y' if st['minSamplesOk'] else '-'}"
            )
    lines.append("=== monotonicity by percentile (p) → 追强效应 ===")
    for horizon, m in sorted(result["pTable"].items()):
        lines.append(f"  h{horizon}: " + "  ".join(
            f"{k}: exMean={v['excessMeanFutureReturn']:+.4f} n={v['count']}" for k, v in sorted(m.items())
        ))
    lines.append("=== monotonicity by delta (d) → 转强/加速效应 ===")
    for horizon, m in sorted(result["dTable"].items()):
        lines.append(f"  h{horizon}: " + "  ".join(
            f"{k}: exMean={v['excessMeanFutureReturn']:+.4f} exAcc={v['excessDirectionAccuracy']:+.4f} n={v['count']}"
            for k, v in sorted(m.items())
        ))
    lines.append("=== crossSection tier monotonicity (reuse tier_forward_returns) ===")
    for horizon, tm in sorted(result["tierMonotonicity"].items()):
        tiers = tm.get("tiers", {})
        lines.append(f"  h{horizon}: " + "  ".join(
            f"{t}: exMean={tiers[t].get('excessMeanFutureReturn')} n={tiers[t].get('count')}"
            for t in ("S", "A", "B", "C", "D") if t in tiers
        ))
    lines.append("=== verdict ===")
    for horizon, v in sorted(result["verdict"].items()):
        lines.append(f"  h{horizon}: {json.dumps(v, ensure_ascii=False)}")
    print("\n".join(lines), file=sys.stderr)


def _verdict(bucket_table: dict[int, dict[str, Any]], p_table: dict[int, dict[str, Any]], d_table: dict[int, dict[str, Any]]) -> dict[int, Any]:
    """弱转强 (low, pos/strong_pos) vs 对照组 + 是否仅为已知 crossSection 追强效应。"""
    out: dict[int, Any] = {}
    for horizon in sorted(bucket_table.keys()):
        bd = bucket_table[horizon]
        wts_p = bd.get(("l", "p"))
        wts_s = bd.get(("l", "s"))
        weak_neg = bd.get(("l", "n"))
        mid_pos = bd.get(("m", "p"))
        high_pos = bd.get(("h", "p"))

        def g(st: dict[str, Any] | None, field: str) -> float | None:
            return (st or {}).get(field)

        # 弱转强候选中择优（有样本者优先 strong_pos；否则 pos）
        best_wts = wts_s if (wts_s and wts_s["count"] >= MIN_S_SAMPLES) else wts_p
        verdict: dict[str, Any] = {
            "weakToStrong": {
                "bucket": ("l", "s") if best_wts is wts_s else ("l", "p"),
                "excessMeanFutureReturn": g(best_wts, "excessMeanFutureReturn"),
                "excessDirectionAccuracy": g(best_wts, "excessDirectionAccuracy"),
                "count": g(best_wts, "count"),
                "minSamplesOk": bool(g(best_wts, "minSamplesOk")),
                "positive": bool(g(best_wts, "excessMeanFutureReturn") is not None and g(best_wts, "excessMeanFutureReturn") > 0),
            },
            "controls": {
                "weakToWeaker(l,n)": g(weak_neg, "excessMeanFutureReturn"),
                "midToStrong(m,p)": g(mid_pos, "excessMeanFutureReturn"),
                "highToStronger(h,p)": g(high_pos, "excessMeanFutureReturn"),
            },
        }
        # 显著优于各对照（excess 差值）
        wts_ex = g(best_wts, "excessMeanFutureReturn")
        def beat(ctrl: float | None) -> bool | None:
            if wts_ex is None or ctrl is None:
                return None
            return wts_ex > ctrl
        verdict["beatsControls"] = {
            "gt_weakToWeaker": beat(g(weak_neg, "excessMeanFutureReturn")),
            "gt_midToStrong": beat(g(mid_pos, "excessMeanFutureReturn")),
            "gt_highToStronger": beat(g(high_pos, "excessMeanFutureReturn")),
        }
        # 是否仅为 crossSection 追强效应：若转强价值在各 p 桶一致（mid/high 转强同样强），
        # 且弱转强 ≈ 高转强，则低分位的'delta 转正'不提供额外区分（增量无）。
        pt = p_table.get(horizon, {})
        dt = d_table.get(horizon, {})
        verdict["incrementalityCheck"] = {
            "p_l": g(pt.get("l"), "excessMeanFutureReturn"),
            "p_m": g(pt.get("m"), "excessMeanFutureReturn"),
            "p_h": g(pt.get("h"), "excessMeanFutureReturn"),
            "d_pos": g(dt.get("p"), "excessMeanFutureReturn"),
            "d_strong": g(dt.get("s"), "excessMeanFutureReturn"),
        }
        out[horizon] = verdict
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="弱转强特征增量 alpha 探索")
    parser.add_argument("--type", default="half_hour")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--start", default="2026-07-01")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--horizon", type=int, nargs="+", default=[1, 8])
    parser.add_argument("--out", default="data/reports/weak-to-strong-explore.json")
    args = parser.parse_args()

    frames = _load_frames(args.dataset, args.start, args.end, args.type)
    if not frames:
        print("[explore] no frames loaded — aborting", file=sys.stderr)
        return 1
    print(f"[explore] loaded {len(frames)} frames", file=sys.stderr)

    signals = _run_replay(frames)
    if not signals:
        print("[explore] replay produced no signals — aborting", file=sys.stderr)
        return 1
    print(f"[explore] replay produced {len(signals)} signals", file=sys.stderr)

    config = RankTrendConfig()

    bucket_table: dict[int, dict[str, dict[str, Any]]] = {}
    p_table: dict[int, dict[str, Any]] = {}
    d_table: dict[int, dict[str, Any]] = {}
    tier_mono: dict[int, dict[str, Any]] = {}
    record_counts: dict[int, int] = {}
    delta_unknown: dict[int, int] = {}

    for horizon in args.horizon:
        records = _build_records(signals, frames, horizon)
        record_counts[horizon] = len(records)
        delta_unknown[horizon] = sum(1 for r in records if r["db"] == "unknown")

        baselines = _bucket_baselines(records)
        # 二维 (p,d) 桶
        bd = _bucket_excess(records, baselines, lambda r: (r["pb"], r["db"]))
        bucket_table[horizon] = {k: v for k, v in bd.items() if k[0] is not None and k[1] != "unknown"}
        # 一维 p 桶（追强效应）
        p_table[horizon] = {k: v for k, v in _bucket_excess(records, baselines, lambda r: r["pb"]).items() if k is not None}
        # 一维 d 桶（转强/加速效应）
        d_table[horizon] = {k: v for k, v in _bucket_excess(records, baselines, lambda r: r["db"]).items() if k != "unknown"}
        # crossSection tier 单调性（复用 tier_forward_returns 原始 harness）
        tier_mono[horizon] = tier_forward_returns(signals, frames, horizon=horizon, dimension="crossSection")

    # tuple key (pb, db) 不可被 json.dumps 序列化为 key，这里转成字符串键（"l_p"）
    bucket_table_str: dict[int, dict[str, Any]] = {
        h: {f"{pb}_{db}": v for (pb, db), v in bd.items()}
        for h, bd in bucket_table.items()
    }

    result: dict[str, Any] = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "window": {"dataset": args.dataset, "type": args.type, "start": args.start, "end": args.end},
        "horizons": args.horizon,
        "frameCount": len(frames),
        "signalCount": len(signals),
        "recordCount": record_counts,
        "deltaUnknownCount": delta_unknown,
        "config": {
            "pBuckets": P_BUCKETS,
            "dBuckets": D_BUCKETS,
            "minSamples": MIN_S_SAMPLES,
            "minExcessAccuracy": MIN_SA_EXCESS_ACCURACY,
            "dimension": "crossSection",
            "atrPeriod": config.atrPeriod,
        },
        "bucketTable": bucket_table_str,
        "pTable": p_table,
        "dTable": d_table,
        "tierMonotonicity": tier_mono,
        "verdict": _verdict(bucket_table, p_table, d_table),
    }

    _print_report(result)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[explore] report written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
