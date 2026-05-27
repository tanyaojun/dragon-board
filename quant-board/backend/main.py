from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.api.journal_routes import router as journal_router
from backend.data.auto_sync import auto_sync_runner, run_outbox_auto_sync_once
from backend.data.archive.auto_archive import archive_auto_runner, run_archive_auto_once
from backend.data.archive.object_store import get_object_backup_store
from backend.data.archive.service import ArchiveService
from backend.data.backup_retention import backup_retention_runner, run_backup_retention_once
from backend.data.backup_sync import BackupSyncService
from backend.data.database import ResearchSessionLocal, get_db, init_db, primary_status
from backend.data.dataset_service import DatasetService
from backend.data.importers import ImporterError, frame_from_record, sector_rows_from_record, stock_rows_from_record
from backend.data.migration import SnapshotMigrationService
from backend.data.models import Dataset
from backend.data.json_codec import loads_json_field
from backend.data.repository import Repository
from backend.data.repository_factory import create_repository, get_runtime_mongodb_database, storage_source_label
from backend.data.schemas import (
    GoldenImportRequest,
    GoldenValidateRequest,
    ImportDatasetRequest,
    SnapshotIngestRequest,
    SnapshotJsonMigrationRequest,
)
from backend.data.stock_name_repository import STOCK_NAMES_VERSION, StockNameRepository
from backend.data import snapshot_cache
from backend.data.supabase_backup import get_backup_client
from backend.data.theme_database import get_theme_db, init_theme_db, theme_status
from backend.data.mongo_theme_repository import MongoThemeRepository
from backend.data.theme_repository import ThemeRepository
from backend.data.theme_service import ThemeMigrationError, ThemeMigrationService
from backend.operations.schedule import run_after_market_once
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

app.include_router(journal_router)

@app.on_event("startup")
def on_startup() -> None:
    if get_settings().storage_backend == "mongodb":
        return
    init_db()
    init_theme_db()
    auto_sync_runner.start()
    archive_auto_runner.start()
    backup_retention_runner.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if get_settings().storage_backend == "mongodb":
        return
    await auto_sync_runner.stop()
    await archive_auto_runner.stop()
    await backup_retention_runner.stop()


@app.get("/api/health")
def health_check(deep: bool = False, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    backup_status = {"configured": False, "connected": False, "last_error": None}
    backup = None if storage_source_label() == "mongodb" else get_backup_client()
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
            "mode": "mongodb_primary" if storage_source_label() == "mongodb" else "sqlite_primary_supabase_backup",
            "outbox": None if storage_source_label() == "mongodb" else (Repository(db, enable_backup=False).outbox_status() if db is not None else None),
            "autoSync": auto_sync_runner.status(),
            "backupRetention": backup_retention_runner.status(),
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


def get_stock_name_repository() -> StockNameRepository:
    return StockNameRepository(get_runtime_mongodb_database())


def get_theme_repository(db: Session | None = None) -> ThemeRepository | MongoThemeRepository:
    if storage_source_label() == "mongodb":
        return MongoThemeRepository(get_runtime_mongodb_database())
    if db is None:
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    return ThemeRepository(db)


@app.get("/api/stocks/names")
def list_stock_names(
    market: str | None = None,
    type: str | None = None,
    active: bool | None = True,
) -> dict[str, Any]:
    try:
        stocks = get_stock_name_repository().list_names(market=market, type=type, active=active)
        return {
            "ok": True,
            "source": "mongodb",
            "version": STOCK_NAMES_VERSION,
            "stocks": stocks,
            "count": len(stocks),
        }
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/stocks/names/{code}")
def get_stock_name(code: str, active: bool | None = True) -> dict[str, Any]:
    try:
        stock = get_stock_name_repository().get_by_code(code, active=active)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if not stock:
        raise HTTPException(status_code=404, detail=f"stock not found: {code}")
    return {
        "ok": True,
        "source": "mongodb",
        "version": STOCK_NAMES_VERSION,
        "stock": stock,
    }


@app.get("/api/stocks/search")
def search_stock_names(
    q: str,
    market: str | None = None,
    type: str | None = None,
    active: bool | None = True,
    limit: int = 50,
) -> dict[str, Any]:
    try:
        stocks = get_stock_name_repository().search(q, market=market, type=type, active=active, limit=limit)
        return {
            "ok": True,
            "source": "mongodb",
            "version": STOCK_NAMES_VERSION,
            "stocks": stocks,
            "count": len(stocks),
        }
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/sync/push-backup")
def push_backup(full_history: bool = False, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="Supabase backup is disabled after MongoDB migration")
    return BackupSyncService(db).push_all_to_backup(full_history=full_history)


@app.post("/api/sync/pull-backup")
def pull_backup(db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="Supabase backup is disabled after MongoDB migration")
    return BackupSyncService(db).pull_backup_to_primary()


@app.post("/api/sync/push-outbox")
def push_outbox(limit: int | None = None, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="sync_outbox is disabled after MongoDB migration")
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    repo = Repository(db, enable_backup=False)
    return BackupSyncService(db).push_outbox_to_backup(repo, limit=limit or get_settings().backup_auto_sync_batch_size)


@app.post("/api/sync/auto-once")
def run_auto_sync_once(limit: int | None = None) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="sync_outbox auto sync is disabled after MongoDB migration")
    return run_outbox_auto_sync_once(limit)


