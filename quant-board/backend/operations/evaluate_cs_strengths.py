# -*- coding: utf-8 -*-
"""cs 档位强度表扫描 harness（方案 B，审计修订稿 §3，两轮制）。

目标参数：`tierSynergyCsStrengths`（list[4] = A/B/C/D，当前 [1.0, 0.5, −0.5, −1.0]，
23.9 参数化默认=原值）。list patch 整体替换无归一化——每个 trial 显式写全四值。
共享映射声明（§3.1）：同表供 cs/pm/dv 三维，pm/dv 票权默认 0，当前无混杂。

trial 组（§3.2 + 审计 B2/B3 落实）：
- 单轴粗扫 10 trial：csA {0.25,0.5,1.5} / csB {0.25,0.75} / csC {0,−0.25,−0.75} /
  csD {−0.5,−1.5}（默认档由 baseline 承担；csA 补 0.25 下探档 = 审计 B3）；
- **B2 线性等价对照对（2 trial）**：uni_half（整表 ×0.5）与 cs_vote_0375
  （tierSynergyCrossSectionVote 0.75×0.5=0.375）——v 上线性等价，须三窗逐位一致；
  不一致 = 强度表消费路径有非乘性逻辑，先修再继续。整表均匀缩放的信息增量 ≡ 23.9
  已扫的票权轴，本对照把该边界做成可验证事实；
- 判定卡（§4）：C1 decision rel ≥+3% / C2 OOS 双窗不全负 / C3 decision passHard；
  C4 regime 四桶 |Δ|≤0.01 附加卡；触发率漂移附加卡（S+A >3.5% 旗标，审计 B1/M2）；
- 效应量预期（审计 B4）：单档变化 ~0.19/票 → saEx ~1% 量级，OBSERVE 须注明
  "钝感 ≠ 无信息"（23.6.5 口径）；
- C5 结构守恒不适用（cs 参与率 100% 无保护区，§3.3.2）——以 baseline 锚逐位复现
  + 档位翻转率（处理效应观测量）+ passHard/样本量核查替代。

用法：
  python -m backend.operations.evaluate_cs_strengths [--window all] [--out <path>]
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

# 锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后，报告 baseline-anchor-post-fund10.json）；
# pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1，历史报告口径）
ANCHOR_BASELINE: dict[str, float] = {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}
BASE_STRENGTHS = [1.0, 0.5, -0.5, -1.0]
_OVERRIDE_MISSING = object()


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫（review C1）：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻、产出假零效应/假惰性结论——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")


TRIGGER_RATE_FLAG = 0.035  # S+A 触发率旗标（阶段 22.6 观察线）


def _patch(a: float, b: float, c: float, d: float) -> dict[str, Any]:
    return {"tierSynergyCsStrengths": [a, b, c, d]}


A, B, C, D = BASE_STRENGTHS

CS_TRIALS: list[dict[str, Any]] = [
    # 单轴粗扫（审计 B3：csA 补 0.25 下探档）
    {"key": "csA_025", "desc": "csA 强度 0.25（下探档，B3）", "overrides": _patch(0.25, B, C, D)},
    {"key": "csA_05", "desc": "csA 强度 0.5（减权）", "overrides": _patch(0.5, B, C, D)},
    {"key": "csA_15", "desc": "csA 强度 1.5（加强）", "overrides": _patch(1.5, B, C, D)},
    {"key": "csB_025", "desc": "csB 强度 0.25（减权）", "overrides": _patch(A, 0.25, C, D)},
    {"key": "csB_075", "desc": "csB 强度 0.75（加强）", "overrides": _patch(A, 0.75, C, D)},
    {"key": "csC_0", "desc": "csC 强度 0（负票中性化；回灌风险 §3.3，e1a 同构预警）", "overrides": _patch(A, B, 0.0, D)},
    {"key": "csC_025", "desc": "csC 强度 −0.25（松绑半档）", "overrides": _patch(A, B, -0.25, D)},
    {"key": "csC_075", "desc": "csC 强度 −0.75（加压半档）", "overrides": _patch(A, B, -0.75, D)},
    {"key": "csD_05", "desc": "csD 强度 −0.5（减负半档）", "overrides": _patch(A, B, C, -0.5)},
    {"key": "csD_15", "desc": "csD 强度 −1.5（加压半档）", "overrides": _patch(A, B, C, -1.5)},
    # B2 线性等价对照对：uni_half ≡ cs_vote_0375（v 上线性等价，须逐位一致）
    {"key": "uni_half", "desc": "B2 对照：整表 ×0.5（≡ 票权 0.375）", "overrides": _patch(0.5, 0.25, -0.25, -0.5)},
    {"key": "cs_vote_0375", "desc": "B2 对照：cs 票权 0.375（≡ uni_half）", "overrides": {"tierSynergyCrossSectionVote": 0.375}},
]


def anchor_check(window: str, sa_ex: float | None, anchor: dict[str, float] | None) -> dict[str, Any]:
    if anchor is None:
        return {"checked": False}
    expected = anchor[window]
    ok = sa_ex is not None and round(float(sa_ex), 4) == round(float(expected), 4)
    return {"checked": True, "expected": expected, "actual": sa_ex, "match": ok}


def _tiers_of(signals: list[dict[str, Any]]) -> list[str]:
    out = []
    for s in signals:
        tier = ((((s.get("rankTrend") or {}).get("observation") or {}).get("synergy") or {}).get("signalTier"))
        out.append(str(tier or "unknown"))
    return out


def trigger_rate_of(result: dict[str, Any]) -> float | None:
    dist = (result.get("synergy") or {}).get("distribution") or {}
    total = sum(v for v in dist.values() if isinstance(v, (int, float)))
    return round((dist.get("S", 0) + dist.get("A", 0)) / total, 4) if total else None


def regime_delta_of(trial: dict[str, Any], base: dict[str, Any]) -> dict[str, Any] | None:
    base_regime = base.get("regimeView") or {}
    trial_regime = trial.get("regimeView") or {}
    if not base_regime or not trial_regime:
        return None
    return {
        state: (
            None
            if (trial_regime.get(state) or {}).get("saEx") is None or (base_regime.get(state) or {}).get("saEx") is None
            else round(trial_regime[state]["saEx"] - base_regime[state]["saEx"], 4)
        )
        for state in ("strong", "normal", "weak", "retreat")
        if state in base_regime
    }


def trial_summary(report: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """单 trial 三窗汇总：saEx/rel + 判定卡 + 触发率漂移 + 等价对照（B2 对仅 uni_half 侧标）。"""
    windows: dict[str, Any] = {}
    rels: dict[str, float | None] = {}
    pass_hard: dict[str, bool | None] = {}
    for win in WINDOWS:
        base = (((report.get(win) or {}).get("trials") or {}).get("baseline") or {}).get("result")
        trial = (((report.get(win) or {}).get("trials") or {}).get(spec["key"]) or {}).get("result")
        if not trial:
            continue
        base_sa = (base or {}).get("synergy", {}).get("saEx")
        trial_sa = trial.get("synergy", {}).get("saEx")
        rels[win] = _rel_improve(trial_sa, base_sa)
        pass_hard[win] = trial.get("synergy", {}).get("passHard")
        trig = trigger_rate_of(trial)
        windows[win] = {
            "saEx": trial_sa,
            "saExRel": rels[win],
            "passHard": pass_hard[win],
            "triggerRateSA": trig,
            "triggerFlag": bool(trig is not None and trig > TRIGGER_RATE_FLAG),
            "anchor": anchor_check(win, trial_sa, spec.get("anchor")),
            "regimeDelta": regime_delta_of(trial, base or {}),
        }
    if not windows:
        return {"verdict": "insufficient_data", "windows": windows}
    c1 = rels.get("decision") is not None and rels["decision"] >= 0.03
    c2 = any(v is not None and v > 0 for v in (rels.get("oos1"), rels.get("oos2")))
    c3 = pass_hard.get("decision") is True
    card = {"C1_decisionRelGE3pct": c1, "C2_oosAnyPositive": c2, "C3_decisionPassHard": c3}
    return {
        "windows": windows,
        "saExRel": rels,
        "verdictCard": card,
        "cardResult": "PASS_CANDIDATE" if all([c1, c2, c3]) else "OBSERVE",
        "effectSizeNote": "单档强度变化效应量预期 ~1% saEx（审计 B4）：OBSERVE 结论须注明'钝感 ≠ 无信息'（23.6.5 口径）",
    }


def equivalence_check(report: dict[str, Any]) -> dict[str, Any]:
    """B2 对照对：uni_half 与 cs_vote_0375 三窗 signalTiers + saEx 逐位一致。"""
    windows: dict[str, Any] = {}
    all_match = True
    for win in WINDOWS:
        trials = (report.get(win) or {}).get("trials") or {}
        uni = (trials.get("uni_half") or {}).get("result")
        vote = (trials.get("cs_vote_0375") or {}).get("result")
        if not uni or not vote:
            windows[win] = {"checked": False}
            all_match = False
            continue
        tiers_equal = (uni.get("signalTiers") or []) == (vote.get("signalTiers") or [])
        sa_equal = uni.get("synergy", {}).get("saEx") == vote.get("synergy", {}).get("saEx")
        windows[win] = {"checked": True, "tiersEqual": tiers_equal, "saExEqual": sa_equal}
        all_match = all_match and tiers_equal and sa_equal
    return {"allMatch": all_match, "windows": windows, "note": "不一致 = 强度表消费存在非乘性逻辑，先修再继续（§3.1 B2）"}


def frames_entry(report: dict[str, Any], window: str) -> list[dict[str, Any]]:
    cache = report.get("__frames__") or {}
    if window not in cache:
        from backend.operations.optimize_resonance_parameters import load_frames

        start, end = WINDOWS[window]
        cache[window] = load_frames(start, end)
        report["__frames__"] = cache
    return cache[window]


def run_window(window: str, report: dict[str, Any], specs: list[dict[str, Any]] | None = None) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = frames_entry(report, window)
    assert_not_frozen(frames, "scan")  # 无条件执行（含 resume 路径，review I2）
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[cs-strength] {window} frames={len(frames)}", file=sys.stderr)
        if not frames:
            entry["error"] = "no frames"
            _save(report)
            return
        entry.pop("error", None)
        _save(report)
    if not frames:
        return

    trials = entry.setdefault("trials", {})
    if specs is None:
        specs = [{"key": "baseline", "desc": "当前默认（cs 强度表 [1.0,0.5,-0.5,-1.0]）", "overrides": {}, "anchor": ANCHOR_BASELINE}, *CS_TRIALS]
    for spec in specs:
        key = spec["key"]
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[cs-strength] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        result = {**result, "signalTiers": _tiers_of(signals)}
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        print(
            f"[cs-strength] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = True  # 审计 M3
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "cs-strengths.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}  # 帧缓存不落盘（review I1，同 evaluate_ts_factor_weights 模式）
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="cs 档位强度表扫描（方案 B，两轮制）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument("--extra-trial", default="", help="追加 trial：JSON {key,desc,overrides}（第二轮精扫补跑）")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "cs-strengths.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    specs: list[dict[str, Any]] = [
        {"key": "baseline", "desc": "当前默认（cs 强度表 [1.0,0.5,-0.5,-1.0]）", "overrides": {}, "anchor": ANCHOR_BASELINE},
        *CS_TRIALS,
    ]
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
    report["anchorChain"] = {
        "baseline": all(
            ((((summary.get("baseline") or {}).get("windows") or {}).get(win) or {}).get("anchor") or {}).get("match") is True
            for win in WINDOWS
        )
    }
    report["equivalence"] = equivalence_check(report)
    _save(report)
    report.pop("__out__", None)
    print(json.dumps({"anchorChain": report["anchorChain"], "equivalence": report["equivalence"], "summary": {k: {**v, "windows": {w: {kk: vv for kk, vv in d.items() if kk in ("saEx", "saExRel", "triggerRateSA", "triggerFlag")} for w, d in v.get("windows", {}).items()}} for k, v in summary.items()}}, ensure_ascii=False, indent=2, default=str))
    print(f"[cs-strength] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
