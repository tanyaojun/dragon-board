# -*- coding: utf-8 -*-
"""生命周期 P5 双轴重设计诊断步（backend/operations，2026-10-07）。

P5 出处：reasoning-corpus-lifecycle-stage.md §11（Opus 首轮提案裁定「论证级合规——
前置四项设计完整；与 U 形证据一致的非单调离散门」；前置四项=stage×分位列联/互信息
可从 replay 导出）+ gate-redesign-proposal §4（方案 B：path×action 拆轴+连续分门控，
score 单调化 FAIL 后收缩形态=非单调离散门）。

一次默认配置全窗 replay（只读，零行为变化，零 config 写回），产出四件诊断（P5 前置四项）：
- D1 stage×pct 分位列联表 + 互信息 I(stage;pct_band)（shuffle 基线，seed 冻结）
  ——「tier 构成由分位带决定」（§4.1-E 结构根因）的定量版；
- D2 stage×velocity（动量轴）分布与重叠率——两轴是否正交可分；
- D3 score 分位桶 fwd 结构（U 形复现，decision 窗分位基准）+ stage×(pct带×velocity档)
  2D 单元格 fwd 证据——非单调门重画的依据；
- D4 action 面信息含量（veto/caution/allow/exit_watch × fwd）与 stage/pct 重叠率
  ——拆轴后 action 轴独立信息量。

fwd 口径：h1/h8 = 该股后续第 1/8 个「有 rank 帧」的 pct 差（分位点，与 D1 框架同族）。
窗口：decision 04-15~07-31（分位基准+主读数）/ 全窗披露列；fwd 跨窗用全窗 pct_at。

用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.diagnose_lifecycle_p5_dual_axis \
      [--out data/reports/lifecycle-p5-dual-axis-diagnosis.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.operations.evaluate_lifecycle_q1_trials import (
    FULL_WINDOW,
    build_pct_tables,
    load_frames,
    window_frames,
)
from backend.operations.evaluate_ts_factor_weights import WINDOWS

SHUFFLE_SEED = 20261007
SHUFFLE_ITERS = 200
SCORE_BUCKETS = 5
PCT_BANDS = 10  # pct 10 带（0-10,10-20,...,90-100）
HORIZONS = (1, 8)
STAGES = ("cooling", "ignition", "expansion", "crowded", "reversal")
ACTIONS = ("veto", "caution", "allow", "exit_watch")


def _fwd(pct_at: dict, fi: int, code: str, frame_count: int, horizon: int) -> float | None:
    """该股后续第 horizon 个有 rank 帧的 pct 差（None=后续不足）。"""
    seen = 0
    prev = pct_at.get((fi, code))
    j = fi + 1
    while j < frame_count:
        nxt = pct_at.get((j, code))
        if nxt is not None and prev is not None:
            seen += 1
            if seen == horizon:
                return nxt - prev
            prev = nxt
        j += 1
    return None


def pct_band(pct: float) -> int:
    return min(PCT_BANDS - 1, max(0, int(pct // 10)))


def velocity_band(v: float | None) -> str:
    if v is None:
        return "none"
    if v > 5:
        return "up_fast"
    if v > 0:
        return "up_slow"
    if v == 0:
        return "flat"
    if v > -5:
        return "down_slow"
    return "down_fast"


def mutual_information(stage_labels: list[str], band_labels: list[int]) -> dict:
    """I(stage;pct_band) nats + shuffle 基线（打乱 stage，同边际）。"""
    n = len(stage_labels)
    if n == 0:
        return {"mi": None, "shuffle_mean": None, "shuffle_std": None, "n": 0}
    joint: dict[tuple[str, int], int] = defaultdict(int)
    s_cnt: dict[str, int] = defaultdict(int)
    b_cnt: dict[int, int] = defaultdict(int)
    for s, b in zip(stage_labels, band_labels):
        joint[(s, b)] += 1
        s_cnt[s] += 1
        b_cnt[b] += 1
    mi = 0.0
    for (s, b), c in joint.items():
        p = c / n
        mi += p * math.log(p / ((s_cnt[s] / n) * (b_cnt[b] / n)))
    rng = np.random.default_rng(SHUFFLE_SEED)
    arr = np.array(band_labels)
    shuffled = []
    stage_arr = np.array(stage_labels)
    for _ in range(SHUFFLE_ITERS):
        rng.shuffle(arr)
        m = 0.0
        j2: dict[tuple[str, int], int] = defaultdict(int)
        for s, b in zip(stage_arr, arr):
            j2[(s, int(b))] += 1
        for (s, b), c in j2.items():
            p = c / n
            m += p * math.log(p / ((s_cnt[s] / n) * (b_cnt[int(b)] / n)))
        shuffled.append(m)
    return {
        "mi": round(mi, 4),
        "shuffle_mean": round(float(np.mean(shuffled)), 4),
        "shuffle_std": round(float(np.std(shuffled)), 4),
        "n": n,
        "note": "互信息以 decision 窗帧为样本；shuffle=打乱 stage 同边际（seed 20261007）",
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/reports/lifecycle-p5-dual-axis-diagnosis.json")
    args = ap.parse_args()
    t0 = time.time()
    frames = load_frames()
    print(f"frames={len(frames)}", file=sys.stderr)
    frame_count = len(frames)
    decision_frames = window_frames(frames, *WINDOWS["decision"])
    decision_index = {id(f): i for i, f in enumerate(frames) if WINDOWS["decision"][0] <= str(f.get("tradingDate") or "") <= WINDOWS["decision"][1]}
    decision_set = set(decision_index.values())

    pct_at, _ = build_pct_tables(frames)

    # 一次默认 replay 全窗导出（signal 顶层 code/snapshotId/tradingDate）
    engine = RankTrendPythonEngine(config=RankTrendConfig())
    signals = engine.replay(frames, meta={})
    print(f"signals={len(signals)} ({time.time() - t0:.0f}s)", file=sys.stderr)

    index_by_snapshot = {str(f.get("snapshotId")): i for i, f in enumerate(frames)}
    rows: list[dict] = []
    for s in signals:
        rt = s.get("rankTrend") or {}
        cycle = rt.get("cycle") or {}
        obs = (rt.get("observation") or {}).get("lifecycle") or {}
        fi = index_by_snapshot.get(str(s.get("snapshotId")), -1)
        code = str(s.get("code") or "")
        if fi < 0 or not code:
            continue
        m = cycle.get("metrics") or {}
        row = {
            "fi": fi,
            "code": code,
            "in_decision": fi in decision_set,
            "pct": pct_at.get((fi, code)),
            "velocity": m.get("rankVelocity"),
            "accel": m.get("rankAcceleration"),
            "drawdown": m.get("drawdownFromPeak"),
            "hot": m.get("hotZoneStreak"),
            "best": m.get("bestRecentRank"),
            "stage": cycle.get("stage"),
            "rawStage": cycle.get("rawStage"),
            "action": (cycle.get("decision") or {}).get("action"),
            "lcTier": obs.get("signalTier"),
            "score": obs.get("score"),
        }
        for h in HORIZONS:
            row[f"fwd{h}"] = _fwd(pct_at, fi, code, frame_count, h)
        rows.append(row)
    print(f"rows={len(rows)} ({time.time() - t0:.0f}s)", file=sys.stderr)

    dec = [r for r in rows if r["in_decision"] and r["pct"] is not None]
    out: dict = {"meta": {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "full_window": list(FULL_WINDOW),
        "frames": frame_count, "signals": len(signals), "rows_decision": len(dec),
        "score_buckets": SCORE_BUCKETS, "pct_bands": PCT_BANDS, "horizons": list(HORIZONS),
        "shuffle_seed": SHUFFLE_SEED, "shuffle_iters": SHUFFLE_ITERS,
        "elapsed_sec": round(time.time() - t0, 1),
    }}

    # ── D1 stage×pct 列联 + 互信息 ──
    cont = {s: {b: 0 for b in range(PCT_BANDS)} for s in STAGES}
    for r in dec:
        st = r["stage"]
        if st in cont:
            cont[st][pct_band(r["pct"])] += 1
    out["D1_stage_pct"] = {
        "contingency": cont,
        "mutual_info": mutual_information([r["stage"] for r in dec if r["stage"] in STAGES],
                                          [pct_band(r["pct"]) for r in dec if r["stage"] in STAGES]),
        "stage_counts": {s: sum(cont[s].values()) for s in STAGES},
    }

    # ── D2 stage×velocity 分布与重叠 ──
    vel_by_stage: dict[str, list[float]] = defaultdict(list)
    for r in dec:
        if r["stage"] in STAGES and isinstance(r["velocity"], (int, float)):
            vel_by_stage[r["stage"]].append(float(r["velocity"]))
    d2 = {}
    for s in STAGES:
        arr = np.array(vel_by_stage.get(s) or [np.nan])
        arr = arr[~np.isnan(arr)]
        d2[s] = {
            "n": int(arr.size),
            "p10": round(float(np.percentile(arr, 10)), 2) if arr.size else None,
            "p50": round(float(np.percentile(arr, 50)), 2) if arr.size else None,
            "p90": round(float(np.percentile(arr, 90)), 2) if arr.size else None,
            "mean": round(float(arr.mean()), 3) if arr.size else None,
        }
    out["D2_stage_velocity"] = d2

    # ── D3 score 分位桶 U 形 + 2D 单元格 fwd 证据 ──
    scored = [r for r in dec if isinstance(r["score"], (int, float))]
    if scored:
        scores = np.array([r["score"] for r in scored])
        edges = np.percentile(scores, np.linspace(0, 100, SCORE_BUCKETS + 1))
        edges[0], edges[-1] = -np.inf, np.inf
        bucket_rows: dict[int, list[dict]] = defaultdict(list)
        for r in scored:
            b = int(np.searchsorted(edges, r["score"], side="right") - 1)
            bucket_rows[max(0, min(SCORE_BUCKETS - 1, b))].append(r)
        d3_score = {}
        for b in range(SCORE_BUCKETS):
            rs = bucket_rows.get(b) or []
            entry = {"n": len(rs), "score_range": [round(float(edges[b]), 1), round(float(edges[b + 1]), 1)]}
            for h in HORIZONS:
                vals = [r[f"fwd{h}"] for r in rs if isinstance(r.get(f"fwd{h}"), (int, float))]
                entry[f"fwd{h}_mean"] = round(float(np.mean(vals)), 4) if vals else None
                entry[f"fwd{h}_n"] = len(vals)
            d3_score[f"b{b}"] = entry
        out["D3_score_buckets"] = {
            "buckets": d3_score,
            "note": "score 分位桶（decision 窗分位基准）；U 形假设=首末桶 fwd 结构优于中间桶",
        }
    # 2D 单元格：pct 带 × velocity 档（decision 窗）
    cells: dict[str, dict] = defaultdict(lambda: {"n": 0, "fwd1": [], "fwd8": []})
    for r in dec:
        if r["pct"] is None:
            continue
        key = f"pct{pct_band(r['pct'])}|{velocity_band(r['velocity'])}"
        c = cells[key]
        c["n"] += 1
        for h in HORIZONS:
            if isinstance(r.get(f"fwd{h}"), (int, float)):
                c[f"fwd{h}"].append(r[f"fwd{h}"])
    d3_cells = {}
    for key, c in sorted(cells.items()):
        d3_cells[key] = {"n": c["n"],
                         "fwd1_mean": round(float(np.mean(c["fwd1"])), 4) if c["fwd1"] else None,
                         "fwd8_mean": round(float(np.mean(c["fwd8"])), 4) if c["fwd8"] else None}
    out["D3_cells_pct_velocity"] = d3_cells

    # ── D4 action 面信息含量 ──
    d4 = {}
    for a in ACTIONS:
        rs = [r for r in dec if r["action"] == a]
        entry = {"n": len(rs)}
        for h in HORIZONS:
            vals = [r[f"fwd{h}"] for r in rs if isinstance(r.get(f"fwd{h}"), (int, float))]
            entry[f"fwd{h}_mean"] = round(float(np.mean(vals)), 4) if vals else None
        # 动作内 pct 分布（重叠率：action 与 pct 带的互信息）
        d4[a] = entry
    out["D4_action_content"] = {
        "actions": d4,
        "action_stage_cross": {
            f"{a}|{s}": sum(1 for r in dec if r["action"] == a and r["stage"] == s)
            for a in ACTIONS for s in STAGES
        },
        "action_pct_mi": mutual_information([r["action"] for r in dec if r["action"] in ACTIONS],
                                            [pct_band(r["pct"]) for r in dec if r["action"] in ACTIONS]),
        "note": "action 轴与 stage 轴的交叉近对角=veto 腿由 reversal 主导（拆轴增量在 caution/allow 的分位结构）",
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(json.dumps({"out": str(out_path),
                      "D1_mi": out["D1_stage_pct"]["mutual_info"],
                      "D3_score_buckets": {k: v.get("fwd1_mean") for k, v in out.get("D3_score_buckets", {}).get("buckets", {}).items()},
                      "D4_actions": {k: v.get("n") for k, v in out["D4_action_content"]["actions"].items()}},
                     ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
