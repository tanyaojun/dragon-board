from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.data.importers import frame_from_record, normalize_record, sector_rows_from_record, stock_rows_from_record
from backend.data.json_codec import dumps_json_field
from backend.data.models import (
    BacktestRun,
    Dataset,
    GoldenRankTrendCase,
    OptimizationRun,
    SnapshotFrameModel,
    SnapshotRecordModel,
    SnapshotSectorRowModel,
    SnapshotStockRowModel,
    SyncOutboxModel,
)
from backend.data.repository import Repository
from backend.utils import json_loads, stable_hash


def migrate_legacy_db(
    *,
    source: str | Path,
    snapshot_database_url: str,
    research_database_url: str,
    apply: bool = False,
) -> dict[str, Any]:
    source_path = Path(source)
    if not source_path.exists():
        return {"ok": False, "applied": False, "error": f"legacy database not found: {source_path}"}

    plan = _legacy_counts(source_path)
    result: dict[str, Any] = {"ok": True, "applied": bool(apply), "source": str(source_path), "plan": plan, "migrated": {}, "conflicts": []}
    if not apply:
        return result

    snapshot_engine = create_engine(snapshot_database_url, connect_args={"check_same_thread": False} if snapshot_database_url.startswith("sqlite") else {})
    research_engine = create_engine(research_database_url, connect_args={"check_same_thread": False} if research_database_url.startswith("sqlite") else {})
    SnapshotSession = sessionmaker(bind=snapshot_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    ResearchSession = sessionmaker(bind=research_engine, autoflush=False, autocommit=False, expire_on_commit=False)
    try:
        with sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True) as legacy:
            legacy.row_factory = sqlite3.Row
            with SnapshotSession() as snapshot_session:
                snapshot_counts = _migrate_snapshots(legacy, snapshot_session)
                snapshot_session.commit()
            with ResearchSession() as research_session:
                research_counts = _migrate_research(legacy, research_session)
                research_session.commit()
        result["migrated"] = {**snapshot_counts, **research_counts}
        result["postAction"] = "旧 quant_board.db 已保留；迁移验收通过后可由用户手动归档。"
        return result
    finally:
        snapshot_engine.dispose()
        research_engine.dispose()


def _legacy_counts(path: Path) -> dict[str, int]:
    wanted = [
        "datasets",
        "snapshot_records",
        "snapshot_frames",
        "snapshot_stock_rows",
        "snapshot_sector_rows",
        "backtest_runs",
        "optimization_runs",
        "golden_ranktrend_cases",
        "sync_outbox",
    ]
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
        tables = _tables(conn)
        return {table: _count(conn, table) if table in tables else 0 for table in wanted}


def _migrate_snapshots(legacy: sqlite3.Connection, session) -> dict[str, int]:
    repo = Repository(session, enable_backup=False)
    counts = {"datasets": 0, "snapshot_records": 0, "snapshot_frames": 0, "snapshot_stock_rows": 0, "snapshot_sector_rows": 0, "sync_outbox": 0}
    tables = _tables(legacy)
    seen_datasets: set[str] = set()
    if "datasets" in tables:
        for row in legacy.execute("select * from datasets"):
            dataset = _dataset_from_row(row)
            seen_datasets.add(dataset.id)
            if not session.get(Dataset, dataset.id):
                session.merge(dataset)
                counts["datasets"] += 1
    if "snapshot_records" in tables:
        for row in legacy.execute("select * from snapshot_records order by timestamp asc"):
            record = _record_from_legacy(row)
            if not record:
                continue
            dataset_id = str(row["dataset_id"] or "dragonboard_live")
            if dataset_id not in seen_datasets and not session.get(Dataset, dataset_id):
                session.merge(_fallback_dataset(dataset_id, record))
                seen_datasets.add(dataset_id)
                counts["datasets"] += 1
            if not _exists(session, SnapshotRecordModel, dataset_id, record["id"]):
                session.add(repo._record_model(dataset_id, record))
                counts["snapshot_records"] += 1
            frame = frame_from_record(record)
            if not _exists(session, SnapshotFrameModel, dataset_id, frame["snapshotId"]):
                session.add(repo._frame_model(dataset_id, frame))
                counts["snapshot_frames"] += 1
            for stock in stock_rows_from_record(record):
                if not _row_exists(session, SnapshotStockRowModel, dataset_id, stock["id"]):
                    session.add(repo._stock_model(dataset_id, stock))
                    counts["snapshot_stock_rows"] += 1
            for sector in sector_rows_from_record(record):
                if not _row_exists(session, SnapshotSectorRowModel, dataset_id, sector["id"]):
                    session.add(repo._sector_model(dataset_id, sector))
                    counts["snapshot_sector_rows"] += 1
            outbox_key = f"legacy_migration:snapshot:{dataset_id}:{record['id']}"[:160]
            if not repo.get_outbox_by_idempotency_key(outbox_key):
                session.add(
                    SyncOutboxModel(
                        op_type="snapshot_ingest",
                        dataset_id=dataset_id,
                        snapshot_id=record["id"],
                        idempotency_key=outbox_key,
                        status="pending",
                    )
                )
                counts["sync_outbox"] += 1
    for dataset_id in [row[0] for row in session.execute(select(Dataset.id)).all()]:
        repo._refresh_dataset_summary(str(dataset_id))
    return counts


