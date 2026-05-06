from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select

from backend.data.database import SessionLocal, init_db
from backend.data.models import ArchiveManifestModel, Dataset, SnapshotFrameModel, SnapshotRecordModel, SnapshotSectorRowModel, SnapshotStockRowModel


def test_archive_code_does_not_use_recursive_delete() -> None:
    root = Path(__file__).resolve().parents[1]
    scanned = [
        root / "backend" / "data" / "archive" / "service.py",
        root / "backend" / "data" / "archive" / "object_store.py",
        root / "tests" / "test_archive_snapshots.py",
        root / "tests" / "test_object_backup.py",
    ]
    banned = (
        "shutil." + "rmtree",
        "Remove-Item " + "-Recurse",
        "rm " + "-rf",
        "rmdir " + "/s",
        "rd " + "/s",
        "del " + "/s",
    )
    offenders = []
    for path in scanned:
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                offenders.append(f"{path.relative_to(root)}: {token}")

    assert offenders == []


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


def test_verify_archive_valid_snapshot_checks_files_and_counts(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as session:
        _seed_snapshot(session)
        service = ArchiveService(session, archive_dir=tmp_path)
        archived = service.archive_snapshots(
            dataset_id="archive_ds",
            snapshot_type="half_hour",
            before_trading_date="2026-01-02",
            apply=True,
        )

        verified = service.verify_archive(archived["archiveId"])

        assert verified["ok"] is True
        assert verified["archiveId"] == archived["archiveId"]
        assert verified["status"] == "verified"
        assert verified["checkedFiles"] >= 5
        assert verified["rowCounts"]["stockRows"] == 1


def test_verify_archive_reports_missing_file(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as session:
        _seed_snapshot(session)
        service = ArchiveService(session, archive_dir=tmp_path)
        archived = service.archive_snapshots(
            dataset_id="archive_ds",
            snapshot_type="half_hour",
            before_trading_date="2026-01-02",
            apply=True,
        )
        stock_path = Path(archived["localPath"]) / "stock_rows.parquet"
        stock_path.unlink()

        verified = service.verify_archive(archived["archiveId"])

        assert verified["ok"] is False
        assert verified["error"]["code"] == "archive_file_missing"


def test_verify_archive_reports_sha256_mismatch(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as session:
        _seed_snapshot(session)
        service = ArchiveService(session, archive_dir=tmp_path)
        archived = service.archive_snapshots(
            dataset_id="archive_ds",
            snapshot_type="half_hour",
            before_trading_date="2026-01-02",
            apply=True,
        )
        stock_path = Path(archived["localPath"]) / "stock_rows.parquet"
        stock_path.write_bytes(b"tampered")

        verified = service.verify_archive(archived["archiveId"])

        assert verified["ok"] is False
        assert verified["error"]["code"] == "archive_sha256_mismatch"


def test_failed_snapshot_archive_is_not_left_verified(tmp_path: Path, monkeypatch) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as session:
        _seed_snapshot(session)

        def fail_verify(self, archive_id: str) -> dict:
            return {"ok": False, "error": {"code": "archive_sha256_mismatch", "archiveId": archive_id}}

        monkeypatch.setattr(ArchiveService, "verify_archive", fail_verify)
        service = ArchiveService(session, archive_dir=tmp_path)

        result = service.archive_snapshots(
            dataset_id="archive_ds",
            snapshot_type="half_hour",
            before_trading_date="2026-01-02",
            apply=True,
        )

        assert result["ok"] is False
        manifest = session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.archive_id == result["archiveId"]))
        assert manifest is not None
        assert manifest.status == "verify_failed"
        assert manifest.last_error is not None
        assert session.scalar(select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == "archive_ds")) is not None


def test_verify_archive_reports_row_count_mismatch(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as session:
        _seed_snapshot(session)
        service = ArchiveService(session, archive_dir=tmp_path)
        archived = service.archive_snapshots(
            dataset_id="archive_ds",
            snapshot_type="half_hour",
            before_trading_date="2026-01-02",
            apply=True,
        )
        manifest = session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.archive_id == archived["archiveId"]))
        assert manifest is not None
        manifest.row_counts_json = '{"records":1,"frames":1,"stockRows":99,"sectorRows":1}'
        session.commit()

        verified = service.verify_archive(archived["archiveId"])

        assert verified["ok"] is False
        assert verified["error"]["code"] == "archive_row_count_mismatch"


def test_verify_archive_reports_unsupported_scope(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as session:
        archive_id = "unsupported_scope_archive"
        session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.archive_id == archive_id))
        session.commit()
        session.merge(
            ArchiveManifestModel(
                archive_id=archive_id,
                scope="unknown",
                local_path=str(tmp_path / archive_id),
                status="verified",
                row_counts_json="{}",
                file_hashes_json="{}",
            )
        )
        session.commit()

        verified = ArchiveService(session, archive_dir=tmp_path).verify_archive(archive_id)

        assert verified["ok"] is False
        assert verified["error"]["code"] == "unsupported_archive_scope"
