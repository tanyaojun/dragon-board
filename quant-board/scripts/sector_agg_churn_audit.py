# -*- coding: utf-8 -*-
"""聚合锚成员漂移审计（一次性研究脚本，只读零写入、零 token、零外部 API）。

问题（2026-10-24 用户提问）：聚合锚成分股个数变化很大（今天 10 只明天 20 只），
读数能否正确反映板块强弱变化？

方法：逐日重算与落库同口径的 N10 成员并集，对相邻两日都在窗的板块-日，
对比两组当日读数——
  - union：今日并集全体（=落库 aggN10 的 pctMean 口径）；
  - stayers：两日并集交集（剔除「今日新进 + 窗口滚出」后的老成员）。
若 union 与 stayers 方向不一致，说明当日读数方向由成员进出（而非老成员涨跌）携带。

另测 v2 资金先手判例（basis 含「资金先手」）上的同款对照——判据健壮性直检。

用法：PYTHONPATH=. ./.venv/Scripts/python.exe scripts/sector_agg_churn_audit.py
"""
from __future__ import annotations

import statistics
from typing import Any

from backend.analysis.hotlist.sector_agg import member_union
from backend.operations.jev_label_jiuyan import (
    _daily_bars,
    bars_need_upto,
    trading_dates_before,
)
from backend.operations.sector_nodes import (
    DEFAULT_DATASET_ID,
    _POOL_CACHE,
    _window_pool_of,
)
from backend.data.repositories.repository_factory import get_runtime_mongodb_database

COLLECTION = "hotlist_jev_sector_nodes"


def _window_pools(db: Any, date: str) -> list[tuple[str, dict[str, set[str]]]]:
    """与 operations._agg_rows_compute 同口径：今日+最近 10 个池 ok 日（新→旧截断）。"""
    candidates = [date] + list(reversed(
        trading_dates_before(db, date, 15, dataset_id=DEFAULT_DATASET_ID)))
    pools: list[tuple[str, dict[str, set[str]]]] = []
    for d in candidates:
        p = _window_pool_of(db, d, DEFAULT_DATASET_ID)
        if p is not None:
            pools.append((d, p))
        if len(pools) >= 10:
            break
    return pools


