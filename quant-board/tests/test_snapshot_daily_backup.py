from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from backend.data.database import SessionLocal, init_db
from backend.data.models import ArchiveManifestModel, Dataset, SnapshotFrameModel, SnapshotRecordModel, SnapshotSectorRowModel, SnapshotStockRowModel


class FakeObjectStore:
    def __init__(self) -> None:
        self.pushed: list[dict[str, Any]] = []

    def push_archive(self, local_dir: Path, archive_id: str | None = None, archive_index_path: Path | None = None) -> dict[str, Any]:
        files = sorted(path.name for path in local_dir.iterdir() if path.is_file())
        self.pushed.append(
            {
                "localDir": str(local_dir),
                "archiveId": archive_id,
                "archiveIndexPath": str(archive_index_path) if archive_index_path else None,
                "files": files,
            }
        )
        return {
            "ok": True,
            "archiveId": archive_id,
            "files": [{"name": name, "key": f"quant-board/{archive_id}/{name}", "bytes": 1, "sha256": "x"} for name in files],
        }

    def archive_prefix(self, archive_id: str) -> str:
        return f"quant-board/{archive_id}/"


def test_daily_snapshot_backup_uploads_without_deleting_sqlite_and_records_manifest(tmp_path: Path, monkeypatch: Any) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    store = FakeObjectStore()
    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: store)

    with SessionLocal() as session:
        _cleanup_snapshot(session, "daily_backup_ds")
        _seed_snapshot(session, "daily_backup_ds", "2026-05-06")

        result = ArchiveService(session, archive_dir=tmp_path).backup_snapshot_day_to_object(
            dataset_id="daily_backup_ds",
            snapshot_type="half_hour",
            trading_date="2026-05-06",
        )

        assert result["ok"] is True
        assert result["target"] == "r2_object_backup"
        assert result["deletedFromSqlite"] == {}
        assert result["rowCounts"]["stockRows"] == 1
        assert store.pushed[0]["archiveId"] == "snapshot_backup_daily_backup_ds_half_hour_2026-05-06"
        assert set(store.pushed[0]["files"]) == {
            "frames.parquet",
            "manifest.json",
            "records.parquet",
            "sector_rows.parquet",
            "stock_rows.parquet",
        }
        assert session.scalar(select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == "daily_backup_ds")) is not None
        manifest = session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.dataset_id == "daily_backup_ds"))
        assert manifest is not None
        assert manifest.archive_id == "snapshot_backup_daily_backup_ds_half_hour_2026-05-06"
        assert manifest.scope == "snapshot_backup"
        assert manifest.status == "uploaded"
        assert manifest.object_key == "quant-board/snapshot_backup_daily_backup_ds_half_hour_2026-05-06/"
        assert manifest.uploaded_at is not None
        assert manifest.trading_date == "2026-05-06"


def test_daily_snapshot_backup_dry_run_does_not_write_or_upload(tmp_path: Path, monkeypatch: Any) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    store = FakeObjectStore()
    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: store)

    with SessionLocal() as session:
        _cleanup_snapshot(session, "daily_backup_ds")
        _seed_snapshot(session, "daily_backup_ds", "2026-05-06")

        result = ArchiveService(session, archive_dir=tmp_path).backup_snapshot_day_to_object(
            dataset_id="daily_backup_ds",
            snapshot_type="half_hour",
            trading_date="2026-05-06",
            dry_run=True,
        )

        assert result["ok"] is True
        assert result["dryRun"] is True
        assert result["rowCounts"]["frames"] == 1
        assert store.pushed == []
        assert not list(tmp_path.rglob("*.parquet"))


def test_daily_snapshot_backup_reports_empty_day(tmp_path: Path, monkeypatch: Any) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    store = FakeObjectStore()
    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: store)

    with SessionLocal() as session:
        _cleanup_snapshot(session, "daily_backup_ds")

        result = ArchiveService(session, archive_dir=tmp_path).backup_snapshot_day_to_object(
            dataset_id="daily_backup_ds",
            snapshot_type="half_hour",
            trading_date="2026-05-06",
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "backup_empty_table"
        assert store.pushed == []


def test_daily_snapshot_backup_sanitizes_local_path_parts(tmp_path: Path, monkeypatch: Any) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    store = FakeObjectStore()
    monkeypatch.setattr("backend.data.archive.service.get_object_backup_store", lambda: store)

    with SessionLocal() as session:
        _cleanup_snapshot(session, "daily_backup_ds")
        _seed_snapshot(session, "daily_backup_ds", "../2026-05-06", snapshot_type="half/hour")

        result = ArchiveService(session, archive_dir=tmp_path).backup_snapshot_day_to_object(
            dataset_id="daily_backup_ds",
            snapshot_type="half/hour",
            trading_date="../2026-05-06",
        )

        assert result["ok"] is True
        local_path = Path(result["localPath"]).resolve()
        assert local_path.is_relative_to((tmp_path / "backups").resolve())
        assert ".." not in local_path.parts
        assert store.pushed[0]["localDir"] == str(local_path)


def _seed_snapshot(session: Any, dataset_id: str, trading_date: str, *, snapshot_type: str = "half_hour") -> None:
    session.merge(
        Dataset(
            id=dataset_id,
            name="Daily Backup DS",
            source_type="test",
            snapshot_count=1,
            frame_count=1,
            stock_row_count=1,
            sector_row_count=1,
            start_date=trading_date,
            end_date=trading_date,
            snapshot_types_json=f'["{snapshot_type}"]',
        )
    )
    session.add(
        SnapshotRecordModel(
            dataset_id=dataset_id,
            snapshot_id=f"{dataset_id}:snap",
            type=snapshot_type,
            trading_date=trading_date,
            timestamp=1,
        )
    )
    session.add(
        SnapshotFrameModel(
            dataset_id=dataset_id,
            snapshot_id=f"{dataset_id}:snap",
            type=snapshot_type,
            trading_date=trading_date,
            timestamp=1,
            stock_row_count=1,
            sector_row_count=1,
        )
    )
    session.add(
        SnapshotStockRowModel(
            dataset_id=dataset_id,
            row_id=f"{dataset_id}:snap:000001",
            snapshot_id=f"{dataset_id}:snap",
            type=snapshot_type,
            trading_date=trading_date,
            timestamp=1,
            code="000001",
            name="平安银行",
            rank=1,
        )
    )
    session.add(
        SnapshotSectorRowModel(
            dataset_id=dataset_id,
            row_id=f"{dataset_id}:snap:sector:bank",
            snapshot_id=f"{dataset_id}:snap",
            type=snapshot_type,
            trading_date=trading_date,
            timestamp=1,
            entity_type="sector",
            entity_key="bank",
            entity_name="银行",
            rank=1,
        )
    )
    session.commit()


def _cleanup_snapshot(session: Any, dataset_id: str) -> None:
    for model in (SnapshotStockRowModel, SnapshotSectorRowModel, SnapshotFrameModel, SnapshotRecordModel):
        session.execute(delete(model).where(model.dataset_id == dataset_id))
    session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.dataset_id == dataset_id))
    session.execute(delete(Dataset).where(Dataset.id == dataset_id))
    session.commit()
