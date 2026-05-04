from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select

from backend.data.database import SessionLocal, init_db
from backend.data.models import ArchiveManifestModel, Dataset, SnapshotFrameModel, SnapshotRecordModel, SnapshotSectorRowModel, SnapshotStockRowModel


def _seed_snapshot(session) -> None:
    _cleanup_snapshot(session, "archive_ds")
    session.merge(
        Dataset(
            id="archive_ds",
            name="Archive DS",
            source_type="test",
            snapshot_count=1,
            frame_count=1,
            stock_row_count=1,
            sector_row_count=1,
            start_date="2026-01-01",
            end_date="2026-01-01",
            snapshot_types_json='["half_hour"]',
        )
    )
    session.add(
        SnapshotRecordModel(
            dataset_id="archive_ds",
            snapshot_id="snap_1",
            type="half_hour",
            trading_date="2026-01-01",
            timestamp=1,
        )
    )
    session.add(
        SnapshotFrameModel(
            dataset_id="archive_ds",
            snapshot_id="snap_1",
            type="half_hour",
            trading_date="2026-01-01",
            timestamp=1,
            stock_row_count=1,
            sector_row_count=1,
        )
    )
    session.add(
        SnapshotStockRowModel(
            dataset_id="archive_ds",
            row_id="snap_1:000001",
            snapshot_id="snap_1",
            type="half_hour",
            trading_date="2026-01-01",
            timestamp=1,
            code="000001",
            name="平安银行",
            rank=1,
        )
    )
    session.add(
        SnapshotSectorRowModel(
            dataset_id="archive_ds",
            row_id="snap_1:sector:bank",
            snapshot_id="snap_1",
            type="half_hour",
            trading_date="2026-01-01",
            timestamp=1,
            entity_type="sector",
            entity_key="bank",
            entity_name="银行",
            rank=1,
        )
    )
    session.commit()


def _cleanup_snapshot(session, dataset_id: str) -> None:
    for model in (SnapshotStockRowModel, SnapshotSectorRowModel, SnapshotFrameModel, SnapshotRecordModel, Dataset):
        session.execute(delete(model).where(model.dataset_id == dataset_id) if model is not Dataset else delete(model).where(model.id == dataset_id))
    session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.dataset_id == dataset_id))
    session.commit()


def test_snapshot_archive_dry_run_does_not_write_or_delete(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as session:
        _seed_snapshot(session)
        result = ArchiveService(session, archive_dir=tmp_path).archive_snapshots(
            dataset_id="archive_ds",
            snapshot_type="half_hour",
            before_trading_date="2026-01-02",
            dry_run=True,
        )

        assert result["ok"] is True
        assert result["dryRun"] is True
        assert result["rowCounts"]["stockRows"] == 1
        assert not list(tmp_path.rglob("*.parquet"))
        assert session.scalar(select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == "archive_ds")) is not None


def test_snapshot_archive_apply_writes_parquet_and_cleans_detail_rows(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as session:
        _seed_snapshot(session)
        service = ArchiveService(session, archive_dir=tmp_path)

        result = service.archive_snapshots(
            dataset_id="archive_ds",
            snapshot_type="half_hour",
            before_trading_date="2026-01-02",
            apply=True,
        )

        assert result["ok"] is True
        assert result["status"] == "verified"
        assert result["deletedFromSqlite"] == {"stockRows": 1, "sectorRows": 1}
        assert (Path(result["localPath"]) / "stock_rows.parquet").exists()
        assert session.scalar(select(SnapshotRecordModel).where(SnapshotRecordModel.dataset_id == "archive_ds")) is not None
        assert session.scalar(select(SnapshotFrameModel).where(SnapshotFrameModel.dataset_id == "archive_ds")) is not None
        assert session.scalar(select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == "archive_ds")) is None

        restored = service.restore_archive(result["archiveId"], apply=True)
        assert restored["ok"] is True
        assert restored["restored"]["stockRows"] == 1
        assert session.scalar(select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == "archive_ds")) is not None
