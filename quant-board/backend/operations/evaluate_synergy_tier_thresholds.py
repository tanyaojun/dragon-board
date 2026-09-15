# -*- coding: utf-8 -*-
"""synergy 总档阈值阶梯扫描 harness（方案 P2，ranktrend-param-gap-scan-plan，两轮制粗扫）。

缺口（方案 P2）：
- ① `tierSynergyVoteStrengths [1.2,1.0,0.8,0.5,1.0,1.0]`（S/A/B/C/D/E 档位强度，config.py:167）
  批 1 参数化后未扫描；
- ② 总档三线 `tierSynergyVoteStrong(2.0)/Weak(1.0)/Reverse(-1.0)` 的 §4.2 结论是**旧 vote 语义**
  （票取方向不取档位）下得出——且实为**两线结论**（Strong 2→3 影响交易但变差、Reverse −1→0
  改档位分布不影响交易；`tierSynergyVoteWeak` 全文无任何记载，连旧语义都没扫过）。
  v4 档位加权 + cs 第 5 维 + 0.75 票权落地后三线均从未复扫。

P2-0 前置消费面核实结论（2026-09-15 审计已完成，记录在案）：
- `tierSynergyVoteStrengths` 在 `_synergy_tier` 中**只乘 res/rank/vp 三票**
  （ranking/volume_price.py:415-418）；cs 票走独立映射 `tierSynergyCsStrengths`
  （:420-422，C/D 档为负票 −0.5/−1.0）；S/A/B 缩放不触及任何维度的 C/D/E 档票。
- **初稿的"数学等价"假设作废**：S/A/B 强度缩放 ≠ 三轴票权缩放（覆盖面不同：票权缩放
  包含 cs 全票与全部档位）；单剂量点零效应不能判子轴冗余（§23.3 真实标准 = 代码消费面
  事实 + 多档逐位零效应）。故 S/A/B/C/D 直接进 5 档粗扫（默认档由 baseline 承担）。
- E 强度**收口免扫**：hard 门早退（volume_price.py:383-389，仅 volumePriceGateMode=soft
  消费），默认门形态下结构性惰性；登记"soft 模式时生效"。本 harness 全部
  VoteStrengths patch 显式写全 6 值并保持 E=index 5=1.0。

与阶段 25 平行方案的协调（用户已裁决未决问题 3：三线复扫，P2 全表 33 trial）：
`ranktrend-dimension-trade-review-cs-strength-proposal.md`（阶段 25 方案 A-D）已扫
`tierSynergyCsStrengths`（13 trial 全 OBSERVE、现值即峰收口），其 §3.1 以"阶段 23 钝感
结论 + 阶梯为门控骨架"为由明确不动三线。**本案复扫三线的依据显式接管该排除理由**：
§4.2 两线结论出自旧 vote 语义，v4 档位加权 + cs 第 5 维 + 0.75 票权落地后未复扫
（Weak 线从未扫过）——"钝感"结论的语义前提已不成立。引用方案 B 结论时注意其 harness
锚为 23.9.1 旧基线（0.1044/0.0918/0.0933），与本案 fund10 锚不同口径。

锚代际：ANCHOR_BASELINE 为 post-fund10 基线锚（2026-09-15 fund10 落默认后）；
pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1 历史口径）。
baseline 首跑任一锚不复现 → 立即停止扫描（配置漂移，总纲"不复现即停"），已产出数据
保留在报告中（fail-visible）。

引擎侧守卫（2026-09-15 主代理已加）：`from_patch` 经 `_validate_tier_constraints` 对
`tierSynergyVoteStrengths` 长度 !=6 直接 ValueError（此前 `_vote` 静默回退旧硬编码
fallback，volume_price.py:405-406，trial 假绿）；三线约束 `reverse <= weak < strong`
由 from_patch fail-fast 兜底（config.py:530-535），本表 32 trial 均已人工核对合法。

trial 表（8 轴 × 4 非默认档 = 32 + baseline = 33，单变量 5 档制，默认档由 baseline 承担）：
  tierSynergyVoteStrong 1.5/1.75/2.25/2.5（默认 2.0）
  tierSynergyVoteWeak 0.5/0.75/1.25/1.5（默认 1.0）
  tierSynergyVoteReverse −1.5/−1.25/−0.75/−0.5（默认 −1.0）
  VoteStrengths[S] 1.0/1.1/1.3/1.4（默认 1.2，index 0）
  VoteStrengths[A] 0.8/0.9/1.1/1.2（默认 1.0，index 1）
  VoteStrengths[B] 0.6/0.7/0.9/1.0（默认 0.8，index 2）
  VoteStrengths[C] 0.0/0.25/0.75/1.0（默认 0.5，index 3；0.0 档=关闭 res/rank/vp 三维
    C 档票，测净贡献方向；cs 维 C 档负票走 tierSynergyCsStrengths 与本轴无关——阶段 25
    方案 B 已扫收口 OBSERVE）
  VoteStrengths[D] 0.5/0.75/1.25/1.5（默认 1.0，index 4）

监控项（每 trial 每窗必出）：
- S/A 档位占比（§23.9 结构下限监控：三轴减权 ≤0.5 时 S/A 塌缩——强度/线位同属该结构面，
  防止单变量扫进塌缩区；triggerRateSA > 0.035 旗标，阶段 22.6 观察线）；
- 档位分布迁移（synergy distribution 的 S/A/B/C/D/E/unknown 计数，evaluate_gate 同源）；
- v_final vs A 线 2 的结构关系读数：evaluate_gate 未输出 vote_sum 分布，不可取——以
  S/A 占比 + 档位分布迁移替代（见 V_FINAL_READOUT_NOTE），若需直接读数须扩 evaluate_gate，
  本案不做。

预期与风险（方案 P2）：可能大范围"逐位一致"（强度变化不跨阈值线）——按结构性惰性收口
并明确记录结构边界（哪些档位强度在哪个线位组合下才活跃）；**但结论只写"当前线位/票权
配置下不活跃"，不引申"子轴冗余"**（§23.3/§23.4 口径）。OOS-2 已被阶段 24/25 部分消费
（M3 折扣，windowsConsumed=True），最终裁决与 9 月全月复验（10 月上旬）同批。
P2-b 精扫（显著档位 × 线位 2 轴小网格 + 与现票权 0.75 组合交互）用 --extra-trial 注入。

判定卡（Track 2，§19.3/§19.6）：C1 decision saEx rel ≥ +3% ∧ C2（OOS ≥1 窗同向为正）
∧ C3（decision passHard 不降）= PASS_CANDIDATE；C4 regime 四桶降幅 ≤0.01 为附加卡
（regimeDelta 每窗输出）。落默认前最后一步必须 Track 1 交易复核（不在本 harness 内）。

用法：
  python -m backend.operations.evaluate_synergy_tier_thresholds [--window all] [--out <path>]
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

# 锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后）；
# pre-fund10 代际锚 = {"decision": 0.1044, "oos1": 0.0918, "oos2": 0.0933}（23.9.1，方案 B harness 口径）
ANCHOR_BASELINE: dict[str, float] = {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}

# 引擎当前默认（config.py:167）；E=index 5=1.0 收口免扫（hard 门早退惰性，soft 模式时生效）
BASE_VOTE_STRENGTHS = [1.2, 1.0, 0.8, 0.5, 1.0, 1.0]

TRIGGER_RATE_FLAG = 0.035  # S+A 触发率旗标（阶段 22.6 观察线）

V_FINAL_READOUT_NOTE = (
    "v_final vs A 线 2 结构关系读数不可取：evaluate_gate 未输出 vote_sum 分布"
    "（§23.9 结构下限以 S/A 占比 + 档位分布迁移替代监控）；若需直接读数须扩 evaluate_gate，本案不做"
)

_OVERRIDE_MISSING = object()


def _assert_overrides_applied(config: Any, overrides: dict[str, Any]) -> None:
    """override 生效性守卫（review C1，范式同款）：from_patch 对未知字段静默忽略（hasattr 无 else），
    字段改名/拼错会静默跑成 baseline 复刻、产出假零效应/假惰性结论——逐键断言。"""
    for key, value in overrides.items():
        actual = getattr(config, key, _OVERRIDE_MISSING)
        if actual is _OVERRIDE_MISSING or actual != value:
            raise AssertionError(f"override 未生效: {key}={value!r}（config 实际={actual!r}）——检查字段名/配置代际")


def _vs_patch(index: int, value: float) -> dict[str, Any]:
    """VoteStrengths trial patch：显式写全 6 值 [S,A,B,C,D,E]，只动自己 index，E=index 5 保持 1.0。

    引擎 2026-09-15 list 形状守卫：len!=6 直接 ValueError（config._validate_tier_constraints）；
    守卫之前 `_vote` 会静默回退旧硬编码 fallback（volume_price.py:405-406），trial 假绿。
    """
    strengths = list(BASE_VOTE_STRENGTHS)
    strengths[index] = value
    return {"tierSynergyVoteStrengths": strengths}


SYNERGY_TIER_TRIALS: list[dict[str, Any]] = [
    # --- 轴 1：tierSynergyVoteStrong（默认 2.0；S/A 分界线，旧语义两线结论之一）---
    {"key": "strong_150", "desc": "VoteStrong 1.5（线下移：A 档易达/S 触发上移）", "overrides": {"tierSynergyVoteStrong": 1.5}},
    {"key": "strong_175", "desc": "VoteStrong 1.75（线下移半档）", "overrides": {"tierSynergyVoteStrong": 1.75}},
    {"key": "strong_225", "desc": "VoteStrong 2.25（线上移半档；旧结论 2→3 变差的近端剂量）", "overrides": {"tierSynergyVoteStrong": 2.25}},
    {"key": "strong_250", "desc": "VoteStrong 2.5（线上移：A 档收紧）", "overrides": {"tierSynergyVoteStrong": 2.5}},
    # --- 轴 2：tierSynergyVoteWeak（默认 1.0；B 线，从未扫过——含旧语义）---
    {"key": "weak_050", "desc": "VoteWeak 0.5（B 线下移：弱买更易达）", "overrides": {"tierSynergyVoteWeak": 0.5}},
    {"key": "weak_075", "desc": "VoteWeak 0.75（B 线下移半档）", "overrides": {"tierSynergyVoteWeak": 0.75}},
    {"key": "weak_125", "desc": "VoteWeak 1.25（B 线上移半档）", "overrides": {"tierSynergyVoteWeak": 1.25}},
    {"key": "weak_150", "desc": "VoteWeak 1.5（B 线上移：弱买收紧）", "overrides": {"tierSynergyVoteWeak": 1.5}},
    # --- 轴 3：tierSynergyVoteReverse（默认 -1.0；D 反向线，旧语义两线结论之一）---
    {"key": "reverse_neg150", "desc": "VoteReverse -1.5（D 线下移：反向判定收紧）", "overrides": {"tierSynergyVoteReverse": -1.5}},
    {"key": "reverse_neg125", "desc": "VoteReverse -1.25（D 线下移半档）", "overrides": {"tierSynergyVoteReverse": -1.25}},
    {"key": "reverse_neg075", "desc": "VoteReverse -0.75（D 线上移半档）", "overrides": {"tierSynergyVoteReverse": -0.75}},
    {"key": "reverse_neg050", "desc": "VoteReverse -0.5（D 线上移：反向判定更易触发）", "overrides": {"tierSynergyVoteReverse": -0.5}},
    # --- 轴 4-8：VoteStrengths[S/A/B/C/D]（res/rank/vp 三票档位强度，E 收口免扫）---
    {"key": "vsS_100", "desc": "VoteStrengths[S] 1.0（S 档减权）", "overrides": _vs_patch(0, 1.0)},
    {"key": "vsS_110", "desc": "VoteStrengths[S] 1.1（S 档减权半档）", "overrides": _vs_patch(0, 1.1)},
    {"key": "vsS_130", "desc": "VoteStrengths[S] 1.3（S 档加权半档）", "overrides": _vs_patch(0, 1.3)},
    {"key": "vsS_140", "desc": "VoteStrengths[S] 1.4（S 档加权）", "overrides": _vs_patch(0, 1.4)},
    {"key": "vsA_080", "desc": "VoteStrengths[A] 0.8（A 档减权）", "overrides": _vs_patch(1, 0.8)},
    {"key": "vsA_090", "desc": "VoteStrengths[A] 0.9（A 档减权半档）", "overrides": _vs_patch(1, 0.9)},
    {"key": "vsA_110", "desc": "VoteStrengths[A] 1.1（A 档加权半档）", "overrides": _vs_patch(1, 1.1)},
    {"key": "vsA_120", "desc": "VoteStrengths[A] 1.2（A 档加权）", "overrides": _vs_patch(1, 1.2)},
    {"key": "vsB_060", "desc": "VoteStrengths[B] 0.6（B 档减权）", "overrides": _vs_patch(2, 0.6)},
    {"key": "vsB_070", "desc": "VoteStrengths[B] 0.7（B 档减权半档）", "overrides": _vs_patch(2, 0.7)},
    {"key": "vsB_090", "desc": "VoteStrengths[B] 0.9（B 档加权半档）", "overrides": _vs_patch(2, 0.9)},
    {"key": "vsB_100", "desc": "VoteStrengths[B] 1.0（B 档加权）", "overrides": _vs_patch(2, 1.0)},
    {"key": "vsC_000", "desc": "VoteStrengths[C] 0.0（关闭 res/rank/vp 三维 C 档票，测净贡献方向；cs 维 C 档负票走 tierSynergyCsStrengths 与本轴无关——阶段 25 方案 B 已扫）", "overrides": _vs_patch(3, 0.0)},
    {"key": "vsC_025", "desc": "VoteStrengths[C] 0.25（C 档减权半档）", "overrides": _vs_patch(3, 0.25)},
    {"key": "vsC_075", "desc": "VoteStrengths[C] 0.75（C 档加权半档）", "overrides": _vs_patch(3, 0.75)},
    {"key": "vsC_100", "desc": "VoteStrengths[C] 1.0（C 档加权）", "overrides": _vs_patch(3, 1.0)},
    {"key": "vsD_050", "desc": "VoteStrengths[D] 0.5（D 档减权）", "overrides": _vs_patch(4, 0.5)},
    {"key": "vsD_075", "desc": "VoteStrengths[D] 0.75（D 档减权半档）", "overrides": _vs_patch(4, 0.75)},
    {"key": "vsD_125", "desc": "VoteStrengths[D] 1.25（D 档加权半档）", "overrides": _vs_patch(4, 1.25)},
    {"key": "vsD_150", "desc": "VoteStrengths[D] 1.5（D 档加权）", "overrides": _vs_patch(4, 1.5)},
]


def anchor_check(window: str, sa_ex: float | None, anchor: dict[str, float] | None) -> dict[str, Any]:
    if anchor is None:
        return {"checked": False}
    expected = anchor[window]
    ok = sa_ex is not None and round(float(sa_ex), 4) == round(float(expected), 4)
    return {"checked": True, "expected": expected, "actual": sa_ex, "match": ok}


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
    """单 trial 三窗汇总：saEx/rel + 判定卡 + §23.9 结构监控 + v_final 读数不可取注明。"""
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
            "tierDistribution": (trial.get("synergy") or {}).get("distribution"),
            "voteSumVsStrongLine": None,  # 不可取，见 V_FINAL_READOUT_NOTE
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
        "vFinalReadoutNote": V_FINAL_READOUT_NOTE,
        "structureNote": "逐位一致 = 结构性惰性：结论限定'当前线位/票权配置下不活跃'，不引申子轴冗余（§23.3/§23.4）",
    }


def frames_entry(report: dict[str, Any], window: str) -> list[dict[str, Any]]:
    cache = report.get("__frames__") or {}
    if window not in cache:
        from backend.operations.optimize_resonance_parameters import load_frames

        start, end = WINDOWS[window]
        cache[window] = load_frames(start, end)
        report["__frames__"] = cache
    return cache[window]


def anchor_chain_of(summary: dict[str, Any]) -> dict[str, Any]:
    """baseline 锚链汇总：只对**已跑窗口**断言逐位 match。

    单窗/渐进（resume）模式下未跑窗口无锚证据——按全三窗 all() 断言会把单窗跑误报成
    "锚不复现"（false 信号，违反 fail-visible）；窗口内锚不符仍如实判 False。
    逐窗即时守卫在 run_window 内（baseline 首跑任一锚不复现直接 SystemExit 停止）。
    """
    windows = (summary.get("baseline") or {}).get("windows") or {}
    ran = [w for w in WINDOWS if windows.get(w)]
    return {
        "ranWindows": ran,
        "baseline": bool(ran) and all(((windows.get(win) or {}).get("anchor") or {}).get("match") is True for win in ran),
    }


def run_window(window: str, report: dict[str, Any], specs: list[dict[str, Any]] | None = None) -> None:
    from backend.analysis.ranktrend.engine import RankTrendConfig
    from backend.optimization.data_windows import assert_not_frozen

    start, end = WINDOWS[window]
    entry = report.setdefault(window, {})
    frames = frames_entry(report, window)
    assert_not_frozen(frames, "scan")  # 无条件执行（含 resume 路径，review I2，范式同款）
    if "window" not in entry:
        entry["window"] = {"start": start, "end": end, "frameCount": len(frames)}
        print(f"[synergy-tier] {window} frames={len(frames)}", file=sys.stderr)
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
            {
                "key": "baseline",
                "desc": "当前默认（三线 2.0/1.0/-1.0 + VoteStrengths [1.2,1.0,0.8,0.5,1.0,1.0]）",
                "overrides": {},
                "anchor": ANCHOR_BASELINE,
            },
            *SYNERGY_TIER_TRIALS,
        ]
    for spec in specs:
        key = spec["key"]
        if key in trials:
            print(f"[skip] {window}/{key} (cached)", file=sys.stderr)
            continue
        print(f"[synergy-tier] {window} {key} {spec['overrides']} ...", file=sys.stderr)
        t0 = time.time()
        config = RankTrendConfig.from_patch(spec["overrides"])
        _assert_overrides_applied(config, spec["overrides"])
        # evaluate_gate 内部自行 replay（flipRates/regimeView/synergy 统计单次产出）；
        # 本 harness 无 B2 等价对照对（P2-0 已作废），不需 signal 级 signalTiers
        result = evaluate_gate(config, frames)
        trials[key] = {"desc": spec["desc"], "overrides": spec["overrides"], "result": result}
        if key == "baseline" and spec.get("anchor"):
            # 总纲"不复现即停"：baseline 首跑任一锚不复现 → 配置漂移，立即停止扫描
            check = anchor_check(window, result["synergy"]["saEx"], spec["anchor"])
            trials[key]["baselineAnchorCheck"] = check
            if not check["match"]:
                _save(report)
                raise SystemExit(
                    f"[synergy-tier] baseline 锚不复现：{window} 期望 {check['expected']} "
                    f"实际 {check['actual']}——配置漂移，扫描停止（已产出数据保留在报告中）"
                )
        print(
            f"[synergy-tier] {window} {key} -> syn(saEx={result['synergy']['saEx']} "
            f"pass={result['synergy']['passHard']}) ({round(time.time() - t0, 1)}s)",
            file=sys.stderr,
        )
        _save(report)


def _save(report: dict[str, Any]) -> None:
    report["generatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["windowsConsumed"] = True  # 审计 M3：OOS-2 已被阶段 24/25 部分消费
    out_path = Path(report["__out__"]) if report.get("__out__") else REPORT_DIR / "synergy-tier-thresholds.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: v for k, v in report.items() if k not in ("__out__", "__frames__")}  # 帧缓存不落盘（review I1，范式同款）
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="synergy 总档阈值阶梯扫描（方案 P2，两轮制粗扫 33 trial）")
    parser.add_argument("--window", default="all", choices=["decision", "oos1", "oos2", "all"])
    parser.add_argument("--out", default="")
    parser.add_argument("--extra-trial", default="", help="追加 trial：JSON {key,desc,overrides}（P2-b 线位×档位小网格注入）")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else REPORT_DIR / "synergy-tier-thresholds.json"
    report: dict[str, Any] = {}
    if out_path.exists():
        report = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"[resume] cached windows: {[k for k in report if k in WINDOWS]}", file=sys.stderr)
    report["__out__"] = str(out_path)

    specs: list[dict[str, Any]] = [
        {
            "key": "baseline",
            "desc": "当前默认（三线 2.0/1.0/-1.0 + VoteStrengths [1.2,1.0,0.8,0.5,1.0,1.0]）",
            "overrides": {},
            "anchor": ANCHOR_BASELINE,
        },
        *SYNERGY_TIER_TRIALS,
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
    report["anchorChain"] = {**anchor_chain_of(summary), "vFinalReadoutNote": V_FINAL_READOUT_NOTE}
    _save(report)
    report.pop("__out__", None)
    print(
        json.dumps(
            {
                "anchorChain": report["anchorChain"],
                "summary": {
                    k: {
                        "cardResult": v.get("cardResult"),
                        "windows": {
                            w: {kk: vv for kk, vv in d.items() if kk in ("saEx", "saExRel", "triggerRateSA", "triggerFlag", "tierDistribution")}
                            for w, d in v.get("windows", {}).items()
                        },
                    }
                    for k, v in summary.items()
                },
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    print(f"[synergy-tier] report -> {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
