# -*- coding: utf-8 -*-
"""vp 成交额量比三参数扫描 harness（参数缺口补扫方案 P4，两轮制粗扫）。

缺口来源：G3 成交额量比三参数 amountRatioPeriod(5)/amountRatioHigh(1.5)/amountRatioLow(0.5)
2026-08-18 落地（ranking/volume_price.py:233-238 High/Low 消费、:260-285 compute_amount_ratio
period 消费），§9.2 vp 扫描在其之前，三参数从未剂量扫描。

P4-0 前置诊断（只读）：amountRatio 可算率重测（G3 落地时可算 20.7%/增强生效 3.6% 为
fund10 前旧口径，只作对照不引用为现值）——baseline replay 后从 signals 统计
observation.amountRatio 非 None/非 NaN 占比写入报告 amountRatioDiagnostic。
2026-09-15 实测（decision 窗 655 帧 / 131197 信号）：可算率 6.12%（8029/131197），
可算样本内增强生效率 27.99%（2247/8029；全信号分母 1.71%）——远低于 30% 判定线，
**低杠杆**：粗扫照跑，结论标注低杠杆（lowLeverage=True 已随报告留痕）。

P4-1 收口注记：synergyLowVp(40)/synergyHighVp(75)（volume_price.py:556-557）消费链已由
2026-09-15 代码核实收口——compute_synergy_state 仅产 observation.synergy（hardWarn 全后端
零消费方，仅 runtime.py:1397 展示标注与 gate_flip_stats 研统计读取）；risk["synergy"] 双门
来自 analyze_risk 独立 severity 合成（risk.py:67，经 decisionRiskPenaltyWeights 进决策面、
活跃）——按 §23.3 zero_effect 模式以代码消费面事实直接收口，不在本 harness 扫描范围。

窗口纪律：decision 2026-04-15~07-31 / OOS-1 08-15~08-31 / OOS-2 09-01~09-12；FINAL
(08-01~08-14) 冻结（assert_not_frozen 守卫无条件执行，含 resume 路径）。WINDOWS 从
evaluate_ts_factor_weights.py:56-60 import，禁止复制日期字面量。OOS-2 已被阶段 24/25
部分消费（M3 折扣口径，报告 windowsConsumed=True 标记）。

锚代际：post-fund10 基线锚（2026-09-15 代际，主代理实测 oos2=0.0951 逐位复现）；
pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1 历史
报告口径，禁止引用）。baseline 任一窗锚不复现立即 raise（配置漂移，不带病继续）。

trial 组（P4-a 粗扫，单变量 5 档，默认档由 baseline 承担，12 trial + baseline）：
- amountRatioPeriod 2/3/**5**/8/13；amountRatioHigh 1.1/1.3/**1.5**/2.0/2.5；
  amountRatioLow 0.2/0.35/**0.5**/0.65/0.8；
- focus 维：synergy + volumePrice（两维 saEx 都出；volumePrice 经 tier_forward_returns
  dimension="volumePrice" 独立统计，附加读数 vpSaEx/vpSaExRel）；
- 每 trial 监控 S+A 触发率（TRIGGER_RATE_FLAG=0.035 同范式）+ regimeDelta 四桶附加读数。

判定卡（Track 2 双轨制 §19.3/§19.6）：C1 decision synergy saEx rel ≥ +3% / C2 OOS ≥1 窗
同向为正 / C3 decision passHard 不降 → PASS_CANDIDATE / OBSERVE。

用法：
  python -m backend.operations.evaluate_vp_amount_ratio [--window all] [--out <path>]
      [--diagnose-only] [--extra-trial <json>]
  --diagnose-only：只跑 baseline（含 P4-0 诊断与锚校验），跳过 12 trial。
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

from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns
from backend.operations.evaluate_ts_factor_weights import WINDOWS, _rel_improve
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate
from backend.operations.optimize_resonance_parameters import _tier_summary

# 锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后，报告 baseline-anchor-post-fund10.json）；
# pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1，历史报告口径）
ANCHOR_BASELINE: dict[str, float] = {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}
TRIGGER_RATE_FLAG = 0.035  # S+A 触发率旗标（阶段 22.6 观察线，同范式）

# P4-0 低杠杆判定线（方案文档：可算率 <30% → 粗扫照跑、结论标注低杠杆）
LOW_LEVERAGE_RATE = 0.30

_OVERRIDE_MISSING = object()


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻、产出假零效应/假惰性结论——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")


# 单变量 5 档：默认档（Period 5 / High 1.5 / Low 0.5）由 baseline 承担
AMOUNT_RATIO_AXIS_LEVELS: dict[str, list[float]] = {
    "amountRatioPeriod": [2.0, 3.0, 8.0, 13.0],
    "amountRatioHigh": [1.1, 1.3, 2.0, 2.5],
    "amountRatioLow": [0.2, 0.35, 0.65, 0.8],
}

AMOUNT_RATIO_TRIALS: list[dict[str, Any]] = [
    # amountRatioPeriod（成交额均额窗口，前 N 帧平均）
    {"key": "arPeriod_2", "desc": "amountRatioPeriod=2（短窗：量比对近期成交额更敏感）", "overrides": {"amountRatioPeriod": 2.0}},
    {"key": "arPeriod_3", "desc": "amountRatioPeriod=3", "overrides": {"amountRatioPeriod": 3.0}},
    {"key": "arPeriod_8", "desc": "amountRatioPeriod=8", "overrides": {"amountRatioPeriod": 8.0}},
    {"key": "arPeriod_13", "desc": "amountRatioPeriod=13（长窗：基准更平滑）", "overrides": {"amountRatioPeriod": 13.0}},
    # amountRatioHigh（放量加分阈值：ar >= High → amount_score +step）
    {"key": "arHigh_11", "desc": "amountRatioHigh=1.1（放量阈值下探：更易加分）", "overrides": {"amountRatioHigh": 1.1}},
    {"key": "arHigh_13", "desc": "amountRatioHigh=1.3", "overrides": {"amountRatioHigh": 1.3}},
    {"key": "arHigh_20", "desc": "amountRatioHigh=2.0（加压：仅极端放量加分）", "overrides": {"amountRatioHigh": 2.0}},
    {"key": "arHigh_25", "desc": "amountRatioHigh=2.5", "overrides": {"amountRatioHigh": 2.5}},
    # amountRatioLow（缩量减分阈值：ar <= Low → amount_score -step）
    {"key": "arLow_02", "desc": "amountRatioLow=0.2（缩量阈值下探：仅极端缩量减分）", "overrides": {"amountRatioLow": 0.2}},
    {"key": "arLow_035", "desc": "amountRatioLow=0.35", "overrides": {"amountRatioLow": 0.35}},
    {"key": "arLow_065", "desc": "amountRatioLow=0.65（上探：更易减分）", "overrides": {"amountRatioLow": 0.65}},
    {"key": "arLow_08", "desc": "amountRatioLow=0.8", "overrides": {"amountRatioLow": 0.8}},
]


def build_specs(extra_trial: str = "") -> list[dict[str, Any]]:
    """baseline（带锚）+ 12 trial；--extra-trial JSON 注入的精扫 trial 追加在尾部（anchor 默认 None）。"""
    specs: list[dict[str, Any]] = [
        {"key": "baseline", "desc": "当前默认（amountRatio 5/1.5/0.5）", "overrides": {}, "anchor": ANCHOR_BASELINE},
        *AMOUNT_RATIO_TRIALS,
    ]
    if extra_trial:
        extra = json.loads(extra_trial)
        for spec in extra if isinstance(extra, list) else [extra]:
            spec.setdefault("anchor", None)
            specs.append(spec)
    return specs


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


def amount_ratio_diagnostic(signals: list[dict[str, Any]], config: Any) -> dict[str, Any]:
    """P4-0 前置诊断：amountRatio 可算率（非 None/非 NaN）+ 增强生效率（阈值命中）。

    生效率分母为可算样本（放量加分/缩量减分实际进 amount_score 的占比）。
    可算率 <LOW_LEVERAGE_RATE(30%) → lowLeverage=True：粗扫照跑，结论标注"低杠杆"。
    空 signals → 可算率 None（fail-visible，不伪造 0）。
    """
    total = len(signals)
    thresholds = {
        "amountRatioPeriod": getattr(config, "amountRatioPeriod", None),
        "amountRatioHigh": getattr(config, "amountRatioHigh", None),
        "amountRatioLow": getattr(config, "amountRatioLow", None),
    }
    if total <= 0:
        return {
            "total": 0, "computable": 0, "computableRate": None, "effective": 0,
            "effectiveRate": None, "lowLeverage": None, "thresholds": thresholds,
            "note": "no signals，可算率不可判（fail-visible）",
        }
    computable = 0
    effective = 0
    high = float(thresholds["amountRatioHigh"])
    low = float(thresholds["amountRatioLow"])
    for s in signals:
        ar = (((s.get("rankTrend") or {}).get("observation") or {}).get("amountRatio"))
        if isinstance(ar, (int, float)) and math.isfinite(float(ar)):
            computable += 1
            if ar >= high or ar <= low:
                effective += 1
    rate = round(computable / total, 4)
    eff_rate = round(effective / computable, 4) if computable else None
    low_leverage = rate < LOW_LEVERAGE_RATE
    return {
        "total": total,
        "computable": computable,
        "computableRate": rate,
        "effective": effective,
        "effectiveRate": eff_rate,
        "lowLeverage": low_leverage,
        "thresholds": thresholds,
        "note": (
            "低杠杆：可算率 <30%，粗扫照跑但结论标注低杠杆（P4-0）" if low_leverage else ""
        ),
    }


def trial_summary(report: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """单 trial 三窗汇总：synergy/volumePrice 两维 saEx + 判定卡 + 触发率漂移 + regimeDelta。"""
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
        base_vp = (base or {}).get("volumePrice") or {}
        trial_vp = trial.get("volumePrice") or {}
        trig = trigger_rate_of(trial)
        windows[win] = {
            "saEx": trial_sa,
            "saExRel": rels[win],
            "vpSaEx": trial_vp.get("saEx"),
            "vpSaExRel": _rel_improve(trial_vp.get("saEx"), (base_vp or {}).get("saEx")),
            "vpPassHard": trial_vp.get("passHard"),
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
        "effectSizeNote": (
            "amountRatio 增强生效占比低（G3 前口径 3.6%，现值以 P4-0 诊断为准）时"
            "单参剂量效应可能小于判定卡门槛：OBSERVE 须结合 P4-0 可算率/生效率解读，"
            "钝感 ≠ 无信息（23.6.5 口径）"
        ),
    }


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
    assert_not_frozen(frames, "scan")  # 无条件执行（含 resume 路径）
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[vp-amount-ratio] {window} frames={len(frames)}", file=sys.stderr)
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
        specs = build_specs()
    for spec in specs:
        key = spec["key"]
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[vp-amount-ratio] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        # focus 维 volumePrice 独立统计（evaluate_gate 只产 synergy/rankTrend 两维）
        vp_stats = tier_forward_returns(signals, frames, horizon=1, dimension="volumePrice")
        result = {**result, "signalTiers": _tiers_of(signals), "volumePrice": _tier_summary(vp_stats)}
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        if key == "baseline":
            # P4-0 前置诊断：amountRatio 可算率（随 baseline 留痕，resume 后不重跑）
            entry["amountRatioDiagnostic"] = amount_ratio_diagnostic(signals, config)
        if spec.get("anchor"):
            # 锚代际守卫：baseline 任一窗不复现 = 配置漂移，立即停止（不带病继续）
            check = anchor_check(window, result["synergy"]["saEx"], spec["anchor"])
            entry.setdefault("anchorChecks", {})[window] = check
            if not check["match"]:
                _save(report)
                raise AssertionError(
                    f"baseline 锚不复现（配置漂移，立即停止）: {window} "
                    f"expected={check['expected']} actual={check['actual']}——检查 config 代际/数据窗口"
                )
        print(
            f"[vp-amount-ratio] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) vp(saEx={result['volumePrice']['saEx']}) "
            f"({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = True  # OOS-2 消费标记（M3 折扣口径）
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "vp-amount-ratio.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}  # 帧缓存不落盘（同范式）
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="vp 成交额量比三参数扫描（方案 P4，两轮制粗扫）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument("--diagnose-only", action="store_true", help="只跑 baseline（含 P4-0 诊断与锚校验）")
    parser.add_argument("--extra-trial", default="", help="追加 trial：JSON {key,desc,overrides}（第二轮精扫补跑）")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "vp-amount-ratio.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    specs = build_specs(args.extra_trial)
    if args.diagnose_only:
        specs = [spec for spec in specs if spec["key"] == "baseline"]

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
    print(json.dumps({"anchorChain": report["anchorChain"], "summary": {k: {**v, "windows": {w: {kk: vv for kk, vv in d.items() if kk in ("saEx", "saExRel", "vpSaEx", "vpSaExRel", "triggerRateSA", "triggerFlag")} for w, d in v.get("windows", {}).items()}} for k, v in summary.items()}}, ensure_ascii=False, indent=2, default=str))
    print(f"[vp-amount-ratio] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
