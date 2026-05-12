from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.settings import get_settings

if TYPE_CHECKING:
    from sqlalchemy import Engine


class ThemeBase(DeclarativeBase):
    pass


settings = get_settings()
theme_engine = create_engine(
    settings.theme_database_url,
    connect_args={"check_same_thread": False} if settings.theme_database_url.startswith("sqlite") else {},
)
ThemeSessionLocal = sessionmaker(bind=theme_engine, autoflush=False, autocommit=False, expire_on_commit=False)
_theme_initialized = False
_theme_available = True
_last_theme_error: str | None = None


def init_theme_db() -> bool:
    global _theme_initialized, _theme_available, _last_theme_error
    if _theme_initialized and _theme_available:
        return _theme_available
    from backend.data import theme_models  # noqa: F401

    try:
        ThemeBase.metadata.create_all(bind=theme_engine)
        _theme_available = True
        _last_theme_error = None
    except Exception as exc:  # pragma: no cover - defensive status path
        _theme_available = False
        _last_theme_error = str(exc)
        raise
    finally:
        _theme_initialized = True
    return _theme_available


def get_theme_db() -> Generator[Session | None, None, None]:
    if get_settings().storage_backend == "mongodb":
        yield None
        return
    if not init_theme_db():
        yield None
        return
    session = ThemeSessionLocal()
    try:
        yield session
    finally:
        session.close()


def theme_status() -> dict[str, str | bool | None]:
    if get_settings().storage_backend == "mongodb":
        from backend.data.repository_factory import mongodb_status

        status = mongodb_status()
        return {
            "configured": status.get("configured"),
            "connected": status.get("connected"),
            "url": None,
            "last_error": status.get("last_error"),
            "source": "mongodb",
        }
    return {
        "configured": bool(settings.theme_database_url),
        "connected": init_theme_db(),
        "url": _redact_database_url(settings.theme_database_url),
        "last_error": _last_theme_error,
    }


def _redact_database_url(url: str) -> str:
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return f"{scheme}://{rest}"
    auth, host = rest.rsplit("@", 1)
    if ":" in auth:
        user = auth.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return f"{scheme}://***@{host}"
