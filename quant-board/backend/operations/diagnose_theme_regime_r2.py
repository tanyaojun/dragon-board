"""Phase R2：rotation_regime 阈值化 + 判定链稳定性双指标定版实证（只读，不写库）。

① 稳定性 × 次期收益双指标：无平滑 + EMA/累计/滞回三候选（默认权重），
   各配置 Top3 日间 Jaccard、Top1 切换率、Top3 组合 T+1 超额收益均值与胜率
② rotation_regime 逐日序列（rot 近 5 日均值 × entropy 近 10 日频率熵滚动）：
   默认阈值 + 3×3 阈值敏感性（各态天数分布与切换次数）
③ regime × market_phase 联合分布（half_hour 15:00 帧 rotationSummary.marketPhase）
④ 引擎口径对照：half_hour 15:00 帧 rotationSummary.mainLines 空值率、
   rotationState=mainline 题材集与判定链 Top3 的日间重合
⑤ 抖动率按月分解（Top1 切换率 / Top3 Jaccard，无平滑 vs 滞回配置）

用法：
  cd quant-board
  .\\.venv\\Scripts\\python.exe -m backend.operations.diagnose_theme_regime_r2
      [--start 2026-07-06] [--end 2026-09-24]
      [--out data/reports/theme-r2-regime.json]

资源纪律：只读、无 optimization API、单进程本地计算；探索性描述统计，
样本 54 天，非正式判定。
fail-visible：缺日/缺帧/缺字段如实打标（None/insufficient），不伪造 0，不中断。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from statistics import fmean
from typing import Any

from backend.analysis.theme.mainline_assignment import mainline_scores
from backend.analysis.theme.mainline_stability import (
    ema_toplists,
    hysteresis_toplists,
    window_toplists,
)
from backend.analysis.theme.rotation.measures import rank_entropy
from backend.analysis.theme.rotation.regime import regime_sequence, transition_counts
from backend.data.repositories.mongo_repository import MongoRepository
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.operations.diagnose_theme_rotation_r1 import (
    DATASET_ID,
    TOP_N,
    load_close_slot_series,
)

ENTROPY_WINDOW = 10   # 排名熵滚动窗口（交易日）
ROT_WINDOW = 5        # 轮动速度滚动均值窗口
REGIME_GRID = {
    "entropy_hi": [0.85, 0.90, 0.95],
    "rot_hi": [0.60, 0.70, 0.80],
}
SMOOTH_CONFIGS = {
    "none": None,
    "ema_a05": {"kind": "ema", "alpha": 0.5},
    "window_n5": {"kind": "window", "window": 5, "broad_k": TOP_N},
    "hysteresis_k3_exit5": {"kind": "hysteresis", "k": 3, "exit_rank": 5},
}


def build_score_series(series: dict[str, Any]) -> dict[str, dict[str, float]]:
    """逐日收盘槽 → {date: {entityKey: MainlineScore}}（默认权重；insufficient 日 = {}）。"""
    out: dict[str, dict[str, float]] = {}
    for d, info in series["series"].items():
        if info["status"] != "ok":
            out[d] = {}
            continue
        scores = {
            k: v["score"]
            for k, v in mainline_scores(info["rows"]).items()
            if v.get("score") is not None
        }
        out[d] = scores
    return out


def apply_smooth(
    scores_by_day: dict[str, dict[str, float]], config: dict[str, Any] | None
) -> dict[str, list[str]]:
    if config is None:
        return {
            d: sorted(scores_by_day[d], key=lambda t: (-scores_by_day[d][t], t))[:3]
            for d in scores_by_day
        }
    kind = config["kind"]
    if kind == "ema":
        return ema_toplists(scores_by_day, alpha=config["alpha"], k=3)
    if kind == "window":
        return window_toplists(scores_by_day, window=config["window"], broad_k=config["broad_k"], k=3)
    if kind == "hysteresis":
        return hysteresis_toplists(scores_by_day, k=config["k"], exit_rank=config["exit_rank"])
    raise ValueError(f"unknown smooth kind: {kind}")


def top3_jaccard_and_switch(toplists: dict[str, list[str]]) -> dict[str, Any]:
    days = sorted(toplists)
    jac: list[float] = []
    switches = 0
    comparable = 0
    prev_top1: str | None = None
    for a, b in zip(days, days[1:]):
        sa, sb = set(toplists[a]), set(toplists[b])
        union = sa | sb
        if union:
            jac.append(1 - len(sa & sb) / len(union))
        if sb:
            comparable += 1
            cur = toplists[b][0]
            if cur != prev_top1:
                switches += 1
            prev_top1 = cur
    lens = [len(v) for v in toplists.values()]
    return {
        "top3_jaccard_mean": round(fmean(jac), 4) if jac else None,
        "top1_switch_rate": round(switches / comparable, 4) if comparable else None,
        "n_transitions": len(jac),
        "max_toplist_len": max(lens) if lens else 0,
    }


def next_day_excess(
    toplists: dict[str, list[str]],
    change_by_day: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Top3 组合 T+1 等权 change 超额（相对全题材均值）；T 日名单用 T+1 日收益评估。"""
    days = sorted(toplists)
    excess: list[float] = []
    for i, d in enumerate(days[:-1]):
        nxt = days[i + 1]
        chg = change_by_day.get(nxt) or {}
        if not chg:
            continue
        picks = [t for t in toplists[d] if t in chg]
        if not picks:
            continue
        pick_mean = fmean(chg[t] for t in picks)
        all_mean = fmean(chg.values())
        excess.append(pick_mean - all_mean)
    if not excess:
        return {"status": "insufficient", "reason": "no_evaluable_days", "n": 0}
    return {
        "status": "ok",
        "n": len(excess),
        "mean_excess": round(fmean(excess), 4),
        "win_rate": round(sum(1 for x in excess if x > 0) / len(excess), 4),
        "max": round(max(excess), 4),
        "min": round(min(excess), 4),
    }


