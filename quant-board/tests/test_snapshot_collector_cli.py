"""Tests for snapshot collector CLI commands and handlers.

Covers argument parsing and handler JSON output for:
- snapshot-collector-status
- snapshot-collector-run-once (dry_run, blocked, deduped, completed)
- snapshot-collector-backfill (dry_run, apply with results)
- snapshot-collector-audit
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────


def _capture_json_output(func: Any, *args: Any) -> dict[str, Any]:
    """Call *func* and return the JSON printed to stdout."""
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        func(*args)
    finally:
        sys.stdout = old_stdout
    return json.loads(buf.getvalue())


def _make_args(**kwargs: Any) -> argparse.Namespace:
    """Build a Namespace from keyword arguments, filling in defaults."""
    defaults: dict[str, Any] = {
        "dataset_id": "dragonboard_backend_shadow",
        "snapshot_type": "half_hour",
        "trading_date": "2026-06-11",
        "slot_time": "15:00",
        "dry_run": False,
        "force": False,
        "start_date": "2026-06-11",
        "end_date": "2026-06-11",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _fake_repo() -> MagicMock:
    """Create a fake SnapshotRepository with default happy-path responses."""
    repo = MagicMock()
    repo.snapshot_exists.return_value = False
    repo.save_snapshot_ingest.return_value = {"status": "saved", "deduped": False}
    repo.collector_status.return_value = {
        "key": "collector",
        "mode": "idle",
        "lastRunAt": None,
    }
    repo.list_runs.return_value = {"items": [], "total": 0}
    repo.audit_dataset.return_value = {
        "datasetId": "dragonboard_backend_shadow",
        "snapshotType": "half_hour",
        "totalFrames": 10,
        "totalRecords": 120,
        "missingSlots": [],
        "emptyFrames": [],
        "missingRecords": [],
        "countDrifts": [],
    }
    return repo


# ── Fake service helpers ───────────────────────────────────────────────────────


class _FakeRunResult:
    """Lightweight stub that mimics CollectorRunResult fields."""

    status: str
    snapshot_id: str
    deduped: bool
    dry_run: bool
    run_id: str
    message: str
    details: dict[str, Any]
    quality: Any

    def __init__(
        self,
        status: str = "completed",
        snapshot_id: str = "half_hour:2026-06-11:15:00",
        deduped: bool = False,
        dry_run: bool = False,
        run_id: str = "sc-abc123",
        message: str = "",
        quality: Any = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status = status
        self.snapshot_id = snapshot_id
        self.deduped = deduped
        self.dry_run = dry_run
        self.run_id = run_id
        self.message = message
        self.quality = quality
        self.details = details or {}


class _FakeQuality:
    """Lightweight stub that mimics QualityResult fields."""

    ok: bool
    blocking_issues: list[str]
    warnings: list[str]
    source_counts: dict[str, int]

    def __init__(
        self,
        ok: bool = True,
        blocking_issues: list[str] | None = None,
        warnings: list[str] | None = None,
        source_counts: dict[str, int] | None = None,
    ) -> None:
        self.ok = ok
        self.blocking_issues = blocking_issues or []
        self.warnings = warnings or []
        self.source_counts = source_counts or {"ok": 2, "failed": 0}


class _FakeService:
    """In-memory SnapshotCollectorService stub for handler tests."""

    def __init__(self, **kwargs: Any) -> None:
        self._run_once_return = kwargs.get("run_once_return")
        self._backfill_return = kwargs.get("backfill_return")
        self._status_return = kwargs.get(
            "status_return",
            {"key": "collector", "mode": "idle", "lastRunAt": None},
        )
        self._runs_return = kwargs.get("runs_return", {"items": [], "total": 0})
        self._audit_return = kwargs.get(
            "audit_return",
            {
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "totalFrames": 10,
                "totalRecords": 120,
                "missingSlots": [],
                "emptyFrames": [],
                "missingRecords": [],
                "countDrifts": [],
            },
        )

    def run_once(self, request: Any) -> _FakeRunResult:
        if self._run_once_return is not None:
            return self._run_once_return
        return _FakeRunResult(status="completed")

    def backfill_slots(self, request: Any) -> dict[str, Any]:
        if self._backfill_return is not None:
            return self._backfill_return
        return {
            "total": 1,
            "succeeded": 1,
            "failed": 0,
            "blocked": 0,
            "deduped": 0,
            "details": [{"snapshotId": "half_hour:2026-06-11:15:00", "status": "completed", "message": "done"}],
        }

    def get_status(self) -> dict[str, Any]:
        return self._status_return

    def get_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
        return self._runs_return

    def audit(self, dataset_id: str, snapshot_type: str, trading_date: str | None = None) -> dict[str, Any]:
        return self._audit_return


# ═══════════════════════════════════════════════════════════════════════════════
# Parser-level tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCollectorCLIParser:
    """Test argparse subcommand registration and argument defaults."""

    @pytest.fixture(autouse=True)
    def _parser(self) -> None:
        from backend.cli import build_parser
        self.parser = build_parser()

    # ── snapshot-collector-status ───────────────────────────────────────────

    def test_status_subcommand_registered(self) -> None:
        """snapshot-collector-status subparser exists and is callable."""
        args = self.parser.parse_args(["snapshot-collector-status"])
        assert args.func is not None

    # ── snapshot-collector-run-once ─────────────────────────────────────────

    def test_run_once_default_dry_run_false(self) -> None:
        """--dry-run defaults to False."""
        args = self.parser.parse_args([
            "snapshot-collector-run-once",
            "--dataset-id", "dragonboard_backend_shadow",
            "--snapshot-type", "half_hour",
            "--trading-date", "2026-06-11",
            "--slot-time", "15:00",
        ])
        assert args.dry_run is False
        assert args.force is False

    def test_run_once_dry_run_true(self) -> None:
        """--dry-run flag sets dry_run to True."""
        args = self.parser.parse_args([
            "snapshot-collector-run-once",
            "--dataset-id", "dragonboard_backend_shadow",
            "--snapshot-type", "half_hour",
            "--trading-date", "2026-06-11",
            "--slot-time", "15:00",
            "--dry-run",
        ])
        assert args.dry_run is True

    def test_run_once_force_flag(self) -> None:
        """--force flag sets force to True."""
        args = self.parser.parse_args([
            "snapshot-collector-run-once",
            "--dataset-id", "dragonboard_backend_shadow",
            "--snapshot-type", "half_hour",
            "--trading-date", "2026-06-11",
            "--slot-time", "15:00",
            "--force",
        ])
        assert args.force is True

    def test_run_once_default_values(self) -> None:
        """Default values for run-once match spec."""
        args = self.parser.parse_args([
            "snapshot-collector-run-once",
            "--dataset-id", "dragonboard_backend_shadow",
            "--snapshot-type", "half_hour",
            "--trading-date", "2026-06-11",
            "--slot-time", "15:00",
        ])
        assert args.snapshot_type == "half_hour"

    def test_run_once_snapshot_type_choices(self) -> None:
        """Only valid snapshot types are accepted."""
        valid = ["quarter_hour", "half_hour", "hourly", "daily"]
        for st in valid:
            args = self.parser.parse_args([
                "snapshot-collector-run-once",
                "--dataset-id", "ds",
                "--snapshot-type", st,
                "--trading-date", "2026-06-11",
                "--slot-time", "15:00",
            ])
            assert args.snapshot_type == st

        with pytest.raises(SystemExit):
            self.parser.parse_args([
                "snapshot-collector-run-once",
                "--dataset-id", "ds",
                "--snapshot-type", "invalid_type",
                "--trading-date", "2026-06-11",
                "--slot-time", "15:00",
            ])

    # ── snapshot-collector-backfill ─────────────────────────────────────────

    def test_backfill_default_dry_run_true(self) -> None:
        """--dry-run defaults to True for backfill (safety)."""
        args = self.parser.parse_args([
            "snapshot-collector-backfill",
            "--dataset-id", "dragonboard_backend_shadow",
            "--snapshot-type", "half_hour",
            "--start-date", "2026-06-11",
            "--end-date", "2026-06-11",
        ])
        assert args.dry_run is True

    def test_backfill_subcommand_registered(self) -> None:
        """snapshot-collector-backfill subparser exists."""
        args = self.parser.parse_args([
            "snapshot-collector-backfill",
            "--dataset-id", "dragonboard_backend_shadow",
            "--snapshot-type", "half_hour",
            "--start-date", "2026-06-11",
            "--end-date", "2026-06-11",
        ])
        assert args.func is not None

    def test_backfill_force_flag(self) -> None:
        """--force flag on backfill."""
        args = self.parser.parse_args([
            "snapshot-collector-backfill",
            "--dataset-id", "dragonboard_backend_shadow",
            "--snapshot-type", "half_hour",
            "--start-date", "2026-06-11",
            "--end-date", "2026-06-11",
            "--force",
        ])
        assert args.force is True

    # ── snapshot-collector-audit ────────────────────────────────────────────

    def test_audit_subcommand_registered(self) -> None:
        """snapshot-collector-audit subparser exists."""
        args = self.parser.parse_args([
            "snapshot-collector-audit",
            "--dataset-id", "dragonboard_backend_shadow",
            "--snapshot-type", "half_hour",
        ])
        assert args.func is not None

    def test_audit_optional_trading_date(self) -> None:
        """--trading-date is optional for audit."""
        args = self.parser.parse_args([
            "snapshot-collector-audit",
            "--dataset-id", "dragonboard_backend_shadow",
            "--snapshot-type", "half_hour",
            "--trading-date", "2026-06-11",
        ])
        assert args.trading_date == "2026-06-11"

    # ── scheduler-status ────────────────────────────────────────────────────

    def test_scheduler_status_subcommand_registered(self) -> None:
        """`snapshot-collector-scheduler-status` is a recognised subcommand."""
        from backend.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["snapshot-collector-scheduler-status"])
        assert args.func is not None
# Handler-level tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestCollectorCLIHandlers:
    """Test CLI handler functions with mocked service."""

    def _patch_service(self, fake_service: _FakeService) -> dict[str, Any]:
        """Return patches dict for service_factory and service class."""
        return {
            "create_snapshot_collector_repository": patch(
                "backend.cli.create_snapshot_collector_repository",
                return_value=_fake_repo(),
            ),
            "SnapshotCollectorService": patch(
                "backend.cli.SnapshotCollectorService",
                return_value=fake_service,
            ),
        }

    # ── status ──────────────────────────────────────────────────────────────

    def test_status_output(self) -> None:
        """Status handler prints JSON with mode and lastRunAt."""
        fake_svc = _FakeService(
            status_return={"key": "collector", "mode": "idle", "lastRunAt": "2026-06-11T07:00:00Z"}
        )
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_status

            output = _capture_json_output(cmd_snapshot_collector_status, _make_args())

        assert output["mode"] == "idle"
        assert output["lastRunAt"] == "2026-06-11T07:00:00Z"

    # ── run-once: dry_run ───────────────────────────────────────────────────

    def test_run_once_dry_run_output(self) -> None:
        """Dry-run run-once prints JSON with dryRun=true and status=dry_run."""
        fake_q = _FakeQuality(ok=True, source_counts={"ok": 2, "failed": 0})
        fake_result = _FakeRunResult(
            status="dry_run",
            snapshot_id="half_hour:2026-06-11:15:00",
            dry_run=True,
            run_id="sc-test001",
            quality=fake_q,
            message="Dry-run completed successfully",
        )
        fake_svc = _FakeService(run_once_return=fake_result)
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_run_once

            output = _capture_json_output(
                cmd_snapshot_collector_run_once,
                _make_args(dry_run=True),
            )

        assert output["status"] == "dry_run"
        assert output["dryRun"] is True
        assert output["snapshotId"] == "half_hour:2026-06-11:15:00"
        assert output["runId"] == "sc-test001"
        assert output["quality"]["ok"] is True

    # ── run-once: blocked ───────────────────────────────────────────────────

    def test_run_once_blocked_output(self) -> None:
        """Blocked run-once prints JSON with status=blocked and blocking issues."""
        fake_q = _FakeQuality(
            ok=False,
            blocking_issues=["empty_stock_rows"],
            warnings=[],
            source_counts={"ok": 1, "failed": 1},
        )
        fake_result = _FakeRunResult(
            status="blocked",
            snapshot_id="half_hour:2026-06-11:15:00",
            run_id="sc-block-01",
            quality=fake_q,
            message="Quality gate blocked",
        )
        fake_svc = _FakeService(run_once_return=fake_result)
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_run_once

            output = _capture_json_output(
                cmd_snapshot_collector_run_once,
                _make_args(),
            )

        assert output["status"] == "blocked"
        assert output["quality"]["ok"] is False
        assert "empty_stock_rows" in output["quality"]["blockingIssues"]

    # ── run-once: deduped ───────────────────────────────────────────────────

    def test_run_once_deduped_output(self) -> None:
        """Deduped run-once prints JSON with deduped=true."""
        fake_result = _FakeRunResult(
            status="deduped",
            snapshot_id="half_hour:2026-06-11:15:00",
            deduped=True,
            run_id="sc-dedup-01",
            message="Snapshot already exists",
        )
        fake_svc = _FakeService(run_once_return=fake_result)
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_run_once

            output = _capture_json_output(
                cmd_snapshot_collector_run_once,
                _make_args(),
            )

        assert output["status"] == "deduped"
        assert output["deduped"] is True
        assert output["dryRun"] is False

    # ── run-once: completed ─────────────────────────────────────────────────

    def test_run_once_completed_output(self) -> None:
        """Completed run-once shows stock counts and idempotency key."""
        fake_q = _FakeQuality(ok=True, source_counts={"ok": 2, "failed": 0})
        fake_result = _FakeRunResult(
            status="completed",
            snapshot_id="half_hour:2026-06-11:15:00",
            run_id="sc-comp-01",
            quality=fake_q,
            message="saved",
            details={
                "stockRowCount": 120,
                "frameCount": 1,
                "sectorRowCount": 2,
                "idempotencyKey": "sc-abc123def456",
            },
        )
        fake_svc = _FakeService(run_once_return=fake_result)
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_run_once

            output = _capture_json_output(
                cmd_snapshot_collector_run_once,
                _make_args(),
            )

        assert output["status"] == "completed"
        assert output["deduped"] is False
        assert output["details"]["stockRowCount"] == 120
        assert output["details"]["idempotencyKey"] == "sc-abc123def456"
        assert output["quality"]["ok"] is True

    # ── run-once: args passthrough ──────────────────────────────────────────

    def test_run_once_args_passthrough(self) -> None:
        """Verify that run-once creates CollectorRunRequest with correct args."""
        captured: list[Any] = []

        class _CapturingService(_FakeService):
            def run_once(self, request: Any) -> _FakeRunResult:
                captured.append(request)
                return _FakeRunResult(status="completed")

        fake_svc = _CapturingService()
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_run_once

            _capture_json_output(
                cmd_snapshot_collector_run_once,
                _make_args(
                    dataset_id="dragonboard_backend_shadow",
                    snapshot_type="half_hour",
                    trading_date="2026-06-11",
                    slot_time="15:00",
                    dry_run=True,
                    force=True,
                ),
            )

        assert len(captured) == 1
        req = captured[0]
        assert req.dataset_id == "dragonboard_backend_shadow"
        assert req.snapshot_type == "half_hour"
        assert req.trading_date == "2026-06-11"
        assert req.slot_time == "15:00"
        assert req.dry_run is True
        assert req.force is True

    # ── backfill: dry_run ───────────────────────────────────────────────────

    def test_backfill_dry_run_output(self) -> None:
        """Backfill dry-run prints JSON with total and details."""
        fake_svc = _FakeService(
            backfill_return={
                "total": 10,
                "succeeded": 0,
                "failed": 0,
                "blocked": 0,
                "deduped": 0,
                "details": [
                    {"snapshotId": "half_hour:2026-06-11:09:30", "status": "dry_run", "message": "Dry-run completed successfully"},
                    {"snapshotId": "half_hour:2026-06-11:10:00", "status": "dry_run", "message": "Dry-run completed successfully"},
                ],
            }
        )
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_backfill

            output = _capture_json_output(
                cmd_snapshot_collector_backfill,
                _make_args(start_date="2026-06-11", end_date="2026-06-11", dry_run=True),
            )

        assert output["total"] == 10
        assert output["succeeded"] == 0
        assert len(output["details"]) == 2

    # ── backfill: apply ─────────────────────────────────────────────────────

    def test_backfill_apply_output(self) -> None:
        """Backfill apply prints JSON with succeeded counts."""
        fake_svc = _FakeService(
            backfill_return={
                "total": 10,
                "succeeded": 8,
                "failed": 0,
                "blocked": 0,
                "deduped": 2,
                "details": [
                    {"snapshotId": "half_hour:2026-06-11:09:30", "status": "completed", "message": "saved"},
                    {"snapshotId": "half_hour:2026-06-11:10:00", "status": "deduped", "message": "Snapshot already exists"},
                ],
            }
        )
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_backfill

            output = _capture_json_output(
                cmd_snapshot_collector_backfill,
                _make_args(start_date="2026-06-11", end_date="2026-06-11", dry_run=False),
            )

        assert output["total"] == 10
        assert output["succeeded"] == 8
        assert output["deduped"] == 2

    # ── backfill: partially failed ──────────────────────────────────────────

    def test_backfill_partial_failure_output(self) -> None:
        """Backfill with partial failures reports ok=false and failed count."""
        fake_svc = _FakeService(
            backfill_return={
                "total": 10,
                "succeeded": 7,
                "failed": 2,
                "blocked": 1,
                "deduped": 0,
                "details": [
                    {"snapshotId": "half_hour:2026-06-11:09:30", "status": "completed", "message": "saved"},
                    {"snapshotId": "half_hour:2026-06-11:10:00", "status": "blocked", "message": "Quality gate blocked"},
                    {"snapshotId": "half_hour:2026-06-11:10:30", "status": "failed", "message": "Connection refused"},
                ],
            }
        )
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_backfill

            output = _capture_json_output(
                cmd_snapshot_collector_backfill,
                _make_args(start_date="2026-06-11", end_date="2026-06-11", dry_run=False),
            )

        assert output["failed"] == 2
        assert output["blocked"] == 1
        assert output["succeeded"] == 7

    # ── audit ───────────────────────────────────────────────────────────────

    def test_audit_output(self) -> None:
        """Audit prints JSON with datasetId, snapshotType, and coverage details."""
        fake_svc = _FakeService(
            audit_return={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": None,
                "totalFrames": 10,
                "totalRecords": 120,
                "missingSlots": [],
                "emptyFrames": [],
                "missingRecords": [],
                "countDrifts": [],
            }
        )
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_audit

            output = _capture_json_output(
                cmd_snapshot_collector_audit,
                _make_args(dataset_id="dragonboard_backend_shadow", snapshot_type="half_hour"),
            )

        assert output["datasetId"] == "dragonboard_backend_shadow"
        assert output["snapshotType"] == "half_hour"
        assert output["totalFrames"] == 10
        assert output["totalRecords"] == 120

    def test_audit_with_trading_date(self) -> None:
        """Audit with trading_date passes it through."""
        fake_svc = _FakeService(
            audit_return={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "totalFrames": 10,
                "totalRecords": 120,
                "missingSlots": [],
                "emptyFrames": [],
                "missingRecords": [],
                "countDrifts": [],
            }
        )
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_audit

            output = _capture_json_output(
                cmd_snapshot_collector_audit,
                _make_args(
                    dataset_id="dragonboard_backend_shadow",
                    snapshot_type="half_hour",
                    trading_date="2026-06-11",
                ),
            )

        assert output["tradingDate"] == "2026-06-11"

    def test_audit_reports_missing_and_drifts(self) -> None:
        """Audit reports missing slots, empty frames, and count drifts."""
        fake_svc = _FakeService(
            audit_return={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "totalFrames": 8,
                "totalRecords": 80,
                "missingSlots": ["half_hour:2026-06-11:10:30", "half_hour:2026-06-11:14:30"],
                "emptyFrames": ["half_hour:2026-06-11:13:00"],
                "missingRecords": ["half_hour:2026-06-11:11:00"],
                "countDrifts": [{"snapshotId": "half_hour:2026-06-11:15:00", "frameCount": 120, "recordCount": 119}],
            }
        )
        patches = self._patch_service(fake_svc)
        with patches["create_snapshot_collector_repository"], patches["SnapshotCollectorService"]:
            from backend.cli import cmd_snapshot_collector_audit

            output = _capture_json_output(
                cmd_snapshot_collector_audit,
                _make_args(
                    dataset_id="dragonboard_backend_shadow",
                    snapshot_type="half_hour",
                    trading_date="2026-06-11",
                ),
            )

        assert len(output["missingSlots"]) == 2
        assert len(output["emptyFrames"]) == 1
        assert len(output["missingRecords"]) == 1
        assert len(output["countDrifts"]) == 1
        assert output["totalFrames"] == 8
        assert output["totalRecords"] == 80

    # ── scheduler-status ────────────────────────────────────────────────────

    def test_scheduler_status_output(self, monkeypatch: Any) -> None:
        """Scheduler status handler prints JSON with scheduler state keys."""
        fake_status = {
            "enabled": True,
            "running": True,
            "dataset_id": "dragonboard_backend_shadow",
            "snapshot_types": ["half_hour", "daily"],
            "poll_seconds": 1.0,
            "grace_minutes": 5,
            "last_run_at": "2026-06-15T10:00:01+08:00",
            "last_slot_collected": "half_hour:2026-06-15:10:00",
            "last_error": None,
            "collection_count": 3,
            "error_count": 0,
            "in_flight_slots": [],
        }
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.snapshot_collector_scheduler.status",
            lambda: fake_status,
        )
        from backend.cli import cmd_snapshot_collector_scheduler_status

        output = _capture_json_output(cmd_snapshot_collector_scheduler_status, _make_args())
        assert output["enabled"] is True
        assert output["running"] is True
        assert output["dataset_id"] == "dragonboard_backend_shadow"
        assert output["snapshot_types"] == ["half_hour", "daily"]
        assert output["collection_count"] == 3
        assert output["error_count"] == 0
