# -*- coding: utf-8 -*-
"""P3-0 前置活跃度诊断（只读，ranktrend-param-gap-scan-plan 方案 P3，2026-09-15）。

两项诊断（方案 P3-0，结论决定 P3-a 扫描范围与 trial 总量）：
1. regime 三线（regimeStrongScore/NormalScore/WeakScore，默认 70/50/30）各 −10/+10
   单变量扰动（6 trial + baseline）：统计信号级 regime 四态（strong/normal/weak/retreat）
   分布迁移 + candidateTier 档位赋值迁移量。判据：某线任一方向移动导致 <1% 档位赋值
   迁移 → 判惰性免扫（§12.3 α 平滑同款钝感形态）；迁移量读数全部留痕。
2. risk 五门触发率现状（默认配置）：riskOverheatSellMin(70)/riskOverheatHoldMin(45)/
   riskDivergenceSellMin(65)/riskDivergenceHoldMin(40)/riskSynergyOverheatSevMin(0.65)
   （div_sev riskSynergyDivergenceSevMin(0.6) 视情况）——各门触发信号占比/触发帧占比/
   涉及股票数。"基本不触发"的门判结构性惰性（§23.4 HighRiskPressureMin 形态；注意原文
   口径：pressure 分支是唯一活跃 veto 路径、有读数，非"从不触发"），并按 §23.7 登记
   重扫触发条件。

消费面事实（2026-09-15 只读核查，与触发率互为印证；以源码为准）：
- risk["overheat"/"divergence"]["signal"]（Sell/Hold 四线的唯一输出）全后端唯一消费方
  为 backend/core/backtest/execution.py:1441 回测展示文本（"风险：过热=…"）——信号决策
  面（candidateTier/finalSignal/confidence）零消费；severity 由 riskOverheatOffset/Scale
  与 stage 乘数决定，不经 Sell/Hold 线（trend/risk.py:60-68）。
- risk["synergy"]（over_sev>=riskSynergyOverheatSevMin AND div_sev>=riskSynergyDivergenceSevMin）
  经 decisionRiskPenaltyWeights[2] 进置信度惩罚（engine/runtime.py:312）——决策面活跃。
- regime state 经 compose_analysis_candidate_tier 环境门（banStrongA/B、retreat 禁入）
  影响候选档位（engine/runtime.py:783-796/826/835）；replay 默认 regimeScoreEmaAlpha=1.0
  直通、hysteresis 关，state 由三线直接判定（trend/risk.py:164-169；RegimeSmoother 直通
  返回原 dict）。regime 不进 analyze_risk/analyze_cycle——risk 门读数应跨 7 trial 恒定，
  脚本做一致性核对，漂移即如实输出（隐藏耦合信号）。

窗口纪律：决策窗 2026-04-15~07-31（WINDOWS["decision"]，从 evaluate_ts_factor_weights
import，禁止复制日期字面量）；assert_not_frozen 守卫（FINAL 08-01~08-14 冻结）。

用法：
  python backend/operations/diagnose_regime_risk_activity.py [--smoke] [--out <path>]
  断点续跑：每 trial 完成即写入缓存（data/reports/regime-risk-activity-cache.json），
  重跑自动跳过已完成 trial；正式报告落 data/reports/regime-risk-activity.json。

fail-visible：字段缺失/统计退化/键对齐缺口/门读数跨 trial 漂移均如实输出，不伪造 0。
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, r"D:\dragon-board\quant-board")
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.optimize_gate_denoise_parameters import REPORT_DIR
from backend.operations.optimize_resonance_parameters import load_frames
from backend.optimization.data_windows import assert_not_frozen

SMOKE_FRAME_LIMIT = 60
STATE_ORDER = ("strong", "normal", "weak", "retreat")
# 方案 P3-0 判据：任一方向 ±10 扰动档位赋值迁移 >=1% → 该线活跃；两方向均 <1% → 惰性免扫
INACTIVE_MIGRATION_THRESHOLD = 0.01
# risk 门"基本不触发"判据：信号级触发率 <0.5%（读数留痕供复核，不静默收口）
RARE_TRIGGER_THRESHOLD = 0.005
LOW_TRIGGER_THRESHOLD = 0.02
SINGLE_TRIAL_WARN_SEC = 600  # 单 trial 超时警戒线（10 分钟，任务预算口径）

REGIME_LINES = ("regimeStrongScore", "regimeNormalScore", "regimeWeakScore")

GATE_NOTES = {
    "overheatScore_ge_SellMin": "riskOverheatSellMin 纯分数线（overheat.score>=线，不含 stage 条件）",
    "overheatSignal_sell": "overheat 完整 sell 门（score>=SellMin 且 stage∈crowded/reversal，risk.py:64）",
    "overheatScore_ge_HoldMin": "riskOverheatHoldMin 分数线（signal∈sell/hold）",
    "divergenceScore_ge_SellMin": "riskDivergenceSellMin 分数线（risk.py:65）",
    "divergenceScore_ge_HoldMin": "riskDivergenceHoldMin 分数线",
    "overheatSev_ge_SynergyMin": "riskSynergyOverheatSevMin 单边（over_sev>=线；severity 进决策面）",
    "divergenceSev_ge_SynergyMin": "riskSynergyDivergenceSevMin 单边（div_sev>=线；视情况补扫轴）",
    "synergyGate_both": "risk.synergy 双门同触发（risk.py:67，经 decisionRiskPenaltyWeights[2] 进置信度）",
    "pressure_ge_reversalMin": "对照读数：pressure>=decisionReversalPressureMin（§23.4 唯一活跃 veto 路径参照，非扫描轴）",
}

PLAN_REFERENCES = {  # 方案文档引用值（出人处以源码为准并在报告标注）
    "regimeStrongScore": 70, "regimeNormalScore": 50, "regimeWeakScore": 30,
    "riskOverheatSellMin": 70, "riskOverheatHoldMin": 45,
    "riskDivergenceSellMin": 65, "riskDivergenceHoldMin": 40,
    "riskSynergyOverheatSevMin": 0.65, "riskSynergyDivergenceSevMin": 0.6,
}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    return None


def trial_specs() -> list[dict[str, Any]]:
    c = RankTrendConfig()
    specs: list[dict[str, Any]] = [{"key": "baseline", "desc": "默认配置", "patch": {}}]
    for name in REGIME_LINES:
        dv = float(getattr(c, name))
        specs.append({"key": f"{name}-10", "desc": f"{name} {dv:g}->{dv - 10:g}", "patch": {name: dv - 10}})
        specs.append({"key": f"{name}+10", "desc": f"{name} {dv:g}->{dv + 10:g}", "patch": {name: dv + 10}})
    return specs


def make_config(patch: dict[str, Any]) -> RankTrendConfig:
    """from_patch 构造 + 逐键断言 override 生效（from_patch 对未知字段静默忽略——防假诊断）
    + 线序断言（方案预检纪律 2：from_patch 对三线与 Sell/Hold 顺序无校验，乱序静默退化）。"""
    cfg = RankTrendConfig.from_patch(patch)
    for key, value in patch.items():
        if not hasattr(cfg, key):
            raise AssertionError(f"from_patch 静默忽略未知字段 {key!r}（假诊断防护中断）")
        actual = getattr(cfg, key)
        if actual != value:
            raise AssertionError(f"override 未生效 {key}: 期望 {value!r} 实际 {actual!r}")
    if not (cfg.regimeStrongScore > cfg.regimeNormalScore > cfg.regimeWeakScore):
        raise AssertionError(
            f"regime 三线乱序：Strong={cfg.regimeStrongScore} Normal={cfg.regimeNormalScore} Weak={cfg.regimeWeakScore}"
        )
    if not (cfg.riskOverheatSellMin > cfg.riskOverheatHoldMin):
        raise AssertionError(f"riskOverheat 乱序：Sell={cfg.riskOverheatSellMin} Hold={cfg.riskOverheatHoldMin}")
    if not (cfg.riskDivergenceSellMin > cfg.riskDivergenceHoldMin):
        raise AssertionError(f"riskDivergence 乱序：Sell={cfg.riskDivergenceSellMin} Hold={cfg.riskDivergenceHoldMin}")
    return cfg


def _quantile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return round(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac, 2)


def collect_stats(signals: list[dict[str, Any]], cfg: RankTrendConfig) -> dict[str, Any]:
    total = len(signals)
    if total == 0:
        return {"totalSignals": 0, "degenerate": "空信号集（全源无信号，fail-visible）"}
    state_counts: Counter = Counter()
    frame_state: dict[str, str] = {}
    tier_counts: Counter = Counter()
    action_counts: Counter = Counter()
    stage_counts: Counter = Counter()
    scores: list[float] = []
    missing: Counter = Counter()
    gates = {name: {"signals": 0, "frames": set(), "codes": set()} for name in GATE_NOTES}

    for s in signals:
        sid = str(s.get("snapshotId") or "")
        code = str(s.get("code") or "")
        state_counts[str(s.get("regime"))] += 1
        frame_state[sid] = str(s.get("regime"))
        tier_counts[str(s.get("candidateTier"))] += 1
        action_counts[str(s.get("action"))] += 1
        stage_counts[str(s.get("stage"))] += 1

        rt = s.get("rankTrend") or {}
        regime_data = (rt.get("strategy") or {}).get("regime") or {}
        score = _num(regime_data.get("score"))
        if score is None:
            missing["regimeScore"] += 1
        else:
            scores.append(score)

        risk = rt.get("risk")
        if not isinstance(risk, dict):
            missing["risk"] += 1
            continue
        oh = risk.get("overheat") or {}
        dv = risk.get("divergence") or {}
        oh_score = _num(oh.get("score"))
        oh_sev = _num(oh.get("severity"))
        dv_score = _num(dv.get("score"))
        dv_sev = _num(dv.get("severity"))
        pressure = _num(risk.get("pressure"))
        oh_sig = str(oh.get("signal") or "")
        dv_sig = str(dv.get("signal") or "")
        synergy = risk.get("synergy")
        if oh_score is None or dv_score is None:
            missing["riskScores"] += 1
            continue

        def _hit(name: str, cond: bool) -> None:
            if cond:
                g = gates[name]
                g["signals"] += 1
                g["frames"].add(sid)
                g["codes"].add(code)

        _hit("overheatScore_ge_SellMin", oh_score >= cfg.riskOverheatSellMin)
        _hit("overheatSignal_sell", oh_sig == "sell")
        _hit("overheatScore_ge_HoldMin", oh_score >= cfg.riskOverheatHoldMin)
        _hit("divergenceScore_ge_SellMin", dv_score >= cfg.riskDivergenceSellMin)
        _hit("divergenceScore_ge_HoldMin", dv_score >= cfg.riskDivergenceHoldMin)
        _hit("overheatSev_ge_SynergyMin", oh_sev is not None and oh_sev >= cfg.riskSynergyOverheatSevMin)
        _hit("divergenceSev_ge_SynergyMin", dv_sev is not None and dv_sev >= cfg.riskSynergyDivergenceSevMin)
        _hit("synergyGate_both", synergy == 1)
        _hit("pressure_ge_reversalMin", pressure is not None and pressure >= cfg.decisionReversalPressureMin)

    scores.sort()
    frame_total = len(frame_state)
    gate_summary: dict[str, Any] = {}
    for name, g in gates.items():
        gate_summary[name] = {
            "note": GATE_NOTES[name],
            "signalCount": g["signals"],
            "signalRate": round(g["signals"] / total, 6),
            "frameCount": len(g["frames"]),
            "frameRate": round(len(g["frames"]) / frame_total, 6) if frame_total else None,
            "stockCount": len(g["codes"]),
        }
    return {
        "totalSignals": total,
        "totalFramesWithSignals": frame_total,
        "stateDistSignal": {st: state_counts.get(st, 0) for st in STATE_ORDER}
        | {"other": sum(v for k, v in state_counts.items() if k not in STATE_ORDER)},
        "stateDistFrame": {st: sum(1 for v in frame_state.values() if v == st) for st in STATE_ORDER},
        "statePctSignal": {
            st: round(state_counts.get(st, 0) / total * 100, 3)
            for st in STATE_ORDER
        },
        "tierDist": dict(tier_counts),
        "actionDist": dict(action_counts),
        "stageDist": dict(stage_counts),
        "scoreDist": {
            "min": round(scores[0], 2) if scores else None,
            "p10": _quantile(scores, 0.10),
            "p25": _quantile(scores, 0.25),
            "p50": _quantile(scores, 0.50),
            "p75": _quantile(scores, 0.75),
            "p90": _quantile(scores, 0.90),
            "max": round(scores[-1], 2) if scores else None,
        },
        "gates": gate_summary,
        "missing": dict(missing),
    }


def encode_bykey(signals: list[dict[str, Any]]) -> dict[str, str]:
    """信号对齐键 -> "state,tier"（trial 间迁移统计用；体积换续跑能力）。"""
    out: dict[str, str] = {}
    for s in signals:
        out[f"{s.get('snapshotId')}|{s.get('code')}"] = f"{s.get('regime')},{s.get('candidateTier')}"
    return out


def migration_stats(base_bykey: dict[str, str], trial_bykey: dict[str, str]) -> dict[str, Any] | None:
    keys = set(base_bykey) & set(trial_bykey)
    n = len(keys)
    if n == 0:
        return None
    state_moved = 0
    tier_moved = 0
    state_matrix: Counter = Counter()
    tier_matrix: Counter = Counter()
    for k in keys:
        bs, bt = base_bykey[k].split(",")
        ts, tt = trial_bykey[k].split(",")
        if bs != ts:
            state_moved += 1
            state_matrix[f"{bs}->{ts}"] += 1
        if bt != tt:
            tier_moved += 1
            tier_matrix[f"{bt}->{tt}"] += 1
    return {
        "aligned": n,
        "onlyInBaseline": len(base_bykey) - n,
        "onlyInTrial": len(trial_bykey) - n,
        "stateMigrationRate": round(state_moved / n, 6),
        "tierMigrationRate": round(tier_moved / n, 6),
        "stateMigrationMatrix": dict(state_matrix.most_common()),
        "tierMigrationMatrix": dict(tier_matrix.most_common()),
    }


def state_dist_delta(base_stats: dict[str, Any], trial_stats: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for st in STATE_ORDER:
        b = float(base_stats["statePctSignal"].get(st) or 0.0)
        t = float(trial_stats["statePctSignal"].get(st) or 0.0)
        out[st] = {"baselinePct": b, "trialPct": t, "deltaPctPts": round(t - b, 3)}
    out["totalSignals"] = {"baseline": base_stats["totalSignals"], "trial": trial_stats["totalSignals"]}
    return out


def build_report(
    cache: dict[str, Any],
    prefix: str,
    win: tuple[str, str],
    frame_count: int,
    field_truth: dict[str, Any],
    smoke: bool,
    elapsed_by_trial: dict[str, Any],
) -> dict[str, Any]:
    cfg = RankTrendConfig()
    base_key = f"{prefix}baseline"
    base = cache["trials"].get(base_key)
    if not base:
        raise RuntimeError(f"baseline 缓存缺失（{base_key}），无法汇总")
    base_stats = base["stats"]
    base_bykey = base["byKey"]

    # ── 诊断项 1：regime 三线 ±10 迁移 ──
    line_reports: dict[str, Any] = {}
    for line in REGIME_LINES:
        dirs: dict[str, Any] = {}
        for sign, skey in (("minus10", f"{prefix}{line}-10"), ("plus10", f"{prefix}{line}+10")):
            t = cache["trials"].get(skey)
            if not t:
                dirs[sign] = {"trialKey": skey, "missing": True}
                continue
            mig = migration_stats(base_bykey, t["byKey"])
            tmr = mig["tierMigrationRate"] if mig else None
            dirs[sign] = {
                "trialKey": skey,
                "patch": t["patch"],
                "desc": t["desc"],
                "stateDistDelta": state_dist_delta(base_stats, t["stats"]),
                "migration": mig,
                "tierMigrationRate": tmr,
                "verdict": (
                    "活跃" if (tmr is not None and tmr >= INACTIVE_MIGRATION_THRESHOLD)
                    else "惰性（<1% 档位赋值迁移）" if tmr is not None
                    else "无法判定（键对齐为零）"
                ),
            }
        rates = [d.get("tierMigrationRate") for d in dirs.values() if isinstance(d, dict)]
        active = any(r is not None and r >= INACTIVE_MIGRATION_THRESHOLD for r in rates)
        line_reports[line] = {
            "dirs": dirs,
            "verdict": "活跃" if active else "惰性免扫",
            "judgeRule": (
                f"任一方向 ±10 扰动 candidateTier 赋值迁移率 >= {INACTIVE_MIGRATION_THRESHOLD:.0%} 即活跃；"
                "两方向均 <1% 判惰性免扫（方案 P3-0，§12.3 α 平滑同款钝感形态）；读数留痕"
            ),
        }

    # ── 诊断项 2：risk 五门触发率（baseline 现状）──
    gate_reports: dict[str, Any] = {}
    consumption_facts = {
        "overheatScore_ge_SellMin": "signal 唯一消费方=core/backtest/execution.py:1441 展示文本；决策面零消费",
        "overheatSignal_sell": "同上（含 stage 条件的完整门）",
        "overheatScore_ge_HoldMin": "同上",
        "divergenceScore_ge_SellMin": "同上",
        "divergenceScore_ge_HoldMin": "同上",
        "overheatSev_ge_SynergyMin": "severity 经 decisionRiskPenaltyWeights[0] 进置信度（runtime.py:312）——决策面活跃",
        "divergenceSev_ge_SynergyMin": "severity 经 decisionRiskPenaltyWeights[1] 进置信度 + A_MAIN 档 money_risk 门（runtime.py:479）——决策面活跃",
        "synergyGate_both": "risk.synergy 经 decisionRiskPenaltyWeights[2] 进置信度（runtime.py:312）——决策面活跃",
        "pressure_ge_reversalMin": "pressure 分支（lifecycle.py:231 + runtime.py:313/459-482）——§23.4 唯一活跃 veto 路径参照",
    }
    rescan_hints = {
        "overheatScore_ge_SellMin": "重扫触发条件（§23.7）：risk.overheat/divergence signal 字段获得决策面消费方，或 severity 计算链改动改为经 Sell/Hold 线",
        "overheatSignal_sell": "同上",
        "overheatScore_ge_HoldMin": "同上",
        "divergenceScore_ge_SellMin": "同上",
        "divergenceScore_ge_HoldMin": "同上",
        "overheatSev_ge_SynergyMin": "重扫触发条件（§23.7）：synergy 双门进决策面的权重/口径改动，或 severity 合成链（Offset/Scale/stage 乘数）改动",
        "divergenceSev_ge_SynergyMin": "同上",
        "synergyGate_both": "同上",
        "pressure_ge_reversalMin": "参照读数：非扫描轴",
    }
    for gname, g in base_stats["gates"].items():
        rate = float(g["signalRate"])
        if rate < RARE_TRIGGER_THRESHOLD:
            verdict = "基本不触发 → 结构性惰性候选（§23.4 HighRiskPressureMin 形态）"
        elif rate < LOW_TRIGGER_THRESHOLD:
            verdict = "低频触发"
        else:
            verdict = "活跃"
        gate_reports[gname] = {
            "stats": g,
            "verdict": verdict,
            "judgeRule": f"信号级触发率 <{RARE_TRIGGER_THRESHOLD:.1%} 判基本不触发（结构性惰性候选）；<{LOW_TRIGGER_THRESHOLD:.0%} 低频",
            "consumptionFact": consumption_facts.get(gname),
            "rescanTrigger": rescan_hints.get(gname),
        }

    # ── risk 门读数跨 trial 一致性核对（regime 不进 risk 链，理论上恒定）──
    # prefix 为空（正式模式）时排除 "smoke:" 前缀条目——smoke 与正式帧窗口不同，
    # 门读数天然不同，混入比对会产生假阳性漂移警告。
    def _same_session(key: str) -> bool:
        if prefix:
            return key.startswith(prefix)
        return ":" not in key

    drift: dict[str, Any] = {}
    base_gates = base_stats["gates"]
    for key, t in cache["trials"].items():
        if not _same_session(key) or key == base_key:
            continue
        tg = (t.get("stats") or {}).get("gates") or {}
        diffs = {g: (base_gates[g]["signalCount"], tg.get(g, {}).get("signalCount")) for g in base_gates if tg.get(g, {}).get("signalCount") != base_gates[g]["signalCount"]}
        if diffs:
            drift[key] = diffs
    if drift:
        print(f"[p3-0][WARN] risk 门读数跨 trial 漂移（隐藏耦合，fail-visible）：{json.dumps(drift, ensure_ascii=False)}", file=sys.stderr)

    # ── P3-a 扫描范围建议 ──
    active_lines = [ln for ln, r in line_reports.items() if r["verdict"] == "活跃"]
    sev_active = gate_reports["overheatSev_ge_SynergyMin"]["stats"]["signalRate"] >= RARE_TRIGGER_THRESHOLD
    div_sev_active = gate_reports["divergenceSev_ge_SynergyMin"]["stats"]["signalRate"] >= RARE_TRIGGER_THRESHOLD
    estimated = len(active_lines) * 4  # 5 档制：默认档由 baseline 承担，每线 4 非默认档
    if sev_active:
        estimated += 4
    if div_sev_active:
        estimated += 4
    p3a_scope = {
        "regimeLinesActive": active_lines,
        "regimeLinesSkip": [ln for ln in REGIME_LINES if ln not in active_lines],
        "riskSellHoldLines": "四线（riskOverheatSellMin/HoldMin、riskDivergenceSellMin/HoldMin）消费面证据=信号决策面零消费（唯一消费为回测展示文本）——建议按 §23.3 A 组 zero_effect 模式收口免扫，登记重扫触发条件；若按保守口径仅看触发率，以 gate_reports 读数为准",
        "riskSynergyOverheatSevMin": ("触发率非零，决策面活跃，保扫 4 档" if sev_active else "触发率读数=基本不触发，结合决策面消费事实由用户裁决是否保扫"),
        "riskSynergyDivergenceSevMin": ("单边触发率非零，视方案『视活跃度补』口径保扫 4 档" if div_sev_active else "单边触发率读数低，建议随 overheat 侧同批裁决"),
        "estimatedTrials": estimated,
        "estimateBasis": "5 档制每活跃线 4 个非默认档（baseline 承担默认档）；方案原文『9 线位全活跃上限 37 trial』为方案口径，本读数按 4/线重算",
        "capNote": "方案预期砍后 <=25 trial；本读数据此核对",
    }

    return {
        "meta": {
            "script": "backend/operations/diagnose_regime_risk_activity.py",
            "plan": "ranktrend-param-gap-scan-plan.md 方案 P3-0 前置活跃度诊断（只读）",
            "window": {"start": win[0], "end": win[1], "frameCount": frame_count, "source": "evaluate_ts_factor_weights.WINDOWS['decision']"},
            "smoke": smoke,
            "frozenGuard": "assert_not_frozen(frames, purpose='scan') 已通过",
            "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "judgeRules": {
                "regimeInactive": f"±10 扰动档位赋值迁移率两方向均 <{INACTIVE_MIGRATION_THRESHOLD:.0%} → 惰性免扫",
                "riskRare": f"信号级触发率 <{RARE_TRIGGER_THRESHOLD:.1%} → 基本不触发（结构性惰性候选，§23.4 形态）",
                "singleTrialWarnSec": SINGLE_TRIAL_WARN_SEC,
            },
            "fieldTruth": field_truth,
            "elapsedByTrial": elapsed_by_trial,
        },
        "baseline": {
            "desc": base["desc"],
            "stateDistSignal": base_stats["stateDistSignal"],
            "stateDistFrame": base_stats["stateDistFrame"],
            "statePctSignal": base_stats["statePctSignal"],
            "tierDist": base_stats["tierDist"],
            "actionDist": base_stats["actionDist"],
            "stageDist": base_stats["stageDist"],
            "scoreDist": base_stats["scoreDist"],
            "gates": base_stats["gates"],
            "missing": base_stats["missing"],
            "totalSignals": base_stats["totalSignals"],
            "totalFramesWithSignals": base_stats["totalFramesWithSignals"],
        },
        "regimeLineTrials": line_reports,
        "riskGateStats": gate_reports,
        "riskGateDriftAcrossTrials": drift,
        "p3aScope": p3a_scope,
    }


def build_field_truth(cfg: RankTrendConfig) -> dict[str, Any]:
    truth: dict[str, Any] = {}
    mismatch = []
    for name, plan_val in PLAN_REFERENCES.items():
        src = float(getattr(cfg, name))
        truth[name] = {"sourceDefault": src, "planReference": plan_val, "match": math.isclose(src, float(plan_val))}
        if not truth[name]["match"]:
            mismatch.append(name)
    truth["batch3Range"] = "config.py:192-251（批 3：risk 阶梯 34 项 + regime 打分 23 项 = 57 项）"
    truth["mismatch"] = mismatch
    truth["regimeStateJudge"] = "trend/risk.py:164-169（strong>=StrongScore / normal>=NormalScore / weak>=WeakScore / retreat）；RegimeSmoother 默认 alpha=1.0 直通（engine/runtime.py:1034-1051）"
    truth["regimeTierGate"] = "compose_analysis_candidate_tier 环境门（engine/runtime.py:783-796/826/835）：strong→禁 A/B（banStrongA/B=True）、retreat→禁 A/B；weak 默认不禁"
    return truth


def main() -> int:
    parser = argparse.ArgumentParser(description="P3-0 前置活跃度诊断（regime 三线 ±10 迁移 + risk 五门触发率，只读）")
    parser.add_argument("--smoke", action="store_true", help=f"决策窗前 {SMOKE_FRAME_LIMIT} 帧快速全链路验证（输出独立报告）")
    parser.add_argument("--out", default="", help="报告输出路径（默认 data/reports/regime-risk-activity.json）")
    args = parser.parse_args()

    cfg = RankTrendConfig()
    field_truth = build_field_truth(cfg)
    if field_truth["mismatch"]:
        print(f"[p3-0][WARN] 方案引用与源码默认值不一致：{field_truth['mismatch']}（以源码为准）", file=sys.stderr)

    win = WINDOWS["decision"]
    t0 = time.time()
    frames = load_frames(*win)
    print(f"[p3-0] 决策窗 {win[0]}~{win[1]} 帧加载={len(frames)}（{time.time() - t0:.0f}s）", file=sys.stderr)
    if not frames:
        print("[p3-0] 帧加载为空 — aborting（全源无数据）", file=sys.stderr)
        return 1
    assert_not_frozen(frames, "scan")
    if args.smoke:
        frames = frames[:SMOKE_FRAME_LIMIT]
        print(f"[p3-0] smoke 模式：截断前 {len(frames)} 帧验证全链路", file=sys.stderr)

    prefix = "smoke:" if args.smoke else ""
    cache_path = REPORT_DIR / "regime-risk-activity-cache.json"
    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            print(f"[p3-0] 缓存命中 trial：{[k for k in cache.get('trials', {}) if k.startswith(prefix)]}", file=sys.stderr)
        except Exception as exc:
            print(f"[p3-0][WARN] 缓存文件损坏，忽略重建：{exc}", file=sys.stderr)
            cache = {}
    trials = cache.setdefault("trials", {})

    specs = trial_specs()
    for spec in specs:
        key = prefix + spec["key"]
        if key in trials:
            print(f"[skip] {key}（缓存命中）", file=sys.stderr)
            continue
        trial_cfg = make_config(spec["patch"])
        engine = RankTrendPythonEngine(config=trial_cfg)
        t1 = time.time()
        signals = engine.replay(frames, meta={})
        dt = time.time() - t1
        stats = collect_stats(signals, trial_cfg)
        trials[key] = {
            "desc": spec["desc"],
            "patch": spec["patch"],
            "elapsedSec": round(dt, 1),
            "stats": stats,
            "byKey": encode_bykey(signals),
        }
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        warn = " [WARN 超 10 分钟警戒线]" if dt > SINGLE_TRIAL_WARN_SEC else ""
        print(
            f"[p3-0] {key} 完成 {dt:.0f}s{warn} 信号={stats.get('totalSignals')} "
            f"四态%={stats.get('statePctSignal')}",
            file=sys.stderr,
        )

    report = build_report(
        cache, prefix, win, len(frames), field_truth,
        smoke=args.smoke,
        elapsed_by_trial={
            k: v.get("elapsedSec") for k, v in trials.items()
            if (k.startswith(prefix) if prefix else ":" not in k)
        },
    )
    report_path = Path(args.out) if args.out else REPORT_DIR / (
        "regime-risk-activity-smoke.json" if args.smoke else "regime-risk-activity.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[p3-0] 报告 -> {report_path}", file=sys.stderr)

    for ln, r in report["regimeLineTrials"].items():
        rates = {sign: d.get("tierMigrationRate") for sign, d in r["dirs"].items() if isinstance(d, dict)}
        print(f"[p3-0][结论] {ln}: {r['verdict']}  迁移率={rates}", file=sys.stderr)
    for gname, g in report["riskGateStats"].items():
        if gname == "pressure_ge_reversalMin":
            continue
        s = g["stats"]
        print(
            f"[p3-0][结论] {gname}: 信号率={s['signalRate']:.4%} 帧率={s['frameRate']:.4%} 股票={s['stockCount']} → {g['verdict']}",
            file=sys.stderr,
        )
    print(f"[p3-0][结论] P3-a 预计 trial 数={report['p3aScope']['estimatedTrials']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
