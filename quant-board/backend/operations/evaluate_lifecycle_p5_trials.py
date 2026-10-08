# -*- coding: utf-8 -*-
"""生命周期 P5 双轴重设计·allow 腿分位带门 trial runner（2026-10-07 预登记合同，判定线冻结于跑数前）。

合同：docs/ranktrend-tier-backtest/lifecycle-p5-preregistration.md
- 臂数冻结（P5-a2）：5 剂量臂 + 1 基线臂 = 6 次 replay + Track1（decision 窗）。
- 判定线（C-3，冻结）：
  C-3.1 信号面无害线（≥2 窗 ≥0 且无一窗 <−0.005）+ 提交线（均值 ≥+0.002 且 ≥1 窗 ≥+0.003）
        + 负效应线（均值 <−0.003 止损）；全臂未达提交线=零效应阴性登记。
  C-3.2 Track1：decision 窗 wrxpf 相对基线 ≥−0.003 且 maxDD 不恶化（|dd|≤|base|）；
        oos2/g1era 披露（oos2 wrxpf 相对基线 <−0.005 须交裁）。
  C-3.3 结构守卫（硬断言）：veto/exit_watch 触发数与基线逐位相同；caution 增量=allow 降幅。
  C-3.4 侵蚀披露：降档（lifecycleTier B/D）变化分列 + allow→caution 改写帧数。
  C-3.5 准入：≥1 臂同时过 C-3.1+C-3.2 → 提交用户裁决；全 FAIL=阴性登记。
- 成本：全本地 replay，零 jev/付费模型调用（AGENTS §1.2-7）。

用法：python -m backend.operations.evaluate_lifecycle_p5_trials [--out data/reports/lifecycle-p5-trials.json]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.operations.evaluate_lifecycle_q1_trials import (
    FULL_WINDOW,
    OOS2_COURT,
    NEGATIVE_MEAN,
    HARMLESS_NEG_WINDOW,
    SUBMIT_MEAN,
    SUBMIT_SINGLE,
    WINDOW_G1ERA,
    WINDOWS,
    load_frames,
    signal_verdict,
    track1_verdict,
    window_frames,
)
from backend.operations.track1_lifecycle_gate_trade import _assert_overrides_applied, _trade_metrics
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns
from backend.operations.optimize_gate_denoise_parameters import sa_excess_of

ARMS: list[dict] = [
    {"key": "baseline", "desc": "全 off（当前生产默认）", "overrides": {}},
    {"key": "a3_pct70", "desc": "1D 保守：allow∧pct≥70→caution",
     "overrides": {"lifecycleAllowBandGateMode": "pct_band", "lifecycleAllowBandGatePctMin": 70.0}},
    {"key": "a1_pct60", "desc": "1D 中间：allow∧pct≥60→caution",
     "overrides": {"lifecycleAllowBandGateMode": "pct_band", "lifecycleAllowBandGatePctMin": 60.0}},
    {"key": "a2_pct50", "desc": "1D 激进：allow∧pct≥50→caution",
     "overrides": {"lifecycleAllowBandGateMode": "pct_band", "lifecycleAllowBandGatePctMin": 50.0}},
    {"key": "b1_f5_s7", "desc": "2D 门：fast(velocity>5)≥50 / slow≥70",
     "overrides": {"lifecycleAllowBandGateMode": "pct_velocity",
                    "lifecycleAllowBandGatePctMin": 70.0, "lifecycleAllowBandGatePctMinFast": 50.0}},
    {"key": "b2_f5_s6", "desc": "2D 门：fast≥50 / slow≥60",
     "overrides": {"lifecycleAllowBandGateMode": "pct_velocity",
                    "lifecycleAllowBandGatePctMin": 60.0, "lifecycleAllowBandGatePctMinFast": 50.0}},
]

_OVERRIDE_MISSING = object()


def _action_counts(signals: list[dict]) -> dict:
    counts = {"veto": 0, "caution": 0, "allow": 0, "exit_watch": 0}
    lc_tiers = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    gate_notes = 0
    for s in signals:
        rt = s.get("rankTrend") or {}
        cycle = rt.get("cycle") or {}
        action = str(((cycle.get("decision") or {}).get("action")) or "")
        if action in counts:
            counts[action] += 1
        tier = str((((rt.get("observation") or {}).get("lifecycle")) or {}).get("signalTier") or "")
        if tier in lc_tiers:
            lc_tiers[tier] += 1
        if any("P5 allow 分位带门" in r for r in ((cycle.get("decision") or {}).get("reasons") or [])):
            gate_notes += 1
    return {"actions": counts, "lcTiers": lc_tiers, "gateRewrites": gate_notes}


def _signal_metrics(signals: list[dict], wf: list[dict]) -> dict:
    syn = tier_forward_returns(signals, wf, horizon=1, dimension="synergy")
    veto_n = 0
    sa_n = 0
    total = 0
    for s in signals:
        rt = s.get("rankTrend") or {}
        lc = (rt.get("observation") or {}).get("lifecycle") or {}
        syn_tier = (rt.get("observation") or {}).get("synergy", {}).get("signalTier")
        total += 1
        veto_n += 1 if lc.get("veto") else 0
        sa_n += 1 if syn_tier in ("S", "A") else 0
    return {
        "signalCount": total,
        "saEx": sa_excess_of(syn),
        "vetoFrames": veto_n,
        "saFrames": sa_n,
    }


def _track1(config: RankTrendConfig, wf: list[dict]) -> dict:
    from backend.core.backtest.execution import TradeSimulator

    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(wf, meta={"candidateTierMode": "execution", "strategyName": "rank_trend_candidate"})
    sim = TradeSimulator().run(wf, signals, {"entryStrategy": "rank_trend_candidate"})
    return _trade_metrics(sim)


def evaluate_arm(arm: dict, frames: list[dict]) -> dict:
    config = RankTrendConfig.from_patch(arm["overrides"])
    _assert_overrides_applied(config, arm["overrides"])
    engine = RankTrendPythonEngine(config=config)
    out: dict = {"desc": arm["desc"], "windows": {}, "track1": {}}
    for name, (start, end) in {**WINDOWS, "g1era": WINDOW_G1ERA}.items():
        wf = window_frames(frames, start, end)
        if not wf:
            out["windows"][name] = {"empty": True}
            continue
        t0 = time.time()
        signals = engine.replay(wf, meta={})
        reading = _signal_metrics(signals, wf)
        reading["actionCounts"] = _action_counts(signals)
        out["windows"][name] = reading
        print(f"[{arm['key']}] {name}: saEx={reading['saEx']} actions={reading['actionCounts']['actions']} "
              f"lcTiers={reading['actionCounts']['lcTiers']} rewrites={reading['actionCounts']['gateRewrites']} "
              f"({time.time() - t0:.0f}s)", file=sys.stderr)
        if name == "decision":
            out["track1"]["decision"] = _track1(config, wf)
            m = out["track1"]["decision"]
            print(f"[{arm['key']}] track1 decision: trades={m.get('tradeCount')} wrxpf={m.get('winRateXpf')} "
                  f"ret={m.get('totalReturn')} dd={m.get('maxDD')}", file=sys.stderr)
    return out


def structural_guard(arm_read: dict, base_read: dict) -> dict:
    """C-3.3：veto/exit_watch 逐位相同；caution 增量=allow 降幅（decision 窗）。"""
    a = arm_read["windows"]["decision"]["actionCounts"]["actions"]
    b = base_read["windows"]["decision"]["actionCounts"]["actions"]
    return {
        "veto_unchanged": a["veto"] == b["veto"],
        "exit_watch_unchanged": a["exit_watch"] == b["exit_watch"],
        "caution_delta_eq_allow_drop": (a["caution"] - b["caution"]) == (b["allow"] - a["allow"]),
        "rewrites": arm_read["windows"]["decision"]["actionCounts"]["gateRewrites"],
        "pass": a["veto"] == b["veto"] and a["exit_watch"] == b["exit_watch"]
                and (a["caution"] - b["caution"]) == (b["allow"] - a["allow"]),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/reports/lifecycle-p5-trials.json")
    args = ap.parse_args()
    t0 = time.time()
    frames = load_frames()
    print(f"frames={len(frames)}", file=sys.stderr)
    out_path = Path(args.out)
    checkpoint_path = out_path.parent / (out_path.stem + "-checkpoint.json")

    results: dict[str, dict] = {}
    for arm in ARMS:
        t1 = time.time()
        read = evaluate_arm(arm, frames)
        results[arm["key"]] = {"desc": arm["desc"], "read": read}
        checkpoint_path.write_text(
            json.dumps({"partial": True, "completed_arms": list(results), "results": results},
                       ensure_ascii=False, default=str),
            encoding="utf-8")
        print(f"[{arm['key']}] done ({time.time() - t1:.0f}s) -> checkpoint", file=sys.stderr)

    base = results["baseline"]["read"]
    for arm in ARMS[1:]:
        key = arm["key"]
        read = results[key]["read"]
        v = {
            "signal": signal_verdict(read, base),
            "track1_decision": track1_verdict(read["track1"].get("decision") or {},
                                              base["track1"].get("decision") or {}),
            "structural_guard": structural_guard(read, base),
        }
        # 披露窗（C-3.2）：oos2/g1era Track1（过线臂才跑，对照=基线同窗）
        if v["signal"]["harmless"] and v["signal"]["submit"] and v["track1_decision"]["pass"]:
            config = RankTrendConfig.from_patch(arm["overrides"])
            for wname, (s, e) in (("oos2", WINDOWS["oos2"]), ("g1era", WINDOW_G1ERA)):
                wf = window_frames(frames, s, e)
                read["track1"][wname] = _track1(config, wf)
                print(f"[{key}] track1 {wname} done", file=sys.stderr)
            for wname in ("oos2", "g1era"):
                a_m = read["track1"].get(wname, {})
                b_m = base["track1"].get(wname, {})
                if a_m.get("winRateXpf") is not None and b_m.get("winRateXpf") not in (None, 0):
                    v[f"{wname}_wrxpf_rel"] = round(a_m["winRateXpf"] / b_m["winRateXpf"] - 1, 5)
                    if wname == "oos2" and v[f"{wname}_wrxpf_rel"] < OOS2_COURT:
                        v["oos2_court"] = "须显式交裁（oos2 wrxpf 相对基线 < −0.005）"
        results[key]["verdict"] = v

    # baseline 补跑 oos2/g1era Track1（披露窗同窗对照）
    base_config = RankTrendConfig()
    for wname, (s, e) in (("oos2", WINDOWS["oos2"]), ("g1era", WINDOW_G1ERA)):
        wf = window_frames(frames, s, e)
        base["track1"][wname] = _track1(base_config, wf)
        print(f"[baseline] track1 {wname} done", file=sys.stderr)

    out = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "elapsed_sec": round(time.time() - t0, 1),
            "full_window": list(FULL_WINDOW),
            "windows_main": dict(WINDOWS), "window_g1era": list(WINDOW_G1ERA),
            "frozen_lines": {
                "harmless": {"windows_ge2_zero": True, "single_floor": HARMLESS_NEG_WINDOW},
                "submit": {"mean": SUBMIT_MEAN, "single": SUBMIT_SINGLE},
                "negative_mean": NEGATIVE_MEAN,
                "wrxpf_floor_abs": -0.003, "maxDD": "≤ 基线（|dd| 口径）",
                "oos2_court": OOS2_COURT,
                "structural_guard": "veto/exit_watch 逐位相同 + caution 增量=allow 降幅",
            },
            "contract": "lifecycle-p5-preregistration.md（判定线冻结于跑数前）",
        },
        "results": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    checkpoint_path.unlink(missing_ok=True)
    print(json.dumps({"out": str(out_path),
                      "verdicts": {k: {"signal": v["verdict"]["signal"],
                                        "track1": v["verdict"]["track1_decision"].get("pass"),
                                        "guard": v["verdict"]["structural_guard"]["pass"]}
                                    for k, v in results.items() if k != "baseline"}},
                     ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
