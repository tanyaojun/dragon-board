# -*- coding: utf-8 -*-
"""jev 涨停打标 v2 重铸试点（pilot2）战报：catalyst_depth 轴质量 + pilot1 稳定性对照 + 分桶次日方向。

预登记判据 docs/hotlist-jev/jev-driver-label-v2-design.md §8（先冻结再开火）：
  门A depth 轴方差（主）：四个实质桶每桶 n≥5 且 实质桶最大桶占比<70%；insufficient_evidence ≤15%。
  门B 驱动分组保留：Kruskal p<0.05（n≥8 组）且 连板率极差≥15pct；单月不显著但与阶段3 全窗排序
      Spearman ρ≥0.5 一致 → INSUFFICIENT-扩窗。
  稳定性对照（观察项）：pilot2 vs pilot1（hotlist_jev_driver_labels_v2_pilot1 备份）driver_type/
      freshness sameShare——叙事与两轴题目均未动，同股应高复现。
  分桶次日方向（观察项）：catalyst_depth 各桶次日 pct 均值/连板率。
判定映射：门A+门B 全过=PASS_CANDIDATE；门A 过门B 不过=INSUFFICIENT；门A 不过=REJECT。
产物 docs/hotlist-jev/phase3-jiuyan-v2-repilot-report.md。
"""
from __future__ import annotations

import statistics
from collections import defaultdict

# 阶段3 全窗参考连板率（phase3-driver-report.md 冻结值，排序方向一致性对照用）
PHASE3_REF_LIANBAN = {"ma_restructure": 21.3, "order_earnings": 14.3, "concept_stretch": 11.6,
                      "industry_cycle": 8.2, "policy": 6.2, "product_event": 4.1, "capital_flow": 1.8}
DEPTH_SUBSTANTIVE = ["core_main_business", "new_growing_business", "equity_or_affiliate", "concept_assembly"]
DEPTH_ALL = DEPTH_SUBSTANTIVE + ["insufficient_evidence"]


def depth_distribution_metrics(depths: list[str]) -> dict:
    """门A 读数：四实质桶 n 与占比 + 逃生口占比（纯函数）。"""
    n = len(depths)
    if n < 20:
        return {"n": n, "insufficient": True}
    counts = {k: 0 for k in DEPTH_ALL}
    for d in depths:
        counts[d] = counts.get(d, 0) + 1
    sub_counts = {k: counts[k] for k in DEPTH_SUBSTANTIVE}
    max_share = max(sub_counts.values()) / n
    return {"n": n, "bucketCounts": sub_counts, "insufficientEvidence": counts["insufficient_evidence"],
            "maxBucketShare": round(max_share, 3),
            "substantiveBucketsWithN5": sum(1 for v in sub_counts.values() if v >= 5),
            "expanded": bool(sum(1 for v in sub_counts.values() if v >= 5) >= 4
                             and max_share < 0.70 and counts["insufficient_evidence"] / n <= 0.15),
            "insufficient": False}


def driver_group_metrics(rows: list[dict]) -> dict:
    """门B 读数：驱动分组 Kruskal + 连板率极差（rows 需含 label/nextPct/nextLianban）。"""
    by_lab: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("label"):
            by_lab[r["label"]].append(r)
    big = {k: v for k, v in by_lab.items() if len(v) >= 8}
    if len(big) < 2:
        return {"insufficient": True}
    from scipy.stats import kruskal

    _, p = kruskal(*[[x["nextPct"] for x in v] for v in big.values()])
    lb_rates = {k: sum(x["nextLianban"] for x in v) / len(v) * 100 for k, v in big.items()}
    spread = max(lb_rates.values()) - min(lb_rates.values())
    return {"p": round(p, 4), "lianbanRates": {k: round(v, 1) for k, v in lb_rates.items()},
            "spread": round(spread, 1), "n": {k: len(v) for k, v in big.items()},
            "groupOk": bool(p < 0.05 and spread >= 15), "insufficient": False}


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 5:
        return None

    def ranks(vals):
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        out = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j < len(order) and vals[order[j]] == vals[order[i]]:
                j += 1
            avg = (i + j - 1) / 2 + 1
            for k in range(i, j):
                out[order[k]] = avg
            i = j
        return out

    rx, ry = ranks(xs), ranks(ys)
    n = len(rx)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    vx = (sum((a - mx) ** 2 for a in rx)) ** 0.5
    vy = (sum((b - my) ** 2 for b in ry)) ** 0.5
    if vx == 0 or vy == 0:
        return None
    return round(cov / (vx * vy), 3)


def direction_consistent_with_phase3(lianban_rates: dict[str, float]) -> dict:
    """门B 单月显著性兜底：七类连板率排序 vs 阶段3 全窗参考，Spearman ρ≥0.5 视为方向一致。
    组数 <5 时不可算（computable=False），与"方向不一致"区分（避免误读）。"""
    common = [k for k in PHASE3_REF_LIANBAN if k in lianban_rates]
    if len(common) < 5:
        return {"rho": None, "consistent": False, "computable": False,
                "reason": f"n>=8 组仅 {len(common)} 个，排序一致性需 ≥5 组"}
    rho = _spearman([PHASE3_REF_LIANBAN[k] for k in common], [lianban_rates[k] for k in common])
    return {"rho": rho, "consistent": bool(rho is not None and rho >= 0.5), "computable": True}


