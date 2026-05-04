from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete, select

from backend.data.database import ResearchSessionLocal, SessionLocal, init_db
from backend.data.models import ArchiveManifestModel, BacktestEquityCurve, BacktestRun, BacktestSignal, BacktestTrade


def _seed_backtest_run(snapshot_session, research_session, run_id: str) -> None:
    _cleanup_research(snapshot_session, research_session, run_id)
    research_session.add(
        BacktestRun(
            id=run_id,
            dataset_id="research_ds",
            strategy_name="rank_trend_candidate",
            snapshot_type="half_hour",
            status="completed",
        )
    )
    research_session.add(
        BacktestTrade(
            backtest_run_id=run_id,
            code="000001",
            name="平安银行",
            side="buy",
            entry_price=10.0,
            exit_price=11.0,
            profit=1.0,
        )
    )
    research_session.add(
        BacktestEquityCurve(
            backtest_run_id=run_id,
            snapshot_id="snap_1",
            equity=1000000.0,
        )
    )
    research_session.add(
        BacktestSignal(
            backtest_run_id=run_id,
            snapshot_id="snap_1",
            code="000001",
            signal="buy",
            candidate_tier="A",
        )
    )
    research_session.commit()


def _cleanup_research(snapshot_session, research_session, run_id: str) -> None:
    for model in (BacktestTrade, BacktestEquityCurve, BacktestSignal, BacktestRun):
        research_session.execute(delete(model).where(model.backtest_run_id == run_id) if model is not BacktestRun else delete(model).where(model.id == run_id))
    snapshot_session.execute(delete(ArchiveManifestModel).where(ArchiveManifestModel.run_id == run_id))
    snapshot_session.commit()
    research_session.commit()


def test_research_archive_dry_run_does_not_write_or_delete(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as snap_session, ResearchSessionLocal() as research_session:
        _seed_backtest_run(snap_session, research_session, "bt_dry")
        service = ArchiveService(snap_session, research_session=research_session, archive_dir=tmp_path)

        result = service.archive_research(
            run_id="bt_dry",
            older_than_days=0,
            keep_latest_per_group=0,
            dry_run=True,
        )

        assert result["ok"] is True
        assert result["dryRun"] is True
        assert not list(tmp_path.rglob("*.parquet"))
        assert research_session.scalar(select(BacktestTrade).where(BacktestTrade.backtest_run_id == "bt_dry")) is not None


def test_research_archive_apply_writes_parquet_and_cleans_detail_rows(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as snap_session, ResearchSessionLocal() as research_session:
        _seed_backtest_run(snap_session, research_session, "bt_apply")
        service = ArchiveService(snap_session, research_session=research_session, archive_dir=tmp_path)

        result = service.archive_research(
            run_id="bt_apply",
            older_than_days=0,
            keep_latest_per_group=0,
            apply=True,
        )

        assert result["ok"] is True
        runs = result["runs"]
        assert len(runs) == 1
        assert runs[0]["status"] == "verified"
        assert runs[0]["deletedFromSqlite"]["trades"] == 1
        local_path = runs[0]["localPath"]
        assert (Path(local_path) / "trades.parquet").exists()

        # restore
        restored = service.restore_archive(runs[0]["archiveId"], apply=True)
        assert restored["ok"] is True
        assert restored["restored"]["trades"] == 1
        assert research_session.scalar(select(BacktestTrade).where(BacktestTrade.backtest_run_id == "bt_apply")) is not None


def test_research_archive_preserves_run_on_restore(tmp_path: Path) -> None:
    from backend.data.archive.service import ArchiveService

    init_db()
    with SessionLocal() as snap_session, ResearchSessionLocal() as research_session:
        _seed_backtest_run(snap_session, research_session, "bt_preserve")
        service = ArchiveService(snap_session, research_session=research_session, archive_dir=tmp_path)

        result = service.archive_research(run_id="bt_preserve", older_than_days=0, keep_latest_per_group=0, apply=True)
        assert result["ok"] is True

        # re-seed research data directly (without _seed_backtest_run which
        # would delete the archive manifest) so the second call sees
        # identical data and hits the dedup path
        from backend.data.models import BacktestEquityCurve, BacktestRun, BacktestSignal, BacktestTrade
        from sqlalchemy import delete
        for model in (BacktestTrade, BacktestEquityCurve, BacktestSignal):
            research_session.execute(delete(model).where(model.backtest_run_id == "bt_preserve"))
        research_session.execute(delete(BacktestRun).where(BacktestRun.id == "bt_preserve"))
        research_session.commit()
        research_session.add(BacktestRun(id="bt_preserve", dataset_id="research_ds", strategy_name="rank_trend_candidate", snapshot_type="half_hour", status="completed"))
        research_session.add(BacktestTrade(backtest_run_id="bt_preserve", code="000001", name="平安银行", side="buy", entry_price=10.0, exit_price=11.0, profit=1.0))
        research_session.add(BacktestEquityCurve(backtest_run_id="bt_preserve", snapshot_id="snap_1", equity=1000000.0))
        research_session.add(BacktestSignal(backtest_run_id="bt_preserve", snapshot_id="snap_1", code="000001", signal="buy", candidate_tier="A"))
        research_session.commit()
        result2 = service.archive_research(run_id="bt_preserve", older_than_days=0, keep_latest_per_group=0, apply=True)
        assert result2["ok"] is True
        run = result2["runs"][0]
        assert run.get("deduped") is True
