# -*- coding: utf-8 -*-
"""jev 情绪判定问题集 v2 生产计算服务（2026-10-02 立项：双表并存的 v2 表）。

jev 情绪判定生产计算服务（2026-10-02 V1 退役后唯一情绪链）：温度=锚定近 20 交易日分位的市场热度计，
拥挤=离散归层（证据分级判据），档位=锚定分位判读。token 缺失降级落库不阻断采集链。2026-10-02 单一事实源裁决：gate 环境变量删除（V1 已灭，无双轨可回退）。

锚日历化（Q3 混季归因修复）：窗口按交易日历取严格早于当日的近 20 个交易日（每历日一条，
数据缺失日照实记 None），不再用"最近 20 个有数日"跨季凑数。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from backend.analysis.hotlist.jev_driver_ammo import percentile_fraction
from backend.analysis.hotlist.jev_state import (
    JEV_DAY_QUESTIONS,
    JEV_SLOT_QUESTIONS,
    QUESTION_SET_VERSION,
    build_day_jev_state,
    build_history_anchor,
    build_slot_jev_state,
    collect_slot_evidence,
    derive_true_ladder_from_pools,
    extract_history_anchor_range,
    narrative_is_truncated,
    summarize_day_evidence,
)
from backend.services.jev.jev_client import (DEFAULT_ACCOUNT_ID, call_jev, call_jev_typesafe,
                                             parse_jev_response)

_DEFAULT_ACCOUNT = DEFAULT_ACCOUNT_ID

# 日级语料口径代际戳（2026-10-22 日级语料修复）：题目集仍 v2.5，本戳只标记语料结构
# （收盘帧全量块/帧覆盖/真连板 as-of/旧 schema 归一）。存量文档由迁移脚本打 legacy/pre_fix。
EOD_CORPUS_CALIBER_VERSION = "eod-2026-10-22"

# 槽级语料口径代际戳（2026-10-24 B1 第二刀，jev-slot-corpus-slim-preregistration-20261024.md）：
# 已走帧压缩行 slim 化（删 TRIN/主力净额/生命周期/强资四组判据外语境证据，slim 仅作用于
# 槽级 priors 渲染；日级逐帧行与当前帧全量段不变）。对照新门 v2 PASS（剔掷硬币 32/32=100%、
# temperature |Δ|≤4.7，实测日链 input 42,013→38,740 = -7.8%）。旧文档无此戳=旧代语料。
SLOT_CORPUS_CALIBER_VERSION = "slot-2026-10-24"


def _dispatch_jev(state, questions: dict) -> tuple[dict, int]:
    """传输选择：JEV_TYPESAFE_KEY 存在 → 官方直连（可经代理）；否则 CF 网关。
    两条通道返回同形状 envelope，parse_jev_response 下游零改动。"""
    ts_key = os.environ.get("JEV_TYPESAFE_KEY", "").strip()
    if ts_key:
        proxy = os.environ.get("JEV_TYPESAFE_PROXY", "").strip() or None
        return call_jev_typesafe(ts_key, state=state, questions=questions, proxy=proxy)
    _enabled, token, account = _jev_config()
    return call_jev(account, token, state=state, questions=questions)


def _jev_config() -> tuple[bool, str, str]:
    """(enabled, token, account)。每次调用读取，兼容运行时改环境变量。"""
    enabled = os.environ.get("JEV_SENTIMENT_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
    token = os.environ.get("JEV_CF_TOKEN", "").strip()
    account = os.environ.get("JEV_CF_ACCOUNT", _DEFAULT_ACCOUNT).strip() or _DEFAULT_ACCOUNT
    return enabled, token, account


# ── 快照取数（直查快照库；帧→行→analysis join 与规则链同源）──


def _load_frame(db: Any, dataset_id: str, snapshot_type: str, trading_date: str, slot_time: str) -> dict | None:
    return db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time},
        sort=[("timestamp", -1), ("snapshotId", -1)],
    )


def _load_rows(db: Any, dataset_id: str, snapshot_id: str) -> list[dict]:
    return list(db["snapshot_stock_rows"].find({"datasetId": dataset_id, "snapshotId": snapshot_id}))


def _load_analysis_by_code(db: Any, dataset_id: str, snapshot_id: str) -> dict:
    rows = db["snapshot_analysis"].find(
        {"datasetId": dataset_id, "snapshotId": snapshot_id},
        {"_id": 0, "code": 1, "analysis": 1},
    )
    return {str(row.get("code")): row.get("analysis") for row in rows if row.get("code")}


def _half_hour_slots() -> list[str]:
    from backend.snapshot_collector.slots import SLOT_TIMES

    return [str(slot) for slot in SLOT_TIMES.get("half_hour") or []]


def _slots_of_date(db: Any, dataset_id: str, snapshot_type: str, trading_date: str) -> list[str]:
    slots = set()
    for f in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date},
            {"slotTime": 1}):
        slot = str(f.get("slotTime") or "")
        if len(slot) == 5 and slot[2] == ":":
            slots.add(slot)
    return sorted(slots)


def load_market_daily_amount_map(db: Any) -> dict[str, float]:
    """market_daily_amount 参考集合 → {tradingDate: 两市合计额}（TDX 综指口径，backfill 工具维护）。

    15:00 槽 evidenceRaw.totalAmount 的重算保护源（2026-10-06 根治：此前回填值被
    replace_one 全量重建冲掉，v2.5 九月重跑实测冲掉 20 文档）。集合缺失/为空 → 空映射，
    计算链行为回退为历史原样（amount=None，fail-visible 不伪造）。
    """
    rows = db["market_daily_amount"].find({}, {"_id": 1, "totalAmount": 1})
    return {str(row["_id"]): float(row["totalAmount"]) for row in rows
            if isinstance(row.get("totalAmount"), (int, float)) and not isinstance(row["totalAmount"], bool)}


def _collect_evidence(db: Any, dataset_id: str, snapshot_type: str, trading_date: str,
                      slot_time: str, yesterday_rows: list,
                      yesterday_amounts: dict[str, float] | None = None,
                      daily_total_amount_fallback: float | None = None,
                      allow_live_ladder: bool = False,
                      allow_historical_eod_ladder: bool = True) -> dict | None:
    frame = _load_frame(db, dataset_id, snapshot_type, trading_date, slot_time)
    if frame is None:
        return None
    snapshot_id = str(frame.get("snapshotId") or "")
    rows = _load_rows(db, dataset_id, snapshot_id)
    if not rows:
        return None
    allow_frame_ladder = _frame_ladder_allowed(frame, slot_time)
    evidence = collect_slot_evidence(
        frame=frame, rows=rows, yesterday_rows=yesterday_rows,
        analysis_by_code=_load_analysis_by_code(db, dataset_id, snapshot_id), slot_time=slot_time,
        yesterday_same_slot_total_amount=(yesterday_amounts or {}).get(slot_time),
        daily_total_amount_fallback=daily_total_amount_fallback,
        allow_frame_ladder=allow_frame_ladder,
        true_ladder=_resolve_slot_true_ladder(
            db, dataset_id, snapshot_type, trading_date, slot_time, frame,
            allow_live=allow_live_ladder,
            allow_historical_eod_ladder=allow_historical_eod_ladder,
            allow_frame_ladder=allow_frame_ladder))
    _note_slot_ladder_caliber(evidence)  # 日级逐帧链/priors 同享历史回放口径披露
    return evidence


def _evidence_skip_reason(db: Any, dataset_id: str, snapshot_type: str,
                          trading_date: str, slot: str) -> str:
    """帧存在但未产出 evidence 的结构化原因（日级覆盖度用，不静默丢槽）。"""
    frame = _load_frame(db, dataset_id, snapshot_type, trading_date, slot)
    if frame is None:
        return "frame_missing"
    snapshot_id = str(frame.get("snapshotId") or "").strip()
    if not snapshot_id:
        return "snapshot_missing"
    if not _load_rows(db, dataset_id, snapshot_id):
        return "rows_empty"
    return "unknown"


def _eod_reusable(doc: dict | None) -> bool:
    """已有 EOD 是否可复用（2026-10-22 裁决：15:00 帧到达后幂等重跑，daily 不再重复烧调用）。

    只有「同代 + 收盘帧完整 + ok」的文档可复用；缺收盘帧/降级/旧代一律重算，
    保证 15:00 迟到或重采后的 EOD 会被覆盖成 close-complete 版本。
    """
    if not isinstance(doc, dict):
        return False
    if doc.get("status") != "ok":
        return False
    if doc.get("questionSetVersion") != QUESTION_SET_VERSION:
        return False
    if doc.get("corpusCaliberVersion") != EOD_CORPUS_CALIBER_VERSION:
        return False
    coverage = doc.get("frameCoverage")
    return isinstance(coverage, dict) and coverage.get("hasCloseFrame") is True


def _eod_evidence_payload(evidences: list, *, slots: list, expected_slots: list,
                          skipped_frames: list) -> tuple[dict, dict]:
    """EOD 结构化证据（evidenceRaw）+ 摘要（叙事/落库共用同一事实源）。"""
    summary = summarize_day_evidence(
        evidences, expected_slots=expected_slots, present_slots=slots,
        skipped_frames=skipped_frames)
    close = evidences[-1] if summary["frameCoverage"]["hasCloseFrame"] else None
    payload = {
        "frameCoverage": summary["frameCoverage"],
        "frames": evidences,
        "close": close,
        "summary": {key: summary[key] for key in (
            "peakZt", "closeZt", "peakTrueBoard", "peakRangeBoard", "trueBoardFrames",
            "trueBoardCoverage", "closeZhabanRate", "closeFengbanRate", "closeAmount",
            "closeAmountSource")},
    }
    return payload, summary


# ── 真连板供给链（2026-10-22 语料口径修复，jev-slot-corpus-caliber-fix-preregistration.md §2.2）──
# 帧连板层由 collect_slot_evidence 内部消费（15:00/EOD 帧 as-of 派生，优先于外部供给）；
# 本层补外部源，as-of 保护是第一硬约束：当日已走帧只复用已存槽文档的落档值，绝不现查
# （THS 现查返回 now-state，重算历史槽会拿当前连板污染当时状态）。


def _sh_today() -> str:
    """上海时区当日（YYYY-MM-DD）——现查/回放的日期分流基准。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _sh_now_hm() -> str:
    """上海时区当前时刻 HH:MM（槽位现查 as-of 窗口判定基准）。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")


# 槽后容差：采集/后处理链在槽时刻后数分钟才跑到是常态；超出即视为「已走槽被回补/重跑」
_SLOT_LIVE_TOLERANCE_MIN = 10


def _slot_is_current(slot_time: str, *, tolerance_min: int = _SLOT_LIVE_TOLERANCE_MIN) -> bool:
    """槽位时刻是否仍在「当前时钟槽」窗口内（now <= slot + tolerance）。

    as-of 硬约束（2026-10-22 review P1）：只有真正当前槽才允许 THS 现查；已走槽被回补
    （collector 当槽宕机后重算、API /slots/rerun、全槽重算脚本）时现查返回 now-state，
    会把收盘连板态写进早槽 as-of 证据（假状态）。超窗 → 走 None 降级，不现查。
    """
    try:
        hh, mm = (int(part) for part in str(slot_time).split(":"))
        nhh, nmm = (int(part) for part in _sh_now_hm().split(":"))
    except (TypeError, ValueError):
        return False
    return (nhh * 60 + nmm) <= (hh * 60 + mm + tolerance_min)


def _frame_has_true_ladder(frame: dict | None) -> bool:
    """帧内连板层可派生真连板（15:00/EOD 帧）→ 外部供给可跳过（collect 自会派生）。"""
    ls = frame.get("limitSummary") if isinstance(frame, dict) and isinstance(frame.get("limitSummary"), dict) else {}
    ths_pools = ls.get("thsPools") if isinstance(ls.get("thsPools"), dict) else {}
    pools = ths_pools.get("pools") if isinstance(ths_pools.get("pools"), dict) else None
    return derive_true_ladder_from_pools(pools) is not None


def _frame_ladder_backfilled(frame: dict | None) -> bool:
    """帧连板层是否为事后回填（ths_hist_backfill / limit_summary_backfilled）。

    回填源是 THS 历史=EOD 态；只有 15:00 收盘槽才是该槽的 as-of 真值。
    """
    if not isinstance(frame, dict):
        return False
    ls = frame.get("limitSummary") if isinstance(frame.get("limitSummary"), dict) else {}
    flags = frame.get("qualityFlags") if isinstance(frame.get("qualityFlags"), list) else []
    return (str(ls.get("source") or "").strip() == "ths_hist_backfill"
            or bool(ls.get("backfilledAt"))
            or "limit_summary_backfilled" in flags)


def _frame_ladder_allowed(frame: dict | None, slot_time: str) -> bool:
    """非收盘槽不得采信事后回填帧池（review P2-1：帧池捷径绕过日级早盘守卫）。"""
    return str(slot_time) == "15:00" or not _frame_ladder_backfilled(frame)


def _stored_doc_ladder(db: Any, dataset_id: str, snapshot_type: str,
                       trading_date: str, slot_time: str) -> dict | None:
    """已存槽文档 evidenceRaw.limit 的真连板 as-of 复用（当日已走帧不现查的唯一来源）。

    trueBoards 落库形状 {yiban,erban,sanban,sibanPlus,high}（sibanPlus=four+high 合并），
    此处还原为 derive 形状（four=sibanPlus-high），maxTrueBoard 精确保留。
    文档畸形（外部写入字符串/列表等）→ None 降级，不让单文档坏值炸掉槽计算（review P3-3）。
    """
    # 不带 projection：部分测试 FakeCollection.find_one 的第二位置参数是 sort（真实
    # pymongo 支持投影位，但为兼容统一走全文档读取，单文档开销可忽略）
    doc = db["hotlist_jev_sentiment"].find_one(
        {"_id": f"{dataset_id}:{snapshot_type}:{trading_date}:{slot_time}"})
    limit = ((doc or {}).get("evidenceRaw") or {}).get("limit") or {}
    mtb = limit.get("maxTrueBoard")
    if not (isinstance(mtb, (int, float)) and not isinstance(mtb, bool)):
        return None
    tb = limit.get("trueBoards") if isinstance(limit.get("trueBoards"), dict) else {}
    try:
        high = int(tb.get("high") or 0)
        siban = int(tb.get("sibanPlus") or 0)
        # 保留落档来源（如 ths_date_eod）：day 聚合对非收盘槽必须能识破
        # 「存档里是 EOD 回放口径」而拒绝把它当 as-of 真值（2026-10-22 第二轮裁决）。
        return {"maxBoard": int(mtb),
                "source": str(limit.get("trueBoardSource") or "stored_doc"),
                "boards": {"one": int(tb.get("yiban") or 0), "two": int(tb.get("erban") or 0),
                           "three": int(tb.get("sanban") or 0), "four": max(siban - high, 0),
                           "high": high}}
    except (TypeError, ValueError):
        return None


def _run_blocking(coro):
    """同步上下文跑协程：无事件循环直接 asyncio.run；防御性兜底线程内起新循环。

    两个生产调用点均无运行中循环（collector 后处理链走 asyncio.to_thread、
    FastAPI 同步路由走线程池），兜底只为未来出现异步直调时不炸。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


