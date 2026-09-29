"""题材成交量聚合（历史趋势页签数据源）测试。

覆盖两层：
- repo：MongoRepository.aggregate_stock_volume_by_theme 的 pipeline 语义
  （datasetId/themes 匹配、槽位分组、升序、缺失计数不伪造 0）。
- 路由：GET /api/themes/stock-volume-series 的参数校验、响应结构与
  非 MongoDB 后端的 503 结构化返回。
"""
from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import backend.api.theme_history_routes as theme_history_routes
from backend.data.repositories.mongo_repository import MongoRepository
from backend.main import app


# ---------- fakes ----------


class _ListCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class VolumeAggregateCollection:
    """只模拟 aggregate：记录 pipeline 并返回预置聚合结果。"""

    def __init__(self, aggregated: list[dict[str, Any]] | None = None) -> None:
        self.aggregated = aggregated or []
        self.pipelines: list[list[dict[str, Any]]] = []

    def aggregate(self, pipeline: list[dict[str, Any]], **_kwargs: Any) -> _ListCursor:
        self.pipelines.append(pipeline)
        return _ListCursor(self.aggregated)


class VolumeFakeDatabase(dict):
    def __getitem__(self, name: str) -> VolumeAggregateCollection:
        if name not in self:
            self[name] = VolumeAggregateCollection()
        return dict.__getitem__(self, name)


class FakeRepo:
    """路由层 fake：记录参数并返回预置 rows。"""

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[dict[str, Any]] = []

    def aggregate_stock_volume_by_theme(self, dataset_id: str, theme_name: str, **options: Any) -> dict[str, Any]:
        self.calls.append({"datasetId": dataset_id, "themeName": theme_name, **options})
        return {"rows": self.rows, "count": len(self.rows), "source": "mongodb"}


# ---------- repo 层 ----------


def _aggregated_docs() -> list[dict[str, Any]]:
    return [
        {
            "_id": {"tradingDate": "2026-09-04", "slotTime": "10:00", "timestamp": 1788496800000},
            "totalVolume": 120500,
            "totalAmount": 990000000.0,
            "stockCount": 12,
            "volumeCount": 12,
            "amountCount": 10,
        },
        {
            "_id": {"tradingDate": "2026-09-04", "slotTime": "10:30", "timestamp": 1788498600000},
            "totalVolume": 130000,
            "totalAmount": 1010000000.0,
            "stockCount": 12,
            "volumeCount": 12,
            "amountCount": 11,
        },
    ]


def test_aggregate_pipeline_matches_dataset_type_dates_and_theme() -> None:
    database = VolumeFakeDatabase()
    database["snapshot_stock_rows"].aggregated = _aggregated_docs()
    repo = MongoRepository(database)

    result = repo.aggregate_stock_volume_by_theme(
        "dragonboard_live",
        "关税战概念",
        snapshot_types=["half_hour"],
        start_date="2026-09-01",
        end_date="2026-09-04",
    )

    assert len(database["snapshot_stock_rows"].pipelines) == 1
    pipeline = database["snapshot_stock_rows"].pipelines[0]
    match = pipeline[0]["$match"]
    assert match["datasetId"] == "dragonboard_live"
    assert match["themes"] == "关税战概念"
    assert match["type"] == {"$in": ["half_hour"]}
    assert match["tradingDate"] == {"$gte": "2026-09-01", "$lte": "2026-09-04"}
    group = pipeline[1]["$group"]
    assert group["_id"] == {
        "tradingDate": "$tradingDate",
        "slotTime": "$slotTime",
        "timestamp": "$timestamp",
    }
    assert group["totalVolume"] == {"$sum": "$volume"}
    assert group["totalAmount"] == {"$sum": "$amount"}
    assert group["stockCount"] == {"$sum": 1}
    assert pipeline[2] == {"$sort": {"_id.timestamp": 1}}

    assert result["source"] == "mongodb"


def test_aggregate_maps_slot_rows_without_faking_missing_counts() -> None:
    """缺失计数（volumeCount/amountCount）保留输出，缺失不被伪装成真实 0。"""
    database = VolumeFakeDatabase()
    database["snapshot_stock_rows"].aggregated = _aggregated_docs()
    repo = MongoRepository(database)

    result = repo.aggregate_stock_volume_by_theme("dragonboard_live", "关税战概念")

    assert result["count"] == 2
    first = result["rows"][0]
    assert first == {
        "tradingDate": "2026-09-04",
        "slotTime": "10:00",
        "timestamp": 1788496800000,
        "totalVolume": 120500,
        "totalAmount": 990000000.0,
        "stockCount": 12,
        "volumeCount": 12,
        "amountCount": 10,
    }


