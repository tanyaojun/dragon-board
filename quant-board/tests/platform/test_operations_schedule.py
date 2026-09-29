from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

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


def test_after_market_job_in_mongodb_mode_runs_hotlist_sentiment_only(monkeypatch: Any) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "storage_backend": "mongodb",
                "archive_auto_dataset_id": "dragonboard_live",
                "archive_auto_snapshot_types": "half_hour",
            },
        )(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: "mongo-db",
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_hotlist_sentiment_for_latest_day",
        lambda db, dataset_id, snapshot_type, dry_run=False: calls.append(
            f"hotlist:{db}:{dataset_id}:{snapshot_type}:{dry_run}"
        )
        or {"ok": True, "written": 1, "tradingDate": "2026-06-05"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_backup_once",
        lambda *, dry_run=False, now=None: calls.append(f"backup:{dry_run}")
        or {"ok": True, "skipped": True, "reason": "dry_run"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_archive_auto_once",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy archive must not run")),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_snapshot_archive_once",
        lambda *, dry_run=False: calls.append(f"archiveR2:{dry_run}")
        or {
            "ok": True,
            "dryRun": dry_run,
            "snapshotTypes": {"half_hour": {"ok": True, "skipped": True, "reason": "dry_run"}},
        },
    )

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(dry_run=True)

    assert result["ok"] is True
    assert result["steps"] == ["hotlistSentiment", "mongodbBackup", "snapshotArchiveR2"]
    assert result["results"]["hotlistSentiment"]["written"] == 1
    assert result["results"]["mongodbBackup"]["skipped"] is True
    assert result["results"]["snapshotArchiveR2"]["ok"] is True
    assert calls == [
        "hotlist:mongo-db:dragonboard_live:half_hour:True",
        "backup:True",
        "archiveR2:True",
    ]


def test_after_market_job_in_mongodb_mode_surfaces_hotlist_sentiment_failure(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "storage_backend": "mongodb",
                "archive_auto_dataset_id": "dragonboard_live",
                "archive_auto_snapshot_types": "half_hour",
            },
        )(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: "mongo-db",
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_hotlist_sentiment_for_latest_day",
        lambda db, dataset_id, snapshot_type, dry_run=False: (_ for _ in ()).throw(
            RuntimeError("MongoDB connection lost")
        ),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_archive_auto_once",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy archive must not run")),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_snapshot_archive_once",
        lambda *, dry_run=False: {"ok": True, "dryRun": dry_run, "snapshotTypes": {}},
    )

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(dry_run=True)

    assert result["ok"] is False
    assert result["stoppedAt"] == "hotlistSentiment"
    assert result["results"]["hotlistSentiment"]["ok"] is False
    assert result["results"]["hotlistSentiment"]["error"]["code"] == "hotlist_sentiment_after_market_failed"
    assert "MongoDB connection lost" in result["results"]["hotlistSentiment"]["error"]["message"]


