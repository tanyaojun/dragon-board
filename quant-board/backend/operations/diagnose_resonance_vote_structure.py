# -*- coding: utf-8 -*-
"""D-a 共振缺票结构解剖（方案 D，提案 §5.3，只读诊断）。

三问（§5.3 D-a）：
1. 六出口分组计数：insufficient 帧按 reason 分桶（快照时间轴不完整/新入榜关注度无效/
   横截面有效样本不足 ×2 处/排名序列不足或无效/快照样本不足）——定位 ~48% 缺票的
   主导分支，解释 unknown 跨窗波动；弃权同时拆"insufficient"与"有数据但 hold 票"
   两种结构；
2. 投票驱动结构分解：res buy/sell 票按驱动源分解（新入榜 entry_strength / Jump 事件 /
   排名序列 direction_score）——调和 G4"half_hour Jump 为 0"与 23.8"44% 帧有方向票"
   的口径矛盾（runtime.py:640 新入榜分支 entry_strength>0 → buy，不依赖 Jump）；
3. 缺票帧反事实区分度（H1/H2 直接证据）：各 insufficient 分支帧的 h1 percentileDelta
   均值 vs 全体基线——分支帧系统性正漂移 → H2（有信息被拦）；零/负 → H1（保护性）。
   投票帧的驱动分解表并列（buy 票命中率 vs 基线）作为"有票侧"参照。

分类口径（runtime.py:597-708 核实）：
- insufficient：resonance.status == "insufficient"，分支 = reasons[0]（六出口中两处
  共用"横截面有效样本不足"文案，按文案计数，如实标注 ×2）；
- voted：direction ∈ {buy, sell}；driver = 新入榜(historyState=="new_entry") /
  Jump 事件(tierReasons 含"Jump") / 排名序列(direction_score)——反向 jump 覆写帧
  （line 708）无独立输出标记，落入"排名序列"桶（近似，如实标注）；
- hold_ok：status ok 且 direction=="hold"（有数据但无方向，非 insufficient）。

regime 归组复用 regime_state_of（同帧全股相同）；前向收益口径同 tier_monotonicity
（percentileDelta，分位十桶基线）。

用法：
  python -m backend.operations.diagnose_resonance_vote_structure [--window all] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.research.gate_flip_stats import extract_gate_states  # noqa: F401（regime_state_of 依赖链文档锚）
from backend.analysis.ranktrend.research.regime_saex import MISSING_STATE, regime_state_of
from backend.analysis.ranktrend.research.tier_monotonicity import _build_lookup, _percentile
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR
from backend.operations.optimize_resonance_parameters import load_frames
from backend.operations.evaluate_ts_factor_weights import WINDOWS

JUMP_MARK = "Jump"


def classify_resonance(obs: dict[str, Any]) -> tuple[str, str]:
    """返回 (bucket, driver)。bucket：insufficient:<reason> / voted / hold_ok。"""
    if str(obs.get("status") or "") == "insufficient":
        reasons = obs.get("reasons") or [""]
        return f"insufficient:{reasons[0]}", ""
    direction = str(obs.get("direction") or "")
    if direction in ("buy", "sell"):
        if str(obs.get("historyState") or "") == "new_entry":
            return "voted", "新入榜(entry_strength)"
        tier_reasons = " ".join(str(r) for r in (obs.get("tierReasons") or []))
        if JUMP_MARK in tier_reasons:
            return "voted", "Jump 事件"
        return "voted", "排名序列(direction_score)"
    return "hold_ok", ""


def collect_samples(signals: list[dict[str, Any]], frames: list[dict[str, Any]], horizon: int = 1) -> dict[str, Any]:
    """每信号采集共振分类 + regime + 前向 percentileDelta；边界/缺股/缺 rank 如实剔除。"""
    index_by_snapshot, stock_by_frame_code = _build_lookup(frames)
    totals = len(frames)
    samples: list[dict[str, Any]] = []
    skipped = {"no_snapshot": 0, "boundary": 0, "missing_stock": 0, "bad_rank": 0, "no_resonance": 0}
    for signal in signals:
        obs = (signal.get("rankTrend") or {}).get("resonance") or {}
        if not obs:
            skipped["no_resonance"] += 1
            continue
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
        bucket, driver = classify_resonance(obs)
        samples.append(
            {
                "bucket": bucket,
                "driver": driver,
                "direction": str(obs.get("direction") or ""),
                "regime": regime_state_of(signal) or MISSING_STATE,
                "delta": (future_pct - current_pct) / 100.0,
                "pct": current_pct,
            }
        )
    return {"samples": samples, "skipped": skipped}


def _decile_baseline(samples: list[dict[str, Any]]) -> dict[int, tuple[float, float]]:
    """全体样本分位十桶基线：(桶内 acc, 桶内 mean delta)。"""
    buckets: dict[int, list[float]] = {}
    for s in samples:
        buckets.setdefault(min(9, int(s["pct"] // 10)), []).append(s["delta"])
    return {
        bucket: (
            sum(1 for d in deltas if d > 0) / len(deltas),
            sum(deltas) / len(deltas),
        )
        for bucket, deltas in buckets.items()
    }


def _excess_of(samples: list[dict[str, Any]], baseline: dict[int, tuple[float, float]]) -> dict[str, Any] | None:
    if not samples:
        return None
    deltas = [s["delta"] for s in samples]
    mean_delta = sum(deltas) / len(deltas)
    acc = sum(1 for d in deltas if d > 0) / len(deltas)
    baseline_accs = [baseline[min(9, int(s["pct"] // 10))][0] for s in samples]
    baseline_accs = [v for v in baseline_accs if v is not None]
    baseline_means = [baseline[min(9, int(s["pct"] // 10))][1] for s in samples]
    baseline_means = [v for v in baseline_means if v is not None]
    return {
        "n": len(samples),
        "meanDelta": round(mean_delta, 6),
        "excessMeanDelta": round(mean_delta - (sum(baseline_means) / len(baseline_means)), 6) if baseline_means else None,
        "directionAccuracy": round(acc, 4),
        "excessDirectionAccuracy": round(acc - (sum(baseline_accs) / len(baseline_accs)), 4) if baseline_accs else None,
    }


def diagnose_window(window: str) -> dict[str, Any]:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    frames = load_frames(start, end)
    assert_not_frozen(frames, "scan")
    t0 = time.time()
    engine = RankTrendPythonEngine(config=RankTrendConfig())
    signals = engine.replay(frames, meta={})
    print(f"[res-vote] {window} frames={len(frames)} signals={len(signals)} ({time.time() - t0:.0f}s)", file=sys.stderr)
    collected = collect_samples(signals, frames)
    samples = collected["samples"]
    baseline = _decile_baseline(samples)
    global_mean = sum(s["delta"] for s in samples) / len(samples)

    # 1. 六出口/弃权结构计数
    buckets: dict[str, list[dict[str, Any]]] = {}
    for s in samples:
        buckets.setdefault(s["bucket"], []).append(s)
    abstention: dict[str, Any] = {}
    for bucket, members in sorted(buckets.items()):
        abstention[bucket] = {
            "n": len(members),
            "share": round(len(members) / len(samples), 4),
            "meanDelta": round(sum(m["delta"] for m in members) / len(members), 6),
            "excessMeanDeltaVsGlobal": round(sum(m["delta"] for m in members) / len(members) - global_mean, 6),
        }

    # 2. 投票驱动分解（buy/sell 分方向）
    drivers: dict[str, dict[str, Any]] = {}
    for s in samples:
        if s["bucket"] != "voted":
            continue
        key = f"{s['direction']}|{s['driver']}"
        drivers.setdefault(key, []).append(s)
    vote_drivers = {
        key: {
            "n": len(members),
            "shareOfAll": round(len(members) / len(samples), 4),
            "hitRate": round(sum(1 for m in members if m["delta"] > 0) / len(members), 4),
            "meanDelta": round(sum(m["delta"] for m in members) / len(members), 6),
        }
        for key, members in sorted(drivers.items())
    }

    # 3. 分支反事实（H1/H2）：insufficient 各分支 excess（vs 分位基线）+ voted 参照
    counterfactual: dict[str, Any] = {}
    for bucket in sorted(buckets):
        if bucket.startswith("insufficient:"):
            counterfactual[bucket] = _excess_of(buckets[bucket], baseline)
    counterfactual["voted_buy_reference"] = _excess_of([s for s in samples if s["direction"] == "buy"], baseline)

    # 4. regime 交叉表（缺票率是 regime 相关变量）
    regime_states = sorted({s["regime"] for s in samples})
    regime_table: dict[str, Any] = {}
    for state in regime_states:
        members = [s for s in samples if s["regime"] == state]
        insufficient = sum(1 for m in members if m["bucket"].startswith("insufficient:"))
        hold_ok = sum(1 for m in members if m["bucket"] == "hold_ok")
        voted = sum(1 for m in members if m["bucket"] == "voted")
        regime_table[state] = {
            "n": len(members),
            "insufficientShare": round(insufficient / len(members), 4),
            "okHoldShare": round(hold_ok / len(members), 4),
            "votedShare": round(voted / len(members), 4),
        }

    return {
        "window": {"start": start, "end": end, "frameCount": len(frames)},
        "signalCount": len(signals),
        "validSamples": len(samples),
        "skipped": collected["skipped"],
        "globalMeanDelta": round(global_mean, 6),
        "abstention": abstention,
        "voteDrivers": vote_drivers,
        "counterfactual": counterfactual,
        "regimeTable": regime_table,
        "notes": [
            "六出口中两处共用'横截面有效样本不足'文案（新入榜支/排名序列支），按文案计数如实标注 ×2",
            "反向 jump 覆写帧（runtime.py:708）无独立输出标记，落入'排名序列'桶（近似）",
            "反事实口径：分支帧 meanDelta − 分位基线均值（方向无关）；正漂移 → H2 线索，零/负 → H1 线索，最终裁决须 D-b 剂量曲线（§5.2）",
        ],
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="D-a 共振缺票结构解剖（只读）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    windows = list(WINDOWS) if args.window == "all" else [args.window]
    report: dict[str, Any] = {"windowsConsumed": True}
    for window in windows:
        report[window] = diagnose_window(window)
    # 跨窗缺票率对照（解释 unknown 波动）
    report["crossWindow"] = {
        win: {
            bucket: stats.get("share")
            for bucket, stats in (report.get(win, {}).get("abstention") or {}).items()
        }
        for win in windows
    }
    out_path = Path(args.out) if args.out else REPORT_DIR / "resonance-vote-structure.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["crossWindow"], ensure_ascii=False, indent=2))
    print(f"[res-vote] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