def verdict(depth: dict, group: dict, direction: dict) -> str:
    """判定映射（预登记 §8）：门A 不过=REJECT；门A+门B 过=PASS_CANDIDATE；其余=INSUFFICIENT。"""
    if depth.get("insufficient") or not depth.get("expanded"):
        return "REJECT"
    if group.get("groupOk"):
        return "PASS_CANDIDATE"
    if direction.get("consistent"):
        return "INSUFFICIENT"  # 单月显著性不足但方向与全窗一致 → 扩窗复验，非 REJECT
    return "INSUFFICIENT"


def stability_vs_pilot1(v2: list[dict], pilot1: list[dict], field: str) -> dict:
    """稳定性对照：同 (date, code) 上某字段 pilot2 vs pilot1 一致率（观察项）。"""
    old = {f"{d['tradingDate']}:{d['code']}": d.get(field) for d in pilot1 if d.get(field)}
    new = {f"{d['tradingDate']}:{d['code']}": d.get(field) for d in v2 if d.get(field)}
    common = set(old) & set(new)
    if not common:
        return {"overlap": 0, "sameShare": None}
    same = sum(1 for k in common if old[k] == new[k])
    return {"overlap": len(common), "sameShare": round(same / len(common), 3)}


def bucket_next_day(rows: list[dict]) -> dict:
    """分桶次日方向（观察项）：各 depth 桶 n / 次日 pct 均值 / 连板率。"""
    out = {}
    for k in DEPTH_ALL:
        sub = [r for r in rows if r.get("catalystDepth") == k]
        if sub:
            out[k] = {"n": len(sub),
                      "nextPctMean": round(statistics.mean(x["nextPct"] for x in sub), 2),
                      "lianban": round(sum(x["nextLianban"] for x in sub) / len(sub) * 100, 1)}
    return out


def main():
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.operations.jev_label_driver_report import build_next_day_map, next_day_info

    db = get_runtime_mongodb_database()
    labels = [d for d in db["hotlist_jev_driver_labels_v2"].find({"status": "ok"}) if d.get("label")]
    if not labels:
        print("hotlist_jev_driver_labels_v2 无 ok 标签，退出")
        return
    dates = sorted({d["tradingDate"] for d in labels})
    date_idx = {d: i for i, d in enumerate(dates)}
    next_map = build_next_day_map(db, dates)
    rows = []
    for d in labels:
        info = next_day_info(next_map, dates, date_idx, d["tradingDate"], d["code"])
        if info:
            rows.append({**d, "nextPct": info["pct"], "nextLianban": info["lianban"]})

    depths = [d["catalystDepth"] for d in labels if d.get("catalystDepth")]
    depth = depth_distribution_metrics(depths)
    group = driver_group_metrics(rows)
    direction = (direction_consistent_with_phase3(group["lianbanRates"])
                 if not group.get("insufficient") and not group.get("groupOk") else {"rho": None, "consistent": False})
    v = verdict(depth, group, direction)

    pilot1 = list(db["hotlist_jev_driver_labels_v2_pilot1"].find({"status": "ok"},
                                                                 {"tradingDate": 1, "code": 1, "label": 1, "freshness": 1, "matchNoul": 1}))
    stab_label = stability_vs_pilot1(labels, pilot1, "label")
    stab_fresh = stability_vs_pilot1(labels, pilot1, "freshness")
    buckets = bucket_next_day(rows)

    # freshness 分布（观察）
    fresh: dict[str, int] = defaultdict(int)
    for d in labels:
        if d.get("freshness"):
            fresh[d["freshness"]] += 1

    lines = ["# jev 涨停打标 v2 重铸试点（pilot2，catalyst_depth）战报", "",
             f"- 标签 {len(labels)}（ok），有心照链次日匹配 {len(rows)}，窗口 {dates[0]} → {dates[-1]}", "",
             "## 门A catalyst_depth 轴方差（主）", "",
             f"- {depth}",
             f"- 展开={depth.get('expanded')}（四实质桶 n≥5 且 最大桶<70% 且 逃生口≤15%）", "",
             "## 门B 驱动分组保留", "",
             f"- {group}",
             f"- 方向一致性 vs 阶段3 全窗参考：{direction}", "",
             "## 稳定性对照（pilot2 vs pilot1，观察项）", "",
             f"- driver_type：{stab_label}",
             f"- catalyst_freshness：{stab_fresh}", "",
             "## catalyst_depth 分桶次日方向（观察项，无硬门）", "",
             f"- {buckets}", "",
             "## catalyst_freshness 分布（观察）", "",
             f"- {dict(fresh)}", "",
             "## 判定依据", "",
             f"- {'✓' if depth.get('expanded') else '✗'} 门A depth 轴方差",
             f"- {'✓' if group.get('groupOk') else '✗'} 门B 驱动分组（p<0.05 且 极差≥15pct）",
             f"- 稳定性/分桶方向=观察项（无硬门）", "",
             f"## 判定：{v}"]
    if v == "INSUFFICIENT" and direction.get("consistent"):
        lines.append("")
        lines.append("注：门B 单月显著性不足但排序方向与阶段3 全窗一致——候选扩窗复验（10 月弹药积累后终判），非 REJECT。")

    out = "docs/hotlist-jev/phase3-jiuyan-v2-repilot-report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
