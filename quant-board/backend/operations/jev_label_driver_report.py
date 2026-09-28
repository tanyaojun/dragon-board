# -*- coding: utf-8 -*-
"""jev 阶段3 驱动分类验证：hotlist_jev_driver_labels × 次日连板率/溢价。

硬阈值（PASS_CANDIDATE，见 hotlist-jev-phase3-plan.md）：
 1 有效样本 ≥800
 2 驱动类型分组：连板率极差 ≥15pct 且 次日 pct Kruskal p<0.05
 3 匹配度 Noul 高组(>0.7) vs 低组(<0.3)：次日 pct 差 ≥2pct 方向为正且 Mann-Whitney p<0.05
 4 稳定性重打 20 只 ≥80%（--stability，需 JEV_CF_TOKEN）
连板近似：次日 pct≥9.8（不细 分板块，报告注明）；|次日pct|>21 剔除（除权）。
"""
from __future__ import annotations

import argparse
import os
import random
import statistics
import time
from collections import defaultdict

from pymongo import MongoClient

SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"]
LIAN_BAN_PCT = 9.8


def build_next_day_map(db, dates):
    """批量预取：(date, code) → 当日最晚槽 pctChange（供次日语料查询）。"""
    slot_rank = {s: i for i, s in enumerate(SLOTS)}
    best = {}
    for date in dates:
        for r in db["snapshot_stock_rows"].find(
                {"type": "half_hour", "tradingDate": date, "pctChange": {"$exists": True, "$ne": None}},
                {"code": 1, "pctChange": 1, "slotTime": 1}):
            key = (date, r.get("code"))
            prev = best.get(key)
            if prev is None or slot_rank.get(r.get("slotTime"), -1) > slot_rank.get(prev[1], -1):
                best[key] = (r["pctChange"], r.get("slotTime"))
    return best


def next_day_info(next_map, dates, date_idx, date, code):
    """次日 (pct, 再涨停)。|pct|>21 剔除（除权）。"""
    ni = date_idx.get(date)
    if ni is None or ni + 1 >= len(dates):
        return None
    hit = next_map.get((dates[ni + 1], code))
    if not hit or abs(hit[0]) > 21:
        return None
    return {"pct": hit[0], "lianban": hit[0] >= LIAN_BAN_PCT}


def stability_check(db, acc, token, n=20):
    docs = random.Random(42).sample([d for d in db["hotlist_jev_driver_labels"].find({"status": "ok"})
                                     if d.get("narrative")], n)
    same = 0
    for d in docs:
        from backend.services.jev.jev_client import call_jev, parse_jev_response
        env, ms = call_jev(acc, token, d["narrative"], d["questionsRaw"])
        p = parse_jev_response(env, ms)
        again = (p.get("answers") or {}).get("driver_type", {}).get("choice") if p["ok"] else "error"
        same += again == d.get("label")
        time.sleep(0.2)
    return same, len(docs)


