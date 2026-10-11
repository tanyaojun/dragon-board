from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from backend.main import app



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
    assert result["steps"] == ["hotlistSentiment", "mongodbBackup", "snapshotArchiveR2", "phasePulse", "jiuyanLabel", "phaseBand", "deepValley", "peakRevalidate", "jevDailyLine", "calibDriftMonitor", "amountVsSameRecord", "jevVoteRecheck"]
    assert result["results"]["amountVsSameRecord"]["skipped"] is True  # dry_run 短路
    assert result["results"]["jevDailyLine"]["skipped"] is True  # dry_run 短路
    assert result["results"]["jevVoteRecheck"]["skipped"] is True  # dry_run 短路
    assert result["results"]["calibDriftMonitor"]["skipped"] is True  # dry_run 短路
    assert result["results"]["hotlistSentiment"]["written"] == 1
    assert result["results"]["mongodbBackup"]["skipped"] is True
    assert result["results"]["snapshotArchiveR2"]["ok"] is True
    assert result["results"]["phasePulse"]["skipped"] is True  # dry_run 短路
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


def test_phase_pulse_step_skipped_without_eod(monkeypatch: Any) -> None:
    """门控：当日无 EOD 情绪文档（非交易日/数据未落）→ 跳过且不碰子进程。"""
    from backend.operations import schedule

    class FakeCollection:
        def find_one(self, _query, _projection=None):
            return None

    class FakeDb:
        def __getitem__(self, name):
            assert name == "hotlist_sentiment"
            return FakeCollection()

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type("Settings", (), {"archive_auto_dataset_id": "dragonboard_live", "archive_auto_snapshot_types": "half_hour"})(),
    )
    ran: list[str] = []
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: ran.append("subprocess"))

    result = schedule._run_phase_pulse_step("2026-10-03")  # 国庆假期，无 EOD

    assert result["ok"] is True and result["skipped"] is True
    assert "no EOD doc" in result["reason"]
    assert ran == []  # 子进程未启动


