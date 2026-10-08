# -*- coding: utf-8 -*-
"""四投票信号 W1-1（共振 D∧buy 倒挂票）行为步 trial runner（2026-10-07 预登记合同）。

合同：docs/ranktrend-tier-backtest/vote-w11-res-dbuy-preregistration.md（判定线冻结于跑数前，
跑后不得回看调线）。机制：`tierSynergyResonanceDbuyMode` off/cap_b/abstain——D∧buy（reversal_penalty
驱动衰竭档投 +0.75 > B +0.525 的倒挂）在 cap_b 下票值封顶 B（min(强度D,强度B)×res 权重=+0.525）、
abstain 下弃权（票 0）；D∧sell（路径 2 真反向）两案都不动；rank/vp/cs 维不触及。

trial：baseline（B0 自证）+ cap_b + abstain = 3 臂 × 3 窗（951 帧口径）+ 2 Track 1（decision 窗）。
判定卡（合同 W1-1.2 冻结）：C1 decision saEx rel ≥+3% ∧ C2 oos2 同向正 ∧ C3 passHard 不降
+ Track 1 wrxpf rel ≥0（maxDD 容差 ≤ 基线）+ 护栏（res S≥7185、syn S≥64）+ 市况分桶（strong vs
retreat 预注册对比对，反号挂起，仅报告列）。
披露义务：S/A 帧计数变化 + res tier 分布逐位一致守卫（res 维不动）+ synergy tier 迁移矩阵
（全帧与 D∧buy 子集）+ 笔数变化。

教训继承：逐臂 checkpoint 落盘（Q1 首轮算完在最终序列化崩掉 Track1 全失）；maxDD 负数域 |dd| 比较
（Q1 verdict bug 修正版）；flip 键 JSON 安全 "snapshotId|code"。

用法：python -m backend.operations.evaluate_vote_w11_res_dbuy [--trials baseline,cap_b,abstain] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns
from backend.analysis.ranktrend.trend.risk import market_regime
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.evaluate_voting_signals_t2 import B0_ANCHOR, GUARD_RES_S, GUARD_SYN_S, load_frames, window_frames
from backend.operations.optimize_gate_denoise_parameters import sa_excess_of
from backend.operations.track1_lifecycle_gate_trade import _assert_overrides_applied, _trade_metrics

TRIALS: dict[str, dict] = {
    "baseline": {"desc": "B0 自证（默认 config = G1 cross_day）", "overrides": {}},
    "cap_b": {"desc": "W1-1a D∧buy 票值封顶 B（+0.75→+0.525）", "overrides": {"tierSynergyResonanceDbuyMode": "cap_b"}},
    "abstain": {"desc": "W1-1b D∧buy 弃权（票 0；D∧sell 不动）", "overrides": {"tierSynergyResonanceDbuyMode": "abstain"}},
}


def _res_key(s: dict) -> tuple[str, str]:
    res = (s.get("rankTrend") or {}).get("resonance") or {}
    return str(res.get("signalTier")), str(res.get("direction"))


def _syn_tier(s: dict) -> str:
    obs = (s.get("rankTrend") or {}).get("observation") or {}
    return str((obs.get("synergy") or {}).get("signalTier"))


def _signal_key(s: dict) -> str:
    return f"{s.get('snapshotId')}|{s.get('code')}"


def evaluate_arm(config: RankTrendConfig, wf: list[dict], regime_by_snapshot: dict[str, str] | None = None) -> tuple[dict, dict[str, list[str]]]:
    engine = RankTrendPythonEngine(config=config)
    t0 = time.time()
    signals = engine.replay(wf, meta={})
    syn = tier_forward_returns(signals, wf, horizon=1, dimension="synergy")
    res_tiers: Counter = Counter()
    syn_tiers: Counter = Counter()
    dbuy = 0
    per_signal: dict[str, list[str]] = {}
    for s in signals:
        rt, rd = _res_key(s)
        res_tiers[rt] += 1
        st = _syn_tier(s)
        syn_tiers[st] += 1
        if rt == "D" and rd == "buy":
            dbuy += 1
        per_signal[_signal_key(s)] = [rt, rd, st]
    reading: dict = {
        "signalCount": len(signals),
        "saEx": sa_excess_of(syn),
        "passHard": syn.get("monotonicity", {}).get("hardPass", syn.get("monotonicity", {}).get("ok")),
        "resSFrames": res_tiers.get("S", 0),
        "resAFrames": res_tiers.get("A", 0),
        "synSFrames": syn_tiers.get("S", 0),
        "synAFrames": syn_tiers.get("A", 0),
        "resTierDist": dict(sorted(res_tiers.items())),
        "resDbuyFrames": dbuy,
    }
    if regime_by_snapshot is not None:
        # 市况分桶（合同：strong vs retreat 预注册对比对；signal_filter 原生通道，分桶基线同口径重算）
        for bucket in ("strong", "retreat"):
            bsyn = tier_forward_returns(
                signals, wf, horizon=1, dimension="synergy",
                signal_filter=lambda s, _b=bucket: regime_by_snapshot.get(_signal_key(s), "missing") == _b,
            )
            reading[f"saEx_{bucket}"] = sa_excess_of(bsyn)
            reading[f"saFrames_{bucket}"] = sum((bsyn.get("tiers") or {}).get(t, {}).get("count") or 0 for t in ("S", "A"))
    print(f"    saEx={reading['saEx']} resS={reading['resSFrames']} synS={reading['synSFrames']} "
          f"D∧buy={dbuy} ({time.time() - t0:.0f}s)", file=sys.stderr)
    return reading, per_signal


def migration_matrix(base_per: dict[str, list[str]], arm_per: dict[str, list[str]]) -> dict:
    """synergy tier 迁移矩阵（baseline→臂）：全帧 + D∧buy 子集（合同披露义务）。"""
    def _mat(keys: list[str]) -> dict:
        mat: Counter = Counter()
        for k in keys:
            b = base_per.get(k)
            a = arm_per.get(k)
            if b and a:
                mat[f"{b[2]}->{a[2]}"] += 1
        return dict(sorted(mat.items()))

    dbuy_keys = [k for k, v in base_per.items() if v[0] == "D" and v[1] == "buy"]
    return {
        "all": _mat(list(base_per.keys())),
        "dbuy_subset": _mat(dbuy_keys),
        "dbuy_n": len(dbuy_keys),
        "paired_n": sum(1 for k in base_per if k in arm_per),
    }


def _track1(config: RankTrendConfig, wf: list[dict]) -> dict:
    from backend.core.backtest.execution import TradeSimulator

    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(wf, meta={"candidateTierMode": "execution", "strategyName": "rank_trend_candidate"})
    sim = TradeSimulator().run(wf, signals, {"entryStrategy": "rank_trend_candidate"})
    return _trade_metrics(sim)


def track1_verdict(arm_track: dict, base_track: dict) -> dict:
    a, b = arm_track.get("winRateXpf"), base_track.get("winRateXpf")
    dd_a, dd_b = arm_track.get("maxDD"), base_track.get("maxDD")
    if a is None or b is None or dd_a is None or dd_b is None:
        return {"pass": False, "note": "Track1 指标缺失（fail-visible）", "arm": arm_track, "base": base_track}
    return {
        "wrxpf_abs_diff": round(a - b, 5),
        "wrxpf_rel": round(a / b - 1, 5) if b not in (None, 0) else None,
        "wrxpf_pass": a >= b,  # 合同：wrxpf 相对基线 ≥ 0（绝对差）
        "maxDD": {"arm": dd_a, "base": dd_b, "pass": abs(dd_a) <= abs(dd_b)},  # 负数域 |dd| 比较（Q1 修正版）
        "tradeCount": {"arm": arm_track.get("tradeCount"), "base": base_track.get("tradeCount")},
        "pass": a >= b and abs(dd_a) <= abs(dd_b),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", default="baseline,cap_b,abstain")
    ap.add_argument("--end", default="2026-09-12", help="帧截止（合同 population=951 帧全窗=09-12）")
    ap.add_argument("--out", default="data/reports/vote-w11-res-dbuy-trials.json")
    args = ap.parse_args()
    keys = [k.strip() for k in args.trials.split(",") if k.strip()]
    for k in keys:
        if k not in TRIALS:
            raise SystemExit(f"未知 trial {k}（可选 {sorted(TRIALS)}）")
    t0 = time.time()
    frames = load_frames(args.end)
    print(f"frames={len(frames)} trials={keys}", file=sys.stderr)

    # decision 窗帧级市况分桶映射（market_regime pool 因子 state，报告列非判定线）
    base_config = RankTrendConfig()
    regime_by_snapshot: dict[str, str] = {}
    for f in window_frames(frames, *WINDOWS["decision"]):
        state = str(market_regime(f, base_config).get("state") or "missing")
        for st in (f.get("stocks") or []):
            regime_by_snapshot[f"{f.get('snapshotId')}|{st.get('code')}"] = state

    results: dict[str, dict] = {}
    per_signal_store: dict[str, dict[str, list[str]]] = {}
    out_path = Path(args.out)
    if "baseline" not in keys and out_path.exists():
        prior = json.loads(out_path.read_text(encoding="utf-8"))
        if "baseline" in prior.get("results", {}):
            results["baseline"] = prior["results"]["baseline"]  # 单臂续跑并入既有 B0
    if "baseline" in results:
        print("baseline: 复用既有 checkpoint", file=sys.stderr)

    for key in keys:
        trial = TRIALS[key]
        config = RankTrendConfig.from_patch(trial["overrides"])
        _assert_overrides_applied(config, trial["overrides"])
        results[key] = {"desc": trial["desc"], "overrides": trial["overrides"], "windows": {}, "track1": {}}
        for name, (start, end) in WINDOWS.items():
            wf = window_frames(frames, start, end)
            if not wf:
                results[key]["windows"][name] = {"empty": True}
                continue
            print(f"[{key}] {name}:", file=sys.stderr)
            reading, per_signal = evaluate_arm(
                config, wf, regime_by_snapshot if name == "decision" else None,
            )
            results[key]["windows"][name] = reading
            if name == "decision":
                per_signal_store[key] = per_signal  # 只进内存，迁移矩阵算完即弃（产物体积控制）
                results[key]["track1"]["decision"] = _track1(config, wf)
                m = results[key]["track1"]["decision"]
                print(f"[{key}] track1 decision: trades={m.get('tradeCount')} wrxpf={m.get('winRateXpf')} "
                      f"dd={m.get('maxDD')}", file=sys.stderr)
        # 逐臂 checkpoint（Q1 教训：最终序列化崩=全失）
        _flush(out_path, results, keys, t0, note=f"checkpoint after {key}")

    # 判定（合同 W1-1.2 冻结线）
    verdict: dict[str, dict] = {}
    base = results.get("baseline", {})
    base_windows = base.get("windows", {})
    b0_check = {w: {"anchor": B0_ANCHOR[w], "today": base_windows[w]["saEx"],
                    "match": abs(base_windows[w]["saEx"] - B0_ANCHOR[w]) < 5e-4}
                for w in B0_ANCHOR if w in base_windows and base_windows[w].get("saEx") is not None}
    verdict["b0_selfcheck"] = {"per_window": b0_check, "pass": bool(b0_check) and all(v["match"] for v in b0_check.values())}

    arm_verdicts: dict[str, dict] = {}
    for key in keys:
        if key == "baseline":
            continue
        if not b0_check or not verdict["b0_selfcheck"]["pass"]:
            verdict[key] = {"verdict": "INVALID_B0", "note": "B0 自证未过，全臂读数作废（合同 W1-1.1）"}
            continue
        sa = {w: results[key]["windows"][w].get("saEx") for w in ("decision", "oos1", "oos2")}
        rel = {w: (sa[w] / base_windows[w]["saEx"] - 1) if (sa[w] is not None and base_windows[w].get("saEx")) else None
               for w in sa}
        hard = {w: results[key]["windows"][w].get("passHard") for w in sa}
        c1 = rel["decision"] is not None and rel["decision"] >= 0.03
        c2 = rel["oos2"] is not None and rel["oos2"] > 0
        c3 = all(v is not False for v in hard.values())
        guard = {
            "resS_decision": results[key]["windows"]["decision"]["resSFrames"], "resS_line": GUARD_RES_S,
            "synS_decision": results[key]["windows"]["decision"]["synSFrames"], "synS_line": GUARD_SYN_S,
            "res_dist_identical": results[key]["windows"]["decision"]["resTierDist"]
            == base_windows["decision"]["resTierDist"],  # res 维不动的实现守卫
        }
        guard_pass = (guard["resS_decision"] >= GUARD_RES_S and guard["synS_decision"] >= GUARD_SYN_S
                      and guard["res_dist_identical"])
        tv = track1_verdict(results[key]["track1"]["decision"], base["track1"]["decision"])
        mkt = {
            "strong": {"arm": results[key]["windows"]["decision"].get("saEx_strong"),
                       "base": base_windows["decision"].get("saEx_strong")},
            "retreat": {"arm": results[key]["windows"]["decision"].get("saEx_retreat"),
                        "base": base_windows["decision"].get("saEx_retreat")},
        }
        mig = migration_matrix(per_signal_store.get("baseline", {}), per_signal_store.get(key, {}))
        v = {
            "saEx": sa, "rel": {w: round(v, 4) if v is not None else None for w, v in rel.items()},
            "c1_pass": c1, "c2_oos2_pass": c2, "c3_passhard": c3,
            "guardrail": {**guard, "pass": guard_pass},
            "track1": tv, "market_regime_disclosure": mkt,
            "syn_migration": mig,
            "verdict": ("PASS_CANDIDATE" if (c1 and c2 and c3 and guard_pass and tv["pass"]) else
                        "FAIL_C1" if not c1 else "FAIL_C2" if not c2 else "FAIL_C3" if not c3 else
                        "FAIL_GUARD" if not guard_pass else "FAIL_TRACK1"),
        }
        verdict[key] = v
        arm_verdicts[key] = v
    # 选臂机械化（合同 §二：两臂均过取三窗均值 rel 改善大者）
    passed = [k for k, v in arm_verdicts.items() if v.get("verdict") == "PASS_CANDIDATE"]
    if len(passed) > 1:
        def _mean_rel(k: str) -> float:
            vals = [arm_verdicts[k]["rel"][w] for w in ("decision", "oos1", "oos2") if arm_verdicts[k]["rel"][w] is not None]
            return sum(vals) / len(vals) if vals else float("-inf")
        verdict["arm_pick"] = {"rule": "均过取三窗均值 rel 改善大者", "passed": passed,
                               "pick": max(passed, key=_mean_rel)}
    elif passed:
        verdict["arm_pick"] = {"rule": "单臂过线", "passed": passed, "pick": passed[0]}
    else:
        verdict["arm_pick"] = {"rule": "无臂过线（阴性登记）", "passed": [], "pick": None}

    _flush(out_path, results, keys, t0, verdict=verdict, final=True)
    print(json.dumps({"out": str(out_path), "b0_selfcheck": verdict["b0_selfcheck"],
                      "arm_pick": verdict["arm_pick"],
                      "verdicts": {k: {kk: vv for kk, vv in v.items()
                                       if kk not in ("guardrail", "track1", "syn_migration", "market_regime_disclosure")}
                                   for k, v in verdict.items() if k not in ("b0_selfcheck", "arm_pick")}},
                     ensure_ascii=False, indent=1))


def _flush(out_path: Path, results: dict, keys: list[str], t0: float,
           verdict: dict | None = None, final: bool = False, note: str = "") -> None:
    out = {"meta": {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "elapsed_sec": round(time.time() - t0, 1), "partial": not final, "note": note,
                    "frozen": "vote-w11-res-dbuy-preregistration.md（B0 锚 0.1450/0.0983/0.1172；护栏 7185/64）"},
           "results": results, "verdict": verdict}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[flush] {'final' if final else 'partial'} -> {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
