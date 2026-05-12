from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.data.models import OptimizationRun


class FakeRepo:
    def __init__(self) -> None:
        self.saved_backtests: list[Any] = []
        self.saved_optimizations: list[OptimizationRun] = []

    def save_backtest_run(self, run) -> Any:
        self.saved_backtests.append(run)
        return run

    def save_optimization_run(self, run: OptimizationRun) -> OptimizationRun:
        self.saved_optimizations.append(run)
        return run

    def save_quality_report(self, report: dict[str, Any]) -> bool:
        return True

    def load_frame_bundles(self, dataset_id: str, snapshot_type: str = "half_hour") -> list[dict[str, Any]]:
        return [{"snapshotId": "s1", "type": snapshot_type, "rows": [], "entities": []}]

    def close(self) -> None:
        pass


class DummySession:
    def __enter__(self) -> None:
        raise AssertionError("SQLite session_factory must not be used in mongodb mode")

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_optimization_background_job_uses_repository_factory_in_mongodb_mode(monkeypatch) -> None:
    import backend.optimization.jobs as jobs

    repo = FakeRepo()

    monkeypatch.setattr(jobs, "create_repository", lambda session: repo)
    monkeypatch.setattr(jobs, "storage_source_label", lambda: "mongodb")
    monkeypatch.setattr(
        jobs.OptimizationRunner,
        "run",
        lambda self, frames, request: {
            "score": 1,
            "backtestArtifacts": [
                {
                    "runId": "bt_1",
                    "request": {"datasetId": "ds_1"},
                    "result": {"metrics": {"score": 1}},
                    "configHash": "bt_hash",
                }
            ],
        },
    )

    jobs._run_job(
        "opt_1",
        [{"snapshotId": "s1"}],
        {"method": "grid"},
        "ds_1",
        "half_hour",
        "rank_trend_candidate",
        7,
        "opt_hash",
        {"datasetId": "ds_1"},
        lambda: DummySession(),
    )

    assert [run.id for run in repo.saved_backtests] == ["bt_1"]
    assert [run.id for run in repo.saved_optimizations] == ["opt_1"]
    assert repo.saved_optimizations[0].status == "completed"


def test_theme_research_builder_reads_frames_from_repository_factory(monkeypatch) -> None:
    service_path = Path(__file__).resolve().parents[1] / "backend" / "services" / "theme_research_service.py"
    spec = importlib.util.spec_from_file_location("theme_research_service_under_test", service_path)
    assert spec and spec.loader
    service = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(service)

    repo = FakeRepo()

    monkeypatch.setattr(service, "create_repository", lambda session: repo)
    monkeypatch.setattr(service, "ThemeResearchRepository", lambda: repo)
    monkeypatch.setattr(service, "storage_source_label", lambda: "mongodb")
    monkeypatch.setattr(
        service.ThemeTrendPythonEngine,
        "replay_sequence_typed",
        lambda self, frames, config, meta: service.ThemeTrendResult(
            factors=[],
            exposures=[],
            signals=[],
            qualityReport=service.ThemeQualityReport(
                passed=True,
                severity="pass",
                researchGrade="research_ready",
                issues=[],
                warnings=[],
                stats={},
                themeCoverage=0.0,
                frameCount=1,
                stockCount=0,
                themeCount=0,
            ),
            strategyVersion=service.STRATEGY_VERSION,
            factorVersion=service.FACTOR_VERSION,
            signalVersion=service.SIGNAL_VERSION,
            meta={},
        ),
    )

    result = service.build_theme_research("ds_1", "half_hour")

    assert result.qualityReport.passed is True


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/storage/archive/snapshots/preview", {}),
        ("post", "/api/storage/archive/snapshots", {}),
        ("post", "/api/storage/archive/research/preview", {}),
        ("post", "/api/storage/archive/research", {}),
        ("get", "/api/storage/archive/manifests", None),
        ("post", "/api/storage/archive/verify", {"archiveId": "a1"}),
        ("post", "/api/storage/archive/restore", {"archiveId": "a1"}),
        ("post", "/api/storage/archive/push-backup", {}),
        ("post", "/api/storage/archive/pull-backup", {"archiveId": "a1"}),
        ("post", "/api/migrations/snapshots/import-json", {"bundle": {"items": []}}),
    ],
)
def test_sqlite_archive_api_is_gone_in_mongodb_mode(monkeypatch, method: str, path: str, payload: dict[str, Any] | None) -> None:
    import backend.main as main

    monkeypatch.setattr(main, "storage_source_label", lambda: "mongodb")
    main.app.dependency_overrides[main.get_db] = lambda: None
    client = TestClient(main.app)
    try:
        response = client.get(path) if method == "get" else client.post(path, json=payload or {})
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 410, response.text


def test_mongodb_mode_disables_supabase_health_probe_and_after_market_workflow(monkeypatch) -> None:
    import backend.main as main

    monkeypatch.setattr(main, "storage_source_label", lambda: "mongodb")
    monkeypatch.setattr(main, "primary_status", lambda: {"mode": "mongodb", "connected": True})
    monkeypatch.setattr(main, "theme_status", lambda: {"source": "mongodb", "connected": True})
    monkeypatch.setattr(
        main,
        "get_backup_client",
        lambda: (_ for _ in ()).throw(AssertionError("Supabase backup client must not be touched")),
    )
    main.app.dependency_overrides[main.get_db] = lambda: None
    client = TestClient(main.app)
    try:
        health = client.get("/api/health", params={"deep": "true"})
        smoke = client.post("/api/sync/smoke-backup")
        after_market = client.post("/api/operations/after-market-once")
    finally:
        main.app.dependency_overrides.clear()

    assert health.status_code == 200, health.text
    assert health.json()["database"]["backup"]["configured"] is False
    assert smoke.status_code == 410, smoke.text
    assert after_market.status_code == 410, after_market.text


def test_theme_status_reports_mongodb_connection_failure(monkeypatch) -> None:
    import backend.data.theme_database as theme_database

    monkeypatch.setattr(
        theme_database,
        "get_settings",
        lambda: type("Settings", (), {"storage_backend": "mongodb"})(),
    )
    monkeypatch.setattr(
        "backend.data.repository_factory.mongodb_status",
        lambda: {
            "configured": False,
            "connected": False,
            "mode": "mongodb",
            "database": "dragon_board_quant",
            "last_error": "missing uri",
        },
    )

    status = theme_database.theme_status()

    assert status["source"] == "mongodb"
    assert status["connected"] is False
    assert status["configured"] is False
    assert status["last_error"] == "missing uri"


@pytest.mark.parametrize(
    "command",
    [
        "push-backup",
        "push-outbox",
        "pull-backup",
        "smoke-backup",
        "prune-backup",
        "migrate-snapshots",
        "migrate-legacy-db",
        "compact-json-fields",
        "archive-snapshots",
        "archive-research",
        "verify-archive",
        "restore-archive",
        "archive-auto-once",
        "push-archive-backup",
        "backup-snapshot-day",
        "after-market-once",
        "pull-archive-backup",
        "verify-snapshot-migration",
    ],
)
def test_legacy_cli_storage_commands_are_rejected_in_mongodb_mode(monkeypatch, command: str) -> None:
    import backend.cli as cli

    monkeypatch.setattr(cli, "get_settings", lambda: type("Settings", (), {"storage_backend": "mongodb"})())

    with pytest.raises(SystemExit) as exc_info:
        cli.reject_legacy_storage_command_in_mongodb(command)

    assert command in str(exc_info.value)
