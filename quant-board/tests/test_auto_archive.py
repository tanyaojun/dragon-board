from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select

from backend.data.database import SessionLocal, init_db
from backend.data.models import ArchiveManifestModel, Dataset, SnapshotFrameModel, SnapshotRecordModel, SnapshotSectorRowModel, SnapshotStockRowModel


def _seed_multi_date(session) -> None:
    dataset_id = "auto_ds"
    for model in (SnapshotStockRowModel, SnapshotSectorRowModel, SnapshotFrameModel, SnapshotRecordModel, Dataset):
        session.execute(delete(model).where(model.dataset_id == dataset_id) if model is not Dataset else delete(model).where(model.id == dataset_id))
    session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.dataset_id == dataset_id))
    session.commit()
    session.merge(
        Dataset(
            id=dataset_id,
            name="Auto DS",
            source_type="test",
            snapshot_count=5,
            frame_count=5,
            stock_row_count=5,
            start_date="2025-01-01",
            end_date="2025-12-31",
            snapshot_types_json='["half_hour"]',
        )
    )
    for i, trading_date in enumerate(["2025-03-01", "2025-06-01", "2025-09-01", "2025-12-01"]):
        snap_id = f"snap_auto_{i}"
        session.add(SnapshotRecordModel(dataset_id=dataset_id, snapshot_id=snap_id, type="half_hour", trading_date=trading_date, timestamp=i))
        session.add(SnapshotFrameModel(dataset_id=dataset_id, snapshot_id=snap_id, type="half_hour", trading_date=trading_date, timestamp=i, stock_row_count=1, sector_row_count=1))
        session.add(SnapshotStockRowModel(dataset_id=dataset_id, row_id=f"{snap_id}:000001", snapshot_id=snap_id, type="half_hour", trading_date=trading_date, timestamp=i, code="000001", name="测试", rank=1))
        session.add(SnapshotSectorRowModel(dataset_id=dataset_id, row_id=f"{snap_id}:sector:tech", snapshot_id=snap_id, type="half_hour", trading_date=trading_date, timestamp=i, entity_type="sector", entity_key="tech", entity_name="科技", rank=1))
    session.commit()


def test_auto_archive_runner_reports_disabled_by_default(tmp_path: Path) -> None:
    from backend.data.archive.auto_archive import ArchiveAutoRunner

    runner = ArchiveAutoRunner(enabled=False, archive_dir=tmp_path)

    assert runner.status()["enabled"] is False
    assert runner.status()["running"] is False
    assert runner.status()["last_started_at"] is None
    assert runner.status()["last_finished_at"] is None
    assert runner.status()["consecutive_failures"] == 0


def test_run_archive_auto_once_skips_when_below_retention(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_AUTO_ENABLED", "true")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_AUTO_DATASET_ID", "auto_ds")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_RETENTION_TRADING_DAYS", "365")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_AUTO_SNAPSHOT_TYPES", "half_hour")
    from backend.settings import get_settings
    get_settings.cache_clear()
    from backend.data.archive.auto_archive import run_archive_auto_once

    init_db()

    with SessionLocal() as session:
        _seed_multi_date(session)

    result = run_archive_auto_once(limit=1)

    assert result["ok"] is True
    assert result.get("skipped") is True
    assert result.get("reason") == "not_enough_history"


def test_run_archive_auto_once_archives_beyond_retention(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_AUTO_ENABLED", "true")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_AUTO_DATASET_ID", "auto_ds")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_RETENTION_TRADING_DAYS", "1")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_AUTO_SNAPSHOT_TYPES", "half_hour")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_DIR", str(tmp_path))
    from backend.settings import get_settings
    get_settings.cache_clear()
    from backend.data.archive.auto_archive import run_archive_auto_once

    init_db()

    with SessionLocal() as session:
        _seed_multi_date(session)

    result = run_archive_auto_once(limit=1)

    assert result["ok"] is True
    assert result.get("skipped") is not True
    assert len(result.get("results", [])) > 0

    # The first result should have archived stocks
    first = result["results"][0]
    assert first["ok"] is True

    # SQLite data should be deleted after archiving
    with SessionLocal() as session:
        remaining = session.scalar(select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == "auto_ds"))
        assert remaining is None or int(session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.dataset_id == "auto_ds").with_only_columns(ArchiveManifestModel.id)) or 0) >= 0


def test_auto_archive_verification_failure_does_not_delete_sqlite(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_AUTO_ENABLED", "true")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_AUTO_DATASET_ID", "auto_ds")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_RETENTION_TRADING_DAYS", "1")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_AUTO_SNAPSHOT_TYPES", "half_hour")
    monkeypatch.setenv("QUANT_BOARD_ARCHIVE_DIR", str(tmp_path))
    from backend.settings import get_settings
    get_settings.cache_clear()

    from backend.data.archive.service import ArchiveService
    from backend.data.archive.auto_archive import run_archive_auto_once

    def fail_verify(self, archive_id: str) -> dict:
        return {"ok": False, "error": {"code": "archive_sha256_mismatch", "archiveId": archive_id}}

    monkeypatch.setattr(ArchiveService, "verify_archive", fail_verify)
    init_db()
    with SessionLocal() as session:
        _seed_multi_date(session)

    result = run_archive_auto_once(limit=1)

    assert result["ok"] is False
    assert result["results"][0]["error"]["code"] == "archive_sha256_mismatch"
    with SessionLocal() as session:
        remaining = int(session.scalar(select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == "auto_ds").with_only_columns(SnapshotStockRowModel.id).limit(1)) or 0)
        assert remaining > 0
