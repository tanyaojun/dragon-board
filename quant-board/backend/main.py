from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.data.auto_sync import auto_sync_runner, run_outbox_auto_sync_once
from backend.data.archive.auto_archive import archive_auto_runner, run_archive_auto_once
from backend.data.archive.object_store import get_object_backup_store
from backend.data.archive.service import ArchiveService
from backend.data.backup_sync import BackupSyncService
from backend.data.database import get_db, init_db, primary_status
from backend.data.dataset_service import DatasetService
from backend.data.importers import ImporterError, frame_from_record, sector_rows_from_record, stock_rows_from_record
from backend.data.migration import SnapshotMigrationService
from backend.data.models import Dataset
from backend.data.json_codec import loads_json_field
from backend.data.repository import Repository
from backend.data.schemas import (
    GoldenImportRequest,
    GoldenValidateRequest,
    ImportDatasetRequest,
    SnapshotIngestRequest,
    SnapshotJsonMigrationRequest,
)
from backend.data.supabase_backup import get_backup_client
from backend.data.theme_database import get_theme_db, init_theme_db, theme_status
from backend.data.theme_repository import ThemeRepository
from backend.data.theme_service import ThemeMigrationError, ThemeMigrationService
from backend.services import BacktestService, GoldenService, OptimizationService
from backend.settings import get_settings
from backend.utils import json_dumps, json_loads, stable_hash


