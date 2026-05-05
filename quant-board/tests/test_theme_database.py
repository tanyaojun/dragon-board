from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.data.theme_database import ThemeBase
from backend.data.theme_repository import ThemeRepository
from backend.data.theme_service import ThemeMigrationError, ThemeMigrationService
from backend.main import app


def _theme_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'themeDATA.db'}")
    ThemeBase.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, Session()


def _mapping_payload() -> dict:
    return {
        "version": "theme-v8-test",
        "lastUpdate": "2026-05-05T09:30:00.000Z",
        "totalThemes": 2,
        "themes": [
            {
                "id": "AI",
                "name": "人工智能",
                "zsCode": "BK0800",
                "stocks": ["000001", "SZ000001", "600001", "000001"],
                "stockTags": {
                    "000001": [{"Name": "算力", "Reason": "服务器订单"}],
                    "600001": [{"Name": "应用"}],
                },
                "stockReasons": {"000001": "算力龙头", "600001": "AI 应用落地"},
            },
            {
                "id": "POWER",
                "name": "电力",
                "stocks": ["600001", "000002"],
                "stockTags": {"600001": [{"Name": "电网"}]},
                "stockReasons": {"600001": "电网建设"},
            },
        ],
    }


def test_theme_database_initialization_is_repeatable(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'themeDATA.db'}")

    ThemeBase.metadata.create_all(bind=engine)
    ThemeBase.metadata.create_all(bind=engine)

    assert {"theme_metadata", "themes", "theme_stock_mappings"} <= set(ThemeBase.metadata.tables)
    engine.dispose()


def test_import_theme_mapping_is_idempotent_and_keeps_reverse_lookup_consistent(tmp_path: Path) -> None:
    engine, session = _theme_session(tmp_path)
    service = ThemeMigrationService(session)

    first = service.import_mapping(_mapping_payload())
    second = service.import_mapping(_mapping_payload())

    assert first["ok"] is True
    assert first["inserted"]["themes"] == 2
    assert first["inserted"]["mappings"] == 4
    assert second["ok"] is True
    assert second["inserted"] == {"themes": 0, "mappings": 0}
    assert second["updated"]["themes"] == 2

    repo = ThemeRepository(session)
    mapping = repo.get_mapping()
    assert mapping["version"] == "theme-v8-test"
    assert mapping["totalThemes"] == 2
    assert [theme["id"] for theme in mapping["themes"]] == ["AI", "POWER"]
    assert mapping["themes"][0]["stocks"] == ["000001", "600001"]

    assert repo.get_theme_stocks("AI")["stocks"] == ["000001", "600001"]
    reverse = repo.get_stock_themes("600001")
    assert [theme["id"] for theme in reverse["themes"]] == ["AI", "POWER"]
    assert reverse["tags"] == [{"Name": "应用"}, {"Name": "电网"}]
    assert reverse["reason"] == "AI 应用落地；电网建设"

    counts = repo.counts()
    assert counts == {
        "themeCount": 2,
        "mappingCount": 4,
        "stockCount": 3,
        "version": "theme-v8-test",
        "lastUpdate": "2026-05-05T09:30:00.000Z",
        "source": "sqlite",
    }
    session.close()
    engine.dispose()


def test_verify_theme_mapping_reports_counts_and_diffs_without_writing(tmp_path: Path) -> None:
    engine, session = _theme_session(tmp_path)
    service = ThemeMigrationService(session)
    service.import_mapping(_mapping_payload())

    matched = service.verify_mapping(_mapping_payload())
    assert matched["ok"] is True
    assert matched["expected"] == {
        "themeCount": 2,
        "mappingCount": 4,
        "stockCount": 3,
    }
    assert matched["actual"]["themeCount"] == 2
    assert matched["actual"]["mappingCount"] == 4
    assert matched["actual"]["stockCount"] == 3
    assert matched["mismatches"] == {}
    assert matched["missingThemes"] == []
    assert matched["extraThemes"] == []
    assert matched["missingMappings"] == []
    assert matched["extraMappings"] == []
    assert matched["source"] == "sqlite"

    changed = _mapping_payload()
    changed["themes"] = [
        {
            "id": "AI",
            "name": "人工智能",
            "stocks": ["SZ000001", "600001", "000003"],
        },
        {
            "id": "ROBOT",
            "name": "机器人",
            "stocks": ["300001"],
        },
    ]
    diff = service.verify_mapping(changed)
    assert diff["ok"] is False
    assert diff["expected"] == {"themeCount": 2, "mappingCount": 4, "stockCount": 4}
    assert diff["actual"]["themeCount"] == 2
    assert diff["missingThemes"] == [{"id": "ROBOT", "name": "机器人"}]
    assert diff["extraThemes"] == [{"id": "POWER", "name": "电力"}]
    assert {"themeId": "AI", "stockCode": "000003"} in diff["missingMappings"]
    assert {"themeId": "ROBOT", "stockCode": "300001"} in diff["missingMappings"]
    assert {"themeId": "POWER", "stockCode": "000002"} in diff["extraMappings"]
    assert service.verify_mapping(_mapping_payload())["ok"] is True

    session.close()
    engine.dispose()


