from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.data.mongo_theme_repository import MongoThemeRepository
from backend.data.theme_service import ThemeMigrationService


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def sort(self, keys) -> "FakeCursor":
        sort_keys = list(keys if isinstance(keys, list) else [keys])
        for key, direction in reversed(sort_keys):
            self.rows.sort(key=lambda row: row.get(key) or "", reverse=int(direction) < 0)
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeDeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []

    def count_documents(self, query: dict[str, Any]) -> int:
        return len(list(self.find(query)))

    def delete_many(self, query: dict[str, Any]) -> FakeDeleteResult:
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return FakeDeleteResult(before - len(self.rows))

    def insert_many(self, rows: list[dict[str, Any]], ordered: bool = False) -> None:
        assert ordered is False
        self.rows.extend(dict(row) for row in rows)

    def replace_one(self, query: dict[str, Any], document: dict[str, Any], upsert: bool = False) -> None:
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                self.rows[index] = dict(document)
                return
        if upsert:
            self.rows.append(dict(document))

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next(iter(self.find(query)), None)

    def find(self, query: dict[str, Any] | None = None) -> FakeCursor:
        return FakeCursor([dict(row) for row in self.rows if _matches(row, query or {})])


class FakeMongoDatabase(dict):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_mongo_theme_repository_matches_theme_contract_without_json_fields() -> None:
    repo = MongoThemeRepository(FakeMongoDatabase())

    assert repo.upsert_theme("AI", "人工智能", "BK0800") is True
    assert repo.upsert_theme("POWER", "电力") is True
    assert repo.replace_theme_mappings(
        "AI",
        [
            {"stockCode": "000001", "tags": [{"Name": "算力", "Reason": "服务器订单"}], "reason": "算力龙头"},
            {"stockCode": "600001", "tags": [{"Name": "应用"}], "reason": "AI 应用落地"},
        ],
    ) == 2
    assert repo.replace_theme_mappings(
        "POWER",
        [{"stockCode": "600001", "tags": [{"Name": "电网"}], "reason": "电网建设"}],
    ) == 1
    repo.set_metadata("theme-v8-test", "2026-05-05T09:30:00.000Z")

    mapping = repo.get_mapping()
    reverse = repo.get_stock_themes("600001")
    counts = repo.counts()
    raw_mapping = repo.db["theme_stock_mappings"].rows[0]

    assert mapping["version"] == "theme-v8-test"
    assert [theme["id"] for theme in mapping["themes"]] == ["AI", "POWER"]
    assert mapping["themes"][0]["stockTags"]["000001"] == [{"Name": "算力", "Reason": "服务器订单"}]
    assert repo.get_theme_stocks("AI")["stocks"] == ["000001", "600001"]
    assert [theme["id"] for theme in reverse["themes"]] == ["AI", "POWER"]
    assert reverse["tags"] == [{"Name": "应用"}, {"Name": "电网"}]
    assert reverse["reason"] == "AI 应用落地；电网建设"
    assert counts == {
        "themeCount": 2,
        "mappingCount": 3,
        "stockCount": 2,
        "version": "theme-v8-test",
        "lastUpdate": "2026-05-05T09:30:00.000Z",
        "source": "mongodb",
    }
    assert raw_mapping["stockTags"] == [{"Name": "算力", "Reason": "服务器订单"}]
    assert "stock_tags_json" not in raw_mapping


def test_theme_migration_service_uses_mongo_repository_in_mongodb_mode(monkeypatch) -> None:
    db = FakeMongoDatabase()
    import backend.data.theme_service as theme_service

    monkeypatch.setattr(
        theme_service,
        "get_settings",
        lambda: type("Settings", (), {"storage_backend": "mongodb"})(),
        raising=False,
    )
    monkeypatch.setattr(theme_service, "get_runtime_mongodb_database", lambda: db, raising=False)

    result = ThemeMigrationService(None).import_mapping(_mapping_payload())
    verified = ThemeMigrationService(None).verify_mapping(_mapping_payload())

    assert result["source"] == "mongodb"
    assert verified["ok"] is True
    assert verified["source"] == "mongodb"
    assert db["themes"].find_one({"id": "AI"})["name"] == "人工智能"
    assert db["theme_stock_mappings"].find_one({"themeId": "AI", "stockCode": "000001"})["stockTags"] == [
        {"Name": "算力", "Reason": "服务器订单"}
    ]


def test_theme_api_reads_mongo_repository_when_storage_backend_is_mongodb(monkeypatch) -> None:
    repo = MongoThemeRepository(FakeMongoDatabase())
    repo.upsert_theme("AI", "人工智能", "BK0800")
    repo.replace_theme_mappings("AI", [{"stockCode": "000001", "tags": [{"Name": "算力"}], "reason": "算力龙头"}])
    repo.set_metadata("theme-v8-test", "2026-05-05T09:30:00.000Z")

    import backend.main as main

    monkeypatch.setattr(main, "storage_source_label", lambda: "mongodb")
    monkeypatch.setattr(main, "get_theme_repository", lambda db=None: repo, raising=False)
    main.app.dependency_overrides[main.get_theme_db] = lambda: None
    client = TestClient(main.app)
    try:
        mapping = client.get("/api/themes/mapping")
        stocks = client.get("/api/themes/stocks/AI")
        counts = client.get("/api/themes/counts")
    finally:
        main.app.dependency_overrides.clear()

    assert mapping.status_code == 200, mapping.text
    assert mapping.json()["source"] == "mongodb"
    assert mapping.json()["mapping"]["themes"][0]["stocks"] == ["000001"]
    assert stocks.status_code == 200, stocks.text
    assert stocks.json()["source"] == "mongodb"
    assert counts.status_code == 200, counts.text
    assert counts.json()["source"] == "mongodb"


def _mapping_payload() -> dict[str, Any]:
    return {
        "version": "theme-v8-test",
        "lastUpdate": "2026-05-05T09:30:00.000Z",
        "themes": [
            {
                "id": "AI",
                "name": "人工智能",
                "zsCode": "BK0800",
                "stocks": ["000001", "600001"],
                "stockTags": {
                    "000001": [{"Name": "算力", "Reason": "服务器订单"}],
                    "600001": [{"Name": "应用"}],
                },
                "stockReasons": {"000001": "算力龙头", "600001": "AI 应用落地"},
            }
        ],
    }


def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            continue
        if value != expected:
            return False
    return True