def build_change_by_day(series: dict[str, Any]) -> dict[str, dict[str, float]]:
    """每日 {entityKey: change}（收盘槽横截面，缺 change 的行跳过）。"""
    out: dict[str, dict[str, float]] = {}
    for d, info in series["series"].items():
        if info["status"] != "ok":
            continue
        chg = {
            str(r.get("entityKey")): float(r["change"])
            for r in info["rows"]
            if isinstance(r.get("change"), (int, float)) and r.get("entityKey") is not None
        }
        if chg:
            out[d] = chg
    return out


def rolling_daily_metrics(
    series: dict[str, Any],
    toplists: dict[str, list[str]],
) -> dict[str, dict[str, Any]]:
    """regime 输入：rot=近 ROT_WINDOW 日 Jaccard 均值；entropy=近 ENTROPY_WINDOW 日霸榜频率熵。"""
    days = sorted(series["series"])
    daily_rot: dict[str, float | None] = {}
    for a, b in zip(days, days[1:]):
        sa = set(toplists.get(a) or [])
        sb = set(toplists.get(b) or [])
        union = sa | sb
        daily_rot[b] = (1 - len(sa & sb) / len(union)) if union else None
    metrics: dict[str, dict[str, Any]] = {}
    for i, d in enumerate(days):
        lo_r = max(0, i - ROT_WINDOW + 1)
        rot_vals = [daily_rot[x] for x in days[lo_r : i + 1] if daily_rot.get(x) is not None]
        lo_e = max(0, i - ENTROPY_WINDOW + 1)
        counts: dict[str, int] = {}
        for x in days[lo_e : i + 1]:
            for t in toplists.get(x) or []:
                counts[t] = counts.get(t, 0) + 1
        ent = rank_entropy(counts)
        metrics[d] = {
            "rot_speed": round(fmean(rot_vals), 4) if rot_vals else None,
            "entropy": ent.get("normalized"),
        }
    return metrics


def transitions_to_json(seq: dict[str, str | None]) -> dict[str, int]:
    """transition_counts 结果转 JSON 可序列化字符串键（'a->b'）。"""
    return {f"{a}->{b}": n for (a, b), n in transition_counts(seq).items()}


def market_phase_alignment(
    repo: MongoRepository, start: str, end: str, regime_seq: dict[str, str | None]
) -> dict[str, Any]:
    """regime × marketPhase 联合计数（half_hour 15:00 帧 rotationSummary.marketPhase）。"""
    joint: dict[str, dict[str, int]] = {}
    mainlines_empty = 0
    mainlines_total = 0
    for doc in repo.db["snapshot_frames"].find(
        {
            "tradingDate": {"$gte": start, "$lte": end},
            "slotTime": "15:00",
            "type": "half_hour",
            "datasetId": DATASET_ID,
        },
        {"tradingDate": 1, "rotationSummary.marketPhase": 1, "rotationSummary.mainLines": 1},
    ):
        d = str(doc.get("tradingDate"))
        rs = doc.get("rotationSummary") or {}
        phase = rs.get("marketPhase")
        ml = rs.get("mainLines")
        reg = regime_seq.get(d)
        if reg is not None:
            bucket = joint.setdefault(reg, {})
            bucket[str(phase)] = bucket.get(str(phase), 0) + 1
        if ml is not None:
            mainlines_total += 1
            if not ml:
                mainlines_empty += 1
    return {
        "joint_regime_x_phase": joint,
        "mainlines_empty_ratio": round(mainlines_empty / mainlines_total, 4) if mainlines_total else None,
        "mainlines_total": mainlines_total,
    }


