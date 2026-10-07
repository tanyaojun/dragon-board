# -*- coding: utf-8 -*-
"""四投票信号 T2（jumpConfirm vr 剂量）行为步 trial runner（2026-10-07 预登记合同）。

合同：docs/ranktrend-tier-backtest/reasoning-corpus-voting-signals.md §12.2（模型A 二轮
输出归档 voting-signals-modelA-round2-output.md T2 案；判定线冻结，跑后不得回看调线）。

trial（单轴单变量）：jumpConfirmVolumeRatioMin 1.0 → {1.25, 1.5}，一次一候选。
升档护栏（合同冻结）：res S 帧 ≥7,185（=R1 精确计数 14,370×50%）∧ synergy S ≥64
（=127×50%）∧ Track 1 S/A ≥30 笔（M2）——1.25 过护栏才跑 1.5。

门判据（第一步=B0 基线自证：默认 config 三窗逐位复现生命周期轮 G1 锚 0.1450/0.0983/0.1172）：
- 主判定线：C1（decision saEx rel ≥+3%）∧ C2（oos2 同向正；oos1 照登不 gate）∧ C3（passHard 不降）；
- S 纯度线：arm res-S 子集 h8 ≥ 基线 res-S −0.01（h8 线属前置参考，主判定=判定卡+Track 1）；
- no-regression：Track 1 wrxpf rel ≥0（终判）；jump 放行率只登记；
- 终止：passHard 任窗崩；Track 1 wrxpf <−5%。

用法：python -m backend.operations.evaluate_voting_signals_t2 [--trials vr125,vr150] [--out <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.evaluate_ts_factor_weights import WINDOWS
from backend.operations.optimize_gate_denoise_parameters import collect_flip_report, sa_excess_of
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS
from backend.analysis.ranktrend.tier_monotonicity import tier_forward_returns

B0_ANCHOR = {"decision": 0.1450, "oos1": 0.0983, "oos2": 0.1172}  # 生命周期轮 G1 行（现默认）
GUARD_RES_S = 7185   # 14,370 × 50%
GUARD_SYN_S = 64     # 127 × 50%

TRIALS: dict[str, dict] = {
    "baseline": {"desc": "B0 自证（默认 config = G1 cross_day）", "overrides": {}},
    "vr125": {"desc": "T2 jumpConfirmVolumeRatioMin 1.0→1.25", "overrides": {"jumpConfirmVolumeRatioMin": 1.25}},
    "vr150": {"desc": "T2 jumpConfirmVolumeRatioMin 1.0→1.5（升档须过护栏）", "overrides": {"jumpConfirmVolumeRatioMin": 1.5}},
}


def load_frames(end: str = "2026-09-12") -> list[dict]:
    # 合同 population =「951 帧全窗」（§12.2，与生命周期轮锚体系一致：oos2=09-01~09-12）。
    # data_windows.WINDOWS 的 oos2 名义上到 09-30，但 B0 锚 0.1450/0.0983/0.1172 的
    # oos2 分量是 09-12 帧截止口径（生命周期轮 loader end=09-12）——锚必须与 population
    # 同口径复现（2026-10-07 首跑实证：全月 oos2 基线 0.1057≠0.1172，decision/oos1 逐位合）。
    repo = MongoRepository(get_runtime_mongodb_database())
    return repo.load_frame_bundles(
        "dragonboard_live", snapshot_type="half_hour",
        start_date="2026-04-15", end_date=end,
        projection="ranktrend", fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )


def window_frames(frames: list[dict], start: str, end: str) -> list[dict]:
    return [f for f in frames if start <= str(f.get("tradingDate") or "") <= end]


def evaluate_trial(config: RankTrendConfig, frames: list[dict]) -> dict:
    engine = RankTrendPythonEngine(config=config)
    signals = engine.replay(frames, meta={})
    syn = tier_forward_returns(signals, frames, horizon=1, dimension="synergy")
    flip = collect_flip_report(signals)
    res_s = 0
    syn_s = 0
    jump_pass = 0
    jump_total = 0
    for s in signals:
        obs = (s.get("rankTrend") or {}).get("observation") or {}
        res = (s.get("rankTrend") or {}).get("resonance") or {}
        res_s += 1 if res.get("signalTier") == "S" else 0
        syn_s += 1 if (obs.get("synergy") or {}).get("signalTier") == "S" else 0
        vp = obs.get("volumePrice") or {}
        if vp.get("signalTier") == "E":
            pass
        res_dir = res.get("direction")
        if res_dir in ("buy", "sell"):
            jump_total += 1
            if res.get("status") == "ok" and res.get("jumpFreshness", 0) > 0:
                jump_pass += 1
    return {
        "signalCount": len(signals),
        "saEx": sa_excess_of(syn),
        "passHard": syn.get("monotonicity", {}).get("hardPass", syn.get("monotonicity", {}).get("ok")),
        "monotonicity": syn.get("monotonicity"),
        "flipRates": flip,
        "resSFrames": res_s,
        "synSFrames": syn_s,
        "resDirectionFrames": jump_total,
        "_note_jump_pass": "jump 放行率口径受限（resonance 输出不含 confirmed 布尔），用 jumpFreshness>0 ∧ status=ok 近似——只登记不判定",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", default="baseline,vr125", help="逗号分隔；vr150 须护栏过线后单独跑（合同升档门控）")
    ap.add_argument("--end", default="2026-09-12", help="帧截止（合同 population=951 帧全窗=09-12；09-30 仅作敏感性）")
    ap.add_argument("--out", default="data/reports/voting-signals-t2-trials.json")
    args = ap.parse_args()
    keys = [k.strip() for k in args.trials.split(",") if k.strip()]
    for k in keys:
        if k not in TRIALS:
            raise SystemExit(f"未知 trial {k}（可选 {sorted(TRIALS)}）")
    t0 = time.time()
    frames = load_frames(args.end)
    print(f"frames={len(frames)} trials={keys}", file=sys.stderr)
    results: dict[str, dict] = {}
    out_path0 = Path(args.out)
    if "baseline" not in keys and out_path0.exists():
        prior = json.loads(out_path0.read_text(encoding="utf-8"))
        if "baseline" in prior.get("results", {}):
            results["baseline"] = prior["results"]["baseline"]  # 判定需要基线；单臂续跑时并入既有 B0
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

    # 判定（冻结线；B0 自证 + C1/C2/C3 + 护栏读数）
    verdict: dict[str, dict] = {}
    base = results.get("baseline", {}).get("windows", {})
    b0_check = {w: {"anchor": B0_ANCHOR[w], "today": base[w]["saEx"], "match": abs(base[w]["saEx"] - B0_ANCHOR[w]) < 5e-4}
                for w in B0_ANCHOR} if base else {}
    verdict["b0_selfcheck"] = {"per_window": b0_check, "pass": all(v["match"] for v in b0_check.values())} if b0_check else {"note": "baseline 未跑"}
    for key in keys:
        if key == "baseline":
            continue
        sa = {w: results[key]["windows"][w]["saEx"] for w in ("decision", "oos1", "oos2")}
        rel = {w: (sa[w] / base[w]["saEx"] - 1) if (sa[w] is not None and base[w]["saEx"]) else None
               for w in sa}
        hard = {w: results[key]["windows"][w]["passHard"] for w in sa}
        c1 = rel["decision"] is not None and rel["decision"] >= 0.03
        c2 = rel["oos2"] is not None and rel["oos2"] > 0
        c3 = all(v is not False for v in hard.values())
        guard = {
            "resS_decision": results[key]["windows"]["decision"]["resSFrames"],
            "resS_line": GUARD_RES_S,
            "synS_decision": results[key]["windows"]["decision"]["synSFrames"],
            "synS_line": GUARD_SYN_S,
            "track1_SA_note": "Track 1 tradeCount≥30 见 track1 extra-arm 报告（另行执行）",
        }
        guard_pass = guard["resS_decision"] >= GUARD_RES_S and guard["synS_decision"] >= GUARD_SYN_S
        verdict[key] = {
            "saEx": sa, "rel": {w: round(v, 4) if v is not None else None for w, v in rel.items()},
            "c1_pass": c1, "c2_oos2_pass": c2, "c3_passhard": c3,
            "guardrail": guard, "guardrail_pass": guard_pass,
            "verdict": ("PASS_CANDIDATE" if (c1 and c2 and c3) else
                        "FAIL_C1" if not c1 else "FAIL_C2" if not c2 else "FAIL_C3"),
            "upgrade_note": "升 1.5 须 guardrail_pass ∧ Track 1 复核" if key == "vr125" else None,
        }

    out = {"meta": {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "elapsed_sec": round(time.time() - t0, 1),
                    "frozen": "reasoning-corpus-voting-signals.md §12.2 T2 案（B0 锚 0.1450/0.0983/0.1172；护栏 7185/64/M2-30）"},
           "results": results, "verdict": verdict}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"out": str(out_path), "b0_selfcheck": verdict["b0_selfcheck"],
                      "verdicts": {k: {kk: vv for kk, vv in v.items() if kk != "guardrail"}
                                   for k, v in verdict.items() if k != "b0_selfcheck"}},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
