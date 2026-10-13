"""热榜情绪 series 读口编排：lazy compute 最新交易日 + 缺失日 fail-visible 标注。

职责（backend 分层：有 I/O 编排 → services/）：
- 取最近 N 个交易日（snapshot_frames）
- 逐日读 hotlist_sentiment 库行；最新交易日缺行时经 HotListSentimentBackfillService
  触发纯函数计算并 upsert（幂等）
- displayStatus join（snapshot_analysis → rows.displayStatusLabel）
- frame.limitSummary → market_data 映射（ztCount/maxContinuousDays 无直接字段时推导）

无任何可用数据时返回 degraded 结构，不做质量阻断。
"""
from __future__ import annotations

import math
import time
from typing import Any

from backend.operations.hotlist_sentiment import (
    HotListSentimentBackfillService,
    build_hotlist_sentiment_document,
)
from backend.services.theme.hotlist_sentiment_service import HotListSentimentService


def _normalize_display_label(entry: Any) -> str | None:
    """snapshot_analysis 的 displayStatus 条目 → label（dict 取 label，str 直接用）。

    2026-09-10：分类层删除后不再有 8 类白名单，label 是后端 `STAGE_LABELS` 的投影
    （5 态词 + "无阶段"），词表单一来源在 `display_status`，本层不做第二套校验；
    只要求"非空字符串"，空值返回 None（fail-visible：无投影的行由 join 统计兜底）。
    """
    label = entry.get("label") if isinstance(entry, dict) else entry
    label = str(label or "").strip()
    return label or None


def _build_market_data_like(limit_summary: Any) -> dict | None:
    # frame.limitSummary = {continuousBoards, zhaban, yesterdayZt, thsPools}
    # → TS DragonBreathMarketDataLike {ztCount, zhaban, limitData, maxContinuousDays, thsLimitUpPools}
    if not isinstance(limit_summary, dict):
        return None
    boards = limit_summary.get("continuousBoards") if isinstance(limit_summary.get("continuousBoards"), dict) else {}
    yiban = float(boards.get("yiban") or 0)
    erban = float(boards.get("erban") or 0)
    sanban = float(boards.get("sanban") or 0)
    siban = float(boards.get("sibanPlus") or 0)
    max_days = 4 if siban > 0 else 3 if sanban > 0 else 2 if erban > 0 else 1 if yiban > 0 else 0
    return {
        "ztCount": yiban + erban + sanban + siban,   # limitSummary 无直接 ztCount，按连板结构聚合
        "zhaban": limit_summary.get("zhaban") if isinstance(limit_summary.get("zhaban"), dict) else {},
        "limitData": boards,
        "maxContinuousDays": max_days,
        "thsLimitUpPools": limit_summary.get("thsPools") if isinstance(limit_summary.get("thsPools"), dict) else None,
    }


