# -*- coding: utf-8 -*-
"""cs 档位定义阈值扫描 harness（参数补扫方案 P1-a，9 轴 × 4 非默认档，两轮制粗扫）。

缺口来源（ranktrend-param-gap-scan-plan.md 方案 P1）：
- `crossSectionStrongMin(85)/StrongDeltaUp(5)/MidMin(50)/MidDeltaUp(15)/MidMax(50)/
  MidDeltaDown(−15)/WeakMax(15)/WeakDeltaDown(−5)`（trend/cross_section.py::_tier_from 消费）
  为阶段 10 设计值直接落默认，从未剂量扫描；
- `crossSectionStrongAbsMin(70)` 为 P1-0 新参数化字段（原 _tier_from 硬编码绝对线 70，
  delta 分支与首帧降级分支复用；默认=原值 golden 不漂移），本案首扫；
- cs 的 A 档可达性（§18 核心痛点：数学边界 delta ≤ 100−pct 由 StrongMin × StrongDeltaUp
  直接决定，榜首强势股 delta 确认永不可达）与 C 档 62.5% 系统性负票流（§23.8）都由这组
  边界决定；
- **WeakAbsMax(30) 无效轴归档注记（审计 I-1）**：`percentile <= 30` 与中位兜底分支同返回
  C 档（cross_section.py:86-91，首帧分支 :95-99 亦然），任何取值只改 tierReasons 文案、
  不改 signalTier——不参数化、不进扫描、不登记台账。

trial 表：9 轴 × 4 非默认档 = 36 trial + baseline = 37（单变量 5 档制，默认档由 baseline
承担）。每 trial 只动自己轴（单键 overrides），无打包。

锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后实测，oos2 已复核）；
pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1 历史口径）。
baseline 首跑任一锚不复现 → 停止，报告配置漂移。

监控项（每 trial 必出）：cs 档位分布迁移（A/B/C/D/unknown 占比，路径
signal['rankTrend']['observation']['crossSection']['signalTier']，runtime.py 写入，
oos2 smoke 以真实帧复核 counts 总和==signalCount）；A 档样本量与 C 档占比的历史对照值
（§11.5 500 / §23.8 62.5%）均为 fund10 前旧口径，首跑已重测，见 monitorReferences；
S+A 触发率（>3.5% 旗标，阶段 22.6 观察线）；C5 翻转率（evaluate_gate flipRates 可取，
veto/bd 升幅 ≤+0.01 附加卡）；A 档塌缩/C 档翻倍类分布剧变打结构代价旗标（收口节口径）。

P1-b 精扫：--extra-trial 注入组合/persist 交叉对照（如 crossSectionPersistFrames=3 置 3
开启替代路径），本 harness 不内置。

用法：
  python -m backend.operations.evaluate_cs_tier_thresholds [--window all] [--out <path>]
      [--extra-trial <json>]
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

# 锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后实测；报告 baseline-anchor-post-fund10.json）
ANCHOR_BASELINE: dict[str, float] = {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}
TRIGGER_RATE_FLAG = 0.035  # S+A 触发率旗标（阶段 22.6 观察线）
C5_FLIP_RISE_FLAG = 0.01  # C5 附加卡：veto/bd 翻转升幅对照线（§19.3）
A_TIER_SAMPLE_REFERENCE = 500  # 长测计划 §11.5 A 档触发线（fund10 前旧口径，首跑重测）
C_TIER_SHARE_REFERENCE = 0.625  # 长测计划 §23.8 C 档占比基线（fund10 前旧口径，首跑重测）
STALE_NOTE = "旧口径对照值（fund10 落默认前），首跑已重测，不直接比对"
MONITOR_REFERENCES: dict[str, Any] = {
    "aTierSampleCount": {"ref": A_TIER_SAMPLE_REFERENCE, "source": "长测计划 §11.5 A 档触发线（fund10 前）", "note": STALE_NOTE},
    "cTierShare": {"ref": C_TIER_SHARE_REFERENCE, "source": "长测计划 §23.8 C 档占比基线（fund10 前）", "note": STALE_NOTE},
    "weakAbsMaxAxis": {
        "status": "无效轴归档（审计 I-1）",
        "note": "percentile<=30 与中位兜底分支同返回 C 档，仅 tierReasons 文案不同——不参数化、不进扫描、不登记台账",
    },
}

# 9 轴 × 4 非默认档（默认档由 baseline 承担；默认值权威来源 trend/cross_section.py CROSS_SECTION_DEFAULTS）
AXIS_LEVELS: dict[str, list[float]] = {
    "crossSectionStrongMin": [80.0, 82.5, 87.5, 90.0],  # 默认 85
    "crossSectionStrongDeltaUp": [3.0, 4.0, 6.0, 8.0],  # 默认 5
    "crossSectionMidMin": [40.0, 45.0, 55.0, 60.0],  # 默认 50
    "crossSectionMidDeltaUp": [10.0, 12.0, 20.0, 25.0],  # 默认 15
    "crossSectionMidMax": [40.0, 45.0, 55.0, 60.0],  # 默认 50
    "crossSectionMidDeltaDown": [-10.0, -12.0, -20.0, -25.0],  # 默认 -15
    "crossSectionWeakMax": [10.0, 12.5, 17.5, 20.0],  # 默认 15
    "crossSectionWeakDeltaDown": [-3.0, -4.0, -6.0, -8.0],  # 默认 -5
    "crossSectionStrongAbsMin": [60.0, 65.0, 75.0, 80.0],  # 默认 70（P1-0 新参数化）
}

AXIS_DESC: dict[str, str] = {
    "crossSectionStrongMin": "StrongMin（A 档 percentile 下限）",
    "crossSectionStrongDeltaUp": "StrongDeltaUp（A 档上升确认，A 可达性杠杆 §18）",
    "crossSectionMidMin": "MidMin（B 档中位下限）",
    "crossSectionMidDeltaUp": "MidDeltaUp（B 档显著上升）",
    "crossSectionMidMax": "MidMax（C 档中位上限）",
    "crossSectionMidDeltaDown": "MidDeltaDown（C 档显著下降）",
    "crossSectionWeakMax": "WeakMax（D 档低位上限）",
    "crossSectionWeakDeltaDown": "WeakDeltaDown（D 档下降确认）",
    "crossSectionStrongAbsMin": "StrongAbsMin（B 档绝对线，P1-0 新参数化）",
}


def _spec(key: str, axis: str, value: float) -> dict[str, Any]:
    return {
        "key": key,
        "desc": f"{AXIS_DESC[axis]} = {value}",
        "axis": axis,
        "value": value,
        "overrides": {axis: value},
    }


def _level_tag(value: float) -> str:
    if value < 0:
        return "m" + _level_tag(-value)
    return str(int(value)) if value == int(value) else str(value).replace(".", "")


def _build_trials() -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    for axis, levels in AXIS_LEVELS.items():
        short = axis.removeprefix("crossSection")
        first = short[0].lower() + short[1:]
        for value in levels:
            trials.append(_spec(f"{first}_{_level_tag(value)}", axis, value))
    return trials


CS_TRIALS: list[dict[str, Any]] = _build_trials()

_OVERRIDE_MISSING = object()


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫（review C1 同款）：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻、产出假零效应/假惰性结论——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")


def anchor_check(window: str, sa_ex: float | None, anchor: dict[str, float] | None) -> dict[str, Any]:
    if anchor is None:
        return {"checked": False}
    expected = anchor[window]
    ok = sa_ex is not None and round(float(sa_ex), 4) == round(float(expected), 4)
    return {"checked": True, "expected": expected, "actual": sa_ex, "match": ok}


CS_TIER_KEYS = ("A", "B", "C", "D")


def cs_tier_distribution_of(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """cs 档位分布统计：observation.crossSection.signalTier 的 A/B/C/D/unknown 计数与占比。

    路径 signal['rankTrend']['observation']['crossSection']['signalTier']（engine/runtime.py
    写入，oos2 smoke 已用真实帧复核 counts 总和==signalCount）。缺 observation/非法档位/
    None 一律计 unknown（fail-visible 计数，不丢弃样本）；total=0 时占比为 None 不伪造 0。
    """
    counts: dict[str, int] = {k: 0 for k in CS_TIER_KEYS}
    counts["unknown"] = 0
    for s in signals:
        tier = ((((s.get("rankTrend") or {}).get("observation") or {}).get("crossSection") or {}).get("signalTier"))
        counts[str(tier) if tier in CS_TIER_KEYS else "unknown"] += 1
    total = sum(counts.values())
    return {
        "counts": counts,
        "total": total,
        "shares": {k: (round(v / total, 4) if total else None) for k, v in counts.items()},
        "aSampleCount": counts["A"],
        "cShare": round(counts["C"] / total, 4) if total else None,
    }


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


def flip_delta_of(trial: dict[str, Any], base: dict[str, Any]) -> dict[str, Any] | None:
    """C5 附加卡素材：veto/bd/regime 翻转率相对 baseline 的变化（evaluate_gate flipRates）。"""
    tf = trial.get("flipRates") or {}
    bf = base.get("flipRates") or {}
    if not tf or not bf:
        return None
    return {
        k: (None if tf.get(k) is None or bf.get(k) is None else round(tf[k] - bf[k], 5))
        for k in ("veto", "bd_downgrade", "regime_state")
        if k in bf or k in tf
    }


def distribution_delta_of(trial: dict[str, Any], base: dict[str, Any]) -> dict[str, Any] | None:
    """cs 档位分布迁移量 + 结构代价旗标（监控旗标，非判定卡）。

    A 档样本量塌缩 >30% 或 C 档占比上升 ≥10pp 判结构代价（方案 P1 收口节：档位分布剧变的
    档位即使 saEx 改善也标注结构代价）。
    """
    td = trial.get("csTierDistribution") or {}
    bd = base.get("csTierDistribution") or {}
    a_trial, a_base = td.get("aSampleCount"), bd.get("aSampleCount")
    c_trial, c_base = td.get("cShare"), bd.get("cShare")
    if not td or not bd or not td.get("total") or not bd.get("total"):
        return None
    a_rel = round((a_trial - a_base) / a_base, 4) if a_base else None
    c_pp = round(c_trial - c_base, 4) if (c_trial is not None and c_base is not None) else None
    return {
        "aSampleCountRel": a_rel,
        "cShareDeltaPp": c_pp,
        "structuralCostFlag": bool(
            (a_base and a_trial is not None and a_trial < 0.7 * a_base)
            or (c_pp is not None and c_pp >= 0.10)
        ),
        "note": "A 档样本塌缩 >30% 或 C 档占比上升 >=10pp 判结构代价（方案 P1 收口节；监控旗标非判定卡）",
    }


def trial_summary(report: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """单 trial 三窗汇总：saEx/rel + 判定卡 + cs 分布迁移 + 触发率 + C5 翻转率素材。"""
    windows: dict[str, Any] = {}
    rels: dict[str, float | None] = {}
    pass_hard: dict[str, bool | None] = {}
    distribution_delta: dict[str, Any] | None = None
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
            "csTierDistribution": trial.get("csTierDistribution"),
            "triggerRateSA": trig,
            "triggerFlag": bool(trig is not None and trig > TRIGGER_RATE_FLAG),
            "anchor": anchor_check(win, trial_sa, spec.get("anchor")),
            "regimeDelta": regime_delta_of(trial, base or {}),
            "flipDelta": flip_delta_of(trial, base or {}),
            "distributionDelta": distribution_delta_of(trial, base or {}),
        }
        if spec["key"] != "baseline" and windows[win]["distributionDelta"] is not None:
            distribution_delta = windows[win]["distributionDelta"]
    if not windows:
        return {"verdict": "insufficient_data", "windows": windows}
    c1 = rels.get("decision") is not None and rels["decision"] >= 0.03
    c2 = any(v is not None and v > 0 for v in (rels.get("oos1"), rels.get("oos2")))
    c3 = pass_hard.get("decision") is True
    rises = [
        fd[k]
        for w in windows.values()
        for fd in [w.get("flipDelta") or {}]
        for k in ("veto", "bd_downgrade")
        if fd.get(k) is not None
    ]
    c5 = (max(rises) <= C5_FLIP_RISE_FLAG) if rises else None  # 附加卡：不可算时 None（不伪造）
    card = {
        "C1_decisionRelGE3pct": c1,
        "C2_oosAnyPositive": c2,
        "C3_decisionPassHard": c3,
        "C5_flipRiseLE1pct": c5,
    }
    return {
        "windows": windows,
        "saExRel": rels,
        "verdictCard": card,
        "cardResult": "PASS_CANDIDATE" if all([c1, c2, c3]) else "OBSERVE",
        "distributionDelta": distribution_delta,
        "effectSizeNote": "C5 为附加卡不参与 PASS_CANDIDATE 判定（§19.3）；A/C 分布剧变见 distributionDelta.structuralCostFlag（监控旗标）",
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
        print(f"[cs-tier] {window} frames={len(frames)}", file=sys.stderr)
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
        specs = [
            {"key": "baseline", "desc": "当前默认（cs 档位 9 参数现值，见 AXIS_LEVELS 注释）", "overrides": {}, "anchor": ANCHOR_BASELINE},
            *CS_TRIALS,
        ]
    for spec in specs:
        key = spec["key"]
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[cs-tier] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        result = {**result, "csTierDistribution": cs_tier_distribution_of(signals)}
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        dist = result.get("csTierDistribution") or {}
        print(
            f"[cs-tier] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) cs(A={dist.get('aSampleCount')} "
            f"C={dist.get('cShare')}) ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = True  # 审计 M3
    report["monitorReferences"] = MONITOR_REFERENCES
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "cs-tier-thresholds.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}  # 帧缓存不落盘
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="cs 档位定义阈值扫描（参数补扫方案 P1-a，9 轴 × 4 非默认档）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument(
        "--extra-trial",
        default="",
        help="追加 trial：JSON {key,desc,overrides}（P1-b 精扫补跑，如 persist 交叉对照 crossSectionPersistFrames=3）",
    )
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "cs-tier-thresholds.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    specs: list[dict[str, Any]] = [
        {"key": "baseline", "desc": "当前默认（cs 档位 9 参数现值，见 AXIS_LEVELS 注释）", "overrides": {}, "anchor": ANCHOR_BASELINE},
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
    _save(report)
    report.pop("__out__", None)
    print(
        json.dumps(
            {
                "anchorChain": report["anchorChain"],
                "summary": {
                    k: {
                        "cardResult": v.get("cardResult"),
                        "verdictCard": v.get("verdictCard"),
                        "saExRel": v.get("saExRel"),
                        "distributionDelta": v.get("distributionDelta"),
                    }
                    for k, v in summary.items()
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    print(f"[cs-tier] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
