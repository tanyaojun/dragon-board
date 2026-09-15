# -*- coding: utf-8 -*-
"""P6-a ATR 观察因子区分度诊断（方案 P6，只读；four-dim-algorithm-research 口径）。

性质声明（方案 P6）：**不是调参案**——ATR 是"观察因子信息量从未验证"（阶段 10
crossSection 同款流程：先区分度、后谈参数）。本诊断不进投票、不触发 Track 1 交易复核、
不写回任何默认值；判定按观察因子标准。

三步（方案 P6-a 原文口径）：
1. **数据可用性先行**（skill 教训 6）：atrAggregateByDay=False 逐帧口径下 high/low
   覆盖率重测（曾因 high/low 缺失 28% 使 ATR 全 unknown）+ ATR unknown 率统计
   （DIMENSION_PATHS["atr"] = observation.atrMeanReversion.signalTier 路径）；
   **unknown > 50% → 判"数据不足"收口，P6-b 不做**；
2. 区分度验证：tier_forward_returns(dimension="atr") 输出档位分布 + h1 exAcc
   （S/A 合并 saEx 口径）+ A 档样本量——阶段 10 口径：**exAcc 正 + 样本 ≥ 门槛**；
3. 历史监控对照值（§23.8 C 档 62.5%、§11.5 A 档样本 500 等）均为 **fund10 落默认
   （阶段 25）之前口径**，本诊断同批重测，不直接引用旧数。

判定规则（先列后跑，防拍脑袋）：
- unknownRate > 0.5                      → INSUFFICIENT_DATA（数据不足收口，P6-b 不做）
- A 档 excessDirectionAccuracy > 0 且 A 档 count ≥ MIN_S_SAMPLES → DISCRIMINATIVE（P6-b 开发）
- 其余                                   → NO_DISCRIMINATION（无区分度收口）
分级注记（不影响上判定，只标注证据等级）：
- saEx ≥ MIN_SA_EXCESS_ACCURACY(0.05) = 达验收线（tier_monotonicity 硬约束口径）；
- A 档 count > 500 = 达 §11.5 复核目标线（fund10 前口径，500 为"复核触发"而非硬门槛）。

fail-visible：覆盖率 / unknown 率 / insufficient 原因分布 / 样本量如实输出；
边界丢样本（帧边界/缺股/坏 rank）从 raw 计数与 forward 计数的差可见，不伪造 0。

用法：
  python -m backend.operations.diagnose_atr_discrimination [--window all] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.atr.atr_mean_reversion import bar_of
from backend.analysis.ranktrend.research.tier_monotonicity import (
    MAX_UNKNOWN_RATE,
    MIN_S_SAMPLES,
    MIN_SA_EXCESS_ACCURACY,
)
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR
from backend.operations.optimize_resonance_parameters import _tier_summary, load_frames, sa_excess_of

# 判定常量（方案 P6-a + 阶段 10 口径；留痕备查）
UNKNOWN_RATE_CLOSE = 0.5  # unknown >50% → 数据不足收口（方案 P6-a 第 1 步硬判据）
A_TIER_MIN_SAMPLES = MIN_S_SAMPLES  # 样本门槛 = tier_monotonicity 硬约束 30（阶段 10 同源基建）
A_REVIEW_TARGET = 500  # §11.5 复核目标线（fund10 前口径，仅分级注记）

TIER_KEYS = ("S", "A", "B", "C", "D", "E", "unknown")
TIER_VALUES_SAFE = {"S", "A", "B", "C", "D", "E", "unknown"}  # 与 tier_signal_of 合法档位集同源
INSUFFICIENT_PREFIX = "ATR 样本不足"


def atr_obs_of(signal: dict[str, Any]) -> dict[str, Any]:
    """signal → observation.atrMeanReversion（DIMENSION_PATHS["atr"] 同路径）；缺字段返回 {}。"""
    return (((signal.get("rankTrend") or {}).get("observation") or {}).get("atrMeanReversion") or {})


def high_low_coverage(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """逐帧口径 high/low 覆盖率（bar_of 与 ATR 实际输入同源，含 highPrice/dayHigh 回退链）。

    bar_of：close 必填（close→closePrice→lastPrice→lastTradePrice→price），
    high/low 可选（high→highPrice→dayHigh / low→lowPrice→dayLow，缺失=None → TR 降级
    收盘 Δclose 准 ATR，不丢弃该帧）。close 缺失 → 该帧不累积（fail-visible）。
    """
    rows = 0
    close_ok = 0
    high_ok = 0
    low_ok = 0
    both_ok = 0
    for frame in frames:
        for row in frame.get("stocks") or []:
            rows += 1
            bar = bar_of(row)
            if bar is None:
                continue  # close 缺失：不累积（计数差可见）
            close_ok += 1
            high, low, _ = bar
            if high is not None:
                high_ok += 1
            if low is not None:
                low_ok += 1
            if high is not None and low is not None:
                both_ok += 1
    return {
        "stockRows": rows,
        "closeAvailable": close_ok,
        "highAvailable": high_ok,
        "lowAvailable": low_ok,
        "highAndLowAvailable": both_ok,
        "highCoverageRate": round(high_ok / rows, 4) if rows else None,
        "lowCoverageRate": round(low_ok / rows, 4) if rows else None,
        "closeCoverageRate": round(close_ok / rows, 4) if rows else None,
        "bothCoverageRate": round(both_ok / rows, 4) if rows else None,
        "note": "bar_of 口径（high→highPrice→dayHigh / low→lowPrice→dayLow）；high/low 缺失时 TR 降级收盘 Δclose，不丢弃帧",
    }


def raw_tier_counts(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """全信号直读 tier 计数（不经前向收益边界过滤）+ insufficient 原因分布。"""
    tiers = {key: 0 for key in TIER_KEYS}
    insufficient_reasons: dict[str, int] = {}
    missing_bars = 0
    gap_resets = 0
    missing_obs = 0
    for signal in signals:
        obs = atr_obs_of(signal)
        if not obs:
            missing_obs += 1
            tiers["unknown"] += 1
            continue
        tier = str(obs.get("signalTier") or "unknown")
        tiers[tier if tier in TIER_VALUES_SAFE else "unknown"] += 1
        if str(obs.get("status") or "") == "insufficient":
            reason = str((obs.get("reasons") or [""])[0])
            if reason.startswith(INSUFFICIENT_PREFIX):
                reason = INSUFFICIENT_PREFIX  # 含动态帧数（N/M 帧），按前缀归桶
            insufficient_reasons[reason] = insufficient_reasons.get(reason, 0) + 1
        missing_bars += int(obs.get("missingBars") or 0)
        gap_resets += int(obs.get("gapResets") or 0)
    total = len(signals)
    return {
        "tierCounts": tiers,
        "unknownRate": round(tiers["unknown"] / total, 4) if total else None,
        "insufficientReasons": insufficient_reasons,
        "missingBarsTotal": missing_bars,
        "gapResetsTotal": gap_resets,
        "missingObsCount": missing_obs,
        "signalCount": total,
    }


def verdict_of(stats: dict[str, Any], unknown_rate: float | None) -> dict[str, Any]:
    """判定（先列后跑）：unknown>50% 收口 / A 档 exAcc 正且样本≥门槛 → 有区分度。"""
    a_tier = (stats.get("tiers") or {}).get("A") or {}
    a_ex = a_tier.get("excessDirectionAccuracy")
    a_count = int(a_tier.get("count") or 0)
    sa_ex = sa_excess_of(stats)
    if unknown_rate is None or unknown_rate > UNKNOWN_RATE_CLOSE:
        verdict = "INSUFFICIENT_DATA"
        reason = f"ATR unknown 率 {unknown_rate} > {UNKNOWN_RATE_CLOSE}（方案 P6-a 第 1 步硬判据）→ 数据不足收口，P6-b 不做"
    elif a_ex is not None and a_ex > 0 and a_count >= A_TIER_MIN_SAMPLES:
        verdict = "DISCRIMINATIVE"
        reason = f"A 档 exAcc={a_ex} > 0 且样本 {a_count} ≥ {A_TIER_MIN_SAMPLES}（阶段 10 口径）→ P6-b 开发"
    else:
        verdict = "NO_DISCRIMINATION"
        reason = (
            f"A 档 exAcc={a_ex}（需 >0）或样本 {a_count}（需 ≥{A_TIER_MIN_SAMPLES}）未达阶段 10 口径 → 无区分度收口"
        )
    return {
        "verdict": verdict,
        "reason": reason,
        "readings": {
            "unknownRate": unknown_rate,
            "aTierExcessDirectionAccuracy": a_ex,
            "aTierCount": a_count,
            "saExcessAccuracy": round(sa_ex, 4) if sa_ex is not None else None,
        },
        "gradeNotes": {
            "saExPassesAcceptanceLine": bool(sa_ex is not None and sa_ex >= MIN_SA_EXCESS_ACCURACY),
            "acceptanceLine": MIN_SA_EXCESS_ACCURACY,
            "aTierReachesReviewTarget": bool(a_count > A_REVIEW_TARGET),
            "reviewTarget": A_REVIEW_TARGET,
            "reviewTargetNote": f"§11.5 复核目标线 {A_REVIEW_TARGET} 为 fund10 前口径，仅分级注记",
            "hardUnknownLine": MAX_UNKNOWN_RATE,
            "hardUnknownNote": "tier_monotonicity 硬约束 unknown<5% 为 passHard 口径；本诊断收口线 0.5 为方案 P6-a 专设",
        },
    }


def diagnose_window(window: str) -> dict[str, Any]:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    frames = load_frames(start, end)
    assert_not_frozen(frames, "scan")
    t0 = time.time()
    engine = RankTrendPythonEngine(config=RankTrendConfig())
    signals = engine.replay(frames, meta={})
    print(f"[atr-diag] {window} frames={len(frames)} signals={len(signals)} ({time.time() - t0:.0f}s)", file=sys.stderr)

    coverage = high_low_coverage(frames)
    raw = raw_tier_counts(signals)
    stats = tier_forward_returns(signals, frames, horizon=1, dimension="atr")
    summary = _tier_summary(stats)
    verdict = verdict_of(stats, raw.get("unknownRate"))
    return {
        "window": {"start": start, "end": end, "frameCount": len(frames)},
        "dataAvailability": coverage,
        "atrRawCounts": raw,
        "h1ForwardStats": {
            "summary": summary,
            "tiers": stats.get("tiers") or {},
            "monotonicity": stats.get("monotonicity") or {},
            "unknownRate": stats.get("unknownRate"),
            "frameCount": stats.get("frameCount"),
            "note": "forward 口径样本数低于 raw 计数的差 = 帧边界/缺股/坏 rank 剔除（fail-visible，不伪造）",
        },
        "verdict": verdict,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="P6-a ATR 区分度诊断（只读，unknown>50% 收口）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    windows = list(WINDOWS) if args.window == "all" else [args.window]
    report: dict[str, Any] = {
        "diagnostic": "P6-a ATR 区分度验证（只读，观察因子标准，不进投票不触发 Track 1）",
        "windowsConsumed": True,
        "criteria": {
            "unknownCloseLine": UNKNOWN_RATE_CLOSE,
            "aTierMinSamples": A_TIER_MIN_SAMPLES,
            "acceptanceLine": MIN_SA_EXCESS_ACCURACY,
            "reviewTargetNote": f"§11.5 复核线 {A_REVIEW_TARGET}（fund10 前口径，分级注记）",
        },
    }
    for window in windows:
        report[window] = diagnose_window(window)

    report["crossWindowVerdict"] = {
        win: {
            "verdict": (report.get(win, {}).get("verdict") or {}).get("verdict"),
            "unknownRate": (report.get(win, {}).get("verdict") or {}).get("readings", {}).get("unknownRate"),
            "aTierExAcc": (report.get(win, {}).get("verdict") or {}).get("readings", {}).get("aTierExcessDirectionAccuracy"),
            "aTierCount": (report.get(win, {}).get("verdict") or {}).get("readings", {}).get("aTierCount"),
        }
        for win in windows
    }
    report["overall"] = (
        "DISCRIMINATIVE"
        if any(v.get("verdict") == "DISCRIMINATIVE" for v in report["crossWindowVerdict"].values())
        else ("INSUFFICIENT_DATA" if all(v.get("verdict") == "INSUFFICIENT_DATA" for v in report["crossWindowVerdict"].values()) else "NO_DISCRIMINATION")
    )

    out_path = Path(args.out) if args.out else REPORT_DIR / "atr-discrimination.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"overall": report["overall"], "crossWindowVerdict": report["crossWindowVerdict"]}, ensure_ascii=False, indent=2))
    print(f"[atr-diag] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
