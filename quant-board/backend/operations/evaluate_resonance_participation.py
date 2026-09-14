# -*- coding: utf-8 -*-
"""共振频率轴剂量扫描 + label 阈值收口 harness（方案 D D-b/D-c，提案 §5.3）。

D-b（频率轴，config 路径首批 4 trial；sampleQuality 联动开关视 D-a 证据二轮追加）：
- 横截面样本门槛：resonanceMinMarketSampleCount 20→10（回收）/→40（收紧）
- 排名序列窗口：resonanceMidWindowBars 8→6（降窗回收）/→10（加窗收紧）
- 判定卡：C1-C3 + C4 regime 四桶（缺票率 regime 相关，必看）+ 触发率漂移 +
  S/A 样本量核查（收紧档防 23.9 ×0.5 式档位塌缩）+ 参与率剂量读数；
  PASS_CANDIDATE → Track 1 交易复核双过 → **res 票权三档交互表**
  （×0.625/×0.75/1.0，频率×分量两轴联合，23.9.1 临时默认联动重验，§5.3）。

D-c（label 阈值收口，预期零效应）：resonanceLabelThresholds [85,67,50,27] ×0.5/×2
+ resonanceWeights 等权锚——零效应（synergy 档位逐位一致 + saEx 不动）判冗余归档
（23.3 A 组模式）；有效应 = label 消费进档位的隐藏路径，停下做代码侦查（§5.3 D-c）。

锚：baseline 三窗逐位复现 post-fund10 基线锚（0.112/0.088/0.0951，2026-09-15 fund10
落默认后；pre-fund10 代际锚 = 0.1044/0.0918/0.0933，历史报告口径）。

用法：
  python -m backend.operations.evaluate_resonance_participation [--window all] [--out <path>]
      [--extra-trial <json>]  （D-b 二轮：sampleQuality 联动开关等）
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
TRIGGER_RATE_FLAG = 0.035
SA_COUNT_FLOOR = 30  # S/A 样本量核查（档位塌缩核查线，审计 §5.4.2）
_OVERRIDE_MISSING = object()


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫（review C1）：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻、产出假零效应/假惰性结论——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")

DB_TRIALS: list[dict[str, Any]] = [
    {"key": "db_ms10", "desc": "D-b 回收：横截面样本门槛 20→10", "overrides": {"resonanceMinMarketSampleCount": 10}, "group": "db"},
    {"key": "db_ms40", "desc": "D-b 收紧：横截面样本门槛 20→40", "overrides": {"resonanceMinMarketSampleCount": 40}, "group": "db"},
    {"key": "db_mid6", "desc": "D-b 回收：排名序列窗口 8→6", "overrides": {"resonanceMidWindowBars": 6}, "group": "db"},
    {"key": "db_mid10", "desc": "D-b 收紧：排名序列窗口 8→10", "overrides": {"resonanceMidWindowBars": 10}, "group": "db"},
]

DC_TRIALS: list[dict[str, Any]] = [
    {"key": "dc_label_x05", "desc": "D-c 收口：label 阈值 ×0.5（预期零效应，展示面）", "overrides": {"resonanceLabelThresholds": [42.5, 33.5, 25.0, 13.5]}, "group": "dc"},
    {"key": "dc_label_x2", "desc": "D-c 收口：label 阈值 ×2（预期零效应，展示面）", "overrides": {"resonanceLabelThresholds": [170.0, 134.0, 100.0, 54.0]}, "group": "dc"},
    {"key": "dc_weights_equal", "desc": "D-c 收口：resonanceWeights 等权锚（阶段 7.2 零效应复核）", "overrides": {"resonanceWeights": [0.2, 0.2, 0.2, 0.2, 0.2]}, "group": "dc"},
]

ALL_TRIALS: list[dict[str, Any]] = [*DB_TRIALS, *DC_TRIALS]


def anchor_check(window: str, sa_ex: float | None, anchor: dict[str, float] | None) -> dict[str, Any]:
    if anchor is None:
        return {"checked": False}
    expected = anchor[window]
    ok = sa_ex is not None and round(float(sa_ex), 4) == round(float(expected), 4)
    return {"checked": True, "expected": expected, "actual": sa_ex, "match": ok}


def _tiers_of(signals: list[dict[str, Any]], dim: str) -> list[str]:
    path = {"synergy": ("rankTrend", "observation", "synergy", "signalTier"), "resonance": ("rankTrend", "resonance", "signalTier")}[dim]
    out = []
    for s in signals:
        node: Any = s
        for key in path:
            node = (node or {}).get(key) if isinstance(node, dict) else None
        out.append(str(node or "unknown"))
    return out


def _directions_of(signals: list[dict[str, Any]]) -> list[str]:
    return [str(((s.get("rankTrend") or {}).get("resonance") or {}).get("direction") or "") for s in signals]


def participation_of(directions: list[str]) -> float | None:
    return round(sum(1 for d in directions if d in ("buy", "sell")) / len(directions), 4) if directions else None


def zero_effect_check(base_result: dict[str, Any], trial_result: dict[str, Any]) -> dict[str, Any]:
    """D-c 零效应判定：synergy 档位逐位一致 + saEx 不动（判定面）。

    resonanceDirections 一致性为诊断项：两侧都有数据时比较（belt-and-suspenders）；
    任一侧缺失（如 2026-09-15 首批缓存 baseline 未记录）记 None 不阻塞判定——
    代码事实兜底：resonanceWeights/label 阈值只进 raw_score→score 展示分，方向与
    signalTier 在 runtime.py:702-708 独立计算（先于 raw_score）。
    """
    tiers_equal = (base_result.get("signalTiers") or []) == (trial_result.get("signalTiers") or [])
    sa_equal = (base_result.get("synergy") or {}).get("saEx") == (trial_result.get("synergy") or {}).get("saEx")
    base_dirs = base_result.get("resonanceDirections")
    trial_dirs = trial_result.get("resonanceDirections")
    dirs_comparable = base_dirs is not None and trial_dirs is not None
    return {
        "tiersIdentical": tiers_equal,
        "saExIdentical": sa_equal,
        "resonanceDirectionsIdentical": (base_dirs == trial_dirs) if dirs_comparable else None,
        "verdict": "zero_effect_redundant" if (tiers_equal and sa_equal) else "unexpected_effect",
    }


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
        dist = trial.get("synergy", {}).get("distribution") or {}
        sa_count = dist.get("S", 0) + dist.get("A", 0)
        windows[win] = {
            "saEx": trial_sa,
            "saExRel": rels[win],
            "passHard": pass_hard[win],
            "triggerRateSA": round(sa_count / sum(v for v in dist.values() if isinstance(v, (int, float))), 4) if dist else None,
            "saCount": sa_count,
            "saCountCollapse": bool(sa_count < SA_COUNT_FLOOR),
            "resonanceParticipation": trial.get("resonanceParticipation"),
            "anchor": anchor_check(win, trial_sa, spec.get("anchor")),
            "regimeDelta": regime_delta_of(trial, base or {}),
        }
        if spec.get("group") == "dc":
            windows[win]["zeroEffect"] = zero_effect_check(base or {}, trial)
    if not windows:
        return {"verdict": "insufficient_data", "windows": windows}
    if spec.get("group") == "dc":
        verdicts = {w["zeroEffect"]["verdict"] for w in windows.values() if w.get("zeroEffect")}
        return {
            "windows": windows,
            "group": "dc",
            "dcVerdict": "zero_effect_redundant" if verdicts == {"zero_effect_redundant"} else "unexpected_effect_investigate",
            "note": "unexpected_effect = label/weights 存在进档位的隐藏路径，停下做代码侦查（§5.3 D-c）；dirs=None 为缓存 baseline 缺字段的诊断降级，判定以 tiers+saEx 为准（runtime.py:702-721 代码事实兜底）",
        }
    c1 = rels.get("decision") is not None and rels["decision"] >= 0.03
    c2 = any(v is not None and v > 0 for v in (rels.get("oos1"), rels.get("oos2")))
    c3 = pass_hard.get("decision") is True
    return {
        "windows": windows,
        "saExRel": rels,
        "group": "db",
        "verdictCard": {"C1_decisionRelGE3pct": c1, "C2_oosAnyPositive": c2, "C3_decisionPassHard": c3},
        "cardResult": "PASS_CANDIDATE" if all([c1, c2, c3]) else "OBSERVE",
        "nextGate": "PASS_CANDIDATE 须追加 Track 1 交易复核 + res 票权三档交互表（频率×分量两轴，§5.3）",
    }


def frames_entry(report: dict[str, Any], window: str) -> list[dict[str, Any]]:
    cache = report.get("__frames__") or {}
    if window not in cache:
        from backend.operations.optimize_resonance_parameters import load_frames

        start, end = WINDOWS[window]
        cache[window] = load_frames(start, end)
        report["__frames__"] = cache
    return cache[window]


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = True  # 审计 M3
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "resonance-participation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}  # 帧缓存不落盘（review I1，同 evaluate_ts_factor_weights 模式）
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_window(window: str, report: dict[str, Any], specs: list[dict[str, Any]] | None = None) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = frames_entry(report, window)
    assert_not_frozen(frames, "scan")  # 无条件执行（含 resume 路径，review I2）
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[res-part] {window} frames={len(frames)}", file=sys.stderr)
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
        baseline_spec = {"key": "baseline", "desc": "当前默认（resonanceMinMarketSampleCount=20 / MidWindowBars=8）", "overrides": {}, "anchor": ANCHOR_BASELINE, "group": "baseline"}
        specs = [baseline_spec, *ALL_TRIALS]
    for spec in specs:
        key = spec["key"]
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[res-part] {window} {key} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        result = {
            **result,
            "signalTiers": _tiers_of(signals, "synergy"),
            "resonanceParticipation": participation_of(_directions_of(signals)),
            "resonanceDirections": _directions_of(signals),
        }
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        print(
            f"[res-part] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']} part={result['resonanceParticipation']}) ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="共振频率轴剂量扫描 + label 收口（方案 D D-b/D-c）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument("--extra-trial", default="", help="追加 trial：JSON {key,desc,overrides,group}（D-b 二轮：sampleQuality 联动开关等）")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "resonance-participation.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    baseline_spec = {"key": "baseline", "desc": "当前默认", "overrides": {}, "anchor": ANCHOR_BASELINE, "group": "baseline"}
    specs: list[dict[str, Any]] = [baseline_spec, *ALL_TRIALS]
    if args.extra_trial:
        extra = json.loads(args.extra_trial)
        for spec in extra if isinstance(extra, list) else [extra]:
            spec.setdefault("anchor", None)
            spec.setdefault("group", "db")
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
    _save(report)
    report.pop("__out__", None)
    print(json.dumps({"anchorChain": report["anchorChain"], "summary": {k: {kk: vv for kk, vv in v.items() if kk != "windows"} for k, v in summary.items()}}, ensure_ascii=False, indent=2, default=str))
    print(f"[res-part] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
