# -*- coding: utf-8 -*-
"""竞价龙头投喂读口 + 单只重跑（vA2，预登记 auction-leader-vA2-preregistration-20261114）。

合同镜像 /theme-leaders（date | start/end | with_narrative；500 档上限+truncated；
sector doc 合入个股行；缺档行 labelMissing 披露——行源 = labels ∪ auctionPush roster
∪ 竞价强度 trial roster（同一 trial_strength_roster 实现，禁第二套；vA4 已退役
jiuyan 龙序源），打标停跑不阻断清单，fail-visible）。
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
            db, board_name=str(board or ""), date=str(date), leader_code=None,
            include_morning=True, include_flash=True)
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
        "selectionSources": d.get("selectionSources"),
        "trialStrength": d.get("trialStrength"),
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
    """竞价龙头投喂读口（合同镜像 theme-leaders；行源 = labels ∪ 推送 roster ∪ jiuyan 龙 roster ∪ 竞价强度 trial roster）。"""
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
    # 缺档行日期集 = live 归档日 ∪ labels 日（单 date 模式即该日）；第三源 trial 按需补行
    # （vA4：jiuyan 龙序源已退役 2026-11-15，不再补 jiuyan 缺档行）
    dates = ({date} if date else
             {str(ld.get("_id")) for ld in live_docs}
             | {str(r.get("tradingDate")) for r in rows})
    seen = {(r["tradingDate"], r["code"]) for r in rows}
    missing_by_key = {(r["tradingDate"], r["code"]): r for r in rows
                      if r.get("labelMissing")}
    # 竞价强度 roster 缺档行（第三源 2026-11-15 预登记：同一 trial_strength_roster
    # 实现按需计算；trial_rows 从 auction_trial_raw 日档加载，禁第二套；失败留痕不阻断）
    trial_roster_error = None
    try:
        from backend.analysis.hotlist.auction_strength import trial_strength_roster
        from backend.operations.auction_leader_label import (
            SOURCE_TRIAL_STRENGTH, TRIAL_STRENGTH_MAX_PER_DAY)
        from backend.operations.auction_trial_fetch import COLLECTION_TRIAL_RAW
        for d0 in sorted(dates):
            if not d0:
                continue
            raw = db[COLLECTION_TRIAL_RAW].find_one({"_id": d0}, {"rows": 1}) or {}
            trows, _tstate = trial_strength_roster(
                db, d0, raw.get("rows") or {}, max_total=TRIAL_STRENGTH_MAX_PER_DAY)
            for tr in trows:
                key = (d0, tr["code"])
                if key in seen:
                    # 双源缺档行合并披露（N3 同款：追加源标签 + 强度载荷）
                    row0 = missing_by_key.get(key)
                    if row0 is not None:
                        srcs = row0.get("selectionSources") or ["auction_push"]
                        if SOURCE_TRIAL_STRENGTH not in srcs:
                            row0["selectionSources"] = srcs + [SOURCE_TRIAL_STRENGTH]
                        row0["trialStrength"] = tr["trialStrength"]
                    continue
                seen.add(key)
                missing += 1
                rows.append({"tradingDate": d0, "code": tr["code"],
                             "name": tr.get("name"), "board": tr.get("board"),
                             "auctionPct": None,
                             "selectionSources": [SOURCE_TRIAL_STRENGTH],
                             "trialStrength": tr["trialStrength"],
                             "labelMissing": True})
    except Exception as exc:  # noqa: BLE001 — trial roster 计算失败不阻断 labels/推送 roster
        trial_roster_error = f"{type(exc).__name__}: {exc}"
    rows.sort(key=lambda r: (str(r.get("tradingDate") or ""), str(r.get("board") or ""),
                             str(r.get("code") or "")), reverse=False)
    rows.sort(key=lambda r: str(r.get("tradingDate") or ""), reverse=True)
    nf: dict[str, Any] = {"labelMissingRows": missing}
    if roster_error:
        nf["rosterError"] = roster_error
    if trial_roster_error:
        nf["trialRosterError"] = trial_roster_error
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
                "error": f"{date}:{code} 无存档（该 code 不在当日选龙名单：推送/韭研/竞价强度）"}
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


# ══════════ 竞价试盘日档读口（2026-11-14，勘察 auction-trial-source-survey-20261114 §6）══════════
# 数据源=本地 MongoDB auction_trial_raw（_id=日期，打标链 auction_trial_fetch 落库，
# 60 交易日回填+盘中打标槽位采集），本读口**纯读零上游外呼**（红线 9：WzsLinker 频控
# 预算只归打标链采集路径，页面刷新不触发任何外呼）。
# rows 键=6 位代码（KPL param.code），无名称列——名称 join stock_names 全 A 字典、
# board join 韭研产业树一级节点（jiuyan_board 单一事实源，未收录置 None 前端「未分板块」），
# miss 不伪装：None 透出，前端标注。跨日回退只向更早
# 有档日回退并 dateFallback 透出（不冒充当日，天普 11-12 池漏档同级教训）。
TRIAL_RAW_COLLECTION = "auction_trial_raw"


def _root_event_buckets() -> list[str]:
    """事件桶名单（前端当日打标分组过滤用，VOTE_EXCLUDE 单源透出）。"""
    try:
        from backend.services.jev.jiuyan_industry_root import VOTE_EXCLUDE
        return sorted(VOTE_EXCLUDE)
    except Exception:
        return ["公告", "其他", "新股", "次新", "ST", "B股", "转债", "其他相关",
                "ST板块", "北交所", "摘帽", "摘帽相关", "ST相关"]


# ══════════ jiuyan↔KPL 板块名称桥（2026-11-15 下沉 services/jev/jiuyan_board 单源：
# 本读口 / 竞价强度第三源 / 评估脚本共用；签名/行为不变，消除 analysis→api 耦合）══════════
from backend.services.jev.jiuyan_board import (  # noqa: E402
    _bridge_hist, _bridge_lookup, _bridge_maps, _norm_bk)


@router.get("/auction-trial")
def get_auction_trial(date: str | None = None) -> dict[str, Any]:
    """竞价试盘日档读口（纯读）：无 date → 最新有档日 + 全部日期索引。"""
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}"}
    try:
        col = db[TRIAL_RAW_COLLECTION]
        dates = sorted(str(d["_id"]) for d in col.find({}, {"_id": 1}))
        if not dates:
            return {"ok": True, "dates": [], "doc": None, "degraded": True,
                    "reason": "auction_trial_raw 无日档（打标链未采集或集合为空）"}
        target = (date or "").strip() or dates[-1]
        date_fallback = None
        doc = col.find_one({"_id": target})
        if doc is None and date:
            earlier = [d for d in dates if d < target]
            if earlier:
                served = earlier[-1]
                doc = col.find_one({"_id": served})
                if doc is not None:
                    date_fallback = {"requested": target, "served": served}
        if doc is None:
            return {"ok": True, "dates": dates, "doc": None, "degraded": True,
                    "reason": f"{target} 无试盘日档（未采集或非交易日）"}
        # 板块归属 join（2026-11-14 用户裁决：未入涨停打标分组的试盘股并入韭研板块分组，
        # 不单独成组）：① board = 韭研产业树一级节点名（jiuyan_board 单一事实源，与
        # 上涨/下跌复盘同源）；② 产业树未收录 → **板块名称桥**（2026-11-14 用户指路：
        # jiuyan↔KPL 桥未接是未分组主因之一）：bk_name 归一 → theme_industry_mapping
        # （P4 治理桥）→ sector_industry_mapping（板块节点 V3 桥）→ industry_alias.
        # suggest_for 同引擎实时建议（exact/contains/multi-union，确定性不猜）；
        # ③ 仍无 → 近 60 日打标链涨停分组最近归属兑底（打标链个股身位，事件桶
        # 公告/其他等停用词不入）。④全 miss → board 缺失透出（前端「未分板块」，
        # 不回推 KPL bk_name 原名，2026-11-06 用户裁决）。当日涨停打标分组归属由
        # 前端 jiuyan-action 读口叠加（多组各计一次，本口不重复建设）。
        bridge = _bridge_maps(db)
        # 粗桶对照（2026-11-14 用户裁决实施）：产业树一级节点太细（单日机器人拆 4-5
        # 节点）而打标链分组名粗——board/boardBridge 归一到打标链粗桶口径（
        # jiuyan_industry_root_mapping 对照层，非物理加层：上游周频全量刷新会冲掉
        # 物理结构）；unmapped 节点保留 level-1 原值兑底（不猜）；boardHist/当日打标
        # 分组本身已是粗桶名，不动。board 保留 level-1 原值作审计字段。
        try:
            from backend.services.jev import jiuyan_industry_root
            root_idx = jiuyan_industry_root.root_index(db)
            root_alias = jiuyan_industry_root.root_alias_map(db)
        except Exception:
            root_idx, root_alias = {}, {}
        rows = doc.get("rows") or {}
        try:
            from backend.services.jev import jiuyan_board
            b_idx, b_meta = jiuyan_board.board_index(db)
        except Exception:
            b_idx, b_meta = {}, {"nodes": 0, "codes": 0, "reason": "jiuyan_board_import_failed"}
        named_rows: dict[str, dict] = {}
        n_name_miss = 0
        n_board_miss = 0
        for code, row in rows.items():
            r = dict(row or {})
            c6 = str(code)[-6:]
            r["name"] = bridge["names"].get(c6)
            if not r["name"]:
                n_name_miss += 1
            r["board"] = b_idx.get(c6)   # 已在 jiuyan_board.board_index 内单点归一到粗桶主名
            if not r["board"] and bridge["maps"]:
                bb: list[str] = []
                for n in _bridge_lookup(r.get("bk_name"), bridge["maps"], bridge["inds"]):
                    rn = root_idx.get(n) or n   # 桥名归一到粗桶，unmapped 保留原值
                    if rn and rn not in bb:
                        bb.append(rn)
                r["boardBridge"] = bb
            named_rows[str(code)] = r
        # ③ 近 60 日打标链兑底：仅限仍无任何韭研板块归属的股（need 非空且 hist 原料
        #    非空才扫，最近身位优先；hist 已在 _bridge_maps 内缓存——hist 兜底独立于
        #    names/映射层故障，只看自身原料，review minor-1）
        need = {c for c, r in named_rows.items()
                if not r.get("board") and not r.get("boardBridge")}
        if need and bridge["hist"]:
            hist = _bridge_hist(bridge["hist"], need)
            for c in need:
                if hist.get(c):
                    seen: list[str] = []
                    for n in hist[c]:
                        rn = root_alias.get(n, n)   # 同义归一到主名（粗桶口径统一）
                        if rn and rn not in seen:
                            seen.append(rn)
                    if seen:
                        named_rows[c]["boardHist"] = seen
        unmapped_bk: set[str] = set()
        try:   # 事件桶词表单源（review minor-4）：与 _bridge_hist/_root_event_buckets 同用 VOTE_EXCLUDE
            from backend.services.jev.jiuyan_industry_root import VOTE_EXCLUDE as _EXCL
        except Exception:
            _EXCL = {"公告", "其他", "新股", "次新", "ST", "B股", "转债", "其他相关"}
        for r in named_rows.values():
            if not r.get("board") and not r.get("boardBridge") and not r.get("boardHist"):
                n_board_miss += 1
                bk = _norm_bk(r.get("bk_name"))
                if bk and bk not in _EXCL:
                    unmapped_bk.add(bk)   # 事件桶词不是桥候选（治理口径），不入未收录清单
        doc = {k: v for k, v in doc.items() if k != "_id"}
        doc["rows"] = named_rows
        result: dict[str, Any] = {"ok": True, "dates": dates, "doc": doc,
                                  "nameMissCount": n_name_miss,
                                  "boardMissCount": n_board_miss,
                                  "bridgeUnmapped": sorted(unmapped_bk),
                                  **({"bridgeDegraded": sorted(bridge["sourceErrors"].keys())}
                                     if bridge.get("sourceErrors") else {}),
                                  "boardMeta": b_meta,
                                  "rootMeta": {"mappedNodes": len(root_idx),
                                               "collection": "jiuyan_industry_root_mapping",
                                               "aliasMap": root_alias,
                                               "eventBuckets": _root_event_buckets()}}
        if date_fallback:
            result["dateFallback"] = date_fallback
        return result
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"auction_trial_read_failed: {exc}"}


# ══════════ 竞价过程事实序列读口（2026-11-16，用户裁决「页面实时看竞价过程」）══════════
# 数据源 = kpl_bidding_series 日档（collector 单写者推送即落库，窗 09:10-09:35，
# tick ≥5s 节流）；纯库读零外呼。派生逐股过程事实（first/max/last 观测值），
# 不冒充 WzsLinker 试盘字段语义（fail-visible：first=观测首帧，max=观测峰值）。

_BIDDING_SERIES_COLLECTION = "kpl_bidding_series"


def _derive_stock_series_facts(ticks: list[dict]) -> dict[str, dict]:
    """tick 序列 → 逐股过程事实（观测值）：first（首帧）/ max（委买额峰值帧）/
    last（末帧）。缺字段如实缺失（不补 0）。"""
    out: dict[str, dict] = {}
    for tick in ticks or []:
        ts = tick.get("ts")
        for it in tick.get("it") or []:
            sid = str(it.get("s") or "")
            if not sid:
                continue
            rec = out.setdefault(sid, {"first": None, "max": None, "last": None})
            row = {"ts": ts, **{f: it.get(f) for f in
                                ("bidding_pct", "bidding_amount", "bidding_net",
                                 "bidding_turnover", "zt_buy_amount", "price", "pct")}}
            if rec["first"] is None:
                rec["first"] = row
            rec["last"] = row
            zb = it.get("zt_buy_amount")
            try:
                zb_v = float(zb) if zb is not None else None
            except (TypeError, ValueError):
                zb_v = None
            if zb_v is not None:
                mx = rec["max"]
                if mx is None or (mx.get("zt_buy_amount") is not None
                                  and zb_v > float(mx.get("zt_buy_amount") or 0)):
                    rec["max"] = row
    return out


@router.get("/auction-bidding-series")
def get_auction_bidding_series(date: str | None = None) -> dict[str, Any]:
    """竞价过程事实序列读口：日档 ticks + 逐股 first/max/last 派生（纯库读零外呼）。"""
    from datetime import datetime as _dt
    date = date or _dt.now().strftime("%Y-%m-%d")
    try:
        db = repository_factory.get_runtime_mongodb_database()
        doc = db[_BIDDING_SERIES_COLLECTION].find_one({"_id": date})
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"bidding_series_read_failed: {exc}"}
    if not doc:
        return {"ok": True, "date": date, "absent": True,
                "reason": "no_series_today（采集窗未运行或 collector 未升级到序列落库）",
                "ticks": [], "stockFacts": {}}
    ticks = doc.get("ticks") or []
    return {"ok": True, "date": date, "absent": False,
            "tickN": len(ticks), "lastTs": doc.get("last_ts"),
            "fields": doc.get("fields") or [],
            "window": doc.get("window") or [],
            "ticks": ticks,
            "stockFacts": _derive_stock_series_facts(ticks)}
