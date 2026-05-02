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
from backend.data.backup_sync import BackupSyncService
from backend.data.database import get_db, init_db, primary_status
from backend.data.dataset_service import DatasetService
from backend.data.importers import ImporterError, frame_from_record, sector_rows_from_record, stock_rows_from_record
from backend.data.migration import SnapshotMigrationService
from backend.data.models import Dataset
from backend.data.repository import Repository
from backend.data.schemas import (
    GoldenImportRequest,
    GoldenValidateRequest,
    ImportDatasetRequest,
    SnapshotIngestRequest,
    SnapshotJsonMigrationRequest,
)
from backend.data.supabase_backup import get_backup_client
from backend.services import BacktestService, GoldenService, OptimizationService
from backend.settings import get_settings
from backend.utils import json_dumps, stable_hash


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
    auto_sync_runner.start()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await auto_sync_runner.stop()


@app.get("/api/health")
def health_check(db: Session | None = Depends(get_db)) -> dict[str, Any]:
    backup = get_backup_client()
    return {
        "status": "ok",
        "version": "0.1.0",
        "engine": "QuantBoard",
        "default_snapshot_type": "half_hour",
        "database": {
            "primary": primary_status(),
            "backup": backup.health() if backup else {"configured": False, "connected": False, "last_error": None},
            "mode": "sqlite_primary_supabase_backup",
            "outbox": Repository(db, enable_backup=False).outbox_status() if db is not None else None,
            "autoSync": auto_sync_runner.status(),
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


@app.post("/api/sync/smoke-backup")
def smoke_backup() -> dict[str, Any]:
    backup = get_backup_client()
    if not backup:
        return {"ok": False, "configured": False, "error": "supabase backup is not configured"}
    return backup.smoke_test()


@app.post("/api/snapshots/ingest")
def ingest_snapshot(request: SnapshotIngestRequest, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
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
        # The lightweight frontend previews browser IndexedDB and posts sampled rows.
        # Treat that as a JSON bundle import path so the backend can persist the sample.
        if source_type == "indexeddb":
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


@app.get("/api/backtests/{run_id}")
def get_backtest(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = BacktestService(db).get_run(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"backtest run not found: {run_id}")
    return result


@app.get("/api/backtests/{run_id}/report")
def get_backtest_report(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return get_backtest(run_id, db)


@app.post("/api/optimizations/rank-trend")
def run_ranktrend_optimization(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return OptimizationService(db).run_ranktrend(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.get("/api/optimizations/{run_id}")
def get_optimization(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = OptimizationService(db).get_run(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"optimization run not found: {run_id}")
    return result


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