@app.post("/api/sync/prune-backup")
def prune_backup(dry_run: bool = False) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="Supabase retention is disabled after MongoDB migration")
    return run_backup_retention_once(dry_run=dry_run)


@app.post("/api/storage/archive/auto-once")
def run_archive_auto_once_api(limit: int | None = None) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="SQLite archive auto cleanup is disabled after MongoDB migration")
    return run_archive_auto_once(limit)


@app.post("/api/storage/archive/backup-snapshot-day")
def backup_snapshot_day(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    trading_date: str | None = None,
    dry_run: bool = False,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="SQLite snapshot-day backup endpoint is disabled after MongoDB migration")
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    service = ArchiveService(db)
    target_date = trading_date or service.latest_snapshot_trading_date(
        dataset_id=dataset_id,
        snapshot_type=snapshot_type,
    )
    if not target_date:
        return {
            "ok": False,
            "error": {
                "code": "no_snapshot_trading_date",
                "datasetId": dataset_id,
                "snapshotType": snapshot_type,
            },
        }
    return service.backup_snapshot_day_to_object(
        dataset_id=dataset_id,
        snapshot_type=snapshot_type,
        trading_date=target_date,
        dry_run=dry_run,
    )


def _reject_sqlite_archive_for_mongodb() -> None:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="SQLite archive endpoints are disabled after MongoDB migration")


@app.post("/api/operations/after-market-once")
def run_after_market_once_api(
    archive_limit: int | None = None,
    backup_limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="SQLite after-market archive workflow is disabled after MongoDB migration")
    return run_after_market_once(archive_limit=archive_limit, backup_limit=backup_limit, dry_run=dry_run)


@app.post("/api/sync/smoke-backup")
def smoke_backup() -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="Supabase backup is disabled after MongoDB migration")
    backup = get_backup_client()
    if not backup:
        return {"ok": False, "configured": False, "error": "supabase backup is not configured"}
    return backup.smoke_test()


