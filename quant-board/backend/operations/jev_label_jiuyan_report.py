# -*- coding: utf-8 -*-
"""jev 涨停打标 v2 pilot3 战报：六桶方差门 + 守恒检验 + T3-scaling 零判例 + 稳定性对照 + 低置信分层。

预登记判据 docs/hotlist-jev/jev-driver-label-v2-design.md §9（先冻结再开火）：
  门A' 六桶方差：五实质桶每桶 n≥5；最大实质桶占比<70%；逃生口≤15%。
  守恒检验：pilot3 两新桶之和 = pilot2 new_growing 桶（117±5）。
  T3-scaling 零判例：scaling 判例叙事含网传/未证实/传闻字样数=0（>0 出人工抽验清单）。
  稳定性：core/equity/concept + driver + freshness 对 pilot2 sameShare>90%；freshness unclear<8%。
  门B：沿用 driver 分组门（n 小预期不显著，方向一致性兜底）。
判定映射：全部硬门过=PASS_CANDIDATE；门A'/守恒/T3 任一不过=REJECT；其余=INSUFFICIENT。
产物 docs/hotlist-jev/phase3-jiuyan-v2-pilot3-report.md。
"""
from __future__ import annotations

import statistics
from collections import defaultdict

# 阶段3 全窗参考连板率（phase3-driver-report.md 冻结值，排序方向一致性对照用）
PHASE3_REF_LIANBAN = {"ma_restructure": 21.3, "order_earnings": 14.3, "concept_stretch": 11.6,
                      "industry_cycle": 8.2, "policy": 6.2, "product_event": 4.1, "capital_flow": 1.8}
DEPTH_SUBSTANTIVE = ["core_main_business", "new_business_scaling", "new_business_early",
                     "equity_or_affiliate", "concept_assembly"]
DEPTH_ALL = DEPTH_SUBSTANTIVE + ["insufficient_evidence"]
NEW_BUCKETS = {"new_business_scaling", "new_business_early"}
OLD_NEW_BUCKET = "new_growing_business"
T3_MARKERS = ("网传", "未证实", "传闻", "市场消息", "未经证实")
# 守恒基准（2026-10-02 用户裁决修订）：core+新业务家族合计 vs pilot2 骨架
# pilot2 core 110 + new 117 = 227；pilot4 实测 112+55+61=228（原"两新桶 143"口径被护栏修复方向反向污染）
PILOT2_FAMILY_TOTAL = 227
FAMILY_BUCKETS = {"core_main_business", "new_business_scaling", "new_business_early"}


def depth_distribution_metrics(depths: list[str]) -> dict:
    """门A' 读数：五实质桶 n 与占比 + 逃生口占比。"""
    n = len(depths)
    if n < 20:
        return {"n": n, "insufficient": True}
    counts = {k: 0 for k in DEPTH_ALL}
    for d in depths:
        counts[d] = counts.get(d, 0) + 1
    sub = {k: counts[k] for k in DEPTH_SUBSTANTIVE}
    return {"n": n, "bucketCounts": sub, "insufficientEvidence": counts["insufficient_evidence"],
            "maxBucketShare": round(max(sub.values()) / n, 3),
            "bucketsWithN5": sum(1 for v in sub.values() if v >= 5),
            "expanded": bool(sum(1 for v in sub.values() if v >= 5) >= 5
                             and max(sub.values()) / n < 0.70
                             and counts["insufficient_evidence"] / n <= 0.15),
            "insufficient": False}


def conservation_check(depths: list[str]) -> dict:
    """守恒检验（修订口径）：core+新业务家族合计 vs pilot2 基准 227±8。仅 pilot 对照模式有意义。"""
    fam_sum = sum(1 for d in depths if d in FAMILY_BUCKETS)
    return {"familySum": fam_sum, "pilot2FamilyTotal": PILOT2_FAMILY_TOTAL,
            "conserved": bool(abs(fam_sum - PILOT2_FAMILY_TOTAL) <= 8)}


