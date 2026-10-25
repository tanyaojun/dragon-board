# -*- coding: utf-8 -*-
"""V3 影子期对比分析（一次性研究脚本，不进生产链）：活跃股聚合 vs 全成分聚合。

问题（用户 2026-10-25 观察）：成分指数（aggStatic）看起来比聚合指数（aggN10）
相对平稳——全月重算后综合对比验证。

维度：
1. 覆盖与样本基础（映射率、缺棒率）；
2. 平稳性配对检验：同一板块全月 pctMean 时序 std/range，active vs static 配对差；
3. 截面分化：当日全板块读数的截面 std（哪个口径板块间分化更大）；
4. 红盘率同款对比；
5. 扩散信号：redStatic-redActive 差值分布 + 节点档位交叉（wzs 日的扩散形态）。

口径注记：历史日 aggStatic 成分=2026-10-25 批次（前视口径，预登记 §五.1）。
"""
from __future__ import annotations

import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pymongo import MongoClient

START, END = "2026-10-01", "2026-10-23"


def load_rows():
    db = MongoClient("mongodb://127.0.0.1:27017")["dragon_board_quant"]
    docs = sorted(db["hotlist_jev_sector_nodes"].find(
        {"tradingDate": {"$gte": START, "$lte": END}},
        {"tradingDate": 1, "status": 1, "rows.board": 1, "rows.node": 1,
         "rows.aggN10": 1, "rows.aggStatic": 1}), key=lambda d: d["tradingDate"])
    out = []
    for doc in docs:
        for r in doc.get("rows") or []:
            out.append({"date": doc["tradingDate"], "board": r.get("board"),
                        "node": r.get("node"),
                        "a": r.get("aggN10") or {}, "s": r.get("aggStatic") or {}})
    return out


