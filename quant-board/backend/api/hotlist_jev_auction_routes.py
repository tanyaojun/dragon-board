# -*- coding: utf-8 -*-
"""竞价龙头投喂读口 + 单只重跑（vA2，预登记 auction-leader-vA2-preregistration-20261114）。

合同镜像 /theme-leaders（date | start/end | with_narrative；500 档上限+truncated；
sector doc 合入个股行；缺档行 labelMissing 披露——行源 = labels ∪ auctionPush roster
∪ jiuyan 龙 roster（同一 jiuyan_dragon_roster 实现，禁第二套），打标停跑不阻断清单，
fail-visible）。
"""
from __future__ import annotations

import math
import os
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.data.repositories import repository_factory

router = APIRouter(prefix="/api/hotlist-jev", tags=["hotlist-jev-auction"])

COLLECTION = "hotlist_jev_auction_leader_labels"
LIVE_COLLECTION = "kpl_live_daily"


def _num_or_none(v: Any) -> float | None:
    """quota 值 → float；不可解析/布尔/非有限 → None（不补 0，fail-visible）。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _bid_items_by_date(db: Any, dates: set[str]) -> dict[tuple[str, str], dict]:
    """bid 通道日档（kpl_daban_pool lane=bid）→ {(date, code): item}。

    仅供旧档竞价涨幅修复 join（bidding_pct=09:25 匹配价真竞价值）；读失败/无档
    → 空映射（fail-visible，不阻断读口，不伪装 0）。单写者读口，零网络零模型。
    """
    try:
        from backend.services.kpl_daban_archiver import load_day
    except Exception:      # 模块不可达（极端）：不阻断读口
        return {}
    out: dict[tuple[str, str], dict] = {}
    for date in sorted(d for d in dates if d):
        try:
            payload = load_day(db, date, lane="bid")
        except Exception:
            continue
        if not payload.get("ok"):
            continue
        for it in payload.get("items") or []:
            code = str((it or {}).get("stock_id") or "")[-6:]
            if code and (date, code) not in out:
                out[(date, code)] = it
    return out


def _legacy_evidence_fields(db: Any, date: str, board: Any, cache: dict) -> dict:
    """旧档事件列证据三徽章读口重建（新档已落库直读，不走此路径）。

    单一事实源 build_theme_evidence_block（纯库读、零网络零模型）；按 (date, board)
    缓存。重建失败 → 三字段 None/[]（fail-visible，不阻断读口，不伪造证据）。

    已知近似（评审 M3）：leader_code=None → 板块级口径（lead=分组首成员，同 sector
    doc 口径），非打标时逐股值；深分组且唯一 expound 靠后时 evidenceBoardResolved
    可能 True→False（仅影响事件列徽章门，不影响事件/新闻计数）；industry/kwordTags
    按当前语料窗重算。彻底消除需零 token 回填旧档（登记为迁移态收尾项）。
    """
    key = (str(date), str(board or ""))
    if key in cache:
        return cache[key]
    try:
        from backend.analysis.hotlist import theme_event_digest as digest
        block = digest.build_theme_evidence_block(
            db, board_name=str(board or ""), date=str(date), leader_code=None)
        ev = {"evidenceIndustry": (block.get("industry") or {}).get("name"),
              "evidenceBoardResolved": bool(block.get("boardResolved")),
              "evidenceKwordTags": list(block.get("kwordTags") or [])}
    except Exception:      # noqa: BLE001 — 重建失败不阻断读口
        ev = {"evidenceIndustry": None, "evidenceBoardResolved": None,
              "evidenceKwordTags": []}
    cache[key] = ev
    return ev


def _row_of(d: dict, sector: dict | None, with_narrative: bool,
            bid_item: dict | None = None, ev_override: dict | None = None) -> dict:
    answers = d.get("answers") or {}
    model = d.get("modelAnswers") or {}
    seal = answers.get("auction_leader_seal_today") or {}
    mseal = model.get("auction_leader_seal_today") or {}
    sec_answers = (sector or {}).get("answers") or {}
    # 竞价涨幅/实时涨幅（2026-11-14 修复：旧版 auctionPct 误存推送实时 pct）：
    #   新档（含 realtimePct）→ 落库 auctionPct 已是 bid 通道真竞价值，直读；
    #   旧档 → 读口 join bid 通道 bidding_pct 重建竞价涨幅，原 auctionPct 如实
    #   转 realtimePct（不重跑烧 token；bid 无档 → None，前端显 '-'）。
    if "realtimePct" in d:
        auction_pct, realtime_pct = d.get("auctionPct"), d.get("realtimePct")
    else:
        auction_pct = (bid_item or {}).get("bidding_pct")
        realtime_pct = d.get("auctionPct")
    # 两分支统一归一（评审 M2）：bidding_pct/落库值可为空串或非数字串（协议层原样
    # 透传），缺值一律 None（前端排序/显示垫后），不令 "" 被 JS coerce 成 0 参与排序。
    auction_pct = _num_or_none(auction_pct)
    realtime_pct = _num_or_none(realtime_pct)
    # 事件列证据三徽章：新档直读落库；旧档读口重建（ev_override）
    if ev_override is not None:
        ev_industry = ev_override.get("evidenceIndustry")
        ev_resolved = ev_override.get("evidenceBoardResolved")
        ev_tags = ev_override.get("evidenceKwordTags") or []
    else:
        ev_industry = d.get("evidenceIndustry")
        ev_resolved = d.get("evidenceBoardResolved")
        ev_tags = d.get("evidenceKwordTags") or []
    row = {
        "tradingDate": d.get("tradingDate"), "code": d.get("code"),
        "name": d.get("name"), "board": d.get("board"),
        "auctionPct": auction_pct,
        "realtimePct": realtime_pct,
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
        # 事件列证据三徽章复刻题材龙头（旧档读口重建，fail-visible）
        "evidenceIndustry": ev_industry,
        "evidenceBoardResolved": ev_resolved,
        "evidenceKwordTags": ev_tags,
        "outcomeSealedToday": d.get("outcomeSealedToday"),
        "outcomeSource": d.get("outcomeSource"), "outcomeCross": d.get("outcomeCross"),
        "corpusState": d.get("corpusState"), "auctionPushState": d.get("auctionPushState"),
        "selectionSources": d.get("selectionSources"), "dragonRoles": d.get("dragonRoles"),
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
    """竞价龙头投喂读口（合同镜像 theme-leaders；行源 = labels ∪ 推送 roster ∪ jiuyan 龙 roster）。"""
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
    leader_docs = [d for d in docs if d.get("docKind") != "sector"]
    # 旧档竞价涨幅修复：join bid 通道 bidding_pct（评审 N1：仅旧档日期需要 join，
    # 新档直读落库值；避免新档窗口每次 60s 轮询白读整日档）
    bid_map = _bid_items_by_date(
        db, {str(d.get("tradingDate")) for d in leader_docs if "realtimePct" not in d})
    ev_cache: dict = {}
    rows = []
    for d in leader_docs:
        d_date = str(d.get("tradingDate")); d_code = str(d.get("code") or "")[-6:]
        # 旧档事件列证据三徽章读口重建（新档含 evidenceKwordTags 直读，零重建开销）
        ev_override = (None if "evidenceKwordTags" in d
                       else _legacy_evidence_fields(db, d_date, d.get("board"), ev_cache))
        rows.append(_row_of(d, sector_docs.get((d_date, str(d.get("board")))),
                            bool(with_narrative), bid_map.get((d_date, d_code)), ev_override))
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
    live_docs: list[dict] = []
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
                # 口径与 _row_of 对齐（评审 M1）：auctionPct=真竞价（缺档行无 bid 值
                # → None 不拿实时冒充），推送实时 pct 落 realtimePct；行不进表
                # （alRows 过滤），但读口合同统一，防后续消费方复现原 bug
                rows.append({"tradingDate": str(ld.get("_id")), "code": s.get("code"),
                             "name": s.get("name"), "board": s.get("board"),
                             "auctionPct": None, "realtimePct": s.get("pct"),
                             "labelMissing": True})
    except Exception as exc:  # noqa: BLE001 — 直播归档读失败不阻断 labels 清单（fail-visible 留痕）
        roster_error = f"{type(exc).__name__}: {exc}"
    # jiuyan 龙 roster 缺档行（vA2 A4e：同一 jiuyan_dragon_roster 实现按需计算；
    # 日期集 = live 归档日 ∪ labels 日，单 date 模式即该日；失败留痕不阻断）
    dragon_roster_error = None
    try:
        from backend.operations.auction_leader_label import (
            SOURCE_JIUYAN_DRAGON, jiuyan_dragon_roster)
        from backend.operations.theme_leader_label import trading_dates_before
        dates = ({date} if date else
                 {str(ld.get("_id")) for ld in live_docs}
                 | {str(r.get("tradingDate")) for r in rows})
        seen = {(r["tradingDate"], r["code"]) for r in rows}
        missing_by_key = {(r["tradingDate"], r["code"]): r for r in rows
                          if r.get("labelMissing")}
        for d0 in sorted(dates):
            if not d0:
                continue
            prevs = trading_dates_before(db, d0, 1)
            jrows, _jstate = jiuyan_dragon_roster(db, prevs[-1] if prevs else None)
            for jr in jrows:
                key = (d0, jr["code"])
                if key in seen:
                    # 双源缺档行合并 jiuyan 披露（review N3：推送 roster 行补源/龙序）
                    row0 = missing_by_key.get(key)
                    if row0 is not None:
                        row0["selectionSources"] = ["auction_push", SOURCE_JIUYAN_DRAGON]
                        row0["dragonRoles"] = jr.get("dragonRoles")
                    continue
                seen.add(key)
                missing += 1
                rows.append({"tradingDate": d0, "code": jr["code"],
                             "name": jr.get("name"), "board": jr.get("board"),
                             "auctionPct": None,
                             "selectionSources": [SOURCE_JIUYAN_DRAGON],
                             "dragonRoles": jr.get("dragonRoles"),
                             "labelMissing": True})
    except Exception as exc:  # noqa: BLE001 — jiuyan roster 计算失败不阻断 labels/推送 roster
        dragon_roster_error = f"{type(exc).__name__}: {exc}"
    rows.sort(key=lambda r: (str(r.get("tradingDate") or ""), str(r.get("board") or ""),
                             str(r.get("code") or "")), reverse=False)
    rows.sort(key=lambda r: str(r.get("tradingDate") or ""), reverse=True)
    nf: dict[str, Any] = {"labelMissingRows": missing}
    if roster_error:
        nf["rosterError"] = roster_error
    if dragon_roster_error:
        nf["dragonRosterError"] = dragon_roster_error
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
                "error": f"{date}:{code} 无存档（该 code 不在当日双源选龙名单）"}
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