def _join_display_status(db: Any, dataset_id: str, snapshot_id: str, rows: list[dict]) -> dict[str, Any]:
    """snapshot_analysis.displayStatus → rows[] 注入展示与规则标记（就地）。

    fail-visible：查询异常与个股无 displayStatus 分开结构化标注，不静默、不抛出（无质量阻断）。

    分类层删除后（spec §10）不再有 8 类 label / classKey / `stageMissing`：

    - 注入 `displayStatusStage` / `displayStatusLabel`（后端投影 `{stage, label, tooltip}`）；
    - 注入规则标记 `displayStatusStrongMoney` / `displayStatusRisk`（等价内联 B1）：判据唯一来源是
      `analysis.hotlist.sentiment.derive_row_flags`（内部复用 `display_status._is_strong_money` /
      `_is_volume_supported`），本层不得再写第二套判据。

    返回 {"joined": N, "noDisplayStatus": M, "joinFailed": bool, "reason": str | None}；
    调用方 `_compute_and_persist` 把标注追加进 `doc["warnings"]`。
    """
    from backend.analysis.hotlist.sentiment import derive_row_flags

    try:
        from backend.data.repositories.mongo_repository import MongoRepository

        analysis_by_code = MongoRepository(db).load_snapshot_analysis(
            dataset_id, snapshot_id, [str(row.get("code") or "") for row in rows]
        )
    except Exception as exc:
        return {
            "joined": 0,
            "noDisplayStatus": 0,
            "joinFailed": True,
            "reason": f"join_failed: {exc}",
        }
    joined = no_display = 0
    for row in rows:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        # load_snapshot_analysis 返回 {code: analysis}；displayStatus 是 analysis 内的条目
        entry = analysis.get("displayStatus") if isinstance(analysis, dict) else None
        label = _normalize_display_label(entry)
        if label:
            row["displayStatusLabel"] = label
            stage = entry.get("stage") if isinstance(entry, dict) else None
            row["displayStatusStage"] = stage if isinstance(stage, str) and stage else None
            # 样本质量声明透传（2026-09-24 口径统一）：meta.sampleQuality.status=insufficient
            # 的行与行情列表「样本不足」同源同判，resolve_row_signals 据此把展示桶归 unknown；
            # 缺 meta 时按 False 处理（老文档无该字段 → 维持 stage 桶，不回溯改历史口径）。
            meta = analysis.get("meta") if isinstance(analysis, dict) else None
            sample_quality = meta.get("sampleQuality") if isinstance(meta, dict) else None
            row["displayStatusSampleInsufficient"] = bool(
                isinstance(sample_quality, dict) and sample_quality.get("status") == "insufficient"
            )
            # 阶段迁移透传（2026-09-16）：cycle.transition 原样注入，供 transitionCounts 聚合
            cycle = analysis.get("cycle") if isinstance(analysis, dict) else None
            transition = cycle.get("transition") if isinstance(cycle, dict) else None
            row["cycleTransition"] = transition if isinstance(transition, str) and transition.strip() else None
            flags = derive_row_flags(analysis, row)
            row["displayStatusStrongMoney"] = bool(flags.get("strongMoney"))
            row["displayStatusRisk"] = bool(flags.get("risk"))
            joined += 1
        else:
            no_display += 1
    return {
        "joined": joined,
        "noDisplayStatus": no_display,
        "joinFailed": False,
        "reason": None,
    }


def _join_warning(join_stats: dict[str, Any]) -> str | None:
    if join_stats.get("joinFailed"):
        return f"displayStatus join failed（fallback 分类接管）: {join_stats.get('reason')}"
    if join_stats.get("noDisplayStatus"):
        return f"displayStatus missing on {join_stats['noDisplayStatus']} stocks（fallback 分类接管）"
    return None


