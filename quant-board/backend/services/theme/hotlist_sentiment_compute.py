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

from typing import Any

from backend.analysis.hotlist.sentiment import STATUS_LABELS
from backend.operations.hotlist_sentiment import (
    HotListSentimentBackfillService,
    build_hotlist_sentiment_document,
)
from backend.services.theme.hotlist_sentiment_service import HotListSentimentService


def _normalize_display_label(entry: Any) -> str | None:
    # snapshot_analysis 的 displayStatus 条目：dict 取 label，str 直接用；非法标签返回 None
    label = entry.get("label") if isinstance(entry, dict) else entry
    label = str(label or "").strip()
    return label if label in STATUS_LABELS else None


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
    """snapshot_analysis.displayStatus → rows[].displayStatusLabel（就地注入）。

    fail-visible：查询异常与个股无 displayStatus 分开结构化标注，不静默、不抛出（无质量阻断）。
    返回 {"joined": N, "noDisplayStatus": M, "joinFailed": bool, "reason": str | None}；
    调用方 _compute_and_persist 把标注追加进 doc["warnings"]。
    """
    try:
        from backend.data.repositories.mongo_repository import MongoRepository

        analysis_by_code = MongoRepository(db).load_snapshot_analysis(
            dataset_id, snapshot_id, [str(row.get("code") or "") for row in rows]
        )
    except Exception as exc:
        return {"joined": 0, "noDisplayStatus": 0, "joinFailed": True, "reason": f"join_failed: {exc}"}
    joined = no_display = 0
    for row in rows:
        analysis = analysis_by_code.get(str(row.get("code") or ""))
        # load_snapshot_analysis 返回 {code: analysis}；displayStatus 是 analysis 内的条目
        entry = analysis.get("displayStatus") if isinstance(analysis, dict) else None
        label = _normalize_display_label(entry)
        if label:
            row["displayStatusLabel"] = label
            joined += 1
        else:
            no_display += 1
    return {"joined": joined, "noDisplayStatus": no_display, "joinFailed": False, "reason": None}


def _join_warning(join_stats: dict[str, Any]) -> str | None:
    if join_stats.get("joinFailed"):
        return f"displayStatus join failed（fallback 分类接管）: {join_stats.get('reason')}"
    if join_stats.get("noDisplayStatus"):
        return f"displayStatus missing on {join_stats['noDisplayStatus']} stocks（fallback 分类接管）"
    return None


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
            if doc is None and trading_date == latest:
                # lazy compute：仅最新交易日，幂等 upsert（取数→join→纯函数→upsert 一体）
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

    def _compute_and_persist(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict | None:
        # 取数 → join displayStatus → 纯函数（含 limitSummary 市场证据）→ upsert。
        # 与 backfill.run_for_date 的差异仅两点：displayStatus join + limitSummary 市场证据注入。
        # market_data 缺失时 fail-visible：missingEvidence 由纯函数标注，不阻断入库。
        frame = self._backfill.latest_frame(dataset_id, snapshot_type, trading_date)
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
            market_data=_build_market_data_like(frame.get("limitSummary")),
            yesterday_trading_date=prior_dates[-1] if prior_dates else None,
            day_before_trading_date=prior_dates[-2] if len(prior_dates) >= 2 else None,
        )
        join_note = _join_warning(join_stats)
        if join_note:
            doc.setdefault("warnings", []).append(join_note)  # fail-visible：join 异常/缺失随文档落库
        HotListSentimentService(self._backfill._db).upsert(doc)
        return {key: value for key, value in doc.items() if key != "_id"}