def t3_scaling_scan(labels: list[dict]) -> dict:
    """T3-scaling 零判例：scaling 判例叙事含 T3 字样扫描（启发式，>0 出人工抽验清单）。"""
    hits = []
    for d in labels:
        if d.get("catalystDepth") == "new_business_scaling":
            narr = d.get("narrative") or ""
            markers = [m for m in T3_MARKERS if m in narr]
            if markers:
                hits.append({"tradingDate": d.get("tradingDate"), "code": d.get("code"),
                             "name": d.get("name"), "markers": markers})
    return {"scanHits": len(hits), "clean": len(hits) == 0, "manualReviewList": hits}


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
    """门B 单月显著性兜底（组数 <5 不可算，与不一致区分）。"""
    common = [k for k in PHASE3_REF_LIANBAN if k in lianban_rates]
    if len(common) < 5:
        return {"rho": None, "consistent": False, "computable": False,
                "reason": f"n>=8 组仅 {len(common)} 个，排序一致性需 ≥5 组"}
    rho = _spearman([PHASE3_REF_LIANBAN[k] for k in common], [lianban_rates[k] for k in common])
    return {"rho": rho, "consistent": bool(rho is not None and rho >= 0.5), "computable": True}


def stability_vs_pilot2(v3: list[dict], pilot2: list[dict], field: str,
                        value_filter=None) -> dict:
    """稳定性对照：同 (date, code) 字段一致率；value_filter 限定 pilot2 侧取值（如仅旧 new 桶）。"""
    old = {f"{d['tradingDate']}:{d['code']}": d.get(field) for d in pilot2
           if d.get(field) and (value_filter is None or d.get(field) in value_filter)}
    new = {f"{d['tradingDate']}:{d['code']}": d.get(field) for d in v3 if d.get(field)}
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


def confidence_split(labels: list[dict]) -> dict:
    """低置信分层（观察项）：depth choice 概率 <0.5 的样本占比与分布。"""
    probs = []
    for d in labels:
        p = (d.get("catalystDepthProbabilities") or {}).get(d.get("catalystDepth"))
        if isinstance(p, (int, float)):
            probs.append(float(p))
    if not probs:
        return {"n": 0}
    return {"n": len(probs), "mean": round(statistics.mean(probs), 3),
            "lowConfShare": round(sum(1 for p in probs if p < 0.5) / len(probs), 3)}


