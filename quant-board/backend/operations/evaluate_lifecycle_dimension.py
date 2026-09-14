# -*- coding: utf-8 -*-
"""周期（lifecycle）维参数贡献率实证评估 harness（backend/operations，长测阶段 23 预研）。

用户命题（2026-09-13）：五维信号中趋势五权重已实证重定义落默认（阶段 22）、共振/量价
已扫且存量候选 OBSERVE；本任务对周期维做同类贡献率实证评估。方法论复用阶段 22
（层 1 事件级区分度 + 层 2 单变量 trial 三窗边际贡献 → 三档提案 → Track 2 判定卡
→ 用户决策后才落默认）。

评估口径（用户确认，brainstorming 2026-09-13）：
- B 组为主（真杠杆）：lifecycle_decision 阈值族 10 参数 + decisionReversal* 3 参数
  （final buy→hold 降档信号面）+ riskPressureWeights（pressure 合成权重，进
  lifecycle high_risk_conflict / compose_strategy 退出门槛 / decision 风险惩罚）。
  阈值是规则边界非连续权重：Min 类 ×>1=收紧、×<1=放宽，Max 类相反（语义逐 trial 标注）。
  档位两轮制：第一轮粗筛 ×0.5/×1.5/×2 找敏感参数，第二轮按证据补精扫（本文件后续填充）。
- A 组冗余验证：lifecycleWeights/lifecycleMomentumWeights 只进
  observation.lifecycle.score 展示分（compose_observation_scores，engine/runtime.py），
  decisionRiskPenaltyWeights 只进 final confidence——三者对 synergy/veto 预期零效应。
  list 字段 from_patch 整体替换无归一化（compose 后 clamp 0-1），trial patch 显式构造
  和=1（用户确认口径）；zero_effect_summary 验证逐位零效应即判冗余，不做深扫。
- 范围排除：cycleRaw*/cycleNorm*/cycleConf* 50 结构参数（overfitting-audit §5.1 D 项
  裁定不扫描，本任务不得推翻）；lifecycleConfirmFrames（阶段 12 已扫，证伪）；
  decisionReversalFinalConfCap（confidence-only 不改信号方向）；decisionMinAgreement 等
  决策共识计数参数（跨维共享，不属周期维）。

窗口纪律：decision 04-15~07-31 + OOS-1 08-15~31 + OOS-2 09-01~12；FINAL(8/1-8/14)
冻结（assert_not_frozen purpose=scan）。全程不写回默认值，提案等用户决策后另走
golden 变更流程。

端到端锚：baseline trial 必须逐位复现阶段 22.8 端到端锚三窗读数（p2_aggressive
落默认后基线）：decision 0.0939 / oos1 0.0854 / oos2 0.0737。

fail-visible：saEx=None 退化、样本计数、翻转率如实输出，不伪造 0。

基线注记：本 harness baseline 即当前默认（阶段 22.8 后），trial 读数与 baseline 直接
可比；若未来默认再变更，需同步更新 BASELINE_ANCHOR 与测试锚。

用法：
  python -m backend.operations.evaluate_lifecycle_dimension [--window decision|oos1|oos2|all]
      [--group a_display|b_scan|all] [--events-only] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.operations.evaluate_ts_factor_weights import WINDOWS, contribution_summary, proposal_verdict
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate
from backend.operations.optimize_resonance_parameters import _tier_summary

# 阶段 22.8 端到端锚（p2_aggressive 落默认后 baseline 三窗 synergy saEx）
BASELINE_ANCHOR: dict[str, float] = {"decision": 0.0939, "oos1": 0.0854, "oos2": 0.0737}

# ---------------------------------------------------------------------------
# B 组：阈值字段（field, kind）。kind=min：×>1 收紧（更难满足条件）；kind=max：×>1 放宽。
# decisionReversalFinalConfCap 为 confidence-only 不入扫描（见模块 docstring 范围排除）。
# ---------------------------------------------------------------------------

THRESHOLD_FIELDS: tuple[tuple[str, str], ...] = (
    # lifecycle_decision 规则阈值族（trend/lifecycle.py lifecycle_decision）
    ("lifecycleMidLongCommitmentMin", "min"),   # 中长动量承诺门槛（mid_long_committed）
    ("lifecycleAccelCommitmentMin", "min"),     # 加速度承诺门槛（mid_long_committed）
    ("lifecycleWeakPathCommitmentMax", "max"),  # 弱承接判定上限（weak_path_commitment）
    ("lifecycleVelocityMin", "min"),            # 排名速度门槛（weak_path/low_visibility）
    ("lifecycleAccelMin", "min"),               # 排名加速度门槛（weak_path/low_visibility）
    ("lifecycleLowVisibilityPathMax", "max"),   # 低可见度承接上限（low_visibility_ignition）
    ("lifecycleLowVisibilityMomentumMin", "min"),  # 低可见度三动量门槛
    ("lifecycleHighRiskPressureMin", "min"),    # 高风险冲突 pressure 门槛（veto 路径）
    ("lifecycleHighRiskDivergenceMin", "min"),  # 高风险冲突背离门槛（veto 路径）
    ("lifecycleHighRiskOverheatMin", "min"),    # 高风险冲突过热门槛（veto 路径）
    # decisionReversal 反转降档信号面（runtime.py compose_decision final buy→hold）
    ("decisionReversalPressureMin", "min"),     # 反转降档 pressure 门槛
    ("decisionReversalOverheatMin", "min"),     # 反转降档过热门槛
    ("decisionReversalMarginMax", "max"),       # 反转降档 score margin 上限
)


def make_threshold_patch(field: str, factor: float) -> dict[str, float]:
    """阈值 trial patch：目标阈值 = 当前默认 × factor（单变量）。

    阈值是规则边界非连续权重，不存在"归一化"语义；×1 即 baseline，档位只取 >0。
    list 权重字段（lifecycleWeights 等）不走本构造器（ValueError）。
    """
    if factor <= 0:
        raise ValueError(f"factor 必须 >0，实际 {factor!r}")
    valid = {f for f, _ in THRESHOLD_FIELDS}
    if field not in valid:
        raise ValueError(f"未知阈值字段 {field!r}，可选 {sorted(valid)}")
    return {field: round(float(getattr(RankTrendConfig(), field)) * factor, 6)}


def threshold_semantics(field: str, factor: float) -> str:
    """按字段方向标注档位语义：tighten（收紧）/ loosen（放宽）/ baseline。"""
    kinds = dict(THRESHOLD_FIELDS)
    if field not in kinds:
        raise ValueError(f"未知阈值字段 {field!r}")
    if factor == 1.0:
        return "baseline"
    tighten = factor > 1.0 if kinds[field] == "min" else factor < 1.0
    return "tighten" if tighten else "loosen"


# ---------------------------------------------------------------------------
# A 组：list 权重 patch（from_patch 整体替换无归一化 → 显式和=1，用户确认口径）
# ---------------------------------------------------------------------------


def lifecycle_weights_patch(weights: list[float]) -> dict[str, list[float]]:
    """lifecycleWeights patch：长度 4、非负、和=1（显式归一化，与 baseline 同量纲）。"""
    if len(weights) != 4:
        raise ValueError(f"lifecycleWeights 需长度 4（stageFitness/pathCommitment/momentumConfirmation/riskSafety），实际 {weights!r}")
    if any(w < 0 for w in weights):
        raise ValueError(f"lifecycleWeights 不能含负值，实际 {weights!r}")
    if abs(sum(weights) - 1.0) > 1e-9:
        raise ValueError(f"lifecycleWeights 需归一化（和=1），实际和 {sum(weights)!r}")
    return {"lifecycleWeights": list(weights)}


TRIAL_GROUPS: dict[str, list[dict[str, Any]]] = {
    # A 组冗余验证（展示分 / confidence-only 面预算期零效应；零效应成立即判冗余）
    "a_display": [
        {
            "key": "a_equal_weights",
            "desc": "lifecycleWeights 等权 [0.25×4]（默认 [0.35,0.25,0.2,0.2]，展示分面）",
            "overrides": lifecycle_weights_patch([0.25, 0.25, 0.25, 0.25]),
        },
        {
            "key": "a_drop_risksafety",
            "desc": "lifecycleWeights 去 riskSafety [0.4,0.35,0.25,0]（展示分面）",
            "overrides": lifecycle_weights_patch([0.4, 0.35, 0.25, 0.0]),
        },
        {
            "key": "a_stage_lean",
            "desc": "lifecycleWeights stage 偏重 [0.5,0.2,0.15,0.15]（展示分面）",
            "overrides": lifecycle_weights_patch([0.5, 0.2, 0.15, 0.15]),
        },
        {
            "key": "a_momentum_mid_lean",
            "desc": "lifecycleMomentumWeights mid 偏重 [0.15,0.6,0.25]（默认 [0.3,0.45,0.25]，展示分面）",
            "overrides": {"lifecycleMomentumWeights": [0.15, 0.6, 0.25]},
        },
        {
            "key": "a_risk_penalty_half",
            "desc": "decisionRiskPenaltyWeights ×0.5 [5.5,4.5,2.5]（confidence-only 面预期零效应）",
            "overrides": {"decisionRiskPenaltyWeights": [5.5, 4.5, 2.5]},
        },
    ],
    # B 组第一轮粗筛：baseline + 13 阈值 × {×0.5,×1.5,×2} + riskPressureWeights 3 档
    "b_scan": [
        {"key": "baseline", "desc": "默认配置（阶段 22.8 p2_aggressive 落默认后基线）", "overrides": {}},
        *[
            {
                "key": f"thr_{field}__x{factor_tag}",
                "desc": f"{field} ×{factor}（{threshold_semantics(field, factor)}；当前默认 {getattr(RankTrendConfig(), field)}）",
                "overrides": make_threshold_patch(field, factor),
            }
            for field, _kind in THRESHOLD_FIELDS
            for factor, factor_tag in ((0.5, "05"), (1.5, "15"), (2.0, "20"))
        ],
        {
            "key": "rp_overheat_lean",
            "desc": "riskPressureWeights [0.7,0.3]（过热偏重，默认 [0.58,0.42]）",
            "overrides": {"riskPressureWeights": [0.7, 0.3]},
        },
        {
            "key": "rp_equal",
            "desc": "riskPressureWeights [0.5,0.5]（两分量等权）",
            "overrides": {"riskPressureWeights": [0.5, 0.5]},
        },
        {
            "key": "rp_divergence_lean",
            "desc": "riskPressureWeights [0.42,0.58]（背离偏重，与默认交换）",
            "overrides": {"riskPressureWeights": [0.42, 0.58]},
        },
    ],
    # 第二轮精扫（2026-09-13 第一轮证据驱动）：只扫敏感参数，全为收紧侧档位。
    # 零效应参数（HighRisk Divergence/Overheat、decisionReversal*、riskPressure）不进精扫。
    "b_refine": [
        {
            "key": "thr_lifecycleMidLongCommitmentMin__x125",
            "desc": "MidLongCommitmentMin ×1.25（收紧；第一轮唯一三窗全正方向，剂量曲线）",
            "overrides": make_threshold_patch("lifecycleMidLongCommitmentMin", 1.25),
            "semantics": "tighten",
        },
        {
            "key": "thr_lifecycleMidLongCommitmentMin__x175",
            "desc": "MidLongCommitmentMin ×1.75（收紧；剂量曲线）",
            "overrides": make_threshold_patch("lifecycleMidLongCommitmentMin", 1.75),
            "semantics": "tighten",
        },
        {
            "key": "thr_lifecycleMidLongCommitmentMin__x30",
            "desc": "MidLongCommitmentMin ×3.0（收紧；上探找平台）",
            "overrides": make_threshold_patch("lifecycleMidLongCommitmentMin", 3.0),
            "semantics": "tighten",
        },
        {
            "key": "thr_lifecycleVelocityMin__x125",
            "desc": "VelocityMin ×1.25（收紧；oos2 全档正，补剂量）",
            "overrides": make_threshold_patch("lifecycleVelocityMin", 1.25),
            "semantics": "tighten",
        },
        {
            "key": "thr_lifecycleVelocityMin__x175",
            "desc": "VelocityMin ×1.75（收紧；补剂量）",
            "overrides": make_threshold_patch("lifecycleVelocityMin", 1.75),
            "semantics": "tighten",
        },
        {
            "key": "thr_lifecycleWeakPathCommitmentMax__x075",
            "desc": "WeakPathCommitmentMax ×0.75（收紧；第一轮放宽侧 oos1 受损，补收紧侧单调性）",
            "overrides": make_threshold_patch("lifecycleWeakPathCommitmentMax", 0.75),
            "semantics": "tighten",
        },
    ],
    # 组合提案组（判定卡对象）：单变量第一轮 decision rel 全部 <±2.3%（远低于 C1 +3%），
    # 组合收紧是唯一可能达线路径；c1 双参数保守、c2 三参数扩展。判定卡见 proposal_verdict。
    "proposal": [
        {
            "key": "c1_commit_tight",
            "desc": "承诺收紧：MidLongCommitmentMin ×1.5 + VelocityMin ×1.5（假突破/低可见度识别门槛双侧收紧）",
            "overrides": {
                "lifecycleMidLongCommitmentMin": round(15.0 * 1.5, 6),
                "lifecycleVelocityMin": round(18.0 * 1.5, 6),
            },
        },
        {
            "key": "c2_commit_tight_ext",
            "desc": "承诺收紧扩展：MidLongCommitmentMin ×2 + VelocityMin ×1.5 + AccelMin ×1.5",
            "overrides": {
                "lifecycleMidLongCommitmentMin": round(15.0 * 2.0, 6),
                "lifecycleVelocityMin": round(18.0 * 1.5, 6),
                "lifecycleAccelMin": round(12.0 * 1.5, 6),
            },
        },
    ],
}


# ---------------------------------------------------------------------------
# 层 1：周期维事件级区分度（observation.lifecycle 路径，tier_monotonicity DIMENSION_PATHS 同源）
# ---------------------------------------------------------------------------


def _lifecycle_obs(signal: dict[str, Any]) -> dict[str, Any]:
    return ((signal.get("rankTrend") or {}).get("observation") or {}).get("lifecycle") or {}


LC_EVENT_SUBSETS: dict[str, tuple[str, Any]] = {
    "lc_veto": ("lifecycle veto 帧", lambda s: bool(_lifecycle_obs(s).get("veto"))),
    "lc_tier_A": ("周期档位 A 帧（优选路径）", lambda s: _lifecycle_obs(s).get("signalTier") == "A"),
    "lc_tier_B": ("周期档位 B 帧（低可见度/假突破谨慎）", lambda s: _lifecycle_obs(s).get("signalTier") == "B"),
    "lc_tier_D": ("周期档位 D 帧（冷却/拥挤回避）", lambda s: _lifecycle_obs(s).get("signalTier") == "D"),
    "lc_tier_E": ("周期档位 E 帧（一票否决）", lambda s: _lifecycle_obs(s).get("signalTier") == "E"),
    "lc_stage_expansion": ("扩散阶段帧", lambda s: _lifecycle_obs(s).get("stage") == "expansion"),
    "lc_stage_ignition": ("点火阶段帧", lambda s: _lifecycle_obs(s).get("stage") == "ignition"),
    "lc_stage_crowded": ("拥挤阶段帧", lambda s: _lifecycle_obs(s).get("stage") == "crowded"),
    "lc_stage_cooling": ("冷却阶段帧", lambda s: _lifecycle_obs(s).get("stage") == "cooling"),
    "lc_stage_reversal": ("反转阶段帧", lambda s: _lifecycle_obs(s).get("stage") == "reversal"),
}


def lc_event_discrimination(signals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> dict[str, Any]:
    """层 1 口径：全量 + 周期维事件/状态子集 h1 synergy 统计 + 原始命中计数。

    每个子集输出 _tier_summary 字段（saEx/spearman/passHard/unknownRate/distribution）
    + sampleCount + rawHits + desc；分位桶基线在子集内重算（阶段 14/17/22 同口径）；
    saEx=None（统计退化）与 unknown 率如实透传，不伪造。
    """
    from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns

    def _stats(filtered: Any = None) -> dict[str, Any]:
        stats = tier_forward_returns(signals, frames, horizon=1, dimension="synergy", signal_filter=filtered)
        summary = _tier_summary(stats)
        summary["sampleCount"] = sum(
            (stats.get("tiers") or {}).get(t, {}).get("count") or 0
            for t in ("S", "A", "B", "C", "D", "E", "unknown")
        )
        return summary

    out: dict[str, Any] = {"all": _stats()}
    for key, (desc, pred) in LC_EVENT_SUBSETS.items():
        summary = _stats(pred)
        summary["desc"] = desc
        summary["rawHits"] = sum(1 for s in signals if pred(s))
        out[key] = summary
    out["totalSignals"] = len(signals)
    return out


# ---------------------------------------------------------------------------
# A 组零效应判定（冗余验证合同）
# ---------------------------------------------------------------------------


def _num_eq(a: float | None, b: float | None, tol: float = 1e-9) -> bool | None:
    """数值相等判定：两侧都 None → None（数据缺失，不计入确认也不计入推翻）。"""
    if a is None and b is None:
        return None
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def zero_effect_summary(report: dict[str, Any], key: str) -> dict[str, Any]:
    """A 组冗余判定：trial vs baseline 逐窗比对 saEx/passHard/翻转率/信号量。

    verdict：
    - zero_effect_confirmed：所有有读数窗口逐位一致（展示分权重确为 signal-neutral）；
    - signal_active：任一窗口出现差异（冗余假设被推翻，需升级评估）；
    - insufficient_data：无任何窗口 trial 读数。
    """
    from backend.operations.evaluate_ts_factor_weights import _trial_result

    windows: dict[str, Any] = {}
    confirmed = True
    seen = False
    for win in WINDOWS:
        base, trial = _trial_result(report, win, "baseline"), _trial_result(report, win, key)
        if not trial:
            continue
        seen = True
        base_sa = (base or {}).get("synergy", {}).get("saEx")
        trial_sa = trial.get("synergy", {}).get("saEx")
        base_flip = (base or {}).get("flipRates") or {}
        trial_flip = trial.get("flipRates") or {}
        base_count = (base or {}).get("signalCount")
        trial_count = trial.get("signalCount")
        sa_eq = _num_eq(base_sa, trial_sa)
        pass_same = _num_eq(
            1.0 if (base or {}).get("synergy", {}).get("passHard") else 0.0,
            1.0 if trial.get("synergy", {}).get("passHard") else 0.0,
        )
        count_eq = _num_eq(
            None if base_count is None else float(base_count),
            None if trial_count is None else float(trial_count),
        )
        veto_delta = None if (trial_flip.get("veto") is None or base_flip.get("veto") is None) else round(trial_flip["veto"] - base_flip["veto"], 8)
        bd_delta = None if (trial_flip.get("bd_downgrade") is None or base_flip.get("bd_downgrade") is None) else round(trial_flip["bd_downgrade"] - base_flip["bd_downgrade"], 8)
        windows[win] = {
            "saEx": trial_sa,
            "saExDelta": None if sa_eq is None else round((trial_sa or 0) - (base_sa or 0), 8),
            "saExSame": sa_eq,
            "passHardSame": pass_same,
            "flipVetoDelta": veto_delta,
            "flipBdDelta": bd_delta,
            "signalCountSame": count_eq,
        }
        checks = [sa_eq, pass_same, count_eq]
        checks += [_num_eq(base_flip.get(k), trial_flip.get(k), 1e-9) is not False for k in ("veto", "bd_downgrade")]
        if any(c is False for c in checks):
            confirmed = False
    if not seen:
        verdict = "insufficient_data"
    elif confirmed:
        verdict = "zero_effect_confirmed"
    else:
        verdict = "signal_active"
    return {"verdict": verdict, "windows": windows}


# ---------------------------------------------------------------------------
# 窗口执行（load_frames 一次/窗复用；resume 缓存逐 trial 落盘）
# ---------------------------------------------------------------------------


def frames_entry(report: dict[str, Any], window: str) -> list[dict[str, Any]]:
    """窗口帧缓存：载入一次存 report 内存态（不落盘，落盘只存统计摘要）。"""
    cache = report.get("__frames__") or {}
    if window not in cache:
        from backend.operations.optimize_resonance_parameters import load_frames

        start, end = WINDOWS[window]
        cache[window] = load_frames(start, end)
        report["__frames__"] = cache
    return cache[window]


def run_window(window: str, report: dict[str, Any], groups: list[str], events_only: bool = False) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = frames_entry(report, window)
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[lc-dim] {window} frames={len(frames)} window={start}~{end}", file=sys.stderr)
        if not frames:
            entry["error"] = "no frames"
            _save(report)
            return
        assert_not_frozen(frames, "scan")
        entry.pop("error", None)
        _save(report)
    if not frames:
        return

    # 层 1：事件级区分度（baseline 单次 replay 复用，观察字段与 B 组 patch 无关——
    # 但 B 组阈值 patch 会改 lifecycle 档位本身，故层 1 只跑 baseline 口径）
    if "events" not in entry:
        t0 = time.time()
        signals = RankTrendPythonEngine(config=RankTrendConfig()).replay(frames, meta={})
        print(f"[lc-dim] {window} baseline replay signals={len(signals)} ({time.time() - t0:.0f}s)", file=sys.stderr)
        entry["events"] = lc_event_discrimination(signals, frames)
        entry["baselineReplaySignals"] = len(signals)
        _save(report)

    if events_only:
        return

    specs: list[dict[str, Any]] = []
    for group in groups:
        specs.extend(TRIAL_GROUPS.get(group) or [])
    seen: set[str] = set()
    trials = entry.setdefault("trials", {})
    for spec in specs:
        key = spec["key"]
        if key in seen:
            continue
        seen.add(key)
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        config = RankTrendConfig.from_patch(spec["overrides"])
        print(f"[lc-dim] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        result = evaluate_gate(config, frames)
        result["elapsedSec"] = round(time.time() - t0, 1)
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "group": _group_of(key), "result": result}
        print(
            f"[lc-dim] {window} {key} -> score={result['score']} syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) ({result['elapsedSec']}s)",
            file=sys.stderr,
        )
        _save(report)


def _group_of(key: str) -> str:
    for group, specs in TRIAL_GROUPS.items():
        if any(s["key"] == key for s in specs):
            return group
    return "unknown"


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "lifecycle-dimension.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="周期维参数贡献率实证评估（长测阶段 23 预研）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--group", default="all", choices=["a_display", "b_scan", "b_refine", "proposal", "all"])
    parser.add_argument("--events-only", action="store_true", help="只跑层 1 事件级区分度（不跑 trial）")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "lifecycle-dimension.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    groups = ["a_display", "b_scan", "b_refine", "proposal"] if args.group == "all" else [args.group]
    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report, groups, events_only=args.events_only)

    # 汇总：B 组边际贡献逐 trial + A 组零效应判定 + 提案判定卡
    summary: dict[str, Any] = {}
    all_keys: list[str] = []
    for group in ("a_display", "b_scan", "b_refine", "proposal"):
        all_keys.extend(s["key"] for s in TRIAL_GROUPS.get(group) or [])
    for key in all_keys:
        if key == "baseline":
            continue
        if any((((report.get(w) or {}).get("trials") or {}).get(key) or {}).get("result") for w in WINDOWS):
            if key.startswith("a_"):
                summary[key] = zero_effect_summary(report, key)
            else:
                summary[key] = contribution_summary(report, key)
    proposal_cards = {
        s["key"]: proposal_verdict(report, s["key"])
        for s in TRIAL_GROUPS.get("proposal") or []
        if ((((report.get("decision") or {}).get("trials") or {}).get(s["key"]) or {}).get("result"))
    }
    report["contribution"] = summary
    report["proposalVerdicts"] = proposal_cards
    _save(report)
    report.pop("__out__", None)
    print(json.dumps({"contribution": summary, "proposalVerdicts": proposal_cards}, ensure_ascii=False, indent=2))
    print(f"[lc-dim] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
