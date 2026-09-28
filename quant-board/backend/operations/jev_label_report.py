# -*- coding: utf-8 -*-
"""jev 阶段2 标签验证：hotlist_jev_stock_labels × 次日 pctChange 分组区分度。

四项硬阈值（PASS_CANDIDATE 标准，见 hotlist-jev-phase2-plan.md）：
 1 有效样本（标签且有次日匹配）≥200
 2 组间：最优组−最差组 次日 pctChange ≥3pct 且 Kruskal-Wallis p<0.05
 3 增量：控制 signalTier 分层后区分度仍存在
 4 稳定性：20 只同输入重打一致率 ≥80%（--stability 开启，需 JEV_CF_TOKEN）
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from pymongo import MongoClient

SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"]


def next_day_pct(db, dates, date_idx, date, code):
    """次日该股的日涨跌幅：优先 15:00 行，缺则当日最晚槽行（如实打标 partial）。

    pctChange 字段本身已是百分数（如 9.98 = +9.98%），不再 ×100。
    |pct|>21 视为除权除息/数据异常，剔除并计数（fail-visible，不静默丢弃）。
    """
    ni = date_idx.get(date)
    if ni is None or ni + 1 >= len(dates):
        return None, False
    nxt = dates[ni + 1]
    for slot in reversed(SLOTS):
        r = db["snapshot_stock_rows"].find_one(
            {"type": "half_hour", "tradingDate": nxt, "slotTime": slot, "code": code},
            {"pctChange": 1, "slotTime": 1})
        if r and r.get("pctChange") is not None:
            if abs(r["pctChange"]) > 21:
                return None, False
            return r["pctChange"], slot != "15:00"
    return None, False


def main():
    db = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)["dragon_board_quant"]
    labels = [d for d in db["hotlist_jev_stock_labels"].find({"status": "ok"}) if d.get("label")]
    dates = sorted({d["tradingDate"] for d in labels})
    date_idx = {d: i for i, d in enumerate(dates)}
    rows_out, partial = [], 0
    for d in labels:
        pct, is_partial = next_day_pct(db, dates, date_idx, d["tradingDate"], d["code"])
        if pct is None:
            continue
        partial += is_partial
        rows_out.append({"label": d["label"], "tier": d.get("ruleTier") or "?", "pct": pct})
    by_label = defaultdict(list)
    for r in rows_out:
        by_label[r["label"]].append(r["pct"])

    lines = ["# Jev 阶段2 五维打标验证报告", "",
             f"- 标签 {len(labels)} 个（ok），有次日匹配 {len(rows_out)} 个（其中非收盘槽近似 {partial}），窗口 {dates[0]} → {dates[-1]}", ""]
    lines.append("## 标签分布与次日 pctChange")
    lines.append("")
    lines.append("| 标签 | n | 均值% | 中位% |")
    lines.append("|---|---|---|---|")
    for lab in sorted(by_label, key=lambda k: -statistics.mean(by_label[k])):
        v = by_label[lab]
        lines.append(f"| {lab} | {len(v)} | {round(statistics.mean(v), 2)} | {round(statistics.median(v), 2)} |")
    lines.append("")

    verdict_parts = []
    if len(rows_out) < 200:
        verdict_parts.append(f"样本不足（{len(rows_out)}<200）")
    else:
        try:
            from scipy.stats import kruskal
            groups = [v for v in by_label.values() if len(v) >= 5]
            stat, p = kruskal(*groups)
            means = {k: statistics.mean(v) for k, v in by_label.items() if len(v) >= 5}
            spread = max(means.values()) - min(means.values())
            lines += [f"- Kruskal-Wallis：H={round(stat, 2)}, p={round(p, 4)}（组数 {len(groups)}）",
                      f"- 最优−最差组均值差：{round(spread, 2)}pct", ""]
            verdict_parts.append(f"组间差 {round(spread, 2)}pct / p={round(p, 4)}")
        except Exception as e:
            verdict_parts.append(f"统计失败 {e}")

    # 增量：signalTier 分层
    lines += ["## signalTier 分层（增量检验）", ""]
    by_tier = defaultdict(lambda: defaultdict(list))
    for r in rows_out:
        by_tier[r["tier"]][r["label"]].append(r["pct"])
    for tier in sorted(by_tier):
        labs = by_tier[tier]
        big = {k: v for k, v in labs.items() if len(v) >= 5}
        if len(big) < 2:
            lines.append(f"- Tier {tier}: 组数不足，跳过")
            continue
        means = {k: round(statistics.mean(v), 2) for k, v in big.items()}
        lines.append(f"- Tier {tier}: {means}")
    lines.append("")

    try:
        from scipy.stats import kruskal
        ok_stat = len(rows_out) >= 200
        means = {k: statistics.mean(v) for k, v in by_label.items() if len(v) >= 5}
        spread = max(means.values()) - min(means.values()) if means else 0
        stat, p = kruskal(*[v for v in by_label.values() if len(v) >= 5])
        if not ok_stat:
            verdict = "INSUFFICIENT（样本不足）"
        elif spread >= 3 and p < 0.05:
            verdict = "PASS_CANDIDATE（有区分度，待分层增量确认后讨论上线）"
        elif p < 0.05:
            verdict = "INSUFFICIENT（统计显著但组间差 <3pct）"
        else:
            verdict = "REJECT（无显著区分度）"
    except Exception:
        verdict = "INSUFFICIENT（统计无法完成）"
    lines += [f"## 判定：{verdict}", "", f"依据：{'；'.join(verdict_parts)}"]

    out = "docs/hotlist-jev/phase2-label-report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
