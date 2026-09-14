# -*- coding: utf-8 -*-
"""vp 量价维信号参数再审视 harness（方案 C，审计修订稿 §4，三层 C-a/C-b/C-c）。

背景（§4.1）：阶段 9 量价扫描（2026-08-17）运行在旧基线（票权 1.0 等权、cs 未进投票），
此后三次落默认把基线推到 0.1044——阶段 9 的相对结论在新合成结构下交互项未验证；
且 23.9 参数化的量价批 2（score 形状面 + 档位决定面 fund/directionThresholds）从未扫描。

三层（§4.2）：
- C-a 已扫参数新基线复核（5 trial × 3 窗）：fund10 / over2 / fund10+over2 / mild1.15
  对照阶段 9/20 旧读数——同向存活 / 反向记"基线漂移失效"（fund10+over2 只记录判读，
  观察池触发条件不变，§4.3.3）；
- C-b 未扫面结构分组（家族探针，decision 窗）：volumeScoreUp(14)/volumeScoreDown(4)/
  fundScore(5) 三家族 ×{×0.5,×2} + directionThresholds 6 值 list ×{×0.5,×2} +
  amountScoreStep 两档——家族零效应（档位分布逐位一致 + saEx 不动）判冗余归档
  （23.3 A 组模式），有读数才进 C-c；
- C-c 活跃参数两轮扫描（视 C-b 证据，--extra-trial 追加，预算 ≤20 trial/窗 §7.4）；
  判定卡 Track 2 同构 + PASS_CANDIDATE 追加 Track 1 交易复核（e1a 教训，§4.2）；
  候选须补 vp 票权三档交互表（×0.75/1.0/×1.25，回应"1.0 已调准"命题，§4.2 末条）。

锚：baseline 三窗逐位复现 23.9.1 锚（0.1044/0.0918/0.0933）。
list patch 语义（§4.3.5）：directionThresholds 6 值整体替换无归一化，显式写全。

用法：
  python -m backend.operations.evaluate_vp_signal_parameters [--window all] [--out <path>]
      [--group ca|cb|all]  （C-c 以 --extra-trial 追加）
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
_OVERRIDE_MISSING = object()


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫（review C1）：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻、产出假零效应/假惰性结论——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")

# 家族字段枚举（config.py:166-190 批 2 量价打分阶梯；默认值与 config 逐一对应，
# 测试 test_vp_families_match_config_defaults 锁定枚举完整性）
UP_FAMILY: dict[str, float] = {
    "volumeScoreUpShrinkLimitUp": 8.0,
    "volumeScoreUpShrinkBase": 10.0,
    "volumeScoreUpShrinkSlope": 15.0,
    "volumeScoreUpCap": 15.0,
    "volumeScoreUpMildLimitUp": 10.0,
    "volumeScoreUpMildNormal": 5.0,
    "volumeScoreUpNormalBase": 10.0,
    "volumeScoreUpNormalSlope": 5.0,
    "volumeScoreUpOverBase": 15.0,
    "volumeScoreUpOverSlope": 10.0,
    "volumeScoreUpOverFloor": 5.0,
    "volumeScoreUpExcessBase": 15.0,
    "volumeScoreUpExcessSlope": 10.0,
    "volumeScoreUpExcessCap": 20.0,
}
DOWN_FAMILY: dict[str, float] = {
    "volumeScoreDownOverMild": -20.0,
    "volumeScoreDownShrink": -5.0,
    "volumeScoreDownLimitDown": -15.0,
    "volumeScoreDownNormal": -10.0,
}
FUND_FAMILY: dict[str, float] = {
    "fundScoreCap": 15.0,
    "fundScoreDumpBase": 10.0,
    "fundScoreDumpSlope": 0.5,
    "fundScoreNetSlope": 3.0,
    "fundScoreInOutStep": 5.0,
}
DTH_DEFAULT: list[float] = [7.0, 5.0, 3.0, 2.0, 1.0, 0.5]


def _scale_family(family: dict[str, float], factor: float) -> dict[str, Any]:
    return {field: round(value * factor, 6) for field, value in family.items()}


def _scale_list(values: list[float], factor: float) -> list[float]:
    return [round(v * factor, 6) for v in values]


# C-a：已扫参数新基线复核（§4.2，3 窗）
CA_TRIALS: list[dict[str, Any]] = [
    {"key": "fund10", "desc": "AbnormalFundRatio 20→10（阶段 9 最显著单参数）", "overrides": {"volumePriceAbnormalFundRatio": 10.0}, "windows": ("decision", "oos1", "oos2")},
    {"key": "over2", "desc": "OverVolumeRatio 2.5→2.0（阶段 9 次显著）", "overrides": {"volumePriceOverVolumeRatio": 2.0}, "windows": ("decision", "oos1", "oos2")},
    {"key": "fund10_over2", "desc": "fund10+over2 叠加（Track 2 观察池最高优先的新基线方向核对；不在本方案内决策）", "overrides": {"volumePriceAbnormalFundRatio": 10.0, "volumePriceOverVolumeRatio": 2.0}, "windows": ("decision", "oos1", "oos2")},
    {"key": "mild115", "desc": "MildRatio 1.05→1.15（阶段 9 微升档复核）", "overrides": {"volumePriceMildRatio": 1.15}, "windows": ("decision", "oos1", "oos2")},
]

# C-b：未扫面家族探针（§4.2，仅 decision 窗；零效应=档位分布逐位一致+saEx 不动）
CB_TRIALS: list[dict[str, Any]] = [
    {"key": "fam_up_x05", "desc": "volumeScoreUp 家族(14) ×0.5（score 形状面，预期冗余）", "overrides": _scale_family(UP_FAMILY, 0.5), "windows": ("decision",)},
    {"key": "fam_up_x2", "desc": "volumeScoreUp 家族(14) ×2", "overrides": _scale_family(UP_FAMILY, 2.0), "windows": ("decision",)},
    {"key": "fam_down_x05", "desc": "volumeScoreDown 家族(4) ×0.5", "overrides": _scale_family(DOWN_FAMILY, 0.5), "windows": ("decision",)},
    {"key": "fam_down_x2", "desc": "volumeScoreDown 家族(4) ×2", "overrides": _scale_family(DOWN_FAMILY, 2.0), "windows": ("decision",)},
    {"key": "fam_fund_x05", "desc": "fundScore 家族(5) ×0.5（档位决定面，预期活跃）", "overrides": _scale_family(FUND_FAMILY, 0.5), "windows": ("decision",)},
    {"key": "fam_fund_x2", "desc": "fundScore 家族(5) ×2", "overrides": _scale_family(FUND_FAMILY, 2.0), "windows": ("decision",)},
    {"key": "fam_dth_x05", "desc": "directionThresholds ×0.5（涨跌轴边界，档位决定面）", "overrides": {"volumePriceDirectionThresholds": _scale_list(DTH_DEFAULT, 0.5)}, "windows": ("decision",)},
    {"key": "fam_dth_x2", "desc": "directionThresholds ×2", "overrides": {"volumePriceDirectionThresholds": _scale_list(DTH_DEFAULT, 2.0)}, "windows": ("decision",)},
    {"key": "amount_25", "desc": "amountScoreStep 5→2.5", "overrides": {"amountScoreStep": 2.5}, "windows": ("decision",)},
    {"key": "amount_10", "desc": "amountScoreStep 5→10", "overrides": {"amountScoreStep": 10.0}, "windows": ("decision",)},
]

ALL_TRIALS: list[dict[str, Any]] = [*CA_TRIALS, *CB_TRIALS]


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


def family_verdict(base_result: dict[str, Any], trial_result: dict[str, Any]) -> dict[str, Any]:
    """C-b 家族判定（§4.2）：档位分布逐位一致 + saEx 不动 → zero_effect（整族冗余归档）。"""
    tiers_equal = (base_result.get("signalTiers") or []) == (trial_result.get("signalTiers") or [])
    base_sa = (base_result.get("synergy") or {}).get("saEx")
    trial_sa = (trial_result.get("synergy") or {}).get("saEx")
    sa_equal = base_sa == trial_sa
    return {
        "tiersIdentical": tiers_equal,
        "saExIdentical": sa_equal,
        "verdict": "zero_effect_redundant" if (tiers_equal and sa_equal) else "active",
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


def trial_summary(report: dict[str, Any], spec: dict[str, Any], group: str) -> dict[str, Any]:
    """C-a：Track 2 同构判定卡；C-b：家族 zero_effect/active 判定（decision 窗）。"""
    windows: dict[str, Any] = {}
    rels: dict[str, float | None] = {}
    pass_hard: dict[str, bool | None] = {}
    for win in WINDOWS:
        if win not in spec.get("windows", ("decision", "oos1", "oos2")):
            continue
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
        if group == "cb":
            windows[win]["family"] = family_verdict(base or {}, trial)
    if not windows:
        return {"verdict": "insufficient_data", "windows": windows}
    if group == "cb":
        fam = windows.get("decision", {}).get("family") or {}
        return {
            "windows": windows,
            "saExRel": rels,
            "group": "cb",
            "familyVerdict": fam.get("verdict"),
            "familyDetail": fam,
        }
    c1 = rels.get("decision") is not None and rels["decision"] >= 0.03
    c2 = any(v is not None and v > 0 for v in (rels.get("oos1"), rels.get("oos2")))
    c3 = pass_hard.get("decision") is True
    return {
        "windows": windows,
        "saExRel": rels,
        "group": "ca",
        "verdictCard": {"C1_decisionRelGE3pct": c1, "C2_oosAnyPositive": c2, "C3_decisionPassHard": c3},
        "cardResult": "PASS_CANDIDATE" if all([c1, c2, c3]) else "OBSERVE",
        "note": "C-a 判读=与阶段 9/20 旧读数对照（同向存活/反向=基线漂移失效）；fund10+over2 不在本方案内决策（§4.3.3）",
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
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "vp-signal-parameters.json"
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
        print(f"[vp-param] {window} frames={len(frames)}", file=sys.stderr)
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
        baseline_spec = {"key": "baseline", "desc": "当前默认（量价阶梯批 2 全默认）", "overrides": {}, "anchor": ANCHOR_BASELINE, "windows": ("decision", "oos1", "oos2")}
        specs = [baseline_spec, *ALL_TRIALS]
    for spec in specs:
        key = spec["key"]
        if window not in spec.get("windows", ("decision", "oos1", "oos2")):
            continue
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[vp-param] {window} {key} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        result = {**result, "signalTiers": _tiers_of(signals)}
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        print(
            f"[vp-param] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="vp 量价维信号参数再审视（方案 C：C-a 复核 + C-b 家族分组）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument("--extra-trial", default="", help="追加 trial：JSON {key,desc,overrides,windows}（C-c 两轮扫描追加）")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "vp-signal-parameters.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    baseline_spec = {"key": "baseline", "desc": "当前默认（量价阶梯批 2 全默认）", "overrides": {}, "anchor": ANCHOR_BASELINE, "windows": ("decision", "oos1", "oos2")}
    specs: list[dict[str, Any]] = [baseline_spec, *ALL_TRIALS]
    if args.extra_trial:
        extra = json.loads(args.extra_trial)
        for spec in extra if isinstance(extra, list) else [extra]:
            spec.setdefault("anchor", None)
            spec.setdefault("windows", ("decision", "oos1", "oos2"))
            specs.append(spec)

    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report, specs)

    summary = {}
    for spec in specs:
        group = "cb" if any(spec["key"] == t["key"] for t in CB_TRIALS) else "ca"
        summary[spec["key"]] = trial_summary(report, spec, group)
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
    print(f"[vp-param] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
