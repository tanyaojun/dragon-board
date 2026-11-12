# -*- coding: utf-8 -*-
"""第4课市场情绪周期 P2 事件研究（零 token，只读 Mongo，不写库）。

预登记 market-cycle-preregistration-20261112.md §八 P2 gate③：
- 突破后天花板延续率（成熟窗 windowDays==20；暖机突破参照窗不足，单列不并入）；
- wzs / 突破命中后次日溢价（以次日 relayIndex 变化度量市场情绪延续，参照列单源）；
- 与大盘 wzs（relayIndex 口径，reference.marketWzs.hit）一致率 / 分歧清单。

口径注记：次日溢价用 ΔrelayIndex（市场级情绪指数）而非个股收益——市场级信号对应市场级
度量；除权日 relayIndex 失真不伪精确（沿报告 §九.4）。无自动 ground truth，供用户盘感终审。
用法：python -m scripts.market_cycle_event_study [--from YYYY-MM-DD --to YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
from statistics import mean, median

from backend.data.repositories.repository_factory import get_runtime_mongodb_database


def _next_delta(by_date, dates, idx, dt):
    i = idx.get(dt)
    if i is None or i + 1 >= len(dates):
        return None
    a = (by_date[dt].get("reference") or {}).get("relayIndex")
    b = (by_date[dates[i + 1]].get("reference") or {}).get("relayIndex")
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(b - a, 2)
    return None


def run(start=None, end=None):
    db = get_runtime_mongodb_database()
    docs = sorted((d for d in db["hotlist_jev_market_cycle"].find({})
                   if d.get("tradingDate")
                   and (not start or d["tradingDate"] >= start)
                   and (not end or d["tradingDate"] <= end)),
                  key=lambda d: d["tradingDate"])
    by_date = {d["tradingDate"]: d for d in docs}
    dates = [d["tradingDate"] for d in docs]
    idx = {dt: i for i, dt in enumerate(dates)}

    # 1) 突破天花板延续率
    bt = [(d, e) for d in docs for e in (d.get("events") or [])
          if e.get("type") == "spaceBreakthrough"]
    mature = [(d, e) for d, e in bt if e.get("windowDays") == 20]
    warm = [(d, e) for d, e in bt if e.get("windowDays") != 20]
    cont = []
    for d, e in mature:
        i = idx[d["tradingDate"]]
        nd = docs[i + 1] if i + 1 < len(docs) else None
        nm = (nd or {}).get("ceiling", {}).get("maxBoard")
        if isinstance(nm, int):
            cont.append({"date": d["tradingDate"], "maxBoard": e["maxBoard"],
                         "nextMaxBoard": nm, "hold": nm >= e["maxBoard"]})
    hold_rate = (sum(c["hold"] for c in cont) / len(cont)) if cont else None

    # 2) wzs / 突破后次日 relayIndex 变化
    wzs_days = [d["tradingDate"] for d in docs
                if (d.get("transition") or {}).get("trigger") == "high_tolerance"
                and (d.get("transition") or {}).get("to") == "wzs"]
    bt_days = [d["tradingDate"] for d, e in mature]
    wzs_d = [x for x in (_next_delta(by_date, dates, idx, dt) for dt in wzs_days) if x is not None]
    bt_d = [x for x in (_next_delta(by_date, dates, idx, dt) for dt in bt_days) if x is not None]

    # 3) 与大盘 wzs 一致率 / 分歧
    mkt_wzs = {d["tradingDate"] for d in docs
               if ((d.get("reference") or {}).get("marketWzs") or {}).get("hit")}
    cyc_wzs = set(wzs_days)
    agree = sorted(cyc_wzs & mkt_wzs)
    div_cyc = sorted(cyc_wzs - mkt_wzs)   # 本状态机判 wzs 而大盘 wzs 未命中
    div_mkt = sorted(mkt_wzs - cyc_wzs)   # 大盘 wzs 命中而本状态机未判 wzs

    def _stat(xs):
        return {"n": len(xs), "mean": round(mean(xs), 2) if xs else None,
                "median": round(median(xs), 2) if xs else None,
                "posRate": round(sum(1 for x in xs if x > 0) / len(xs), 3) if xs else None}

    return {"days": len(docs), "range": [dates[0], dates[-1]] if dates else None,
            "breakthrough": {"total": len(bt), "mature": len(mature), "warmup": len(warm),
                             "continuation": cont, "holdRate": round(hold_rate, 3) if hold_rate is not None else None},
            "nextDayRelayIndex": {"wzsEntry": _stat(wzs_d), "matureBreakthrough": _stat(bt_d),
                                  "wzsDays": wzs_days, "breakthroughDays": bt_days},
            "marketWzsAgreement": {"cycleWzsN": len(cyc_wzs), "marketWzsN": len(mkt_wzs),
                                   "agreeN": len(agree), "agree": agree,
                                   "divergeCycleOnly": div_cyc, "divergeMarketOnly": div_mkt}}


if __name__ == "__main__":
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=None)
    ap.add_argument("--to", dest="end", default=None)
    args = ap.parse_args()
    print(json.dumps(run(args.start, args.end), ensure_ascii=False, indent=1))