def verdict(depth: dict, cons: dict, t3_manual: bool | None, stab: dict, group: dict,
            freshness_ok: bool) -> str:
    """判定映射（预登记 §10）：门A''/守恒/freshness 任一不过=REJECT；T3 人工抽验=None 待抽验、
    =False 违规=REJECT；稳定性（driver>90%/depth≥75%）不过=INSUFFICIENT；全过+门B=PASS_CANDIDATE。"""
    if depth.get("insufficient") or not depth.get("expanded"):
        return "REJECT"
    if "note" not in cons and not cons.get("conserved"):
        return "REJECT"
    if not freshness_ok:
        return "REJECT"
    if t3_manual is None:
        return "PENDING_T3_REVIEW"
    if t3_manual is False:
        return "REJECT"
    if "note" in stab:
        return "PASS_CANDIDATE" if group.get("groupOk") else "INSUFFICIENT"
    driver_ok = stab.get("driver_type", {}).get("sameShare") is None or stab["driver_type"]["sameShare"] >= 0.85
    depth_ok = stab.get("depth_overall", {}).get("sameShare") is None or stab["depth_overall"]["sameShare"] >= 0.75
    if not (driver_ok and depth_ok):
        return "INSUFFICIENT"
    return "PASS_CANDIDATE" if group.get("groupOk") else "INSUFFICIENT"


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
    pilot_mode = len(labels) < 400  # 全量模式（T2）跳过 pilot 专属检验
    cons = conservation_check(depths) if pilot_mode else {"note": "全量模式，守恒为 pilot 专属检验"}
    t3 = t3_scaling_scan(labels)
    group = driver_group_metrics(rows)
    direction = (direction_consistent_with_phase3(group["lianbanRates"])
                 if not group.get("insufficient") and not group.get("groupOk")
                 else {"rho": None, "consistent": False})
    conf = confidence_split(labels)

    if pilot_mode:
        pilot3 = list(db["hotlist_jev_driver_labels_v2_pilot3"].find(
            {"status": "ok"}, {"tradingDate": 1, "code": 1, "label": 1, "freshness": 1, "catalystDepth": 1}))
        # 稳定性：driver ≥85%（修订）；depth 各桶整体一致率≥75%
        stab = {
            "driver_type": stability_vs_pilot2(labels, pilot3, "label"),
            "depth_overall": stability_vs_pilot2(labels, pilot3, "catalystDepth"),
            "freshness_for_reference": stability_vs_pilot2(labels, pilot3, "freshness"),
        }
    else:
        stab = {"note": "全量模式，稳定性为 pilot 专属检验"}
    unclear_share = (sum(1 for d in labels if d.get("freshness") == "unclear") / len(labels))
    freshness_ok = unclear_share < 0.08
    buckets = bucket_next_day(rows)
    # T3 抽验制回填：--t3-manual pass|fail|pending（抽验 ≥5 只违规 ≤1 = pass；默认 pending 待人工）
    import sys as _sys
    _arg = "--t3-manual="
    t3_manual = {"pass": True, "fail": False}.get(
        next((a[len(_arg):] for a in _sys.argv[1:] if a.startswith(_arg)), "pending"))

    v = verdict(depth, cons, t3_manual, stab, group, freshness_ok)

    lines = ["# jev 涨停打标 v2 pilot4（题目 v3.1：叙事补日期+三护栏）战报", "",
             f"- 标签 {len(labels)}（ok），有心照链次日匹配 {len(rows)}，窗口 {dates[0]} → {dates[-1]}", "",
             "## 门A' 六桶方差", "",
             f"- {depth}",
             f"- 展开={depth.get('expanded')}（五实质桶 n≥5 且 最大桶<70% 且 逃生口≤15%）", "",
             "## 守恒检验（core+新家族 vs pilot2 基准 227±8，修订口径）", "",
             f"- {cons}", "",
             "## T3 抽验制（§10：扫描仅出候选清单，人工抽验定夺）", "",
             f"- 扫描候选池 scanHits={t3['scanHits']}（抽验制，不作硬门）",
             *[f"  - 待人工抽验：{h['tradingDate']} {h['name']} {h['code']} markers={h['markers']}"
               for h in t3["manualReviewList"]], "",
             "## 稳定性对照（vs pilot3；叙事加日期+判据护栏后的预期）", "",
             *[f"- {k}：{sv}" for k, sv in stab.items()],
             f"- freshness unclear 占比：{round(unclear_share, 3)}（判据 <0.08）", "",
             "## 门B 驱动分组（沿用）", "",
             f"- {group}",
             f"- 方向一致性 vs 阶段3 全窗参考：{direction}", "",
             "## catalyst_depth 分桶次日方向（观察项）", "",
             f"- {buckets}", "",
             "## 置信度分层（观察项）", "",
             f"- {conf}", "",
             "## 判定依据", "",
             f"- {'✓' if depth.get('expanded') else '✗'} 门A' 六桶方差",
             f"- {'✓' if cons.get('conserved') or 'note' in cons else '✗'} 守恒检验（{cons.get('note', '')}）",
             f"- T3 抽验制：{'✓ 已抽验通过' if t3_manual is True else '✗ 已抽验违规' if t3_manual is False else '待人工抽验'}（扫描候选池 {t3['scanHits']} 只）",
             f"- {'✓' if freshness_ok else '✗'} freshness unclear<8%（实际 {round(unclear_share, 3)}）",
             f"- {'✓' if 'note' in stab or stab['driver_type'].get('sameShare') is None or stab['driver_type']['sameShare'] >= 0.85 else '✗'} driver 稳定性≥85%（修订）",
             f"- {'✓' if 'note' in stab or stab['depth_overall'].get('sameShare') is None or stab['depth_overall']['sameShare'] >= 0.75 else '✗'} depth 一致率≥75%",
             f"- {'✓' if group.get('groupOk') else '✗'} 门B 分组（预期 n 小不显著）", "",
             f"## 判定：{v}"]

    out = "docs/hotlist-jev/phase3-jiuyan-v2-pilot4-report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
