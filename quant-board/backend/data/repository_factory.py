from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.data.mongo_research_repository import MongoResearchRepository
from backend.data.mongodb_migration import get_mongodb_database
from backend.data.repository import Repository
from backend.settings import get_settings


_runtime_mongodb_database: Any | None = None


def create_repository(session: Session | None, *, enable_backup: bool = True) -> Any:
    settings = get_settings()
    if settings.storage_backend == "mongodb":
        return MongoResearchRepository(get_runtime_mongodb_database())
    return Repository(session, enable_backup=enable_backup)


def get_runtime_mongodb_database() -> Any:
    global _runtime_mongodb_database
    if _runtime_mongodb_database is None:
        settings = get_settings()
        _runtime_mongodb_database = get_mongodb_database(
            settings.mongodb_uri,
            settings.mongodb_database,
            connect_timeout_ms=settings.mongodb_connect_timeout_ms,
            server_selection_timeout_ms=settings.mongodb_server_selection_timeout_ms,
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
