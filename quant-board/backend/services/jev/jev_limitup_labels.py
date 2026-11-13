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
                # 归属交易日（2026-10-22 报障修复）：个股复跑（POST /limitup-labels/rerun）
                # 以行内 tradingDate 组 payload，此前缺此字段 → 前端发 undefined → 后端 422，
                # 详情卡重跑按钮永远失败（banner 显示 [object Object]）
                "tradingDate": date,
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
                # 投喂槽位（2026-10-20）：midday=午盘名单口径（12:30 调度投喂已于 2026-11-03 移除，存量档保留）/final=收盘投喂（当日唯一自动投喂口）；
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
    # 2026-11-04 用户需求：名单可见性与打标解耦——韭研名单抓到多少就展示多少，
    # 未打标个股以 unlabeled=True 行并入 stocks（高度/原因/炸板二分等 join 由路由层
    # 统一补齐，与打标行同构；打标行保持既有排序在前，未打标行按名单序沉底）。
    # source 透出名单源（slot/fetchedAt/listTotal），labelCoverage 透出名单/已打标/未打标
    # 三数——前端据此展示采集进度与打标进度，不再盲等打标完成才能看到名单（§4.0）。
    source: dict[str, Any] | None = None
    labeled_codes = {str(s.get("code") or "")[-6:] for s in stocks}
    try:
        proj = {"fetchedAt": 1, "counts.all": 1,
                "fields.name": 1, "fields.stocks.code": 1, "fields.stocks.name": 1}
        slot = "final"
        doc = db["jiuyan_action"].find_one({"_id": f"{date}:final"}, proj)
        if not doc or not any(f.get("stocks") for f in (doc or {}).get("fields") or []):
            slot = "midday"
            doc = db["jiuyan_action"].find_one({"_id": f"{date}:midday"}, proj)
        if doc and any(f.get("stocks") for f in (doc or {}).get("fields") or []):
            list_total = 0
            for field in doc.get("fields") or []:
                bname = field.get("name")
                for st in field.get("stocks") or []:
                    list_total += 1
                    code6 = str(st.get("code") or "")[-6:]
                    if not code6 or code6 in labeled_codes:
                        continue
                    stocks.append({
                        # 2026-11-13 用户裁决：未打标行代码去 SZ/SH 前缀（末 6 位；_strip
                        # 仅剥小写前缀，join 层恒取末 6 位，大写前缀原料亦正确命中）；
                        # 原料档 jiuyan_action 保留原始 code 不动（单一事实源），
                        # join 层本就按末 6 位命中，归一不影响高度/原因/龙序 join
                        "code": code6, "name": st.get("name"),
                        "tradingDate": date, "board": bname, "rank": list_total,
                        # rank=韭研名单序（板块段展平）；打标行 rank=投喂序，同为名单内序
                        "unlabeled": True, "labelSlot": slot,
                        "jiuyanFetchedAt": doc.get("fetchedAt"),
                    })
            source = {"slot": slot, "fetchedAt": doc.get("fetchedAt"),
                      "sourceCountsAll": (doc.get("counts") or {}).get("all"),
                      "listTotal": list_total}
        # final+midday 双缺 → source=None（无名单可展示，走既有 no_data 路径）
    except Exception as exc:  # noqa: BLE001 — 名单读失败不阻断打标行（fail-visible）
        source = {"ok": False, "error": f"jiuyan_source_read_failed: {exc}"}
    labeled_n = sum(1 for s in stocks if not s.get("unlabeled"))
    no_data = phase_doc is None and not stocks and not degraded
    return {
        "ok": True,
        "date": date,
        "phase": phase,
        "phaseStatus": phase_status,
        "phaseError": phase_error,
        "stocks": stocks,
        "summary": {
            # total=stocks 行数（含 unlabeled 行，即名单全量）；label 分布只数打标行
            "total": len(stocks),
            "unlabeledCount": len(stocks) - labeled_n,
            "label": _counts([x["label"] for x in stocks if not x.get("unlabeled")]),
            "catalystDepth": _counts([x["catalystDepth"] for x in stocks if not x.get("unlabeled")]),
            "buySideLogic": _counts([x["buySideLogic"] for x in stocks if not x.get("unlabeled")]),
            "degradedCount": len(degraded),
            "degraded": degraded,
        },
        "source": source,
        "labelCoverage": {
            "fetched": source.get("listTotal") if isinstance(source, dict) else None,
            "labeled": labeled_n,
            "unlabeled": len(stocks) - labeled_n,
        },
        "noData": no_data,
        "reason": None if not no_data else f"{date} 无涨停名单与打标文档（非交易日或当日未采集）",
    }