def _status_source_summary(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """文档的展示状态来源/分布摘要（重算 before/after 对比用；缺字段保持缺失）。"""
    if not isinstance(doc, dict):
        return None
    metrics = doc.get("metrics") if isinstance(doc.get("metrics"), dict) else {}
    layers = metrics.get("layers") if isinstance(metrics.get("layers"), dict) else {}
    all_layer = layers.get("all") if isinstance(layers.get("all"), dict) else {}
    return {
        "slotTime": doc.get("slotTime"),
        "computedAt": doc.get("computedAt"),
        "statusSourceCounts": metrics.get("statusSourceCounts"),
        # 2026-09-12：8 类 statusCounts 已退役，分布只存在于 metrics.layers.<layer>.stageCounts
        # （文档无顶层 stageCounts）→ 三级回退，否则摘要恒为 None。
        "stageCounts": (
            doc.get("stageCounts")
            or metrics.get("stageCounts")
            or all_layer.get("stageCounts")
        ),
        "stage": doc.get("stage"),
    }


def _collect_intraday_state(
    db: Any,
    dataset_id: str,
    snapshot_type: str,
    trading_date: str,
    *,
    before_slot: str,
) -> dict[str, Any]:
    """因果截断地收集当日两条独立日内轨道（升序，双 EOD 形态排除）。

    - ``points``：日内边际证据轨道（slotTime + layers.all.stageShares），缺 shares 的槽跳过；
    - ``rawStagePoints``：阶段确认轨道（rawStage 优先、旧文档回退 stage），供
      ``stage_confirm.confirm_stage`` 重放；stage 缺失不影响 points 保留（独立轨道降级）；
    - ``scorePoints``：评分斜率轨道（路线 B 审计 B2，emotionScore.score 严格早于当前槽的
      有效序列），供当前槽 ``slope = score − prev_score``；旧文档无 emotionScore 的槽跳过；
    - ``historyStatus``：complete / empty / legacy_fallback / unavailable；
    - 非标准槽位（非 ``HH:MM``）保留在库但跳过收集，原因写入 ``diagnostics``。

    因果边界由调用方以 ``before_slot=当前帧槽位`` 给定：``slotTime >= before_slot`` 的
    记录一律不进入序列——数据库中已存在的未来槽不得污染历史重算（spec §5.1）。
    fail-visible：读取异常返回空结构 + 结构化诊断，不阻断主计算。
    """
    eod_id = f"{dataset_id}:{snapshot_type}:{trading_date}"
    points: list[dict[str, Any]] = []
    raw_stage_points: list[tuple[str, str]] = []
    score_points: list[tuple[str, float]] = []
    diagnostics: list[str] = []
    legacy_count = 0
    try:
        rows = db["hotlist_sentiment"].find(
            {
                "datasetId": dataset_id,
                "snapshotType": snapshot_type,
                "tradingDate": trading_date,
                "slotTime": {"$ne": "EOD"},
            },
            {"_id": 1, "slotTime": 1, "stage": 1, "rawStage": 1,
             "metrics.layers.all.stageShares": 1, "emotionScore.score": 1},
        )
        for row in rows:
            if str(row.get("_id") or "") == eod_id:
                continue
            slot_time = str(row.get("slotTime") or "")
            if len(slot_time) != 5 or slot_time[2] != ":":
                diagnostics.append(f"stage_confirm_nonstandard_slot:{slot_time or '<missing>'}")
                continue
            if slot_time >= before_slot:
                continue
            shares = (((row.get("metrics") or {}).get("layers") or {}).get("all") or {}).get("stageShares")
            if isinstance(shares, dict) and shares:
                points.append({"slotTime": slot_time, "stageShares": shares})
            raw_stage = str(row.get("rawStage") or "").strip()
            if not raw_stage:
                raw_stage = str(row.get("stage") or "").strip()
                if raw_stage:
                    legacy_count += 1
            if raw_stage:
                raw_stage_points.append((slot_time, raw_stage))
            score_value = (row.get("emotionScore") or {}).get("score")
            # isfinite 防御：NaN/inf 经 ingest 白名单可入库，污染 slope 合同（slope<0 对 NaN 恒 False）
            if isinstance(score_value, (int, float)) and not isinstance(score_value, bool) and math.isfinite(float(score_value)):
                score_points.append((slot_time, float(score_value)))
        points.sort(key=lambda item: item["slotTime"])
        raw_stage_points.sort(key=lambda item: item[0])
        score_points.sort(key=lambda item: item[0])
        if legacy_count:
            diagnostics.append(f"stage_confirm_legacy_fallback:{legacy_count}")
        status = "legacy_fallback" if legacy_count else "complete" if raw_stage_points else "empty"
        return {
            "points": points,
            "rawStagePoints": raw_stage_points,
            "scorePoints": score_points,
            "historyStatus": status,
            "diagnostics": diagnostics,
        }
    except Exception as exc:
        return {
            "points": [],
            "rawStagePoints": [],
            "scorePoints": [],
            "historyStatus": "unavailable",
            "diagnostics": [f"stage_confirm_history_unavailable:{type(exc).__name__}:{exc}"],
        }


def _stage_confirm_config() -> tuple[int, str | None]:
    """确认槽数配置（HOTLIST_STAGE_CONFIRM_SLOTS，默认 2）。

    非法值（非整数 / <1）回到裁决默认 2，并返回结构化原因供文档 diagnostics 落库；
    禁止静默退化为 1（那会关闭平滑且不可见，违反 fail-visible）。
    """
    import os

    raw = os.environ.get("HOTLIST_STAGE_CONFIRM_SLOTS", "2")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 2, f"stage_confirm_invalid_config:{raw!r}:fallback=2"
    if value < 1:
        return 2, f"stage_confirm_invalid_config:{raw!r}:fallback=2"
    return value, None


def _append_diagnostic(doc: dict[str, Any], message: str | None) -> None:
    """数据质量诊断标注进 doc["diagnostics"]（2026-09-24 与业务风险提示 warnings 分离）。"""
    if message:
        doc.setdefault("diagnostics", []).append(message)


def _invalidate_hotlist_sentiment_cache(dataset_id: str) -> None:
    """hotlist EOD 文档写库后失效读口缓存（``GET /api/hotlist-sentiment/series``）。

    依赖注册口径与读口一致（``<prefix>:snapshot:index:dataset:<dataset_id>``），
    所以这里只需重算同一个 index key，无需知道具体 response key。快照写入路径
    （ingest / collector，统一经数据层 after-save 钩子）失效的也是同一个 key，
    因此两条写入来源共用一套失效口径。

    fail-safe：任何异常只记 warning，绝不影响已经完成的写库结果
    （与 `run_snapshot_post_save_hooks` 的异常隔离同一原则）。
    """
    try:
        from backend.core.settings import get_settings
        from backend.data.cache.snapshot_cache import (
            build_snapshot_cache_index_keys,
            get_snapshot_redis_cache,
        )

        settings = get_settings()
        get_snapshot_redis_cache().invalidate_indexes(
            build_snapshot_cache_index_keys(
                prefix=settings.redis_key_prefix,
                dataset_id=dataset_id,
            )
        )
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "hotlist sentiment cache invalidation failed (dataset=%s)",
            dataset_id,
            exc_info=True,
        )


