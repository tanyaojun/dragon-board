# -*- coding: utf-8 -*-
"""研究验证 harness：fusion(crossSection×ATR 过热/超卖) vs crossSection(追强) vs atr(均值回归)。

在 half_hour 快照 universe 上，比较三个信号在各自 buy/sell 方向上的前视收益区分度：

- fusion：用 `analyze_cross_section_overheat(cross_tier, vol_rank, config)` 校准出的方向
  （横截面强势+放量过热 → sell 回归；横截面弱势+缩量企稳 → buy 超卖回升）。其中
  cross_tier 来自 observation.crossSection.signalTier，vol_rank 是该股
  pct_vol = ATR_close_only/close 相对当帧全体的分位(0-1)，ATR 复用 engine replay 累积的
  atrMeanReversion.atr（close-only 口径）。ATR 不可用 → vol_rank=None → fusion unknown（fail-visible）。
- crossSection：existing 追强方向（A/B→buy，C/D→sell）。
- atr：existing atrMeanReversion.direction（价格通道回归）。

前视收益口径与 backend/analysis/ranktrend/tier_monotonicity.py::tier_forward_returns 完全一致：
信号帧 → 未来 horizon 帧的 percentileDelta（0-1 刻度），excess 对照样本所在分位桶基线
（去均值回归趋势）。**buy/sell 分组统计，绝不混合两方向的单调统计。**

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe scripts\\ranktrend_overheat_validation.py --type half_hour
      [--dataset dragonboard_live] [--start 2026-07-01] [--end 2026-08-14]
      [--horizon 1 8] [--out data/reports/ranktrend-overheat-validation.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# 允许直接从 quant-board 仓库根目录运行（scripts/*.py 的父目录即仓库根）
_SELF_DIR = Path(__file__).resolve().parent
if str(_SELF_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SELF_DIR.parent))

from backend.analysis.ranktrend.atr_mean_reversion import bar_of
from backend.analysis.ranktrend.cross_section_vol_overheat import analyze_cross_section_overheat
from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.tier_monotonicity import (
    MIN_S_SAMPLES,
    MIN_SA_EXCESS_ACCURACY,
    _build_lookup,
    _percentile,
)
from backend.core.settings import get_settings
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

DIRECTIONS = ("buy", "sell")
STRONG_TIERS = ("A", "B")
WEAK_TIERS = ("C", "D")
BUCKET_COUNT = 10


# ─────────────────────────────────────────────────────────────────────────────
# 数据加载 + replay（复用现有 harness，与 diagnose_tier_discrimination 同源）
# ─────────────────────────────────────────────────────────────────────────────
def _load_frames(dataset_id: str, start_date: str, end_date: str, snapshot_type: str) -> list[dict[str, Any]]:
    settings = get_settings()
    print(
        f"[validate] mongodb={settings.storage_backend} db={settings.mongodb_database} "
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


# ─────────────────────────────────────────────────────────────────────────────
# 观察值读取助手（全部 fail-visible：缺字段/非法值 → None/unknown，不伪造）
# ─────────────────────────────────────────────────────────────────────────────
def _observation_of(signal: dict[str, Any]) -> dict[str, Any]:
    return ((signal or {}).get("rankTrend") or {}).get("observation") or {}


def _cross_tier(signal: dict[str, Any]) -> str | None:
    tier = (_observation_of(signal).get("crossSection") or {}).get("signalTier")
    return str(tier) if tier in (*STRONG_TIERS, *WEAK_TIERS) else None


def _atr_value(signal: dict[str, Any]) -> float | None:
    atr = (_observation_of(signal).get("atrMeanReversion") or {}).get("atr")
    try:
        atr = float(atr)
    except (TypeError, ValueError):
        return None
    return atr if atr is not None and atr > 0 and atr == atr else None  # 排除 NaN/非正


def _atr_direction(signal: dict[str, Any]) -> str | None:
    d = (_observation_of(signal).get("atrMeanReversion") or {}).get("direction")
    return d if d in DIRECTIONS else None


def _cross_section_direction(signal: dict[str, Any]) -> str | None:
    """existing crossSection 追强方向：A/B→buy（追强），C/D→sell（弱势回避）。"""
    tier = _cross_tier(signal)
    if tier in STRONG_TIERS:
        return "buy"
    if tier in WEAK_TIERS:
        return "sell"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# vol_rank：该股 pct_vol = ATR_close_only/close 相对当帧全体的分位(0-1)
# ─────────────────────────────────────────────────────────────────────────────
def _compute_vol_ranks(signals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> dict[tuple[str, str], float]:
    """返回 {(snapshotId, code): vol_rank(0-1]}。

    vol_rank 基于该股当帧 pct_vol 在'当帧全体有效 pct_vol'中的分位（中位秩分数：x∈(0,1]）。
    当帧全体 = 该帧内 ATR 可用的股票集合（ATR 不可用股票无 pct_vol，不参与分位 —— fail-visible，
    从 fusion 的 unknown 占比可见）。
    """
    frame_index, by_code = _build_lookup(frames)
    frame_pct: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for signal in signals:
        sid = str(signal.get("snapshotId") or "")
        code = str(signal.get("code") or "")
        entry = frame_index.get(sid)
        if entry is None:
            continue
        row = (by_code[entry] or {}).get(code)
        if not row:
            continue
        atr = _atr_value(signal)
        bar = bar_of(row)
        if bar is None:
            continue
        close = bar[2]  # bar_of 对 close 有 price/lastPrice 回退
        if atr is None or not close or close <= 0:
            continue
        frame_pct[sid].append((code, atr / float(close)))

    frame_sorted: dict[str, list[float]] = {}
    for sid, items in frame_pct.items():
        frame_sorted[sid] = sorted(pct for _code, pct in items)

    vol_ranks: dict[tuple[str, str], float] = {}
    for sid, items in frame_pct.items():
        vals = frame_sorted[sid]
        n = len(vals)
        for code, pct in items:
            less = sum(1 for v in vals if v < pct)
            equal = sum(1 for v in vals if v == pct)
            vol_ranks[(sid, code)] = (less + 0.5 * equal) / n
    return vol_ranks


def _fusion_direction(
    signal: dict[str, Any], vol_ranks: dict[tuple[str, str], float], config: RankTrendConfig
) -> dict[str, Any]:
    """返回 analyze_cross_section_overheat 的原始结果（fail-visible：含 status/direction/score/reasons）。"""
    cross_tier = _cross_tier(signal)
    sid = str(signal.get("snapshotId") or "")
    code = str(signal.get("code") or "")
    vol_rank = vol_ranks.get((sid, code))
    return analyze_cross_section_overheat(cross_tier, vol_rank, config)


# ─────────────────────────────────────────────────────────────────────────────
# 方向分组前视收益（复用 tier_forward_returns 的 percentileDelta + 分位桶基线口径）
# ─────────────────────────────────────────────────────────────────────────────
def _direction_forward_stats(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    horizon: int,
    direction_fn: Callable[[dict[str, Any]], str | None],
) -> dict[str, Any]:
    frame_index, by_code = _build_lookup(frames)
    totals = len(frames)
    groups: dict[str, list[tuple[float, float]]] = {d: [] for d in DIRECTIONS}
    # 全体前视样本按当前分位分桶 → 去趋势基线（buy 用 delta>0 基线、sell 用 delta<0 基线）
    buckets: dict[int, list[float]] = {b: [] for b in range(BUCKET_COUNT)}

    for signal in signals:
        code = str(signal.get("code") or "")
        entry = frame_index.get(str(signal.get("snapshotId") or ""))
        if entry is None or entry + horizon >= totals:
            continue  # 帧边界不足：该样本不计入（fail-visible：count 缺失可见）
        future = entry + horizon
        current = (by_code[entry] or {}).get(code)
        target = (by_code[future] or {}).get(code)
        if not current or not target:
            continue
        current_pct = _percentile(float(current.get("rank") or 0), len(by_code[entry]))
        future_pct = _percentile(float(target.get("rank") or 0), len(by_code[future]))
        if current_pct <= 0 or future_pct <= 0:
            continue
        delta = (future_pct - current_pct) / 100.0
        buckets[min(9, int(current_pct // 10))].append(delta)

        direction = direction_fn(signal)
        if direction in groups:
            groups[direction].append((delta, current_pct))

    # 分位桶基线（buy 指向 delta>0、sell 指向 delta<0）与桶均值
    base_acc: dict[int, dict[str, float | None]] = {}
    base_mean: dict[int, float | None] = {}
    for bucket, deltas in buckets.items():
        if deltas:
            base_acc[bucket] = {
                "buyAcc": round(sum(1 for x in deltas if x > 0) / len(deltas), 4),
                "sellAcc": round(sum(1 for x in deltas if x < 0) / len(deltas), 4),
            }
            base_mean[bucket] = round(sum(deltas) / len(deltas), 6)
        else:
            base_acc[bucket] = {"buyAcc": None, "sellAcc": None}
            base_mean[bucket] = None

    def acc_for(direction: str, delta: float) -> bool:
        return (delta > 0) if direction == "buy" else (delta < 0)

    result: dict[str, Any] = {}
    for direction in DIRECTIONS:
        samples = groups[direction]
        count = len(samples)
        if count == 0:
            result[direction] = _empty_group_stats(horizon)
            continue
        deltas = [sample[0] for sample in samples]
        pcts = [sample[1] for sample in samples]
        accuracy = sum(1 for d in deltas if acc_for(direction, d)) / count
        mean_return = sum(deltas) / count

        acc_key = "buyAcc" if direction == "buy" else "sellAcc"
        baseline_accs = [base_acc[min(9, int(p // 10))][acc_key] for p in pcts]
        baseline_accs = [v for v in baseline_accs if v is not None]
        baseline_acc = sum(baseline_accs) / len(baseline_accs) if baseline_accs else None
        excess_acc = round(accuracy - baseline_acc, 4) if baseline_acc is not None else None

        baseline_means = [base_mean[min(9, int(p // 10))] for p in pcts]
        baseline_means = [v for v in baseline_means if v is not None]
        baseline_mean = sum(baseline_means) / len(baseline_means) if baseline_means else None
        excess_mean = round(mean_return - baseline_mean, 6) if baseline_mean is not None else None

        checks = {
            "minSamples": {"ok": count >= MIN_S_SAMPLES, "actual": count},
            "saExcessAccuracy": {
                "ok": excess_acc is None or excess_acc >= MIN_SA_EXCESS_ACCURACY,
                "actual": excess_acc,
            },
        }
        result[direction] = {
            "horizon": horizon,
            "count": count,
            "meanFutureReturn": round(mean_return, 6),
            "excessMeanFutureReturn": excess_mean,
            "directionAccuracy": round(accuracy, 4),
            "bucketBaselineAccuracy": round(baseline_acc, 4) if baseline_acc is not None else None,
            "saExcessAccuracy": excess_acc,  # = 去趋势后的方向精度增量（任务所称 saEx）
            "passHard": all(check["ok"] for check in checks.values()),
            "checks": checks,
        }
    # 每个 horizon 附上分位桶基线，便于审计
    result["_bucketBaselines"] = base_acc
    return result


def _empty_group_stats(horizon: int) -> dict[str, Any]:
    checks = {
        "minSamples": {"ok": False, "actual": 0},
        "saExcessAccuracy": {"ok": False, "actual": None},
    }
    return {
        "horizon": horizon,
        "count": 0,
        "meanFutureReturn": None,
        "excessMeanFutureReturn": None,
        "directionAccuracy": None,
        "bucketBaselineAccuracy": None,
        "saExcessAccuracy": None,
        "passHard": False,
        "checks": checks,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 汇总 + verdict
# ─────────────────────────────────────────────────────────────────────────────
def _summarize_baseline(stats_by_horizon: dict[int, dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for direction in DIRECTIONS:
        summary[direction] = {}
        for horizon, stats in sorted(stats_by_horizon.items()):
            group = stats.get(direction, _empty_group_stats(horizon))
            summary[direction][f"h{horizon}"] = group
    return summary


def _build_verdict(summary: dict[str, Any]) -> dict[str, Any]:
    """fusion 的 buy/sell saEx 是否显著高于 crossSection / atr 两个单选 baseline。"""
    verdict: dict[str, Any] = {}
    horizons = sorted(
        {int(key[1:]) for group in summary["fusion"].values() for key in group}
    )
    for direction in DIRECTIONS:
        verdict[direction] = {}
        for horizon in horizons:
            hkey = f"h{horizon}"
            fusion_ex = summary["fusion"][direction].get(hkey, {}).get("saExcessAccuracy")
            cs_ex = summary["crossSection"][direction].get(hkey, {}).get("saExcessAccuracy")
            atr_ex = summary["atr"][direction].get(hkey, {}).get("saExcessAccuracy")

            def gt(a: float | None, b: float | None) -> bool | None:
                if a is None or b is None:
                    return None
                return a > b

            verdict[direction][hkey] = {
                "fusionSaEx": fusion_ex,
                "crossSectionSaEx": cs_ex,
                "atrSaEx": atr_ex,
                "fusionGtCrossSection": gt(fusion_ex, cs_ex),
                "fusionGtAtr": gt(fusion_ex, atr_ex),
                "fusionMinusCrossSection": round(fusion_ex - cs_ex, 4) if fusion_ex is not None and cs_ex is not None else None,
                "fusionMinusAtr": round(fusion_ex - atr_ex, 4) if fusion_ex is not None and atr_ex is not None else None,
            }
    return verdict


def _print_report(result: dict[str, Any]) -> None:
    lines = [f"[report] frames={result['frameCount']} signals={result['signalCount']} "
             f"fusionEligible={result.get('fusionEligibleCount')}"]

    def dump(summary: dict[str, Any], label: str) -> None:
        lines.append(f"=== {label} ===")
        for name in ("fusion", "crossSection", "atr"):
            lines.append(f"--- {name} ---")
            for direction in DIRECTIONS:
                for hkey, g in sorted(summary[name][direction].items(), key=lambda kv: int(kv[0][1:])):
                    lines.append(
                        f"  {direction} {hkey}: n={g['count']} acc={g['directionAccuracy']} "
                        f"saEx={g['saExcessAccuracy']} passHard={g['passHard']}"
                    )

    dump(result["baselines"], "全池 (all signals)")
    if "withinFusionDomain" in result:
        dump(result["withinFusionDomain"], "fusion 可判定域 (ATR 可用子集，同域对照)")
    lines.append("=== verdict (fusion 可判定域) ===")
    for direction, per_h in result["verdict"].items():
        for hkey, v in per_h.items():
            lines.append(
                f"  {direction} {hkey}: fusionSaEx={v['fusionSaEx']} "
                f"csSaEx={v['crossSectionSaEx']} atrSaEx={v['atrSaEx']} "
                f"gtCrossSection={v['fusionGtCrossSection']} gtAtr={v['fusionGtAtr']}"
            )
    print("\n".join(lines), file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="fusion vs crossSection vs atr 方向区分度验证")
    parser.add_argument("--type", default="half_hour", help="snapshot_type（默认 half_hour）")
    parser.add_argument("--dataset", default="dragonboard_live")
    parser.add_argument("--start", default="2026-07-01")
    parser.add_argument("--end", default="2026-08-14")
    parser.add_argument("--horizon", type=int, nargs="+", default=[1, 8])
    parser.add_argument("--out", default="data/reports/ranktrend-overheat-validation.json")
    args = parser.parse_args()

    config = RankTrendConfig()

    frames = _load_frames(args.dataset, args.start, args.end, args.type)
    if not frames:
        print("[validate] no frames loaded — aborting (all sources empty)", file=sys.stderr)
        return 1
    print(f"[validate] loaded {len(frames)} frames", file=sys.stderr)

    signals = _run_replay(frames)
    if not signals:
        print("[validate] replay produced no signals — aborting", file=sys.stderr)
        return 1
    print(f"[validate] replay produced {len(signals)} signals", file=sys.stderr)

    vol_ranks = _compute_vol_ranks(signals, frames)
    print(f"[validate] computed vol_ranks for {len(vol_ranks)} signals "
          f"(ATR 可用占比 {round(len(vol_ranks) / max(1, len(signals)), 4)})", file=sys.stderr)

    # 三个 baseline 的方向函数
    def fusion_fn(sig: dict[str, Any]) -> str | None:
        res = _fusion_direction(sig, vol_ranks, config)
        d = res.get("direction")
        return d if d in DIRECTIONS else None

    def cross_section_fn(sig: dict[str, Any]) -> str | None:
        return _cross_section_direction(sig)

    def atr_fn(sig: dict[str, Any]) -> str | None:
        return _atr_direction(sig)

    direction_fns: dict[str, Callable[[dict[str, Any]], str | None]] = {
        "fusion": fusion_fn,
        "crossSection": cross_section_fn,
        "atr": atr_fn,
    }

    # fusion 可判定域 = ATR 可用（vol_rank 非 None）的信号子集；
    # 在此同域内重算三基线，消除"fusion 仅覆盖 ATR 可用子集"导致的池偏斜。
    fusion_codes = set(vol_ranks.keys())
    domain_signals = [
        s
        for s in signals
        if (str(s.get("snapshotId") or ""), str(s.get("code") or "")) in fusion_codes
    ]
    print(f"[validate] fusion-eligible domain signals = {len(domain_signals)}", file=sys.stderr)

    def _run_all(sig_list: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
        stats_by_h = {name: {} for name in direction_fns}
        for name, fn in direction_fns.items():
            for horizon in args.horizon:
                stats_by_h[name][horizon] = _direction_forward_stats(sig_list, frames, horizon, fn)
        summary = {name: _summarize_baseline(per_h) for name, per_h in stats_by_h.items()}
        return summary, stats_by_h

    summary, stats_by_horizon = _run_all(signals)            # 全池
    domain_summary, _ = _run_all(domain_signals)             # fusion 可判定域

    result: dict[str, Any] = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "window": {"dataset": args.dataset, "type": args.type, "start": args.start, "end": args.end},
        "horizons": args.horizon,
        "frameCount": len(frames),
        "signalCount": len(signals),
        "volRankCount": len(vol_ranks),
        "fusionEligibleCount": len(domain_signals),
        "config": {
            "atrPeriod": config.atrPeriod,
            "atrRefPeriod": config.atrRefPeriod,
            "atrChannelK": config.atrChannelK,
            "atrDeepDeviation": config.atrDeepDeviation,
            "atrGapResetBars": config.atrGapResetBars,
            "atrMaxHistoryBars": config.atrMaxHistoryBars,
            "crossVolP33": getattr(config, "crossVolP33", 0.33),
            "crossVolP67": getattr(config, "crossVolP67", 0.67),
            "crossVolP90": getattr(config, "crossVolP90", 0.90),
            "minSamples": MIN_S_SAMPLES,
            "minSaExcessAccuracy": MIN_SA_EXCESS_ACCURACY,
        },
        "baselines": summary,
        "withinFusionDomain": domain_summary,
        "verdict": _build_verdict(domain_summary),
    }

    _print_report(result)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[validate] report written to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
