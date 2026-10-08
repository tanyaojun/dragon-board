# -*- coding: utf-8 -*-
"""第八维 amountVsSame 重校准研究轮（只读零写库零模型调用；预登记裁决 3 执行项）。

用 150 日日级 vsSamePct 真实分布校准候选曲线，模拟 8 维 EOD 分，检验冻结门，产出三出口之一：
(a) 激活候选 → 走预登记；(b) 永久退役提案；(c) 续冻延长窗口。

冻结判定门（跑数前冻结，study-internal）：
- G1 覆盖：EOD 日 vsSamePct 覆盖率 ≥80%；
- G2 尾部方向（反稀释）：校准曲线下深谷日（score7<30）Δ8 均值 ≤−1 且高峰日（≥75）Δ8 均值 ≥+1
  ——即第八维不再单向稀释（尾部锐化）。对照锚=A-① 评估实证：设计曲线（±30pp）深谷 Δ+3.2/高峰
  −3.0 单向指向中位；本研究须先复现该锚再看校准曲线是否翻转方向；
- G3 增量预测力：控制 score7(t) 后 sub8 对 Δt+1=score(t+1)−score(t) 的偏相关 |ρ|≥0.15，
  且 8 维分自身对次日变化的相关不降（|r8|≥|r7|）；
- G4 样本：深谷 n≥10 且高峰 n≥10。

候选曲线口径：主维锚定网格（P10/P25/P50/P75/P95→10/25/50/75/95），端点=150 日观测 min/max
（与其他维「分位锚+端点截断」同构）；单一事实源 import _interp，零插值副本。

用法：cd quant-board && .venv/Scripts/python.exe -m backend.operations.amount_vs_same_study \
      [--json .tmp/amount-vs-same-study.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist.emotion_score import _interp

DESIGN_CURVE = [(-80.0, 0.0), (-30.0, 25.0), (0.0, 50.0), (30.0, 80.0), (80.0, 100.0)]
ANCHOR_GRID = ((10.0, 10.0), (25.0, 25.0), (50.0, 50.0), (75.0, 75.0), (95.0, 95.0))
DEEP_LINE = 30.0
PEAK_LINE = 75.0
G_COVERAGE = 0.80
G_TAIL_DELTA = 1.0
G_PARTIAL_CORR = 0.15
G_MIN_GROUP = 10


def percentile(sorted_vals: list[float], p: float) -> float:
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def build_candidate_curve(values: list[float]) -> list[tuple[float, float]]:
    """端点=观测 min/max，内部=P 分位锚（升序单调）。"""
    vals = sorted(values)
    pts = [(round(vals[0], 2), 0.0)]
    for p, sub in ANCHOR_GRID:
        pts.append((round(percentile(vals, p), 2), sub))
    pts.append((round(vals[-1], 2), 100.0))
    return pts


def corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def partial_corr(xs: list[float], ys: list[float], ctrl: list[float]) -> float | None:
    """偏相关：x、y 各自对 ctrl 残差化后求相关。"""
    n = len(xs)
    if n < 3:
        return None
    mc = sum(ctrl) / n

    def resid(vs: list[float]) -> list[float]:
        mv = sum(vs) / n
        b = sum((c - mc) * (v - mv) for c, v in zip(ctrl, vs)) / max(sum((c - mc) ** 2 for c in ctrl), 1e-12)
        return [v - (mv + b * (c - mc)) for v, c in zip(vs, ctrl)]

    return corr(resid(xs), resid(ys))


def main() -> int:
    parser = argparse.ArgumentParser(description="amountVsSame 第八维重校准研究轮（只读）")
    parser.add_argument("--json", default=".tmp/amount-vs-same-study.json")
    args = parser.parse_args()

    from backend.data.repositories import repository_factory

    db = repository_factory.get_runtime_mongodb_database()
    amounts = {str(d["_id"]): float(d["vsSamePct"])
               for d in db["market_daily_amount"].find({"vsSamePct": {"$exists": True}})}
    eods = sorted(
        ({"date": str(d["tradingDate"]),
          "score": float(d["emotionScore"]["score"]),
          "stage": str(d.get("stage") or "")}
         for d in db["hotlist_sentiment"].find(
             {"datasetId": "dragonboard_live", "snapshotType": "half_hour", "slotTime": "EOD"},
             {"tradingDate": 1, "emotionScore.score": 1, "stage": 1})
         if isinstance((d.get("emotionScore") or {}).get("score"), (int, float))),
        key=lambda x: x["date"])
    joined = [e for e in eods if e["date"] in amounts]
    coverage = len(joined) / len(eods) if eods else 0.0
    if not amounts:
        print(json.dumps({"ok": False, "errorCode": "no_amount_records",
                          "message": "market_daily_amount 无 vsSamePct 记录，研究轮无法进行（fail-visible 结构化退出）"},
                         ensure_ascii=False))
        return 1

    values = sorted(amounts.values())
    curve = build_candidate_curve(values)
    stats = {"n": len(values), "min": round(values[0], 2), "max": round(values[-1], 2),
             "minDate": min(amounts), "maxDate": max(amounts),
             "caliber": "day-level adjacent-trading-day pct（market_daily_amount 全量，非显式窗口）",
             **{f"p{int(p)}": round(percentile(values, p), 2) for p, _s in ANCHOR_GRID}}

    rows: list[dict[str, Any]] = []
    for e in joined:
        s7 = e["score"]
        v = amounts[e["date"]]
        sub_new = round(_interp(curve, v), 2)
        sub_design = round(_interp(DESIGN_CURVE, v), 2)
        rows.append({"date": e["date"], "score7": s7, "stage": e["stage"], "vsSamePct": round(v, 2),
                     "sub8New": sub_new, "sub8Design": sub_design,
                     "score8": round((7 * s7 + sub_new) / 8, 2),
                     "deltaNew": round((sub_new - s7) / 8, 2),
                     "deltaDesign": round((sub_design - s7) / 8, 2)})

    deep = [r for r in rows if r["score7"] < DEEP_LINE]
    peak = [r for r in rows if r["score7"] >= PEAK_LINE]

    def mean(vs: list[float]) -> float | None:
        return round(sum(vs) / len(vs), 2) if vs else None

    # 对照锚复现（设计曲线应呈单向稀释）+ 校准曲线尾部方向
    anchor = {"deepDeltaDesign": mean([r["deltaDesign"] for r in deep]),
              "peakDeltaDesign": mean([r["deltaDesign"] for r in peak])}
    tail = {"deepDeltaNew": mean([r["deltaNew"] for r in deep]),
            "peakDeltaNew": mean([r["deltaNew"] for r in peak]),
            "deepN": len(deep), "peakN": len(peak)}

    # G3：次日变化预测（相邻 EOD 日对）
    pairs = [(rows[i], rows[i + 1]) for i in range(len(rows) - 1)
             if rows[i + 1]["date"] > rows[i]["date"]]
    s7_t = [p[0]["score7"] for p in pairs]
    s8_t = [p[0]["score8"] for p in pairs]
    sub8_t = [p[0]["sub8New"] for p in pairs]
    tgt7 = [round(p[1]["score7"] - p[0]["score7"], 2) for p in pairs]
    tgt8 = [round(p[1]["score8"] - p[0]["score8"], 2) for p in pairs]
    r7 = corr(s7_t, tgt7)
    r8 = corr(s8_t, tgt8)
    rho = partial_corr(sub8_t, tgt7, s7_t)

    g1 = coverage >= G_COVERAGE
    g2 = (tail["deepDeltaNew"] is not None and tail["peakDeltaNew"] is not None
          and tail["deepDeltaNew"] <= -G_TAIL_DELTA and tail["peakDeltaNew"] >= G_TAIL_DELTA)
    g3 = (rho is not None and r7 is not None and r8 is not None
          and abs(rho) >= G_PARTIAL_CORR and abs(r8) >= abs(r7))
    g4 = tail["deepN"] >= G_MIN_GROUP and tail["peakN"] >= G_MIN_GROUP
    if g1 and g2 and g3 and g4:
        exit_code, exit_desc = "a", "激活候选：走预登记（曲线+回放+裁决）"
    elif not g1 or not g4:
        exit_code, exit_desc = "c", "续冻延长窗口：覆盖/样本不足，继续积累后复跑本研究"
    else:
        exit_code, exit_desc = "b", "永久退役提案：尾部方向或增量预测力不达标（原料照采，权重表除名待裁决）"

    out = {"frozenGates": {"G1_coverage": G_COVERAGE, "G2_tailDelta": -G_TAIL_DELTA,
                           "G3_partialCorr": G_PARTIAL_CORR, "G4_minGroup": G_MIN_GROUP},
           "coverage": {"eodDays": len(eods), "joined": len(joined), "ratio": round(coverage, 3)},
           "vsSamePctDist": stats, "candidateCurve": curve,
           "designAnchorRepro": anchor, "tailDirection": tail,
           "predictive": {"pairs": len(pairs), "r7": None if r7 is None else round(r7, 3),
                          "r8": None if r8 is None else round(r8, 3),
                          "partialRhoSub8": None if rho is None else round(rho, 3)},
           "gates": {"G1": g1, "G2": g2, "G3": g3, "G4": g4},
           "exit": {"code": exit_code, "desc": exit_desc},
           "rows": rows}
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("coverage", "vsSamePctDist", "candidateCurve",
                                          "designAnchorRepro", "tailDirection", "predictive",
                                          "gates", "exit")}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