app = FastAPI(
    title="QuantBoard",
    version="0.1.0",
    description="Python RankTrend 回测平台",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    init_theme_db()
    auto_sync_runner.start()
    archive_auto_runner.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await auto_sync_runner.stop()
    await archive_auto_runner.stop()


@app.get("/api/health")
def health_check(deep: bool = False, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    backup = get_backup_client()
    backup_status = {"configured": False, "connected": False, "last_error": None}
    if backup:
        backup_status = backup.deep_health() if deep else backup.health()
    return {
        "status": "ok",
        "version": "0.1.0",
        "engine": "QuantBoard",
        "default_snapshot_type": "half_hour",
        "database": {
            "primary": primary_status(),
            "theme": theme_status(),
            "backup": backup_status,
            "mode": "sqlite_primary_supabase_backup",
            "outbox": Repository(db, enable_backup=False).outbox_status() if db is not None else None,
            "autoSync": auto_sync_runner.status(),
        },
        "archive": {
            "dir": str(get_settings().archive_dir),
            "retentionTradingDays": get_settings().archive_retention_trading_days,
            "parquetCompression": get_settings().archive_parquet_compression,
            "autoArchive": archive_auto_runner.status(),
            "objectBackup": {
                "enabled": get_settings().object_backup_enabled,
                "bucketConfigured": bool(get_settings().object_backup_bucket),
                "provider": "r2",
            },
        },
    }


@app.post("/api/sync/push-backup")
def push_backup(db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return BackupSyncService(db).push_all_to_backup()


@app.post("/api/sync/pull-backup")
def pull_backup(db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return BackupSyncService(db).pull_backup_to_primary()


@app.post("/api/sync/push-outbox")
def push_outbox(limit: int | None = None, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    repo = Repository(db, enable_backup=False)
    return BackupSyncService(db).push_outbox_to_backup(repo, limit=limit or get_settings().backup_auto_sync_batch_size)


@app.post("/api/sync/auto-once")
def run_auto_sync_once(limit: int | None = None) -> dict[str, Any]:
    return run_outbox_auto_sync_once(limit)


@app.post("/api/storage/archive/auto-once")
def run_archive_auto_once_api(limit: int | None = None) -> dict[str, Any]:
    return run_archive_auto_once(limit)


@app.post("/api/sync/smoke-backup")
def smoke_backup() -> dict[str, Any]:
    backup = get_backup_client()
    if not backup:
        return {"ok": False, "configured": False, "error": "supabase backup is not configured"}
    return backup.smoke_test()


@app.post("/api/snapshots/ingest")
def ingest_snapshot(request: SnapshotIngestRequest, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        dataset, records, frames, stock_rows, sector_rows, idempotency_key = normalize_snapshot_ingest(request)
        result = Repository(db).save_snapshot_ingest(
            dataset,
            records,
            frames,
            stock_rows,
            sector_rows,
            idempotency_key=idempotency_key,
            trading_date=request.trading_date,
            source=request.source,
        )
        return {"ok": True, **result}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _parse_csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _assert_snapshot_sort(sort: str) -> None:
    if sort not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail=f"unsupported sort: {sort}")


DEFAULT_SNAPSHOT_DATASET_ID = "dragonboard_live"


def _dataset_has_snapshot_facts(dataset: Dataset | None) -> bool:
    if not dataset:
        return False
    return any(
        int(value or 0) > 0
        for value in (
            dataset.frame_count,
            dataset.snapshot_count,
            dataset.stock_row_count,
            dataset.sector_row_count,
        )
    )


def _latest_snapshot_dataset(repo: Repository) -> Dataset | None:
    candidates = [item for item in repo.list_datasets() if _dataset_has_snapshot_facts(item)]
    return candidates[0] if candidates else None


def _resolve_snapshot_dataset(
    repo: Repository,
    dataset_id: str | None,
    *,
    allow_default_fallback: bool = False,
) -> tuple[str, Dataset]:
    requested_dataset_id = dataset_id.strip() if isinstance(dataset_id, str) and dataset_id.strip() else None
    resolved_dataset_id = requested_dataset_id or DEFAULT_SNAPSHOT_DATASET_ID
    dataset = repo.get_dataset(resolved_dataset_id)
    should_try_default_fallback = requested_dataset_id is None or (
        allow_default_fallback and requested_dataset_id == DEFAULT_SNAPSHOT_DATASET_ID
    )
    if should_try_default_fallback and (not dataset or not _dataset_has_snapshot_facts(dataset)):
        dataset = _latest_snapshot_dataset(repo) or dataset
        resolved_dataset_id = dataset.id if dataset else resolved_dataset_id
    if not dataset:
        raise HTTPException(status_code=404, detail=f"dataset not found: {resolved_dataset_id}")
    return resolved_dataset_id, dataset


@app.get("/api/snapshots/frames")
def list_snapshot_frames(
    dataset_id: str | None = None,
    snapshot_type: str = "half_hour",
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    sort: str = "asc",
    limit: int | None = None,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    if snapshot_type not in {"quarter_hour", "half_hour", "hourly", "daily"}:
        raise HTTPException(status_code=400, detail=f"unsupported snapshot_type: {snapshot_type}")
    _assert_snapshot_sort(sort)
    start = trading_date or start_date
    end = trading_date or end_date
    capture_modes = _parse_csv(allowed_capture_modes)
    repo = Repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    frames = repo.load_frame_bundles(
        resolved_dataset_id,
        snapshot_type=snapshot_type,
        start_date=start,
        end_date=end,
        before_trading_date=before_trading_date,
        allowed_capture_modes=capture_modes,
        exclude_restored=exclude_restored,
        limit=limit,
        sort=sort,
    )
    return {
        "ok": True,
        "dataset": Repository.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "snapshotType": snapshot_type,
        "frames": frames,
        "count": len(frames),
        "source": "sqlite",
    }


@app.get("/api/snapshots/records")
def list_snapshot_records(
    dataset_id: str | None = None,
    snapshot_type: str | None = None,
    types: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    sort: str = "desc",
    limit: int | None = None,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    _assert_snapshot_sort(sort)
    repo = Repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    records = repo.list_snapshot_records(
        resolved_dataset_id,
        snapshot_type=snapshot_type,
        snapshot_types=_parse_csv(types),
        trading_date=trading_date,
        start_date=start_date,
        end_date=end_date,
        before_trading_date=before_trading_date,
        allowed_capture_modes=_parse_csv(allowed_capture_modes),
        exclude_restored=exclude_restored,
        limit=limit,
        sort=sort,
    )
    return {
        "ok": True,
        "dataset": Repository.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "records": records,
        "count": len(records),
        "source": "sqlite",
    }


@app.get("/api/snapshots/records/{snapshot_id}")
def get_snapshot_record(
    snapshot_id: str,
    dataset_id: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    repo = Repository(db, enable_backup=False)
    resolved_dataset_id = dataset_id
    dataset: Dataset | None = None
    if dataset_id:
        resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    record = repo.get_snapshot_record(
        snapshot_id,
        dataset_id=resolved_dataset_id,
        allowed_capture_modes=_parse_csv(allowed_capture_modes),
        exclude_restored=exclude_restored,
    )
    if not record:
        raise HTTPException(status_code=404, detail=f"snapshot not found: {snapshot_id}")
    if dataset is None:
        resolved_dataset_id = "dragonboard_live"
        dataset = repo.get_dataset(resolved_dataset_id)
        if not dataset:
            resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, None)
    return {
        "ok": True,
        "dataset": Repository.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "record": record,
        "source": "sqlite",
    }


@app.get("/api/snapshots/stock-rows")
def list_snapshot_stock_rows(
    dataset_id: str | None = None,
    snapshot_id: str | None = None,
    snapshot_type: str | None = None,
    types: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    code: str | None = None,
    codes: str | None = None,
    slot_time: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    sort: str = "desc",
    limit: int | None = None,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    _assert_snapshot_sort(sort)
    repo = Repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    result = repo.list_snapshot_stock_rows(
        resolved_dataset_id,
        snapshot_id=snapshot_id,
        snapshot_type=snapshot_type,
        snapshot_types=_parse_csv(types),
        trading_date=trading_date,
        start_date=start_date,
        end_date=end_date,
        before_trading_date=before_trading_date,
        code=code,
        codes=_parse_csv(codes),
        slot_time=slot_time,
        allowed_capture_modes=_parse_csv(allowed_capture_modes),
        exclude_restored=exclude_restored,
        limit=limit,
        sort=sort,
    )
    return {
        "ok": True,
        "dataset": Repository.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "rows": result["rows"],
        "count": len(result["rows"]),
        "source": result["source"],
    }


@app.get("/api/snapshots/sector-rows")
def list_snapshot_sector_rows(
    dataset_id: str | None = None,
    snapshot_id: str | None = None,
    snapshot_type: str | None = None,
    types: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    entity_type: str | None = None,
    entity_types: str | None = None,
    entity_key: str | None = None,
    entity_keys: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    sort: str = "desc",
    limit: int | None = None,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    _assert_snapshot_sort(sort)
    repo = Repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    result = repo.list_snapshot_sector_rows(
        resolved_dataset_id,
        snapshot_id=snapshot_id,
        snapshot_type=snapshot_type,
        snapshot_types=_parse_csv(types),
        trading_date=trading_date,
        start_date=start_date,
        end_date=end_date,
        before_trading_date=before_trading_date,
        entity_type=entity_type,
        entity_types=_parse_csv(entity_types),
        entity_key=entity_key,
        entity_keys=_parse_csv(entity_keys),
        allowed_capture_modes=_parse_csv(allowed_capture_modes),
        exclude_restored=exclude_restored,
        limit=limit,
        sort=sort,
    )
    return {
        "ok": True,
        "dataset": Repository.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "rows": result["rows"],
        "count": len(result["rows"]),
        "source": result["source"],
    }


@app.get("/api/snapshots/counts")
def get_snapshot_counts(
    dataset_id: str | None = None,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    repo = Repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    counts = repo.snapshot_table_counts(resolved_dataset_id)
    return {
        "ok": True,
        "dataset": Repository.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "counts": counts,
        "source": "sqlite",
    }


@app.post("/api/storage/archive/snapshots/preview")
def preview_snapshot_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).archive_snapshots(
        dataset_id=str(payload.get("datasetId") or payload.get("dataset_id") or "dragonboard_live"),
        snapshot_type=str(payload.get("snapshotType") or payload.get("snapshot_type") or "half_hour"),
        before_trading_date=str(payload.get("beforeTradingDate") or payload.get("before_trading_date") or ""),
        dry_run=True,
        max_partitions=payload.get("maxPartitions") or payload.get("max_partitions"),
    )


@app.post("/api/storage/archive/snapshots")
def archive_snapshots(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).archive_snapshots(
        dataset_id=str(payload.get("datasetId") or payload.get("dataset_id") or "dragonboard_live"),
        snapshot_type=str(payload.get("snapshotType") or payload.get("snapshot_type") or "half_hour"),
        before_trading_date=str(payload.get("beforeTradingDate") or payload.get("before_trading_date") or ""),
        apply=True,
        max_partitions=payload.get("maxPartitions") or payload.get("max_partitions"),
    )


@app.post("/api/storage/archive/research/preview")
def preview_research_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).archive_research(
        run_id=payload.get("runId") or payload.get("run_id"),
        older_than_days=int(payload.get("olderThanDays") or payload.get("older_than_days") or 30),
        keep_latest_per_group=int(payload.get("keepLatestPerGroup") or payload.get("keep_latest_per_group") or 10),
        dry_run=True,
    )


@app.post("/api/storage/archive/research")
def archive_research(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).archive_research(
        run_id=payload.get("runId") or payload.get("run_id"),
        older_than_days=int(payload.get("olderThanDays") or payload.get("older_than_days") or 30),
        keep_latest_per_group=int(payload.get("keepLatestPerGroup") or payload.get("keep_latest_per_group") or 10),
        apply=True,
    )


@app.get("/api/storage/archive/manifests")
def list_archive_manifests(scope: str | None = None, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    manifests = ArchiveService(db).list_manifests(scope=scope)
    return {"ok": True, "manifests": manifests, "count": len(manifests)}


@app.post("/api/storage/archive/verify")
def verify_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    archive_id = str(payload.get("archiveId") or payload.get("archive_id") or "")
    manifest = ArchiveService(db).get_manifest(archive_id)
    return {"ok": bool(manifest), "archiveId": archive_id, "status": manifest.status if manifest else "missing"}


@app.post("/api/storage/archive/restore")
def restore_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).restore_archive(
        str(payload.get("archiveId") or payload.get("archive_id") or ""),
        dry_run=bool(payload.get("dryRun") or payload.get("dry_run")),
        apply=bool(payload.get("apply")),
    )


@app.post("/api/storage/archive/smoke-object-backup")
def smoke_object_backup() -> dict[str, Any]:
    store = get_object_backup_store()
    if not store:
        return {"ok": False, "configured": False, "error": "object backup bucket is not configured"}
    return store.smoke_test()


@app.post("/api/storage/archive/push-backup")
def push_archive_backup(limit: int | None = None, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).push_archive_backup(limit=limit)


@app.post("/api/storage/archive/pull-backup")
def pull_archive_backup(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).pull_archive_backup(
        str(payload.get("archiveId") or payload.get("archive_id") or ""),
        dry_run=bool(payload.get("dryRun") or payload.get("dry_run")),
        apply=bool(payload.get("apply")),
    )


@app.post("/api/migrations/snapshots/import-json")
def import_snapshot_json_migration(
    request: SnapshotJsonMigrationRequest,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    try:
        return SnapshotMigrationService(db).import_json(request.model_dump(by_alias=True))
    except (ImporterError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/migrations/themes/import-json")
def import_theme_json_migration(
    payload: dict[str, Any],
    db: Session | None = Depends(get_theme_db),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    try:
        return ThemeMigrationService(db).import_mapping(payload)
    except ThemeMigrationError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error


@app.post("/api/migrations/themes/verify-json")
def verify_theme_json_migration(
    payload: dict[str, Any],
    db: Session | None = Depends(get_theme_db),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    try:
        return ThemeMigrationService(db).verify_mapping(payload)
    except ThemeMigrationError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error


@app.get("/api/themes/mapping")
def get_theme_mapping(db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    mapping = ThemeRepository(db).get_mapping()
    return {"ok": True, "mapping": mapping, "source": "sqlite"}


@app.get("/api/themes/stocks/{theme_id}")
def get_theme_stocks(theme_id: str, db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    return ThemeRepository(db).get_theme_stocks(theme_id)


@app.get("/api/themes/stocks/by-code/{code}")
def get_stock_themes(code: str, db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    return ThemeRepository(db).get_stock_themes(code)


@app.get("/api/themes/counts")
def get_theme_counts(db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    return {"ok": True, "counts": ThemeRepository(db).counts(), "source": "sqlite"}


def normalize_snapshot_ingest(
    request: SnapshotIngestRequest,
) -> tuple[Dataset, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str]:
    bundle = request.bundle
    if not isinstance(bundle, dict):
        raise ValueError("bundle is required")

    records = [item for item in bundle.get("items") or bundle.get("records") or [] if isinstance(item, dict)]
    if not records:
        raise ValueError("bundle.items is required")
    frames = [item for item in bundle.get("frames") or [] if isinstance(item, dict)]
    stock_rows = [item for item in bundle.get("stockRows") or bundle.get("stock_rows") or [] if isinstance(item, dict)]
    sector_rows = [item for item in bundle.get("sectorRows") or bundle.get("sector_rows") or [] if isinstance(item, dict)]

    if not frames:
        frames = [frame_from_record(record) for record in records if str(record.get("type") or "") != "five_minute"]
    if not stock_rows:
        for record in records:
            stock_rows.extend(stock_rows_from_record(record))
    if not sector_rows:
        for record in records:
            sector_rows.extend(sector_rows_from_record(record))

    snapshot_ids = {str(record.get("id") or record.get("snapshotId") or "") for record in records}
    snapshot_ids.update(str(frame.get("snapshotId") or frame.get("id") or "") for frame in frames)
    snapshot_ids.discard("")
    if not snapshot_ids:
        raise ValueError("snapshot id is required")

    trading_dates = sorted(
        {
            str(item.get("tradingDate") or "")
            for item in [*records, *frames]
            if isinstance(item, dict) and item.get("tradingDate")
        }
    )
    snapshot_types = sorted(
        {
            str(item.get("type") or "")
            for item in [*records, *frames]
            if isinstance(item, dict) and item.get("type")
        }
    )
    dataset_id = request.dataset_id or "dragonboard_live"
    dataset = Dataset(
        id=dataset_id,
        name="DragonBoard Live Snapshots" if dataset_id == "dragonboard_live" else dataset_id,
        source_type="dragon_board_runtime",
        source_path="",
        db_name="DragonBoardData",
        schema_fingerprint=stable_hash({"snapshotIds": sorted(snapshot_ids), "source": request.source}),
        snapshot_count=len(records),
        frame_count=len(frames),
        stock_row_count=len(stock_rows),
        sector_row_count=len(sector_rows),
        start_date=trading_dates[0] if trading_dates else request.trading_date,
        end_date=trading_dates[-1] if trading_dates else request.trading_date,
        snapshot_types_json=json_dumps(snapshot_types),
        metadata_json=json_dumps({"source": request.source, "ingest": "snapshots_ingest"}),
        created_at=datetime.utcnow(),
    )
    idempotency_key = request.idempotency_key or stable_hash(
        {
            "datasetId": dataset_id,
            "records": records,
            "frames": frames,
            "stockRows": stock_rows,
            "sectorRows": sector_rows,
        }
    )
    return dataset, records, frames, stock_rows, sector_rows, idempotency_key


@app.get("/api/datasets")
def list_datasets(db: Session | None = Depends(get_db)) -> list[dict[str, Any]]:
    return DatasetService(db).list_datasets()


@app.get("/api/datasets/{dataset_id}")
def get_dataset(dataset_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    dataset = DatasetService(db).get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
    return dataset


@app.post("/api/datasets/upload")
async def upload_dataset(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    content = payload.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    try:
        settings = get_settings()
        safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(payload.get("filename") or "upload.json"))
        path = settings.staging_dir / f"upload_{safe_name}"
        from backend.utils import write_json_file

        write_json_file(path, content)
        request = ImportDatasetRequest(
            source_type="json_bundle",
            source_path=str(path),
            name=payload.get("name") or safe_name,
            snapshot_types=payload.get("snapshotTypes") or ["half_hour"],
            dry_run=bool(payload.get("dryRun")),
        )
        return DatasetService(db).import_dataset(request)
    except (ImporterError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def normalize_import_payload(payload: dict[str, Any]) -> ImportDatasetRequest:
    if "sourceType" in payload:
        source_type = payload.get("sourceType")
        if source_type == "sqlite":
            payload = {**payload, "sourceType": "sqlite_snapshots"}
        # The lightweight frontend previews browser IndexedDB and posts sampled rows.
        # Treat that as a JSON bundle import path so the backend can persist the sample.
        if payload.get("sourceType") == "indexeddb":
            records = payload.get("records") or []
            if not records:
                raise ImporterError(
                    "当前页面没有读到 IndexedDB 样本。浏览器 IndexedDB 受 origin 隔离，"
                    "请改用 browser_bridge、leveldb 或 json_bundle 导入 DragonBoard 数据。"
                )
            preview = payload.get("preview") or {}
            options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
            return ImportDatasetRequest(
                source_type="json_bundle",
                source_path=_write_inline_import_bundle(payload.get("name") or "frontend-import", records, preview),
                name=payload.get("name"),
                snapshot_types=payload.get("snapshotTypes") or ["half_hour", "quarter_hour"],
                dry_run=bool(options.get("dryRun")),
            )
        if source_type == "json":
            return ImportDatasetRequest(
                source_type="json_bundle",
                source_path=payload.get("sourcePath") or payload.get("path"),
                name=payload.get("name"),
                snapshot_types=payload.get("snapshotTypes") or ["half_hour"],
                dry_run=bool(payload.get("dryRun")),
            )
    return ImportDatasetRequest(**payload)


def _write_inline_import_bundle(name: str, records: list[Any], preview: dict[str, Any]) -> str:
    from backend.utils import write_json_file

    settings = get_settings()
    path = settings.staging_dir / f"inline_{name.replace(' ', '_')}.json"
    normalized = []
    for index, record in enumerate(records):
        if isinstance(record, dict):
            value = record.get("value") if isinstance(record.get("value"), dict) else record
            normalized.append(value)
    write_json_file(path, {"metadata": {"preview": preview, "source": "frontend_inline"}, "records": normalized})
    return str(path)


@app.post("/api/datasets/import")
def import_dataset(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        request = normalize_import_payload(payload)
        dataset = DatasetService(db).import_dataset(request)
        return dataset
    except (ImporterError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/backtests/rank-trend")
def run_ranktrend_backtest(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).run_ranktrend(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/backtests/theme-trend")
def run_theme_trend_backtest(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).run_theme_trend(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/backtests/theme-confluence")
def run_theme_confluence_backtest(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).run_theme_confluence(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _backtest_not_found(run_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "backtest_run_not_found", "runId": run_id})


def _structured_bad_request(error: ValueError) -> HTTPException:
    detail = error.args[0] if error.args and isinstance(error.args[0], dict) else str(error)
    return HTTPException(status_code=400, detail=detail)


@app.post("/api/backtests/compare")
def compare_backtests(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    run_ids = payload.get("run_ids") or payload.get("runIds") or []
    if not isinstance(run_ids, list) or not run_ids:
        raise HTTPException(status_code=400, detail={"code": "invalid_backtest_compare_request", "field": "run_ids"})
    metrics = payload.get("metrics")
    if metrics is not None and not isinstance(metrics, list):
        raise HTTPException(status_code=400, detail={"code": "invalid_backtest_compare_request", "field": "metrics"})
    try:
        return BacktestService(db).compare_runs([str(item) for item in run_ids], [str(item) for item in metrics] if metrics else None)
    except LookupError as error:
        raise _backtest_not_found(str(error.args[0])) from error
    except ValueError as error:
        raise _structured_bad_request(error) from error


@app.get("/api/backtests/{run_id}/trades")
def get_backtest_trades(
    run_id: str,
    limit: int = 100,
    offset: int = 0,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = BacktestService(db).get_trades(run_id, limit=limit, offset=offset)
    except ValueError as error:
        raise _structured_bad_request(error) from error
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/{run_id}/equity")
def get_backtest_equity(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = BacktestService(db).get_equity(run_id)
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/{run_id}/signals")
def get_backtest_signals(
    run_id: str,
    tier: str | None = None,
    regime: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = BacktestService(db).get_signals(run_id, limit=limit, offset=offset, tier=tier, regime=regime)
    except ValueError as error:
        raise _structured_bad_request(error) from error
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/{run_id}/quality")
def get_backtest_quality(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = BacktestService(db).get_quality(run_id)
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.delete("/api/backtests/{run_id}")
def delete_backtest(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = BacktestService(db).delete_run(run_id)
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/{run_id}")
def get_backtest(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = BacktestService(db).get_run(run_id)
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/{run_id}/report")
def get_backtest_report(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return get_backtest(run_id, db)


@app.get("/api/storage/research-summary")
def get_research_storage_summary(db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return BacktestService(db).research_storage_summary()


@app.post("/api/storage/research-cleanup-preview")
def preview_research_cleanup(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).cleanup_research(payload, apply=False)
    except ValueError as error:
        raise _structured_bad_request(error) from error


@app.post("/api/storage/research-cleanup")
def cleanup_research(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).cleanup_research(payload, apply=True)
    except ValueError as error:
        raise _structured_bad_request(error) from error


@app.post("/api/optimizations/rank-trend")
def run_ranktrend_optimization(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return OptimizationService(db).run_ranktrend(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/optimizations/theme-trend")
def run_theme_trend_optimization(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return OptimizationService(db).run_theme_trend(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/optimizations/theme-confluence")
def run_theme_confluence_optimization(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return OptimizationService(db).run_theme_confluence(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/optimizations/{run_id}")
def get_optimization(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = OptimizationService(db).get_run(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"optimization run not found: {run_id}")
    return result


@app.get("/api/research/theme-summary")
def get_theme_research_summary(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    """Dragon Board 消费的题材研究摘要。QuantBoard 后端不可用时前端显示"不可用"。"""
    try:
        repo = Repository(db)
        frames = repo.load_frame_bundles(dataset_id, snapshot_type=snapshot_type)
        if not frames or len(frames) < 2:
            return {"available": False, "reason": "insufficient_frames", "frameCount": len(frames) if frames else 0}

        # 函数内导入避免与 FastAPI startup 事件中的 DB 初始化形成循环依赖
        from backend.analysis.theme_trend import ThemeTrendPythonEngine
        result = ThemeTrendPythonEngine().replay_sequence(frames)
        factors = result.get("factors") or []
        quality = result.get("qualityReport") or {}

        lifecycle_dist: dict[str, int] = {}
        for f in factors:
            lc = str(f.get("lifecycle") or "neutral")
            lifecycle_dist[lc] = lifecycle_dist.get(lc, 0) + 1

        mainline_themes = [
            {"themeId": f.get("themeId"), "themeName": f.get("themeName"), "heatScore": f.get("heatScore")}
            for f in factors
            if f.get("lifecycle") == "mainline"
        ][:10]

        crowding_themes = [
            {"themeId": f.get("themeId"), "themeName": f.get("themeName"), "crowdingRisk": f.get("crowdingRisk")}
            for f in factors
            if f.get("lifecycle") == "crowded"
        ][:5]

        return {
            "available": True,
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "frameCount": len(frames),
            "lastTradingDate": str(frames[-1].get("tradingDate") or ""),
            "lifecycleDistribution": lifecycle_dist,
            "mainlineThemes": mainline_themes,
            "crowdingAlerts": crowding_themes,
            "qualityPassed": not quality.get("blocked", False),
            "researchGrade": "degraded" if quality.get("warnings") else "research_ready",
            "themeCount": len({f.get("themeId") for f in factors if f.get("themeId")}),
            "signalCount": len(factors),
        }
    except Exception as exc:
        return {"available": False, "reason": f"backend_error: {str(exc)[:200]}"}


@app.get("/api/reports/theme-trend/{run_id}")
def get_theme_trend_report(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    """主题研究报告：同时查询 optimization_runs 和 backtest_runs。

    bt_* 前缀的回测 ID 从 backtest_runs.result_json 提取 themeTrend 段；
    opt_* 前缀的优化 ID 从 optimization_runs.result_json.trialList[0] 提取 engineFactors。
    """
    bt_service = BacktestService(db)
    opt_service = OptimizationService(db)

    factors: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    execution_signals: list[dict[str, Any]] = []
    strategy_name = ""
    dataset_id = ""

    # 优先按 optimization_runs 查询
    opt_run = opt_service.repo.get_optimization_run(run_id)
    if opt_run:
        raw = loads_json_field(opt_run.result_json, {})
        trial_list = raw.get("trialList") or []
        best_trial = trial_list[0] if trial_list else {}
        factors = best_trial.get("engineFactors") or []
        strategy_name = opt_run.strategy_name
        dataset_id = opt_run.dataset_id or ""
    else:
        # 回退到 backtest_runs
        bt_run = bt_service.repo.get_backtest_run(run_id)
        if not bt_run:
            raise HTTPException(status_code=404, detail={"code": "run_not_found", "runId": run_id})
        result = loads_json_field(bt_run.result_json, {})
        tt = result.get("themeTrend") or {}
        factors = tt.get("factors") or tt.get("signals") or result.get("signals") or []
        trades = result.get("trades") or ((result.get("tradeSimulation") or {}).get("trades")) or []
        if not trades:
            trades = bt_service.repo.get_backtest_trades(run_id)
        execution_signals = result.get("executionSignals") or []
        strategy_name = bt_run.strategy_name
        dataset_id = bt_run.dataset_id

    lifecycle_dist: dict[str, int] = {}
    for f in factors:
        lc = str(f.get("lifecycle") or "neutral")
        lifecycle_dist[lc] = lifecycle_dist.get(lc, 0) + 1

    signal_dist: dict[str, int] = {}
    for f in factors:
        sig = str(f.get("signal") or "watch")
        signal_dist[sig] = signal_dist.get(sig, 0) + 1

    crowding_events = [f for f in factors if f.get("lifecycle") == "crowded"]
    transitions = [f for f in factors if f.get("lifecycleTransition")]
    trade_report = _build_theme_trade_report(trades, execution_signals)

    return {
        "runId": run_id,
        "strategyName": strategy_name,
        "datasetId": dataset_id,
        "lifecycleDistribution": lifecycle_dist,
        "signalDistribution": signal_dist,
        "crowdingEventCount": len(crowding_events),
        "lifecycleTransitionCount": len(transitions),
        "recentTransitions": transitions[:20],
        "themeCount": len({f.get("themeId") for f in factors if f.get("themeId")}),
        "totalFactorCount": len(factors),
        **trade_report,
    }


def _build_theme_trade_report(trades: list[dict[str, Any]], execution_signals: list[dict[str, Any]]) -> dict[str, Any]:
    signal_by_entry = {
        (str(item.get("snapshotId") or ""), str(item.get("code") or "")): item
        for item in execution_signals
        if item.get("code")
    }

    def enrich(trade: dict[str, Any]) -> dict[str, Any]:
        signal = signal_by_entry.get((str(trade.get("entrySnapshotId") or ""), str(trade.get("code") or "")), {})
        return {
            **trade,
            "lifecycle": trade.get("stage") or signal.get("stage") or "neutral",
            "themeName": signal.get("mainTheme") or trade.get("themeName") or "",
            "role": signal.get("themeRole") or trade.get("themeRole") or "",
            "candidateTier": trade.get("candidateTier") or signal.get("candidateTier") or "",
            "crowdingTriggered": (
                trade.get("candidateTier") == "C_CROWDED"
                or signal.get("candidateTier") == "C_CROWDED"
                or str(signal.get("stage") or "") in {"crowded", "divergence"}
                or any(str(flag).startswith("crowding:") for flag in (signal.get("themeRiskFlags") or []))
            ),
        }

    enriched = [enrich(trade) for trade in trades]

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(rows)
        total_profit = round(sum(float(row.get("profit") or 0) for row in rows), 2)
        total_return = round(sum(float(row.get("netReturn") or 0) for row in rows), 4)
        wins = sum(1 for row in rows if float(row.get("netReturn") or 0) > 0)
        return {
            "tradeCount": count,
            "winRate": round(wins / count, 4) if count else 0,
            "avgNetReturn": round(total_return / count, 4) if count else 0,
            "totalNetReturn": total_return,
            "totalProfit": total_profit,
        }

    def group_by(field: str) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in enriched:
            key = str(row.get(field) or "unknown")
            grouped.setdefault(key, []).append(row)
        return grouped

    lifecycle_returns = {
        key: summarize(rows)
        for key, rows in sorted(group_by("lifecycle").items())
    }
    theme_diagnostics = [
        {"themeName": key, **summarize(rows)}
        for key, rows in sorted(group_by("themeName").items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    tier_diagnostics = [
        {"candidateTier": key, **summarize(rows)}
        for key, rows in sorted(group_by("candidateTier").items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    role_diagnostics = [
        {"role": key, **summarize(rows)}
        for key, rows in sorted(group_by("role").items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    crowded_rows = [row for row in enriched if row.get("crowdingTriggered")]

    return {
        "lifecycleReturnDistribution": lifecycle_returns,
        "themeTradeDiagnostics": theme_diagnostics,
        "candidateTierDiagnostics": tier_diagnostics,
        "roleDiagnostics": role_diagnostics,
        "crowdingRiskDecay": {
            "triggeredTradeCount": len(crowded_rows),
            **summarize(crowded_rows),
        },
    }


@app.post("/api/golden/import")
def import_golden(request: GoldenImportRequest, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return GoldenService(db).import_case(request.model_dump(by_alias=True))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/golden/baseline")
def create_golden_baseline(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return GoldenService(db).create_baseline(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/golden/validate")
def validate_golden(request: GoldenValidateRequest, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return GoldenService(db).validate(request.model_dump(by_alias=True))


settings = get_settings()
frontend_dist = settings.frontend_dir / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="quant-assets")


@app.get("/", response_model=None)
def index():
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "QuantBoard API is running", "docs": "/docs"}
