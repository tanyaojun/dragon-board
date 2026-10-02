from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"

# 2026-09-29 隔离缺口 #1：operations 三文件曾硬编码
# MongoClient("mongodb://localhost:27017")["dragon_board_quant"]，绕过 settings 与 pytest 护栏
OPERATIONS_FILES = [
    BACKEND_ROOT / "operations" / "jev_phase_label_run.py",
]


def test_operations_ingest_files_have_no_hardcoded_mongo_client():
    for path in OPERATIONS_FILES:
        source = path.read_text(encoding="utf-8")
        assert "MongoClient(" not in source, f"{path.name} 仍在硬编码直连 MongoDB，必须改走 repository_factory"


def test_create_repository_rejects_sqlite_chain(monkeypatch):
    """sqlite Repository 已退役：create_repository 只认 mongodb 后端（pytest 与生产同合同）。"""
    from backend.data.repositories import repository_factory

    monkeypatch.setattr(
        repository_factory, "get_settings", lambda: SimpleNamespace(storage_backend="sqlite")
    )
    with pytest.raises(RuntimeError, match="sqlite 存储链已退役"):
        repository_factory.create_repository(None)


def test_theme_database_shim_has_no_sqlite_engine():
    """theme_database 收缩为 ThemeBase+theme_status：不再暴露任何 sqlite 建库入口。"""
    import backend.data.models.theme_database as theme_database

    assert not hasattr(theme_database, "init_theme_db")
    assert not hasattr(theme_database, "theme_engine")
    assert not hasattr(theme_database, "ThemeSessionLocal")

