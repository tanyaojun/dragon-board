# -*- coding: utf-8 -*-
"""涨停打标轨道读数聚合（研究↔展示同步 2026-10-03）：个股四题标签 + 日级相位哨兵。

数据源 hotlist_jev_driver_labels（生产集合）：
- 个股文档 origin=driver_label_jiuyan_v3_pilot（历史写入者标识遵令保留）；
- 日级相位哨兵 origin=phase_band_daily（_id={date}:PHASE）。
纯读聚合，fail-visible：该日无任何文档时 no_data=true + reason，不伪造空成功。

2026-10-05 批次A（C1，审查 .tmp/jev-limitup-audit.md）：读口不再按 status=ok 过滤——
- degraded/no_data 个股文档进 summary.degraded（code/name/status/errorCode/errorDetail）；
- PHASE 非 ok 时 phaseStatus/phaseError 结构化暴露，phase 仍为 None（不伪造档位）；
- noData 仅在「该日一篇文档都没有」时为 True；stocks 保持 ok-only（前端合同不变）。
同时个股查询改排除式 projection，不拉 narrative/questionsRaw/responseRaw 大字段。
"""
from __future__ import annotations

from typing import Any

PHASE_ORIGIN = "phase_band_daily"

# 排除式 projection：剔除整份叙事/题集/原始响应大字段，其余字段照常透传
_STOCK_EXCLUDED = {"narrative": 0, "questionsRaw": 0, "responseRaw": 0,
                   "stockPhaseQuestionsRaw": 0}


def _counts(values: list[Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        if v:
            out[str(v)] = out.get(str(v), 0) + 1
    return out


def _clip(value: Any, limit: int = 200) -> str | None:
    text = str(value or "").strip()
    return text[:limit] or None


def collect_limitup_labels(db: Any, date: str, with_raw: bool = False) -> dict[str, Any]:
    """单日涨停叙事聚合：日级哨兵 + 个股标签（热榜排名升序、无排名沉底）+ 分布小结。

    with_raw=True（relay_page 调用日志用）：个股条目附带 narrative/questionsRaw/responseRaw/
    model/usage/latencyMs 等原始调用字段（成功路径 responseRaw 本就为 None=fail-visible）；
    默认 False 保持既有合同（不拉大字段，根前端消费方零变化）。
    """
    phase_doc = db["hotlist_jev_driver_labels"].find_one(
        {"_id": f"{date}:PHASE"},
        {"status": 1, "phaseBand": 1, "phaseBandProbabilities": 1,
         "errorCode": 1, "errorDetail": 1, "computedAt": 1},
    )
    phase = None
    phase_status: str | None = None
    phase_error: dict[str, str | None] | None = None
    if phase_doc:
        phase_status = str(phase_doc.get("status") or "unknown")
        if phase_status == "ok":
            phase = {
                "band": phase_doc.get("phaseBand"),
                "probabilities": phase_doc.get("phaseBandProbabilities"),
                "computedAt": phase_doc.get("computedAt"),
            }
        else:
            phase_error = {"errorCode": phase_doc.get("errorCode"),
                           "errorDetail": _clip(phase_doc.get("errorDetail"))}

    stocks: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    for d in db["hotlist_jev_driver_labels"].find(
            {"tradingDate": date, "origin": {"$ne": PHASE_ORIGIN}},
            None if with_raw else _STOCK_EXCLUDED):
        status = str(d.get("status") or "unknown")
        ctx = d.get("jiuyanContext") or {}
        rank = ctx.get("rank")
        rank = rank if isinstance(rank, int) and not isinstance(rank, bool) else None
        if status == "ok":
            item = {
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
                # 投喂槽位（2026-10-20）：midday=12:30 午盘投喂（收盘幂等不重复投喂）/final=收盘投喂；
                # 旧档无此字段 → None（前端不伪造槽位，也不当收盘档冒充）
                "labelSlot": d.get("labelSlot"),
                "jiuyanFetchedAt": d.get("jiuyanFetchedAt"),
                # 个股相位分线（2026-10-04 试点字段，--stock-phase-date 单题补跑写入；未跑日为 None=fail-visible）
                "stockPhasePosition": d.get("stockPhasePosition"),
                "stockPhaseProbabilities": d.get("stockPhaseProbabilities"),
                "computedAt": d.get("computedAt"),
            }
            if with_raw:
                # 调用日志展开用原始字段（含 _id；成功路径 responseRaw=None 如实透传）
                item.update({k: d.get(k) for k in (
                    "_id", "narrative", "questionsRaw", "responseRaw", "model",
                    "usage", "latencyMs", "errorCode", "questionSetVersion", "origin")})
                item["status"] = status
            stocks.append(item)
        else:
            # degraded/no_data 文档：结构化暴露失败面（不混入 stocks，前端合同不变）
            degraded.append({
                "code": d.get("code"),
                "name": d.get("name"),
                "status": status,
                "errorCode": d.get("errorCode"),
                "errorDetail": _clip(d.get("errorDetail")),
                "computedAt": d.get("computedAt"),
            })
    stocks.sort(key=lambda x: (x["rank"] is None, x["rank"] if x["rank"] is not None else 9999,
                               str(x["code"])))
    no_data = phase_doc is None and not stocks and not degraded
    return {
        "ok": True,
        "date": date,
        "phase": phase,
        "phaseStatus": phase_status,
        "phaseError": phase_error,
        "stocks": stocks,
        "summary": {
            "total": len(stocks),
            "label": _counts([x["label"] for x in stocks]),
            "catalystDepth": _counts([x["catalystDepth"] for x in stocks]),
            "buySideLogic": _counts([x["buySideLogic"] for x in stocks]),
            "degradedCount": len(degraded),
            "degraded": degraded,
        },
        "noData": no_data,
        "reason": None if not no_data else f"{date} 无涨停打标文档（非交易日或当日未跑）",
    }
