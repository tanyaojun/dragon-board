# -*- coding: utf-8 -*-
"""§11.5 rt=A × cs=A 双强降级复核（只读诊断，2026-09-10）。

背景（§11.4f 方向 B 验证遗留观察项，2026-08-19）：
- 决策窗 synA 信号内 rt×cs 交叉：rt=A 行 cs 反向区分——csA −0.0469 vs csC +0.0413，
  疑似"双强过热降级"（rankTrend 买 + crossSection 高位双强共振）；当时样本 n=264
  < 500 复核触发线，挂起至 9 月数据累积（§11.5）。

口径澄清（本脚本复核确认）：§11.4f 的 n=264 是 synA ∩ rt=A ∩ cs=A 的交集样本；
rt=A × cs=A 信号级共现为 838/132078=0.63%，与 §11.4f "A×A 共现仅 0.6%" 吻合——
即分层口径是"先圈 synA，再交叉 rt×cs"，不是 rt×cs 共现全集。cs tier 提取统一走
tier_monotonicity.tier_signal_of（DIMENSION_PATHS 公开路径，缺字段回退 unknown）。

主判定口径 = 原始 meanFutureReturn / directionAccuracy 的组间差（csA vs csC）：
同 synA 同 rt=A 背景下均值回归背景近似相同，组间原始差即 cs 维增量信息。
不用 signal_filter 组内 excess 口径——tier_forward_returns 的分桶基线是"过滤后同口径
重算"（tests/test_tier_monotonicity.py::test_tier_forward_returns_signal_filter_buckets
锁定行为），synA 信号全集中在最高分位段，同质小组基线塌缩为组自身 → excess 恒 0，
无信息量（该口径仅对覆盖全分位段的大组有意义，如阶段 14 regime 分桶）。

方法：
- h1、synergy 主口径；分组统计复用 tier_forward_returns(signal_filter=...) 取组内
  count/dirAcc/meanFutureReturn；synA 内 rt=A 行按 cs ∈ {A,B,C,D} 分组 + 全 synA 基线；
- regime 补充视图：双强组按 market regime state 分桶（检验"strong 期双强更差"，
  关联阶段 14 strong 双峰假说——双强=高位拥挤代理）；
- 判定输入：三窗双强有效前瞻样本数（vs §11.5 500 触发线）+ csA−csC 差值方向一致性。

只读：不写库、不改默认值；报告落 data/reports/，fail-visible 缺失如实计数。

用法：
  python -m backend.operations.diagnose_dual_strength_syna [--window all|decision|oos1|oos2] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.research.gate_flip_stats import extract_gate_states
from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns, tier_signal_of
from backend.operations.diagnose_regime_saex_decomposition import WINDOWS
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR
from backend.operations.optimize_resonance_parameters import load_frames

CS_TIERS = ("A", "B", "C", "D")


def _syn_a_group(rt_tier: str | None = None, cs_tier: str | None = None) -> Callable[[dict[str, Any]], bool]:
    """synA 交集组谓词：synergy=A，可选再交 rt tier / cs tier（None=不约束）。"""

    def pred(signal: dict[str, Any]) -> bool:
        if tier_signal_of(signal, "synergy") != "A":
            return False
        if rt_tier is not None and tier_signal_of(signal, "rankTrend") != rt_tier:
            return False
        if cs_tier is not None and tier_signal_of(signal, "crossSection") != cs_tier:
            return False
        return True

    return pred


def _dual_strong_state(state: str) -> Callable[[dict[str, Any]], bool]:
    def pred(signal: dict[str, Any]) -> bool:
        return _syn_a_group("A", "A")(signal) and str(
            extract_gate_states(signal).get("regime_state") or ""
        ) == state

    return pred


def _group_summary(
    name: str,
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    pred: Callable[[dict[str, Any]], bool],
) -> dict[str, Any]:
    """组内 synA 原始统计：filter 已把组限定为 synA 信号，tiers["A"] 即该组全部有效样本。

    只取原始口径（dirAcc/meanFutureReturn）——组内 excess 口径在同质小组会塌缩恒 0
    （分桶基线=组自身，见模块 docstring），不输出避免误读。
    """
    matched = sum(1 for signal in signals if pred(signal))
    stats = tier_forward_returns(signals, frames, horizon=1, dimension="synergy", signal_filter=pred)
    tier_a = (stats.get("tiers") or {}).get("A") or {}
    return {
        "group": name,
        "matchedSignals": matched,
        "count": tier_a.get("count"),
        "directionAccuracy": tier_a.get("directionAccuracy"),
        "meanFutureReturn": tier_a.get("meanFutureReturn"),
    }


def analyze_window(name: str, bounds: dict[str, str]) -> dict[str, Any]:
    from backend.optimization.data_windows import assert_not_frozen

    frames = load_frames(bounds["start"], bounds["end"])
    if not frames:
        return {"window": name, "error": "no frames loaded"}
    # 遗留观察项复核属报告用途（非参数决策）；守卫确认窗口不含 FINAL 冻结段之外的越界引用
    assert_not_frozen(frames, "report")

    engine = RankTrendPythonEngine(config=RankTrendConfig())
    signals = engine.replay(frames, meta={})
    if not signals:
        return {"window": name, "error": "replay produced no signals"}

    groups = {
        "synA_rtA_csA": _syn_a_group("A", "A"),
        "synA_rtA_csB": _syn_a_group("A", "B"),
        "synA_rtA_csC": _syn_a_group("A", "C"),
        "synA_rtA_csD": _syn_a_group("A", "D"),
        "synA_rtA_allCs": _syn_a_group("A"),
        "synA_all": _syn_a_group(),
    }
    summaries = {
        group_name: _group_summary(group_name, signals, frames, pred)
        for group_name, pred in groups.items()
    }

    # regime 补充视图：双强组按市场级 state 分桶（strong/normal/weak/retreat，空值如实计数）
    state_counts: dict[str, int] = defaultdict(int)
    dual_pred = _syn_a_group("A", "A")
    for signal in signals:
        if dual_pred(signal):
            state_counts[str(extract_gate_states(signal).get("regime_state") or "<missing>")] += 1
    regime_view = {
        state: _group_summary(f"dualStrong@{state}", signals, frames, _dual_strong_state(state))
        for state in sorted(state_counts)
        if state != "<missing>" and state_counts[state] > 0
    }
    regime_view_counts = dict(state_counts)

    cs_a = summaries["synA_rtA_csA"]
    cs_c = summaries["synA_rtA_csC"]
    delta = {
        "meanReturn_csA_minus_csC": (
            round(cs_a["meanFutureReturn"] - cs_c["meanFutureReturn"], 4)
            if cs_a["meanFutureReturn"] is not None and cs_c["meanFutureReturn"] is not None
            else None
        ),
        "dirAcc_csA_minus_csC": (
            round(cs_a["directionAccuracy"] - cs_c["directionAccuracy"], 4)
            if cs_a["directionAccuracy"] is not None and cs_c["directionAccuracy"] is not None
            else None
        ),
        "dualStrongCount": cs_a["count"],
        "reviewTriggerMet": bool((cs_a["count"] or 0) >= 500),
    }

    return {
        "window": name,
        "bounds": bounds,
        "frameCount": len(frames),
        "signalCount": len(signals),
        "groups": summaries,
        "dualStrongRegimeView": regime_view,
        "dualStrongRegimeCounts": regime_view_counts,
        "csA_vs_csC": delta,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="§11.5 双强降级复核（只读）")
    parser.add_argument("--window", default="all", choices=["all", "decision", "oos1", "oos2"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    names = list(WINDOWS) if args.window == "all" else [args.window]
    results = []
    for name in names:
        print(f"[dual-strength] analyzing {name} ...", file=sys.stderr)
        result = analyze_window(name, WINDOWS[name])
        results.append(result)
        if "error" in result:
            print(f"[dual-strength] {name}: {result['error']}", file=sys.stderr)
            continue
        delta = result["csA_vs_csC"]
        print(
            f"[dual-strength] {name}: dualStrong(count={delta['dualStrongCount']} trigger>=500: "
            f"{delta['reviewTriggerMet']}) meanRet(csA-csC)={delta['meanReturn_csA_minus_csC']} "
            f"dirAcc(csA-csC)={delta['dirAcc_csA_minus_csC']}",
            file=sys.stderr,
        )

    out_path = Path(args.out) if args.out else REPORT_DIR / "dual-strength-syna-review.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"generatedAt": "2026-09-10", "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[dual-strength] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
