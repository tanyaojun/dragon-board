# -*- coding: utf-8 -*-
"""四投票信号 T3（resonance warming 补票）/ T4（cs 持续高位独立档）行为步 trial runner（2026-10-07）。

合同：docs/ranktrend-tier-backtest/reasoning-corpus-voting-signals.md §12.2（判定线冻结）。
T3 剂量（单变量=cap 档）：W1 cap C（票 +0.375）→ W2 cap B（票 +0.525）；
T4 三态（单变量=A_PERSIST 强度）：正态 +1.0（票 +0.75）/ 零态 +0.5（票同 B=纯标签，
逐位一致工程验收）/ 负态 −0.5（票 −0.375，Track 1 终判）。
门判据同 T2 案（C1/C2/C3 + no-regression + Track 1），B0 锚 0.1450/0.0983/0.1172。

用法：python -m backend.operations.evaluate_voting_signals_t3_t4 [--trials w1,w2,t4pos,t4zero,t4neg] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.evaluate_voting_signals_t2 import (
    B0_ANCHOR,
    evaluate_trial,
    load_frames,
    window_frames,
)

TRIALS: dict[str, dict] = {
    "baseline": {"desc": "B0 自证（默认 config）", "overrides": {}},
    "w1": {"desc": "T3 warming cap C（票 +0.375）",
           "overrides": {"resonanceWarmingEnabled": True, "resonanceWarmingTierCap": "C"}},
    "w2": {"desc": "T3 warming cap B（票 +0.525）",
           "overrides": {"resonanceWarmingEnabled": True, "resonanceWarmingTierCap": "B"}},
    "t4pos": {"desc": "T4 A_PERSIST 正态 +1.0（票 +0.75）",
              "overrides": {"crossSectionPersistIndependentTier": True, "tierSynergyCsPersistStrength": 1.0}},
    "t4zero": {"desc": "T4 A_PERSIST 零态 +0.5（票同 B=纯标签，逐位一致验收）",
               "overrides": {"crossSectionPersistIndependentTier": True, "tierSynergyCsPersistStrength": 0.5}},
    "t4neg": {"desc": "T4 A_PERSIST 负态 −0.5（票 −0.375）",
              "overrides": {"crossSectionPersistIndependentTier": True, "tierSynergyCsPersistStrength": -0.5}},
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", default="baseline,w1", help="逗号分隔（W2 须 W1 过线；t4 顺序 pos→zero→neg）")
    ap.add_argument("--end", default="2026-09-12")
    ap.add_argument("--out", default="data/reports/voting-signals-t3t4-trials.json")
    args = ap.parse_args()
    keys = [k.strip() for k in args.trials.split(",") if k.strip()]
    for k in keys:
        if k not in TRIALS:
            raise SystemExit(f"未知 trial {k}（可选 {sorted(TRIALS)}）")
    t0 = time.time()
    frames = load_frames(args.end)
    print(f"frames={len(frames)} trials={keys}", file=sys.stderr)
    results: dict[str, dict] = {}
    out_path = Path(args.out)
    if "baseline" not in keys and out_path.exists():
        prior = json.loads(out_path.read_text(encoding="utf-8"))
        if "baseline" in prior.get("results", {}):
            results["baseline"] = prior["results"]["baseline"]
    for key in keys:
        trial = TRIALS[key]
        results[key] = {"desc": trial["desc"], "overrides": trial["overrides"], "windows": {}}
        for name, (start, end) in WINDOWS.items():
            wf = window_frames(frames, start, end)
            config = RankTrendConfig.from_patch(trial["overrides"])
            t1 = time.time()
            reading = evaluate_trial(config, wf)
            results[key]["windows"][name] = reading
            print(f"[{key}] {name}: saEx={reading['saEx']} resS={reading['resSFrames']} "
                  f"synS={reading['synSFrames']} ({time.time() - t1:.0f}s)", file=sys.stderr)

    verdict: dict[str, dict] = {}
    base = results.get("baseline", {}).get("windows", {})
    if base:
        b0_check = {w: {"anchor": B0_ANCHOR[w], "today": base[w]["saEx"],
                        "match": abs(base[w]["saEx"] - B0_ANCHOR[w]) < 5e-4} for w in B0_ANCHOR}
        verdict["b0_selfcheck"] = {"per_window": b0_check, "pass": all(v["match"] for v in b0_check.values())}
    for key in keys:
        if key == "baseline" or not base:
            continue
        sa = {w: results[key]["windows"][w]["saEx"] for w in ("decision", "oos1", "oos2")}
        rel = {w: (sa[w] / base[w]["saEx"] - 1) if (sa[w] is not None and base[w]["saEx"]) else None for w in sa}
        hard = {w: results[key]["windows"][w]["passHard"] for w in sa}
        c1 = rel["decision"] is not None and rel["decision"] >= 0.03
        c2 = rel["oos2"] is not None and rel["oos2"] > 0
        c3 = all(v is not False for v in hard.values())
        verdict[key] = {
            "saEx": sa, "rel": {w: round(v, 4) if v is not None else None for w, v in rel.items()},
            "c1_pass": c1, "c2_oos2_pass": c2, "c3_passhard": c3,
            "resS_decision": results[key]["windows"]["decision"]["resSFrames"],
            "synS_decision": results[key]["windows"]["decision"]["synSFrames"],
            "verdict": ("PASS_CANDIDATE" if (c1 and c2 and c3) else
                        "FAIL_C1" if not c1 else "FAIL_C2" if not c2 else "FAIL_C3"),
            "note": ("t4zero 验收=逐位一致（rel 三窗 |Δ|<1e-6 即 PASS）" if key == "t4zero" else None),
        }
        if key == "t4zero":
            identical = all(rel[w] is not None and abs(rel[w]) < 1e-6 for w in rel)
            verdict[key]["bitwise_identical"] = identical
            verdict[key]["verdict"] = "PASS_IDENTICAL" if identical else "DRIFT(工程回归)"

    out = {"meta": {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "elapsed_sec": round(time.time() - t0, 1),
                    "frozen": "reasoning-corpus-voting-signals.md §12.2（T3/T4 案；B0 锚同 T2）"},
           "results": results, "verdict": verdict}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out_path),
                      "verdicts": {k: {kk: vv for kk, vv in v.items()} for k, v in verdict.items()}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
