"""题材轮动只读 API：返回最新 frame.rotationSummary 与带轮动状态的 sector rows。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.data.cache import snapshot_cache
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.core.settings import get_settings

router = APIRouter(prefix="/api/theme-rotation", tags=["theme-rotation"])


def _cache_key(
    dataset_id: str,
    snapshot_type: str,
    trading_date: str | None,
    slot_time: str | None,
) -> str:
    builder = snapshot_cache.SnapshotCacheKeyBuilder(prefix=get_settings().redis_key_prefix)
    return builder.response_key(
        "theme-rotation-summary",
        resolved_dataset_id=dataset_id,
        params={
            "snapshot_type": snapshot_type,
            "trading_date": trading_date or "",
            "slot_time": slot_time or "",
        },
    )


@router.get("/summary")
def theme_rotation_summary(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    trading_date: str | None = None,
    slot_time: str | None = None,
) -> dict[str, Any]:
    """返回最近一个含 rotationSummary 的 frame 及其 sector rows 轮动状态。"""
    cache = snapshot_cache.get_snapshot_redis_cache()
    cache_key = _cache_key(dataset_id, snapshot_type, trading_date, slot_time)
    cached = cache.get_response(cache_key)
    if cached is not None:
        return cached

    db = get_runtime_mongodb_database()
    query: dict[str, Any] = {
        "datasetId": dataset_id,
        "type": snapshot_type,
        # M6：过滤引擎产出的 rotationSummary（含 algorithmVersion），避免空 dict 命中
        "rotationSummary.algorithmVersion": {"$exists": True},
    }
    if trading_date:
        query["tradingDate"] = trading_date
    if slot_time:
        query["slotTime"] = slot_time
    frame_doc = db["snapshot_frames"].find_one(query, sort=[("timestamp", -1)])
    if not frame_doc:
        raise HTTPException(
            status_code=404,
            detail={"ok": False, "status": "error",
                    "error": "no theme rotation summary found for the given filters"},
        )

    sector_rows = list(
        db["snapshot_sector_rows"]
        .find(
            {
                "datasetId": dataset_id,
                "snapshotId": frame_doc["snapshotId"],
                "entityType": "hot_theme",
            }
        )
        .sort([("rank", 1)])
    )
    response: dict[str, Any] = {
        "ok": True,
        "status": "ok",
        "data": {
            "frame": {
                "snapshotId": frame_doc["snapshotId"],
                "tradingDate": frame_doc.get("tradingDate"),
                "slotTime": frame_doc.get("slotTime"),
                "timestamp": frame_doc.get("timestamp"),
                "rotationSummary": frame_doc.get("rotationSummary"),
            },
            "statuses": [_public_sector(row) for row in sector_rows],
        },
    }
    settings = get_settings()
    cache.set_response(cache_key, response, ttl_seconds=settings.theme_rotation_cache_ttl_seconds)
    cache.register_dependencies(
        cache_key,
        snapshot_cache.build_snapshot_cache_index_keys(
            prefix=settings.redis_key_prefix,
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            trading_date=str(frame_doc.get("tradingDate") or trading_date or ""),
        ),
    )
    return response


def _public_sector(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "themeId", "themeName", "entityKey", "entityName", "rank", "rankChange",
        "rotationState", "lifecycle", "rotationScore", "heatTrend", "flowTrend",
        "breadthTrend", "crowdingTrend", "mainlineConcentrationRank", "reasons",
        "factorBreakdown", "qualityFlags",
    )
    return {key: row.get(key) for key in keys if key in row}