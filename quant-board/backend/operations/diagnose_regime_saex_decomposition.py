# -*- coding: utf-8 -*-
"""OOS 失败解剖复核：regime 分桶 × synergy saEx 分解（只读诊断，2026-09-10）。

背景（2026-09-10 会话解剖结论，本脚本复核后落盘 longterm-backtest-plan 阶段 14）：
- 机制 1：决策窗 strong（信号级 n=19333, 14.6%）内部本来 passHard=False（A 档 exAcc≈0、
  B>A 反序、组内 saEx≈0.0224）；OOS-2 strong 占比 15%→25.7% 把 ALL 加权 saEx 拖到
  0.0422（门槛 0.05），无反序（spearman=1.0）——既有缺陷 × 市况构成变化。
- 机制 2：OOS-1 唯一反序 A>S（S 0.0342 vs A 0.0853）——A 档上行从"上面"顶破硬序，
  属"好消息型失败"。
- 机制 3：B/C/D 三窗一致无区分度。

本脚本对三窗口做 baseline replay 后按 regime state（rankTrend.strategy.regime.state，
市场级状态，同帧全股相同）分桶分解，验证：
a) 各桶 saEx / A 档 exAcc / S-A-B 反序与解剖数字一致；
b) raw directionAccuracy 可由桶×样本数精确加权重构（exAcc 不可线性重构——分位桶基线
   随组重算，差异本身是证据：strong 组基线与 ALL 基线不同）；
c) 逐日 strong 占比与当日 synergy saEx 的同向性（占比↔拖累链条的日间维度）。

桶内 passHard/0.05 门槛仅为诊断视图（生产判定是 ALL 口径），不构成采纳依据。
只读：不写库、不改默认值；报告落 data/reports/，fail-visible 缺失如实计数。

用法：
  python -m backend.operations.diagnose_regime_saex_decomposition [--window all|decision|oos1|oos2] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.research.gate_flip_stats import extract_gate_states
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR
from backend.operations.optimize_resonance_parameters import _tier_summary, load_frames, sa_excess_of

WINDOWS: dict[str, dict[str, str]] = {
    "decision": {"start": "2026-04-15", "end": "2026-07-31"},
    "oos1": {"start": "2026-08-15", "end": "2026-08-31"},
    "oos2": {"start": "2026-09-01", "end": "2026-09-09"},
}


def _regime_state_of(signal: dict[str, Any]) -> str:
    return str(extract_gate_states(signal).get("regime_state") or "")


def _day_of_snapshot(snapshot_id: str) -> str:
    # snapshotId 形如 "half_hour:2026-09-01:09:30"；格式不符返回空（fail-visible，当日计入 <missing>）
    parts = str(snapshot_id or "").split(":")
    return parts[1] if len(parts) >= 2 else ""


def _mono_detail(stats: dict[str, Any]) -> dict[str, Any]:
    mono = stats.get("monotonicity") or {}
    return {
        "spearman": mono.get("spearmanRankCorr"),
        "passHardConstraint": mono.get("passHardConstraint"),
        "hardOrderViolations": mono.get("hardOrderViolations"),
        "reversals": mono.get("reversals"),
    }


def analyze_window(name: str, bounds: dict[str, str]) -> dict[str, Any]:
    from backend.optimization.data_windows import assert_not_frozen

    frames = load_frames(bounds["start"], bounds["end"])
    if not frames:
        return {"window": name, "error": "no frames loaded"}
    # 机制验证属报告用途（非参数决策）；守卫仍确认窗口不含 FINAL 冻结段之外的越界引用
    assert_not_frozen(frames, "report")

    engine = RankTrendPythonEngine(config=RankTrendConfig())
    signals = engine.replay(frames, meta={})
    if not signals:
        return {"window": name, "error": "replay produced no signals"}

    # 信号级 regime state 分布（市场级状态，同帧全股相同；空值如实计数）
    state_of_signal = [_regime_state_of(signal) for signal in signals]
    state_counts: dict[str, int] = defaultdict(int)
    for state in state_of_signal:
        state_counts[state or "<missing>"] += 1

    # 逐桶 tier 统计（h1，synergy 主口径；分位桶基线在桶内重算）
    def bucketed(state: str):
        return lambda signal: _regime_state_of(signal) == state

    all_stats = tier_forward_returns(signals, frames, horizon=1, dimension="synergy")
    buckets: dict[str, dict[str, Any]] = {}
    for state in sorted(state_counts):
        if state == "<missing>":
            continue
        stats = tier_forward_returns(
            signals, frames, horizon=1, dimension="synergy", signal_filter=bucketed(state)
        )
        tiers = stats.get("tiers") or {}
        buckets[state] = {
            "signalCount": state_counts[state],
            "signalShare": round(state_counts[state] / len(signals), 4),
            "tierSampleCount": sum(int((tiers.get(t) or {}).get("count") or 0) for t in ("S", "A", "B", "C", "D", "E", "unknown")),
            "saEx": round(sa_excess_of(stats), 4) if sa_excess_of(stats) is not None else None,
            "tiers": {
                tier: {
                    "count": (tiers.get(tier) or {}).get("count"),
                    "directionAccuracy": (tiers.get(tier) or {}).get("directionAccuracy"),
                    "excessDirectionAccuracy": (tiers.get(tier) or {}).get("excessDirectionAccuracy"),
                    "excessMeanFutureReturn": (tiers.get(tier) or {}).get("excessMeanFutureReturn"),
                    "bucketBaselineAccuracy": (tiers.get(tier) or {}).get("bucketBaselineAccuracy"),
                }
                for tier in ("S", "A", "B", "C")
            },
            "monotonicity": _mono_detail(stats),
        }

    # raw directionAccuracy 加权重构（桶×样本数 → ALL；exAcc 不可线性重构，见模块 docstring）
    def reconstruct(tier: str) -> dict[str, Any]:
        num = 0.0
        den = 0
        for state, payload in buckets.items():
            entry = payload["tiers"].get(tier) or {}
            count = int(entry.get("count") or 0)
            acc = entry.get("directionAccuracy")
            if count and acc is not None:
                num += count * acc
                den += count
        if den <= 0:
            return {"reconstructed": None, "denominator": 0}
        all_entry = (all_stats.get("tiers") or {}).get(tier) or {}
        return {
            "reconstructed": round(num / den, 4),
            "actual": all_entry.get("directionAccuracy"),
            "denominator": den,
            "match": abs(num / den - float(all_entry.get("directionAccuracy") or 0)) < 5e-4 if all_entry.get("directionAccuracy") is not None else None,
        }

    reconstruction = {tier: reconstruct(tier) for tier in ("S", "A", "B")}

    # 逐日表：strong 帧占比（市场级，按帧去重）× 当日 synergy 统计
    day_by_signal = [_day_of_snapshot(signal.get("snapshotId")) for signal in signals]
    regime_by_snapshot: dict[str, str] = {}
    for signal in signals:
        sid = str(signal.get("snapshotId") or "")
        if sid and sid not in regime_by_snapshot:
            regime_by_snapshot[sid] = _regime_state_of(signal)
    signals_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    frames_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal, day in zip(signals, day_by_signal):
        if day:
            signals_by_day[day].append(signal)
    for frame in frames:
        day = _day_of_snapshot(frame.get("snapshotId"))
        if day:
            frames_by_day[day].append(frame)
    daily: dict[str, dict[str, Any]] = {}
    for day in sorted(signals_by_day):
        day_signals = signals_by_day[day]
        day_frames = frames_by_day.get(day) or []
        day_stats = tier_forward_returns(day_signals, day_frames, horizon=1, dimension="synergy")
        day_sids = {str(signal.get("snapshotId") or "") for signal in day_signals}
        day_states = [regime_by_snapshot[sid] for sid in day_sids if regime_by_snapshot.get(sid)]
        strong_ratio = (day_states.count("strong") / len(day_states)) if day_states else None
        daily[day] = {
            "frames": len(day_frames),
            "signals": len(day_signals),
            "strongFrameRatio": round(strong_ratio, 4) if strong_ratio is not None else None,
            "saEx": round(sa_excess_of(day_stats), 4) if sa_excess_of(day_stats) is not None else None,
            "aExAcc": (day_stats.get("tiers") or {}).get("A", {}).get("excessDirectionAccuracy"),
            "aCount": (day_stats.get("tiers") or {}).get("A", {}).get("count"),
        }

    return {
        "window": name,
        "bounds": bounds,
        "frameCount": len(frames),
        "signalCount": len(signals),
        "stateCounts": dict(state_counts),
        "all": _tier_summary(all_stats),
        "buckets": buckets,
        "directionAccuracyReconstruction": reconstruction,
        "daily": daily,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="regime 分桶 × synergy saEx 分解复核（只读）")
    parser.add_argument("--window", default="all", choices=["all", "decision", "oos1", "oos2"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    names = list(WINDOWS) if args.window == "all" else [args.window]
    results = []
    for name in names:
        print(f"[regime-saex] analyzing {name} ...", file=sys.stderr)
        result = analyze_window(name, WINDOWS[name])
        results.append(result)
        if "error" in result:
            print(f"[regime-saex] {name}: {result['error']}", file=sys.stderr)
            continue
        states = " / ".join(
            f"{state}={payload['signalShare']:.1%}(saEx={payload['saEx']})"
            for state, payload in result["buckets"].items()
        )
        print(
            f"[regime-saex] {name}: ALL saEx={result['all']['saEx']} pass={result['all']['passHard']} | {states}",
            file=sys.stderr,
        )

    out_path = Path(args.out) if args.out else REPORT_DIR / "regime-saex-decomposition.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"generatedAt": "2026-09-10", "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[regime-saex] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
