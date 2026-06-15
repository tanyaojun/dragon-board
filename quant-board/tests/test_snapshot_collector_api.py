"""Tests for Snapshot Collector API routes.

Task 9: API Routes for the QuantBoard Backend Snapshot Collector.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from backend.main import app
from backend.snapshot_collector.models import CollectorRunResult, QualityResult


# ── Fake repository ────────────────────────────────────────────────────────


class FakeSnapshotRepository:
    """In-memory implementation of SnapshotRepository for API testing."""

    def __init__(self) -> None:
        self._snapshots: dict[str, set[str]] = {}
        self._ingests: list[dict[str, Any]] = []
        self._runs: list[dict[str, Any]] = []
        self._state: dict[str, Any] = {"mode": "idle", "lastRunAt": None}

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
        return snapshot_id in self._snapshots.get(dataset_id, set())

    def save_snapshot_ingest(
        self,
        dataset: dict[str, Any],
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        ds_id = dataset.get("id", "")
        snapshot_ids = {
            item.get("snapshotId") or item.get("snapshot_id") or ""
            for item in [*records, *frames, *stock_rows, *sector_rows]
            if isinstance(item, dict)
        }
        snapshot_ids.discard("")
        existing = self._snapshots.setdefault(ds_id, set())
        existing.update(snapshot_ids)
        self._ingests.append(
            {
                "datasetId": ds_id,
                "snapshotIds": sorted(snapshot_ids),
                "idempotencyKey": idempotency_key,
            }
        )
        return {"status": "done", "deduped": False}

    def insert_run(self, run: dict[str, Any]) -> None:
        self._runs.append(dict(run))

    def list_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
        items = [
            run
            for run in self._runs
            if all(run.get(k) == v for k, v in filters.items())
        ]
        return {"items": items, "total": len(items)}

    def collector_status(self) -> dict[str, Any]:
        return dict(self._state)

    def audit_dataset(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str | None = None,
    ) -> dict[str, Any]:
        return {
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "missingSlots": [],
            "emptyFrames": [],
            "missingRecords": [],
            "countDrifts": [],
        }


# ── Fake service (configurable) ────────────────────────────────────────────


class FakeCollectorService:
    """Fake SnapshotCollectorService for API testing.

    Subclass and override methods for tests that need specific behavior.
    """

    def __init__(self, repo=None, settings=None, **kwargs: Any) -> None:
        self.repo = repo

    def get_status(self) -> dict[str, Any]:
        return {"mode": "idle", "lastRunAt": None, "lastRunId": None}

    def get_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
        return {"items": [], "total": 0}

    def run_once(self, request: Any) -> CollectorRunResult:
        return CollectorRunResult(
            status="completed",
            snapshot_id=f"{request.snapshot_type}:{request.trading_date}:{request.slot_time}",
            run_id="test-run-001",
            quality=QualityResult(
                ok=True, blocking_issues=[], warnings=[], source_counts={"ok": 1, "failed": 0}
            ),
            message="Test completed",
        )

    def backfill_slots(self, request: Any) -> dict[str, Any]:
        return {
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "blocked": 0,
            "deduped": 0,
            "details": [],
        }

    def audit(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str | None = None,
    ) -> dict[str, Any]:
        return {
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "missingSlots": [],
            "emptyFrames": [],
            "missingRecords": [],
            "countDrifts": [],
        }


# ── Test helpers ───────────────────────────────────────────────────────────


def _setup_client(monkeypatch: Any, service_cls: type | None = None) -> tuple[TestClient, FakeSnapshotRepository]:
    """Set up TestClient with mocked dependencies."""
    import backend.api.snapshot_collector_routes as routes

    fake_repo = FakeSnapshotRepository()
    monkeypatch.setattr(
        "backend.api.snapshot_collector_routes.create_snapshot_collector_repository",
        lambda: fake_repo,
    )
    cls = service_cls if service_cls is not None else FakeCollectorService
    monkeypatch.setattr(
        "backend.api.snapshot_collector_routes.SnapshotCollectorService",
        cls,
    )
    monkeypatch.setattr(
        "backend.api.snapshot_collector_routes._create_service",
        lambda repo: routes.SnapshotCollectorService(repo=repo),
        raising=False,
    )
    return TestClient(app), fake_repo


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/snapshot-collector/status
# ═══════════════════════════════════════════════════════════════════════════


class TestGetStatus:
    """Tests for GET /api/snapshot-collector/status."""

    def test_uses_service_factory(self, monkeypatch: Any) -> None:
        """Routes must use the shared service factory wiring."""
        import backend.api.snapshot_collector_routes as routes

        fake_repo = FakeSnapshotRepository()
        created_with: list[Any] = []
        monkeypatch.setattr(routes, "create_snapshot_collector_repository", lambda: fake_repo)
        monkeypatch.setattr(
            routes,
            "create_snapshot_collector_service",
            lambda repo: created_with.append(repo) or FakeCollectorService(repo=repo),
            raising=False,
        )

        response = TestClient(app).get("/api/snapshot-collector/status")

        assert response.status_code == 200
        assert created_with == [fake_repo]

    def test_returns_ok_and_data(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def get_status(self) -> dict[str, Any]:
                return {"mode": "idle", "lastRunAt": "2026-06-11T10:00:00Z"}

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.get("/api/snapshot-collector/status")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["status"] == "completed"
        assert body["data"]["mode"] == "idle"

    def test_response_has_ok_field(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        response = client.get("/api/snapshot-collector/status")
        body = response.json()
        assert "ok" in body


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/snapshot-collector/run-once
# ═══════════════════════════════════════════════════════════════════════════


class TestRunOnceSuccess:
    """Tests for successful POST /api/snapshot-collector/run-once."""

    def test_returns_ok_true_for_completed_run(self, monkeypatch: Any) -> None:
        client, fake_repo = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["status"] == "completed"
        assert body["data"]["snapshotId"] == "half_hour:2026-06-11:10:00"
        assert body["data"]["runId"] is not None

    def test_dry_run_returns_ok_true(self, monkeypatch: Any) -> None:
        client, fake_repo = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def run_once(self, request: Any) -> CollectorRunResult:
                return CollectorRunResult(
                    status="dry_run",
                    snapshot_id=f"{request.snapshot_type}:{request.trading_date}:{request.slot_time}",
                    dry_run=True,
                    run_id="test-dry-001",
                    quality=QualityResult(ok=True, blocking_issues=[], warnings=[], source_counts={"ok": 1, "failed": 0}),
                    message="Dry-run completed",
                )

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
                "dryRun": True,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["status"] == "dry_run"
        assert body["data"]["dryRun"] is True

    def test_deduped_returns_ok_true(self, monkeypatch: Any) -> None:
        client, fake_repo = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def run_once(self, request: Any) -> CollectorRunResult:
                return CollectorRunResult(
                    status="deduped",
                    snapshot_id=f"{request.snapshot_type}:{request.trading_date}:{request.slot_time}",
                    deduped=True,
                    run_id="test-dedup-001",
                    message="Snapshot already exists",
                )

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["status"] == "deduped"
        assert body["data"]["deduped"] is True


class TestRunOnceBlocked:
    """Blocked run returns HTTP 200 with ok=false and quality info."""

    def test_blocked_returns_200_with_ok_false(self, monkeypatch: Any) -> None:
        client, fake_repo = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def run_once(self, request: Any) -> CollectorRunResult:
                return CollectorRunResult(
                    status="blocked",
                    snapshot_id="half_hour:2026-06-11:10:00",
                    run_id="test-blocked-001",
                    quality=QualityResult(
                        ok=False,
                        blocking_issues=["empty_stock_rows"],
                        warnings=["low_sample"],
                        source_counts={"ok": 0, "failed": 1},
                    ),
                    message="Quality gate blocked",
                )

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["status"] == "blocked"
        assert "quality" in body
        assert body["quality"]["ok"] is False
        assert "empty_stock_rows" in body["quality"]["blockingIssues"]

    def test_blocked_quality_includes_blocking_issues(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def run_once(self, request: Any) -> CollectorRunResult:
                return CollectorRunResult(
                    status="blocked",
                    snapshot_id="half_hour:2026-06-11:10:00",
                    run_id="test-blocked-002",
                    quality=QualityResult(
                        ok=False,
                        blocking_issues=["invalid_stock_code", "timestamp_outside_slot"],
                        warnings=[],
                        source_counts={"ok": 0, "failed": 2},
                    ),
                    message="Multiple issues",
                )

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert len(body["quality"]["blockingIssues"]) == 2

    def test_blocked_still_has_run_id(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def run_once(self, request: Any) -> CollectorRunResult:
                return CollectorRunResult(
                    status="blocked",
                    snapshot_id="half_hour:2026-06-11:10:00",
                    run_id="test-blocked-run-id",
                    quality=QualityResult(ok=False, blocking_issues=["empty_stock_rows"], warnings=[], source_counts={"ok": 0, "failed": 1}),
                    message="Blocked",
                )

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
            },
        )

        body = response.json()
        assert body["data"]["runId"] == "test-blocked-run-id"


class TestRunOnceValidation:
    """Invalid inputs return HTTP 4xx."""

    def test_invalid_snapshot_type_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "INVALID_TYPE",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
            },
        )

        assert 400 <= response.status_code < 500
        body = response.json()
        detail = body.get("detail", body)
        assert detail["ok"] is False
        assert detail["status"] == "error"

    def test_missing_dataset_id_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
            },
        )

        assert 400 <= response.status_code < 500
        body = response.json()
        detail = body.get("detail", body)
        assert detail["ok"] is False

    def test_missing_trading_date_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "slotTime": "10:00",
            },
        )

        assert 400 <= response.status_code < 500
        body = response.json()
        detail = body.get("detail", body)
        assert detail["ok"] is False

    def test_missing_slot_time_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
            },
        )

        assert 400 <= response.status_code < 500

    def test_invalid_trading_date_format_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "06-11-2026",
                "slotTime": "10:00",
            },
        )

        assert 400 <= response.status_code < 500


class TestRunOnceRequestFields:
    """Verify force and dryRun request fields are passed through."""

    def test_force_field_accepted(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured_request: list[Any] = []

        class Svc(FakeCollectorService):
            def run_once(self, request: Any) -> CollectorRunResult:
                captured_request.append(request)
                return super().run_once(request)

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
                "force": True,
            },
        )

        assert response.status_code == 200
        assert len(captured_request) == 1
        assert captured_request[0].force is True

    def test_dry_run_field_accepted(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured_request: list[Any] = []

        class Svc(FakeCollectorService):
            def run_once(self, request: Any) -> CollectorRunResult:
                captured_request.append(request)
                return super().run_once(request)

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/run-once",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
                "slotTime": "10:00",
                "dryRun": True,
            },
        )

        assert response.status_code == 200
        assert len(captured_request) == 1
        assert captured_request[0].dry_run is True


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/snapshot-collector/backfill-slots
# ═══════════════════════════════════════════════════════════════════════════


class TestBackfillSlotsDryRunDefault:
    """Default dryRun=true writes no facts."""

    def test_dry_run_defaults_to_true(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured_requests: list[Any] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                captured_requests.append(request)
                return {
                    "total": 1,
                    "succeeded": 1,
                    "failed": 0,
                    "blocked": 0,
                    "deduped": 0,
                    "details": [{"snapshotId": "half_hour:2026-06-11:10:00", "status": "dry_run", "message": "ok"}],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        # No dryRun specified in payload → should default to True
        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
            },
        )

        assert response.status_code == 200
        assert len(captured_requests) == 1
        assert captured_requests[0].dry_run is True

    def test_explicit_dry_run_false_accepted(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured_requests: list[Any] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                captured_requests.append(request)
                return {
                    "total": 1, "succeeded": 1, "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
                "dryRun": False,
            },
        )

        assert response.status_code == 200
        assert captured_requests[0].dry_run is False


class TestBackfillSlotsDateRange:
    """Date range is inclusive and limited to requested startDate/endDate."""

    def test_single_day_creates_slots(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured: list[list[dict[str, str]]] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                captured.append(list(request.slots))
                return {
                    "total": len(request.slots),
                    "succeeded": len(request.slots),
                    "failed": 0,
                    "blocked": 0,
                    "deduped": 0,
                    "details": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        # half_hour has 10 slots
        assert body["data"]["total"] == 10
        assert len(captured[0]) == 10

    def test_date_range_inclusive(self, monkeypatch: Any) -> None:
        """Both startDate and endDate are included."""
        client, _ = _setup_client(monkeypatch)
        captured_dates: list[set[str]] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                dates = {s["trading_date"] for s in request.slots}
                captured_dates.append(dates)
                return {
                    "total": len(request.slots),
                    "succeeded": len(request.slots),
                    "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "startDate": "2026-06-10",
                "endDate": "2026-06-11",
            },
        )

        assert response.status_code == 200
        # daily has 1 slot per day, 2 days = 2 slots
        dates = captured_dates[0]
        assert "2026-06-10" in dates
        assert "2026-06-11" in dates
        assert len(dates) == 2

    def test_missing_start_date_defaults_to_end_date(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "endDate": "2026-06-11",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True

    def test_invalid_snapshot_type_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "INVALID",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
            },
        )

        assert 400 <= response.status_code < 500
        body = response.json()
        detail = body.get("detail", body)
        assert detail["ok"] is False
        assert detail["status"] == "error"


class TestBackfillSlotsForce:
    """force=false skips existing slots."""

    def test_force_false_passed_to_service(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured: list[Any] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                captured.append(request)
                return {
                    "total": 1, "succeeded": 1, "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        # Default force=false
        client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
            },
        )

        assert captured[0].force is False

    def test_force_true_passed_to_service(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured: list[Any] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                captured.append(request)
                return {
                    "total": 1, "succeeded": 1, "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
                "force": True,
            },
        )

        assert captured[0].force is True


class TestBackfillSlotsPartialFailure:
    """Partial slot failure returns ok=false with per-slot results."""

    def test_partial_failure_returns_ok_false(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                return {
                    "total": 3,
                    "succeeded": 1,
                    "failed": 2,
                    "blocked": 0,
                    "deduped": 0,
                    "details": [
                        {"snapshotId": "daily:2026-06-10:15:00", "status": "completed", "message": "ok"},
                        {"snapshotId": "daily:2026-06-11:15:00", "status": "failed", "message": "timeout"},
                        {"snapshotId": "daily:2026-06-12:15:00", "status": "failed", "message": "error"},
                    ],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "startDate": "2026-06-10",
                "endDate": "2026-06-12",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert body["data"]["failed"] == 2
        assert body["data"]["succeeded"] == 1
        assert len(body["data"]["details"]) == 3

    def test_all_succeeded_returns_ok_true(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                return {
                    "total": 2, "succeeded": 2, "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [
                        {"snapshotId": "daily:2026-06-10:15:00", "status": "completed", "message": "ok"},
                        {"snapshotId": "daily:2026-06-11:15:00", "status": "completed", "message": "ok"},
                    ],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "startDate": "2026-06-10",
                "endDate": "2026-06-11",
            },
        )

        body = response.json()
        assert body["ok"] is True


class TestBackfillSlotsApplyMode:
    """Apply mode (dryRun=false) writes to repo."""

    def test_apply_mode_passes_dry_run_false(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured: list[Any] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                captured.append(request)
                return {
                    "total": 1, "succeeded": 1, "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
                "dryRun": False,
            },
        )

        assert captured[0].dry_run is False

    def test_apply_mode_includes_details(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                return {
                    "total": 1, "succeeded": 1, "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [
                        {"snapshotId": "daily:2026-06-11:15:00", "status": "completed", "message": "saved"},
                    ],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
                "dryRun": False,
            },
        )

        body = response.json()
        assert body["data"]["details"][0]["status"] == "completed"


class TestBackfillSlotsSlotGeneration:
    """Verify slots are generated correctly from date range."""

    def test_half_hour_slots_count_per_day(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured: list[list[dict[str, str]]] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                captured.append(list(request.slots))
                return {
                    "total": len(request.slots),
                    "succeeded": len(request.slots),
                    "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
            },
        )

        # half_hour has 10 slots
        assert len(captured[0]) == 10
        # All should have same trading_date
        for s in captured[0]:
            assert s["trading_date"] == "2026-06-11"

    def test_daily_slots_single_per_day(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured: list[list[dict[str, str]]] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                captured.append(list(request.slots))
                return {
                    "total": len(request.slots),
                    "succeeded": len(request.slots),
                    "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
            },
        )

        assert len(captured[0]) == 1
        assert captured[0][0]["slot_time"] == "15:00"

    def test_backfill_skips_weekend_dates(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured: list[list[dict[str, str]]] = []

        class Svc(FakeCollectorService):
            def backfill_slots(self, request: Any) -> dict[str, Any]:
                captured.append(list(request.slots))
                return {
                    "total": len(request.slots),
                    "succeeded": len(request.slots),
                    "failed": 0, "blocked": 0, "deduped": 0,
                    "details": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "daily",
                "startDate": "2026-06-12",
                "endDate": "2026-06-15",
            },
        )

        assert response.status_code == 200
        assert [s["trading_date"] for s in captured[0]] == ["2026-06-12", "2026-06-15"]


class TestBackfillSlotsValidation:
    """Validation errors for backfill-slots endpoint."""

    def test_missing_dataset_id_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "snapshotType": "half_hour",
                "startDate": "2026-06-11",
                "endDate": "2026-06-11",
            },
        )

        assert 400 <= response.status_code < 500

    def test_invalid_date_format_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/backfill-slots",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "startDate": "not-a-date",
                "endDate": "2026-06-11",
            },
        )

        assert 400 <= response.status_code < 500


# ═══════════════════════════════════════════════════════════════════════════
# GET /api/snapshot-collector/runs
# ═══════════════════════════════════════════════════════════════════════════


class TestGetRuns:
    """Tests for GET /api/snapshot-collector/runs."""

    def test_returns_ok_and_pagination_fields(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def get_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
                return {
                    "items": [
                        {"runId": "r1", "status": "completed"},
                        {"runId": "r2", "status": "blocked"},
                    ],
                    "total": 2,
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.get("/api/snapshot-collector/runs")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["data"]["items"] is not None
        assert body["data"]["total"] == 2
        assert "limit" in body["data"]
        assert "offset" in body["data"]

    def test_runs_has_items_total_limit_offset(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        response = client.get("/api/snapshot-collector/runs")
        body = response.json()
        data = body["data"]
        assert "items" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data

    def test_runs_with_query_params(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured_filters: list[dict[str, Any]] = []

        class Svc(FakeCollectorService):
            def get_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
                captured_filters.append(dict(filters))
                return {"items": [], "total": 0}

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.get(
            "/api/snapshot-collector/runs?datasetId=dragonboard_backend_shadow&status=completed&limit=10&offset=0"
        )

        assert response.status_code == 200
        assert len(captured_filters) == 1
        assert captured_filters[0].get("datasetId") == "dragonboard_backend_shadow"
        assert captured_filters[0].get("status") == "completed"

    def test_runs_passes_pagination_to_service(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        captured_filters: list[dict[str, Any]] = []

        class Svc(FakeCollectorService):
            def get_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
                captured_filters.append(dict(filters))
                return {"items": [], "total": 0}

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.get("/api/snapshot-collector/runs?limit=10&offset=20")

        assert response.status_code == 200
        assert captured_filters[0]["limit"] == 10
        assert captured_filters[0]["offset"] == 20

    def test_runs_default_limit_and_offset(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)
        response = client.get("/api/snapshot-collector/runs")
        body = response.json()
        assert body["data"]["limit"] == 50
        assert body["data"]["offset"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# POST /api/snapshot-collector/audit
# ═══════════════════════════════════════════════════════════════════════════


class TestPostAudit:
    """Tests for POST /api/snapshot-collector/audit."""

    def test_audit_returns_expected_keys(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def audit(self, dataset_id: str, snapshot_type: str, trading_date: str | None = None) -> dict[str, Any]:
                return {
                    "datasetId": dataset_id,
                    "snapshotType": snapshot_type,
                    "tradingDate": trading_date,
                    "missingSlots": ["half_hour:2026-06-11:09:30"],
                    "emptyFrames": ["half_hour:2026-06-11:10:00"],
                    "missingRecords": [],
                    "countDrifts": [{"snapshotId": "half_hour:2026-06-11:10:30", "frameCount": 50, "recordCount": 48}],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/audit",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        data = body["data"]
        assert data["datasetId"] == "dragonboard_backend_shadow"
        assert data["snapshotType"] == "half_hour"
        assert "missingSlots" in data
        assert "emptyFrames" in data
        assert "missingRecords" in data
        assert "countDrifts" in data

    def test_audit_without_trading_date(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def audit(self, dataset_id: str, snapshot_type: str, trading_date: str | None = None) -> dict[str, Any]:
                return {
                    "datasetId": dataset_id,
                    "snapshotType": snapshot_type,
                    "tradingDate": None,
                    "missingSlots": [],
                    "emptyFrames": [],
                    "missingRecords": [],
                    "countDrifts": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/audit",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True

    def test_audit_invalid_snapshot_type_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/audit",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "INVALID",
            },
        )

        assert 400 <= response.status_code < 500
        body = response.json()
        detail = body.get("detail", body)
        assert detail["ok"] is False
        assert detail["status"] == "error"

    def test_audit_missing_dataset_id_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/audit",
            json={
                "snapshotType": "half_hour",
            },
        )

        assert 400 <= response.status_code < 500

    def test_audit_missing_snapshot_type_returns_4xx(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        response = client.post(
            "/api/snapshot-collector/audit",
            json={
                "datasetId": "dragonboard_backend_shadow",
            },
        )

        assert 400 <= response.status_code < 500

    def test_audit_with_missing_slots(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def audit(self, dataset_id: str, snapshot_type: str, trading_date: str | None = None) -> dict[str, Any]:
                return {
                    "datasetId": dataset_id,
                    "snapshotType": snapshot_type,
                    "tradingDate": trading_date,
                    "missingSlots": ["half_hour:2026-06-11:09:30", "half_hour:2026-06-11:10:00"],
                    "emptyFrames": [],
                    "missingRecords": [],
                    "countDrifts": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/audit",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
                "tradingDate": "2026-06-11",
            },
        )

        body = response.json()
        assert body["ok"] is True
        assert len(body["data"]["missingSlots"]) == 2

    def test_audit_with_count_drifts(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def audit(self, dataset_id: str, snapshot_type: str, trading_date: str | None = None) -> dict[str, Any]:
                return {
                    "datasetId": dataset_id,
                    "snapshotType": snapshot_type,
                    "tradingDate": trading_date,
                    "missingSlots": [],
                    "emptyFrames": [],
                    "missingRecords": [],
                    "countDrifts": [
                        {"snapshotId": "half_hour:2026-06-11:10:00", "frameCount": 100, "recordCount": 98},
                        {"snapshotId": "half_hour:2026-06-11:10:30", "frameCount": 100, "recordCount": 95},
                    ],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/audit",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
            },
        )

        body = response.json()
        assert len(body["data"]["countDrifts"]) == 2

    def test_audit_has_missing_records(self, monkeypatch: Any) -> None:
        client, _ = _setup_client(monkeypatch)

        class Svc(FakeCollectorService):
            def audit(self, dataset_id: str, snapshot_type: str, trading_date: str | None = None) -> dict[str, Any]:
                return {
                    "datasetId": dataset_id,
                    "snapshotType": snapshot_type,
                    "tradingDate": trading_date,
                    "missingSlots": [],
                    "emptyFrames": [],
                    "missingRecords": ["half_hour:2026-06-11:11:00"],
                    "countDrifts": [],
                }

        monkeypatch.setattr(
            "backend.api.snapshot_collector_routes.SnapshotCollectorService", Svc
        )

        response = client.post(
            "/api/snapshot-collector/audit",
            json={
                "datasetId": "dragonboard_backend_shadow",
                "snapshotType": "half_hour",
            },
        )

        body = response.json()
        assert body["ok"] is True
        assert len(body["data"]["missingRecords"]) == 1
