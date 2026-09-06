from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.data.repositories import repository_factory
from backend.services.theme.hotlist_sentiment_service import get_hotlist_sentiment_service


router = APIRouter(prefix="/api/hotlist-sentiment", tags=["hotlist-sentiment"])


class HotListSentimentPayload(BaseModel):
    tradingDate: str
    datasetId: str = "dragonboard_live"
    snapshotType: str = "half_hour"
    stage: str = "启动"
    riskLevel: str = "中"
    confidence: float = 0
    summary: str = ""
    metrics: dict[str, Any] = Field(default_factory=dict)
    turnover: dict[str, Any] = Field(default_factory=dict)
    signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.post("/ingest")
def ingest_hotlist_sentiment(payload: HotListSentimentPayload) -> dict[str, Any]:
    query = {
        "datasetId": payload.datasetId,
        "snapshotType": payload.snapshotType,
        "tradingDate": payload.tradingDate,
    }

    try:
        # 每次取当前运行时 db 传入 service，兼容测试 monkeypatch（单例缓存不阻塞注入）
        get_hotlist_sentiment_service(
            repository_factory.get_runtime_mongodb_database()
        ).upsert(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MongoDB primary is unavailable: {exc}") from exc

    return {"status": "ok", **query}


@router.get("/series")
def get_hotlist_sentiment_series(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    days: int = 3,
) -> dict[str, Any]:
    capped_days = max(1, min(int(days), 30))
    try:
        db = repository_factory.get_runtime_mongodb_database()
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"mongodb_unavailable: {exc}", "items": []}
    try:
        from backend.services.theme.hotlist_sentiment_compute import HotListSentimentComputeService

        return HotListSentimentComputeService(db).ensure_series(dataset_id, snapshot_type, capped_days)
    except Exception as exc:
        return {"ok": False, "degraded": True, "reason": f"series_compute_failed: {exc}", "items": []}