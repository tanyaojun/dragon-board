# -*- coding: utf-8 -*-
"""共振参数搜索（backend/operations，2026-08-17）。

用户决策（2026-08-17）：优化【共振】信号参数——
  1) 主目标：改善共振维对 synergy 投票的贡献（合并档为主，监测共振单维 excess）；
  2) 搜索范围：档位阈值（tierResonance*）+ 连续分权重（resonance* 中影响档位的参数 + 展示权重）；
  3) 产出：搜索报告 + 建议参数，**不写回默认值**（golden 不变，参数采纳另行立项）。

评估：replay(config) → tier_forward_returns(dimension=resonance/synergy, horizon=1)
关键事实：`_resonance_tier` 只消费 reversal_penalty / jump_event / direction / jump_freshness /
persistence 五个输入，`resonanceWeights`（[0.35,0.25,0.2,0.2,0.2]）只影响 score/label 展示，
不影响档位 → 不影响 synergy 投票。因此"对 synergy 投票的贡献"由档位阈值 + reversal/direction/
freshness 归一化参数决定，resonanceWeights 仅验证展示分变化。

Phase 1：单维敏感性（固定其它为默认，每次只扫 1 参数，约 28 次 evaluate）
Phase 2：联合坐标下降（取 Phase 1 改善最大的参数组合，1-2 轮）
输出：data/reports/resonance-parameter-search.json

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.optimize_resonance_parameters [--resume] [--phase 1|2]
fail-visible：只读诊断 + 搜索，不写库、不改默认值；样本不足/缺维如实输出，不伪造 0。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns
from backend.optimization.validation import split_frames

REPORT_PATH = Path(r"D:\dragon-board\quant-board\data\reports\resonance-parameter-search.json")

# ── 搜索空间（每个参数：名称 → (候选值列表, 是否整体替换)）────────────────────────────
# 档位阈值（tierResonance*，直接影响 S/A/B/C/D 分布与投票）
TIER_STEPS: dict[str, list[Any]] = {
    "tierResonanceReversalPenaltyMin": [0.4, 0.5, 0.6, 0.7],
    "tierResonanceJumpFreshnessMin": [0.3, 0.4, 0.5, 0.6],
    "tierResonancePersistenceMin": [0.4, 0.5, 0.6, 0.7],
    "tierResonanceEntryStrengthMin": [0.2, 0.3, 0.4],
}
# 连续分参数（影响档位的：reversal/direction/freshness 归一化；resonanceWeights 只影响展示分，验证用）
RESONANCE_STEPS: dict[str, list[Any]] = {
    "resonanceReversalSwitchWeight": [0.4, 0.6, 0.8],
    "resonanceReversalDrawdownWeight": [0.3, 0.4, 0.5],
    "resonancePathDirectionWeight": [0.1, 0.2, 0.3],
    "resonanceDirectionThreshold": [0.05, 0.1, 0.15],
    "resonanceJumpFreshnessDecay": [2.0, 3.0, 5.0],
    "resonanceMomentumScale": [10.0, 15.0, 20.0],
    "resonanceAccelerationScale": [10.0, 15.0, 20.0],
    # 展示权重（整体替换，和须为 1；预期不影响档位/vote，仅验证）
    "resonanceWeights": [
        [0.35, 0.25, 0.2, 0.2, 0.2],
        [0.30, 0.25, 0.20, 0.15, 0.10],
        [0.25, 0.20, 0.25, 0.20, 0.10],
        [0.30, 0.20, 0.20, 0.15, 0.15],
    ],
}
ALL_STEPS = {**TIER_STEPS, **RESONANCE_STEPS}

# ── 样本外复核配置（Phase 3）：基线 + 建议参数组合 ──────────────────────────────
# 每个配置在完整 769 帧 replay 一次，然后按 chronological 切分的 train/validation 段
# 分别统计 resonance/synergy h1 tier（信号已含全历史上下文，仅收益统计分窗口）。
WALKFORWARD_CONFIGS: list[tuple[str, dict[str, Any]]] = [
    ("baseline", {}),
    ("jump_min_0.6", {"tierResonanceJumpFreshnessMin": 0.6}),
    (
        "jump_min_0.6 + reversal_penalty_min_0.4",
        {"tierResonanceJumpFreshnessMin": 0.6, "tierResonanceReversalPenaltyMin": 0.4},
    ),
    (
        "jump_min_0.6 + momentum_scale_10",
        {"tierResonanceJumpFreshnessMin": 0.6, "resonanceMomentumScale": 10.0},
    ),
]


def segment_stats(signals: list[dict[str, Any]], segment_frames: list[dict[str, Any]]) -> dict[str, Any]:
    """对给定 frames 段（train/validation）统计 resonance/synergy h1。signals 为全量 replay 输出，
    段外 snapshotId 自动跳过；段内信号用段内当前帧/未来帧计算收益。"""
    res = tier_forward_returns(signals, frames=segment_frames, horizon=1, dimension="resonance")
    syn = tier_forward_returns(signals, frames=segment_frames, horizon=1, dimension="synergy")
    return {"synergy": _tier_summary(syn), "resonance": _tier_summary(res)}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def sa_excess_of(stats: dict[str, Any]) -> float | None:
    """S/A 合并加权 excessDirectionAccuracy（验收口径，见 tier_discrimination.saExcessAccuracy）。"""
    tiers = stats.get("tiers") or {}
    s = tiers.get("S") or {}
    a = tiers.get("A") or {}
    s_count = int(s.get("count") or 0)
    a_count = int(a.get("count") or 0)
    total = s_count + a_count
    if total <= 0:
        return None
    s_ex = s.get("excessDirectionAccuracy")
    a_ex = a.get("excessDirectionAccuracy")
    if s_ex is None or a_ex is None:
        return None
    return (s_count * s_ex + a_count * a_ex) / total


def _tier_summary(stats: dict[str, Any]) -> dict[str, Any]:
    tiers = stats.get("tiers") or {}
    mono = stats.get("monotonicity") or {}
    return {
        "saEx": round(sa_excess_of(stats), 4) if sa_excess_of(stats) is not None else None,
        "spearman": mono.get("spearmanRankCorr"),
        "passHard": bool(mono.get("passHardConstraint")),
        "unknownRate": stats.get("unknownRate"),
        "distribution": {
            tier: (tiers.get(tier) or {}).get("count") for tier in ("S", "A", "B", "C", "D", "E", "unknown")
        },
    }


def evaluate(config: RankTrendConfig, frames: list[dict[str, Any]]) -> dict[str, Any]:
    """replay + resonance/synergy h1 tier 统计。返回主/次指标。

    评分（用户决策：主目标=共振对 synergy 投票的贡献）：
    - 主项 1：synergy saEx（合并档最终体现），达标线 0.05，越高越好；passHard 加分；
    - 主项 2：resonance 单维 saEx（当前为负），提升为正加分；
    - 惩罚：resonance unknown 占比高（当前 18.75%）扣分；synergy passHard=False 扣分。
    """
    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(frames, window_size=50)
    res = tier_forward_returns(signals, frames, horizon=1, dimension="resonance")
    syn = tier_forward_returns(signals, frames, horizon=1, dimension="synergy")

    syn_sa = sa_excess_of(syn)
    res_sa = sa_excess_of(res)
    res_unknown = float(res.get("unknownRate") or 0)
    syn_pass = bool((syn.get("monotonicity") or {}).get("passHardConstraint"))
    res_pass = bool((res.get("monotonicity") or {}).get("passHardConstraint"))

    score = 0.0
    if syn_sa is not None:
        score += 2.0 * _clamp(syn_sa, 0.0, 0.15)  # synergy 合并档（主，0..0.3）
    if syn_pass:
        score += 0.5  # synergy 硬约束达标
    else:
        score -= 0.8  # synergy 硬约束失败重罚（不退化）
    if res_sa is not None:
        score += 1.0 * _clamp(res_sa, 0.0, 0.05) * 10.0  # 共振单维改善（0..0.5）
    if res_pass:
        score += 0.2  # 共振单维硬约束达标小加
    score -= 0.5 * max(0.0, res_unknown - 0.10)  # unknown 占比惩罚（10% 起）
    return {
        "score": round(score, 4),
        "synergy": _tier_summary(syn),
        "resonance": _tier_summary(res),
        "signalCount": len(signals),
    }


def load_frames(
    start_date: str,
    end_date: str,
    *,
    purpose: str = "scan",
) -> list[dict[str, Any]]:
    """权威实现已收敛到 harness_common.load_frames（2026-09-21 审计，内联
    assert_not_frozen 冻结守卫）；保留同名转发兼容既有 import（历史口径 26+ 处）。
    purpose 透传：scan（默认）在帧含 FINAL 冻结窗时 raise；仅最终报告呈现传
    purpose="report"。注意：两个未迁移 harness（optimize_ranktrend_parameters /
    optimize_core_signal_parameters）的默认 --end 2026-08-14 会触发该守卫 fail-fast，
    属审计 e 类 FAIL 修复的本意——重跑请显式传 --end 2026-07-31 或分窗加载。
    """
    from backend.operations.harness_common import load_frames as _common_load_frames

    return _common_load_frames(start_date, end_date, purpose=purpose)


def _inherited(base: dict[str, Any], key: str, value: Any) -> dict[str, Any]:
    out = dict(base)
    out[key] = value
    return out


def _fmt(result: dict[str, Any]) -> str:
    s, r = result["synergy"], result["resonance"]
    return (
        f"score={result['score']} syn(saEx={s['saEx']} pass={s['passHard']} "
        f"unk={s['unknownRate']}) res(saEx={r['saEx']} pass={r['passHard']} unk={r['unknownRate']})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="共振参数搜索（只读，不写回默认值）")
    # 默认窗 = decision（04-15~07-31）。2026-09-21 审计修复：原默认 --end 08-14 覆盖
    # FINAL 冻结窗且无守卫（8 月冻结令 2026-08-19 设立前写就）；冻结守卫现内联于
    # harness_common.load_frames，含 FINAL 帧的加载会当场 raise。
    parser.add_argument("--start", default="2026-04-15")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--phase", type=int, default=1, choices=(1, 2, 3, 4), help="1=单维敏感性, 2=定向组合验证, 3=walk-forward 样本外复核, 4=regime 分桶复核")
    parser.add_argument("--resume", action="store_true", help="复用已有报告已完成候选，跳过重跑")
    parser.add_argument("--rounds", type=int, default=2, help="Phase 2 坐标下降轮数")
    args = parser.parse_args()

    report: dict[str, Any] = {}
    if args.resume and REPORT_PATH.exists():
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        print(f"[resume] loaded report with {len(report.get('sensitivity', {}))} sensitivity entries", file=sys.stderr)

    frames = load_frames(args.start, args.end)
    print(f"[search] frames={len(frames)} window={args.start}~{args.end}", file=sys.stderr)
    if not frames:
        print("[search] no frames loaded — aborting (all sources empty)", file=sys.stderr)
        return 1

    # 基线（默认 config）
    if "baseline" not in report:
        print("[search] evaluating baseline (default config) ...", file=sys.stderr)
        t0 = time.time()
        base = evaluate(RankTrendConfig(), frames)
        base["elapsedSec"] = round(time.time() - t0, 1)
        print(f"[baseline] {_fmt(base)} ({base['elapsedSec']}s)", file=sys.stderr)
        report["baseline"] = base
    else:
        print(f"[baseline] (cached) {_fmt(report['baseline'])}", file=sys.stderr)

    if args.phase == 1:
        sensitivity = report.setdefault("sensitivity", {})
        for key, candidates in ALL_STEPS.items():
            entries = sensitivity.setdefault(key, {})
            for cand in candidates:
                cand_key = json.dumps(cand, ensure_ascii=False)
                if args.resume and cand_key in entries:
                    print(f"[skip] {key}={cand} (cached)", file=sys.stderr)
                    continue
                cur = getattr(RankTrendConfig(), key)
                if cand == cur:
                    entries[cand_key] = {"note": "= default, skipped"}
                    continue
                trial = RankTrendConfig(**_inherited(dict(RankTrendConfig().__dict__), key, cand))
                print(f"[phase1] {key}={cand} ...", file=sys.stderr)
                t0 = time.time()
                result = evaluate(trial, frames)
                result["elapsedSec"] = round(time.time() - t0, 1)
                entries[cand_key] = result
                print(f"[phase1] {key}={cand} -> {_fmt(result)} ({result['elapsedSec']}s)", file=sys.stderr)
                REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
                REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    elif args.phase == 2:
        sensitivity = report.get("sensitivity") or {}
        if not sensitivity:
            print("[phase2] no sensitivity data — run --phase 1 first", file=sys.stderr)
            return 1
        # Phase 1 结论（2026-08-17 实跑）：唯一显著改善维度是 Jump 新鲜度——
        # tierResonanceJumpFreshnessMin=0.6 与 resonanceJumpFreshnessDecay=2.0 数学等价并列最佳
        # （score 0.5864→0.5940，synergy saEx 0.0651→0.0689，resonance saEx −0.0162→−0.0093）；
        # 其余参数（reversal/scale/threshold）无改善或仅微弱，resonanceWeights 不影响档位（与基线完全一致）。
        # 因此 Phase 2 不做全参数坐标下降（Phase 1 已证明大部分参数无改善），改为定向组合验证：
        # ① Jump 新鲜度双旋钮是否叠加；② 与 reversalPenaltyMin=0.4 / momentumScale=10.0 等
        # 不同机制参数是否叠加（防过拟合：组合不叠加则建议只取单旋钮）。
        base_score = report["baseline"]["score"]
        combos: list[tuple[str, dict[str, Any]]] = [
            ("jump_freshness_min_0.6", {"tierResonanceJumpFreshnessMin": 0.6}),
            ("jump_freshness_decay_2.0", {"resonanceJumpFreshnessDecay": 2.0}),
            ("jump_min_0.6 + decay_2.0", {"tierResonanceJumpFreshnessMin": 0.6, "resonanceJumpFreshnessDecay": 2.0}),
            ("jump_min_0.6 + reversal_penalty_min_0.4", {"tierResonanceJumpFreshnessMin": 0.6, "tierResonanceReversalPenaltyMin": 0.4}),
            ("jump_min_0.6 + momentum_scale_10", {"tierResonanceJumpFreshnessMin": 0.6, "resonanceMomentumScale": 10.0}),
            ("jump_min_0.6 + decay_2.0 + reversal_penalty_min_0.4", {"tierResonanceJumpFreshnessMin": 0.6, "resonanceJumpFreshnessDecay": 2.0, "tierResonanceReversalPenaltyMin": 0.4}),
        ]
        combo_results: dict[str, Any] = {}
        best_score = base_score
        best_params: dict[str, Any] = {}
        for label, params in combos:
            trial = RankTrendConfig(**{**dict(RankTrendConfig().__dict__), **params})
            print(f"[phase2] {label} -> {params} ...", file=sys.stderr)
            t0 = time.time()
            result = evaluate(trial, frames)
            result["elapsedSec"] = round(time.time() - t0, 1)
            combo_results[label] = {"params": params, "result": result}
            print(f"[phase2] {label} -> {_fmt(result)} ({result['elapsedSec']}s)", file=sys.stderr)
            if result["score"] > best_score:
                best_score = result["score"]
                best_params = params
        report["phase2"] = {
            "baseScore": base_score,
            "combos": combo_results,
            "bestParams": best_params,
            "bestScore": round(best_score, 4),
            "improvementVsBaseline": round(best_score - base_score, 4),
            "note": (
                "定向组合验证：Phase 1 证明唯一显著改善维度是 Jump 新鲜度（两旋钮数学等价），"
                "此处验证双旋钮叠加与跨机制叠加；若组合不显著优于单旋钮，建议参数只取单旋钮避免过拟合。"
            ),
        }
        print(f"[phase2] best={best_params} score={best_score} (baseline {base_score})", file=sys.stderr)

    elif args.phase == 3:
        # walk-forward 样本外复核：chronological 切分（后 30% 交易日为 validation），
        # 每配置全量 replay 一次，train/validation 段分别统计。
        split = split_frames(frames, {"validation_mode": "chronological", "validation_ratio": 0.3})
        train_frames = split["train_frames"]
        validation_frames = split["validation_frames"]
        meta = split["metadata"]
        print(
            f"[phase3] split {meta['mode']}: train={meta['train']['snapshotCount']}帧 "
            f"({meta['train']['startDate']}~{meta['train']['endDate']}) / "
            f"validation={meta['validation']['snapshotCount']}帧 "
            f"({meta['validation']['startDate']}~{meta['validation']['endDate']})",
            file=sys.stderr,
        )
        if len(validation_frames) < 10:
            print("[phase3] validation 段过短，结果波动大", file=sys.stderr)

        wf = report.setdefault("walkforward", {})
        wf["split"] = meta
        for label, params in WALKFORWARD_CONFIGS:
            trial = RankTrendConfig(**{**dict(RankTrendConfig().__dict__), **params})
            print(f"[phase3] {label} replay ...", file=sys.stderr)
            t0 = time.time()
            engine = RankTrendPythonEngine(config=trial)
            signals = engine.replay(frames, window_size=50)
            replay_sec = round(time.time() - t0, 1)
            entry: dict[str, Any] = {"params": params, "replaySec": replay_sec}
            for seg_name, seg_frames in (("train", train_frames), ("validation", validation_frames)):
                t1 = time.time()
                entry[seg_name] = segment_stats(signals, seg_frames)
                entry[seg_name + "ElapsedSec"] = round(time.time() - t1, 1)
            wf[label] = entry
            s, v = entry["train"], entry["validation"]
            print(
                f"[phase3] {label}: train syn saEx={s['synergy']['saEx']} pass={s['synergy']['passHard']} "
                f"res saEx={s['resonance']['saEx']} | validation syn saEx={v['synergy']['saEx']} "
                f"pass={v['synergy']['passHard']} res saEx={v['resonance']['saEx']}",
                file=sys.stderr,
            )
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        # 复核判定：validation 段 synergy saEx 不低于基线且 passHard=True
        base_v = (wf.get("baseline") or {}).get("validation") or {}
        base_syn = base_v.get("synergy") or {}
        verdicts: dict[str, str] = {}
        for label, entry in wf.items():
            if label == "split":
                continue
            v = entry.get("validation") or {}
            syn = v.get("synergy") or {}
            sa_ex = syn.get("saEx")
            if sa_ex is None:
                verdicts[label] = "no_validation_samples"
            elif syn.get("passHard") is not True:
                verdicts[label] = "validation_passHard_failed"
            elif base_syn.get("saEx") is not None and sa_ex >= float(base_syn.get("saEx")):
                verdicts[label] = "outperform_or_hold"
            else:
                verdicts[label] = "underperform_baseline"
        wf["verdicts"] = verdicts
        print(f"[phase3] verdicts: {verdicts}", file=sys.stderr)

    elif args.phase == 4:
        # regime 分桶复核（2026-08-17）：market_regime(frame) 五因子打分给出每帧 state
        # （score≥70 strong / ≥50 normal / ≥30 weak / 其余 retreat），signal 带 regime 字段。
        # 目标：验证"validation 段 synergy 区分度失效是否由市场状态解释"——按 regime 分桶统计
        # synergy/resonance h1（全窗口 + train/validation 段），看 strong/normal 子集是否
        # 保持区分度（saEx≥0.05 且 passHard=True）、weak/retreat 是否失效。
        split = split_frames(frames, {"validation_mode": "chronological", "validation_ratio": 0.3})
        train_frames = split["train_frames"]
        validation_frames = split["validation_frames"]
        regimes = ["strong", "normal", "weak", "retreat"]
        rf = report.setdefault("regime_filter", {})
        rf["split"] = split["metadata"]
        rf["regimes"] = regimes
        for label, params in WALKFORWARD_CONFIGS:
            trial = RankTrendConfig(**{**dict(RankTrendConfig().__dict__), **params})
            print(f"[phase4] {label} replay ...", file=sys.stderr)
            t0 = time.time()
            engine = RankTrendPythonEngine(config=trial)
            signals = engine.replay(frames, window_size=50)
            entry: dict[str, Any] = {"params": params, "replaySec": round(time.time() - t0, 1), "regimes": {}}
            for r in regimes:
                flt = (lambda s, r=r: str(s.get("regime") or "normal") == r)
                bucket: dict[str, Any] = {"signalCount": sum(1 for s in signals if flt(s))}
                for seg_name, seg_frames in (("all", frames), ("train", train_frames), ("validation", validation_frames)):
                    t1 = time.time()
                    syn = tier_forward_returns(signals, seg_frames, horizon=1, dimension="synergy", signal_filter=flt)
                    res = tier_forward_returns(signals, seg_frames, horizon=1, dimension="resonance", signal_filter=flt)
                    bucket[seg_name] = {
                        "synergy": _tier_summary(syn),
                        "resonance": _tier_summary(res),
                        "elapsedSec": round(time.time() - t1, 1),
                    }
                entry["regimes"][r] = bucket
                s_all = bucket["all"]["synergy"]
                print(
                    f"[phase4] {label} regime={r} n={bucket['signalCount']} "
                    f"all syn saEx={s_all['saEx']} pass={s_all['passHard']} unk={s_all['unknownRate']} "
                    f"| train saEx={bucket['train']['synergy']['saEx']} "
                    f"val saEx={bucket['validation']['synergy']['saEx']}",
                    file=sys.stderr,
                )
            rf[label] = entry
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[phase4] regime 分桶复核完成（报告含 regime_filter 键）", file=sys.stderr)

    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[search] report written to {REPORT_PATH}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
