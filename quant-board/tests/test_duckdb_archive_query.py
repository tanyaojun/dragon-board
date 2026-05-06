from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select

from backend.data.database import ResearchSessionLocal, SessionLocal, init_db
from backend.data.models import ArchiveManifestModel, BacktestEquityCurve, BacktestRun, BacktestSignal, BacktestTrade, Dataset, SnapshotFrameModel, SnapshotRecordModel, SnapshotSectorRowModel, SnapshotStockRowModel


# ── snapshot stock rows ──

def _seed_duck_snapshot(session) -> None:
    for model in (SnapshotStockRowModel, SnapshotFrameModel, SnapshotRecordModel, Dataset):
        session.execute(delete(model).where(model.dataset_id == "duck_ds") if model is not Dataset else delete(model).where(model.id == "duck_ds"))
    session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.dataset_id == "duck_ds"))
    session.commit()
    session.merge(
        Dataset(
            id="duck_ds",
            name="Duck DS",
            source_type="test",
            snapshot_count=1,
            frame_count=1,
            stock_row_count=1,
            start_date="2026-01-01",
            end_date="2026-01-01",
            snapshot_types_json='["half_hour"]',
        )
    )
    session.add(SnapshotRecordModel(dataset_id="duck_ds", snapshot_id="snap_duck", type="half_hour", trading_date="2026-01-01", timestamp=1))
    session.add(SnapshotFrameModel(dataset_id="duck_ds", snapshot_id="snap_duck", type="half_hour", trading_date="2026-01-01", timestamp=1))
    session.add(
        SnapshotStockRowModel(
            dataset_id="duck_ds",
            row_id="snap_duck:000001",
            snapshot_id="snap_duck",
            type="half_hour",
            trading_date="2026-01-01",
            timestamp=1,
            code="000001",
            name="平安银行",
            rank=1,
        )
    )
    session.commit()


def test_stock_rows_fall_back_to_duckdb_archive(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService
    from backend.data.repository import Repository

    init_db()
    with SessionLocal() as session:
        _seed_duck_snapshot(session)

        archived = ArchiveService(session, archive_dir=tmp_path).archive_snapshots(
            dataset_id="duck_ds",
            snapshot_type="half_hour",
            before_trading_date="2026-01-02",
            apply=True,
        )
        assert archived["ok"] is True
        assert session.scalar(select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == "duck_ds")) is None

        result = Repository(session, enable_backup=False).list_snapshot_stock_rows(
            "duck_ds",
            snapshot_type="half_hour",
            trading_date="2026-01-01",
        )

        assert result["source"] == "parquet_archive"
        assert result["rows"][0]["code"] == "000001"
        assert result["rows"][0]["name"] == "平安银行"


# ── snapshot sector rows ──

def _seed_duck_sector(session) -> None:
    for model in (SnapshotSectorRowModel, SnapshotFrameModel, SnapshotRecordModel, Dataset):
        session.execute(delete(model).where(model.dataset_id == "duck_sec") if model is not Dataset else delete(model).where(model.id == "duck_sec"))
    session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.dataset_id == "duck_sec"))
    session.commit()
    session.merge(
        Dataset(
            id="duck_sec",
            name="Duck Sector DS",
            source_type="test",
            snapshot_count=1,
            frame_count=1,
            sector_row_count=1,
            start_date="2026-02-01",
            end_date="2026-02-01",
            snapshot_types_json='["half_hour"]',
        )
    )
    session.add(SnapshotRecordModel(dataset_id="duck_sec", snapshot_id="snap_sec", type="half_hour", trading_date="2026-02-01", timestamp=1))
    session.add(SnapshotFrameModel(dataset_id="duck_sec", snapshot_id="snap_sec", type="half_hour", trading_date="2026-02-01", timestamp=1, sector_row_count=1))
    session.add(
        SnapshotSectorRowModel(
            dataset_id="duck_sec",
            row_id="snap_sec:sector:energy",
            snapshot_id="snap_sec",
            type="half_hour",
            trading_date="2026-02-01",
            timestamp=1,
            entity_type="sector",
            entity_key="energy",
            entity_name="能源",
            rank=1,
        )
    )
    session.commit()