@app.post("/api/snapshots/ingest")
def ingest_snapshot(request: SnapshotIngestRequest, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        dataset, records, frames, stock_rows, sector_rows, idempotency_key = normalize_snapshot_ingest(request)
        result = create_repository(db).save_snapshot_ingest(
            dataset,
            records,
            frames,
            stock_rows,
            sector_rows,
            idempotency_key=idempotency_key,
            trading_date=request.trading_date,
            source=request.source,
        )
        _invalidate_snapshot_cache_after_ingest(
            dataset_id=dataset.id,
            records=records,
            frames=frames,
            stock_rows=stock_rows,
            sector_rows=sector_rows,
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
    if not dataset:
        raise HTTPException(status_code=404, detail=f"dataset not found: {resolved_dataset_id}")
    if not _dataset_has_snapshot_facts(dataset):
        raise HTTPException(status_code=404, detail=f"dataset has no snapshot facts: {resolved_dataset_id}")
    return resolved_dataset_id, dataset


def _snapshot_cache_builder() -> snapshot_cache.SnapshotCacheKeyBuilder:
    return snapshot_cache.SnapshotCacheKeyBuilder(prefix=get_settings().redis_key_prefix)


def _cached_snapshot_response(
    resource: str,
    *,
    resolved_dataset_id: str,
    params: dict[str, Any],
    snapshot_type: str | None = None,
    trading_date: str | None = None,
    snapshot_ids: list[str] | None = None,
    loader,
) -> dict[str, Any]:
    cache_key = _snapshot_cache_builder().response_key(
        resource,
        resolved_dataset_id=resolved_dataset_id,
        params=params,
    )
    cache = snapshot_cache.get_snapshot_redis_cache()
    cached = cache.get_response(cache_key)
    if cached is not None:
        return cached

    response = loader()
    response = {**response, "cache": {"hit": False, "store": storage_source_label()}}
    cache.set_response(cache_key, response)
    cache.register_dependencies(
        cache_key,
        snapshot_cache.build_snapshot_cache_index_keys(
            prefix=get_settings().redis_key_prefix,
            dataset_id=resolved_dataset_id,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            snapshot_ids=snapshot_ids or [],
        ),
    )
    return response


def _invalidate_snapshot_cache_after_ingest(
    *,
    dataset_id: str,
    records: list[Any],
    frames: list[Any],
    stock_rows: list[Any],
    sector_rows: list[Any],
) -> None:
    def pick(item: Any, *keys: str) -> str:
        for key in keys:
            if isinstance(item, dict) and item.get(key):
                return str(item.get(key) or "")
            if hasattr(item, key) and getattr(item, key):
                return str(getattr(item, key) or "")
        return ""

    snapshot_ids = {
        pick(item, "id", "snapshotId", "snapshot_id")
        for item in records
        if pick(item, "id", "snapshotId", "snapshot_id")
    }
    snapshot_ids.update(
        pick(item, "snapshotId", "snapshot_id", "id")
        for item in [*frames, *stock_rows, *sector_rows]
        if pick(item, "snapshotId", "snapshot_id", "id")
    )

    index_keys: list[str] = []
    seen_date_keys: set[tuple[str, str]] = set()
    for item in [*records, *frames, *stock_rows, *sector_rows]:
        snapshot_type = pick(item, "type")
        trading_date = pick(item, "tradingDate", "trading_date")
        if snapshot_type and trading_date:
            seen_date_keys.add((snapshot_type, trading_date))

    for snapshot_type, trading_date in seen_date_keys:
        index_keys.extend(
            snapshot_cache.build_snapshot_cache_index_keys(
                prefix=get_settings().redis_key_prefix,
                dataset_id=dataset_id,
                snapshot_type=snapshot_type,
                trading_date=trading_date,
            ),
        )
    index_keys.extend(
        snapshot_cache.build_snapshot_cache_index_keys(
            prefix=get_settings().redis_key_prefix,
            dataset_id=dataset_id,
            snapshot_ids=sorted(snapshot_ids),
        ),
    )
    try:
        snapshot_cache.get_snapshot_redis_cache().invalidate_indexes(list(dict.fromkeys(index_keys)))
    except Exception:
        return


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
    projection: str = "full",
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    if snapshot_type not in {"quarter_hour", "half_hour", "hourly", "daily"}:
        raise HTTPException(status_code=400, detail=f"unsupported snapshot_type: {snapshot_type}")
    if projection not in {"full", "ranktrend"}:
        raise HTTPException(status_code=400, detail=f"unsupported projection: {projection}")
    _assert_snapshot_sort(sort)
    start = trading_date or start_date
    end = trading_date or end_date
    capture_modes = _parse_csv(allowed_capture_modes)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
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
            projection=projection,
        )
        snapshot_ids.extend(str(frame.get("snapshotId") or "") for frame in frames if frame.get("snapshotId"))
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "snapshotType": snapshot_type,
            "frames": frames,
            "count": len(frames),
            "source": storage_source_label(),
        }

    return _cached_snapshot_response(
        "frames",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_type": snapshot_type,
            "start_date": start,
            "end_date": end,
            "before_trading_date": before_trading_date,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "sort": sort,
            "limit": limit,
            "projection": projection,
        },
        snapshot_type=snapshot_type,
        trading_date=start if start == end else None,
        snapshot_ids=snapshot_ids,
        loader=load_response,
    )