def main():
    rows = load_rows()
    days = sorted({r["date"] for r in rows})
    n_all = len(rows)
    mapped = [r for r in rows if r["s"].get("mapped") is True and r["s"].get("pctMean") is not None]
    unmapped = [r for r in rows if r["s"].get("mapped") is False]
    print(f"== 样本基础 ==")
    print(f"{days[0]}~{days[-1]} 共 {len(days)} 交易日 · {n_all} 板块行 · "
          f"aggStatic 已映射有读数 {len(mapped)}（{len(mapped)/n_all:.0%}）· "
          f"未收录 {len(unmapped)}（{len(unmapped)/n_all:.0%}）")
    # 成分批次披露
    batches = {tuple(sorted(r["s"].get("batchDates") or [])) for r in mapped}
    print(f"成分批次：{sorted({'/'.join(b) for b in batches})}（前视口径）")

    # ── 1. 平稳性配对（同板块全月时序） ─────────────────────────────
    by_board: dict[str, list[dict]] = defaultdict(list)
    for r in mapped:
        if r["a"].get("pctMean") is not None:
            by_board[r["board"]].append(r)
    pairs = []
    for board, rs in by_board.items():
        if len(rs) < 5:
            continue
        sa = st.pstdev([r["a"]["pctMean"] for r in rs])
        ss = st.pstdev([r["s"]["pctMean"] for r in rs])
        ra = max(r["a"]["pctMean"] for r in rs) - min(r["a"]["pctMean"] for r in rs)
        rg = max(r["s"]["pctMean"] for r in rs) - min(r["s"]["pctMean"] for r in rs)
        pairs.append({"board": board, "n": len(rs), "stdA": sa, "stdS": ss,
                      "rangeA": ra, "rangeS": rg})
    calmer = [p for p in pairs if p["stdS"] < p["stdA"]]
    louder = [p for p in pairs if p["stdS"] > p["stdA"]]
    print(f"\n== 平稳性（同板块全月 pctMean 时序，≥5 日样本，{len(pairs)} 板块）==")
    print(f"全成分更平稳：{len(calmer)} 板块（{len(calmer)/len(pairs):.0%}）· "
          f"活跃股更平稳：{len(louder)} 板块（{len(louder)/len(pairs):.0%}）")
    med_a = st.median([p["stdA"] for p in pairs])
    med_s = st.median([p["stdS"] for p in pairs])
    print(f"时序波动(std) 中位数：活跃股 {med_a:.2f}pp vs 全成分 {med_s:.2f}pp "
          f"（全成分≈活跃股的 {med_s/med_a:.0%}）")
    med_ra = st.median([p["rangeA"] for p in pairs])
    med_rs = st.median([p["rangeS"] for p in pairs])
    print(f"全月值域 中位数：活跃股 {med_ra:.2f}pp vs 全成分 {med_rs:.2f}pp "
          f"（压缩到 {med_rs/med_ra:.0%}）")
    print("反例（全成分反而更跳）：" + "、".join(
        f"{p['board']}({p['stdA']:.1f}→{p['stdS']:.1f})"
        for p in sorted(louder, key=lambda x: x["stdS"]-x["stdA"], reverse=True)[:5]) or "无")

    # ── 2. 截面分化（当日板块间分化） ───────────────────────────────
    print(f"\n== 截面分化（当日全板块 pctMean 的截面 std，{len(days)} 日均值）==")
    xs_a, xs_s = [], []
    for d in days:
        a = [r["a"]["pctMean"] for r in mapped if r["date"] == d
             and r["a"].get("pctMean") is not None]
        s = [r["s"]["pctMean"] for r in mapped if r["date"] == d]
        if len(a) >= 3:
            xs_a.append(st.pstdev(a))
        if len(s) >= 3:
            xs_s.append(st.pstdev(s))
    print(f"活跃股截面 std 均值 {st.mean(xs_a):.2f}pp vs 全成分 {st.mean(xs_s):.2f}pp "
          f"（全成分为活跃股的 {st.mean(xs_s)/st.mean(xs_a):.0%}）——板块间谁更分化")

    # ── 3. 红盘率波动 ───────────────────────────────────────────────
    rb_pairs = []
    for board, rs in by_board.items():
        ra_ = [r["a"]["redRatio"] for r in rs if r["a"].get("redRatio") is not None]
        rs_ = [r["s"]["redRatio"] for r in rs if r["s"].get("redRatio") is not None]
        if len(ra_) >= 5 and len(rs_) >= 5:
            rb_pairs.append((board, st.pstdev(ra_), st.pstdev(rs_)))
    print(f"\n== 红盘率时序波动（std，{len(rb_pairs)} 板块）==")
    print(f"活跃股 {st.median([p[1] for p in rb_pairs]):.3f} vs "
          f"全成分 {st.median([p[2] for p in rb_pairs]):.3f}")

    # ── 4. 扩散信号分布 ────────────────────────────────────────────
    diffs = []
    for r in mapped:
        ra_, rs_ = r["a"].get("redRatio"), r["s"].get("redRatio")
        if ra_ is not None and rs_ is not None:
            diffs.append({"board": r["board"], "date": r["date"], "node": r["node"],
                          "diff": round(rs_ - ra_, 3),
                          "ra": ra_, "rs": rs_})
    pos = [d for d in diffs if d["diff"] >= 0.1]
    neg = [d for d in diffs if d["diff"] <= -0.1]
    mid = [d for d in diffs if -0.1 < d["diff"] < 0.1]
    print(f"\n== 扩散度（全成分红盘率−活跃红盘率，{len(diffs)} 行）==")
    print(f"≥+10pp（全成分不弱/轮动接替）{len(pos)}（{len(pos)/len(diffs):.0%}）· "
          f"±10pp 内（同向）{len(mid)}（{len(mid)/len(diffs):.0%}）· "
          f"≤−10pp（强度集中活跃股）{len(neg)}（{len(neg)/len(diffs):.0%}）")
    print("极值轮动接替 TOP5：" + "；".join(
        f"{d['board']} {d['date'][5:]}（活跃{round(d['ra']*100)}%→全成分{round(d['rs']*100)}%，{d['node']}）"
        for d in sorted(diffs, key=lambda x: x["diff"], reverse=True)[:5]))
    print("极值独角戏 TOP5：" + "；".join(
        f"{d['board']} {d['date'][5:]}（活跃{round(d['ra']*100)}%→全成分{round(d['rs']*100)}%，{d['node']}）"
        for d in sorted(diffs, key=lambda x: x["diff"])[:5]))

    # ── 5. 节点档位交叉 ────────────────────────────────────────────
    print(f"\n== 节点档位 × 扩散形态 ==")
    for node in ("wzs", "mainline", "fermenting", "weakening", "collapse", "ice"):
        sub = [d for d in diffs if d["node"] == node]
        if not sub:
            continue
        med = st.median([d["diff"] for d in sub])
        hi_active = sum(1 for d in sub if d["ra"] >= 0.5)
        hi_static = sum(1 for d in sub if d["rs"] >= 0.5)
        print(f"{node:<11} n={len(sub):<3} 扩散差中位 {med:+.3f} · "
              f"活跃红盘≥50%：{hi_active} · 全成分红盘≥50%：{hi_static}")

    # 落盘原始对
    out = {"pairs": pairs, "diffs": diffs}
    Path("logs/agg_static_compare_oct.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n明细落 logs/agg_static_compare_oct.json")


if __name__ == "__main__":
    main()