def test_sector_rows_fall_back_to_duckdb_archive(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService
    from backend.data.repository import Repository

    init_db()
    with SessionLocal() as session:
        _seed_duck_sector(session)

        archived = ArchiveService(session, archive_dir=tmp_path).archive_snapshots(
            dataset_id="duck_sec",
            snapshot_type="half_hour",
            before_trading_date="2026-02-02",
            apply=True,
        )
        assert archived["ok"] is True

        result = Repository(session, enable_backup=False).list_snapshot_sector_rows(
            "duck_sec",
            snapshot_type="half_hour",
            trading_date="2026-02-01",
        )

        assert result["source"] == "parquet_archive"
        assert result["rows"][0]["entityName"] == "能源"


# ── mixed source ──

def _seed_duck_mixed(session) -> None:
    ds = "duck_mix"
    for model in (SnapshotStockRowModel, SnapshotFrameModel, SnapshotRecordModel, Dataset):
        session.execute(delete(model).where(model.dataset_id == ds) if model is not Dataset else delete(model).where(model.id == ds))
    session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.dataset_id == ds))
    session.commit()
    session.merge(Dataset(id=ds, name="Mixed DS", source_type="test", snapshot_count=2, frame_count=2, stock_row_count=2, start_date="2026-03-01", end_date="2026-03-02", snapshot_types_json='["half_hour"]'))
    # date1: will stay in SQLite (hot)
    session.add(SnapshotRecordModel(dataset_id=ds, snapshot_id="snap_hot", type="half_hour", trading_date="2026-03-02", timestamp=2))
    session.add(SnapshotFrameModel(dataset_id=ds, snapshot_id="snap_hot", type="half_hour", trading_date="2026-03-02", timestamp=2, stock_row_count=1))
    session.add(SnapshotStockRowModel(dataset_id=ds, row_id="snap_hot:000002", snapshot_id="snap_hot", type="half_hour", trading_date="2026-03-02", timestamp=2, code="000002", name="万科A", rank=2))
    # date2: will be archived (cold)
    session.add(SnapshotRecordModel(dataset_id=ds, snapshot_id="snap_cold", type="half_hour", trading_date="2026-03-01", timestamp=1))
    session.add(SnapshotFrameModel(dataset_id=ds, snapshot_id="snap_cold", type="half_hour", trading_date="2026-03-01", timestamp=1, stock_row_count=1))
    session.add(SnapshotStockRowModel(dataset_id=ds, row_id="snap_cold:000001", snapshot_id="snap_cold", type="half_hour", trading_date="2026-03-01", timestamp=1, code="000001", name="平安银行", rank=1))
    session.commit()


