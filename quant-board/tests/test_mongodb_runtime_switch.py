from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.data.models import OptimizationRun
from backend.utils import json_loads


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
    assert repo.saved_backtests[0].status == "completed"
    artifact_request = json_loads(repo.saved_backtests[0].request_json)
    assert artifact_request["artifact_type"] == "optimization_trial"
    assert artifact_request["artifactType"] == "optimization_trial"
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


def test_mongodb_mode_disables_supabase_health_probe_and_runs_hotlist_after_market(monkeypatch) -> None:
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
        monkeypatch.setattr(
            main,
            "run_after_market_once",
            lambda archive_limit=None, backup_limit=None, dry_run=False: {
                "ok": True,
                "steps": ["hotlistSentiment"],
                "dryRun": dry_run,
            },
        )
        after_market = client.post("/api/operations/after-market-once")
    finally:
        main.app.dependency_overrides.clear()

    assert health.status_code == 200, health.text
    assert health.json()["database"]["backup"]["configured"] is False
    assert smoke.status_code == 410, smoke.text
    assert after_market.status_code == 200, after_market.text
    assert after_market.json()["steps"] == ["hotlistSentiment"]


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


def test_dataset_list_reports_service_unavailable_when_mongodb_is_down(monkeypatch) -> None:
    import backend.main as main

    class UnavailableDatasetService:
        def __init__(self, session) -> None:
            pass

        def list_datasets(self) -> list[dict[str, Any]]:
            raise TimeoutError("mongo timed out")

    monkeypatch.setattr(main, "storage_source_label", lambda: "mongodb")
    monkeypatch.setattr(main, "DatasetService", UnavailableDatasetService)
    main.app.dependency_overrides[main.get_db] = lambda: None
    client = TestClient(main.app)
    try:
        response = client.get("/api/datasets")
    finally:
        main.app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "MongoDB primary is unavailable" in response.json()["detail"]


def test_delete_dataset_api_uses_mongodb_service_and_preserves_primary_guard(monkeypatch) -> None:
    import backend.main as main

    calls: list[str] = []

    class FakeDatasetService:
        def __init__(self, session) -> None:
            pass

        def delete_dataset(self, dataset_id: str) -> dict[str, Any] | None:
            calls.append(dataset_id)
            if dataset_id == "dragonboard_live":
                raise ValueError("snapshot primary dataset cannot be deleted from UI/API: dragonboard_live")
            return {
                "ok": True,
                "datasetId": dataset_id,
                "deleted": {
                    "snapshot_sector_rows": 1,
                    "snapshot_stock_rows": 1,
                    "snapshot_frames": 1,
                    "snapshot_records": 1,
                    "datasets": 1,
                },
                "source": "mongodb",
            }

    monkeypatch.setattr(main, "storage_source_label", lambda: "mongodb")
    monkeypatch.setattr(main, "DatasetService", FakeDatasetService)
    main.app.dependency_overrides[main.get_db] = lambda: None
    client = TestClient(main.app)
    try:
        deleted = client.delete("/api/datasets/ds_test")
        protected = client.delete("/api/datasets/dragonboard_live")
    finally:
        main.app.dependency_overrides.clear()

    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["source"] == "mongodb"
    assert protected.status_code == 400, protected.text
    assert protected.json()["detail"] == "snapshot primary dataset cannot be deleted from UI/API: dragonboard_live"
    assert calls == ["ds_test", "dragonboard_live"]


def test_pytest_cannot_connect_to_production_mongodb_database(monkeypatch) -> None:
    from backend.data import repository_factory

    repository_factory._runtime_mongodb_database = None
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_guard")
    monkeypatch.setattr(
        repository_factory,
        "get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "mongodb_uri": "mongodb://127.0.0.1:27017",
                "mongodb_database": "dragon_board_quant",
                "mongodb_connect_timeout_ms": 100,
                "mongodb_server_selection_timeout_ms": 100,
            },
        )(),
    )

    with pytest.raises(RuntimeError, match="pytest must not connect"):
        repository_factory.get_runtime_mongodb_database()

    repository_factory._runtime_mongodb_database = None


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
