# -*- coding: utf-8 -*-
"""月度重校准回放 runner（预登记 emotion-score-recalib-preregistration-20261008.md）。

只读零写库零模型调用：存量槽位/EOD 文档 dims.raw → 新旧曲线插值 → 新旧 score →
EOD 全链（slope/dd/confirm）档位迁移 + 相位/均值/regime 分量 + 五档可达性 → JSON 落盘。

判定门（冻结）：门1 锚向合理 / 门2 迁移≤15%候选、≤10%确认 / 门3 |Δmean|≤5 /
门4 五档可达不降级 / 门5 相位翻转≤10% / 门6 regime 均值差披露 ≤2。
用法：
  cd quant-board && .venv/Scripts/python.exe -m backend.operations.emotion_score_recalib_replay \
      [--json .tmp/emotion-score-recalib-replay.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist.emotion_score import _CALIB, _interp
from backend.analysis.hotlist.stage_confirm import confirm_stage
from backend.data.repositories import repository_factory
from backend.operations.emotion_score_calib_monitor import percentile

# 各维锚位网格（分位→sub；预登记 §1 冻结；设计点在 _CALIB 原样保留）
ANCHOR_GRIDS: dict[str, tuple[tuple[float, float], ...]] = {
    "upRatio": ((10.0, 10.0), (25.0, 25.0), (50.0, 50.0), (75.0, 75.0), (95.0, 95.0)),
    "attackShare": ((50.0, 30.0), (75.0, 50.0), (90.0, 70.0), (95.0, 85.0)),
    "riskShare": ((10.0, 90.0), (50.0, 50.0), (90.0, 10.0)),
    "trin": ((5.0, 90.0), (25.0, 75.0), (50.0, 50.0), (75.0, 25.0), (90.0, 10.0)),
    "yhPositive": ((10.0, 10.0), (50.0, 50.0), (90.0, 90.0)),
    "riskRowsPct": ((10.0, 90.0), (50.0, 50.0), (90.0, 10.0)),
}
STAGES = ("高潮", "发酵", "启动", "退潮", "冰点")
REGIME_ADJUST = {"高潮": 8, "发酵": 5, "启动": 0, "退潮": -6, "冰点": -8}


def _numeric(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def build_new_curves(slot_docs: list[dict[str, Any]]) -> tuple[dict[str, list], dict[str, dict]]:
    """锚位 raw 替换为新窗口分位值（sub/设计点不动）→ 新曲线 + 新旧锚对照。"""
    raws_by_dim: dict[str, list[float]] = {name: [] for name in ANCHOR_GRIDS}
    for doc in slot_docs:
        dims = ((doc.get("emotionScore") or {}).get("dims")) or {}
        for name in ANCHOR_GRIDS:
            raw = _numeric((dims.get(name) or {}).get("raw"))
            if raw is not None:
                raws_by_dim[name].append(raw)
    new_curves: dict[str, list] = {}
    anchor_diff: dict[str, dict] = {}
    for name, grid in ANCHOR_GRIDS.items():
        vals = sorted(raws_by_dim[name])
        old_pts = list(_CALIB[name])
        new_pts = list(old_pts)
        diffs: dict[str, float] = {}
        for p, sub in grid:
            v_new = percentile(vals, p)
            target_i = next((i for i, pt in enumerate(old_pts)
                             if abs(pt[1] - sub) < 1e-6 and pt[0] not in (0.0, 1.0)), None)
            if target_i is None or v_new is None:
                diffs[f"P{p:g}"] = float("nan")
                continue
            old_raw = old_pts[target_i][0]
            diffs[f"P{p:g}"] = round(v_new - old_raw, 4)
            new_pts[target_i] = (round(v_new, 4), sub)
        new_curves[name] = new_pts
        anchor_diff[name] = diffs
    return new_curves, anchor_diff


def score_of(doc: dict[str, Any], curves: dict[str, list]) -> float | None:
    """等权重算：监控维用曲线插值，其余维沿用 stored sub；缺维归一。"""
    dims = ((doc.get("emotionScore") or {}).get("dims")) or {}
    subs: list[float] = []
    for name, entry in dims.items():
        sub = _numeric(entry.get("sub"))
        if sub is None:
            continue
        if name in curves:
            raw = _numeric(entry.get("raw"))
            subs.append(_interp(curves[name], raw) if raw is not None else sub)
        else:
            subs.append(sub)
    return round(sum(subs) / len(subs), 2) if subs else None


def main() -> int:
    parser = argparse.ArgumentParser(description="月度重校准回放（只读）")
    parser.add_argument("--json", default=".tmp/emotion-score-recalib-replay.json")
    args = parser.parse_args()

    db = repository_factory.get_runtime_mongodb_database()
    slot_docs = list(db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": {"$ne": "EOD"}}))
    eod_docs = {d["tradingDate"]: d for d in db["hotlist_sentiment"].find(
        {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD"})}

    new_curves, anchor_diff = build_new_curves(slot_docs)

    # 代际标记（review P3）：本 runner 的「旧侧=stored 分」隔离方法学只在退役前成立；
    # 若存量文档已无 amountVsSame skip（=已重算新代），old 侧已是现行口径，纯曲线对照失效
    pre_retirement = any(
        "amountVsSame" in ((d.get("emotionScore") or {}).get("skippedDims") or [])
        for d in slot_docs[:200])
    generation_note = (
        "pre_retirement: stored 分含退役维 skip=旧代，纯曲线隔离方法学有效"
        if pre_retirement else
        "post_retirement: stored 分已是现行口径——纯曲线隔离失效，本次对照仅结构参考，勿作裁决依据")

    # 槽位分双侧：新曲线新分 + stored 分作 old 侧（现行规则+旧曲线——隔离纯曲线效应；
    # 存量 stage 混杂 A/B+C 之前旧规则，不可作对照基线）
    slot_new: dict[tuple[str, str], float] = {}
    slot_old: dict[tuple[str, str], float] = {}
    for doc in slot_docs:
        s = score_of(doc, new_curves)
        s_old = _numeric(((doc.get("emotionScore") or {})).get("score"))
        if s is not None and s_old is not None:
            slot_new[(str(doc["tradingDate"]), str(doc["slotTime"]))] = s
            slot_old[(str(doc["tradingDate"]), str(doc["slotTime"]))] = s_old
    dates = sorted({k[0] for k in slot_new})

    cand_mig: Counter = Counter()
    confirm_mig: Counter = Counter()
    phase_flip = 0
    old_means: list[float] = []
    new_means: list[float] = []
    regime_diffs: list[float] = []
    old_stage_days: Counter = Counter()
    new_stage_days: Counter = Counter()
    eod_rows: list[dict[str, Any]] = []
    for dt in dates:
        day_docs = sorted((d for d in slot_docs if str(d["tradingDate"]) == dt
                           and (dt, str(d["slotTime"])) in slot_new),
                          key=lambda d: str(d["slotTime"]))
        eod = eod_docs.get(dt)
        if eod is None:
            continue
        es = (eod.get("emotionScore") or {})
        s_old = _numeric(es.get("score"))
        s_new = score_of(eod, new_curves)
        if s_old is None or s_new is None:
            continue
        old_means.append(s_old)
        new_means.append(s_new)

        def _day_replay(score_key: dict[tuple[str, str], float], eod_score: float) -> tuple[str, str]:
            """当日全链重放：槽位候选（末步差分）+ EOD 候选（含 dd）→ confirm 滞回。"""
            prev_v: float | None = None
            points: list[tuple[str, str]] = []
            for d in day_docs:
                v = score_key[(dt, str(d["slotTime"]))]
                slope_s = round(v - prev_v, 2) if prev_v is not None else None
                points.append((str(d["slotTime"]), _map_stage_for(v, slope_s, None)))
                prev_v = v
            slope_e = round(eod_score - prev_v, 2) if prev_v is not None else None
            series_vals = [score_key[(dt, str(d["slotTime"]))] for d in day_docs]
            dd_e = round(eod_score - max(series_vals + [eod_score]), 1) if series_vals else None
            cand = _map_stage_for(eod_score, slope_e, {"dd": dd_e} if dd_e is not None else None)
            points.append(("EOD", cand))
            confirmed_s, _st = confirm_stage(points, 2)
            return cand, confirmed_s

        old_cand, old_confirmed = _day_replay(slot_old, s_old)
        new_candidate, new_confirmed = _day_replay(slot_new, s_new)
        old_stage_days[old_confirmed] += 1
        new_stage_days[new_confirmed] += 1
        if old_cand != new_candidate:
            cand_mig[(old_cand, new_candidate)] += 1
        if old_confirmed != new_confirmed:
            confirm_mig[(old_confirmed, new_confirmed)] += 1
        # 相位（≥60 offense）与 regime 分量
        if (s_old >= 60) != (s_new >= 60):
            phase_flip += 1
        regime_diffs.append(REGIME_ADJUST.get(new_confirmed, 0) - REGIME_ADJUST.get(old_confirmed, 0))
        eod_rows.append({"date": dt, "old": s_old, "new": s_new, "oldStage": old_confirmed,
                         "newStage": new_confirmed, "oldCandidate": old_cand,
                         "newCandidate": new_candidate})

    n = len(new_means)
    mean_delta = round(statistics.mean(new_means) - statistics.mean(old_means), 2) if n else None
    cand_total = sum(cand_mig.values())
    confirm_total = sum(confirm_mig.values())
    gates = {
        "门1_锚向合理": "见 anchorDiff（riskShare/riskRowsPct 下移=与告警一致）",
        "门2_迁移": {"candidatePct": round(cand_total / n * 100, 1) if n else None,
                     "confirmPct": round(confirm_total / n * 100, 1) if n else None,
                     "limits": "候选≤15% / 确认≤10%"},
        "门3_均值稳定": {"meanDelta": mean_delta, "limit": "≤5"},
        "门4_五档可达": {"old": {k: old_stage_days.get(k, 0) for k in STAGES},
                         "new": {k: new_stage_days.get(k, 0) for k in STAGES}},
        "门5_相位翻转": {"days": phase_flip, "pct": round(phase_flip / n * 100, 1) if n else None,
                         "limit": "≤10%"},
        "门6_regime": {"meanDiff": round(statistics.mean(regime_diffs), 2) if regime_diffs else None,
                       "limit": "披露≤2"},
    }
    summary = {
        "slots": len(slot_docs), "eodDays": n,
        "oldSideGeneration": generation_note,
        "candidateMigration": {f"{a}→{b}": c for (a, b), c in cand_mig.items()},
        "confirmMigration": {f"{a}→{b}": c for (a, b), c in confirm_mig.items()},
        "phaseFlipDays": phase_flip,
        "meanOld": round(statistics.mean(old_means), 2) if n else None,
        "meanNew": round(statistics.mean(new_means), 2) if n else None,
        "meanDelta": mean_delta,
        "gates": gates,
    }
    out = {"summary": summary, "anchorDiff": anchor_diff, "newCurves": {k: [list(p) for p in v] for k, v in new_curves.items()},
           "eodRows": eod_rows}
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


def _map_stage_for(score: float, slope: float | None, path: dict | None) -> str:
    from backend.analysis.hotlist.emotion_score import map_stage

    return map_stage(score, slope, path=path)


if __name__ == "__main__":
    raise SystemExit(main())