def test_phase_pulse_step_runs_subprocess_on_trading_day(monkeypatch, tmp_path) -> None:
    """交易日（EOD 已落）→ 子进程隔离执行；摘要从产物 JSON 读取。"""
    from backend.operations import schedule

    class FakeCollection:
        def find_one(self, _query, _projection=None):
            return {"_id": "x"}

    class FakeDb:
        def __getitem__(self, name):
            return FakeCollection()

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type("Settings", (), {"archive_auto_dataset_id": "dragonboard_live", "archive_auto_snapshot_types": "half_hour"})(),
    )
    monkeypatch.setattr(schedule, "_PULSE_OUT_DIR", tmp_path)
    (tmp_path / "pulse-2026-10.json").write_text(
        '{"month": "2026-10", "tradeCount": 3, "ab": {"delta": {"netReturnSaved": 0.055}}}',
        encoding="utf-8",
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        return type("Proc", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)

    result = schedule._run_phase_pulse_step("2026-10-12")

    assert result["ok"] is True and result["month"] == "2026-10"
    assert result["summary"]["tradeCount"] == 3
    assert result["summary"]["netReturnSaved"] == 0.055
    assert "backend.operations.phase_pulse" in " ".join(captured["cmd"])
    assert "--month" in captured["cmd"] and "2026-10" in captured["cmd"]


def test_phase_pulse_failure_does_not_flip_chain(monkeypatch: Any) -> None:
    """advisory 语义：脉拍失败只进 results，不翻转整体 ok，也不产生 stoppedAt。"""
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type("Settings", (), {"storage_backend": "mongodb", "archive_auto_dataset_id": "dragonboard_live", "archive_auto_snapshot_types": "half_hour"})(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: "mongo-db",
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_hotlist_sentiment_for_latest_day",
        lambda db, dataset_id, snapshot_type, dry_run=False: calls.append("hotlist") or {"ok": True, "written": 1},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_backup_once",
        lambda *, dry_run=False, now=None: calls.append("backup") or {"ok": True, "skipped": True, "reason": "dry_run"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_snapshot_archive_once",
        lambda *, dry_run=False: calls.append("archiveR2") or {"ok": True, "dryRun": True, "snapshotTypes": {}},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_phase_pulse_step",
        lambda today, dry_run=False: calls.append("pulse") or {"ok": False, "error": {"code": "phase_pulse_failed", "message": "boom"}},
    )

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(dry_run=True)

    assert result["ok"] is True  # advisory 步失败不翻转
    assert "stoppedAt" not in result  # ok 时无 stoppedAt 键
    assert result["results"]["phasePulse"]["ok"] is False
    assert calls == ["hotlist", "backup", "archiveR2", "pulse"]


def test_phase_band_gate_skips_without_material(monkeypatch: Any) -> None:
    """无韭研 final（非交易日/缺料）→ 哨兵跳过，子进程不启动。"""
    from backend.operations import schedule

    class FakeCollection:
        def find_one(self, _query, _projection=None):
            return None

    class FakeDb:
        def __getitem__(self, name):
            return FakeCollection()

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    ran: list[str] = []
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: ran.append("subprocess"))

    result = schedule._run_phase_band_step("2026-10-11")  # 周六，无 final

    assert result["ok"] is True and result["skipped"] is True
    assert "no jiuyan final" in result["reason"]
    assert ran == []  # 子进程未启动


def test_phase_band_step_runs_subprocess_on_material_day(monkeypatch: Any) -> None:
    """原料齐（final+15:00 帧）→ 子进程调 --phase-band-day，PHASE 文档回读判档。"""
    from backend.operations import schedule

    class FakeCol:
        def __init__(self, name):
            self.name = name

        def find_one(self, _query, _projection=None):
            if self.name == "hotlist_jev_driver_labels":
                return {"phaseBand": "cold_lt40", "computedAt": "2099-01-01T00:00:00"}
            return {"_id": "x"}  # jiuyan final / 15:00 帧均存在

    class FakeDb:
        def __getitem__(self, name):
            return FakeCol(name)

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("Proc", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)

    result = schedule._run_phase_band_step("2026-10-12")

    assert result["ok"] is True and result["phaseBand"] == "cold_lt40"
    assert result["mongoFresh"] is True
    assert "backend.operations.jev_label_jiuyan" in " ".join(captured["cmd"])
    assert "--phase-band-day" in captured["cmd"] and "2026-10-12" in captured["cmd"]


def test_phase_band_failure_does_not_flip_chain(monkeypatch: Any) -> None:
    """advisory 语义：哨兵失败只进 results，不翻转整体 ok。"""
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type("Settings", (), {"storage_backend": "mongodb", "archive_auto_dataset_id": "dragonboard_live", "archive_auto_snapshot_types": "half_hour"})(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: "mongo-db",
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_hotlist_sentiment_for_latest_day",
        lambda db, dataset_id, snapshot_type, dry_run=False: calls.append("hotlist") or {"ok": True, "written": 1},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_backup_once",
        lambda *, dry_run=False, now=None: calls.append("backup") or {"ok": True, "skipped": True, "reason": "dry_run"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_snapshot_archive_once",
        lambda *, dry_run=False: calls.append("archiveR2") or {"ok": True, "dryRun": True, "snapshotTypes": {}},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_phase_pulse_step",
        lambda today, dry_run=False: calls.append("pulse") or {"ok": True, "month": "2026-10"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_phase_band_step",
        lambda today, dry_run=False: calls.append("phaseBand") or {"ok": False, "error": {"code": "phase_band_failed", "message": "boom"}},
    )

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(dry_run=True)

    assert result["ok"] is True
    assert result["results"]["phaseBand"]["ok"] is False
    assert calls == ["hotlist", "backup", "archiveR2", "pulse", "phaseBand"]


def test_jiuyan_label_gate_skips_without_material(monkeypatch: Any) -> None:
    """无韭研 final → 个股打标跳过，子进程不启动。"""
    from backend.operations import schedule

    class FakeCollection:
        def find_one(self, _query, _projection=None):
            return None

    class FakeDb:
        def __getitem__(self, name):
            return FakeCollection()

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    ran: list[str] = []
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: ran.append("subprocess"))

    result = schedule._run_jiuyan_label_step("2026-10-11")

    assert result["ok"] is True and result["skipped"] is True
    assert "no jiuyan final" in result["reason"]
    assert ran == []


def test_jiuyan_label_step_runs_subprocess_and_counts(monkeypatch: Any) -> None:
    """原料齐 → 子进程跑当日个股打标，回读当日 ok 标签数。"""
    from backend.operations import schedule

    class FakeCol:
        def __init__(self, name):
            self.name = name

        def find(self, _query, _projection=None):
            # 批次A：验证查询改拉 status 字段统计 ok/降级面（degradedToday）
            return [{"_id": "1", "status": "ok"}, {"_id": "2", "status": "ok"}]

        def find_one(self, _query, _projection=None):
            return {"_id": "x"}

    class FakeDb:
        def __getitem__(self, name):
            return FakeCol(name)

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("Proc", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)

    result = schedule._run_jiuyan_label_step("2026-10-12")

    assert result["ok"] is True and result["labeledToday"] == 2
    assert result["degradedToday"] == 0  # 批次A I5：降级面结构化回传
    assert "backend.operations.jev_label_jiuyan" in " ".join(captured["cmd"])
    assert "--start" in captured["cmd"] and "2026-10-12" in captured["cmd"]


def test_jiuyan_stock_phase_gate_default_off(monkeypatch: Any) -> None:
    """F2 成本防火墙（review P1-E）：JIUYAN_STOCK_PHASE_ENABLED 未设 → 命令不含 --with-stock-phase（零额外 token）。"""
    from backend.operations import schedule

    class FakeCol:
        def find(self, _query, _projection=None):
            return [{"_id": "1"}]

        def find_one(self, _query, _projection=None):
            return {"_id": "x"}

    class FakeDb:
        def __getitem__(self, name):
            return FakeCol()

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("Proc", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    monkeypatch.delenv("JIUYAN_STOCK_PHASE_ENABLED", raising=False)

    result = schedule._run_jiuyan_label_step("2026-10-12")
    assert result["ok"] is True
    assert "--with-stock-phase" not in captured["cmd"]


def test_jiuyan_stock_phase_gate_enabled_adds_flag(monkeypatch: Any) -> None:
    """JIUYAN_STOCK_PHASE_ENABLED=1（用户批准成本后）→ 命令带 --with-stock-phase。"""
    from backend.operations import schedule

    class FakeCol:
        def find(self, _query, _projection=None):
            return [{"_id": "1"}]

        def find_one(self, _query, _projection=None):
            return {"_id": "x"}

    class FakeDb:
        def __getitem__(self, name):
            return FakeCol()

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("Proc", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    monkeypatch.setenv("JIUYAN_STOCK_PHASE_ENABLED", "1")

    result = schedule._run_jiuyan_label_step("2026-10-12")
    assert result["ok"] is True
    assert "--with-stock-phase" in captured["cmd"]


def test_jiuyan_label_failure_does_not_flip_chain(monkeypatch: Any) -> None:
    """advisory 语义：个股打标失败只进 results，不翻转整体 ok。"""
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type("Settings", (), {"storage_backend": "mongodb", "archive_auto_dataset_id": "dragonboard_live", "archive_auto_snapshot_types": "half_hour"})(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: "mongo-db",
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_hotlist_sentiment_for_latest_day",
        lambda db, dataset_id, snapshot_type, dry_run=False: calls.append("hotlist") or {"ok": True, "written": 1},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_backup_once",
        lambda *, dry_run=False, now=None: calls.append("backup") or {"ok": True, "skipped": True, "reason": "dry_run"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_snapshot_archive_once",
        lambda *, dry_run=False: calls.append("archiveR2") or {"ok": True, "dryRun": True, "snapshotTypes": {}},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_phase_pulse_step",
        lambda today, dry_run=False: calls.append("pulse") or {"ok": True, "month": "2026-10"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_jiuyan_label_step",
        lambda today, dry_run=False: calls.append("jiuyanLabel") or {"ok": False, "error": {"code": "jiuyan_label_failed", "message": "boom"}},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_phase_band_step",
        lambda today, dry_run=False: calls.append("phaseBand") or {"ok": True, "phaseBand": "cold_lt40"},
    )

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(dry_run=True)

    assert result["ok"] is True
    assert result["results"]["jiuyanLabel"]["ok"] is False
    assert calls == ["hotlist", "backup", "archiveR2", "pulse", "jiuyanLabel", "phaseBand"]


def test_deep_valley_gate_skips_without_eod(monkeypatch: Any) -> None:
    """无 EOD 文档 → C9 复验跳过，子进程不启动。"""
    from backend.operations import schedule

    class FakeCollection:
        def find_one(self, _query, _projection=None):
            return None

    class FakeDb:
        def __getitem__(self, name):
            return FakeCollection()

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type("Settings", (), {"archive_auto_dataset_id": "dragonboard_live", "archive_auto_snapshot_types": "half_hour"})(),
    )
    ran: list[str] = []
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: ran.append("subprocess"))

    result = schedule._run_deep_valley_step("2026-10-11")

    assert result["ok"] is True and result["skipped"] is True
    assert "no EOD doc" in result["reason"]
    assert ran == []


def test_deep_valley_step_runs_subprocess_and_reads_ledger(monkeypatch: Any) -> None:
    """EOD 已落 → 子进程跑当月复验 --apply，回读 c9 账本摘要与新鲜度。"""
    from backend.operations import schedule

    class FakeCol:
        def __init__(self, name):
            self.name = name

        def find_one(self, _query, _projection=None):
            if self.name == "phase_monitor":
                return {"summary": {"deepSamples": 3}, "updatedAt": "2099-01-01T00:00:00"}
            return {"_id": "x"}  # hotlist_sentiment EOD 存在

    class FakeDb:
        def __getitem__(self, name):
            return FakeCol(name)

    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type("Settings", (), {"archive_auto_dataset_id": "dragonboard_live", "archive_auto_snapshot_types": "half_hour"})(),
    )
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("Proc", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(schedule.subprocess, "run", fake_run)

    result = schedule._run_deep_valley_step("2026-10-12")

    assert result["ok"] is True and result["month"] == "2026-10"
    assert result["summary"]["deepSamples"] == 3
    assert result["mongoFresh"] is True
    assert "backend.operations.deep_valley_revalidate" in " ".join(captured["cmd"])
    assert "--apply" in captured["cmd"]


def test_deep_valley_failure_does_not_flip_chain(monkeypatch: Any) -> None:
    """advisory 语义：C9 复验失败只进 results，不翻转整体 ok。"""
    calls: list[str] = []
    monkeypatch.setattr(
        "backend.operations.schedule.get_settings",
        lambda: type("Settings", (), {"storage_backend": "mongodb", "archive_auto_dataset_id": "dragonboard_live", "archive_auto_snapshot_types": "half_hour"})(),
    )
    monkeypatch.setattr(
        "backend.operations.schedule.repository_factory.get_runtime_mongodb_database",
        lambda: "mongo-db",
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_hotlist_sentiment_for_latest_day",
        lambda db, dataset_id, snapshot_type, dry_run=False: calls.append("hotlist") or {"ok": True, "written": 1},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_backup_once",
        lambda *, dry_run=False, now=None: calls.append("backup") or {"ok": True, "skipped": True, "reason": "dry_run"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule.run_mongodb_snapshot_archive_once",
        lambda *, dry_run=False: calls.append("archiveR2") or {"ok": True, "dryRun": True, "snapshotTypes": {}},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_phase_pulse_step",
        lambda today, dry_run=False: calls.append("pulse") or {"ok": True, "month": "2026-10"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_jiuyan_label_step",
        lambda today, dry_run=False: calls.append("jiuyanLabel") or {"ok": True, "labeledToday": 0},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_phase_band_step",
        lambda today, dry_run=False: calls.append("phaseBand") or {"ok": True, "phaseBand": "cold_lt40"},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_deep_valley_step",
        lambda today, dry_run=False: calls.append("deepValley") or {"ok": False, "error": {"code": "deep_valley_failed", "message": "boom"}},
    )
    monkeypatch.setattr(
        "backend.operations.schedule._run_peak_revalidate_step",
        lambda today, dry_run=False: calls.append("peakRevalidate") or {"ok": True, "month": "2026-10"},
    )

    from backend.operations.schedule import run_after_market_once

    result = run_after_market_once(dry_run=True)

    assert result["ok"] is True
    assert result["results"]["deepValley"]["ok"] is False
    assert result["results"]["peakRevalidate"]["ok"] is True  # advisory：deepValley 失败不翻转 C10 步
    assert calls == ["hotlist", "backup", "archiveR2", "pulse", "jiuyanLabel", "phaseBand", "deepValley", "peakRevalidate"]


# ── jevVoteRecheck 步（双题集收盘复核，观察轨道 advisory 语义）──


def test_jev_vote_recheck_step_skipped_when_frame_missing(monkeypatch):
    from backend.operations import schedule
    class _Col:
        def find_one(self, query, projection=None):
            return None

    class _Db:
        def __getitem__(self, name):
            return _Col()

    monkeypatch.setattr(schedule.repository_factory, "get_runtime_mongodb_database", lambda: _Db())
    result = schedule._run_jev_vote_recheck_step("2026-10-03")  # 非交易日无帧
    assert result["ok"] is True and result["skipped"] is True


def test_jev_vote_recheck_step_dry_run():
    from backend.operations import schedule
    assert schedule._run_jev_vote_recheck_step("2026-10-09", dry_run=True) == {
        "ok": True, "skipped": True, "reason": "dry_run"}


def test_jev_vote_recheck_step_runs_full_population(monkeypatch):
    from backend.operations import schedule
    captured = {}

    class _Col:
        def find_one(self, query, projection=None):
            return {"snapshotId": "half_hour:2026-10-09:15:00"}

    class _Db:
        def __getitem__(self, name):
            return _Col()

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return type("P", (), {"returncode": 0, "stdout": "FINAL", "stderr": ""})()

    monkeypatch.setattr(schedule.repository_factory, "get_runtime_mongodb_database", lambda: _Db())
    monkeypatch.setattr(schedule.subprocess, "run", fake_run)
    result = schedule._run_jev_vote_recheck_step("2026-10-09")
    assert result["ok"] is True
    cmd = " ".join(captured["cmd"])
    assert "backend.operations.jev_vote_confirm" in cmd
    # 全量人口口径（用户裁决：250 只池全覆盖）+ 收盘帧 + 幂等 fire
    for flag in ("--include-neutral", "--include-cooling", "--slot", "15:00", "--fire",
                 "--vote-cap-buy", "200", "--lc-cap-total", "200"):
        assert flag in cmd, flag