@app.get("/api/ranktrend/rank-series")
def get_ranktrend_rank_series(
    dataset_id: str | None = None,
    snapshot_type: str = "half_hour",
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    codes: str | None = None,
    sort: str = "asc",
    limit: int | None = 50,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    if snapshot_type not in {"quarter_hour", "half_hour", "hourly", "daily"}:
        raise HTTPException(status_code=400, detail=f"unsupported snapshot_type: {snapshot_type}")
    _assert_snapshot_sort(sort)
    start = trading_date or start_date
    end = trading_date or end_date
    capture_modes = _parse_csv(allowed_capture_modes)
    stock_codes = _parse_csv(codes)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
        frames = repo.load_rank_series(
            resolved_dataset_id,
            snapshot_type=snapshot_type,
            start_date=start,
            end_date=end,
            before_trading_date=before_trading_date,
            allowed_capture_modes=capture_modes,
            exclude_restored=exclude_restored,
            codes=stock_codes,
            limit=limit,
            sort=sort,
        )
        snapshot_ids.extend(str(frame.get("snapshotId") or "") for frame in frames if frame.get("snapshotId"))
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "snapshotType": snapshot_type,
            "frames": frames,
            "count": len(frames),
            "source": storage_source_label(),
        }

    return _cached_snapshot_response(
        "ranktrend:rank-series",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_type": snapshot_type,
            "start_date": start,
            "end_date": end,
            "before_trading_date": before_trading_date,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "codes": ",".join(stock_codes),
            "sort": sort,
            "limit": limit,
        },
        snapshot_type=snapshot_type,
        trading_date=start if start == end else None,
        snapshot_ids=snapshot_ids,
        loader=load_response,
    )


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
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    _assert_snapshot_sort(sort)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
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
        snapshot_ids.extend(str(record.get("id") or "") for record in records if record.get("id"))
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "records": records,
            "count": len(records),
            "source": storage_source_label(),
        }

    return _cached_snapshot_response(
        "records",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_type": snapshot_type,
            "types": types,
            "trading_date": trading_date,
            "start_date": start_date,
            "end_date": end_date,
            "before_trading_date": before_trading_date,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "sort": sort,
            "limit": limit,
        },
        snapshot_type=snapshot_type,
        trading_date=trading_date,
        snapshot_ids=snapshot_ids,
        loader=load_response,
    )