# 真连板按日结果缓存（进程级，仅缓存成功值；TTL 300s）——同一日多槽/多帧重算只出网一次。
# 不能依赖 LimitUpService 单例缓存：该函数每次在独立事件循环执行，而单例 client 的连接池
# 绑定首次事件循环（实测跨循环复用 → RuntimeError: Event loop is closed，2026-10-22 review P1）。
_LADDER_FETCH_TTL_S = 300.0
_LADDER_FETCH_CACHE: dict[str, tuple[float, dict]] = {}


def _fetch_true_ladder(date8: str) -> dict | None:
    """THS 连板层五池按日拉取 → 真连板梯队（derive 口径，与帧池同源）。

    date8=YYYYMMDD：当日=as-of 现查（盘中叙事真连板供给）；历史日=EOD 态（回放口径，
    由调用方标 source=ths_date_eod 并在叙事披露）。任何失败 → None（fail-visible 不伪造，
    测试离线护栏 monkeypatch 本函数）。

    跨事件循环安全（2026-10-22 review P1）：**不共享进程单例 client**——本函数在生产两个
    进程（collector 后处理线程 / FastAPI 同步路由线程池）都在新建的 asyncio.run 循环里执行，
    单例 httpx.AsyncClient 的连接池绑定首次事件循环，跨循环复用会 RuntimeError: Event loop
    is closed。改为每次调用新建专用 client（一次调用内 5 池共享），用完即关；跨调用的
    重复请求由模块级 `_LADDER_FETCH_CACHE`（TTL 300s，只缓存成功值）吸收。
    服务层节流 250ms 仍生效（新建 service 的 min_request_gap 默认值）。
    """
    cached = _LADDER_FETCH_CACHE.get(date8)
    if cached and time.time() - cached[0] < _LADDER_FETCH_TTL_S:
        return dict(cached[1])

    async def _go():
        import httpx

        from backend.market_proxy.limitup import UA, LimitUpService

        client = httpx.AsyncClient(timeout=8.0, headers={"User-Agent": UA})
        try:
            svc = LimitUpService(client=client)
            body = await svc.get_ths_pools(date8, keys=("one", "two", "three", "four", "high"))
        finally:
            await client.aclose()
        pools = body.get("pools") if isinstance(body, dict) else None
        if isinstance(body, dict) and body.get("degraded"):
            # 部分池失败：derive 会整体返 None（宁缺毋猜），此处保留上游错误供排障
            logging.warning("true ladder pools degraded for %s: %s", date8, body.get("errors"))
        return derive_true_ladder_from_pools(pools)

    try:
        ladder = _run_blocking(_go())
    except Exception as exc:  # noqa: BLE001 — 上游失败降级披露，不阻断情绪链
        logging.warning("true ladder fetch failed for %s: %s", date8, exc)
        return None
    if isinstance(ladder, dict):
        _LADDER_FETCH_CACHE[date8] = (time.time(), dict(ladder))
    return ladder