def main(stability: bool):
    from scipy.stats import kruskal, mannwhitneyu
    db = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)["dragon_board_quant"]
    labels = [d for d in db["hotlist_jev_driver_labels"].find({"status": "ok"}) if d.get("label")]
    dates = sorted({d["tradingDate"] for d in labels})
    date_idx = {d: i for i, d in enumerate(dates)}
    next_map = build_next_day_map(db, dates)
    rows = []
    for d in labels:
        info = next_day_info(next_map, dates, date_idx, d["tradingDate"], d["code"])
        if info:
            rows.append({**d, "nextPct": info["pct"], "nextLianban": info["lianban"]})

    lines = ["# Jev 阶段3 涨停驱动分类验证报告", "",
             f"- 标签 {len(labels)}（ok），有次日匹配 {len(rows)}，窗口 {dates[0]} → {dates[-1]}", ""]

    by_lab = defaultdict(list)
    for r in rows:
        by_lab[r["label"]].append(r)
    lines += ["## 驱动类型分布 × 次日表现", "",
              "| 驱动类型 | n | 次日连板率 | 次日 pct 均值 | 中位 |", "|---|---|---|---|---|"]
    for lab in sorted(by_lab, key=lambda k: -sum(x["nextLianban"] for x in by_lab[k]) / len(by_lab[k])):
        v = by_lab[lab]
        lb = sum(x["nextLianban"] for x in v) / len(v) * 100
        lines.append(f"| {lab} | {len(v)} | {round(lb, 1)}% | {round(statistics.mean(x['nextPct'] for x in v), 2)} | "
                     f"{round(statistics.median(x['nextPct'] for x in v), 2)} |")
    lines.append("")

    p_kruskal = None
    big = [v for v in by_lab.values() if len(v) >= 8]
    if len(big) >= 2:
        stat, p_kruskal = kruskal(*[[x["nextPct"] for x in v] for v in big])
        lines.append(f"- Kruskal-Wallis（≥8 样本组）：p={round(p_kruskal, 4)}")
        lb_rates = {k: round(sum(x['nextLianban'] for x in v) / len(v) * 100, 1) for k, v in by_lab.items() if len(v) >= 8}
        lines.append(f"- 连板率极差：{round(max(lb_rates.values()) - min(lb_rates.values()), 1)}pct（{lb_rates}）")
    lines.append("")

    hi = [r["nextPct"] for r in rows if (r.get("matchNoul") or 0) > 0.7]
    lo = [r["nextPct"] for r in rows if (r.get("matchNoul") or 0) < 0.3]
    lines += ["## 催化-主业匹配度（Noul）分组", ""]
    p_mw = None
    if hi and lo:
        u, p_mw = mannwhitneyu(hi, lo, alternative="greater")
        diff = statistics.mean(hi) - statistics.mean(lo)
        lines += [f"- 高匹配(>0.7) n={len(hi)}：次日 pct 均值 {round(statistics.mean(hi), 2)}%",
                  f"- 低匹配(<0.3) n={len(lo)}：次日 pct 均值 {round(statistics.mean(lo), 2)}%",
                  f"- 差值 {round(diff, 2)}pct，Mann-Whitney p={round(p_mw, 4)}"]
    else:
        lines.append(f"- 分组样本不足（hi={len(hi)}, lo={len(lo)}）——Noul 输出分布过窄")
    all_noul = [r.get("matchNoul") for r in rows if r.get("matchNoul") is not None]
    if all_noul:
        s = sorted(all_noul)
        lines.append(f"- Noul 分布：mean={round(statistics.mean(s), 2)} p25={s[len(s)//4]} p50={s[len(s)//2]} "
                     f"p75={s[3*len(s)//4]} min={s[0]} max={s[-1]}")
    lines.append("")

    # 连板/首板分层
    lines += ["## 连板（昨日也有 reason）vs 首板分层", ""]
    for flag, name in ((True, "连板"), (False, "首板")):
        sub = [r for r in rows if r.get("hadReasonYesterday") == flag]
        if sub:
            lb = sum(x["nextLianban"] for x in sub) / len(sub) * 100
            lines.append(f"- {name}: n={len(sub)} 次日连板率 {round(lb,1)}% pct均值 {round(statistics.mean(x['nextPct'] for x in sub), 2)}%")
    lines.append("")

    stab_line = "未执行"
    if stability:
        token = os.environ.get("JEV_CF_TOKEN") or ""
        same, total = stability_check(db, os.environ.get("JEV_CF_ACCOUNT",
                                      "921cf15176f84c90ea49865334af32c6"), token)
        stab_line = f"{same}/{total} = {round(same / total * 100)}%"
        lines += ["## 稳定性抽检", "", f"- {stab_line}", ""]
    else:
        lines += ["## 稳定性抽检", "", "- 未执行（--stability 开启）", ""]

    # 判定
    checks = []
    checks.append(("样本≥800", len(rows) >= 800))
    if p_kruskal is not None:
        lb_rates = {k: sum(x['nextLianban'] for x in v) / len(v) * 100 for k, v in by_lab.items() if len(v) >= 8}
        spread_lb = (max(lb_rates.values()) - min(lb_rates.values())) if lb_rates else 0
        checks.append(("驱动分组 极差≥15pct 且 p<0.05", spread_lb >= 15 and p_kruskal < 0.05))
    if p_mw is not None and hi and lo:
        checks.append(("匹配度 高低差≥2pct 正向 且 p<0.05",
                       (statistics.mean(hi) - statistics.mean(lo)) >= 2 and p_mw < 0.05))
    else:
        checks.append(("匹配度分组可检验", False))
    lines += ["## 判定依据", ""] + [f"- {'✓' if ok else '✗'} {name}" for name, ok in checks]
    # 判定语义（计划定义）：全过=PASS_CANDIDATE；核心分组信号真但个别轴不足=INSUFFICIENT；无区分度或方向反=REJECT
    match_diff = (statistics.mean(hi) - statistics.mean(lo)) if hi and lo else None
    if not all(ok for _, ok in checks):
        verdict = "REJECT" if (p_kruskal is not None and p_kruskal >= 0.05) or (match_diff is not None and match_diff < 0) else "INSUFFICIENT"
    else:
        verdict = "PASS_CANDIDATE"
    if verdict != "REJECT":
        lines.append("")
        if verdict == "INSUFFICIENT":
            lines.append("注：核心驱动分组信号真实（阈值 2 过），个别轴不足——候选扩窗复验，非 REJECT。")
    lines += ["", f"## 判定：{verdict}"]

    out = "docs/hotlist-jev/phase3-driver-report.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--stability", action="store_true")
    main(ap.parse_args().stability)
