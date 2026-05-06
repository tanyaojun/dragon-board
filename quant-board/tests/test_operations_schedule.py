from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.main import app


def test_after_market_job_runs_archive_push_and_prune_in_order(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_archive(limit: int | None = None, *, dry_run: bool = False) -> dict[str, Any]:
        calls.append(f"archive:{limit}")
        return {"ok": True, "results": [], "cutoff": "2026-04-20"}

    class FakeArchiveService:
        def __init__(self, _session: Any) -> None:
            pass

        def push_archive_backup(self, *, limit: int | None = None) -> dict[str, Any]:
            calls.append(f"push:{limit}")
            return {"ok": True, "pushed": 1, "manifests": [{"archiveId": "a1"}]}

    def fake_prune(*, dry_run: bool = False) -> dict[str, Any]:
        calls.append(f"prune:{dry_run}")
        return {"ok": True, "dryRun": dry_run, "results": [], "errors": []}

    monkeypatch.setattr("backend.operations.schedule.run_archive_auto_once", fake_archive)
    monkeypatch.setattr("backend.operations.schedule.ArchiveService", FakeArchiveService)
    monkeypatch.setattr("backend.operations.schedule.run_backup_retention_once", fake_prune)

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(archive_limit=2, backup_limit=1)

    assert result["ok"] is True
    assert result["steps"] == ["archive", "pushArchiveBackup", "pruneBackup"]
    assert calls == ["archive:2", "push:1", "prune:False"]


def test_after_market_job_dry_run_skips_mutating_push_and_prune(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_archive(limit: int | None = None, *, dry_run: bool = False) -> dict[str, Any]:
        calls.append(f"archive:{limit}:{dry_run}")
        return {"ok": True, "skipped": True, "reason": "not_enough_history"}

    class FakeArchiveService:
        def __init__(self, _session: Any) -> None:
            pass

        def push_archive_backup(self, *, limit: int | None = None) -> dict[str, Any]:
            calls.append(f"push:{limit}")
            return {"ok": True}

    def fake_prune(*, dry_run: bool = False) -> dict[str, Any]:
        calls.append(f"prune:{dry_run}")
        return {"ok": True, "dryRun": dry_run}

    monkeypatch.setattr("backend.operations.schedule.run_archive_auto_once", fake_archive)
    monkeypatch.setattr("backend.operations.schedule.ArchiveService", FakeArchiveService)
    monkeypatch.setattr("backend.operations.schedule.run_backup_retention_once", fake_prune)

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(archive_limit=2, backup_limit=1, dry_run=True)

    assert result["ok"] is True
    assert result["dryRun"] is True
    assert result["results"]["pushArchiveBackup"]["skipped"] is True
    assert calls == ["archive:2:True", "prune:True"]


def test_after_market_job_stops_after_archive_failure(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_archive(limit: int | None = None, *, dry_run: bool = False) -> dict[str, Any]:
        calls.append(f"archive:{limit}")
        return {"ok": False, "error": {"code": "archive_failed"}}

    class FakeArchiveService:
        def __init__(self, _session: Any) -> None:
            pass

        def push_archive_backup(self, *, limit: int | None = None) -> dict[str, Any]:
            calls.append(f"push:{limit}")
            return {"ok": True}

    def fake_prune(*, dry_run: bool = False) -> dict[str, Any]:
        calls.append(f"prune:{dry_run}")
        return {"ok": True}

    monkeypatch.setattr("backend.operations.schedule.run_archive_auto_once", fake_archive)
    monkeypatch.setattr("backend.operations.schedule.ArchiveService", FakeArchiveService)
    monkeypatch.setattr("backend.operations.schedule.run_backup_retention_once", fake_prune)

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(archive_limit=2, backup_limit=1)

    assert result["ok"] is False
    assert result["stoppedAt"] == "archive"
    assert calls == ["archive:2"]


def test_after_market_api_returns_structured_result(monkeypatch: Any) -> None:
    def fake_once(archive_limit: int | None = None, backup_limit: int | None = None, dry_run: bool = False) -> dict[str, Any]:
        return {
            "ok": True,
            "dryRun": dry_run,
            "archiveLimit": archive_limit,
            "backupLimit": backup_limit,
            "steps": ["archive", "pushArchiveBackup", "pruneBackup"],
        }

    monkeypatch.setattr("backend.main.run_after_market_once", fake_once)

    response = TestClient(app).post(
        "/api/operations/after-market-once?archive_limit=3&backup_limit=2&dry_run=true"
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["dryRun"] is True
    assert response.json()["archiveLimit"] == 3
    assert response.json()["backupLimit"] == 2