_EOD_LADDER_NOTE = "真连板取该日收盘连板层（历史回放口径）"


def _note_slot_ladder_caliber(evidence: dict | None) -> str | None:
    """历史回放口径披露（fail-visible）：真连板来自该日 EOD 连板层时，证据质量段留痕。

    下沉到证据层（而非只在当前槽）——priors 与日级逐帧链同样经 ths_date_eod 供给，
    若不标注，模型会把盘中帧的收盘态连板当成 as-of 真值（review P2-1）。
    """
    source = ((evidence or {}).get("limit") or {}).get("trueBoardSource")
    if source != "ths_date_eod":
        return None
    quality = evidence.setdefault("quality", {}).setdefault("degradedSources", [])
    if _EOD_LADDER_NOTE not in quality:
        quality.append(_EOD_LADDER_NOTE)
    return _EOD_LADDER_NOTE


def _resolve_slot_true_ladder(db: Any, dataset_id: str, snapshot_type: str, trading_date: str,
                              slot_time: str, frame: dict | None, *,
                              allow_live: bool,
                              allow_historical_eod_ladder: bool = True,
                              allow_frame_ladder: bool = True) -> dict | None:
    """槽位真连板外部供给解析（帧池优先已由 collect 内部处理，本函数只补外部源）。

    优先级：① 已存槽文档 as-of 复用（当日已走帧唯一合法源——绝不现查，now-state 污染）；
    ② 当日**当前时钟槽**（allow_live 且槽后容差内）THS 现查 as-of——超出容差的当日
       已走槽重跑/回补一律 None 降级（现查 now-state 会冒充槽位 as-of，review P1）；
    ③ 历史日按日查（EOD 态，source=ths_date_eod，`_note_slot_ladder_caliber` 披露）；
       日级聚合对非收盘槽传 ``allow_historical_eod_ladder=False``：早盘行不得被收盘态
       抹平（2026-10-22 日级审计 P0-3）；单槽回放仍默认允许并披露。
    ④ None 降级（叙事「真连板该帧未采集」）。
    """
    if allow_frame_ladder and _frame_has_true_ladder(frame):
        return None  # 帧内连板层可用（15:00/EOD 帧）→ collect 自派生，零外部请求
    stored = _stored_doc_ladder(db, dataset_id, snapshot_type, trading_date, slot_time)
    if stored is not None:
        # 日级聚合对非收盘槽禁用 EOD 回放口径的存档值：否则早盘行仍被收盘态抹平
        # （即使存档是「早先单槽回放」写入的）。收盘槽 15:00 允许并披露。
        if (not allow_historical_eod_ladder
                and stored.get("source") == "ths_date_eod"):
            stored = None
        else:
            return stored
    today = _sh_today()
    date8 = trading_date.replace("-", "")
    if trading_date == today:
        if not (allow_live and _slot_is_current(slot_time)):
            return None  # 当日已走槽被回补/重跑：不现查（now-state 污染 as-of）
        ladder = _fetch_true_ladder(date8)
        if ladder is not None:
            ladder["source"] = "ths_live"
        return ladder
    if trading_date < today:
        if not allow_historical_eod_ladder:
            return None
        ladder = _fetch_true_ladder(date8)
        if ladder is not None:
            ladder["source"] = "ths_date_eod"
        return ladder
    return None