@app.get("/api/snapshots/records/{snapshot_id}")
def get_snapshot_record(
    snapshot_id: str,
    dataset_id: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    repo = create_repository(db, enable_backup=False)
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
        "dataset": repo.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "record": record,
        "source": storage_source_label(),
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
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    _assert_snapshot_sort(sort)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    row_snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
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
        row_snapshot_ids.extend(str(row.get("snapshotId") or "") for row in result["rows"] if row.get("snapshotId"))
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "rows": result["rows"],
            "count": len(result["rows"]),
            "source": result["source"],
        }

    return _cached_snapshot_response(
        "stock_rows",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_id": snapshot_id,
            "snapshot_type": snapshot_type,
            "types": types,
            "trading_date": trading_date,
            "start_date": start_date,
            "end_date": end_date,
            "before_trading_date": before_trading_date,
            "code": code,
            "codes": codes,
            "slot_time": slot_time,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "sort": sort,
            "limit": limit,
        },
        snapshot_type=snapshot_type,
        trading_date=trading_date,
        snapshot_ids=[snapshot_id] if snapshot_id else row_snapshot_ids,
        loader=load_response,
    )


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
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    _assert_snapshot_sort(sort)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    row_snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
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
        row_snapshot_ids.extend(str(row.get("snapshotId") or "") for row in result["rows"] if row.get("snapshotId"))
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "rows": result["rows"],
            "count": len(result["rows"]),
            "source": result["source"],
        }

    return _cached_snapshot_response(
        "sector_rows",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_id": snapshot_id,
            "snapshot_type": snapshot_type,
            "types": types,
            "trading_date": trading_date,
            "start_date": start_date,
            "end_date": end_date,
            "before_trading_date": before_trading_date,
            "entity_type": entity_type,
            "entity_types": entity_types,
            "entity_key": entity_key,
            "entity_keys": entity_keys,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "sort": sort,
            "limit": limit,
        },
        snapshot_type=snapshot_type,
        trading_date=trading_date,
        snapshot_ids=[snapshot_id] if snapshot_id else row_snapshot_ids,
        loader=load_response,
    )


