# -*- coding: utf-8 -*-
"""涨停打标轨道读数聚合（研究↔展示同步 2026-10-03）：个股四题标签 + 日级相位哨兵。

数据源 hotlist_jev_driver_labels（生产集合）：
- 个股文档 origin=driver_label_jiuyan_v3_pilot（历史写入者标识遵令保留）；
- 日级相位哨兵 origin=phase_band_daily（_id={date}:PHASE）。
纯读聚合，fail-visible：该日无任何文档时 no_data=true + reason，不伪造空成功。
"""
from __future__ import annotations

from typing import Any

PHASE_ORIGIN = "phase_band_daily"


def _counts(values: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        if v:
            out[str(v)] = out.get(str(v), 0) + 1
    return out


def collect_limitup_labels(db: Any, date: str) -> dict[str, Any]:
    """单日涨停叙事聚合：日级哨兵 + 个股标签（热榜排名升序、无排名沉底）+ 分布小结。"""
    phase_doc = db["hotlist_jev_driver_labels"].find_one(
        {"_id": f"{date}:PHASE", "status": "ok"},
        {"phaseBand": 1, "phaseBandProbabilities": 1, "computedAt": 1},
    )
    phase = None
    if phase_doc:
        phase = {
            "band": phase_doc.get("phaseBand"),
            "probabilities": phase_doc.get("phaseBandProbabilities"),
            "computedAt": phase_doc.get("computedAt"),
        }
    stocks: list[dict[str, Any]] = []
    for d in db["hotlist_jev_driver_labels"].find(
            {"tradingDate": date, "status": "ok", "origin": {"$ne": PHASE_ORIGIN}}):
        ctx = d.get("jiuyanContext") or {}
        rank = ctx.get("rank") if isinstance(ctx.get("rank"), int) else None
        stocks.append({
            "code": d.get("code"),
            "name": d.get("name"),
            "label": d.get("label"),
            "labelProbabilities": d.get("driverProbabilities"),
            "catalystDepth": d.get("catalystDepth"),
            "catalystDepthProbabilities": d.get("catalystDepthProbabilities"),
            "freshness": d.get("freshness"),
            "buySideLogic": d.get("buySideLogic"),
            "buySideProbabilities": d.get("buySideProbabilities"),
            "board": ctx.get("board"),
            "inHotlist": bool(ctx.get("inHotlist")),
            "rank": rank,
            "computedAt": d.get("computedAt"),
        })
    stocks.sort(key=lambda x: (x["rank"] is None, x["rank"] if x["rank"] is not None else 9999,
                               str(x["code"])))
    no_data = phase is None and not stocks
    return {
        "ok": True,
        "date": date,
        "phase": phase,
        "stocks": stocks,
        "summary": {
            "total": len(stocks),
            "label": _counts([x["label"] for x in stocks]),
            "catalystDepth": _counts([x["catalystDepth"] for x in stocks]),
            "buySideLogic": _counts([x["buySideLogic"] for x in stocks]),
        },
        "noData": no_data,
        "reason": None if not no_data else f"{date} 无涨停打标文档（非交易日或当日未跑）",
    }
