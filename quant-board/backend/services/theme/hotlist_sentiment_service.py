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
        self._db = mongo_db  # provider 闭包 _query_trading_dates 经此访问 snapshot_frames
        self._collection = mongo_db["hotlist_sentiment"]

    def upsert(self, payload: dict[str, Any]) -> None:
        """按 _id 精确 upsert 一条情绪文档（slotTime="EOD" 哨兵 / "HH:MM" 槽位）。

        _id 由 build_hotlist_sentiment_document 构造（唯一构造点）；payload 缺 _id 时
        按四键格式构造兜底。query 用 _id 而非业务四键——存量行 slotTime 为旧 "HH:MM"
        值时，业务 query 命中 _id 不同的行会导致 MongoDB 拒绝改 _id（DuplicateKeyError）。
        """
        dataset_id = str(payload.get("datasetId") or "")
        snapshot_type = str(payload.get("snapshotType") or "")
        trading_date = str(payload.get("tradingDate") or "")
        slot_time = str(payload.get("slotTime") or "EOD")
        doc = dict(payload)
        doc.setdefault("slotTime", slot_time)
        doc.setdefault(
            "_id",
            f"{dataset_id}:{snapshot_type}:{trading_date}"
            + ("" if slot_time == "EOD" else f":{slot_time}"),
        )
        doc["computedAt"] = int(time.time())
        self._collection.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def get_by_date(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, Any] | None:
        """按日读取 EOD 终值文档（按 _id 精确命中——存量行与迁移后哨兵行同 _id，均返回）。"""
        return self._collection.find_one({"_id": f"{dataset_id}:{snapshot_type}:{trading_date}"})

    def list_slot_documents(self, dataset_id: str, snapshot_type: str, trading_date: str) -> list[dict[str, Any]]:
        """当日全部槽位文档，按 slotTime 升序。

        双条件排除 EOD：_id $ne 滤掉存量 EOD 行（slotTime 仍为旧 "HH:MM" 值），
        slotTime $ne "EOD" 滤掉迁移后哨兵行。
        """
        return list(
            self._collection.find(
                {
                    "datasetId": dataset_id,
                    "snapshotType": snapshot_type,
                    "tradingDate": trading_date,
                    "_id": {"$ne": f"{dataset_id}:{snapshot_type}:{trading_date}"},
                    "slotTime": {"$ne": "EOD"},
                }
            ).sort([("slotTime", 1)])
        )

    def get_eod_document(self, dataset_id: str, snapshot_type: str, trading_date: str) -> dict[str, Any] | None:
        """指定交易日的 EOD 终值文档（get_by_date 的显式命名别名，供 as-of 回退用）。"""
        return self.get_by_date(dataset_id, snapshot_type, trading_date)


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