@app.get("/api/snapshots/counts")
def get_snapshot_counts(
    dataset_id: str | None = None,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    counts = repo.snapshot_table_counts(resolved_dataset_id)
    return {
        "ok": True,
        "dataset": repo.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "counts": counts,
        "source": storage_source_label(),
    }


@app.post("/api/storage/archive/snapshots/preview")
def preview_snapshot_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
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
    _reject_sqlite_archive_for_mongodb()
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
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    with ResearchSessionLocal() as research_session:
        return ArchiveService(db, research_session=research_session).archive_research(
            run_id=payload.get("runId") or payload.get("run_id"),
            older_than_days=int(payload.get("olderThanDays") or payload.get("older_than_days") or 30),
            keep_latest_per_group=int(payload.get("keepLatestPerGroup") or payload.get("keep_latest_per_group") or 10),
            dry_run=True,
        )


@app.post("/api/storage/archive/research")
def archive_research(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    with ResearchSessionLocal() as research_session:
        return ArchiveService(db, research_session=research_session).archive_research(
            run_id=payload.get("runId") or payload.get("run_id"),
            older_than_days=int(payload.get("olderThanDays") or payload.get("older_than_days") or 30),
            keep_latest_per_group=int(payload.get("keepLatestPerGroup") or payload.get("keep_latest_per_group") or 10),
            apply=True,
        )


@app.get("/api/storage/archive/manifests")
def list_archive_manifests(scope: str | None = None, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    manifests = ArchiveService(db).list_manifests(scope=scope)
    return {"ok": True, "manifests": manifests, "count": len(manifests)}


@app.post("/api/storage/archive/verify")
def verify_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    archive_id = str(payload.get("archiveId") or payload.get("archive_id") or "")
    return ArchiveService(db).verify_archive(archive_id)


@app.post("/api/storage/archive/restore")
def restore_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
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
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).push_archive_backup(limit=limit)


@app.post("/api/storage/archive/pull-backup")
def pull_archive_backup(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
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
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="SQLite snapshot JSON migration endpoint is disabled after MongoDB migration")
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
    if db is None and storage_source_label() != "mongodb":
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
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    try:
        return ThemeMigrationService(db).verify_mapping(payload)
    except ThemeMigrationError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error


@app.get("/api/themes/mapping")
def get_theme_mapping(db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    repo = get_theme_repository(db)
    mapping = repo.get_mapping()
    return {"ok": True, "mapping": mapping, "source": storage_source_label()}


@app.get("/api/themes/stocks/{theme_id}")
def get_theme_stocks(theme_id: str, db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    return get_theme_repository(db).get_theme_stocks(theme_id)


@app.get("/api/themes/stocks/by-code/{code}")
def get_stock_themes(code: str, db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    return get_theme_repository(db).get_stock_themes(code)


@app.get("/api/themes/counts")
def get_theme_counts(db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    return {"ok": True, "counts": get_theme_repository(db).counts(), "source": storage_source_label()}


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

    def row_snapshot_id(item: dict[str, Any]) -> str:
        return str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or "")

    stock_row_count_by_snapshot: dict[str, int] = {}
    for row in stock_rows:
        snapshot_id = row_snapshot_id(row)
        if snapshot_id:
            stock_row_count_by_snapshot[snapshot_id] = stock_row_count_by_snapshot.get(snapshot_id, 0) + 1
    empty_formal_snapshot_ids = [
        snapshot_id
        for frame in frames
        for snapshot_id in [row_snapshot_id(frame)]
        if str(frame.get("type") or "") != "five_minute"
        and snapshot_id
        and str(frame.get("captureMode") or "real_time") != "restored"
        and stock_row_count_by_snapshot.get(snapshot_id, 0) == 0
    ]
    if empty_formal_snapshot_ids:
        raise ValueError(f"formal snapshot hotlist is empty: {empty_formal_snapshot_ids[0]}")

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
    try:
        return DatasetService(db).list_datasets()
    except Exception as error:
        if storage_source_label() == "mongodb":
            raise HTTPException(
                status_code=503,
                detail=f"MongoDB primary is unavailable: {error}",
            ) from error
        raise


@app.get("/api/datasets/{dataset_id}")
def get_dataset(dataset_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        dataset = DatasetService(db).get_dataset(dataset_id)
    except Exception as error:
        if storage_source_label() == "mongodb":
            raise HTTPException(
                status_code=503,
                detail=f"MongoDB primary is unavailable: {error}",
            ) from error
        raise
    if not dataset:
        raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
    return dataset


@app.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if storage_source_label() != "mongodb":
        raise HTTPException(status_code=410, detail="dataset deletion is only available in MongoDB mode")
    try:
        result = DatasetService(db).delete_dataset(dataset_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        if storage_source_label() == "mongodb":
            raise HTTPException(
                status_code=503,
                detail=f"MongoDB primary is unavailable: {error}",
            ) from error
        raise
    if not result:
        raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
    return result


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
        if payload.get("sourceType") == "indexeddb":
            raise ImporterError(
                "sourceType=indexeddb is removed; use leveldb or json_bundle for explicit historical migration"
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
        raise _structured_bad_request(error) from error
    except Exception as error:
        raise _structured_backtest_error("rank_trend_backtest_failed", error) from error


@app.post("/api/backtests/theme-trend")
def run_theme_trend_backtest(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).run_theme_trend(payload)
    except ValueError as error:
        raise _structured_bad_request(error) from error
    except Exception as error:
        raise _structured_backtest_error("theme_trend_backtest_failed", error) from error


@app.post("/api/backtests/theme-confluence")
def run_theme_confluence_backtest(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).run_theme_confluence(payload)
    except ValueError as error:
        raise _structured_bad_request(error) from error
    except Exception as error:
        raise _structured_backtest_error("theme_confluence_backtest_failed", error) from error


def _backtest_not_found(run_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "backtest_run_not_found", "runId": run_id})


def _structured_bad_request(error: ValueError) -> HTTPException:
    detail = error.args[0] if error.args and isinstance(error.args[0], dict) else str(error)
    return HTTPException(status_code=400, detail=detail)


def _structured_backtest_error(code: str, error: Exception) -> HTTPException:
    return HTTPException(
        status_code=500,
        detail={
            "code": code,
            "message": str(error) or error.__class__.__name__,
            "errorType": error.__class__.__name__,
            "storage": storage_source_label(),
        },
    )


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


@app.get("/api/backtests/alignment")
def get_alignment(
    checkpoint_id: str = Query(...),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> dict[str, Any]:
    """Cross-reference trade_journal execution records with backtest signals for a checkpoint period."""
    repo = create_repository(None)
    if not hasattr(repo, "list_journal_entries"):
        return {
            "checkpointId": checkpoint_id,
            "journalExecutedCount": 0,
            "signalCodeCount": 0,
            "intersectionCount": 0,
            "sufficientSample": False,
            "alignmentStatus": "unavailable",
            "reason": "journal requires MongoDB storage backend",
        }

    journal_entries = repo.list_journal_entries(
        status="reviewed",
        date_from=start_date,
        date_to=end_date,
        limit=200,
    )
    executed = [
        e for e in journal_entries
        if e.get("entryPrice") is not None and float(e.get("entryPrice") or 0) > 0
    ]

    # Read checkpoint baselines from JSONL
    jsonl_path = get_settings().reports_dir / "long_test_runs.jsonl"
    checkpoint_runs: list[dict[str, Any]] = []
    if jsonl_path.exists():
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json_loads(line.strip())
                    if record and record.get("checkpointId") == checkpoint_id:
                        checkpoint_runs = record.get("baselines") or []
                        break
                except Exception:
                    continue

    # Collect signal codes from backtest run results
    signal_codes: set[str] = set()
    for baseline in checkpoint_runs:
        run_id = baseline.get("runId") or baseline.get("id")
        if not run_id:
            continue
        bt_run = repo.get_backtest_run(run_id)
        if not bt_run:
            continue
        result_json = loads_json_field(bt_run.result_json, {})
        signals = result_json.get("signals") or []
        for s in signals:
            code = str(s.get("code") or "")
            if code:
                signal_codes.add(code)

    journal_codes = {str(e.get("stockCode") or e.get("stock_code", "")) for e in executed}

    intersection = signal_codes & journal_codes
    signal_only = signal_codes - journal_codes
    journal_only = journal_codes - signal_codes

    intersection_entries = [e for e in executed if str(e.get("stockCode") or e.get("stock_code", "")) in intersection]
    intersection_pnl = sum(float(e.get("pnl") or 0) for e in intersection_entries)
    intersection_pnl_pct = round(sum(float(e.get("pnlPct") or 0) for e in intersection_entries), 4)

    sufficient_sample = len(executed) >= 10

    return {
        "checkpointId": checkpoint_id,
        "journalExecutedCount": len(executed),
        "signalCodeCount": len(signal_codes),
        "intersectionCount": len(intersection),
        "signalOnlyCount": len(signal_only),
        "journalOnlyCount": len(journal_only),
        "intersectionCodes": sorted(intersection),
        "signalOnlyCodes": sorted(signal_only)[:30],
        "journalOnlyCodes": sorted(journal_only)[:30],
        "intersectionPnl": intersection_pnl,
        "intersectionPnlPct": intersection_pnl_pct,
        "sufficientSample": sufficient_sample,
        "alignmentStatus": (
            "sufficient" if sufficient_sample else "insufficient_data"
        ),
    }


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
        repo = create_repository(db)
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
        parameter_sensitivity = _build_theme_parameter_sensitivity(trial_list)
        control_attribution = _empty_theme_control_attribution()
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
        parameter_sensitivity = _build_theme_parameter_sensitivity([])
        control_attribution = _build_theme_control_attribution(result, trades, execution_signals)
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
        "controlGroupAttribution": control_attribution,
        "parameterSensitivity": parameter_sensitivity,
        **trade_report,
    }


def _empty_theme_control_attribution() -> dict[str, Any]:
    base = {"signalCount": 0, "tradeCount": 0, "winRate": 0, "avgNetReturn": 0, "totalProfit": 0}
    return {
        "rankTrendOnly": dict(base),
        "themeOnly": dict(base),
        "themeRankTrendConfluence": dict(base),
        "leaderConfirmation": dict(base),
        "conclusion": "optimization_run_no_trade_control_groups",
    }


def _summarize_theme_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    total_profit = round(sum(float(row.get("profit") or 0) for row in rows), 2)
    total_return = round(sum(float(row.get("netReturn") or 0) for row in rows), 4)
    wins = sum(1 for row in rows if float(row.get("netReturn") or 0) > 0)
    return {
        "tradeCount": count,
        "winRate": round(wins / count, 4) if count else 0,
        "avgNetReturn": round(total_return / count, 4) if count else 0,
        "totalProfit": total_profit,
    }


def _build_theme_control_attribution(
    result: dict[str, Any],
    trades: list[dict[str, Any]],
    execution_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    theme_trend = result.get("themeTrend") if isinstance(result.get("themeTrend"), dict) else {}
    rank_control = theme_trend.get("rankTrendControl") if isinstance(theme_trend.get("rankTrendControl"), dict) else {}
    signals = result.get("signals") if isinstance(result.get("signals"), list) else []
    confluence_count = len(execution_signals)
    leader_signals = [
        signal for signal in execution_signals
        if str(signal.get("themeRole") or "").lower() == "leader"
        or "leader" in str(signal.get("themeReasons") or "").lower()
        or "龙头" in str(signal.get("themeReasons") or "")
    ]
    leader_trades = [
        trade for trade in trades
        if str(trade.get("explanation") or "").find("龙头") >= 0
        or str(trade.get("candidateTier") or "") == "A_MAIN"
    ]
    trade_summary = _summarize_theme_rows(trades)
    leader_trade_summary = _summarize_theme_rows(leader_trades)
    return {
        "rankTrendOnly": {
            "signalCount": int(rank_control.get("signalCount") or 0),
            "tradeCount": int(rank_control.get("tradeCount") or 0),
            "totalReturn": rank_control.get("totalReturn"),
            "maxDrawdown": rank_control.get("maxDrawdown"),
            "winRate": rank_control.get("winRate") or 0,
        },
        "themeOnly": {
            "signalCount": len(signals),
            **trade_summary,
        },
        "themeRankTrendConfluence": {
            "signalCount": confluence_count,
            **trade_summary,
        },
        "leaderConfirmation": {
            "signalCount": len(leader_signals),
            **leader_trade_summary,
        },
        "conclusion": (
            "theme_confluence_available"
            if confluence_count or trades
            else "theme_research_only_no_executable_control_group"
        ),
    }


def _build_theme_parameter_sensitivity(trials: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [trial for trial in trials if isinstance(trial, dict) and isinstance(trial.get("params"), dict)]
    if not completed:
        return {"trialCount": 0, "parameters": [], "topParameterSet": {}, "warnings": ["no_completed_trials"]}
    completed = sorted(completed, key=lambda trial: float(trial.get("score") or 0), reverse=True)
    top_count = max(1, min(5, len(completed)))
    top_trials = completed[:top_count]
    keys = sorted({key for trial in completed for key in (trial.get("params") or {}).keys()})
    rows: list[dict[str, Any]] = []
    for key in keys:
        values = [trial.get("params", {}).get(key) for trial in completed]
        top_values = [trial.get("params", {}).get(key) for trial in top_trials]
        score_by_value: dict[str, list[float]] = {}
        for trial in completed:
            value_key = str((trial.get("params") or {}).get(key))
            score_by_value.setdefault(value_key, []).append(float(trial.get("score") or 0))
        best_value, best_scores = max(
            score_by_value.items(),
            key=lambda item: (sum(item[1]) / len(item[1]) if item[1] else float("-inf")),
        )
        rows.append({
            "parameter": key,
            "bestValue": top_trials[0].get("params", {}).get(key),
            "dominantTopValues": sorted({str(value) for value in top_values}),
            "testedValueCount": len({str(value) for value in values}),
            "bestAverageValue": best_value,
            "bestAverageScore": round(sum(best_scores) / len(best_scores), 4) if best_scores else 0,
        })
    return {
        "trialCount": len(completed),
        "topTrialCount": top_count,
        "topParameterSet": completed[0].get("params") or {},
        "topScore": completed[0].get("score"),
        "parameters": rows,
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
