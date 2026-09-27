"""theme_daily_factors 集合数据访问层（设计 §5.1 存储方案，2026-09-27）。

集合是快照 stock rows × theme_stock_mappings 的派生投影（可由
services/theme/daily_factors_service.compute_and_store_daily_factors 全量重建），
不是第二事实源；行粒度 (datasetId, tradingDate, themeId)，因子值与
qualityFlags 见 analysis/theme/factors_daily.py。

仅 MongoDB 后端使用（调度器与 API 进程均按 storage_backend == "mongodb" 启用，
对齐 ThemeMappingRefreshScheduler 先例）；SQLite 后端不建该集合。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

COLLECTION_NAME = "theme_daily_factors"


class ThemeDailyFactorRepository:
    def __init__(self, database: Any) -> None:
        self.db = database
        self._indexed = False

    def _ensure_indexes(self) -> None:
        if self._indexed:
            return
        collection = self.db[COLLECTION_NAME]
        collection.create_index(
            [("datasetId", 1), ("tradingDate", 1), ("themeId", 1)], unique=True
        )
        collection.create_index([("datasetId", 1), ("tradingDate", -1)])
        self._indexed = True

    def upsert_day(self, dataset_id: str, trading_date: str, rows: list[dict[str, Any]]) -> int:
        """按 (datasetId, tradingDate, themeId) 幂等覆盖写入一日的全部因子行。"""
        self._ensure_indexes()
        collection = self.db[COLLECTION_NAME]
        now = datetime.now(UTC)
        written = 0
        for row in rows:
            theme_id = str(row.get("themeId") or "")
            if not theme_id:
                continue
            doc = {
                **row,
                "datasetId": dataset_id,
                "tradingDate": trading_date,
                "themeId": theme_id,
                "updatedAt": now,
            }
            collection.replace_one(
                {"datasetId": dataset_id, "tradingDate": trading_date, "themeId": theme_id},
                doc,
                upsert=True,
            )
            written += 1
        return written

    def computed_dates(self, dataset_id: str, start_date: str, end_date: str) -> list[str]:
        """已有因子行的交易日列表（去重升序）。"""
        docs = self.db[COLLECTION_NAME].find(
            {"datasetId": dataset_id, "tradingDate": {"$gte": start_date, "$lte": end_date}},
            {"tradingDate": 1},
        )
        return sorted({str(doc.get("tradingDate")) for doc in docs if doc.get("tradingDate")})

    def dates_with_factor_key(
        self, dataset_id: str, start_date: str, end_date: str, field_path: str
    ) -> list[str]:
        """已写入指定因子键（如 factors.momentumV2）的交易日列表（去重升序）。

        用于 auto 模式"完整度"判定：新增因子维度后，已有拥挤行但缺新维度的
        日期会被自动补算（自愈），不再依赖一次性回填。
        """
        docs = self.db[COLLECTION_NAME].find(
            {
                "datasetId": dataset_id,
                "tradingDate": {"$gte": start_date, "$lte": end_date},
                field_path: {"$exists": True},
            },
            {"tradingDate": 1},
        )
        return sorted({str(doc.get("tradingDate")) for doc in docs if doc.get("tradingDate")})

    def latest_date(self, dataset_id: str) -> str | None:
        doc = self.db[COLLECTION_NAME].find_one(
            {"datasetId": dataset_id}, sort=[("tradingDate", -1)]
        )
        return str(doc.get("tradingDate")) if doc else None

    def list_range(self, dataset_id: str, start_date: str, end_date: str) -> list[dict[str, Any]]:
        cursor = self.db[COLLECTION_NAME].find(
            {"datasetId": dataset_id, "tradingDate": {"$gte": start_date, "$lte": end_date}}
        ).sort([("tradingDate", 1), ("themeId", 1)])
        return list(cursor)
