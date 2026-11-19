"""快照只读查询服务：题材动量 / 题材轮动 API 的读取统一入口。

把 api 层对帧内嵌 sectorRows / snapshot_frames 的直接 MongoDB 查询（2026-11-19 起独立集合已 drop）
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
        rows = (
            self._repo.db["snapshot_frames"]
            .find(
                {
                    "datasetId": dataset_id,
                    "type": snapshot_type,
                },
                {"sectorRows": 1, "snapshotId": 1, "tradingDate": 1, "slotTime": 1,
                 "timestamp": 1, "type": 1, "datasetId": 1},
            )
            .sort([("timestamp", -1)])
        )
        # 2026-11-19 起 sector rows 内嵌在帧文档 sectorRows 数组（独立集合已 drop）。
        # 按帧惰性展开直到凑满 limit（不再用固定行/帧比估算帧数，帧内行数稀密不一）。
        collected: list[dict[str, Any]] = []
        for frame in rows:
            context = {
                key: frame.get(key)
                for key in ("datasetId", "snapshotId", "tradingDate", "slotTime", "timestamp", "type")
            }
            for embedded in frame.get("sectorRows") or []:
                if not isinstance(embedded, dict):
                    continue
                if entity_type and embedded.get("entityType") != entity_type:
                    continue
                collected.append({**context, **embedded})
            if limit and limit > 0 and len(collected) >= limit:
                break
        collected = collected[:limit] if limit and limit > 0 else collected
        collected.reverse()
        return collected

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
        """按 snapshotId 读取帧内嵌 sector rows（rank 升序；2026-11-19 起集合已 drop）。"""
        frame = self._repo.db["snapshot_frames"].find_one(
            {"datasetId": dataset_id, "snapshotId": snapshot_id},
            {"sectorRows": 1, "snapshotId": 1, "tradingDate": 1, "slotTime": 1,
             "timestamp": 1, "type": 1, "datasetId": 1},
        )
        if not frame:
            return []
        context = {
            key: frame.get(key)
            for key in ("datasetId", "snapshotId", "tradingDate", "slotTime", "timestamp", "type")
        }
        rows = [
            {**context, **embedded}
            for embedded in frame.get("sectorRows") or []
            if isinstance(embedded, dict)
            and (not entity_type or embedded.get("entityType") == entity_type)
        ]
        rows.sort(key=lambda row: row.get("rank") if isinstance(row.get("rank"), (int, float)) else 10**9)
        return rows


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