def engine_mainline_overlap(
    repo: MongoRepository, start: str, end: str, toplists: dict[str, list[str]]
) -> dict[str, Any]:
    """引擎口径对照：half_hour 15:00 sector rows rotationState=mainline 题材集 vs 判定链 Top3。"""
    res = repo.list_snapshot_sector_rows(
        DATASET_ID, start_date=start, end_date=end, entity_type="hot_theme",
        snapshot_type="half_hour", sort="asc",
    )
    by_day: dict[str, set[str]] = {}
    for r in res["rows"]:
        if str(r.get("slotTime")) != "15:00" or r.get("rotationState") != "mainline":
            continue
        k = r.get("entityKey")
        if k is not None:
            by_day.setdefault(str(r.get("tradingDate")), set()).add(str(k))
    overlaps: list[float] = []
    for d, engine_set in sorted(by_day.items()):
        ours = set(toplists.get(d) or [])
        if not ours or not engine_set:
            continue
        overlaps.append(len(engine_set & ours) / max(len(engine_set | ours), 1))
    return {
        "engine_mainline_days": len(by_day),
        "overlap_jaccard_mean": round(fmean(overlaps), 4) if overlaps else None,
        "n_compared": len(overlaps),
    }


def monthly_jitter(toplists: dict[str, list[str]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for month, (a, b) in {
        "2026-07": ("2026-07-06", "2026-07-31"),
        "2026-08": ("2026-08-01", "2026-08-31"),
        "2026-09": ("2026-09-01", "2026-09-24"),
    }.items():
        sub = {d: v for d, v in toplists.items() if a <= d <= b}
        if sub:
            out[month] = top3_jaccard_and_switch(sub)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2026-07-06")
    parser.add_argument("--end", default="2026-09-24")
    parser.add_argument("--out", default="data/reports/theme-r2-regime.json")
    args = parser.parse_args()

    repo = MongoRepository(get_runtime_mongodb_database())
    series = load_close_slot_series(repo, args.start, args.end)
    if series["status"] != "ok":
        print(json.dumps(series, ensure_ascii=False, indent=2))
        return 2
    scores_by_day = build_score_series(series)
    change_by_day = build_change_by_day(series)

    stability: dict[str, Any] = {}
    toplists_by_cfg: dict[str, dict[str, list[str]]] = {}
    for name, cfg in SMOOTH_CONFIGS.items():
        toplists = apply_smooth(scores_by_day, cfg)
        toplists_by_cfg[name] = toplists
        stability[name] = {
            **top3_jaccard_and_switch(toplists),
            "next_day_excess": next_day_excess(toplists, change_by_day),
        }

    # regime：用 none 配置名单计算滚动两指标；平滑对 regime 的影响留 R3
    metrics = rolling_daily_metrics(series, toplists_by_cfg["none"])
    regime_seq = regime_sequence(metrics)
    regime_days: dict[str, int] = {}
    for v in regime_seq.values():
        if v is not None:
            regime_days[v] = regime_days.get(v, 0) + 1
    threshold_sensitivity = []
    for eh in REGIME_GRID["entropy_hi"]:
        for rh in REGIME_GRID["rot_hi"]:
            seq = regime_sequence(metrics, rot_hi=rh, entropy_hi=eh)
            dist: dict[str, int] = {}
            for v in seq.values():
                if v is not None:
                    dist[v] = dist.get(v, 0) + 1
            threshold_sensitivity.append({
                "entropy_hi": eh, "rot_hi": rh, "days": dist,
                "switches": sum(transitions_to_json(seq).values()),
            })

    report = {
        "window": {"start": args.start, "end": args.end},
        "stability_vs_excess": stability,
        "regime_sequence": regime_seq,
        "regime_days_default": regime_days,
        "regime_transitions_default": transitions_to_json(regime_seq),
        "threshold_sensitivity": threshold_sensitivity,
        "market_phase_alignment": market_phase_alignment(repo, args.start, args.end, regime_seq),
        "engine_mainline_overlap": engine_mainline_overlap(repo, args.start, args.end, toplists_by_cfg["none"]),
        "monthly_jitter_none": monthly_jitter(toplists_by_cfg["none"]),
        "monthly_jitter_hysteresis": monthly_jitter(toplists_by_cfg["hysteresis_k3_exit5"]),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, s in stability.items():
        ne = s["next_day_excess"]
        print(f"[{name}] jac={s['top3_jaccard_mean']} switch={s['top1_switch_rate']} "
              f"maxlen={s['max_toplist_len']} excess={ne.get('mean_excess')} win={ne.get('win_rate')}")
    print(f"[regime] days={regime_days} transitions={report['regime_transitions_default']}")
    print(f"report -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
