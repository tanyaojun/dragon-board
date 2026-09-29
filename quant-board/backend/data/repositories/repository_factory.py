from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.data.repositories.mongo_research_repository import MongoResearchRepository
from backend.data.migrations.mongodb_migration import get_mongodb_database
from backend.core.settings import get_settings


_runtime_mongodb_database: Any | None = None


def create_repository(session: Session | None, *, enable_backup: bool = True) -> Any:
    """mongodb 单链唯一仓库入口（sqlite Repository 已随 2026-09-29 退役删除）。"""
    settings = get_settings()
    if settings.storage_backend == "mongodb":
        return MongoResearchRepository(get_runtime_mongodb_database())
    raise RuntimeError("sqlite 存储链已退役（2026-09-29）：请使用 mongodb 后端")


def get_runtime_mongodb_database() -> Any:
    global _runtime_mongodb_database
    if _runtime_mongodb_database is None:
        settings = get_settings()
        # pytest 库护栏统一在 get_mongodb_database 内实施（含生产库禁连与 test 库白名单）
        _runtime_mongodb_database = get_mongodb_database(
            settings.mongodb_uri,
            settings.mongodb_database,
            connect_timeout_ms=settings.mongodb_connect_timeout_ms,
            server_selection_timeout_ms=settings.mongodb_server_selection_timeout_ms,
            socket_timeout_ms=settings.mongodb_socket_timeout_ms,
            max_pool_size=settings.mongodb_max_pool_size,
        )
    return _runtime_mongodb_database


def storage_source_label() -> str:
    return "mongodb" if get_settings().storage_backend == "mongodb" else "sqlite"


def mongodb_status() -> dict[str, Any]:
    settings = get_settings()
    if settings.storage_backend != "mongodb":
        return {
            "configured": False,
            "connected": False,
            "mode": "sqlite",
            "last_error": None,
        }
    try:
        get_runtime_mongodb_database()
    except Exception as exc:
        return {
            "configured": bool(settings.mongodb_uri),
            "connected": False,
            "mode": "mongodb",
            "database": settings.mongodb_database,
            "last_error": str(exc),
        }
    return {
        "configured": bool(settings.mongodb_uri),
        "connected": True,
        "mode": "mongodb",
        "database": settings.mongodb_database,
        "last_error": None,
    }
