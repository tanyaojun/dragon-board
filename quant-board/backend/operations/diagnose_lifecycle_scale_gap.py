# -*- coding: utf-8 -*-
"""生命周期 P1（池规尺度）/ P3（时间缺口）诊断步（backend/operations，2026-10-07）。

预登记合同：docs/ranktrend-tier-backtest/reasoning-corpus-lifecycle-stage.md §11.1/§11.2
（判定线冻结，跑后不得回看调线）；Opus 4.8 第二轮输出归档 lifecycle-stage-opus-round2-output.md。

一次默认配置数据 pass，产出两案诊断 schema（只读，零行为变化，零 config 写回）：
- P3/A4·B4：时间缺口对（G1=跨日 / G2=跨日∨同日非相邻）富集检验
  ER = P(gap_origin | velocity>lifecycleVelocityMin) / P(gap_origin)，
  按 code 聚块 bootstrap 95% CI（1 万次，seed 冻结）；
- P1：绝对名次谓词 vs T=200 锚等价分位谓词的分歧表 + 末态（stage/tier/veto/bd）双风味分歧。
  pct 风味在 metric 层换算（rank ⇔ pct=(201-R)/2 @T=200；drawdown 1 格=0.5 pct 点），
  复用同一套阈值常量——等价于把名次类阈值整体换算为分位线（合同 A5 L2 语义）。

窗口（合同 A3）：decision 04-15~07-31 / midgap 08-01~08-14（frozen-only）/
oos1 08-15~08-31 / oos2 09-01~09-12；frozen=midgap∪oos1（仅过程指标对账，不设线）。
主判定 population 预声明（§11.2 审定后、跑数前冻结）：decision 窗、序列长度≥2 的股帧。

市况分桶（合同 A10 偏差如实登记）：帧投影无 hotlistSentiment → 用 market_regime 池内因子
state（strong/normal/weak/retreat）替代热榜情绪 stage，仅报告列，不进判定线。

用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.diagnose_lifecycle_scale_gap \
      [--end 2026-09-12] [--out data/reports/lifecycle-scale-gap-diagnosis.json] [--skip-engine-check]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.engine.primitives import attention_rank_lookup, percentile_rank
from backend.analysis.ranktrend.engine.runtime import _lifecycle_tier
from backend.analysis.ranktrend.trend.lifecycle import (
    analyze_cycle,
    cycle_confidence,
    lifecycle_decision,
    normalize_stage,
    raw_stage,
)
from backend.analysis.ranktrend.trend.risk import analyze_risk, market_regime
from backend.analysis.ranktrend.trend.technical import analyze_technical
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.services.shared import BACKTEST_RANKTREND_STOCK_FIELDS

BOOTSTRAP_SEED = 20261007  # 合同 B2：种子冻结于脚本常量
BOOTSTRAP_ITERS = 10_000
HISTORY_WINDOW = 50  # replay 默认窗口（runtime.replay_frame_at window_size=50）
METRICS_WINDOW = 8   # cycle_metrics 尾窗

BEST_LE_KEYS = (5, 10, 12, 20, 25, 30)
DRAWDOWN_GE_KEYS = (1, 2, 3)

WINDOW_RANGES = (
    ("decision", "2026-04-15", "2026-07-31"),
    ("midgap", "2026-08-01", "2026-08-14"),
    ("oos1", "2026-08-15", "2026-08-31"),
    ("oos2", "2026-09-01", "2026-09-12"),
)


def window_label(trading_date: str) -> str:
    for label, start, end in WINDOW_RANGES:
        if start <= trading_date <= end:
            return label
    return "outside"


def cycle_metrics_window_flavored(
    rank_window: list[float],
    percentile_window: list[float],
    *,
    rank_scale_mode: str,
) -> dict[str, float]:
    """混合/pct 双风味 metrics（P1）。

    mixed = 现行为（名次/分位双口径）；pct = 名次谓词整体换算 T=200 等价分位线：
    bestRecentRank→201−2·max(pct窗)，drawdownFromPeak→2·max(0, max−cur)，热区仅 pct≥88 臂。
    velocity/acceleration/shock/pathCommitment 本就是分位单位，两风味相同。
    """
    current_rank = rank_window[-1] if rank_window else 999
    hot_streak = 0
    for rank, percentile in zip(reversed(rank_window), reversed(percentile_window)):
        hot = rank <= 10 or percentile >= 88
        if rank_scale_mode == "pct":
            hot = percentile >= 88
        if hot:
            hot_streak += 1
        else:
            break
    count = len(percentile_window)
    velocity = percentile_window[-1] - percentile_window[-2] if count >= 2 else 0
    previous_velocity = percentile_window[-2] - percentile_window[-3] if count >= 3 else 0
    if rank_scale_mode == "mixed":
        best = min(rank_window) if rank_window else current_rank
        drawdown = max(0, current_rank - best)
    else:
        max_pct = max(percentile_window) if percentile_window else 0.0
        best = 201.0 - 2.0 * max_pct
        drawdown = 2.0 * max(0.0, max_pct - percentile_window[-1] if percentile_window else 0.0)
    return {
        "rankVelocity": velocity,
        "rankAcceleration": velocity - previous_velocity,
        "rankShock": _cycle_rank_shock(percentile_window),
        "hotZoneStreak": hot_streak,
        "bestRecentRank": best,
        "drawdownFromPeak": drawdown,
        "rankPathCommitment": _rank_path_commitment(percentile_window),
    }


def _cycle_rank_shock(percentiles: list[float]) -> float:
    count = len(percentiles)
    if count < 6:
        return 0.0
    recent = [percentiles[j] - percentiles[j - 1] for j in range(count - 5, count)]
    current = recent[-1]
    mean = sum(recent) / len(recent)
    variance = sum((v - mean) ** 2 for v in recent) / len(recent)
    std = variance ** 0.5
    return 0.0 if not np.isfinite(std) or std < 1e-6 else (current - mean) / std


def _rank_path_commitment(percentiles: list[float]) -> float:
    if len(percentiles) < 4:
        return 0.5
    window = percentiles[-8:]
    total_improvement = max(0.0, window[-1] - window[0])
    if total_improvement <= 0:
        return 0.0
    steps = [window[index] - window[index - 1] for index in range(1, len(window))]
    positive_steps = [step for step in steps if step > 0]
    last_step = max(0.0, steps[-1] if steps else 0.0)
    pre_breakout_improvement = sum(positive_steps[:-1])
    positive_step_share = len(positive_steps) / max(1, len(steps))
    pre_breakout_share = pre_breakout_improvement / max(total_improvement, 1)
    last_step_dominance = last_step / max(total_improvement, 1)
    value = positive_step_share * 0.45 + pre_breakout_share * 0.45 + (1 - last_step_dominance) * 0.1
    return max(0.0, min(1.0, value))


def run_cycle_sequence(
    ranks: list[float],
    percentiles: list[float],
    config: RankTrendConfig,
    rank_scale_mode: str,
) -> dict:
    """analyze_cycle 同构逐步重放（混合链必须与 analyze_cycle 逐位一致，自证见 main）。"""
    previous_stage = None
    current_stage = None
    current_raw = None
    previous_normalized = None
    metrics: dict[str, float] = {}
    steps: list[dict] = []
    for index in range(len(percentiles)):
        window_start = index - 7 if index >= 7 else 0
        metrics = cycle_metrics_window_flavored(
            ranks[window_start : index + 1],
            percentiles[window_start : index + 1],
            rank_scale_mode=rank_scale_mode,
        )
        r = raw_stage(index + 1, percentiles[index], metrics, config=config)
        normalized = normalize_stage(current_stage, r, percentiles[index], metrics, config=config)
        previous_stage = current_raw
        previous_normalized = current_stage
        current_raw = r
        current_stage = normalized
        steps.append(
            {
                "raw": r,
                "stage": normalized,
                "prev_stage": previous_normalized,
                "metrics": metrics,
            }
        )
    stage = current_stage or "cooling"
    raw = current_raw or "cooling"
    transition = stage if not previous_normalized or previous_normalized == stage else f"{previous_normalized}->{stage}"
    confidence = cycle_confidence(stage, percentiles[-1] if percentiles else 0, metrics, config=config)
    if not metrics:
        metrics = {
            "rankVelocity": 0, "rankAcceleration": 0, "rankShock": 0, "hotZoneStreak": 0,
            "bestRecentRank": ranks[-1] if ranks else 999, "drawdownFromPeak": 0,
            "rankPathCommitment": 0.5,
        }
    return {"stage": stage, "rawStage": raw, "transition": transition, "confidence": confidence,
            "metrics": metrics, "steps": steps}


def pct_verdicts(percentile_window: list[float], pct_now: float) -> dict[str, bool]:
    max_pct = max(percentile_window) if percentile_window else 0.0
    best_equiv = 201.0 - 2.0 * max_pct
    dd_equiv = 2.0 * max(0.0, max_pct - pct_now) if percentile_window else 0.0
    out = {
        "warm": pct_now >= 65.0 or best_equiv <= 25.0,
        "hotzone": pct_now >= 85.0 or best_equiv <= 10.0,
    }
    for k in BEST_LE_KEYS:
        out[f"best_le_{k}"] = best_equiv <= k
    for d in DRAWDOWN_GE_KEYS:
        out[f"drawdown_ge_{d}"] = dd_equiv >= d
    return out


def mixed_verdicts(rank_window: list[float], percentile_window: list[float], pct_now: float) -> dict[str, bool]:
    best = min(rank_window) if rank_window else 999
    dd = max(0, (rank_window[-1] if rank_window else 999) - best)
    out = {
        "warm": pct_now >= 65.0 or best <= 25.0,
        "hotzone": pct_now >= 85.0 or best <= 10.0,
    }
    for k in BEST_LE_KEYS:
        out[f"best_le_{k}"] = best <= k
    for d in DRAWDOWN_GE_KEYS:
        out[f"drawdown_ge_{d}"] = dd >= d
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-15")
    ap.add_argument("--end", default="2026-09-12")
    ap.add_argument("--out", default="data/reports/lifecycle-scale-gap-diagnosis.json")
    ap.add_argument("--skip-engine-check", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    config = RankTrendConfig()
    vel_min = float(config.lifecycleVelocityMin)

    repo = MongoRepository(get_runtime_mongodb_database())
    frames = repo.load_frame_bundles(
        "dragonboard_live", snapshot_type="half_hour",
        start_date=args.start, end_date=args.end,
        projection="ranktrend", fields=list(BACKTEST_RANKTREND_STOCK_FIELDS),
    )
    frames.sort(key=lambda f: (str(f.get("tradingDate") or ""), str(f.get("slotTime") or "")))
    frame_dates = [str(f.get("tradingDate") or "") for f in frames]
    labels = [window_label(d) for d in frame_dates]
    regime_states = [str(market_regime(f, config).get("state") or "missing") for f in frames]
    attention_maps = [attention_rank_lookup(f.get("stocks") or []) for f in frames]
    print(f"frames={len(frames)} labels={Counter(labels)} regimes={Counter(regime_states)}", file=sys.stderr)

    # ── L0 自证 A：inline 混合链 vs analyze_cycle（抽样 2000 股帧）──
    # ── L0 自证 B：混合末态 vs 引擎 replay_frame_at（3 帧）──
    inline_mismatch = 0
    inline_checked = 0
    engine_compare = {"frames_checked": 0, "stocks_compared": 0, "stage_match": 0, "tier_match": 0}

    # 聚合容器
    t_by_window: dict[str, list[float]] = defaultdict(list)
    t_by_window_regime: Counter = Counter()
    pred_dis: dict[str, dict] = defaultdict(lambda: {"n": 0, "dis": 0, "looser": 0, "tighter": 0,
                                                     "by_tercile": defaultdict(lambda: [0, 0])})
    end_dis: dict[str, dict] = defaultdict(lambda: {"n": 0, "dis": 0, "by_tercile": defaultdict(lambda: [0, 0])})
    series_lt2 = 0
    stock_frames_total = 0
    # P3
    pair_gap: dict[str, Counter] = defaultdict(Counter)      # window -> {n, g1, g2}
    pair_delta: dict[str, dict] = defaultdict(lambda: {"gap": [], "nogap": []})
    frame_rows: dict[str, list] = defaultdict(list)           # window -> rows for ER / tails
    trans_gap: dict[str, Counter] = defaultdict(Counter)      # window -> {trans -> [n, gap]}
    veto_bd_gap: dict[str, Counter] = defaultdict(Counter)    # window -> {veto/bd -> [n, gap]}

    def add_pred(key: str, mixed: bool, pct: bool, tercile: int) -> None:
        d = pred_dis[key]
        d["n"] += 1
        if mixed != pct:
            d["dis"] += 1
            d["by_tercile"][tercile][1] += 1
        d["by_tercile"][tercile][0] += 1
        if pct and not mixed:
            d["looser"] += 1
        if mixed and not pct:
            d["tighter"] += 1

    def add_end(key: str, mixed_v, pct_v, tercile: int) -> None:
        d = end_dis[key]
        d["n"] += 1
        if mixed_v != pct_v:
            d["dis"] += 1
            d["by_tercile"][tercile][1] += 1
        d["by_tercile"][tercile][0] += 1

    # T 三分位切点先冻结（帧级 T 全窗分布）——先扫一遍帧级 T
    frame_totals = []
    for fi, frame in enumerate(frames):
        _ranks_map, total = attention_maps[fi]
        frame_totals.append(float(total))
    tercile_cuts = [float(np.percentile(frame_totals, 100 / 3)), float(np.percentile(frame_totals, 200 / 3))]

    engine = None if args.skip_engine_check else RankTrendPythonEngine(config=config)
    engine_check_indices = [] if args.skip_engine_check else [len(frames) // 2, len(frames) // 2 + 1, len(frames) - 2]

    for fi, frame in enumerate(frames):
        label = labels[fi]
        date = frame_dates[fi]
        regime = regime_states[fi]
        ranks_map, total = attention_maps[fi]
        t_by_window[label].append(float(total))
        t_by_window_regime[f"{label}|{regime}"] += 1
        history_start = max(0, fi - HISTORY_WINDOW + 1)
        slot = str(frame.get("slotTime") or "")

        if not args.skip_engine_check and fi in engine_check_indices:
            engine_signals = {
                str(s.get("code")): ((s.get("rankTrend") or {}).get("observation") or {}).get("lifecycle") or {}
                for s in engine.replay_frame_at(frames, fi, window_size=HISTORY_WINDOW)
            }

        for stock in frame.get("stocks") or []:
            code = str(stock.get("code") or "")
            if not code:
                continue
            ranks: list[float] = []
            pcts: list[float] = []
            elem_dates: list[str] = []
            elem_slots: list[str] = []
            elem_fi: list[int] = []
            for hj in range(history_start, fi + 1):
                r = attention_maps[hj][0].get(code)
                if r is None:
                    continue
                ranks.append(float(r))
                pcts.append(percentile_rank(float(r), attention_maps[hj][1]))
                elem_dates.append(frame_dates[hj])
                elem_slots.append(str(frames[hj].get("slotTime") or ""))
                elem_fi.append(hj)
            stock_frames_total += 1
            if len(pcts) < 2:
                series_lt2 += 1
                continue
            pct_now = pcts[-1]
            tercile = 0 if total <= tercile_cuts[0] else (1 if total <= tercile_cuts[1] else 2)

            # L0 自证 A（抽样）：inline 混合链 ≡ analyze_cycle
            if inline_checked < 2000 and stock_frames_total % 80 == 0:
                ref = analyze_cycle(ranks, pcts, config)
                mine = run_cycle_sequence(ranks, pcts, config, "mixed")
                inline_checked += 1
                if (ref["stage"], ref["rawStage"], ref["transition"], ref["confidence"]) != (
                    mine["stage"], mine["rawStage"], mine["transition"], mine["confidence"]
                ) or ref["metrics"] != mine["metrics"]:
                    inline_mismatch += 1

            seq_m = run_cycle_sequence(ranks, pcts, config, "mixed")
            seq_p = run_cycle_sequence(ranks, pcts, config, "pct")

            # P1 谓词分歧（decision 窗为主判定 population；全窗报告）
            win_tail_r = ranks[-METRICS_WINDOW:]
            win_tail_p = pcts[-METRICS_WINDOW:]
            v_m = mixed_verdicts(win_tail_r, win_tail_p, pct_now)
            v_p = pct_verdicts(win_tail_p, pct_now)
            if label == "decision":
                for key in v_m:
                    add_pred(key, v_m[key], v_p[key], tercile)

            # 末态双风味 + decision 层（risk/momentum 注入，双算）
            fallback = {
                "displayChange": pct_now - (pcts[-2] if len(pcts) >= 2 else pct_now),
                "stockChange": stock.get("change"),
                "volumeRatio": stock.get("volumeRatio"),
                "zlje": stock.get("zlje"),
                "zljzb": stock.get("zljzb"),
            }
            technical = analyze_technical(pcts, config, fallback)
            momentum_profile = technical["momentumProfile"]

            def endstate(seq, tag: str) -> dict:
                cyc = {k: seq[k] for k in ("stage", "rawStage", "transition", "confidence", "metrics")}
                risk = analyze_risk(pct_now, technical, cyc, fallback["zlje"], fallback["zljzb"], fallback["volumeRatio"], config)
                decision = lifecycle_decision(
                    cyc["rawStage"], cyc["stage"], cyc["transition"], float(cyc["confidence"]),
                    cyc["metrics"], risk, momentum_profile, config=config,
                )
                action = str(decision.get("action") or "caution")
                tier = _lifecycle_tier(cyc["stage"], action)[0]
                reasons_text = " ".join(str(r) for r in (decision.get("reasons") or []))
                driver = "reversal" if "反转路径" in reasons_text else (
                    "highrisk" if ("风险背离" in reasons_text or "过热" in reasons_text)
                    else ("reversal" if cyc["stage"] == "reversal" else "highrisk")
                )
                return {"stage": cyc["stage"], "raw": cyc["rawStage"], "action": action,
                        "tier": tier, "veto": action == "veto", "bd": tier in ("B", "D"), "driver": driver}

            es_m = endstate(seq_m, "mixed")
            es_p = endstate(seq_p, "pct")

            if label == "decision":
                add_end("stage", es_m["stage"], es_p["stage"], tercile)
                add_end("rawStage", es_m["raw"], es_p["raw"], tercile)
                add_end("tier", es_m["tier"], es_p["tier"], tercile)
                add_end("veto", es_m["veto"], es_p["veto"], tercile)
                add_end("bd", es_m["bd"], es_p["bd"], tercile)

            # L0 自证 B：混合末态 vs 引擎（仅引擎检查帧）
            if not args.skip_engine_check and fi in engine_check_indices:
                lc = engine_signals.get(code)
                if lc:
                    engine_compare["frames_checked"] = len(engine_check_indices)
                    engine_compare["stocks_compared"] += 1
                    engine_compare["stage_match"] += int(lc.get("stage") == es_m["stage"])
                    engine_compare["tier_match"] += int(lc.get("signalTier") == es_m["tier"])

            # P3 对级 + 帧级
            for k in range(1, len(pcts)):
                cross_day = elem_dates[k] != elem_dates[k - 1]
                frames_apart = elem_fi[k] - elem_fi[k - 1]
                non_adj = cross_day or frames_apart >= 2
                delta = pcts[k] - pcts[k - 1]
                bucket = "gap" if cross_day else "nogap"
                pair_gap[label]["n"] += 1
                pair_gap[label]["g1"] += int(cross_day)
                pair_gap[label]["g2"] += int(non_adj)
                pair_delta[label].setdefault(bucket, []).append(abs(delta))
                if k == len(pcts) - 1:
                    vel_last = seq_m["metrics"]["rankVelocity"]
                    gap_origin_g1 = cross_day
                    gap_origin_g2 = non_adj
                    row = {
                        "code": code, "gap1": bool(gap_origin_g1), "gap2": bool(gap_origin_g2),
                        "vel": float(vel_last), "regime": regime,
                        "frames_apart": int(frames_apart), "date": date,
                    }
                    frame_rows[label].append(row)
                    # stage 转移 gap 占比（末步转移）
                    prev_stage = seq_m["steps"][-1]["prev_stage"]
                    trans_key = f"{prev_stage}->{seq_m['steps'][-1]['stage']}" if prev_stage and prev_stage != seq_m["steps"][-1]["stage"] else "hold"
                    trans_gap[label].setdefault(trans_key, [0, 0])
                    trans_gap[label][trans_key][0] += 1
                    trans_gap[label][trans_key][1] += int(gap_origin_g1)
                    # veto/bd 帧 gap 占比（对账表）
                    for tag in ("veto", "bd"):
                        veto_bd_gap[label].setdefault(tag, [0, 0])
                        veto_bd_gap[label][tag][0] += int(es_m[tag])
                        veto_bd_gap[label][tag][1] += int(es_m[tag] and gap_origin_g1)

    # ── 聚合输出 ──
    def dist_summary(values: list[float]) -> dict:
        arr = np.array(values, dtype=float)
        return {
            "n": int(arr.size), "mean": round(float(arr.mean()), 2), "std": round(float(arr.std()), 2),
            "min": round(float(arr.min()), 2),
            "p5": round(float(np.percentile(arr, 5)), 2), "p25": round(float(np.percentile(arr, 25)), 2),
            "p50": round(float(np.percentile(arr, 50)), 2), "p75": round(float(np.percentile(arr, 75)), 2),
            "p95": round(float(np.percentile(arr, 95)), 2), "max": round(float(arr.max()), 2),
            "share_lt75": round(float((arr < 75).mean()), 4), "share_lt60": round(float((arr < 60).mean()), 4),
        }

    t_dist = {w: dist_summary(v) for w, v in sorted(t_by_window.items())}

    pred_out = {}
    for key, d in sorted(pred_dis.items()):
        pred_out[key] = {
            "n": d["n"], "disagree_rate": round(d["dis"] / d["n"], 4) if d["n"] else None,
            "pct_looser_share": round(d["looser"] / d["n"], 4) if d["n"] else None,
            "pct_tighter_share": round(d["tighter"] / d["n"], 4) if d["n"] else None,
            "by_tercile": {f"T{t}": {"n": v[0], "disagree_rate": round(v[1] / v[0], 4) if v[0] else None}
                           for t, v in sorted(d["by_tercile"].items())},
        }

    end_out = {}
    for key, d in sorted(end_dis.items()):
        end_out[key] = {
            "n": d["n"], "disagree_rate": round(d["dis"] / d["n"], 4) if d["n"] else None,
            "by_tercile": {f"T{t}": {"n": v[0], "disagree_rate": round(v[1] / v[0], 4) if v[0] else None}
                           for t, v in sorted(d["by_tercile"].items())},
        }

    # P3 ER（主判定：decision 窗、G1、帧级）
    def er_for(label_filter: str, gap_key: str, vel_side: str) -> dict:
        rows = frame_rows.get(label_filter, [])
        if not rows:
            return {"n": 0}
        codes = np.array([r["code"] for r in rows])
        gap = np.array([bool(r[gap_key]) for r in rows])
        vel = np.array([float(r["vel"]) for r in rows])
        vel_flags = (vel > vel_min) if vel_side == "up" else (vel < -vel_min)
        base = {"n_frames": int(len(rows)), "P_gap": round(float(gap.mean()), 4)}
        subset = vel_flags & np.ones(len(rows), dtype=bool)
        if subset.sum() == 0:
            return {**base, "er": None, "note": "no vel-tail frames"}
        # ER = P(gap|vel尾)/P(gap)；CI=按 code 聚块重抽同口径
        p_gap_given = float(gap[subset].mean())
        p_gap_all = float(gap.mean())
        point = p_gap_given / p_gap_all if p_gap_all > 0 else None
        # bootstrap CI 同口径重算
        rng = np.random.default_rng(BOOTSTRAP_SEED)
        unique_codes, inverse = np.unique(codes, return_inverse=True)
        n_codes = len(unique_codes)
        gap_c = np.bincount(inverse, weights=gap.astype(float), minlength=n_codes)
        n_c = np.bincount(inverse, minlength=n_codes).astype(float)
        gv_c = np.bincount(inverse[subset], weights=gap[subset].astype(float), minlength=n_codes)
        v_c = np.bincount(inverse[subset], minlength=n_codes).astype(float)
        ers = []
        for _ in range(BOOTSTRAP_ITERS):
            pick = rng.integers(0, n_codes, n_codes)
            pg = gv_c[pick].sum() / v_c[pick].sum() if v_c[pick].sum() > 0 else np.nan
            pa = gap_c[pick].sum() / n_c[pick].sum() if n_c[pick].sum() > 0 else np.nan
            if np.isfinite(pg) and np.isfinite(pa) and pa > 0:
                ers.append(pg / pa)
        ers = np.array(ers)
        return {**base,
                "P_gap_given_veltail": round(p_gap_given, 4), "ER_point": round(point, 4) if point else None,
                "ER_ci95": [round(float(np.percentile(ers, 2.5)), 4), round(float(np.percentile(ers, 97.5)), 4)],
                "veltail_n": int(subset.sum()), "iters": BOOTSTRAP_ITERS, "seed": BOOTSTRAP_SEED}

    delta_out = {}
    for w, d in sorted(pair_delta.items()):
        delta_out[w] = {
            gap: {stat: round(float(np.percentile(np.array(v), q)), 3) if v else None
                  for stat, q in (("median", 50), ("p90", 90), ("p99", 99))}
            for gap, v in d.items()
        }

    pair_out = {}
    for w, c in sorted(pair_gap.items()):
        pair_out[w] = {"pairs": c["n"], "gap_G1_share": round(c["g1"] / c["n"], 4) if c["n"] else None,
                       "gap_G2_share": round(c["g2"] / c["n"], 4) if c["n"] else None}

    # 冻结判定线评估（跑数前冻结于合同；此处只对照，不得改线）
    dec_stage = end_out.get("stage", {})
    dec_veto = end_out.get("veto", {})
    dec_bd = end_out.get("bd", {})
    p1_stage_rate = dec_stage.get("disagree_rate") or 0
    p1_gate_rate = max(dec_veto.get("disagree_rate") or 0, dec_bd.get("disagree_rate") or 0)
    max_pred_tercile = max(
        (t["disagree_rate"] or 0) for d in pred_out.values() for t in d["by_tercile"].values()
    ) if pred_out else 0
    p1_gate_pass = (p1_stage_rate >= 0.02) or (p1_gate_rate >= 0.01) or (max_pred_tercile >= 0.05)
    t_all = np.array(frame_totals, dtype=float)
    t_p5, t_p95 = float(np.percentile(t_all, 5)), float(np.percentile(t_all, 95))
    t_degenerate = bool(190 <= t_p5 and t_p95 <= 210)
    all_pred_lt3 = all((d["disagree_rate"] or 0) < 0.03 for d in pred_out.values()) if pred_out else True
    p1_terminate = bool(t_degenerate) or (sum(1 for x in frame_totals if x < 75) == 0 and all_pred_lt3)

    er_dec_g1 = er_for("decision", "gap1", "up")
    p3_gate_pass = bool(
        er_dec_g1.get("ER_point") is not None
        and er_dec_g1["ER_point"] >= 1.5
        and er_dec_g1["ER_ci95"][0] > 1.0
    )

    report = {
        "meta": {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "start": args.start, "end": args.end,
            "frames_loaded": len(frames),
            "window_labels": dict(Counter(labels)),
            "tercile_cuts_frozen": tercile_cuts,
            "vel_min_from_config": vel_min,
            "bucket_note": "帧投影无 hotlistSentiment → 分桶用 market_regime state（strong/normal/weak/retreat），报告列非判定线",
            "regime_distribution": dict(Counter(regime_states)),
            "primary_population_frozen": "decision 窗、序列长度≥2 股帧（§11.2 跑数前声明）",
            "elapsed_sec": round(time.time() - t0, 1),
        },
        "data_quality": {
            "stock_frames_total": stock_frames_total,
            "series_lt2_count": series_lt2,
            "series_lt2_share": round(series_lt2 / stock_frames_total, 4) if stock_frames_total else None,
            "self_check_inline_vs_analyze_cycle": {"checked": inline_checked, "mismatch": inline_mismatch},
            "self_check_engine_replay": engine_compare,
        },
        "p1": {
            "t_distribution_by_window": t_dist,
            "t_by_window_regime": dict(t_by_window_regime),
            "predicate_disagreement_decision": pred_out,
            "endstate_disagreement_decision": end_out,
            "gates": {
                "stage_disagree_rate": p1_stage_rate, "line": 0.02,
                "veto_bd_disagree_rate_max": p1_gate_rate, "line": 0.01,
                "max_predicate_tercile_rate": round(max_pred_tercile, 4), "line": 0.05,
                "gate_pass": p1_gate_pass,
                "T_degenerate": p1_terminate,
                "T_degenerate_rule": "p5-p95∈[190,210] 或 T<75 帧数=0 且全部谓词分歧<3%",
            },
        },
        "p3": {
            "pair_shares_by_window": pair_out,
            "abs_delta_by_window": delta_out,
            "ER": {
                "decision_G1_up": er_dec_g1,
                "decision_G2_up": er_for("decision", "gap2", "up"),
                "decision_G1_down": er_for("decision", "gap1", "down"),
                "frozen_G1_up": er_for("midgap", "gap1", "up"),
                "oos1_G1_up": er_for("oos1", "gap1", "up"),
                "oos2_G1_up": er_for("oos2", "gap1", "up"),
            },
            "stage_transition_gap_share_by_window": {
                w: {k: {"n": v[0], "gap_share": round(v[1] / v[0], 4) if v[0] else None} for k, v in sorted(d.items())}
                for w, d in sorted(trans_gap.items())
            },
            "veto_bd_gap_share_by_window": {
                w: {k: {"frames": v[0], "gap_share": round(v[1] / v[0], 4) if v[0] else None} for k, v in sorted(d.items())}
                for w, d in sorted(veto_bd_gap.items())
            },
            "gates": {
                "ER_decision_G1_up": er_dec_g1.get("ER_point"), "line": 1.5,
                "ci95_low": er_dec_g1.get("ER_ci95", [None])[0], "line_low": 1.0,
                "gate_pass": p3_gate_pass,
            },
        },
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({
        "out": str(out_path),
        "self_check": report["data_quality"]["self_check_inline_vs_analyze_cycle"],
        "engine_check": engine_compare,
        "p1_gate": report["p1"]["gates"],
        "p3_gate": report["p3"]["gates"],
        "ER_decision_G1_up": er_dec_g1,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
