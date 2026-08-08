"""快照只读查询服务：题材动量 / 题材轮动 API 的读取统一入口。

把 api 层对 snapshot_sector_rows / snapshot_frames 的直接 MongoDB 查询
收敛到 services 层。构造注入 repo（实现 SnapshotRepository 协议，
生产可注入 MongoRepository，测试可注入内存 fake）。
"""
from __future__ import annotations

from threading import Lock
from typing import Any

from backend.data.repositories import repository_factory
from backend.data.repositories.mongo_repository import MongoRepository


class SnapshotQueryService:
    def __init__(self, repo: Any) -> None:
        # repo 需暴露 db（MongoRepository.db），service 通过其访问集合
        self._repo = repo

    def recent_sector_rows(
        self,
        dataset_id: str,
        snapshot_type: str,
        *,
        entity_type: str = "hot_theme",
        limit: int = 20000,
    ) -> list[dict[str, Any]]:
        """最近 *limit* 行 sector rows：timestamp desc + limit，再逆序为时间升序。

        与原 theme_momentum 路由行为一致（desc 拉取 → reverse 升序）。
        """
        rows = list(
            self._repo.db["snapshot_sector_rows"]
            .find(
                {
                    "datasetId": dataset_id,
                    "type": snapshot_type,
                    "entityType": entity_type,
                }
            )
            .sort([("timestamp", -1)])
            .limit(limit)
        )
        rows.reverse()
        return rows

    def latest_rotation_frame(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str | None = None,
        slot_time: str | None = None,
    ) -> dict[str, Any] | None:
        """最近一个含 rotationSummary.algorithmVersion 的 frame（timestamp desc）。"""
        query: dict[str, Any] = {
            "datasetId": dataset_id,
            "type": snapshot_type,
            "rotationSummary.algorithmVersion": {"$exists": True},
        }
        if trading_date:
            query["tradingDate"] = trading_date
        if slot_time:
            query["slotTime"] = slot_time
        return self._repo.db["snapshot_frames"].find_one(query, sort=[("timestamp", -1)])

    def sector_rows_by_snapshot(
        self,
        dataset_id: str,
        snapshot_id: str,
        *,
        entity_type: str = "hot_theme",
    ) -> list[dict[str, Any]]:
        """按 snapshotId 读取 sector rows（rank 升序）。"""
        return list(
            self._repo.db["snapshot_sector_rows"]
            .find(
                {
                    "datasetId": dataset_id,
                    "snapshotId": snapshot_id,
                    "entityType": entity_type,
                }
            )
            .sort([("rank", 1)])
        )


_snapshot_query_service: SnapshotQueryService | None = None
_snapshot_query_service_lock = Lock()


def get_snapshot_query_service(database: Any | None = None) -> SnapshotQueryService:
    """模块级单例 getter。

    传 *database*（如路由从自身可注入的 get_runtime_mongodb_database 取到）
    时重建实例；否则用默认 repository_factory 的运行时库（惰性构造）。
    """
    global _snapshot_query_service
    with _snapshot_query_service_lock:
        if _snapshot_query_service is None or database is not None:
            db = database if database is not None else repository_factory.get_runtime_mongodb_database()
            _snapshot_query_service = SnapshotQueryService(MongoRepository(db))
    return _snapshot_query_service
