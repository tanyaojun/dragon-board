from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.settings import get_settings
from backend.data.models.theme_database import ThemeBase
from backend.data.repositories.repository_factory import get_runtime_mongodb_database
from backend.data.migrations.theme_migration import ThemeMigrationError, ThemeMigrationService



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





@pytest.fixture(autouse=True)
def _clean_test_themes_mongo_rows():
    """mongodb 测试库跨轮持久：克隆库 themes/theme_stock_mappings 已含同名主题，
    幂等导入用例需先清掉本测试的两条固定主题再验证 inserted 计数。"""
    from backend.core.settings import get_settings

    if get_settings().storage_backend == "mongodb":
        from backend.data.repositories.repository_factory import get_runtime_mongodb_database

        db = get_runtime_mongodb_database()
        db["themes"].delete_many({"id": {"$in": ["AI", "POWER"]}})
        db["theme_stock_mappings"].delete_many({"themeId": {"$in": ["AI", "POWER"]}})
        db["theme_metadata"].delete_many({"key": {"$in": ["theme-v8-test"]}})
    yield


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