@pytest.mark.parametrize(
    ("payload", "code", "field"),
    [
        ({}, "missing_themes", "themes"),
        ({"themes": [{"id": "", "name": "空", "stocks": ["000001"]}]}, "missing_theme_id", "themes[0].id"),
        ({"themes": [{"id": "AI", "name": "", "stocks": ["000001"]}]}, "missing_theme_name", "themes[0].name"),
        ({"themes": [{"id": "AI", "name": "人工智能", "stocks": ["abc"]}]}, "invalid_stock_code", "themes[0].stocks[0]"),
    ],
)
def test_import_theme_mapping_reports_structured_errors(
    tmp_path: Path,
    payload: dict,
    code: str,
    field: str,
) -> None:
    engine, session = _theme_session(tmp_path)

    with pytest.raises(ThemeMigrationError) as exc_info:
        ThemeMigrationService(session).import_mapping(payload)

    detail = exc_info.value.detail
    assert detail["code"] == code
    assert detail["field"] == field
    assert detail["message"]
    session.close()
    engine.dispose()


def test_theme_api_import_and_read_contracts() -> None:
    client = TestClient(app)

    imported = client.post("/api/migrations/themes/import-json", json=_mapping_payload())
    repeated = client.post("/api/migrations/themes/import-json", json=_mapping_payload())

    assert imported.status_code == 200, imported.text
    assert imported.json()["ok"] is True
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["inserted"] == {"themes": 0, "mappings": 0}

    mapping = client.get("/api/themes/mapping")
    assert mapping.status_code == 200, mapping.text
    body = mapping.json()
    assert body["ok"] is True
    assert body["source"] == "sqlite"
    assert body["mapping"]["version"] == "theme-v8-test"
    assert "source" not in body["mapping"]
    assert body["mapping"]["themes"][0]["stocks"] == ["000001", "600001"]
    ai_theme = next(theme for theme in body["mapping"]["themes"] if theme["id"] == "AI")
    assert ai_theme["stockTags"]["000001"] == [{"Name": "算力", "Reason": "服务器订单"}]
    assert ai_theme["stockReasons"]["600001"] == "AI 应用落地"

    stocks = client.get("/api/themes/stocks/AI")
    assert stocks.status_code == 200, stocks.text
    assert stocks.json()["stocks"] == ["000001", "600001"]

    reverse = client.get("/api/themes/stocks/by-code/600001")
    assert reverse.status_code == 200, reverse.text
    assert [theme["id"] for theme in reverse.json()["themes"]] == ["AI", "POWER"]
    assert reverse.json()["tags"] == [{"Name": "应用"}, {"Name": "电网"}]
    assert reverse.json()["reason"] == "AI 应用落地；电网建设"

    counts = client.get("/api/themes/counts")
    assert counts.status_code == 200, counts.text
    assert counts.json()["source"] == "sqlite"
    assert counts.json()["counts"] == {
        "themeCount": 2,
        "mappingCount": 4,
        "stockCount": 3,
        "version": "theme-v8-test",
        "lastUpdate": "2026-05-05T09:30:00.000Z",
        "source": "sqlite",
    }

    bad = client.post("/api/migrations/themes/import-json", json={})
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "missing_themes"

    verified = client.post("/api/migrations/themes/verify-json", json=_mapping_payload())
    assert verified.status_code == 200, verified.text
    assert verified.json()["ok"] is True
    assert verified.json()["expected"]["mappingCount"] == 4

    bad_verify = client.post("/api/migrations/themes/verify-json", json={})
    assert bad_verify.status_code == 400
    assert bad_verify.json()["detail"]["code"] == "missing_themes"

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["database"]["theme"]["connected"] is True