class HotListSentimentComputeService:
    def __init__(self, mongo_db: Any) -> None:
        self._db = mongo_db
        self._backfill = HotListSentimentBackfillService(mongo_db)
        self._sentiment = mongo_db["hotlist_sentiment"]

    def ensure_series(self, dataset_id: str, snapshot_type: str, days: int) -> dict[str, Any]:
        dates = self._backfill.trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type)
        if not dates:
            return {"ok": False, "degraded": True, "reason": "no_snapshot_trading_date", "items": []}
        window = dates[-days:]
        latest = window[-1]

        items: list[dict[str, Any]] = []
        for trading_date in window:
            # EOD 终值读口统一走 service 读原语（按 _id 精确命中，避免查询形状漂移）
            doc = HotListSentimentService(self._db).get_eod_document(dataset_id, snapshot_type, trading_date)
            if trading_date == latest and self._should_refresh_latest_eod(
                doc, dataset_id=dataset_id, snapshot_type=snapshot_type, trading_date=trading_date
            ):
                # lazy compute / 盘中陈旧刷新：仅最新交易日，幂等 upsert（取数→join→纯函数→upsert 一体）
                computed = self._compute_and_persist(dataset_id, snapshot_type, trading_date)
                if computed is None or computed.get("missing"):
                    items.append(computed or {"tradingDate": trading_date, "missing": True, "reason": "unknown"})
                    continue
                items.append(computed)
                continue
            if doc is None:
                items.append({"tradingDate": trading_date, "missing": True, "reason": "not_persisted"})
                continue
            items.append({key: value for key, value in doc.items() if key != "_id"})
        return {"ok": True, "items": items}

    def _should_refresh_latest_eod(
        self,
        doc: dict[str, Any] | None,
        *,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
    ) -> bool:
        """最新交易日 EOD 是否需要（重）算：无库行、或锚定帧落后且最新帧 analysis 已就绪。

        2026-09-15 盘中修复：lazy compute 原先"存在即跳过"，若首次触发落在
        "帧已落、analyze 产物未就绪"窗口（worker 异步 30s~2min），写入的 fallback
        EOD 全天固化。现在锚定帧落后于最新帧时刷新，但仅在最新帧已有 analyze 产物时
        （避免把旧的好口径降级重算成新帧的 fallback）；analysis 未就绪则保留旧文档。
        fail-visible：全日无 analyze 产物时按原 lazy compute 语义兜底（无库行才写）。
        """
        if doc is None:
            return True
        frame = self._backfill.latest_frame(dataset_id, snapshot_type, trading_date)
        if not frame:
            return False
        latest_snapshot_id = str(frame.get("snapshotId") or "")
        if not latest_snapshot_id or str(doc.get("snapshotId") or "") == latest_snapshot_id:
            return False  # 已锚定最新帧，不重算（防写放大）
        return (
            self._db["snapshot_analysis"].find_one(
                {"datasetId": dataset_id, "snapshotId": latest_snapshot_id}
            )
            is not None
        )

    def _compute_and_persist(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        *,
        persist: bool = True,
    ) -> dict | None:
        # 取数 → join displayStatus → 纯函数（含 limitSummary 市场证据）→ upsert（persist=False 只算不写）。
        # 与 backfill.run_for_date 的差异仅两点：displayStatus join + limitSummary 市场证据注入。
        # market_data 缺失时 fail-visible：missingEvidence 由纯函数标注，不阻断入库。
        frame, evidence_frame, evidence_slot = self._backfill.latest_frame_with_market_evidence(
            dataset_id, snapshot_type, trading_date
        )
        if not frame:
            return {"tradingDate": trading_date, "missing": True, "reason": "no_snapshot_frame"}
        stocks = self._backfill.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or ""))
        if not stocks:
            return {"tradingDate": trading_date, "missing": True, "reason": "empty_stock_rows"}
        previous = self._backfill.previous_day_stocks(dataset_id, snapshot_type, trading_date)
        # 昨日/前日 trading_date 透传（Task 5 裁决）：从完整历史窗口推导，与 run_for_date 口径一致
        prior_dates = [
            date
            for date in self._backfill.trading_dates(dataset_id=dataset_id, snapshot_type=snapshot_type)
            if date < trading_date
        ]
        join_stats = _join_display_status(self._backfill._db, dataset_id, str(frame.get("snapshotId") or ""), stocks)
        # 日内双轨道收集：shares 趋势点 + 截面阶段序列（因果截断于锚定帧槽位）
        anchored_slot = str(frame.get("slotTime") or "")
        intraday_state = _collect_intraday_state(
            self._backfill._db, dataset_id, snapshot_type, trading_date, before_slot=anchored_slot
        )
        confirm_slots, config_diagnostic = _stage_confirm_config()
        if config_diagnostic:
            intraday_state["diagnostics"].append(config_diagnostic)
        # 评分 evidence parts 取数（延迟 import：复用 jev 服务层模式，口径与 jev 轨道同源）；
        # 读失败降级为空 + 结构化诊断（与 _join_display_status 同语义：部分来源失败不阻断写库）
        from backend.services.jev.jev_sentiment_compute import (
            _load_analysis_by_code,
            _yesterday_total_amounts_by_slot,
        )

        try:
            emotion_analysis = _load_analysis_by_code(
                self._backfill._db, dataset_id, str(frame.get("snapshotId") or ""))
            emotion_amounts = _yesterday_total_amounts_by_slot(
                self._backfill._db, dataset_id, snapshot_type, trading_date)
            emotion_parts_error = None
        except Exception as exc:
            emotion_analysis, emotion_amounts = {}, None
            emotion_parts_error = f"emotion_evidence_load_failed:{type(exc).__name__}:{exc}"

        doc = build_hotlist_sentiment_document(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            frame=frame,
            stocks=stocks,
            yesterday_stocks=previous.get("yesterday") or [],
            day_before_stocks=previous.get("day_before") or [],
            market_data=_build_market_data_like(evidence_frame.get("limitSummary")) if evidence_frame else None,
            yesterday_trading_date=prior_dates[-1] if prior_dates else None,
            day_before_trading_date=prior_dates[-2] if len(prior_dates) >= 2 else None,
            intraday_history=intraday_state["points"],
            current_slot=str(anchored_slot) if anchored_slot else None,
            stage_history=intraday_state,
            stage_confirm_slots=confirm_slots,
            # 路线 B（T3 写口接线）：评分 evidence parts——昨日行复用 previous_day_stocks
            # （已含 displayStatus join，jev 聚合器只读行情字段不冲突），
            # analysis_by_code / 昨日同期总额复用 jev 服务层取数模式（口径同源）。
            yesterday_rows=previous.get("yesterday") or [],
            analysis_by_code=emotion_analysis,
            yesterday_amounts=emotion_amounts,
        )
        _append_diagnostic(doc, emotion_parts_error)
        join_note = _join_warning(join_stats)
        _append_diagnostic(doc, join_note)  # fail-visible：join 异常/缺失随文档落库
        for issue in previous.get("joinIssues") or []:
            _append_diagnostic(doc, issue)
        # fail-visible（2026-09-25 review）：炸板价格推导输入缺失行数随文档落库，
        # 让「真无炸板」与「bridge 行情离线导致输入缺失回 0」可分辨
        from backend.analysis.hotlist.sentiment import count_zhaban_input_missing

        zhaban_missing = count_zhaban_input_missing(stocks)
        if zhaban_missing:
            _append_diagnostic(doc, f"炸板推导输入缺失 {zhaban_missing} 行（无炸板标记且无 high/limitUpPrice，按未炸计）")
        if evidence_slot:
            # 与 run_for_date 同口径：市场证据回退来源随文档落库（fail-visible，不静默近似）
            _append_diagnostic(doc, f"最新帧 limitSummary 缺失，全市场证据回退自 {evidence_slot} 槽位")
        if persist:
            HotListSentimentService(self._backfill._db).upsert(doc)
            # 写口（lazy compute / recompute / 批量重算）统一失效读口缓存
            _invalidate_hotlist_sentiment_cache(dataset_id)
        return {key: value for key, value in doc.items() if key != "_id"}

    def recompute(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        *,
        persist: bool = True,
    ) -> dict[str, Any]:
        """强制重算并覆盖指定交易日的 EOD 文档（绕过 lazy compute 的“已存在即跳过”）。

        用途（2026-09-10 displayStatus 补跑）：`ensure_series` 只在“无库行”时计算，
        已持久化文档不会重算 → 新 join 到的 golden displayStatus 与 stageMissing
        永远不会生效。本方法显式重算 + 覆盖；重算本身可复现（纯函数 + 库内帧）。
        回滚安全网=git 历史与 data/backups 文件归档（2026-10-13 红线 4 执行：
        业务库不留 backup 集合，原 hotlist_sentiment_recompute_backup 已归档 drop）。
        """
        service = HotListSentimentService(self._backfill._db)
        before = service.get_eod_document(dataset_id, snapshot_type, trading_date)
        after = self._compute_and_persist(dataset_id, snapshot_type, trading_date, persist=persist)
        return {
            "ok": True,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "trading_date": trading_date,
            "applied": bool(persist),
            "before": _status_source_summary(before),
            "after": _status_source_summary(after),
        }


