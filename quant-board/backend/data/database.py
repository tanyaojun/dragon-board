from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.settings import get_settings


class Base(DeclarativeBase):
    pass


class ResearchBase(DeclarativeBase):
    pass


settings = get_settings()
engine = create_engine(
    settings.snapshot_database_url,
    connect_args={"check_same_thread": False} if settings.snapshot_database_url.startswith("sqlite") else {},
)
research_engine = create_engine(
    settings.research_database_url,
    connect_args={"check_same_thread": False} if settings.research_database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
ResearchSessionLocal = sessionmaker(bind=research_engine, autoflush=False, autocommit=False, expire_on_commit=False)
_initialized = False
_primary_available = True
_last_primary_error: str | None = None


def init_db() -> bool:
    global _initialized, _primary_available, _last_primary_error
    if _initialized and _primary_available:
        return _primary_available
    from backend.data import models  # noqa: F401

    try:
        Base.metadata.create_all(bind=engine)
        ResearchBase.metadata.create_all(bind=research_engine)
        _primary_available = True
        _last_primary_error = None
    except SQLAlchemyError as exc:
        _primary_available = False
        _last_primary_error = str(exc)
        if not settings.backup_read_fallback:
            raise
    finally:
        _initialized = True
    return _primary_available


def primary_status() -> dict[str, str | bool | None]:
    return {
        "configured": bool(settings.database_url),
        "connected": init_db(),
        "url": _redact_database_url(settings.snapshot_database_url),
        "research_url": _redact_database_url(settings.research_database_url),
        "last_error": _last_primary_error,
    }


def get_db() -> Generator[Session | None, None, None]:
    if not init_db():
        yield None
        return
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


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
