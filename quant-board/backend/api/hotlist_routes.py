from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.data import repository_factory


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
    doc = payload.model_dump()
    doc["_id"] = f"{payload.datasetId}:{payload.snapshotType}:{payload.tradingDate}"
    doc["computedAt"] = int(time.time())

    try:
        db = repository_factory.get_runtime_mongodb_database()
        db["hotlist_sentiment"].replace_one(query, doc, upsert=True)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"MongoDB primary is unavailable: {exc}") from exc

    return {"status": "ok", **query}
