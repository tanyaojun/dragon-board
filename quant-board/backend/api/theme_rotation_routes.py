"""题材轮动只读 API：返回最新 frame.rotationSummary 与带轮动状态的 sector rows。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.data.repository_factory import get_runtime_mongodb_database

router = APIRouter(prefix="/api/theme-rotation", tags=["theme-rotation"])


@router.get("/summary")
def theme_rotation_summary(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    trading_date: str | None = None,
    slot_time: str | None = None,
) -> dict[str, Any]:
    """返回最近一个含 rotationSummary 的 frame 及其 sector rows 轮动状态。"""
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
    return {
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


def _public_sector(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "themeId", "themeName", "entityKey", "entityName", "rank", "rankChange",
        "rotationState", "lifecycle", "rotationScore", "heatTrend", "flowTrend",
        "breadthTrend", "crowdingTrend", "mainlineConcentrationRank", "reasons",
        "factorBreakdown", "qualityFlags",
    )
    return {key: row.get(key) for key in keys if key in row}