def test_mixed_source_returns_both_hot_and_cold(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService
    from backend.data.repository import Repository

    init_db()
    with SessionLocal() as session:
        _seed_duck_mixed(session)

        # Archive only the cold date (2026-03-01)
        archived = ArchiveService(session, archive_dir=tmp_path).archive_snapshots(
            dataset_id="duck_mix",
            snapshot_type="half_hour",
            before_trading_date="2026-03-02",
            apply=True,
        )
        assert archived["ok"] is True

        # Query: should return both hot (SQLite) and cold (Parquet)
        result = Repository(session, enable_backup=False).list_snapshot_stock_rows(
            "duck_mix",
            snapshot_type="half_hour",
        )

        assert result["source"] == "mixed"
        codes = {row["code"] for row in result["rows"]}
        assert codes == {"000001", "000002"}


def test_stock_rows_range_query_includes_archived_rows(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService
    from backend.data.repository import Repository

    init_db()
    with SessionLocal() as session:
        _seed_duck_mixed(session)
        archived = ArchiveService(session, archive_dir=tmp_path).archive_snapshots(
            dataset_id="duck_mix",
            snapshot_type="half_hour",
            before_trading_date="2026-03-02",
            apply=True,
        )
        assert archived["ok"] is True

        result = Repository(session, enable_backup=False).list_snapshot_stock_rows(
            "duck_mix",
            snapshot_type="half_hour",
            start_date="2026-03-01",
            end_date="2026-03-02",
        )

        assert result["source"] == "mixed"
        assert {row["code"] for row in result["rows"]} == {"000001", "000002"}


def test_sector_rows_range_query_includes_archived_rows(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService
    from backend.data.repository import Repository

    init_db()
    with SessionLocal() as session:
        _seed_duck_sector(session)
        archived = ArchiveService(session, archive_dir=tmp_path).archive_snapshots(
            dataset_id="duck_sec",
            snapshot_type="half_hour",
            before_trading_date="2026-02-02",
            apply=True,
        )
        assert archived["ok"] is True

        result = Repository(session, enable_backup=False).list_snapshot_sector_rows(
            "duck_sec",
            snapshot_type="half_hour",
            start_date="2026-02-01",
            end_date="2026-02-02",
        )

        assert result["source"] == "parquet_archive"
        assert result["rows"][0]["entityName"] == "能源"


def test_duckdb_query_rejects_unsupported_filter(tmp_path: Path) -> None:
    from backend.data.archive.duckdb_query import ArchiveQueryError, DuckDBArchiveQuery
    from backend.data.archive.parquet_store import ParquetStore

    store = ParquetStore(tmp_path)
    file_info = store.write_table("stock_rows", [{"datasetId": "duck_filter", "code": "000001", "timestamp": 1, "rank": 1}])

    try:
        DuckDBArchiveQuery().read_table(Path(file_info["path"]), table="stock_rows", filters={"notAllowed": "x"})
    except ArchiveQueryError as exc:
        assert exc.code == "archive_query_filter_unsupported"
    else:
        raise AssertionError("unsupported filter should raise ArchiveQueryError")


def test_service_reports_missing_archived_parquet_file(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as session:
        _seed_duck_snapshot(session)
        service = ArchiveService(session, archive_dir=tmp_path)
        archived = service.archive_snapshots(
            dataset_id="duck_ds",
            snapshot_type="half_hour",
            before_trading_date="2026-01-02",
            apply=True,
        )
        assert archived["ok"] is True
        (Path(archived["localPath"]) / "stock_rows.parquet").unlink()

        result = service.query_archived_stock_rows_result(dataset_id="duck_ds", snapshot_type="half_hour", trading_date="2026-01-01")

        assert result["ok"] is False
        assert result["error"]["code"] == "archive_file_missing"


def test_multi_date_archive_is_included_in_range_lookup(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService
    from backend.data.repository import Repository

    init_db()
    with SessionLocal() as session:
        _seed_duck_mixed(session)
        session.execute(delete(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == "duck_mix").where(SnapshotStockRowModel.trading_date == "2026-03-02"))
        session.execute(delete(SnapshotFrameModel).where(SnapshotFrameModel.dataset_id == "duck_mix").where(SnapshotFrameModel.trading_date == "2026-03-02"))
        session.execute(delete(SnapshotRecordModel).where(SnapshotRecordModel.dataset_id == "duck_mix").where(SnapshotRecordModel.trading_date == "2026-03-02"))
        # Add an earlier cold date so archive_snapshots writes a multi-date manifest with trading_date=None.
        session.add(SnapshotRecordModel(dataset_id="duck_mix", snapshot_id="snap_cold_2", type="half_hour", trading_date="2026-02-28", timestamp=0))
        session.add(SnapshotFrameModel(dataset_id="duck_mix", snapshot_id="snap_cold_2", type="half_hour", trading_date="2026-02-28", timestamp=0, stock_row_count=1))
        session.add(SnapshotStockRowModel(dataset_id="duck_mix", row_id="snap_cold_2:000003", snapshot_id="snap_cold_2", type="half_hour", trading_date="2026-02-28", timestamp=0, code="000003", name="冷数据二", rank=3))
        session.commit()

        archived = ArchiveService(session, archive_dir=tmp_path).archive_snapshots(
            dataset_id="duck_mix",
            snapshot_type="half_hour",
            before_trading_date="2026-03-02",
            apply=True,
        )
        assert archived["ok"] is True
        manifest = session.scalar(select(ArchiveManifestModel).where(ArchiveManifestModel.archive_id == archived["archiveId"]))
        assert manifest is not None
        assert manifest.trading_date is None

        result = Repository(session, enable_backup=False).list_snapshot_stock_rows(
            "duck_mix",
            snapshot_type="half_hour",
            start_date="2026-02-28",
            end_date="2026-03-01",
        )

        assert result["source"] == "parquet_archive"
        assert {row["code"] for row in result["rows"]} == {"000001", "000003"}

        narrowed = Repository(session, enable_backup=False).list_snapshot_stock_rows(
            "duck_mix",
            snapshot_type="half_hour",
            start_date="2026-03-01",
            end_date="2026-03-01",
        )

        assert narrowed["source"] == "parquet_archive"
        assert {row["code"] for row in narrowed["rows"]} == {"000001"}


# ── research trades via archive ──

def _seed_duck_research(research_session, session) -> None:
    run_id = "bt_duck"
    for model in (BacktestTrade, BacktestEquityCurve, BacktestSignal, BacktestRun):
        research_session.execute(delete(model).where(model.backtest_run_id == run_id) if model is not BacktestRun else delete(model).where(model.id == run_id))
    session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.run_id == run_id))
    session.commit()
    research_session.commit()
    research_session.add(BacktestRun(id=run_id, dataset_id="duck_bt", strategy_name="test", snapshot_type="half_hour", status="completed"))
    research_session.add(BacktestTrade(backtest_run_id=run_id, code="000001", name="平安银行", side="buy", entry_price=10.0, exit_price=11.0, profit=1.0))
    research_session.commit()


def test_backtest_trades_fall_back_to_archive(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService
    from backend.services import BacktestService

    init_db()
    with SessionLocal() as session, ResearchSessionLocal() as research_session:
        _seed_duck_research(research_session, session)

        archived = ArchiveService(session, research_session=research_session, archive_dir=tmp_path).archive_research(
            run_id="bt_duck",
            older_than_days=0,
            keep_latest_per_group=0,
            apply=True,
        )
        assert archived["ok"] is True

        result = BacktestService(research_session).get_trades("bt_duck")
        assert result is not None
        assert result["source"] == "parquet_archive"
        assert result["items"][0]["code"] == "000001"
