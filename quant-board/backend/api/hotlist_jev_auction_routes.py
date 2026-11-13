# -*- coding: utf-8 -*-
"""竞价龙头投喂读口 + 单只重跑（vA1，预登记 auction-leader-vA1-preregistration-20261113）。

合同镜像 /theme-leaders（date | start/end | with_narrative；500 档上限+truncated；
sector doc 合入个股行；缺档行 labelMissing 披露——行源 = labels ∪ auctionPush roster，
打标停跑不阻断清单，fail-visible）。
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.data.repositories import repository_factory

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev-auction"])

COLLECTION = "hotlist_jev_auction_leader_labels"
LIVE_COLLECTION = "kpl_live_daily"


def _row_of(d: dict, sector: dict | None, with_narrative: bool) -> dict:
    answers = d.get("answers") or {}
    model = d.get("modelAnswers") or {}
    seal = answers.get("auction_leader_seal_today") or {}
    mseal = model.get("auction_leader_seal_today") or {}
    sec_answers = (sector or {}).get("answers") or {}
    row = {
        "tradingDate": d.get("tradingDate"), "code": d.get("code"),
        "name": d.get("name"), "board": d.get("board"),
        "auctionPct": d.get("auctionPct"),
        "choice": d.get("auctionSealToday"),
        "probabilities": d.get("auctionSealProbabilities"),
        "choiceConfidence": seal.get("confidence"),
        "leaderCatalystHardness": d.get("leaderCatalystHardness"),
        "leaderCatalystHardnessConfidence": (answers.get("leader_catalyst_hardness") or {}).get("confidence"),
        "auctionSeatDurability": d.get("auctionSeatDurability"),
        "auctionSeatDurabilityConfidence": (answers.get("auction_seat_durability") or {}).get("confidence"),
        "themeSpeculationDepth": sec_answers.get("theme_speculation_depth", {}).get("choice")
        if isinstance(sec_answers.get("theme_speculation_depth"), dict) else d.get("themeSpeculationDepth"),
        "themeContinuation": sec_answers.get("theme_continuation", {}).get("choice")
        if isinstance(sec_answers.get("theme_continuation"), dict) else d.get("themeContinuation"),
        "modelChoice": mseal.get("choice"), "modelProbabilities": mseal.get("probabilities"),
        "gate": d.get("gate"), "status": d.get("status"),
        "sampleOrigin": d.get("sampleOrigin"), "computedAt": d.get("computedAt"),
        "questionSetVersion": d.get("questionSetVersion"),
        "evidenceMissing": d.get("evidenceMissing"),
        "evidenceMissingReason": d.get("evidenceMissingReason"),
        "evidenceEventTitles": d.get("evidenceEventTitles"),
        "evidenceNewsTitles": d.get("evidenceNewsTitles"),
        "outcomeSealedToday": d.get("outcomeSealedToday"),
        "outcomeSource": d.get("outcomeSource"), "outcomeCross": d.get("outcomeCross"),
        "corpusState": d.get("corpusState"), "auctionPushState": d.get("auctionPushState"),
        "lhbState": d.get("lhbState"), "sectorJudgmentState": d.get("sectorJudgmentState"),
        "model": d.get("model"), "usage": d.get("usage"), "latencyMs": d.get("latencyMs"),
        "errorCode": d.get("errorCode"), "errorDetail": d.get("errorDetail"),
        "labelMissing": False,
    }
    if with_narrative:
        row["narrative"] = d.get("narrative")
        row["questionsRaw"] = d.get("questionsRaw")
        row["responseRaw"] = d.get("responseRaw")
    return row


@router.get("/auction-leaders")
def get_auction_leaders(date: str | None = None, start: str | None = None,
                        end: str | None = None, with_narrative: int = 0) -> Any:
    """竞价龙头投喂读口（合同镜像 theme-leaders；行源 = labels ∪ 推送 roster）。"""
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:  # noqa: BLE001 — 读库降级结构化（不伪装空）
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    col = db[COLLECTION]
    query: dict[str, Any] = {}
    if date:
        query["tradingDate"] = date
    else:
        rng: dict[str, Any] = {}
        if start:
            rng["$gte"] = start
        if end:
            rng["$lte"] = end
        if rng:
            query["tradingDate"] = rng
    cursor = col.find(query).sort([("tradingDate", -1), ("board", 1), ("code", 1)])
    if not query:
        cursor = cursor.limit(500)
    docs = list(cursor)
    truncated = bool(not query) and len(docs) >= 500
    sector_docs = {(str(d.get("tradingDate")), str(d.get("board"))): d
                   for d in docs if d.get("docKind") == "sector"}
    rows = [_row_of(d, sector_docs.get((str(d.get("tradingDate")), str(d.get("board")))),
                    bool(with_narrative))
            for d in docs if d.get("docKind") != "sector"]
    labeled = {(r["tradingDate"], r["code"]) for r in rows}
    # 推送 roster 缺档行（打标停跑/当日未跑不阻断清单，fail-visible）
    live_q: dict[str, Any] = {"_id": date} if date else {}
    if not date:
        rng2: dict[str, Any] = {}
        if start:
            rng2["$gte"] = start
        if end:
            rng2["$lte"] = end
        if rng2:
            live_q = {"_id": rng2}
    missing = 0
    roster_error = None
    roster_truncated = False
    try:
        # 投影只取 auctionPush（重文档 items 不进读口）；无参模式 500 帽与 labels 同口径
        live_docs = sorted(db[LIVE_COLLECTION].find(live_q, {"auctionPush": 1}),
                           key=lambda d: str(d.get("_id") or ""), reverse=True)
        if not date and not start and not end:
            roster_truncated = len(live_docs) > 500
            live_docs = live_docs[:500]
        for ld in live_docs:
            push = ld.get("auctionPush") or {}
            for s in push.get("stocks") or []:
                key = (str(ld.get("_id")), str(s.get("code")))
                if key in labeled:
                    continue
                missing += 1
                rows.append({"tradingDate": str(ld.get("_id")), "code": s.get("code"),
                             "name": s.get("name"), "board": s.get("board"),
                             "auctionPct": s.get("pct"), "labelMissing": True})
    except Exception as exc:  # noqa: BLE001 — 直播归档读失败不阻断 labels 清单（fail-visible 留痕）
        roster_error = f"{type(exc).__name__}: {exc}"
    rows.sort(key=lambda r: (str(r.get("tradingDate") or ""), str(r.get("board") or ""),
                             str(r.get("code") or "")), reverse=False)
    rows.sort(key=lambda r: str(r.get("tradingDate") or ""), reverse=True)
    nf: dict[str, Any] = {"labelMissingRows": missing}
    if roster_error:
        nf["rosterError"] = roster_error
    if roster_truncated:
        nf["rosterTruncated"] = True
    if not rows:
        return {"ok": True, "no_data": True, "leaders": [], "sectorCount": len(sector_docs),
                "nodeFilter": nf, "truncated": truncated}
    return {"ok": True, "leaders": rows, "sectorCount": len(sector_docs),
            "nodeFilter": nf, "truncated": truncated}


class AuctionLeaderRerunPayload(BaseModel):
    date: str
    code: str
    datasetId: str | None = None


@router.post("/auction-leaders/rerun")
def post_auction_leader_rerun(payload: AuctionLeaderRerunPayload) -> dict[str, Any]:
    """单只竞价龙头-日重跑（force 覆盖幂等；computedAt 真重判校验，F6 同款）。

    预算披露：force 下同板块 sector doc 一并重判（共 2 次 jev 调用，页内 confirm 同款文案）。
    """
    if not ((os.environ.get("JEV_TYPESAFE_KEY") or "").strip()
            or (os.environ.get("JEV_CF_TOKEN") or "").strip()):
        return {"ok": False, "errorCode": "missing_token",
                "error": "JEV_TYPESAFE_KEY / JEV_CF_TOKEN not configured"}
    date = (payload.date or "").strip()
    code = (payload.code or "").strip()[-6:]
    if not date or not code:
        return {"ok": False, "errorCode": "bad_payload", "error": "date and code required"}
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        from backend.analysis.hotlist.jev_driver_ammo import DEFAULT_DATASET_ID
        from backend.operations.auction_leader_label import (
            COLLECTION as COL, SAMPLE_ORIGIN_LIVE, run)
        col = db[COL]
        before = col.find_one({"_id": f"{date}:{code}"}, {"computedAt": 1, "sampleOrigin": 1})
        before_at = (before or {}).get("computedAt")
        summary = run(date, confirm_budget=True, force=True, codes={code},
                      dataset_id=payload.datasetId or DEFAULT_DATASET_ID,
                      sample_origin=(before or {}).get("sampleOrigin") or SAMPLE_ORIGIN_LIVE)
        doc = col.find_one({"_id": f"{date}:{code}"})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "degraded": True, "reason": f"auction_leader_rerun_failed: {exc}"}
    if doc is None:
        return {"ok": False, "errorCode": "not_written",
                "error": f"{date}:{code} 无存档（该 code 不在当日推送名单）"}
    if before is not None and doc.get("computedAt") == before_at:
        return {"ok": False, "errorCode": "not_rerun",
                "error": f"{date}:{code} computedAt 未刷新（入口跳过或幂等命中，未真重判）"}
    return {"ok": True,
            "summary": {"labeled": summary.get("leaders"), "okCount": summary.get("okCount"),
                        "degraded": summary.get("degraded"),
                        "tokensUsed": summary.get("tokensUsed")},
            "doc": {"tradingDate": doc.get("tradingDate"), "code": doc.get("code"),
                    "name": doc.get("name"), "board": doc.get("board"),
                    "status": doc.get("status"), "sampleOrigin": doc.get("sampleOrigin"),
                    "choice": doc.get("auctionSealToday"), "gate": doc.get("gate"),
                    "model": doc.get("model"), "usage": doc.get("usage"),
                    "latencyMs": doc.get("latencyMs"), "errorCode": doc.get("errorCode"),
                    "errorDetail": doc.get("errorDetail"),
                    "computedAt": doc.get("computedAt")}}