def _latest_yesterday_rows(db: Any, dataset_id: str, snapshot_type: str, trading_date: str) -> list:
    """上一交易日最新 half_hour 帧行（昨日承接/新进淘汰的对比基线）。"""
    latest_date = _latest_date_before(db, dataset_id, snapshot_type, trading_date)
    if latest_date is None:
        return []
    frame = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": latest_date},
        sort=[("timestamp", -1), ("snapshotId", -1)],
    )
    if not frame:
        return []
    return _load_rows(db, dataset_id, str(frame.get("snapshotId") or ""))


def _latest_date_before(db: Any, dataset_id: str, snapshot_type: str, trading_date: str) -> str | None:
    dates = sorted({
        str(f.get("tradingDate"))
        for f in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type}, {"tradingDate": 1})
        if f.get("tradingDate") and str(f.get("tradingDate")) < trading_date
    })
    return dates[-1] if dates else None


def _yesterday_slot_total_amount(db: Any, dataset_id: str, snapshot_type: str,
                                 trading_date: str, slot_time: str) -> float | None:
    return _yesterday_total_amounts_by_slot(db, dataset_id, snapshot_type, trading_date).get(slot_time)


def _yesterday_total_amounts_by_slot(db: Any, dataset_id: str, snapshot_type: str,
                                     trading_date: str) -> dict[str, float]:
    """上一交易日各槽位帧的两市总成交额（同期量能基线映射）；缺失槽位不在结果中。"""
    latest_date = _latest_date_before(db, dataset_id, snapshot_type, trading_date)
    if latest_date is None:
        return {}
    out: dict[str, float] = {}
    for f in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": latest_date}, {"indices": 1, "slotTime": 1}):
        slot = str(f.get("slotTime") or "")
        entry = (f.get("indices") or {}).get("totalAmount") if isinstance(f.get("indices"), dict) else None
        if len(slot) == 5 and slot[2] == ":" and isinstance(entry, dict):
            amount = entry.get("amount")
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                out[slot] = float(amount)
    return out

ANCHOR_WINDOW = 20


