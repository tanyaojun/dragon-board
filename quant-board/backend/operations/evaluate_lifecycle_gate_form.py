# -*- coding: utf-8 -*-
"""生命周期环境门干预形态扫描 harness（阶段 24 方案 A，审计修订稿 §5）。

trial 组（§5.1）：
- 锚 a0-a3：三点等价链——a0 新基线（23.9.1 锚）/ a1 旧票权基线（22.8 锚）/
  a2 = a1+gate_off 逐位复现 23.8 no_lc_gate（等价性验证，不等先修再继续）/
  a3 新基线+gate_off（下界参照）；
- veto 剂量 b0-b3：soft 负票 strength ∈ {0.375, 0.75, 1.5, 2.25}（0.75 票权步长 ±半档；
  b3=2.25 时 A 档不可达 → 入场侧 ≡ 硬否决，只刻画出场/排序通道）；
- 降档形态 c1/c2a/c2b：关闭 / penalty 0.25 / 0.5（§2.3 裁决 cooling 降档价值方向）；
- 混合路径 d1/d2：pathMode=reversal_hard / highrisk_hard（对照 b2，分离路径贡献）；
- 同构位 e1a/e1b：vp E→D 短路 off / soft。

判定卡（§5 判定卡口径修订）：C1 决策窗 rel ≥ +3%；C2 OOS 双窗不全负；C3 decision
passHard；C4 regime 四桶 |Δ| ≤ 0.01；C5 结构守恒（重定义）——非 E/B/D 帧（e 组加
vp≠E）synergy 档位三窗逐位零翻转，同票权口径 trial 必须满足（soft 实现正确性最强
断言；票权口径不同的锚 trial 标 N/A，等价性由锚链保证）；
veto/bd 翻转率降级为处理效应观测量。

交易层复核（§5.2）：saEx 口径盲区，判定卡通过的候选须追加 Track 1 交易模拟后才进
用户决策（出场腿泄漏：synergyExitOnDanger/downgradeSteps 消费 synergy tier 分布）。

用法：
  python -m backend.operations.evaluate_lifecycle_gate_form [--window all] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.operations.evaluate_ts_factor_weights import WINDOWS, _rel_improve
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate

# 锚点体系（审计修订稿 §5：23.8 no_lc_gate 读数实测于落默认前的 1.0 票权基线，
# 等价链 a2 必须对 a1（旧票权）逐位复现，而非对新基线）
ANCHOR_NEW_BASELINE: dict[str, float] = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}  # 23.9.1
ANCHOR_OLD_BASELINE: dict[str, float] = {"decision": 0.0939, "oos1": 0.0854, "oos2": 0.0737}  # 22.8
ANCHOR_GATE_OFF_OLD: dict[str, float] = {"decision": 0.0366, "oos1": 0.0437, "oos2": 0.0373}  # 23.8 no_lc_gate 绝对值

_W1 = {"tierSynergyResonanceVote": 1.0, "tierSynergyRankVote": 1.0, "tierSynergyCrossSectionVote": 1.0}
_OFF = {"lifecycleVetoGateMode": "off", "lifecycleDowngradeGateMode": "off"}

ANCHOR_TRIALS: list[dict[str, Any]] = [
    {"key": "a0_baseline", "desc": "锚1：新基线（默认配置）", "overrides": {}, "anchor": ANCHOR_NEW_BASELINE},
    {"key": "a1_old_baseline", "desc": "锚2：旧票权基线（res/rank/cs=1.0，22.8 锚）", "overrides": dict(_W1), "anchor": ANCHOR_OLD_BASELINE},
    {"key": "a2_gate_off_old", "desc": "锚3：锚2+gate_off（须逐位复现 23.8 no_lc_gate 等价链）", "overrides": {**_W1, **_OFF}, "anchor": ANCHOR_GATE_OFF_OLD},
    {"key": "a3_gate_off_new", "desc": "新基线+gate_off（下界参照，无锚）", "overrides": dict(_OFF), "anchor": None},
]

DOSE_TRIALS: list[dict[str, Any]] = [
    {
        "key": f"b{i}_soft_veto_{tag}",
        "desc": f"veto 负票 strength={strength}（{note}；降档保持 hard）",
        "overrides": {"lifecycleVetoGateMode": "soft", "lifecycleVetoVoteStrength": strength},
    }
    for i, (strength, tag, note) in enumerate(
        [
            (0.375, "0375", "A 档可达 v≥2.375/63%max，真软化观测点"),
            (0.75, "075", "A 档可达 v≥2.75/73%max，真软化观测点"),
            (1.5, "15", "A 档可达 v≥3.5/93%max，近似硬否决"),
            (2.25, "225", "A 档不可达（≥4.25>3.75max），入场侧≡硬否决，只测出场/排序通道"),
        ],
        start=0,
    )
]

DOWNGRADE_TRIALS: list[dict[str, Any]] = [
    {"key": "c1_downgrade_off", "desc": "降档关闭（veto 保持 hard；§2.3 cooling 降档价值裁决点）", "overrides": {"lifecycleDowngradeGateMode": "off"}},
    {"key": "c2a_penalty_025", "desc": "降档改连续惩罚 penalty=0.25（veto 保持 hard）", "overrides": {"lifecycleDowngradeGateMode": "soft", "lifecycleDowngradePenalty": 0.25}},
    {"key": "c2b_penalty_05", "desc": "降档改连续惩罚 penalty=0.5（veto 保持 hard）", "overrides": {"lifecycleDowngradeGateMode": "soft", "lifecycleDowngradePenalty": 0.5}},
]

PATH_TRIALS: list[dict[str, Any]] = [
    {"key": "d1_reversal_hard", "desc": "pathMode=reversal_hard（reversal 硬否决保留 + HighRisk 转负票 1.5；对照 b2 分离路径贡献）", "overrides": {"lifecycleVetoGateMode": "soft", "lifecycleVetoPathMode": "reversal_hard", "lifecycleVetoVoteStrength": 1.5}},
    {"key": "d2_highrisk_hard", "desc": "pathMode=highrisk_hard（HighRisk 硬否决保留 + reversal 转负票 1.5；对照 b2）", "overrides": {"lifecycleVetoGateMode": "soft", "lifecycleVetoPathMode": "highrisk_hard", "lifecycleVetoVoteStrength": 1.5}},
]

VP_TRIALS: list[dict[str, Any]] = [
    {"key": "e1a_vp_off", "desc": "vp E→D 短路移除（E 静默不计票；交叉参照 23.8 no_vp）", "overrides": {"volumePriceGateMode": "off"}},
    {"key": "e1b_vp_soft", "desc": "vp E→D 短路改强制负票（E 强度 × vp 权重）", "overrides": {"volumePriceGateMode": "soft"}},
]

ALL_TRIALS: list[dict[str, Any]] = [*ANCHOR_TRIALS, *DOSE_TRIALS, *DOWNGRADE_TRIALS, *PATH_TRIALS, *VP_TRIALS]
CONSERVATION_TRIALS = {s["key"] for s in (*DOSE_TRIALS, *DOWNGRADE_TRIALS, *PATH_TRIALS)}
VP_CONSERVATION_TRIALS = {s["key"] for s in VP_TRIALS}

LC_GATE_TIERS = {"B", "D", "E"}

# 票权口径键：trial 覆盖任一键即与 a0 基线票权口径不同（C5 守恒不适用，见 trial_summary）
_VOTE_WEIGHT_KEYS = (
    "tierSynergyResonanceVote",
    "tierSynergyRankVote",
    "tierSynergyCrossSectionVote",
    "tierSynergyVolumePriceVote",
)


def conservation_scope(overrides: dict[str, Any]) -> tuple[bool, bool]:
    """按 trial patch 自动判定 C5 保护区（组合 trial 覆盖两个门时同时检查）。

    patch 触及 veto/降档门 → 检查 lc 保护区（lc∉{B,D,E}）；触及 vp 门 → 检查
    vp≠E 豁免（e 组语义）。
    """
    include_lc = any(k in overrides for k in ("lifecycleVetoGateMode", "lifecycleDowngradeGateMode"))
    include_vp = "volumePriceGateMode" in overrides
    return include_lc, include_vp


def anchor_check(window: str, sa_ex: float | None, anchor: dict[str, float] | None) -> dict[str, Any]:
    if anchor is None:
        return {"checked": False}
    expected = anchor[window]
    ok = sa_ex is not None and round(float(sa_ex), 4) == round(float(expected), 4)
    return {"checked": True, "expected": expected, "actual": sa_ex, "match": ok}


def conservation_stats(
    base_tiers: list[str],
    trial_tiers: list[str],
    lc_tiers: list[str],
    vp_tiers: list[str],
    *,
    include_vp: bool,
) -> dict[str, Any]:
    """C5 结构守恒：非门作用帧（lc∉{B,D,E}；e 组加 vp≠E）synergy 档位零翻转。

    长度不一致（replay 信号数漂移）如实报 violated=True，不伪造。
    """
    if not base_tiers or not trial_tiers or len(base_tiers) != len(trial_tiers) or len(base_tiers) != len(lc_tiers):
        return {"checked": len(base_tiers), "violations": None, "violated": True, "note": "序列长度不一致，无法逐位对齐"}
    violations = 0
    checked = 0
    for i, base in enumerate(base_tiers):
        if lc_tiers[i] in LC_GATE_TIERS:
            continue
        if include_vp and vp_tiers[i] == "E":
            continue
        checked += 1
        if trial_tiers[i] != base:
            violations += 1
    return {"checked": checked, "violations": violations, "violated": violations > 0}


def trial_summary(report: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """单 trial 三窗汇总：saEx/rel + C5 守恒 + 锚检查 + 判定卡要素。"""
    windows: dict[str, Any] = {}
    rels: dict[str, float | None] = {}
    pass_hard: dict[str, bool | None] = {}
    for win in WINDOWS:
        base = (((report.get(win) or {}).get("trials") or {}).get("a0_baseline") or {}).get("result")
        trial = (((report.get(win) or {}).get("trials") or {}).get(spec["key"]) or {}).get("result")
        if not trial:
            continue
        base_sa = (base or {}).get("synergy", {}).get("saEx")
        trial_sa = trial.get("synergy", {}).get("saEx")
        rels[win] = _rel_improve(trial_sa, base_sa)
        pass_hard[win] = trial.get("synergy", {}).get("passHard")
        dist = trial.get("synergy", {}).get("distribution") or {}
        total = sum(v for v in dist.values() if isinstance(v, (int, float)))
        trigger_sa = round((dist.get("S", 0) + dist.get("A", 0)) / total, 4) if total else None
        overrides = spec.get("overrides") or {}
        include_lc, include_vp = conservation_scope(overrides)
        conserv = None
        if any(k in overrides for k in _VOTE_WEIGHT_KEYS):
            # 票权口径与 a0 基线不同（a1/a2 锚）：守恒会被票权差本身打穿，检查不适用——
            # 显式标 N/A，不产出伪 violations 污染报告（等价性由锚链三窗逐位复现保证）。
            conserv = {"skipped": True, "note": "票权口径与 a0 基线不同，C5 守恒不适用（等价性由锚链保证）"}
        elif include_lc or include_vp or spec["key"] in CONSERVATION_TRIALS or spec["key"] in VP_CONSERVATION_TRIALS:
            conserv = conservation_stats(
                (base or {}).get("signalTiers") or [],
                trial.get("signalTiers") or [],
                (base or {}).get("lcTiers") or [],
                (base or {}).get("vpTiers") or [],
                include_vp=include_vp or spec["key"] in VP_CONSERVATION_TRIALS,
            )
        # C4 附加卡：regime 四桶 saEx Δ（vs baseline，decision 窗判定口径同前）
        regime_delta = None
        base_regime = (base or {}).get("regimeView") or {}
        trial_regime = trial.get("regimeView") or {}
        if base_regime and trial_regime:
            regime_delta = {
                state: (
                    None
                    if (trial_regime.get(state) or {}).get("saEx") is None or (base_regime.get(state) or {}).get("saEx") is None
                    else round((trial_regime[state]["saEx"] - base_regime[state]["saEx"]), 4)
                )
                for state in ("strong", "normal", "weak", "retreat")
                if state in base_regime
            }
        windows[win] = {
            "saEx": trial_sa,
            "saExRel": rels[win],
            "passHard": pass_hard[win],
            "triggerRateSA": trigger_sa,
            "anchor": anchor_check(win, trial_sa, spec.get("anchor")),
            "conservation": conserv,
            "regimeDelta": regime_delta,
            "flipRates": trial.get("flipRates"),
        }
    if not windows:
        return {"verdict": "insufficient_data", "windows": windows}
    c1 = rels.get("decision") is not None and rels["decision"] >= 0.03
    oos_rels = [rels.get("oos1"), rels.get("oos2")]
    c2 = any(v is not None and v > 0 for v in oos_rels)
    c3 = pass_hard.get("decision") is True
    card = {"C1_decisionRelGE3pct": c1, "C2_oosAnyPositive": c2, "C3_decisionPassHard": c3}
    card_pass = all([c1, c2, c3])
    return {
        "windows": windows,
        "saExRel": rels,
        "verdictCard": card,
        "cardResult": "PASS_CANDIDATE" if card_pass else "OBSERVE",
    }


# ---------------------------------------------------------------------------
# 窗口执行（trial 级缓存 resume，模式同 evaluate_dimension_voting_power）
# ---------------------------------------------------------------------------


def _obs(signal: dict[str, Any], name: str) -> dict[str, Any]:
    return ((signal.get("rankTrend") or {}).get("observation") or {}).get(name) or {}


def _tiers_of(signals: list[dict[str, Any]], dim: str) -> list[str]:
    return [str(_obs(s, dim).get("signalTier") or "unknown") for s in signals]


def frames_entry(report: dict[str, Any], window: str) -> list[dict[str, Any]]:
    cache = report.get("__frames__") or {}
    if window not in cache:
        from backend.operations.optimize_resonance_parameters import load_frames

        start, end = WINDOWS[window]
        cache[window] = load_frames(start, end)
        report["__frames__"] = cache
    return cache[window]


def run_window(window: str, report: dict[str, Any], specs: list[dict[str, Any]]) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = frames_entry(report, window)
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[gate-form] {window} frames={len(frames)}", file=sys.stderr)
        if not frames:
            entry["error"] = "no frames"
            _save(report)
            return
        assert_not_frozen(frames, "scan")
        entry.pop("error", None)
        _save(report)
    if not frames:
        return

    trials = entry.setdefault("trials", {})
    # baseline（a0）：同一次 replay 产出 lc/vp tier 序列（C5 保护区 mask 与对照基准）
    if "a0_baseline" not in trials:
        t0 = time.time()
        engine = RankTrendPythonEngine(config=RankTrendConfig())
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(RankTrendConfig(), frames)
        result = {
            **result,
            "signalTiers": _tiers_of(signals, "synergy"),
            "lcTiers": _tiers_of(signals, "lifecycle"),
            "vpTiers": _tiers_of(signals, "volumePrice"),
        }
        trials["a0_baseline"] = {"desc": ANCHOR_TRIALS[0]["desc"], "overrides": {}, "result": result}
        print(
            f"[gate-form] {window} a0_baseline syn(saEx={result['synergy']['saEx']}) "
            f"({result.get('elapsedSec', round(time.time() - t0, 1))}s)",
            file=sys.stderr,
        )
        _save(report)

    for spec in specs:
        key = spec["key"]
        if key == "a0_baseline":
            continue
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[gate-form] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        result = {**result, "signalTiers": _tiers_of(signals, "synergy")}
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        print(
            f"[gate-form] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "lifecycle-gate-form.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="生命周期环境门干预形态扫描（阶段 24 方案 A）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument("--extra-trial", default="", help="追加 trial：JSON {key,desc,overrides}（组合提案第二轮补跑）")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "lifecycle-gate-form.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    specs = list(ALL_TRIALS)
    if args.extra_trial:
        extra = json.loads(args.extra_trial)
        for spec in extra if isinstance(extra, list) else [extra]:
            spec.setdefault("anchor", None)
            specs.append(spec)

    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report, specs)

    summary = {spec["key"]: trial_summary(report, spec) for spec in specs}
    report["summary"] = summary
    # 锚点等价链总检（a0/a1/a2 三窗全 match 才可继续正式判定；a3 无锚不检）
    anchor_ok = {}
    for spec in ANCHOR_TRIALS:
        if spec.get("anchor") is None:
            continue
        anchor_ok[spec["key"]] = all(
            ((((summary.get(spec["key"]) or {}).get("windows") or {}).get(win) or {}).get("anchor") or {}).get("match") is True
            for win in WINDOWS
        )
    report["anchorChain"] = anchor_ok
    _save(report)
    report.pop("__out__", None)
    print(json.dumps({"anchorChain": anchor_ok, "summary": {k: {**v, "windows": {w: {kk: vv for kk, vv in d.items() if kk in ("saEx", "saExRel", "anchor")} for w, d in v.get("windows", {}).items()}} for k, v in summary.items()}}, ensure_ascii=False, indent=2, default=str))
    print(f"[gate-form] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
