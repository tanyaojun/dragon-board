# -*- coding: utf-8 -*-
"""L2 成交额量比喂量价档位 trial runner（2026-10-08 合同 v1.1，判定线冻结于跑数前）。

合同：docs/ranktrend-tier-backtest/vote-l2-vp-amount-tier-preregistration.md（v1.1，双模型审定
有条件通过 A1/A2/A5 必改+A3/A4 建议全部落实；用户 2026-10-08「请继续」=开跑令）。
harness：复用 evaluate_voting_signals_t2.py 骨架（B0 锚 0.1450/0.0983/0.1172、951 帧口径、
护栏 resS≥7185/synS≥64）——不触引擎文件。

trial（单参三态）：volumePriceAmountTierMode off → {high_demote, both}，2 剂量臂 + 1 基线臂。
判定卡（合同 L2-2 冻结）：
- B0 自证前置断言（不 PASS 全臂读数作废）；
- C1 decision saEx rel ≥ +3% / C2 oos2 同向正 / C3 passHard 不降 / A3 oos1 < −5% 止损；
- Track 1 终判：decision wrxpf rel ≥ 0 且 |maxDD| ≤ 基线；oos2 Track1 披露（rel < −5% 交裁）；
- 护栏：resS/synS 半数线；触发率披露（=0 零效应阴性；<2% 标注触面过小）；
- 披露：vp tier 迁移表（a 臂 A+B 面↓、b 臂另 C↓B↑）、b−a 同帧改判配对差、decision 按月可算率、
  市况分桶 strong vs retreat（retreat n<50 降级只披露）。
成本：3 replay + 3 Track1，全本地零调用（AGENTS §1.2-7）。

用法：python -m backend.operations.evaluate_vote_l2_vp_amount [--out data/reports/vote-l2-vp-amount-trials.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.evaluate_voting_signals_t2 import (
    B0_ANCHOR,
    GUARD_RES_S,
    GUARD_SYN_S,
    load_frames,
    window_frames,
)
from backend.operations.optimize_gate_denoise_parameters import sa_excess_of
from backend.operations.track1_lifecycle_gate_trade import _assert_overrides_applied, _trade_metrics

MAIN_WINDOWS = ("decision", "oos1", "oos2")
OOS2_TRACK1_COURT = -0.05  # 披露交裁线（合同 L2-2/A2）
OOS1_STOP_BAND = -0.05     # A3 止损带
TRIGGER_ZERO = 0.0
TRIGGER_SMALL = 0.02

TRIALS: dict[str, dict] = {
    "baseline": {"desc": "B0 自证（默认 config，mode=off）", "overrides": {}},
    "a_high_demote": {"desc": "放量奖励撤回：ar≥1.5 ∧ rise_volume → 降一档（A→B/B→C）",
                      "overrides": {"volumePriceAmountTierMode": "high_demote"}},
    "b_both": {"desc": "双向门：a 臂 + ar≤0.5 ∧ (rise_shrink|normal) C→B（升档腿对照）",
               "overrides": {"volumePriceAmountTierMode": "both"}},
}

_OVERRIDE_MISSING = object()


def _vp_tier_map(signals: list[dict], wf: list[dict]) -> tuple[dict[str, str], Counter, dict[str, list[int]]]:
    """逐信号 (fi|code → vp tier) + tier 计数 + 按月可算率（amountRatio 有限=可算）。"""
    index_by_snapshot = {str(f.get("snapshotId")): (i, str(f.get("tradingDate") or "")) for i, f in enumerate(wf)}
    tier_map: dict[str, str] = {}
    tier_counts: Counter = Counter()
    monthly: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # month → [computable, total]
    for s in signals:
        rt = s.get("rankTrend") or {}
        obs = rt.get("observation") or {}
        fi, date = index_by_snapshot.get(str(s.get("snapshotId")), (-1, ""))
        code = str(s.get("code") or "")
        tier = str((obs.get("volumePrice") or {}).get("signalTier") or "unknown")
        tier_map[f"{fi}|{code}"] = tier
        tier_counts[tier] += 1
        if fi >= 0:
            month = date[:7]
            ar = obs.get("amountRatio")
            computable = isinstance(ar, (int, float))
            monthly[month][0] += 1 if computable else 0
            monthly[month][1] += 1
    return tier_map, tier_counts, {m: {"computable": c, "total": t, "rate": round(c / t, 4) if t else None}
                                    for m, (c, t) in sorted(monthly.items())}


def _regime_buckets(signals: list[dict], wf: list[dict]) -> dict:
    """市况分桶（strong vs retreat；signal_filter 通道分桶基线同口径重算；报告列不进判定线）。"""
    out: dict = {}
    for bucket in ("strong", "retreat"):
        def flt(s, _b=bucket):
            # signal 顶层 regime 是状态字符串（runtime:1559 "regime": regime["state"]）；兼容 dict 形态
            regime = s.get("regime")
            state = regime if isinstance(regime, str) else str((regime or {}).get("state") or "")
            return state == _b
        n = sum(1 for s in signals if flt(s))
        syn = tier_forward_returns(signals, wf, horizon=1, dimension="synergy", signal_filter=flt)
        out[bucket] = {"n_signals": n, "saEx": sa_excess_of(syn),
                       "downgraded_note": "retreat n<50 股帧 → 只披露不挂起（合同 A5）" if n < 50 else None}
    return out


def _track1(config: RankTrendConfig, wf: list[dict]) -> dict:
    from backend.core.backtest.execution import TradeSimulator

    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(wf, meta={"candidateTierMode": "execution", "strategyName": "rank_trend_candidate"})
    sim = TradeSimulator().run(wf, signals, {"entryStrategy": "rank_trend_candidate"})
    return _trade_metrics(sim)


def evaluate_arm(key: str, arm: dict, frames: list[dict]) -> dict:
    config = RankTrendConfig.from_patch(arm["overrides"])
    _assert_overrides_applied(config, arm["overrides"])
    engine = RankTrendPythonEngine(config=config)
    out: dict = {"desc": arm["desc"], "windows": {}, "track1": {}}
    for name, (start, end) in WINDOWS.items():
        if name not in MAIN_WINDOWS:
            continue
        wf = window_frames(frames, start, end)
        t0 = time.time()
        signals = engine.replay(wf, meta={})
        syn = tier_forward_returns(signals, wf, horizon=1, dimension="synergy")
        res_s = sum(1 for s in signals
                    if ((s.get("rankTrend") or {}).get("resonance") or {}).get("signalTier") == "S")
        syn_s = sum(1 for s in signals
                    if (((s.get("rankTrend") or {}).get("observation") or {}).get("synergy") or {}).get("signalTier") == "S")
        tier_map, tier_counts, monthly = _vp_tier_map(signals, wf)
        reading = {
            "signalCount": len(signals),
            "saEx": sa_excess_of(syn),
            "passHard": syn.get("monotonicity", {}).get("hardPass", syn.get("monotonicity", {}).get("ok")),
            "resSFrames": res_s,
            "synSFrames": syn_s,
            "vpTierCounts": dict(tier_counts),
            "monthlyComputable": monthly if name == "decision" else None,
            "regimeBuckets": _regime_buckets(signals, wf) if name == "decision" else None,
        }
        out["windows"][name] = reading
        out.setdefault("_tierMaps", {})[name] = tier_map  # 判定后裁剪，不进产物
        print(f"[{key}] {name}: saEx={reading['saEx']} vpTier={dict(tier_counts)} ({time.time() - t0:.0f}s)",
              file=sys.stderr)
        if name == "decision":
            out["track1"]["decision"] = _track1(config, wf)
            m = out["track1"]["decision"]
            print(f"[{key}] track1 decision: trades={m.get('tradeCount')} wrxpf={m.get('winRateXpf')} "
                  f"ret={m.get('totalReturn')} dd={m.get('maxDD')}", file=sys.stderr)
    return out


def _diff_sets(arm_map: dict[str, str], base_map: dict[str, str]) -> set[str]:
    return {k for k, v in arm_map.items() if base_map.get(k) not in (None, v)}


def track1_verdict(arm_m: dict, base_m: dict) -> dict:
    a, b = arm_m.get("winRateXpf"), base_m.get("winRateXpf")
    dd_a, dd_b = arm_m.get("maxDD"), base_m.get("maxDD")
    if a is None or b in (None, 0) or dd_a is None or dd_b is None:
        return {"pass": False, "note": "Track1 指标缺失（fail-visible）", "arm": arm_m, "base": base_m}
    rel = a / b - 1
    return {"wrxpf_rel": round(rel, 5), "wrxpf_pass": rel >= 0,
            "maxDD": {"arm": dd_a, "base": dd_b, "pass": abs(dd_a) <= abs(dd_b)},
            "tradeCount": {"arm": arm_m.get("tradeCount"), "base": base_m.get("tradeCount")},
            "pass": rel >= 0 and abs(dd_a) <= abs(dd_b)}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/reports/vote-l2-vp-amount-trials.json")
    args = ap.parse_args()
    t0 = time.time()
    frames = load_frames()
    print(f"frames={len(frames)}", file=sys.stderr)
    out_path = Path(args.out)
    checkpoint_path = out_path.parent / (out_path.stem + "-checkpoint.json")

    results: dict[str, dict] = {}
    for key, arm in TRIALS.items():
        t1 = time.time()
        results[key] = {"desc": arm["desc"], "read": evaluate_arm(key, arm, frames)}
        # checkpoint 逐臂落盘（Q1/P5 长跑教训）
        slim = {k: ({**v, "_tierMaps": {w: len(m) for w, m in (v.get("_tierMaps") or {}).items()}}
                    if isinstance(v, dict) else v)
                for k, v in results.items()}
        checkpoint_path.write_text(
            json.dumps({"partial": True, "completed_arms": list(results), "results": slim},
                       ensure_ascii=False, default=str), encoding="utf-8")
        print(f"[{key}] done ({time.time() - t1:.0f}s) -> checkpoint", file=sys.stderr)

    base = results["baseline"]["read"]
    # B0 自证前置断言（合同 L2-1：不 PASS 全臂读数作废）
    b0 = {w: {"anchor": B0_ANCHOR[w], "today": base["windows"][w]["saEx"],
              "match": abs((base["windows"][w]["saEx"] or 0) - B0_ANCHOR[w]) < 5e-4}
          for w in MAIN_WINDOWS}
    b0_pass = all(v["match"] for v in b0.values())
    print(f"B0 selfcheck: {'PASS' if b0_pass else 'FAIL'} {json.dumps(b0)}", file=sys.stderr)

    verdict: dict[str, dict] = {"b0_selfcheck": {"per_window": b0, "pass": b0_pass,
                                                 "note": "不 PASS 全臂读数作废" if not b0_pass else None}}
    for key in ("a_high_demote", "b_both"):
        arm_read = results[key]["read"]
        sa = {w: arm_read["windows"][w]["saEx"] for w in MAIN_WINDOWS}
        rel = {w: (sa[w] / base["windows"][w]["saEx"] - 1)
               if (sa[w] is not None and base["windows"][w]["saEx"]) else None for w in MAIN_WINDOWS}
        c1 = rel["decision"] is not None and rel["decision"] >= 0.03
        c2 = rel["oos2"] is not None and rel["oos2"] > 0
        c3 = all(arm_read["windows"][w]["passHard"] is not False for w in MAIN_WINDOWS)
        a3_stop = rel["oos1"] is not None and rel["oos1"] < OOS1_STOP_BAND
        guards = {"resS": arm_read["windows"]["decision"]["resSFrames"], "resS_line": GUARD_RES_S,
                  "synS": arm_read["windows"]["decision"]["synSFrames"], "synS_line": GUARD_SYN_S}
        guards_pass = guards["resS"] >= GUARD_RES_S and guards["synS"] >= GUARD_SYN_S

        # 触发率 + vp tier 迁移 + b−a 配对差（decision 窗）
        base_map = base["_tierMaps"]["decision"]
        arm_map = arm_read["_tierMaps"]["decision"]
        changed = _diff_sets(arm_map, base_map)
        trigger_rate = len(changed) / max(1, len(base_map))
        pair_note = None
        if key == "b_both":
            a_map = results["a_high_demote"]["read"]["_tierMaps"]["decision"]
            a_changed = _diff_sets(a_map, base_map)
            b_only = changed - a_changed
            a_only = a_changed - changed
            pair_note = {"b_changed_total": len(changed), "a_changed_total": len(a_changed),
                         "b_only_升档腿独占": len(b_only), "a_only": len(a_only),
                         "shared_a_leg": len(changed & a_changed)}
        v = {
            "saEx": sa, "rel": {w: round(x, 5) if x is not None else None for w, x in rel.items()},
            "c1_pass": c1, "c2_oos2_pass": c2, "c3_passhard": c3,
            "a3_oos1_stop": a3_stop,
            "guardrail": guards, "guardrail_pass": guards_pass,
            "trigger": {"changed_frames": len(changed), "total": len(base_map),
                        "rate": round(trigger_rate, 5),
                        "zero_effect": trigger_rate == TRIGGER_ZERO,
                        "small_surface": 0 < trigger_rate < TRIGGER_SMALL},
            "vp_tier_migration": {t: {"arm": arm_read["windows"]["decision"]["vpTierCounts"].get(t, 0),
                                       "base": base["windows"]["decision"]["vpTierCounts"].get(t, 0)}
                                   for t in ("A", "B", "C", "D", "E")},
            "pair_disclosure": pair_note,
        }
        # Track 1 终判（decision）+ oos2 披露
        v["track1_decision"] = track1_verdict(arm_read["track1"]["decision"], base["track1"]["decision"])
        # 触发率判读（合同：=0 零效应阴性；<2% 标注）
        if v["trigger"]["zero_effect"]:
            v["verdict"] = "FAIL_ZERO_EFFECT"
        else:
            core_pass = c1 and c2 and c3 and not a3_stop and guards_pass and v["track1_decision"]["pass"]
            v["verdict"] = ("PASS_CANDIDATE" if core_pass else
                            "FAIL_C1" if not c1 else "FAIL_C2" if not c2 else "FAIL_C3"
                            if not c3 else "FAIL_A3_STOP" if a3_stop else "FAIL_GUARD"
                            if not guards_pass else "FAIL_TRACK1")
            if v["trigger"]["small_surface"]:
                v["small_surface_note"] = "触面过小，效应量解释受限（Q1 C-c 教训）"
        # Track 1 是一票否决面：C1 过但 Track1 <0 → 判不晋升（L2-3）
        if c1 and not v["track1_decision"]["pass"] and v["verdict"] not in ("FAIL_ZERO_EFFECT",):
            v["verdict"] = "FAIL_TRACK1"
            v["note"] = "C1 过但 Track 1 <0 → 判不晋升（保护向机制若伤交易面=证伪其保护语义，L2-3）"
        verdict[key] = v

    # 过线臂 oos2 Track1 披露（合同 A2；基线同窗对照）
    base_oos2_wf = window_frames(frames, *WINDOWS["oos2"])
    base["track1"]["oos2"] = _track1(RankTrendConfig(), base_oos2_wf)
    print(f"[baseline] track1 oos2 done", file=sys.stderr)
    for key in ("a_high_demote", "b_both"):
        v = verdict[key]
        if v["verdict"] == "PASS_CANDIDATE":
            arm = TRIALS[key]
            config = RankTrendConfig.from_patch(arm["overrides"])
            results[key]["read"]["track1"]["oos2"] = _track1(config, base_oos2_wf)
            a_m = results[key]["read"]["track1"]["oos2"]
            b_m = base["track1"]["oos2"]
            if a_m.get("winRateXpf") is not None and b_m.get("winRateXpf") not in (None, 0):
                v["oos2_track1_wrxpf_rel"] = round(a_m["winRateXpf"] / b_m["winRateXpf"] - 1, 5)
                if v["oos2_track1_wrxpf_rel"] < OOS2_TRACK1_COURT:
                    v["oos2_court"] = "wrxpf 相对基线 < −5%，须显式解释交用户裁决（A2）"

    # 机械化选臂（合同 §二：均过取三窗均值 rel 改善大者，另一臂如实披露）
    passed = [k for k in ("a_high_demote", "b_both") if verdict[k]["verdict"] == "PASS_CANDIDATE"]
    candidate = None
    if len(passed) == 2:
        means = {k: sum(x for x in verdict[k]["rel"].values() if x is not None) / 3 for k in passed}
        candidate = max(passed, key=lambda k: means[k])
    elif len(passed) == 1:
        candidate = passed[0]

    # 产物裁剪：_tierMaps 不进 JSON（体积控制），只留 map 尺寸
    for key, item in results.items():
        maps = item["read"].pop("_tierMaps", {})
        item["read"]["_tierMapSizes"] = {w: len(m) for w, m in maps.items()}

    out = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 1),
            "population": "951 帧全窗（end=09-12，B0 锚同源口径）",
            "frozen": "vote-l2-vp-amount-tier-preregistration.md v1.1（判定线冻结于跑数前）",
            "candidate": candidate,
        },
        "results": results,
        "verdict": verdict,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    checkpoint_path.unlink(missing_ok=True)
    print(json.dumps({"out": str(out_path), "b0_pass": b0_pass, "candidate": candidate,
                      "verdicts": {k: {"verdict": v["verdict"], "rel": v.get("rel"),
                                        "track1_pass": v.get("track1_decision", {}).get("pass"),
                                        "trigger_rate": (v.get("trigger") or {}).get("rate")}
                                   for k, v in verdict.items() if k != "b0_selfcheck"}},
                     ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
