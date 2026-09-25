# -*- coding: utf-8 -*-
"""Jump 确认阈值扫描 harness（方案 P6-c，观察因子标准，监控型）。

性质声明（方案 P6）：**不是调参案**——Jump 确认阈值是"设计值从未复验"（D-a 推翻
"Jump 事件为 0 无影响"旧口径后，确认阈值面需要重看）。本 harness 判定按**观察因子
标准**（区分度/方向读数），**不做 C1-C3 交易判定卡、不触发 Track 1 交易复核**；
Jump 确认进的是共振维（res）方向票语义（G4：runtime.py:208-252 `_confirm_jump`），
harness 不进投票、不写回默认值、无落默认候选。

trial 组（§P6-c，两单轴各 5 档，默认档由 baseline 承担，8 trial + baseline = 9/窗）：
- jumpConfirmChangeMin：1 / 2 / **3(默认)** / 4 / 5（价格确认：up 需 change ≥x / down ≤−x）；
- jumpConfirmVolumeRatioMin：0.6 / 0.8 / **1.0(默认)** / 1.25 / 1.5（量确认：量比 ≥x）。
交互组合不扫（留 --extra-trial 精扫）。

监控量（每 trial 每窗，方案 P6-c 指定）：
- synergy saEx（+rel vs baseline）；
- res 维 saEx（jump 票所在维，dimension="resonance" h1 S/A 合并 excess 方向精度）；
- unconfirmed 降级率（G4 语义：不满足确认 → direction 降 hold + confirmed=False +
  unconfirmedReasons，**事件保留不删**；降级率 = 降级数 / 需确认数）；
- Jump 票占比重测（D-a 同口径：res voted 且 tierReasons 含 "Jump" 占全体信号；
  **对照 D-a 12-14% 为 fund10 落默认前口径，只作方向对照**）。

锚：baseline 三窗逐位复现 post-fund10 基线锚（2026-09-15 fund10 落默认后）；
pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1）。
**baseline 首跑任一锚不复现 → 立即停止（配置漂移），不继续跑任何 trial**。

**2026-09-15 oos2 smoke 首跑实证发现（消费面断线，收口级证据）**：
全部 8 档 trial 的 syn saEx / res saEx / jumpVoteShare / 降级率逐位一致（= baseline 复刻）。
根因（代码 + 实证双确认，非剂量钝感）：`_confirm_jump` 确认分支只匹配 "up"/"down"
（runtime.py:230-235），而生产 `detect_rank_jumps` 输出 direction ∈ buy/sell/hold
（runtime.py:134/176）——oos2 实测 10936 个带事件 jump（buy 5220 / sell 5716）全部
confirmed=True 走放行分支，**G4 确认门从未实际拦截**。tests/test_confirm_jump.py
全部用 jump("up")/jump("down") 构造（未覆盖真实生产枚举）。两轴在当前引擎消费面下
zero_effect（结构性惰性）；修复属 engine/** 变更，不在本 harness 职责内（只读扫描）。

**2026-09-15 断线已修复（同日 engine/** 变更，用户决策）**：`_confirm_jump` 改按生产枚举
buy/sell 匹配（"up"/"down" 保留为语义别名），G4 确认门自修复起真实生效。**后果**：
- 本报告既有 baseline 锚（ANCHOR_BASELINE）是**断线代际**（门不拦截）的读数；修复后
  重跑 baseline 锚必然不复现并触发 RuntimeError——这是**预期行为变化**（门开始拦截），
  不是配置漂移事故；修复后代际锚需以新 out 路径重录，勿覆盖本报告；
- jump_confirm_stats 的 unconditionalPass 语义由"未核验放行"变为"核验后放行"，
  unconfirmedRate 自修复起真实反映 G4 降级率（监控无需改动，docstring 预留了此演进）。

窗口纪律：决策窗 04-15~07-31 + OOS-1 08-15~31 + OOS-2 09-01~12；FINAL(08-01~08-14)
冻结（assert_not_frozen purpose=scan，含 resume 路径无条件执行）。OOS-2 已被阶段
24/25 部分消费，结论标注"窗口已消费"（M3 折扣）。断线扫描批次全程零默认值改动；
2026-09-15 修复为用户决策的 engine 行为变更（golden 见 L1 台账 §15.7 修复记录）。

用法：
  python -m backend.operations.evaluate_jump_confirm_parameters [--window all]
      [--out <path>] [--extra-trial <JSON>]   （交互组合精扫入口）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")

from backend.operations.diagnose_resonance_vote_structure import classify_resonance
from backend.operations.evaluate_ts_factor_weights import WINDOWS, _rel_improve
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR, evaluate_gate
from backend.operations.optimize_resonance_parameters import sa_excess_of

# 锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后，报告 baseline-anchor-post-fund10.json）；
# pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1，历史报告口径）
# 锚单一事实源（2026-09-25 B-202610 演练落地）：硬编码 fund10 代际冻结锚改为运行时读
# 锚注册表 currentGeneration（gen-2026-10-b202610）——注册表更新后自动跟随（审计 D3）。
from backend.operations.harness_common import baseline_anchor

ANCHOR_BASELINE: dict[str, float] = baseline_anchor()[1]
_OVERRIDE_MISSING = object()

JUMP_CHANGE_DEFAULT = 3.0  # engine/config.py jumpConfirmChangeMin（2026-08-17 G4 默认）
JUMP_VR_DEFAULT = 1.0  # engine/config.py jumpConfirmVolumeRatioMin


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫（review C1）：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻、产出假零效应/假惰性结论——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")


# 两单轴各 4 非默认档（默认档 3.0/1.0 由 baseline 承担；单变量拆分，交互组合留精扫）
JUMP_TRIALS: list[dict[str, Any]] = [
    {"key": "chg_1", "desc": "jumpConfirmChangeMin 3→1（价格确认最松）", "overrides": {"jumpConfirmChangeMin": 1.0}},
    {"key": "chg_2", "desc": "jumpConfirmChangeMin 3→2（价格确认松半档）", "overrides": {"jumpConfirmChangeMin": 2.0}},
    {"key": "chg_4", "desc": "jumpConfirmChangeMin 3→4（价格确认紧半档）", "overrides": {"jumpConfirmChangeMin": 4.0}},
    {"key": "chg_5", "desc": "jumpConfirmChangeMin 3→5（价格确认最紧）", "overrides": {"jumpConfirmChangeMin": 5.0}},
    {"key": "vr_06", "desc": "jumpConfirmVolumeRatioMin 1.0→0.6（量确认最松）", "overrides": {"jumpConfirmVolumeRatioMin": 0.6}},
    {"key": "vr_08", "desc": "jumpConfirmVolumeRatioMin 1.0→0.8（量确认松半档）", "overrides": {"jumpConfirmVolumeRatioMin": 0.8}},
    {"key": "vr_125", "desc": "jumpConfirmVolumeRatioMin 1.0→1.25（量确认紧半档）", "overrides": {"jumpConfirmVolumeRatioMin": 1.25}},
    {"key": "vr_15", "desc": "jumpConfirmVolumeRatioMin 1.0→1.5（量确认最紧）", "overrides": {"jumpConfirmVolumeRatioMin": 1.5}},
]


def build_specs(extra_trial_json: str = "") -> list[dict[str, Any]]:
    """执行序列：baseline（锚 + 默认档承担）+ 8 单轴 trial + --extra-trial 注入（精扫入口）。"""
    specs: list[dict[str, Any]] = [
        {
            "key": "baseline",
            "desc": "当前默认（jumpConfirmChangeMin=3.0 / jumpConfirmVolumeRatioMin=1.0，G4 默认生效）",
            "overrides": {},
            "anchor": ANCHOR_BASELINE,
        },
        *JUMP_TRIALS,
    ]
    if extra_trial_json:
        extra = json.loads(extra_trial_json)
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


def jump_confirm_stats(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """G4 unconfirmed 降级率（runtime.py:208-252 语义，生产枚举 buy/sell）。

    **2026-09-15 P6-c 消费面实证（oos2 smoke 首跑发现，代码行号留痕）**：
    `detect_rank_jumps` 输出 direction ∈ buy/sell/hold（runtime.py:134/176），而
    `_confirm_jump` 的确认分支只匹配 "up"/"down"（runtime.py:230-235）——生产路径带方向
    jump 全部落 `else: ok=True` 放行分支，**确认门从未实际拦截任何 jump**
    （tests/test_confirm_jump.py 全部用 jump("up")/jump("down") 构造，未覆盖真实生产枚举，
    TDD 真实运行环境边界教训实例）。因此本监控：
    - confirmRequired 分母 = 降级样本（confirmed=False；direction 已被 G4 改 hold，不能再按
      direction 识别）+ 带方向放行样本（direction ∈ buy/sell 且 confirmed=True）；
    - unconfirmedRate = 降级数 / 分母（降级=G4 fail-visible：direction 降 hold + 事件保留）；
    - unconditionalPass = 带方向且 confirmed=True——断线代际（2026-09-15 修复前）即
      "未经价格/量核验放行"体量，该值>0 且 unconfirmed=0 时按结构性惰性判读；
      2026-09-15 接线修复后该值为"核验后放行"，unconfirmedRate 真实反映降级率；
    - 本监控无需改动即可跨代际真实反映降级率（docstring 预留的演进已发生）。
    缺 confirmed 字段如实计数（fail-visible），不伪造 0。
    """
    confirm_required = 0
    unconfirmed = 0
    unconditional_pass = 0
    missing_confirmed = 0
    no_jump = 0
    for signal in signals:
        jump = (signal.get("rankTrend") or {}).get("jump")
        if not jump:
            no_jump += 1
            continue
        direction = str(jump.get("direction") or "")
        confirmed = jump.get("confirmed")
        if confirmed is None:
            missing_confirmed += 1
            continue
        if confirmed is False:
            # 降级样本（G4：direction 已同步降 hold + unconfirmedReasons，事件保留）——
            # 不能再靠 direction ∈ buy/sell 识别（direction 已被改成 hold）
            unconfirmed += 1
            confirm_required += 1
        elif direction in ("buy", "sell"):
            unconditional_pass += 1  # 带方向且 confirmed=True：当前引擎下即"未核验放行"体量
            confirm_required += 1
    return {
        "confirmRequired": confirm_required,
        "unconfirmed": unconfirmed,
        "unconfirmedRate": round(unconfirmed / confirm_required, 4) if confirm_required else None,
        "unconditionalPass": unconditional_pass,
        "missingConfirmed": missing_confirmed,
        "noJumpCount": no_jump,
    }


def jump_vote_share(signals: list[dict[str, Any]]) -> float | None:
    """Jump 票占比（D-a 同口径）：res voted 且 tierReasons 含 'Jump' 占全体信号。

    复用 diagnose_resonance_vote_structure.classify_resonance（D-a 投票驱动分解同源），
    避免口径漂移；12-14% 基线为 fund10 落默认前口径，只作方向对照。
    """
    total = len(signals)
    if not total:
        return None
    hits = 0
    for signal in signals:
        obs = (signal.get("rankTrend") or {}).get("resonance") or {}
        _bucket, driver = classify_resonance(obs)
        if driver == "Jump 事件":
            hits += 1
    return round(hits / total, 4)


def _tiers_of(signals: list[dict[str, Any]]) -> list[str]:
    out = []
    for s in signals:
        tier = ((((s.get("rankTrend") or {}).get("observation") or {}).get("synergy") or {}).get("signalTier"))
        out.append(str(tier or "unknown"))
    return out


def _observed_metrics(signals: list[dict[str, Any]], frames: list[dict[str, Any]]) -> dict[str, Any]:
    """从 replay 信号提取 P6-c 监控量（res 维 saEx + G4 降级率 + Jump 票占比）。"""
    from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns

    res_stats = tier_forward_returns(signals, frames, horizon=1, dimension="resonance")
    return {
        "resSaEx": round(sa_excess_of(res_stats), 4) if sa_excess_of(res_stats) is not None else None,
        "resUnknownRate": res_stats.get("unknownRate"),
        "jumpConfirm": jump_confirm_stats(signals),
        "jumpVoteShare": jump_vote_share(signals),
    }


def trial_summary(report: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """单 trial 三窗监控汇总（观察因子标准）：syn/res saEx rel + 降级率 + Jump 票占比。

    verdict 恒为 monitor_only——不做 C1-C3 交易判定卡、不触发 Track 1、不产生落默认候选
    （方案 P6 性质声明）；saExRel 仅作方向读数，与 baseline 漂移大于噪声时人工判读。
    """
    windows: dict[str, Any] = {}
    rels: dict[str, float | None] = {}
    res_rels: dict[str, float | None] = {}
    for win in WINDOWS:
        base = (((report.get(win) or {}).get("trials") or {}).get("baseline") or {}).get("result")
        trial = (((report.get(win) or {}).get("trials") or {}).get(spec["key"]) or {}).get("result")
        if not trial:
            continue
        base_sa = (base or {}).get("synergy", {}).get("saEx")
        trial_sa = trial.get("synergy", {}).get("saEx")
        base_res = (base or {}).get("resSaEx")
        trial_res = trial.get("resSaEx")
        rels[win] = _rel_improve(trial_sa, base_sa)
        res_rels[win] = _rel_improve(trial_res, base_res)
        confirm = trial.get("jumpConfirm") or {}
        windows[win] = {
            "saEx": trial_sa,
            "saExRel": rels[win],
            "passHard": trial.get("synergy", {}).get("passHard"),
            "resSaEx": trial_res,
            "resSaExRel": res_rels[win],
            "unconfirmedRate": confirm.get("unconfirmedRate"),
            "unconfirmedCount": confirm.get("unconfirmed"),
            "confirmRequired": confirm.get("confirmRequired"),
            "unconditionalPass": confirm.get("unconditionalPass"),
            "jumpVoteShare": trial.get("jumpVoteShare"),
            "anchor": anchor_check(win, trial_sa, spec.get("anchor")),
        }
    if not windows:
        return {"verdict": "insufficient_data", "windows": windows}
    return {
        "windows": windows,
        "saExRel": rels,
        "resSaExRel": res_rels,
        "verdict": "monitor_only",
        "note": (
            "观察因子标准（方案 P6 性质声明）：不进投票、不做 C1-C3 判定卡、不触发 Track 1、"
            "不写回默认值；Jump 票占比对照 D-a 12-14% 为 fund10 落默认前口径，只作方向对照；"
            "OOS-2 已被阶段 24/25 部分消费（M3 折扣），结论仅作方向证据。"
            "2026-09-15 消费面实证：_confirm_jump 确认分支只匹配 up/down（runtime.py:230-235），"
            "生产 jump.direction 为 buy/sell（runtime.py:176）——确认门从未拦截；"
            "unconditionalPass>0 且 unconfirmed=0 时，档位逐位一致按结构性惰性（消费面断线）判读"
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
    assert_not_frozen(frames, "scan")  # 无条件执行（含 resume 路径，review I2）
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[jump-confirm] {window} frames={len(frames)}", file=sys.stderr)
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
        print(f"[jump-confirm] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(frames, meta={})
        result = evaluate_gate(config, frames)
        result = {
            **result,
            "signalTiers": _tiers_of(signals),
            **_observed_metrics(signals, frames),  # P6-c 监控量（res 维 + G4 降级率 + Jump 票占比）
        }
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        confirm = result["jumpConfirm"]
        print(
            f"[jump-confirm] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) res(saEx={result['resSaEx']}) "
            f"unconfirmed={confirm['unconfirmed']}/{confirm['confirmRequired']} "
            f"jumpShare={result['jumpVoteShare']} ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)
        if key == "baseline":
            anchor = anchor_check(window, result["synergy"]["saEx"], spec.get("anchor"))
            trials[key]["anchor"] = anchor
            _save(report)
            if anchor.get("checked") and not anchor["match"]:
                raise RuntimeError(
                    f"baseline 锚漂移：{window} saEx={anchor['actual']} != 期望 {anchor['expected']}"
                    f"（post-fund10 锚）——配置漂移，立即停止（后续 trial 未跑）；"
                    f"先核查 engine/config.py 默认值与帧数据代际，再清理报告重跑"
                )


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = True  # 审计 M3
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "jump-confirm-parameters.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}  # 帧缓存不落盘（review I1，同 evaluate_ts_factor_weights 模式）
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Jump 确认阈值扫描（方案 P6-c，观察因子标准，监控型）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument("--extra-trial", default="", help="追加 trial：JSON {key,desc,overrides}（交互组合精扫入口）")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "jump-confirm-parameters.json"
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
    report["anchorChain"] = {
        "baseline": all(
            ((((summary.get("baseline") or {}).get("windows") or {}).get(win) or {}).get("anchor") or {}).get("match") is True
            for win in WINDOWS
        )
    }
    _save(report)
    report.pop("__out__", None)
    print(json.dumps(
        {
            "anchorChain": report["anchorChain"],
            "summary": {
                k: {
                    "verdict": v.get("verdict"),
                    "windows": {
                        w: {kk: vv for kk, vv in d.items() if kk in ("saEx", "saExRel", "resSaEx", "resSaExRel", "unconfirmedRate", "jumpVoteShare", "anchor")}
                        for w, d in v.get("windows", {}).items()
                    },
                }
                for k, v in summary.items()
            },
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    ))
    print(f"[jump-confirm] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
