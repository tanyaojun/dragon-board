from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.main import app


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = list(rows)

    def sort(self, spec: list[tuple[str, int]]) -> "FakeCursor":
        for key, direction in reversed(spec):
            self.rows.sort(key=lambda row: row.get(key) or 0, reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeReplaceResult:
    matched_count = 0
    modified_count = 0
    upserted_id = "dragonboard_live:half_hour:2026-06-05"


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    def find(self, query: dict[str, Any] | None = None, projection: dict[str, Any] | None = None) -> FakeCursor:
        query = query or {}
        rows = [row for row in self.rows if self._matches(row, query)]
        if projection:
            projected = []
            for row in rows:
                projected.append({key: row.get(key) for key, enabled in projection.items() if enabled})
            rows = projected
        return FakeCursor(rows)

    def find_one(
        self,
        query: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        rows = list(self.find(query or {}))
        if sort:
            rows = list(FakeCursor(rows).sort(sort))
        return rows[0] if rows else None

    def replace_one(
        self,
        query: dict[str, Any],
        doc: dict[str, Any],
        upsert: bool = False,
    ) -> FakeReplaceResult:
        self.replace_calls.append((query, doc, upsert))
        self.rows = [row for row in self.rows if not self._matches(row, query)]
        self.rows.append(doc)
        return FakeReplaceResult()

    @staticmethod
    def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, expected in query.items():
            actual = row.get(key)
            if isinstance(expected, dict) and "$in" in expected:
                if actual not in expected["$in"]:
                    return False
            elif isinstance(expected, dict) and "$ne" in expected:
                if actual == expected["$ne"]:
                    return False
            elif actual != expected:
                return False
        return True


class FakeMongoDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {
            "snapshot_frames": FakeCollection(),
            "snapshot_stock_rows": FakeCollection(),
            "hotlist_sentiment": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


def _frame(dataset_id: str, snapshot_type: str, trading_date: str, snapshot_id: str) -> dict:
    return {"datasetId": dataset_id, "type": snapshot_type, "tradingDate": trading_date,
            "snapshotId": snapshot_id, "slotTime": "14:30", "timestamp": 1757000000}


def _seed_frames(db, dataset_id: str, snapshot_type: str, dates: list[str]) -> None:
    for i, date in enumerate(dates):
        db["snapshot_frames"].rows.append(_frame(dataset_id, snapshot_type, date, f"snap-{date}"))
        db["snapshot_stock_rows"].rows.extend([
            {"datasetId": dataset_id, "snapshotId": f"snap-{date}", "code": "000001", "name": "甲",
             "compRank": 1, "change": 5.0, "turnover": 8e8, "zlje": 1e8, "zljzb": 12,
             "cddje": 5000e4, "cddjzb": 5, "volumeRatio": 1.4, "turnoverRate": 8, "rank": 1},
        ])


def test_series_lazy_computes_latest_day_and_persists(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    _seed_frames(fake_db, "dragonboard_live", "half_hour", ["2026-06-03", "2026-06-04", "2026-06-05"])
    # 历史日不做 lazy compute，前两日预置库文档；只有最新交易日走 lazy compute
    for date in ("2026-06-03", "2026-06-04"):
        fake_db["hotlist_sentiment"].rows.append({
            "_id": f"dragonboard_live:half_hour:{date}",
            "datasetId": "dragonboard_live", "snapshotType": "half_hour",
            "tradingDate": date, "stage": "启动", "riskLevel": "低", "confidence": 60,
            "summary": "预置",
            "metrics": {"topN": 1, "layers": {}, "comparison": {}, "limitEvidence": {}},
            "turnover": {"newEntries": [], "eliminated": []}, "signals": [], "warnings": [],
        })
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    response = client.get("/api/hotlist-sentiment/series", params={
        "dataset_id": "dragonboard_live", "snapshot_type": "half_hour", "days": 3,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    items = body["items"]
    assert [item["tradingDate"] for item in items] == ["2026-06-03", "2026-06-04", "2026-06-05"]
    assert all(not item.get("missing") for item in items)
    assert all("stage" in item and "metrics" in item for item in items)
    # lazy compute 幂等：最新交易日已 upsert 到 hotlist_sentiment
    assert fake_db["hotlist_sentiment"].rows, "最新交易日应已入库"
    assert all(row["tradingDate"] in ("2026-06-03", "2026-06-04", "2026-06-05")
               for row in fake_db["hotlist_sentiment"].rows)
    # Task 5 裁决回归防线：lazy compute 透传昨日/前日 trading_date，前端可读 comparison.yesterday.tradingDate
    latest_row = next(row for row in fake_db["hotlist_sentiment"].rows
                      if row["tradingDate"] == "2026-06-05")
    assert latest_row["metrics"]["comparison"]["yesterday"]["tradingDate"] == "2026-06-04"
    assert latest_row["metrics"]["comparison"]["dayBefore"]["tradingDate"] == "2026-06-03"


def test_series_second_call_reads_from_db(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    _seed_frames(fake_db, "dragonboard_live", "half_hour", ["2026-06-04", "2026-06-05"])
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)
    client.get("/api/hotlist-sentiment/series", params={"dataset_id": "dragonboard_live"})
    writes_after_first = len(fake_db["hotlist_sentiment"].rows)

    response = client.get("/api/hotlist-sentiment/series", params={"dataset_id": "dragonboard_live"})

    assert response.status_code == 200
    assert len(fake_db["hotlist_sentiment"].rows) == writes_after_first  # 未新增写库


def test_series_days_default_and_cap(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    # 种子 35 天 > cap 30：确保 cap-30 截断真实生效（10 天种子下 <=30 恒真，测不到截断）
    _seed_frames(fake_db, "dragonboard_live", "half_hour", [f"2026-05-{d:02d}" for d in range(1, 36)])
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    body = client.get("/api/hotlist-sentiment/series", params={"dataset_id": "dragonboard_live"}).json()
    assert len(body["items"]) == 3

    body = client.get("/api/hotlist-sentiment/series",
                      params={"dataset_id": "dragonboard_live", "days": "99"}).json()
    assert len(body["items"]) == 30


def test_series_no_frames_returns_degraded(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    response = client.get("/api/hotlist-sentiment/series", params={"dataset_id": "dragonboard_live"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["degraded"] is True
    assert body["reason"]


def test_series_empty_stock_rows_marks_missing_day(monkeypatch):
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    # 只有帧、没有 stock rows → 该日 missing 标注，不伪造
    fake_db["snapshot_frames"].rows.append(_frame("dragonboard_live", "half_hour", "2026-06-05", "snap-x"))
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    body = client.get("/api/hotlist-sentiment/series",
                      params={"dataset_id": "dragonboard_live", "days": "1"}).json()
    assert body["ok"] is True
    assert body["items"][0]["missing"] is True
    assert body["items"][0]["reason"] == "empty_stock_rows"


import pytest


@pytest.fixture(autouse=True)
def _disable_snapshot_cache(monkeypatch):
    """读口缓存隔离（2026-09-10 系列读口新增 Redis TTL 缓存）：测试必须走真实计算路径。

    若本机 Redis 可达，缓存会跨测试命中（前一个测试写入的响应被复用），series 断言会随机失败。
    """
    from backend.data.cache import snapshot_cache

    class _NoCache:
        def get_response(self, key):
            return None

        def set_response(self, key, response, *, ttl_seconds=None):
            return None

        def register_dependencies(self, response_key, index_keys):
            return None

        def invalidate_indexes(self, index_keys):
            return None

        def get_generation(self, key):
            return 0

        def bump_generation(self, key):
            return 0

    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: _NoCache())

