# -*- coding: utf-8 -*-
"""regime/risk 核心线位扫描 harness（方案 P3，P3-0 裁决收窄后粗扫轮）。

缺口（方案 P3）：批 3 区域（engine/config.py:192-251，risk 阶梯 34 项 + regime 打分
23 项 = 57 项，2026-09-14 参数化，长测计划无此清点编号）从未扫描。范围控制：不扫
全量——slope/cap/weights 属分值幅度面（阶段 25 方案 C-b 经验：×正缩放不改符号/阈值
比较，预期冗余），本轮只扫阈值比较面。

P3-0 前置活跃度诊断（data/reports/regime-risk-activity.json，判据与读数全留痕）裁决：
- regimeStrongScore 保扫：±10 扰动 candidateTier 赋值迁移率 1.14%（+10 方向）过 1% 判据
  线，迁移全部经 strong 禁入门 banStrongA/B=True 单一路径（normal->strong 26864 /
  strong->normal 11881）；
- regimeNormalScore/WeakScore 惰性免扫：±10 档位迁移 0%/0.27%/0.57% 均 <1%——
  NormalScore"分布敏感但档位钝感"（normal↔weak 边界不接档位门，runtime.py:783-796
  环境门只消费 strong/retreat）；
- risk Overheat/Divergence Sell/Hold 四线收口免扫：risk signal 唯一消费方 =
  core/backtest/execution.py:1441 回测展示文本，决策面零消费（§23.3 A 组 zero_effect
  模式，重扫触发条件见下）；
- riskSynergyOverheatSevMin/DivergenceSevMin 双 sev 轴保扫：severity 经
  decisionRiskPenaltyWeights 进置信度惩罚（runtime.py:312）+ A_MAIN money_risk 门
  （runtime.py:479），决策面活跃。

重扫触发条件（§23.7，两条）：
1. risk.overheat/divergence signal 字段获得决策面消费方，或 severity 计算链改为经
   Sell/Hold 线 → 重扫 risk Overheat/Divergence Sell/Hold 四线；
2. synergy 双门进决策面的权重/口径改动，或 severity 合成链（Offset/Scale/stage 乘数）
   改动 → 重扫双 sev 轴。

trial 表（3 轴 × 4 非默认档 = 12 + baseline = 13，单变量拆分，默认档由 baseline 承担，
focus synergy）：regimeStrongScore 60/65/75/80（默认 70）、riskSynergyOverheatSevMin
0.45/0.55/0.75/0.85（默认 0.65）、riskSynergyDivergenceSevMin 0.4/0.5/0.7/0.8（默认 0.6）。

线序预检（方案 P3 审计新增）：from_patch 对 regime 三线无校验（config.py 仅校验
tierSynergy 系），乱序 patch 在 trend/risk.py:164-169 的 elif 链静默退化不报错——
harness 对每个 trial（含 baseline 与 --extra-trial 注入）断言
StrongScore > NormalScore(50) > WeakScore(30) fail-fast。Normal/Weak 两线 P3-0 裁决
免扫，仅作线序固定参照。

特别监控（方案 P3 独有，每 trial 必出）：
- regimeView 分状态视图：evaluate_gate 四桶 saEx（strong/normal/weak/retreat）——
  strong 线移动直接重划 strong 桶边界与样本量（阶段 14 strong 双峰：塌陷/强劲并存，
  线位移动重新划分两峰）；
- 禁入触发率：banStrongA/B=True 的禁入面随线移动放大/缩小，以 strong 桶样本量
  （regimeStateCounts.strong）相对 baseline 的比值（strongBanRatio）度量；
- 判定卡 C1（decision rel ≥ +3%）∧ C2（OOS ≥1 窗同向为正）∧ C3（decision passHard）
  → PASS_CANDIDATE/OBSERVE；C4 四桶附加读数（regimeDelta）随窗输出。

锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后）；pre-fund10 代际锚 =
{"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1，历史报告口径）。
baseline 锚不复现即停（配置漂移），不产出 trial 结论。

用法：
  python -m backend.operations.evaluate_regime_risk_thresholds
      [--window decision|oos1|oos2|all] [--out <path>]
      [--extra-trial <json>]（P3-b 精扫注入：剂量点/组合 trial，{key,desc,overrides} 或列表）
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

# regime 线序参照：Normal/Weak P3-0 裁决免扫，线位保持默认（config.py:234-236 字段真名）
REGIME_STRONG_SCORE_DEFAULT = 70.0
REGIME_NORMAL_SCORE_DEFAULT = 50.0
REGIME_WEAK_SCORE_DEFAULT = 30.0

REGIME_STATES = ("strong", "normal", "weak", "retreat")

_OVERRIDE_MISSING = object()

TRIALS: list[dict[str, Any]] = [
    # ── regimeStrongScore（P3-0 保扫：禁入门单一路径；strong 桶边界/样本量直接随线移动）──
    {"key": "strong_60", "desc": "regimeStrongScore 70->60（strong 桶扩容，banStrongA/B 禁入面放大）", "overrides": {"regimeStrongScore": 60.0}},
    {"key": "strong_65", "desc": "regimeStrongScore 70->65", "overrides": {"regimeStrongScore": 65.0}},
    {"key": "strong_75", "desc": "regimeStrongScore 70->75", "overrides": {"regimeStrongScore": 75.0}},
    {"key": "strong_80", "desc": "regimeStrongScore 70->80（strong 桶收缩，禁入面缩小）", "overrides": {"regimeStrongScore": 80.0}},
    # ── riskSynergyOverheatSevMin（决策面活跃：over_sev 经 decisionRiskPenaltyWeights[0] 进置信度，runtime.py:312）──
    {"key": "overSev_045", "desc": "riskSynergyOverheatSevMin 0.65->0.45", "overrides": {"riskSynergyOverheatSevMin": 0.45}},
    {"key": "overSev_055", "desc": "riskSynergyOverheatSevMin 0.65->0.55", "overrides": {"riskSynergyOverheatSevMin": 0.55}},
    {"key": "overSev_075", "desc": "riskSynergyOverheatSevMin 0.65->0.75", "overrides": {"riskSynergyOverheatSevMin": 0.75}},
    {"key": "overSev_085", "desc": "riskSynergyOverheatSevMin 0.65->0.85", "overrides": {"riskSynergyOverheatSevMin": 0.85}},
    # ── riskSynergyDivergenceSevMin（决策面活跃：div_sev 进置信度[1] + A_MAIN money_risk 门，runtime.py:479）──
    {"key": "divSev_04", "desc": "riskSynergyDivergenceSevMin 0.6->0.4", "overrides": {"riskSynergyDivergenceSevMin": 0.4}},
    {"key": "divSev_05", "desc": "riskSynergyDivergenceSevMin 0.6->0.5", "overrides": {"riskSynergyDivergenceSevMin": 0.5}},
    {"key": "divSev_07", "desc": "riskSynergyDivergenceSevMin 0.6->0.7", "overrides": {"riskSynergyDivergenceSevMin": 0.7}},
    {"key": "divSev_08", "desc": "riskSynergyDivergenceSevMin 0.6->0.8", "overrides": {"riskSynergyDivergenceSevMin": 0.8}},
]


def assert_regime_line_order(overrides: dict[str, Any]) -> dict[str, float]:
    """线序预检（fail-fast）：from_patch 对 regime 三线无校验，乱序 patch 在
    trend/risk.py:164-169 的 elif 链静默退化不报错。Normal/Weak 取 patch 值或默认
    （免扫线，固定参照）——任何进入执行循环的 trial（含 extra-trial）都必须过线。"""
    strong = float(overrides.get("regimeStrongScore", REGIME_STRONG_SCORE_DEFAULT))
    normal = float(overrides.get("regimeNormalScore", REGIME_NORMAL_SCORE_DEFAULT))
    weak = float(overrides.get("regimeWeakScore", REGIME_WEAK_SCORE_DEFAULT))
    if not (strong > normal > weak):
        raise AssertionError(
            f"regime 线序非法: StrongScore={strong} >= NormalScore={normal} >= WeakScore={weak}"
            f"——须严格 Strong > Normal > Weak；from_patch 无校验，乱序会静默退化产出假结论"
        )
    return {"strong": strong, "normal": normal, "weak": weak}


def validate_trials() -> None:
    """内置 trial 表预检：单变量拆分（每 trial 恰一轴）+ 线序 fail-fast。"""
    for spec in TRIALS:
        axes = set(spec["overrides"])
        if len(axes) != 1:
            raise AssertionError(f"{spec['key']} 违反单变量拆分（恰一轴）: {sorted(axes)}")
        assert_regime_line_order(spec["overrides"])


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫：from_patch 对未知字段静默忽略（hasattr 无 else），
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


def _tiers_of(signals: list[dict[str, Any]]) -> list[str]:
    out = []
    for s in signals:
        tier = ((((s.get("rankTrend") or {}).get("observation") or {}).get("synergy") or {}).get("signalTier"))
        out.append(str(tier or "unknown"))
    return out


def regime_delta_of(trial: dict[str, Any], base: dict[str, Any]) -> dict[str, Any] | None:
    """C4 四桶附加读数：trial − baseline 的分状态 saEx 差（缺 regimeView/saEx 返回 None，不伪造 0）。"""
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
        for state in REGIME_STATES
        if state in base_regime
    }


def strong_ban_ratio_of(trial: dict[str, Any], base: dict[str, Any]) -> float | None:
    """禁入触发率监控：banStrongA/B=True 的禁入面随 strong 线移动放大/缩小——以
    regimeStateCounts.strong（strong 桶样本量）相对 baseline 的比值度量。
    缺计数或 baseline 桶为 0 → None（fail-visible，不伪造 1.0）。"""
    counts = trial.get("regimeStateCounts") or {}
    base_counts = base.get("regimeStateCounts") or {}
    trial_n = counts.get("strong")
    base_n = base_counts.get("strong")
    if not trial_n or not base_n:
        return None
    return round(trial_n / base_n, 4)


def trial_summary(report: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """单 trial 三窗汇总：saEx/rel + 判定卡 + regimeView 四桶 + 禁入面比值。"""
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
        windows[win] = {
            "saEx": trial_sa,
            "saExRel": rels[win],
            "passHard": pass_hard[win],
            "regimeDelta": regime_delta_of(trial, base or {}),
            "strongBanRatio": strong_ban_ratio_of(trial, base or {}),
            "anchor": anchor_check(win, trial_sa, spec.get("anchor")),
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
        "regimeNote": "C4 四桶附加读数=windows[*].regimeDelta；禁入面=windows[*].strongBanRatio（strong 桶样本量 vs baseline）",
    }


def build_specs(extra_trial_json: str = "") -> list[dict[str, Any]]:
    """baseline（承担三轴默认档）+ 内置 TRIALS（+ --extra-trial 注入，P3-b 精扫补跑）。"""
    specs: list[dict[str, Any]] = [
        {
            "key": "baseline",
            "desc": "当前默认（StrongScore=70 / OverheatSevMin=0.65 / DivergenceSevMin=0.6）",
            "overrides": {},
            "anchor": ANCHOR_BASELINE,
        },
        *TRIALS,
    ]
    if extra_trial_json:
        extra = json.loads(extra_trial_json)
        for spec in extra if isinstance(extra, list) else [extra]:
            spec.setdefault("anchor", None)
            specs.append(spec)
    return specs


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
        print(f"[regime-risk] {window} frames={len(frames)}", file=sys.stderr)
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
        assert_regime_line_order(spec["overrides"])  # 线序预检：含 baseline 与 extra-trial
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[regime-risk] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        result = {**result, "signalTiers": _tiers_of(signals)}
        anchor = anchor_check(window, (result.get("synergy") or {}).get("saEx"), spec.get("anchor"))
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "anchor": anchor, "result": result}
        if anchor.get("checked") and not anchor["match"]:
            _save(report)  # 漂移现场落盘留痕，然后停（方案总纲：配置漂移即停）
            raise AssertionError(
                f"baseline 锚不复现（配置漂移）: {window}/{key} 期望 {anchor['expected']} 实际 {anchor['actual']}"
                f"——检查配置代际/数据窗口后再继续"
            )
        print(
            f"[regime-risk] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = True  # 审计 M3：OOS-2 已被阶段 24/25 部分消费，结论标折扣
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "regime-risk-thresholds.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}  # 帧缓存不落盘
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="regime/risk 核心线位扫描（方案 P3，P3-0 收窄后 12+1 trial）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument("--extra-trial", default="", help="追加 trial：JSON {key,desc,overrides} 或列表（P3-b 精扫注入）")
    args = parser.parse_args()

    validate_trials()
    out_path = Path(args.out) if args.out else REPORT_DIR / "regime-risk-thresholds.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    specs = build_specs(args.extra_trial)

    windows = list(WINDOWS) if args.window == "all" else [args.window]
    for window in windows:
        run_window(window, report, specs)

    summary = {spec["key"]: trial_summary(report, spec) for spec in specs}
    report["summary"] = summary
    # 锚链只统计已跑窗（--window 单窗模式不因未跑窗误报）；漂移即停（方案总纲）
    anchor_chain: dict[str, bool] = {}
    for win in WINDOWS:
        anchor = (((summary.get("baseline") or {}).get("windows") or {}).get(win) or {}).get("anchor") or {}
        if anchor.get("checked"):
            anchor_chain[win] = bool(anchor.get("match"))
    report["anchorChain"] = {"baseline": anchor_chain, "allMatch": all(anchor_chain.values()) if anchor_chain else None}
    _save(report)
    if report["anchorChain"]["allMatch"] is False:
        raise AssertionError(f"baseline 锚不复现（配置漂移）: {report['anchorChain']['baseline']}——按方案总纲停止")
    compact = {
        k: {
            "cardResult": v.get("cardResult"),
            "saExRel": v.get("saExRel"),
            "windows": {
                w: {kk: vv for kk, vv in d.items() if kk in ("saEx", "saExRel", "strongBanRatio", "regimeDelta")}
                for w, d in v.get("windows", {}).items()
            },
        }
        for k, v in summary.items()
    }
    print(json.dumps({"anchorChain": report["anchorChain"], "summary": compact}, ensure_ascii=False, indent=2, default=str))
    print(f"[regime-risk] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
