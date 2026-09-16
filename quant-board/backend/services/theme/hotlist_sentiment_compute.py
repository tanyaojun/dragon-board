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
        )
        join_note = _join_warning(join_stats)
        if join_note:
            doc.setdefault("warnings", []).append(join_note)  # fail-visible：join 异常/缺失随文档落库
        if evidence_slot:
            # 与 run_for_date 同口径：市场证据回退来源随文档落库（fail-visible，不静默近似）
            doc.setdefault("warnings", []).append(
                f"最新帧 limitSummary 缺失，全市场证据回退自 {evidence_slot} 槽位"
            )
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
        永远不会生效。本方法显式重算 + 覆盖，并先把旧文档写入
        `hotlist_sentiment_recompute_backup`（新集合，不动原文档）作回滚安全网；
        重算本身可复现（纯函数 + 库内帧），备份只是安全网。
        """
        service = HotListSentimentService(self._backfill._db)
        before = service.get_eod_document(dataset_id, snapshot_type, trading_date)
        if isinstance(before, dict):
            backup = {key: value for key, value in before.items() if key != "_id"}
            backup["sourceId"] = before.get("_id")
            backup["backedUpAt"] = int(time.time())
            backup["_id"] = f"{before.get('_id')}:recompute:{int(time.time())}"
            self._db["hotlist_sentiment_recompute_backup"].insert_one(backup)
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
        )
        join_note = _join_warning(join_stats)
        if join_note:
            doc.setdefault("warnings", []).append(join_note)  # fail-visible：join 异常/缺失随文档落库
        HotListSentimentService(mongo_db).upsert(doc)
        return {"written": True, "reason": None}
    except Exception as exc:  # 无质量阻断：情绪失败不阻断帧采集
        return {"written": False, "reason": f"error: {exc}"}