def test_after_market_job_in_mongodb_mode_hotlist_failure_still_backs_up(monkeypatch: Any) -> None:
    """hotlist 失败不阻断备份链：快照数据可能已入库，备份独立完成。"""
    calls: list[str] = []

    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "storage_backend": "mongodb",
                "archive_auto_dataset_id": "dragonboard_live",
                "archive_auto_snapshot_types": "half_hour",
            },
        )(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: "mongo-db",
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_hotlist_sentiment_for_latest_day",
        lambda db, dataset_id, snapshot_type, dry_run=False: (_ for _ in ()).throw(
            RuntimeError("MongoDB connection lost")
        ),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_backup_once",
        lambda *, dry_run=False, now=None: calls.append("backup")
        or {"ok": True, "backupId": "b1", "strategy": "light_dump"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_snapshot_archive_once",
        lambda *, dry_run=False: calls.append("archiveR2")
        or {"ok": True, "dryRun": dry_run, "snapshotTypes": {}},
    )

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(dry_run=False)

    assert result["ok"] is False
    assert result["stoppedAt"] == "hotlistSentiment"
    assert calls == ["backup", "archiveR2"]
    assert result["results"]["mongodbBackup"]["ok"] is True
    assert result["results"]["mongodbBackup"]["backupId"] == "b1"


def test_after_market_job_in_mongodb_mode_surfaces_backup_failure(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type(
            "Settings",
            (),
            {
                "storage_backend": "mongodb",
                "archive_auto_dataset_id": "dragonboard_live",
                "archive_auto_snapshot_types": "half_hour",
            },
        )(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: "mongo-db",
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_hotlist_sentiment_for_latest_day",
        lambda db, dataset_id, snapshot_type, dry_run=False: {"ok": True, "written": 1},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_backup_once",
        lambda *, dry_run=False, now=None: {
            "ok": False,
            "friday": False,
            "strategy": "light_dump",
            "failedStep": "create",
            "error": {"code": "mongodump_failed", "returncode": 2},
        },
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_snapshot_archive_once",
        lambda *, dry_run=False: {"ok": True, "dryRun": dry_run, "snapshotTypes": {}},
    )

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(dry_run=False)

    assert result["ok"] is False
    assert result["stoppedAt"] == "mongodbBackup"
    assert result["results"]["hotlistSentiment"]["ok"] is True
    assert result["results"]["mongodbBackup"]["failedStep"] == "create"


class FakeBackupService:
    """按调用顺序记录备份链动作。"""

    def __init__(
        self,
        calls: list[str],
        *,
        full_ok: bool = True,
        verify_ok: bool = True,
        push_ok: bool = True,
        last_full_info: dict[str, Any] | None = None,
        has_object_store: bool = False,
    ) -> None:
        self.calls = calls
        self.full_ok = full_ok
        self.verify_ok = verify_ok
        self.push_ok = push_ok
        self.last_full_info = last_full_info
        self.object_store = object() if has_object_store else None

    def latest_full_backup_info(self) -> dict[str, Any] | None:
        self.calls.append("latest_full")
        return self.last_full_info

    def create_full_backup(self, *, backup_id: str | None = None) -> dict[str, Any]:
        self.calls.append("create_full")
        if not self.full_ok:
            return {"ok": False, "error": {"code": "mongodump_failed", "returncode": 2}}
        return {"ok": True, "backupId": backup_id or "b-full"}

    def create_light_backup(self, *, backup_id: str | None = None) -> dict[str, Any]:
        self.calls.append("create_light")
        return {"ok": True, "backupId": backup_id or "b-light"}

    def verify_backup(self, backup_id: str) -> dict[str, Any]:
        self.calls.append(f"verify:{backup_id}")
        if not self.verify_ok:
            return {"ok": False, "error": {"code": "backup_doc_count_mismatch"}}
        return {"ok": True}

    def prune_local_backups(self, *, dry_run: bool = False) -> dict[str, Any]:
        self.calls.append(f"prune:{dry_run}")
        return {"ok": True, "deleted": [{"backupId": "old"}]}

    def push_backup(self, backup_id: str) -> dict[str, Any]:
        self.calls.append(f"push:{backup_id}")
        if not self.push_ok:
            return {"ok": False, "error": {"code": "upload_failed"}}
        return {"ok": True, "files": [{"name": "manifest.json"}]}


def test_run_mongodb_backup_once_friday_runs_full_with_push(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_mongodb_backup_service",
        lambda: FakeBackupService(calls),
    )
    monkeypatch.setattr("backend.operations.schedule.is_trading_day", lambda day: True)

    from backend.operations.schedule import run_mongodb_backup_once

    friday = datetime(2026, 9, 18, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert friday.weekday() == 4

    result = run_mongodb_backup_once(now=friday)

    assert result["ok"] is True
    assert result["friday"] is True
    assert result["strategy"] == "full_dump"
    assert result["backupId"] == "b-full"
    assert result["push"]["ok"] is True
    assert calls == ["create_full", "verify:b-full", "prune:False", "push:b-full"]


def test_run_mongodb_backup_once_weekday_runs_light_without_push(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_mongodb_backup_service",
        lambda: FakeBackupService(calls),
    )
    monkeypatch.setattr("backend.operations.schedule.is_trading_day", lambda day: True)

    from backend.operations.schedule import run_mongodb_backup_once

    wednesday = datetime(2026, 9, 16, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert wednesday.weekday() == 2

    result = run_mongodb_backup_once(now=wednesday)

    assert result["ok"] is True
    assert result["friday"] is False
    assert result["strategy"] == "light_dump"
    assert "push" not in result
    assert all(not call.startswith("push") for call in calls)
    assert calls == ["latest_full", "create_light", "verify:b-light", "prune:False"]
    # 未配置 object store 且查不到全量历史：保持 light 并结构化记录原因
    assert result["lastFullBackup"]["skipped"] is True
    assert "fullCatchUp" not in result["lastFullBackup"]


def test_run_mongodb_backup_once_structured_failure_on_create(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_mongodb_backup_service",
        lambda: FakeBackupService(calls, full_ok=False),
    )
    monkeypatch.setattr("backend.operations.schedule.is_trading_day", lambda day: True)

    from backend.operations.schedule import run_mongodb_backup_once

    friday = datetime(2026, 9, 18, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = run_mongodb_backup_once(now=friday)

    assert result["ok"] is False
    assert result["failedStep"] == "create"
    assert result["error"]["code"] == "mongodump_failed"
    # create 失败后不再 verify/prune/push
    assert calls == ["create_full"]


def test_run_mongodb_backup_once_structured_failure_on_verify(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_mongodb_backup_service",
        lambda: FakeBackupService(calls, verify_ok=False),
    )
    monkeypatch.setattr("backend.operations.schedule.is_trading_day", lambda day: True)

    from backend.operations.schedule import run_mongodb_backup_once

    wednesday = datetime(2026, 9, 16, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = run_mongodb_backup_once(now=wednesday)

    assert result["ok"] is False
    assert result["failedStep"] == "verify"
    assert calls == ["latest_full", "create_light", "verify:b-light"]


def test_run_mongodb_backup_once_skips_non_trading_day_and_dry_run(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_mongodb_backup_service",
        lambda: FakeBackupService(calls),
    )
    monkeypatch.setattr("backend.operations.schedule.is_trading_day", lambda day: False)

    from backend.operations.schedule import run_mongodb_backup_once

    saturday = datetime(2026, 9, 19, 15, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    non_trading = run_mongodb_backup_once(now=saturday)
    dry_run = run_mongodb_backup_once(dry_run=True, now=saturday)

    assert non_trading["ok"] is True
    assert non_trading["skipped"] is True
    assert non_trading["reason"] == "non_trading_day"
    assert dry_run["skipped"] is True
    assert dry_run["reason"] == "dry_run"
    assert calls == []


def test_run_mongodb_backup_once_forces_full_when_last_full_older_than_8_days(monkeypatch: Any) -> None:
    calls: list[str] = []
    last_full = {
        "backupId": "20260904T080002Z",
        "source": "remote",
        "createdAt": datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc),
    }
    monkeypatch.setattr(
        "backend.operations.schedule.get_mongodb_backup_service",
        lambda: FakeBackupService(calls, last_full_info=last_full, has_object_store=True),
    )
    monkeypatch.setattr("backend.operations.schedule.is_trading_day", lambda day: True)

    from backend.operations.schedule import run_mongodb_backup_once

    monday = datetime(2026, 9, 21, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = run_mongodb_backup_once(now=monday)

    # 错过周五后周一补全量：strategy=full_dump 且走完整 push 链
    assert result["strategy"] == "full_dump"
    assert result["lastFullBackup"]["backupId"] == "20260904T080002Z"
    assert result["lastFullBackup"]["fullCatchUp"]["reason"] == "last_full_older_than_8_days"
    assert calls == [
        "latest_full",
        "create_full",
        "verify:b-full",
        "prune:False",
        "push:b-full",
    ]


def test_run_mongodb_backup_once_keeps_light_when_last_full_recent(monkeypatch: Any) -> None:
    calls: list[str] = []
    last_full = {
        "backupId": "20260925T100000Z",
        "source": "remote",
        "createdAt": datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc),
    }
    monkeypatch.setattr(
        "backend.operations.schedule.get_mongodb_backup_service",
        lambda: FakeBackupService(calls, last_full_info=last_full, has_object_store=True),
    )
    monkeypatch.setattr("backend.operations.schedule.is_trading_day", lambda day: True)

    from backend.operations.schedule import run_mongodb_backup_once

    monday = datetime(2026, 9, 28, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = run_mongodb_backup_once(now=monday)

    assert result["strategy"] == "light_dump"
    assert "fullCatchUp" not in result["lastFullBackup"]
    assert "push" not in result
    assert calls == ["latest_full", "create_light", "verify:b-light", "prune:False"]


def test_run_mongodb_backup_once_no_full_history_with_object_store_forces_first_full(monkeypatch: Any) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_mongodb_backup_service",
        lambda: FakeBackupService(calls, last_full_info=None, has_object_store=True),
    )
    monkeypatch.setattr("backend.operations.schedule.is_trading_day", lambda day: True)

    from backend.operations.schedule import run_mongodb_backup_once

    wednesday = datetime(2026, 9, 16, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    result = run_mongodb_backup_once(now=wednesday)

    assert result["strategy"] == "full_dump"
    assert result["lastFullBackup"]["fullCatchUp"]["reason"] == "no_full_backup_found"
    assert calls == ["latest_full", "create_full", "verify:b-full", "prune:False", "push:b-full"]