def temperature_percentile(db: Any, *, dataset_id: str, trading_date: str,
                           current: Any) -> tuple[float | None, int]:
    """当前温度在近 ANCHOR_WINDOW 个交易日 EOD 日级温度中的分位。

    口径（2026-10-14 用户裁决「近20日 EOD 日级温度」）：参照系=近 20 个交易日的
    EOD ``scores.day_temperature``，与 relay-index 的 dayTemperature join、页面
    「近20日参照」锚段同源。三条硬约束：

    - **窗口严格早于当日**（``tradingDate < trading_date``）：当日文档不参与，
      零未来函数——回填历史槽位时不会用到之后才产生的 EOD 结论；
    - **样本 <10 不产出**：返回 ``(None, n)``，调用方不写该字段（fail-visible：
      字段缺席由前端按「-」呈现，不补 0 不伪造分位）；
    - **参照值只取 EOD**：盘中槽位温度与收盘日级温度比是既定混合口径（用户裁决），
      此处只负责取数，不比同日同时刻槽温（那套样本不足 10 的比例更高）。

    Returns:
        ``(分位 0-1 小数或 None, 有效样本数)``——样本数随返回值透出，供回填脚本
        与排障判断「不可算」是窗口薄还是字段缺。
    """
    dates = sorted({
        str(r["tradingDate"]) for r in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": "half_hour",
             "tradingDate": {"$lt": trading_date, "$gt": "2020-01-01"}},
            {"tradingDate": 1}) if r.get("tradingDate")
    })[-ANCHOR_WINDOW:]
    if not dates:
        return None, 0
    refs: list[float] = []
    for date in dates:
        eod = db["hotlist_jev_sentiment"].find_one(
            {"datasetId": dataset_id, "snapshotType": "half_hour", "kind": "eod",
             "status": "ok", "tradingDate": date},
            {"scores.day_temperature": 1})
        temp = (eod or {}).get("scores", {}).get("day_temperature") if eod else None
        if isinstance(temp, (int, float)) and not isinstance(temp, bool):
            refs.append(float(temp))
    return percentile_fraction(refs, current), len(refs)


def _anchor_max_true_board_detail(db: Any, dataset_id: str, date: str,
                                  doc: dict | None) -> tuple[int | None, str]:
    """锚历日真连板最高板四级取数链（2026-10-22 口径修复 §2.3，同源=THS 连板层）：

    ① 15:00 v2 槽文档 evidenceRaw.limit.maxTrueBoard（本修复后生产自供）；
    ② 15:00 帧连板层五池派生（10-10 起 EOD 帧入采，as-of）；
    ③ market_true_ladder 参考集合（backfill_true_ladder 工具按日回填，同源采样）；
    ④ None（fail-visible，<8 样本时锚段如实标「历史样本不足」）。

    返回 (值, 来源)；来源进锚叙事，避免四源混成匿名分位（日级审计 P1-3）。
    """
    limit = ((doc or {}).get("evidenceRaw") or {}).get("limit") or {}
    mtb = limit.get("maxTrueBoard")
    if isinstance(mtb, (int, float)) and not isinstance(mtb, bool) and mtb > 0:
        return int(mtb), "slot_doc"
    frame = db["snapshot_frames"].find_one(
        {"datasetId": dataset_id, "type": "half_hour", "tradingDate": date, "slotTime": "15:00"})
    ls = (frame or {}).get("limitSummary") if isinstance((frame or {}).get("limitSummary"), dict) else {}
    ths_pools = ls.get("thsPools") if isinstance(ls.get("thsPools"), dict) else {}
    pools = ths_pools.get("pools") if isinstance(ths_pools.get("pools"), dict) else None
    ladder = derive_true_ladder_from_pools(pools)
    if ladder is not None and ladder["maxBoard"] > 0:
        return int(ladder["maxBoard"]), "frame_15"
    ref = db["market_true_ladder"].find_one({"_id": date})
    ref_mtb = (ref or {}).get("maxTrueBoard")
    if isinstance(ref_mtb, (int, float)) and not isinstance(ref_mtb, bool) and ref_mtb > 0:
        return int(ref_mtb), "market_true_ladder"
    return None, "none"


def _anchor_max_true_board(db: Any, dataset_id: str, date: str, doc: dict | None) -> int | None:
    """兼容入口：只返回值（测试/旧调用方）。来源见 _anchor_max_true_board_detail。"""
    return _anchor_max_true_board_detail(db, dataset_id, date, doc)[0]


def build_history_stats_calendar(db: Any, dataset_id: str, trading_date: str,
                                 window: int = ANCHOR_WINDOW) -> list[dict]:
    """近 window 个交易日（日历口径，严格 < 当日）收盘统计，每历日一条。

    数据源=v2 15:00 槽文档 evidenceRaw（2026-10-02 用户裁决 V1 退役后锚自供：
    v2 槽文档与 v1 同为 collect_slot_evidence 产物，字段同构）；当日文档缺失或
    指标缺失 → 该历日相应字段 None（fail-visible：锚段会标注有效样本数，不跨季凑数）。
    最高连板 2026-10-22 起改真连板口径（maxTrueBoard，四级取数链见 _anchor_max_true_board，
    独立于文档 limit 块——文档损坏不再连带抹掉真连板样本）；区间 maxBoard 不再进锚。
    """
    dates = sorted({
        str(r["tradingDate"]) for r in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": "half_hour",
             "tradingDate": {"$lt": trading_date, "$gt": "2020-01-01"}},
            {"tradingDate": 1}) if r.get("tradingDate")
    })[-window:]
    stats: list[dict] = []
    for date in dates:
        doc = db["hotlist_jev_sentiment"].find_one(
            {"datasetId": dataset_id, "snapshotType": "half_hour", "kind": "slot",
             "slotTime": "15:00", "tradingDate": date},
            {"evidenceRaw": 1})
        ev = (doc or {}).get("evidenceRaw") or {}
        limit = ev.get("limit") or {}
        amount = (ev.get("totalAmount") or {}).get("amount")
        zt = limit.get("ztCount")
        # 伪 0 防线（v2.3 教训）：limitSummary 损坏时代 ztCount 记 0 视为缺失而非零值；
        # ztCount 无效=同源 limit 块整体不可信，zhabanRate 联动置 None（真连板独立链不受连带）
        zt_ok = isinstance(zt, (int, float)) and not isinstance(zt, bool) and zt > 0
        zhaban = limit.get("zhabanRate")
        max_true_board, max_true_board_source = _anchor_max_true_board_detail(
            db, dataset_id, date, doc)
        stats.append({
            "date": date,
            "ztCount": zt if zt_ok else None,
            "maxTrueBoard": max_true_board,
            "maxTrueBoardSource": max_true_board_source,
            "amountYi": round(amount / 1e8, 1) if isinstance(amount, (int, float)) else None,
            "zhabanRate": round(zhaban, 1) if zt_ok and isinstance(zhaban, (int, float)) else None,
        })
    return stats


