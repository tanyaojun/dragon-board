# -*- coding: utf-8 -*-
"""jev 涨停打标 v2 战果判定报告：三门（预登记）+ 新旧迁移矩阵。

设计依据 docs/hotlist-jev/jev-driver-label-v2-design.md §1/§5（先冻结再开火）：
  门1 Noul 修复（主）：分布展开 IQR≥0.30 且 低组(<0.3)占比≥15%；效果=高组(>0.7)−低组 次日 pct 差
      ≥2pct 正向 且 Mann-Whitney（greater）p<0.05。基线：旧链 IQR 0.19 / 低组 2.7% / 差 0.44pct p=0.30。
  门2 驱动分组复验：Kruskal p<0.05（n≥8 组）且 连板率极差≥15pct。
  门3 freshness：观察项无硬门。
  单月市况风险预登记：门2 p 不显著但七类连板率排序与阶段3 全窗参考（Spearman ρ≥0.5）一致
      → INSUFFICIENT-扩窗复验，不判 REJECT。
判定语义：门1 分布未展开=REJECT（修复失败）；全过=PASS_CANDIDATE；其余=INSUFFICIENT。
产物 docs/hotlist-jev/phase3-jiuyan-v2-report.md。
"""
from __future__ import annotations

import statistics
from collections import defaultdict

# 阶段3 全窗参考连板率（phase3-driver-report.md 冻结值，排序方向一致性对照用）
PHASE3_REF_LIANBAN = {"ma_restructure": 21.3, "order_earnings": 14.3, "concept_stretch": 11.6,
                      "industry_cycle": 8.2, "policy": 6.2, "product_event": 4.1, "capital_flow": 1.8}
NOUL_HIGH, NOUL_LOW = 0.7, 0.3


def quartile(vals: list[float], p: float) -> float:
    """与 diagnose_jev_temp_crowding 同法（idx=int(p*(n-1))），保证跨报告可比。"""
    s = sorted(vals)
    return s[min(len(s) - 1, max(0, int(p * (len(s) - 1))))]


def noul_distribution_metrics(nouls: list[float]) -> dict:
    """门1 分布展开读数：IQR、低组占比（纯函数，方向无关）。"""
    if len(nouls) < 10:
        return {"n": len(nouls), "iqr": None, "lowShare": None, "expanded": False, "insufficient": True}
    p25, p75 = quartile(nouls, 0.25), quartile(nouls, 0.75)
    low_share = sum(1 for v in nouls if v < NOUL_LOW) / len(nouls)
    return {"n": len(nouls), "p25": round(p25, 3), "p75": round(p75, 3),
            "iqr": round(p75 - p25, 3), "lowShare": round(low_share, 4),
            "expanded": bool(p75 - p25 >= 0.30 and low_share >= 0.15), "insufficient": False}


def noul_effect_metrics(pairs: list[tuple[float, float]]) -> dict:
    """门1 效果读数：高组−低组次日 pct 差（方向语义：diff=mean(high)−mean(low)，锁定）。"""
    hi = [pct for noul, pct in pairs if noul > NOUL_HIGH]
    lo = [pct for noul, pct in pairs if noul < NOUL_LOW]
    if len(hi) < 8 or len(lo) < 8:
        return {"nHigh": len(hi), "nLow": len(lo), "diff": None, "p": None,
                "effectOk": False, "insufficient": True}
    from scipy.stats import mannwhitneyu

    diff = statistics.mean(hi) - statistics.mean(lo)
    _, p = mannwhitneyu(hi, lo, alternative="greater")
    return {"nHigh": len(hi), "meanHigh": round(statistics.mean(hi), 2),
            "nLow": len(lo), "meanLow": round(statistics.mean(lo), 2),
            "diff": round(diff, 2), "p": round(p, 4),
            "effectOk": bool(diff >= 2 and p < 0.05), "insufficient": False}


def driver_group_metrics(rows: list[dict]) -> dict:
    """门2 读数：驱动分组 Kruskal + 连板率极差（rows 需含 label/nextPct/nextLianban）。"""
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
    """门2 单月显著性兜底：七类连板率排序 vs 阶段3 全窗参考，Spearman ρ≥0.5 视为方向一致。"""
    common = [k for k in PHASE3_REF_LIANBAN if k in lianban_rates]
    rho = _spearman([PHASE3_REF_LIANBAN[k] for k in common], [lianban_rates[k] for k in common])
    return {"rho": rho, "consistent": bool(rho is not None and rho >= 0.5)}


def verdict(dist: dict, effect: dict, group: dict, direction: dict) -> str:
    """判定映射（预登记）：分布未展开=REJECT；全过=PASS_CANDIDATE；其余=INSUFFICIENT。"""
    if dist.get("insufficient") or not dist.get("expanded"):
        return "REJECT"
    if effect.get("effectOk") and group.get("groupOk"):
        return "PASS_CANDIDATE"
    if not group.get("groupOk") and direction.get("consistent"):
        return "INSUFFICIENT"  # 单月显著性不足但方向与全窗一致 → 扩窗复验，非 REJECT
    return "INSUFFICIENT"


