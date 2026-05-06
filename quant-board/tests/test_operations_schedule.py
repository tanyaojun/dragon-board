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

        def latest_snapshot_trading_date(self, *, dataset_id: str, snapshot_type: str) -> str | None:
            calls.append(f"latest:{dataset_id}:{snapshot_type}")
            return "2026-05-06"

        def backup_snapshot_day_to_object(
            self,
            *,
            dataset_id: str,
            snapshot_type: str,
            trading_date: str,
            dry_run: bool = False,
        ) -> dict[str, Any]:
            calls.append(f"daily:{dataset_id}:{snapshot_type}:{trading_date}:{dry_run}")
            return {"ok": True, "archiveId": "snapshot_backup_dragonboard_live_half_hour_2026-05-06"}

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
    assert result["steps"] == ["dailySnapshotBackup", "archive", "pushArchiveBackup", "pruneBackup"]
    assert calls == [
        "latest:dragonboard_live:half_hour",
        "daily:dragonboard_live:half_hour:2026-05-06:False",
        "archive:2",
        "push:1",
        "prune:False",
    ]


def test_after_market_job_dry_run_skips_mutating_push_and_prune(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_archive(limit: int | None = None, *, dry_run: bool = False) -> dict[str, Any]:
        calls.append(f"archive:{limit}:{dry_run}")
        return {"ok": True, "skipped": True, "reason": "not_enough_history"}

    class FakeArchiveService:
        def __init__(self, _session: Any) -> None:
            pass

        def latest_snapshot_trading_date(self, *, dataset_id: str, snapshot_type: str) -> str | None:
            calls.append(f"latest:{dataset_id}:{snapshot_type}")
            return "2026-05-06"

        def backup_snapshot_day_to_object(
            self,
            *,
            dataset_id: str,
            snapshot_type: str,
            trading_date: str,
            dry_run: bool = False,
        ) -> dict[str, Any]:
            calls.append(f"daily:{dataset_id}:{snapshot_type}:{trading_date}:{dry_run}")
            return {"ok": True, "dryRun": dry_run}

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
    assert calls == [
        "latest:dragonboard_live:half_hour",
        "daily:dragonboard_live:half_hour:2026-05-06:True",
        "archive:2:True",
        "prune:True",
    ]


def test_after_market_job_stops_after_archive_failure(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_archive(limit: int | None = None, *, dry_run: bool = False) -> dict[str, Any]:
        calls.append(f"archive:{limit}")
        return {"ok": False, "error": {"code": "archive_failed"}}

    class FakeArchiveService:
        def __init__(self, _session: Any) -> None:
            pass

        def latest_snapshot_trading_date(self, *, dataset_id: str, snapshot_type: str) -> str | None:
            calls.append(f"latest:{dataset_id}:{snapshot_type}")
            return "2026-05-06"

        def backup_snapshot_day_to_object(
            self,
            *,
            dataset_id: str,
            snapshot_type: str,
            trading_date: str,
            dry_run: bool = False,
        ) -> dict[str, Any]:
            calls.append(f"daily:{dataset_id}:{snapshot_type}:{trading_date}:{dry_run}")
            return {"ok": True}

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
    assert calls == [
        "latest:dragonboard_live:half_hour",
        "daily:dragonboard_live:half_hour:2026-05-06:False",
        "archive:2",
    ]


def test_after_market_job_continues_after_daily_backup_failure(monkeypatch: Any) -> None:
    calls: list[str] = []

    def fake_archive(limit: int | None = None, *, dry_run: bool = False) -> dict[str, Any]:
        calls.append(f"archive:{limit}")
        return {"ok": True, "results": []}

    class FakeArchiveService:
        def __init__(self, _session: Any) -> None:
            pass

        def latest_snapshot_trading_date(self, *, dataset_id: str, snapshot_type: str) -> str | None:
            calls.append(f"latest:{dataset_id}:{snapshot_type}")
            return "2026-05-06"

        def backup_snapshot_day_to_object(
            self,
            *,
            dataset_id: str,
            snapshot_type: str,
            trading_date: str,
            dry_run: bool = False,
        ) -> dict[str, Any]:
            calls.append(f"daily:{dataset_id}:{snapshot_type}:{trading_date}:{dry_run}")
            return {"ok": False, "error": {"code": "object_backup_not_configured"}}

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

    assert result["ok"] is True
    assert result["results"]["dailySnapshotBackup"]["ok"] is False
    assert calls == [
        "latest:dragonboard_live:half_hour",
        "daily:dragonboard_live:half_hour:2026-05-06:False",
        "archive:2",
        "push:1",
        "prune:False",
    ]


def test_after_market_api_returns_structured_result(monkeypatch: Any) -> None:
    def fake_once(archive_limit: int | None = None, backup_limit: int | None = None, dry_run: bool = False) -> dict[str, Any]:
        return {
            "ok": True,
            "dryRun": dry_run,
            "archiveLimit": archive_limit,
            "backupLimit": backup_limit,
            "steps": ["dailySnapshotBackup", "archive", "pushArchiveBackup", "pruneBackup"],
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