# ── C2 锚供给逃生率告警（jev-temp-crowding-confidence-deepening.md 提案C2，2026-10-02 重评版）──
# 单日槽位逃生率（crowding=insufficient_evidence 的 ok 槽占比）>25% 连续 2 日 → 排查锚供给
# （v2.2/v2.3 教训：逃生率飙升几乎总是锚数据源问题而非题目问题：status=ok 限定、伪 0、
# limitSummary 损坏三类历史事故）。告警只上报、不得阻断采集/写入/读取链路（数据链路硬门禁禁令）；
# 基线只以现行代（QUESTION_SET_VERSION）文档计，跨代口径不可比。
ANCHOR_ALERT_ESCAPE_RATE = 0.25


def evaluate_anchor_escape_alert(db: Any, *, dataset_id: str, trading_date: str) -> dict:
    """当日+上一交易日槽位逃生率与连续告警判定（纯读，不写库不阻断）。"""
    def _day_rate(date: str) -> float | None:
        n_ok = n_escape = 0
        for doc in db["hotlist_jev_sentiment"].find(
                {"kind": "slot", "status": "ok", "datasetId": dataset_id,
                 "snapshotType": "half_hour",
                 "tradingDate": date, "questionSetVersion": QUESTION_SET_VERSION},
                {"answers.crowding.choice": 1}):
            n_ok += 1
            if ((doc.get("answers") or {}).get("crowding") or {}).get("choice") == "insufficient_evidence":
                n_escape += 1
        return round(n_escape / n_ok, 3) if n_ok else None

    today_rate = _day_rate(trading_date)
    prev_docs = db["hotlist_jev_sentiment"].find(
        {"kind": "slot", "datasetId": dataset_id, "snapshotType": "half_hour",
         "tradingDate": {"$lt": trading_date}},
        {"tradingDate": 1})
    prev_date = max((d.get("tradingDate") for d in prev_docs if d.get("tradingDate")),
                    default=None)
    prev_rate = _day_rate(prev_date) if prev_date else None
    alert = (today_rate is not None and today_rate > ANCHOR_ALERT_ESCAPE_RATE
             and prev_rate is not None and prev_rate > ANCHOR_ALERT_ESCAPE_RATE)
    return {"alert": alert, "tradingDate": trading_date, "todayRate": today_rate,
            "prevDate": prev_date, "prevRate": prev_rate,
            "threshold": ANCHOR_ALERT_ESCAPE_RATE}