def compute_and_upsert_for_slot(
    mongo_db: Any,
    *,
    dataset_id: str,
    snapshot_type: str,
    trading_date: str,
    slot_time: str,
) -> dict[str, Any]:
    """collector 每槽落帧后的情绪计算入口（WP1b）。

    与 series lazy compute 的差异：指定槽位帧（非当日最新帧）、产出槽位 _id 文档。
    全库取数（不信任内存对象，保证 save-后-计算的数据一致性）；缺失返回 reason 不抛异常
    ——调用方（collector）负责不阻断帧采集。
    """
    try:
        from backend.operations.hotlist_sentiment import (
            HotListSentimentBackfillService,
            build_hotlist_sentiment_document,
        )

        backfill = HotListSentimentBackfillService(mongo_db)
        frame = backfill.frame_for_slot(dataset_id, snapshot_type, trading_date, slot_time)
        if not frame:
            return {"written": False, "reason": "no_snapshot_frame"}
        stocks = backfill.stocks_for_frame(dataset_id, str(frame.get("snapshotId") or ""))
        if not stocks:
            return {"written": False, "reason": "empty_stock_rows"}
        previous = backfill.previous_day_stocks(dataset_id, snapshot_type, trading_date)
        join_stats = _join_display_status(backfill._db, dataset_id, str(frame.get("snapshotId") or ""), stocks)
        # 日内双轨道收集：shares 趋势点 + 截面阶段序列（因果截断于当前槽位）
        intraday_state = _collect_intraday_state(
            backfill._db, dataset_id, snapshot_type, trading_date, before_slot=str(slot_time)
        )
        confirm_slots, config_diagnostic = _stage_confirm_config()
        if config_diagnostic:
            intraday_state["diagnostics"].append(config_diagnostic)
        # 评分 evidence parts 取数（延迟 import：复用 jev 服务层模式，口径与 jev 轨道同源）；
        # 读失败降级为空 + 结构化诊断（与 _join_display_status 同语义：部分来源失败不阻断写库）
        from backend.services.jev.jev_sentiment_compute import (
            _load_analysis_by_code,
            _yesterday_total_amounts_by_slot,
        )

        try:
            emotion_analysis = _load_analysis_by_code(
                mongo_db, dataset_id, str(frame.get("snapshotId") or ""))
            emotion_amounts = _yesterday_total_amounts_by_slot(
                mongo_db, dataset_id, snapshot_type, trading_date)
            emotion_parts_error = None
        except Exception as exc:
            emotion_analysis, emotion_amounts = {}, None
            emotion_parts_error = f"emotion_evidence_load_failed:{type(exc).__name__}:{exc}"

        doc = build_hotlist_sentiment_document(
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            frame=frame,
            stocks=stocks,
            yesterday_stocks=previous.get("yesterday") or [],
            day_before_stocks=previous.get("day_before") or [],
            market_data=_build_market_data_like(frame.get("limitSummary")),
            slot_time=slot_time,
            intraday_history=intraday_state["points"],
            current_slot=str(slot_time),
            stage_history=intraday_state,
            stage_confirm_slots=confirm_slots,
            # 路线 B（T3 写口接线）：评分 evidence parts（与 _compute_and_persist 同口径）
            yesterday_rows=previous.get("yesterday") or [],
            analysis_by_code=emotion_analysis,
            yesterday_amounts=emotion_amounts,
        )
        _append_diagnostic(doc, emotion_parts_error)
        join_note = _join_warning(join_stats)
        _append_diagnostic(doc, join_note)  # fail-visible：join 异常/缺失随文档落库
        for issue in previous.get("joinIssues") or []:
            _append_diagnostic(doc, issue)
        # fail-visible（2026-09-25 review）：炸板价格推导输入缺失行数随文档落库（与
        # _compute_and_persist / run_for_date 同口径）
        from backend.analysis.hotlist.sentiment import count_zhaban_input_missing

        zhaban_missing = count_zhaban_input_missing(stocks)
        if zhaban_missing:
            _append_diagnostic(doc, f"炸板推导输入缺失 {zhaban_missing} 行（无炸板标记且无 high/limitUpPrice，按未炸计）")
        HotListSentimentService(mongo_db).upsert(doc)
        return {"written": True, "reason": None}
    except Exception as exc:  # 无质量阻断：情绪失败不阻断帧采集
        return {"written": False, "reason": f"error: {exc}"}
