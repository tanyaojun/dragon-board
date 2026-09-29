from __future__ import annotations

import pytest

from backend.data.migrations.theme_migration import ThemeMigrationError, ThemeMigrationService


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
    payload: dict,
    code: str,
    field: str,
) -> None:
    """主题映射导入的结构化错误合同（mongodb 单链，payload 校验先于任何存储触达）。"""
    with pytest.raises(ThemeMigrationError) as exc_info:
        ThemeMigrationService(None).import_mapping(payload)

    detail = exc_info.value.detail
    assert detail["code"] == code
    assert detail["field"] == field
    assert detail["message"]
