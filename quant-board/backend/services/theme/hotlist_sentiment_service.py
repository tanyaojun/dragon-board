"""热榜情绪（hotlist_sentiment）运行时服务。

统一封装 hotlist_sentiment 集合的写入（upsert）与按交易日读取，
供 API 路由（POST /api/hotlist-sentiment/ingest）与 ranktrend engine
（execution 模式 sentiment 补全）使用，避免 api / analysis 层直接持有 db 句柄。

写库语义与 backend/operations/hotlist_sentiment.py 中
HotListSentimentBackfillService 一致：replace_one(query, doc, upsert=True)。
"""
from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable

from backend.data.repositories import repository_factory


class HotListSentimentService:
    def __init__(self, mongo_db: Any) -> None:
        self._collection = mongo_db["hotlist_sentiment"]

    def upsert(self, payload: dict[str, Any]) -> None:
        """按 (datasetId, snapshotType, tradingDate) replace_one upsert 一条情绪文档。"""
        dataset_id = str(payload.get("datasetId") or "")
        snapshot_type = str(payload.get("snapshotType") or "")
        trading_date = str(payload.get("tradingDate") or "")
        query = {
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
        }
        doc = dict(payload)
        doc["_id"] = f"{dataset_id}:{snapshot_type}:{trading_date}"
        doc["computedAt"] = int(time.time())
        self._collection.replace_one(query, doc, upsert=True)

    def get_by_date(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, Any] | None:
        """按 (datasetId, snapshotType, tradingDate) 读取情绪文档（无则 None）。"""
        return self._collection.find_one(
            {
                "datasetId": dataset_id,
                "snapshotType": snapshot_type,
                "tradingDate": trading_date,
            }
        )


_hotlist_sentiment_service: HotListSentimentService | None = None
_hotlist_sentiment_service_lock = Lock()


def get_hotlist_sentiment_service(database: Any | None = None) -> HotListSentimentService:
    """模块级单例 getter：惰性构造，db 通过 repository_factory 获取。

    database 参数用于测试注入（fake db）或显式指定存储；为 None 时走
    repository_factory.get_runtime_mongodb_database()（与既有单例风格一致）。
    单例一旦构造后缓存在模块级；测试需要隔离时可传 database 绕过缓存。
    """
    global _hotlist_sentiment_service
    if database is not None:
        return HotListSentimentService(database)
    with _hotlist_sentiment_service_lock:
        if _hotlist_sentiment_service is None:
            _hotlist_sentiment_service = HotListSentimentService(
                repository_factory.get_runtime_mongodb_database()
            )
    return _hotlist_sentiment_service


def make_hotlist_sentiment_provider(
    dataset_id: str,
    snapshot_type: str = "half_hour",
) -> Callable[[str], dict[str, Any] | None]:
    """构造 ranktrend engine 注入用的 sentiment provider：(trading_date) -> doc | None。

    provider 惰性获取 service，MongoDB 不可用时由 engine 内部 try/except 降级，
    不影响 engine 构造与 analysis 模式回放。
    """

    def provider(trading_date: str) -> dict[str, Any] | None:
        service = get_hotlist_sentiment_service()
        return service.get_by_date(dataset_id, snapshot_type, trading_date)

    return provider