def _migrate_research(legacy: sqlite3.Connection, session) -> dict[str, int]:
    counts = {"backtest_runs": 0, "optimization_runs": 0, "golden_ranktrend_cases": 0}
    tables = _tables(legacy)
    if "backtest_runs" in tables:
        for row in legacy.execute("select * from backtest_runs"):
            if session.get(BacktestRun, row["id"]):
                continue
            session.add(_backtest_run_from_row(row))
            counts["backtest_runs"] += 1
    if "optimization_runs" in tables:
        for row in legacy.execute("select * from optimization_runs"):
            if session.get(OptimizationRun, row["id"]):
                continue
            session.add(_optimization_run_from_row(row))
            counts["optimization_runs"] += 1
    if "golden_ranktrend_cases" in tables:
        for row in legacy.execute("select * from golden_ranktrend_cases"):
            if session.get(GoldenRankTrendCase, row["id"]):
                continue
            session.add(_golden_case_from_row(row))
            counts["golden_ranktrend_cases"] += 1
    return counts


def _record_from_legacy(row: sqlite3.Row) -> dict[str, Any] | None:
    payload = json_loads(row["payload_json"] if "payload_json" in row.keys() else None, {})
    raw = {
        "id": row["snapshot_id"],
        "snapshotId": row["snapshot_id"],
        "type": row["type"],
        "tradingDate": row["trading_date"],
        "slotTime": row["slot_time"],
        "timestamp": row["timestamp"],
        "displayKey": row["display_key"],
        "captureMode": row["capture_mode"],
        "source": row["source"],
        "payload": payload if isinstance(payload, dict) else {},
    }
    return normalize_record(raw)


def _dataset_from_row(row: sqlite3.Row) -> Dataset:
    return Dataset(
        id=str(row["id"]),
        name=str(row["name"] or row["id"]),
        source_type=str(row["source_type"] or "legacy_split"),
        source_path=str(row["source_path"] or ""),
        db_name=str(row["db_name"] or "DragonBoardData"),
        schema_fingerprint=str(row["schema_fingerprint"] or ""),
        snapshot_count=int(row["snapshot_count"] or 0),
        frame_count=int(row["frame_count"] or 0),
        stock_row_count=int(row["stock_row_count"] or 0),
        sector_row_count=int(row["sector_row_count"] or 0),
        start_date=row["start_date"],
        end_date=row["end_date"],
        snapshot_types_json=str(row["snapshot_types_json"] or "[]"),
        metadata_json=dumps_json_field(row["metadata_json"] or "{}"),
        created_at=_parse_datetime(row["created_at"]),
    )


def _fallback_dataset(dataset_id: str, record: dict[str, Any]) -> Dataset:
    return Dataset(
        id=dataset_id,
        name=dataset_id,
        source_type="legacy_split",
        source_path="",
        db_name="DragonBoardData",
        schema_fingerprint=stable_hash({"datasetId": dataset_id, "firstRecord": record.get("id")}),
        snapshot_count=0,
        frame_count=0,
        stock_row_count=0,
        sector_row_count=0,
        start_date=record.get("tradingDate"),
        end_date=record.get("tradingDate"),
        snapshot_types_json=dumps_json_field([record.get("type")]),
        metadata_json=dumps_json_field({"source": "legacy_split_migration"}),
        created_at=datetime.utcnow(),
    )


def _backtest_run_from_row(row: sqlite3.Row) -> BacktestRun:
    return BacktestRun(
        id=str(row["id"]),
        dataset_id=str(row["dataset_id"] or ""),
        strategy_name=str(row["strategy_name"] or "rank_trend_candidate"),
        strategy_version=str(row["strategy_version"] or "0.1.0"),
        snapshot_type=str(row["snapshot_type"] or "half_hour"),
        config_hash=str(row["config_hash"] or ""),
        random_seed=int(row["random_seed"] or 0),
        status=str(row["status"] or "completed"),
        request_json=dumps_json_field(row["request_json"] or "{}"),
        result_json=dumps_json_field(row["result_json"] or "{}"),
        created_at=_parse_datetime(row["created_at"]),
    )


def _optimization_run_from_row(row: sqlite3.Row) -> OptimizationRun:
    return OptimizationRun(
        id=str(row["id"]),
        dataset_id=str(row["dataset_id"] or ""),
        strategy_name=str(row["strategy_name"] or "rank_trend_candidate"),
        method=str(row["method"] or "grid"),
        config_hash=str(row["config_hash"] or ""),
        random_seed=int(row["random_seed"] or 0),
        status=str(row["status"] or "completed"),
        request_json=dumps_json_field(row["request_json"] or "{}"),
        result_json=dumps_json_field(row["result_json"] or "{}"),
        created_at=_parse_datetime(row["created_at"]),
    )


def _golden_case_from_row(row: sqlite3.Row) -> GoldenRankTrendCase:
    return GoldenRankTrendCase(
        id=str(row["id"]),
        name=str(row["name"] or row["id"]),
        dataset_id=row["dataset_id"],
        input_json=dumps_json_field(row["input_json"] or "{}"),
        expected_json=dumps_json_field(row["expected_json"] or "{}"),
        created_at=_parse_datetime(row["created_at"]),
    )


def _exists(session, model, dataset_id: str, snapshot_id: str) -> bool:
    return bool(
        session.scalar(select(model.id).where(model.dataset_id == dataset_id, model.snapshot_id == snapshot_id).limit(1))
    )


def _row_exists(session, model, dataset_id: str, row_id: str) -> bool:
    return bool(session.scalar(select(model.id).where(model.dataset_id == dataset_id, model.row_id == row_id).limit(1)))


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute("select name from sqlite_master where type='table'").fetchall()}


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'select count(*) from "{table}"').fetchone()[0] or 0)


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass
    return datetime.utcnow()
