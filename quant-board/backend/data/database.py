from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

if TYPE_CHECKING:
    from sqlalchemy import Engine

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
    if settings.storage_backend == "mongodb":
        _initialized = True
        _primary_available = True
        _last_primary_error = None
        return True
    if _initialized and _primary_available:
        return _primary_available
    from backend.data import models  # noqa: F401

    try:
        Base.metadata.create_all(bind=engine)
        ResearchBase.metadata.create_all(bind=research_engine)
        _migrate_snapshot_db(engine)
        _migrate_research_db(research_engine)
        _primary_available = True
        _last_primary_error = None
    except SQLAlchemyError as exc:
        _primary_available = False
        _last_primary_error = str(exc)
        raise
    finally:
        _initialized = True
    return _primary_available


def _migrate_snapshot_db(eng: "Engine") -> None:
    """逐列迁移快照事实库，补充 create_all 无法追加的列。"""
    from sqlalchemy import text

    migrations = [
        ("snapshot_stock_rows", "theme_contribution", "FLOAT"),
        ("snapshot_stock_rows", "theme_role", "VARCHAR(32)"),
        ("snapshot_stock_rows", "theme_exposure_weight", "FLOAT"),
        ("snapshot_stock_rows", "theme_risk_flags_json", "TEXT DEFAULT '[]'"),
        ("snapshot_sector_rows", "momentum_score", "FLOAT"),
        ("snapshot_sector_rows", "breadth_score", "FLOAT"),
        ("snapshot_sector_rows", "fund_score", "FLOAT"),
        ("snapshot_sector_rows", "leadership_score", "FLOAT"),
        ("snapshot_sector_rows", "correlation_score", "FLOAT"),
        ("snapshot_sector_rows", "crowding_risk", "FLOAT"),
        ("snapshot_sector_rows", "persistence_score", "FLOAT"),
        ("snapshot_sector_rows", "rotation_state", "VARCHAR(32)"),
        ("snapshot_sector_rows", "theme_quality_flags_json", "TEXT DEFAULT '[]'"),
    ]
    _apply_column_migrations(eng, migrations)


def _migrate_research_db(eng: "Engine") -> None:
    """逐列迁移，补充 create_all 无法追加的列。"""
    migrations = [
        # Phase 4: BacktestRun 增强字段
        ("backtest_runs", "date_start", "VARCHAR(16)"),
        ("backtest_runs", "date_end", "VARCHAR(16)"),
        ("backtest_runs", "error_reason", "TEXT"),
        ("backtest_runs", "finished_at", "DATETIME"),
        # Theme V2: 回测信号题材解释字段
        ("backtest_signals", "main_theme", "VARCHAR(160)"),
        ("backtest_signals", "theme_heat", "FLOAT"),
        ("backtest_signals", "theme_contribution", "FLOAT"),
        ("backtest_signals", "theme_role", "VARCHAR(32)"),
        ("backtest_signals", "theme_support_score", "FLOAT"),
        ("backtest_signals", "theme_risk_flags_json", "TEXT DEFAULT '[]'"),
        ("backtest_signals", "theme_reasons_json", "TEXT DEFAULT '[]'"),
    ]
    _apply_column_migrations(eng, migrations)


def _apply_column_migrations(eng: "Engine", migrations: list[tuple[str, str, str]]) -> None:
    from sqlalchemy import text

    with eng.connect() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                conn.commit()
            except OperationalError as exc:
                conn.rollback()
                if "duplicate column name" in str(exc).lower():
                    continue
                raise


def primary_status() -> dict[str, str | bool | None]:
    if settings.storage_backend == "mongodb":
        from backend.data.repository_factory import mongodb_status

        return mongodb_status()
    return {
        "configured": bool(settings.database_url),
        "connected": init_db(),
        "url": _redact_database_url(settings.snapshot_database_url),
        "research_url": _redact_database_url(settings.research_database_url),
        "last_error": _last_primary_error,
    }


def get_db() -> Generator[Session | None, None, None]:
    if settings.storage_backend == "mongodb":
        yield None
        return
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