def test_aggregate_trading_date_takes_precedence_over_range() -> None:
    database = VolumeFakeDatabase()
    repo = MongoRepository(database)

    repo.aggregate_stock_volume_by_theme(
        "dragonboard_live",
        "AI硬件",
        trading_date="2026-09-04",
        start_date="2026-09-01",
        end_date="2026-09-04",
    )

    match = database["snapshot_stock_rows"].pipelines[0][0]["$match"]
    assert match["tradingDate"] == "2026-09-04"


# ---------- 路由层 ----------


def test_stock_volume_series_returns_rows(monkeypatch) -> None:
    repo = FakeRepo(
        rows=[
            {
                "tradingDate": "2026-09-04",
                "slotTime": "10:00",
                "timestamp": 1788496800000,
                "totalVolume": 120500,
                "totalAmount": 990000000.0,
                "stockCount": 12,
                "volumeCount": 12,
                "amountCount": 10,
            }
        ]
    )
    monkeypatch.setattr(theme_history_routes, "create_repository", lambda db, enable_backup=True: repo)
    monkeypatch.setattr(theme_history_routes, "storage_source_label", lambda: "mongodb")
    client = TestClient(app)

    response = client.get(
        "/api/themes/stock-volume-series",
        params={
            "theme_name": "关税战概念",
            "types": "half_hour",
            "start_date": "2026-09-01",
            "end_date": "2026-09-04",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["themeName"] == "关税战概念"
    assert body["count"] == 1
    assert body["source"] == "mongodb"
    assert body["rows"][0]["totalVolume"] == 120500
    assert repo.calls[0]["themeName"] == "关税战概念"
    assert repo.calls[0]["datasetId"] == "dragonboard_live"


def test_stock_volume_series_requires_theme_name(monkeypatch) -> None:
    monkeypatch.setattr(theme_history_routes, "create_repository", lambda db, enable_backup=True: FakeRepo())
    monkeypatch.setattr(theme_history_routes, "storage_source_label", lambda: "mongodb")
    client = TestClient(app)

    response = client.get("/api/themes/stock-volume-series")

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False


def test_stock_volume_series_unavailable_without_mongodb(monkeypatch) -> None:
    """非 MongoDB 后端返回 503 结构化原因，不返回伪造空数据。"""
    monkeypatch.setattr(theme_history_routes, "create_repository", lambda db, enable_backup=True: FakeRepo())
    monkeypatch.setattr(theme_history_routes, "storage_source_label", lambda: "sqlite")
    from backend.data.models.database import get_db

    app.dependency_overrides[get_db] = lambda: None
    try:
        client = TestClient(app)
        response = client.get("/api/themes/stock-volume-series", params={"theme_name": "关税战概念"})

        assert response.status_code == 503
        body = response.json()
        assert body["ok"] is False
        assert body["errorCode"] == "storage_unavailable"
    finally:
        app.dependency_overrides.clear()


def test_stock_volume_series_unavailable_on_sqlite_with_session(monkeypatch) -> None:
    """sqlite 后端且 get_db 提供了 session（init_db 成功路径）时同样必须 503。

    SQL Repository 没有聚合方法，若守卫只看 db is None，请求会落到
    SQL repo 抛 AttributeError → 500，而非结构化 503。
    """
    monkeypatch.setattr(theme_history_routes, "create_repository", lambda db, enable_backup=True: FakeRepo())
    monkeypatch.setattr(theme_history_routes, "storage_source_label", lambda: "sqlite")
    from backend.data.models.database import get_db

    app.dependency_overrides[get_db] = lambda: object()  # 非 None session
    try:
        client = TestClient(app)
        response = client.get("/api/themes/stock-volume-series", params={"theme_name": "关税战概念"})

        assert response.status_code == 503
        body = response.json()
        assert body["ok"] is False
        assert body["errorCode"] == "storage_unavailable"
    finally:
        app.dependency_overrides.clear()
