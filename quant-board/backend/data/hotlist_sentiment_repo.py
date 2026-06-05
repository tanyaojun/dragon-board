from __future__ import annotations

from typing import Any


class HotListSentimentRepository:
    def __init__(self, mongo_db: Any) -> None:
        self._collection = mongo_db["hotlist_sentiment"]
        self._cache: dict[tuple[str, str, str], dict | None] = {}

    def get_by_date(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict | None:
        key = (dataset_id, snapshot_type, trading_date)
        if key not in self._cache:
            self._cache[key] = self._collection.find_one(
                {
                    "datasetId": dataset_id,
                    "snapshotType": snapshot_type,
                    "tradingDate": trading_date,
                }
            )
        return self._cache[key]