def main() -> int:
    db = get_runtime_mongodb_database()
    docs = list(db[COLLECTION].find({}, sort=[("tradingDate", 1)]))

    # 1) 逐日重算 N10 并集（与落库同源同口径）
    unions: dict[str, dict[str, set[str]]] = {}
    for doc in docs:
        date = str(doc["tradingDate"])
        pools = _window_pools(db, date)
        boards = {b for _, p in pools for b in p}
        unions[date] = {b: member_union(b, pools, 10)["codes"] for b in boards}
    _POOL_CACHE.clear()
    dates = sorted(unions)

    # 2) 全成员宇宙日线棒一次取齐（本地 vipdoc 优先，与生产同源）
    all_codes: set[str] = set()
    for ub in unions.values():
        for codes in ub.values():
            all_codes |= codes
    with bars_need_upto(dates[-1]):
        bars = {c: _daily_bars(c) for c in sorted(all_codes)}

    def pct_of(code: str, date: str) -> float | None:
        bs = bars.get(code) or []
        idx = next((i for i, b in enumerate(bs) if str(b.get("date")) == date), None)
        if idx is None or idx < 1:
            return None
        c, p = bs[idx].get("close"), bs[idx - 1].get("close")
        if not c or not p:
            return None
        return (float(c) / float(p) - 1) * 100

    def mean_red(codes: set[str], date: str) -> tuple[float | None, float | None, int]:
        pcts = [p for c in sorted(codes) if (p := pct_of(c, date)) is not None]
        if not pcts:
            return None, None, 0
        return (sum(pcts) / len(pcts),
                sum(1 for p in pcts if p > 0) / len(pcts), len(pcts))

    # 3) 相邻文档日配对统计
    pairs: list[dict[str, Any]] = []
    for d0, d1 in zip(dates, dates[1:]):
        for board in sorted(set(unions[d0]) & set(unions[d1])):
            u0, u1 = unions[d0][board], unions[d1][board]
            entrants, stayers = u1 - u0, u1 & u0
            m_u, r_u, q_u = mean_red(u1, d1)
            m_s, r_s, q_s = mean_red(stayers, d1)
            m_e, r_e, q_e = mean_red(entrants, d1)
            pairs.append({
                "date": d1, "board": board, "n0": len(u0), "n1": len(u1),
                "entN": len(entrants), "exitN": len(u0 - u1),
                "jaccard": len(u1 & u0) / len(u1 | u0),
                "mU": m_u, "mS": m_s, "mE": m_e, "qU": q_u, "qS": q_s, "qE": q_e,
                "rU": r_u, "rS": r_s,
            })

    def q(vals: list[float], p: float) -> float:
        s = sorted(vals)
        return s[min(len(s) - 1, int(p * len(s)))]

    print(f"文档日 {len(dates)}（{dates[0]}..{dates[-1]}），相邻日板块-日配对 {len(pairs)} 组，"
          f"成员宇宙 {len(all_codes)} 只")

    ent = [p["entN"] for p in pairs]
    exit_ = [p["exitN"] for p in pairs]
    jac = [p["jaccard"] for p in pairs]
    dn = [abs(p["n1"] - p["n0"]) for p in pairs]
    print(f"成员进出/日：新进 中位 {statistics.median(ent):.0f} / p90 {q(ent, .9):.0f} / 最大 {max(ent)}；"
          f"滚出 中位 {statistics.median(exit_):.0f} / p90 {q(exit_, .9):.0f}；"
          f"|ΔN| 中位 {statistics.median(dn):.0f}；Jaccard 中位 {statistics.median(jac):.2f} / p10 {q(jac, .1):.2f}")

    big = [p for p in pairs if p["entN"] >= 5 or p["n1"] >= 1.8 * max(p["n0"], 1)]
    dbl = [p for p in pairs if p["n0"] >= 5 and p["n1"] >= 2 * p["n0"]]
    print(f"剧变日（新进≥5 或 N 翻近倍）：{len(big)} 组（{len(big)/len(pairs):.0%}），"
          f"其中严格翻倍（N0≥5 且 N1≥2×N0）：{len(dbl)} 组")

    ok = [p for p in pairs if p["mU"] is not None and p["mS"] is not None]
    flips = [p for p in ok if (p["mU"] > 0) != (p["mS"] > 0)]
    diffs = [abs(p["mU"] - p["mS"]) for p in ok]
    print(f"读数方向对照（union vs 老成员 stayers，均可算 {len(ok)} 组）："
          f"方向分歧 {len(flips)} 组（{len(flips)/len(ok):.1%}），"
          f"|Δ读数| 中位 {statistics.median(diffs):.2f}pp / p90 {q(diffs, .9):.2f}pp")

    for name, grp in (("剧变日", big), ("翻倍日", dbl)):
        g = [p for p in grp if p["mU"] is not None and p["mS"] is not None]
        if not g:
            continue
        f = [p for p in g if (p["mU"] > 0) != (p["mS"] > 0)]
        print(f"  {name}内方向分歧：{len(f)}/{len(g)}"
              + (f"（{len(f)/len(g):.0%}）" if g else ""))

    # 新进成员当日均值（机械抬升幅度）与权重
    with_e = [p for p in pairs if p["mE"] is not None and p["qE"]]
    w = [p["qE"] / p["qU"] for p in with_e if p["qU"]]
    me = [p["mE"] for p in with_e]
    print(f"新进成员当日均涨 中位 {statistics.median(me):+.1f}%（应为≈涨停位，机械抬升来源），"
          f"新进占当日报价成员权重 中位 {statistics.median(w):.0%} / p90 {q(w, .9):.0%}")

    # 4) v2 资金先手判例直检
    hand: list[tuple[str, str, dict[str, Any]]] = []
    for doc in docs:
        date = str(doc["tradingDate"])
        for r in doc.get("rows") or []:
            basis = r.get("basis") or []
            if any("资金先手" in str(b) for b in basis):
                p_ = next((x for x in pairs if x["date"] == date and x["board"] == str(r.get("board"))), None)
                if p_:
                    hand.append((date, str(r.get("board")), p_))
    hs = [h for h in hand if h[2]["mS"] is not None]
    h_neg = [h for h in hs if h[2]["mU"] > 0 and h[2]["mS"] <= 0]
    print(f"v2 资金先手判例 {len(hand)} 例（配对可算 {len(hs)}）：老成员口径仍为正 "
          f"{len(hs) - len(h_neg)}/{len(hs)}")
    for h in h_neg:
        mu, ms = h[2]["mU"], h[2]["mS"]
        print(f"  翻案例：{h[1]} {h[0]} union {mu:+.1f}% vs 老成员 {ms:+.1f}%")

    # 5) 最大分歧示例（人工抽验用）
    print("\n— 分歧最大 10 例（|union−stayers|）：")
    for p in sorted(ok, key=lambda x: -abs(x["mU"] - x["mS"]))[:10]:
        me_txt = "—" if p["mE"] is None else f"{p['mE']:+.1f}%"
        print(f"  {p['date']} {p['board']}: N {p['n0']}→{p['n1']}"
              f"（新进{p['entN']}/滚出{p['exitN']}）"
              f" union {p['mU']:+.2f}% vs 老成员 {p['mS']:+.2f}%"
              f"（新进均涨 {me_txt}，占比 {p['qE']}/{p['qU']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