def compute_and_upsert_for_day(db: Any, *, dataset_id: str, trading_date: str,
                                  snapshot_type: str = "half_hour", origin: str = "collector",
                                  dry_run: bool = False,
                                  reuse_if_complete: bool = False) -> dict[str, Any]:
    """日级 EOD 计算+落库（hotlist_jev_sentiment）。异常向上抛，由链捕获为 warning。

    ``reuse_if_complete=True``（daily 触发用）：已有同代、ok、收盘帧完整的 EOD 直接复用，
    不再调 jev（15:00 half_hour 先到并已算 EOD 时，daily 15:30 只做幂等确认）。
    ``False``（15:00 触发 / 手工 evaluate / eod rerun）：强制重算，覆盖迟到/重采的收盘帧。
    """
    _, token, account = _jev_config()
    slots = _slots_of_date(db, dataset_id, snapshot_type, trading_date)
    expected_slots = [str(slot) for slot in _half_hour_slots()]
    doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:EOD"
    if reuse_if_complete and not dry_run:
        existing = db["hotlist_jev_sentiment"].find_one({"_id": doc_id})
        if _eod_reusable(existing):
            return {"written": False, "status": existing.get("status"), "reused": True,
                    "frameCoverage": existing.get("frameCoverage"),
                    "dayTemperature": (existing.get("scores") or {}).get("day_temperature")}
    base = {"_id": doc_id, "kind": "eod", "origin": origin, "datasetId": dataset_id,
            "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": "EOD",
            "asOf": f"{trading_date} EOD+08:00", "computedAt": int(time.time()),
            "questionsRaw": JEV_DAY_QUESTIONS, "anchoredSlotTime": slots[-1] if slots else None,
            "questionSetVersion": QUESTION_SET_VERSION,
            "corpusCaliberVersion": EOD_CORPUS_CALIBER_VERSION,
            "errorCode": None, "errorDetail": None}
    if not slots:
        empty_payload, _ = _eod_evidence_payload(
            [], slots=[], expected_slots=expected_slots, skipped_frames=[])
        if not dry_run:
            db["hotlist_jev_sentiment"].replace_one(
                {"_id": doc_id}, {**base, "status": "no_data", "errorDetail": "no half_hour frames",
                                  "answers": None, "scores": None, "usage": None, "model": None,
                                  "evidenceRaw": empty_payload,
                                  "frameCoverage": empty_payload["frameCoverage"],
                                  "narrativeRaw": None, "responseRaw": None,
                                  "latencyMs": None}, upsert=True)
        return {"written": True, "status": "no_data",
                "reason": "no_half_hour_frames", "errorDetail": "no half_hour frames",
                "frameCoverage": empty_payload["frameCoverage"]}

    yesterday_rows = _latest_yesterday_rows(db, dataset_id, snapshot_type, trading_date)
    yesterday_amounts = _yesterday_total_amounts_by_slot(db, dataset_id, snapshot_type, trading_date)
    market_amounts = load_market_daily_amount_map(db)
    evidences = []
    skipped_frames = []
    for slot in slots:
        evidence = _collect_evidence(
            db, dataset_id, snapshot_type, trading_date, slot,
            yesterday_rows, yesterday_amounts,
            daily_total_amount_fallback=market_amounts.get(trading_date),
            # 日级聚合：历史日仅收盘槽允许按日查 EOD 真连板；早盘行不回填收盘态（as-of）
            allow_historical_eod_ladder=(slot == "15:00"))
        if evidence is not None:
            evidences.append(evidence)
        else:
            skipped_frames.append({"slot": slot, "reason": _evidence_skip_reason(
                db, dataset_id, snapshot_type, trading_date, slot)})
    payload, _summary = _eod_evidence_payload(
        evidences, slots=slots, expected_slots=expected_slots, skipped_frames=skipped_frames)
    if not evidences:
        if not dry_run:
            db["hotlist_jev_sentiment"].replace_one(
                {"_id": doc_id}, {**base, "status": "no_data", "errorDetail": "frames present but no rows",
                                  "answers": None, "scores": None, "usage": None, "model": None,
                                  "evidenceRaw": payload, "frameCoverage": payload["frameCoverage"],
                                  "narrativeRaw": None, "responseRaw": None,
                                  "latencyMs": None}, upsert=True)
        return {"written": True, "status": "no_data",
                "reason": "frames_present_but_no_rows",
                "errorDetail": "frames present but no rows",
                "frameCoverage": payload["frameCoverage"]}

    previous_date = _latest_date_before(db, dataset_id, snapshot_type, trading_date)
    yesterday_close_total_amount = yesterday_amounts.get("15:00")
    if yesterday_close_total_amount is None and previous_date:
        # 昨日 15:00 帧缺额时用 market_daily_amount 同源回退（日级审计 P1-2）
        yesterday_close_total_amount = market_amounts.get(previous_date)
    anchor = build_history_anchor(build_history_stats_calendar(db, dataset_id, trading_date))
    narrative = build_day_jev_state(
        trading_date=trading_date, evidences=evidences,
        yesterday_close_total_amount=yesterday_close_total_amount,
        history_anchor=anchor, expected_slots=expected_slots, present_slots=slots,
        skipped_frames=skipped_frames)
    if dry_run:
        return {"status": "dry", "narrative": narrative, "evidenceRaw": payload,
                "frameCoverage": payload["frameCoverage"]}

    if not token and not os.environ.get("JEV_TYPESAFE_KEY", "").strip():
        # review M8：无 token 重跑的降级 replace 不得抹掉既往 ok 链路写入的锚告警字段
        prior = db["hotlist_jev_sentiment"].find_one(
            {"_id": doc_id}, {"anchorEscapeRate": 1, "anchorEscapeAlert": 1}) or {}
        carry = {k: prior[k] for k in ("anchorEscapeRate", "anchorEscapeAlert")
                 if prior.get(k) is not None}
        db["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id}, {**base, "status": "degraded", "errorCode": "missing_token",
                              "errorDetail": "JEV_CF_TOKEN / JEV_TYPESAFE_KEY not configured",
                              "evidenceRaw": payload, "frameCoverage": payload["frameCoverage"],
                              "narrativeRaw": narrative,
                              "narrativeTruncated": narrative_is_truncated(narrative),
                              "answers": None, "scores": None, "usage": None, "model": None,
                              "responseRaw": None, "latencyMs": None, **carry}, upsert=True)
        return {"written": True, "status": "degraded", "errorCode": "missing_token"}

    envelope, latency_ms = _dispatch_jev(narrative, JEV_DAY_QUESTIONS)
    # 缺题=partial_answers（degraded）：缺哪题结构化留档，幂等重跑可补（2026-10-05 批次A C2）
    parsed = parse_jev_response(envelope, latency_ms, expected_keys=set(JEV_DAY_QUESTIONS))
    # C2 锚供给告警（只上报不阻断）：评估自身异常也不得影响 EOD 主链路
    try:
        escape_alert = evaluate_anchor_escape_alert(db, dataset_id=dataset_id,
                                                    trading_date=trading_date)
    except Exception as exc:  # noqa: BLE001 — 告警机制故障不得阻断链路
        logging.warning("anchor escape alert eval failed for %s: %s", trading_date, exc)
        escape_alert = None
    else:
        if escape_alert.get("alert"):
            logging.warning(
                "anchor escape alert %s: today=%.2f prev(%s)=%.2f threshold=%.2f —— 排查锚供给",
                trading_date, escape_alert["todayRate"], escape_alert["prevDate"],
                escape_alert["prevRate"], escape_alert["threshold"])
    doc = {**base, "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": payload, "frameCoverage": payload["frameCoverage"],
           "narrativeRaw": narrative,
           "narrativeTruncated": narrative_is_truncated(narrative),
           "responseRaw": envelope, "answers": parsed.get("answers"), "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "historyAnchorRange": extract_history_anchor_range(anchor),
           "anchorEscapeRate": escape_alert.get("todayRate") if escape_alert else None,
           "anchorEscapeAlert": escape_alert if escape_alert and escape_alert.get("alert") else None}
    db["hotlist_jev_sentiment"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    return {"written": True, "status": doc["status"],
            "dayTemperature": (parsed.get("scores") or {}).get("day_temperature")}


def compute_and_upsert_for_slot(db: Any, *, dataset_id: str, trading_date: str, slot_time: str,
                                   snapshot_type: str = "half_hour", origin: str = "collector",
                                   dry_run: bool = False) -> dict[str, Any]:
    """v2 槽级计算+落库（hotlist_jev_sentiment_v2，2026-10-02 V1 退役后生产槽位唯一评判）。

    与 pilot（operations/jev_sentiment_pilot.compute_slot）同构：锚=日历口径近 20
    交易日（生产坐标系）。异常向上抛，由链捕获为 warning。
    """
    _, token, account = _jev_config()
    frame = _load_frame(db, dataset_id, snapshot_type, trading_date, slot_time)
    rows = _load_rows(db, dataset_id, str(frame.get("snapshotId") or "")) if frame else []
    doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:{slot_time}"
    if frame is None or not rows:
        if not dry_run:
            db["hotlist_jev_sentiment"].replace_one(
                {"_id": doc_id},
                {"_id": doc_id, "kind": "slot", "origin": origin, "datasetId": dataset_id,
                 "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time,
                 "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
                 "questionSetVersion": QUESTION_SET_VERSION,
                 "corpusCaliberVersion": SLOT_CORPUS_CALIBER_VERSION,
                 "status": "no_data", "errorCode": None,
                 "errorDetail": f"frame={'present' if frame else 'missing'} rows={len(rows)}",
                 "questionsRaw": None, "evidenceRaw": None, "narrativeRaw": None,
                 "responseRaw": None, "answers": None, "scores": None, "usage": None,
                 "model": None, "latencyMs": None, "historyAnchorRange": None},
                upsert=True)
        return {"written": True, "status": "no_data"}

    yesterday_rows = _latest_yesterday_rows(db, dataset_id, snapshot_type, trading_date)
    yesterday_amounts = _yesterday_total_amounts_by_slot(db, dataset_id, snapshot_type, trading_date)
    market_amounts = load_market_daily_amount_map(db)
    present_slots = _slots_of_date(db, dataset_id, snapshot_type, trading_date)
    prior_slots = [slot for slot in present_slots if slot < slot_time]
    missing_slots = [slot for slot in _half_hour_slots() if slot < slot_time and slot not in prior_slots]
    priors = []
    for slot in prior_slots:
        evidence = _collect_evidence(db, dataset_id, snapshot_type, trading_date, slot,
                                     yesterday_rows, yesterday_amounts,
                                     daily_total_amount_fallback=market_amounts.get(trading_date))
        if evidence is not None:
            priors.append(evidence)
    allow_frame_ladder = _frame_ladder_allowed(frame, slot_time)
    current_evidence = collect_slot_evidence(
        frame=frame, rows=rows, yesterday_rows=yesterday_rows,
        analysis_by_code=_load_analysis_by_code(db, dataset_id, str(frame.get("snapshotId") or "")),
        slot_time=slot_time,
        yesterday_same_slot_total_amount=yesterday_amounts.get(slot_time),
        daily_total_amount_fallback=market_amounts.get(trading_date),
        allow_frame_ladder=allow_frame_ladder,
        true_ladder=_resolve_slot_true_ladder(
            db, dataset_id, snapshot_type, trading_date, slot_time, frame, allow_live=True,
            allow_frame_ladder=allow_frame_ladder))
    # 历史回放口径披露（fail-visible）：当前槽自身取 EOD 连板层时留痕；priors 若取 EOD
    # 而当前槽取自帧池（历史日 15:00 槽重算的混合形态），也要把披露汇入叙事质量段
    current_note = _note_slot_ladder_caliber(current_evidence)
    if current_note is None and any(
            ((ev.get("limit") or {}).get("trueBoardSource") == "ths_date_eod") for ev in priors):
        current_evidence["quality"]["degradedSources"].append(_EOD_LADDER_NOTE)
    anchor = build_history_anchor(build_history_stats_calendar(db, dataset_id, trading_date))
    narrative = build_slot_jev_state(
        trading_date=trading_date, slot_time=slot_time,
        current=current_evidence or {}, priors=priors, missing_slots=missing_slots,
        history_anchor=anchor)
    if dry_run:
        return {"status": "dry", "narrative": narrative, "evidence": current_evidence}

    if not token and not os.environ.get("JEV_TYPESAFE_KEY", "").strip():
        db["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id},
            {"_id": doc_id, "kind": "slot", "origin": origin, "datasetId": dataset_id,
             "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time,
                 "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
                 "questionSetVersion": QUESTION_SET_VERSION,
                 "corpusCaliberVersion": SLOT_CORPUS_CALIBER_VERSION,
                 "status": "degraded", "errorCode": "missing_token",
             "errorDetail": "JEV_CF_TOKEN / JEV_TYPESAFE_KEY not configured",
                 "questionsRaw": JEV_SLOT_QUESTIONS, "evidenceRaw": current_evidence,
                 "narrativeRaw": narrative,
                 "narrativeTruncated": narrative_is_truncated(narrative),
                 "responseRaw": None, "answers": None, "scores": None,
             "usage": None, "model": None, "latencyMs": None, "historyAnchorRange": None},
            upsert=True)
        return {"written": True, "status": "degraded", "errorCode": "missing_token"}

    envelope, latency_ms = _dispatch_jev(narrative, JEV_SLOT_QUESTIONS)
    # 缺题=partial_answers（degraded）：缺哪题结构化留档，幂等重跑可补（2026-10-05 批次A C2）
    parsed = parse_jev_response(envelope, latency_ms, expected_keys=set(JEV_SLOT_QUESTIONS))
    # 温度分位（2026-10-14）：answers.temperature.percentile=当前温度在近20日 EOD 日级
    # 温度中的分位（口径见 temperature_percentile）。该值派生自库内历史而非模型返回，
    # 故浅拷贝 answers 顶层与 temperature 子 dict 后再注入——responseRaw 持有的是同一
    # envelope 对象，原地改写会把模型没返回过的字段混进「信封元信息」（原始返回保真）。
    # 样本不足/温度缺失时 percentile=None，字段整体缺席（fail-visible，不补 0）。
    stored_answers = parsed.get("answers")
    percentile, _samples = temperature_percentile(
        db, dataset_id=dataset_id, trading_date=trading_date,
        current=(parsed.get("scores") or {}).get("temperature"))
    if (percentile is not None and isinstance(stored_answers, dict)
            and isinstance(stored_answers.get("temperature"), dict)):
        stored_answers = {**stored_answers,
                          "temperature": {**stored_answers["temperature"],
                                          "percentile": percentile}}
    doc = {"_id": doc_id, "kind": "slot", "origin": origin, "datasetId": dataset_id,
           "snapshotType": snapshot_type, "tradingDate": trading_date, "slotTime": slot_time,
           "asOf": f"{trading_date} {slot_time}+08:00", "computedAt": int(time.time()),
           "questionSetVersion": QUESTION_SET_VERSION,
           "corpusCaliberVersion": SLOT_CORPUS_CALIBER_VERSION,
           "status": "ok" if parsed["ok"] else "degraded",
           "evidenceRaw": current_evidence, "narrativeRaw": narrative,
           "narrativeTruncated": narrative_is_truncated(narrative),
           "questionsRaw": JEV_SLOT_QUESTIONS, "responseRaw": envelope,
           "answers": stored_answers, "scores": parsed.get("scores"),
           "usage": parsed.get("usage"), "latencyMs": parsed.get("latencyMs"),
           "model": parsed.get("model"), "errorCode": parsed.get("errorCode"),
           "errorDetail": parsed.get("errorDetail"),
           "historyAnchorRange": extract_history_anchor_range(anchor)}
    db["hotlist_jev_sentiment"].replace_one({"_id": doc["_id"]}, doc, upsert=True)
    # errorCode 必须随返回透出（2026-10-09 实障）：采集 warning 与 /evaluate 补评响应
    # 都消费本返回，漏带时只显示 `hotlist_jev_degraded: None`，排障被迫查库
    return {"written": True, "status": doc["status"], "errorCode": parsed.get("errorCode")}