def build_migration(v1: list[dict], v2: list[dict]) -> dict:
    """新旧迁移：同 (date, code) 交叉表 + Noul 分位对比（重叠对）。"""
    old = {f"{d['tradingDate']}:{d['code']}": d for d in v1 if d.get("label")}
    new = {f"{d['tradingDate']}:{d['code']}": d for d in v2 if d.get("label")}
    common = sorted(set(old) & set(new))
    cross: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    same = 0
    for key in common:
        a, b = old[key]["label"], new[key]["label"]
        cross[a][b] += 1
        same += a == b
    old_n = [d["matchNoul"] for d in (old[k] for k in common) if isinstance(d.get("matchNoul"), (int, float))]
    new_n = [d["matchNoul"] for d in (new[k] for k in common) if isinstance(d.get("matchNoul"), (int, float))]
    quant = lambda vs: ({k: round(quartile(vs, p), 3) for k, p in (("p25", .25), ("p50", .5), ("p75", .75))}
                        if len(vs) >= 10 else None)
    return {"overlap": len(common), "sameLabel": same,
            "sameShare": round(same / len(common), 3) if common else None,
            "cross": {a: dict(b) for a, b in sorted(cross.items())},
            "noulQuantiles": {"v1": quant(old_n), "v2": quant(new_n)}}


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

    nouls = [r["matchNoul"] for r in rows if isinstance(r.get("matchNoul"), (int, float))]
    dist = noul_distribution_metrics(nouls)
    # 全量分布对照（不要求次日语料）：区分"语料子集偏斜"还是"轴本身无方差"——试点 2026-10-02 结论=后者
    nouls_all = [d["matchNoul"] for d in labels if isinstance(d.get("matchNoul"), (int, float))]
    dist_all = noul_distribution_metrics(nouls_all)
    effect = noul_effect_metrics([(r["matchNoul"], r["nextPct"]) for r in rows
                                  if isinstance(r.get("matchNoul"), (int, float))])
    group = driver_group_metrics(rows)
    direction = (direction_consistent_with_phase3(group["lianbanRates"])
                 if not group.get("insufficient") and not group.get("groupOk") else {"rho": None, "consistent": False})
    v = verdict(dist, effect, group, direction)

    # 门3 freshness 观察（无硬门）
    fresh: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.get("freshness"):
            fresh[r["freshness"]].append(r["nextPct"])
    fresh_rows = {k: {"n": len(v_), "nextPctMean": round(statistics.mean(v_), 2)} for k, v_ in sorted(fresh.items())}

    v1_labels = [d for d in db["hotlist_jev_driver_labels"].find({"status": "ok"}, {"tradingDate": 1, "code": 1, "label": 1, "matchNoul": 1})]
    migration = build_migration(v1_labels, labels)

    # 连板/首板分层（韭研 day 字段：day≥2=连板，缺失/1=首板；阶段3 已证锚点复核）
    layers = {}
    for flag, name in ((True, "连板"), (False, "首板")):
        def is_lianban(r):
            day = (r.get("jiuyanContext") or {}).get("day")
            return isinstance(day, int) and day >= 2
        sub = [r for r in rows if is_lianban(r) == flag]
        if sub:
            layers[name] = {"n": len(sub),
                            "lianban": round(sum(x["nextLianban"] for x in sub) / len(sub) * 100, 1),
                            "nextPctMean": round(statistics.mean(x["nextPct"] for x in sub), 2)}

    lines = ["# jev 涨停打标 v2（韭研弹药版）战果判定报告", "",
             f"- 标签 {len(labels)}（ok），有心照链次日匹配 {len(rows)}，窗口 {dates[0]} → {dates[-1]}", "",
             "## 门1 Noul 修复（主）", "",
             f"- 分布（次日语料子集）：{dist}",
             f"- 分布（全量标签对照）：{dist_all}",
             f"- 效果（高>0.7 vs 低<0.3，diff=mean(high)−mean(low)）：{effect}",
             f"- 展开={dist.get('expanded')} effectOk={effect.get('effectOk')}", "",
             "## 门2 驱动分组复验", "",
             f"- {group}",
             f"- 方向一致性 vs 阶段3 全窗参考：{direction}", "",
             "## 门3 catalyst_freshness 观察（无硬门）", "",
             f"- {fresh_rows}", "",
             "## 连板 vs 首板分层（韭研 day 字段）", "",
             f"- {layers}", "",
             "## 迁移矩阵（v1 旧链 × v2 新链，同股同日）", "",
             f"- {migration}", "",
             "## 判定依据", "",
             f"- {'✓' if dist.get('expanded') else '✗'} 门1 分布展开（IQR≥0.30 且 低组≥15%）",
             f"- {'✓' if effect.get('effectOk') else '✗'} 门1 效果（差≥2pct 正向 且 p<0.05）",
             f"- {'✓' if group.get('groupOk') else '✗'} 门2 分组（p<0.05 且 极差≥15pct）",
             f"- 门3 观察项（无硬门）", "",
             f"## 判定：{v}"]
    if v == "INSUFFICIENT" and direction.get("consistent"):
        lines.append("")
        lines.append("注：门2 单月显著性不足但排序方向与阶段3 全窗一致——候选扩窗复验（10 月弹药积累后终判），非 REJECT。")

    out = "docs/hotlist-jev/phase3-jiuyan-v2-report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print(f"-> {out}")


if __name__ == "__main__":
    main()
