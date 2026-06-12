"""Tests for settings, repository port, and service factory for the snapshot collector.

Task 3: Settings, Repository Port, and Service Factory.
"""

from __future__ import annotations

import inspect
import os
from typing import Any

from backend.settings import Settings


# ── Fake repository for protocol validation ───────────────────────────────────


class FakeSnapshotRepository:
    """In-memory implementation of SnapshotRepository for testing protocol conformance."""

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
        # Always record the write — dedup is a service-level concern.
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


# ── Settings default tests ────────────────────────────────────────────────────


class TestSettingsDefaults:
    """Verify snapshot collector settings fields match the contract."""

    def test_collector_disabled_by_default(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_enabled is False

    def test_default_dataset_id_is_shadow(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_dataset_id == "dragonboard_backend_shadow"

    def test_default_types_are_half_hour_and_daily(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_types == "half_hour,daily"

    def test_default_poll_ms_is_1000(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_poll_ms == 1000

    def test_default_close_grace_minutes_is_5(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_close_grace_minutes == 5

    def test_default_proxy_base_url(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_proxy_base_url == "http://127.0.0.1:3000"

    def test_default_bridge_base_url(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_bridge_base_url == "http://127.0.0.1:8765"

    def test_default_provider_timeout_ms_is_5000(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_provider_timeout_ms == 5000

    def test_default_allow_live_dataset_is_false(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_allow_live_dataset is False


class TestSettingsEnvOverrides:
    """Verify env var overrides work for snapshot collector settings."""

    def test_enabled_via_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED", "1")
        settings = Settings()
        assert settings.snapshot_collector_enabled is True

    def test_dataset_id_via_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID", "custom_dataset")
        settings = Settings()
        assert settings.snapshot_collector_dataset_id == "custom_dataset"

    def test_types_via_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES", "quarter_hour,daily")
        settings = Settings()
        assert settings.snapshot_collector_types == "quarter_hour,daily"

    def test_poll_ms_via_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_POLL_MS", "500")
        settings = Settings()
        assert settings.snapshot_collector_poll_ms == 500

    def test_close_grace_minutes_via_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_CLOSE_GRACE_MINUTES", "10")
        settings = Settings()
        assert settings.snapshot_collector_close_grace_minutes == 10

    def test_proxy_base_url_via_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_PROXY_BASE_URL", "http://other:4000")
        settings = Settings()
        assert settings.snapshot_collector_proxy_base_url == "http://other:4000"

    def test_bridge_base_url_via_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_BRIDGE_BASE_URL", "http://bridge:9999")
        settings = Settings()
        assert settings.snapshot_collector_bridge_base_url == "http://bridge:9999"

    def test_provider_timeout_ms_via_env(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_PROVIDER_TIMEOUT_MS", "10000")
        settings = Settings()
        assert settings.snapshot_collector_provider_timeout_ms == 10000

    def test_allow_live_dataset_via_env_true(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET", "1")
        settings = Settings()
        assert settings.snapshot_collector_allow_live_dataset is True


class TestLiveDatasetBlocked:
    """dragonboard_live must be blocked unless QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=1."""

    def test_live_dataset_blocked_by_default(self) -> None:
        settings = Settings()
        assert settings.snapshot_collector_allow_live_dataset is False

    def test_live_dataset_allowed_when_env_set_explicitly(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET", "1")
        settings = Settings()
        assert settings.snapshot_collector_allow_live_dataset is True

    def test_live_dataset_blocked_with_explicit_zero(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET", "0")
        settings = Settings()
        assert settings.snapshot_collector_allow_live_dataset is False

    def test_live_dataset_blocked_with_invalid_value(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET", "maybe")
        settings = Settings()
        assert settings.snapshot_collector_allow_live_dataset is False


class TestSettingsPreserveExistingDefaults:
    """Adding collector fields must not change existing non-collector defaults."""

    def test_storage_backend_default_preserved(self) -> None:
        settings = Settings()
        assert settings.storage_backend == "sqlite"

    def test_mongodb_database_default_preserved(self, monkeypatch: Any) -> None:
        monkeypatch.delenv("QUANT_BOARD_MONGODB_DATABASE", raising=False)
        settings = Settings()
        assert settings.mongodb_database == "dragon_board_quant"

    def test_backup_batch_size_default_preserved(self) -> None:
        settings = Settings()
        assert settings.backup_auto_sync_batch_size == 50


# ── Repository port tests ─────────────────────────────────────────────────────


class TestRepositoryPortProtocol:
    """Verify the SnapshotRepository Protocol declares the required method signatures."""

    def test_protocol_declares_required_methods(self) -> None:
        from backend.snapshot_collector.repository_port import SnapshotRepository

        members = {
            name
            for name, member in inspect.getmembers(SnapshotRepository)
            if not name.startswith("_") and (callable(member) or inspect.isfunction(member))
        }
        expected = {
            "snapshot_exists",
            "save_snapshot_ingest",
            "insert_run",
            "list_runs",
            "collector_status",
            "audit_dataset",
        }
        missing = expected - members
        assert not missing, f"Protocol is missing methods: {missing}"

    def test_fake_implements_all_protocol_methods(self) -> None:
        """FakeSnapshotRepository must satisfy the SnapshotRepository protocol."""
        from backend.snapshot_collector.repository_port import SnapshotRepository

        repo = FakeSnapshotRepository()
        assert isinstance(repo, SnapshotRepository), "FakeSnapshotRepository must satisfy SnapshotRepository protocol"


class TestFakeRepositorySnapshotExists:
    """snapshot_exists returns bool and respects dataset_id."""

    def test_returns_false_for_unknown_snapshot(self) -> None:
        repo = FakeSnapshotRepository()
        assert repo.snapshot_exists("ds", "s1") is False

    def test_returns_false_for_unknown_dataset(self) -> None:
        repo = FakeSnapshotRepository()
        assert repo.snapshot_exists("unknown_ds", "s1") is False

    def test_returns_true_after_ingest(self) -> None:
        repo = FakeSnapshotRepository()
        repo.save_snapshot_ingest(
            dataset={"id": "ds"},
            records=[{"snapshotId": "s1"}],
            frames=[{"snapshotId": "s1"}],
            stock_rows=[],
            sector_rows=[],
            idempotency_key="k1",
        )
        assert repo.snapshot_exists("ds", "s1") is True

    def test_only_matches_dataset_boundary(self) -> None:
        repo = FakeSnapshotRepository()
        repo.save_snapshot_ingest(
            dataset={"id": "ds1"},
            records=[{"snapshotId": "s1"}],
            frames=[],
            stock_rows=[],
            sector_rows=[],
            idempotency_key="k1",
        )
        assert repo.snapshot_exists("ds2", "s1") is False


class TestFakeRepositorySaveSnapshotIngest:
    """save_snapshot_ingest persists and deduplicates."""

    def test_first_ingest_returns_done(self) -> None:
        repo = FakeSnapshotRepository()
        result = repo.save_snapshot_ingest(
            dataset={"id": "ds"},
            records=[{"snapshotId": "s1"}],
            frames=[],
            stock_rows=[],
            sector_rows=[],
            idempotency_key="k1",
        )
        assert result["status"] == "done"
        assert result["deduped"] is False

    def test_repeated_snapshot_ids_still_save(self) -> None:
        """Save always writes — dedup is handled at the service level via snapshot_exists."""
        repo = FakeSnapshotRepository()
        repo.save_snapshot_ingest(
            dataset={"id": "ds"},
            records=[{"snapshotId": "s1"}],
            frames=[],
            stock_rows=[],
            sector_rows=[],
            idempotency_key="k1",
        )
        result = repo.save_snapshot_ingest(
            dataset={"id": "ds"},
            records=[{"snapshotId": "s1"}],
            frames=[],
            stock_rows=[],
            sector_rows=[],
            idempotency_key="k2",
        )
        # The FakeRepository always writes; the service handles dedup via snapshot_exists
        assert result["status"] == "done"
        assert len(repo._ingests) == 2

    def test_new_snapshot_ids_after_partial_dedupe(self) -> None:
        repo = FakeSnapshotRepository()
        repo.save_snapshot_ingest(
            dataset={"id": "ds"},
            records=[{"snapshotId": "s1"}],
            frames=[],
            stock_rows=[],
            sector_rows=[],
            idempotency_key="k1",
        )
        result = repo.save_snapshot_ingest(
            dataset={"id": "ds"},
            records=[{"snapshotId": "s1"}, {"snapshotId": "s2"}],
            frames=[],
            stock_rows=[],
            sector_rows=[],
            idempotency_key="k2",
        )
        assert result["deduped"] is False


class TestFakeRepositoryInsertRunAndListRuns:
    """insert_run writes to runs; list_runs filters and returns items/total."""

    def test_insert_and_list_single_run(self) -> None:
        repo = FakeSnapshotRepository()
        repo.insert_run({"runId": "r1", "datasetId": "ds", "status": "completed"})
        result = repo.list_runs({"datasetId": "ds"})
        assert result["total"] == 1
        assert result["items"][0]["runId"] == "r1"

    def test_list_runs_filters_by_fields(self) -> None:
        repo = FakeSnapshotRepository()
        repo.insert_run({"runId": "r1", "datasetId": "ds1", "status": "completed"})
        repo.insert_run({"runId": "r2", "datasetId": "ds2", "status": "blocked"})
        result = repo.list_runs({"datasetId": "ds1"})
        assert result["total"] == 1
        assert result["items"][0]["runId"] == "r1"


class TestFakeRepositoryCollectorStatus:
    """collector_status returns structured state dict."""

    def test_status_keys(self) -> None:
        repo = FakeSnapshotRepository()
        status = repo.collector_status()
        assert "mode" in status
        assert isinstance(status, dict)


class TestFakeRepositoryAuditDataset:
    """audit_dataset returns structured audit summary."""

    def test_audit_returns_expected_keys(self) -> None:
        repo = FakeSnapshotRepository()
        audit = repo.audit_dataset("ds", "half_hour", trading_date="2026-06-11")
        assert audit["datasetId"] == "ds"
        assert "missingSlots" in audit
        assert "emptyFrames" in audit
        assert "missingRecords" in audit
        assert "countDrifts" in audit

    def test_audit_without_trading_date(self) -> None:
        repo = FakeSnapshotRepository()
        audit = repo.audit_dataset("ds", "half_hour")
        assert audit["tradingDate"] is None


# ── Service factory tests ─────────────────────────────────────────────────────


class TestServiceFactory:
    """Verify service_factory creates correct repository."""

    def test_factory_module_exists_and_has_expected_function(self) -> None:
        from backend.snapshot_collector import service_factory

        assert hasattr(service_factory, "create_snapshot_collector_repository")
        assert callable(service_factory.create_snapshot_collector_repository)

    def test_factory_returns_snapshot_repository_protocol_instance(self, monkeypatch: Any) -> None:
        """Factory must return an object satisfying the SnapshotRepository protocol."""
        from backend.data.repository_factory import _runtime_mongodb_database as orig
        from backend.snapshot_collector.repository_port import SnapshotRepository
        from backend.snapshot_collector.service_factory import (
            create_snapshot_collector_repository,
        )

        # Use the FakeMongoDatabase with MongoRepository pattern from existing tests
        from backend.data.mongo_repository import MongoRepository

        # Match the test pattern from test_mongo_repository.py
        class FakeCursor:
            def __init__(self, rows: list[dict[str, Any]]) -> None:
                self.rows = rows

            def sort(self, keys: Any) -> "FakeCursor":
                sort_keys = list(keys if isinstance(keys, list) else [keys])
                for key, direction in reversed(sort_keys):
                    self.rows.sort(
                        key=lambda row: row.get(key) or 0,
                        reverse=int(direction) < 0,
                    )
                return self

            def limit(self, count: int) -> "FakeCursor":
                if count and count > 0:
                    self.rows = self.rows[:count]
                return self

            def __iter__(self) -> Any:
                return iter(self.rows)

        class FakeCollection:
            def __init__(self) -> None:
                self.rows: list[dict[str, Any]] = []

            def count_documents(self, query: dict[str, Any]) -> int:
                return len(list(self.find(query)))

            def delete_many(self, query: dict[str, Any]) -> Any:
                before = len(self.rows)
                self.rows = [
                    row
                    for row in self.rows
                    if not _fake_matches(row, query)
                ]
                return type(
                    "DeleteResult", (), {"deleted_count": before - len(self.rows)}
                )()

            def insert_many(
                self, rows: list[dict[str, Any]], ordered: bool = False
            ) -> None:
                assert ordered is False
                self.rows.extend(dict(row) for row in rows)

            def replace_one(
                self,
                query: dict[str, Any],
                document: dict[str, Any],
                upsert: bool = False,
            ) -> None:
                for index, row in enumerate(self.rows):
                    if _fake_matches(row, query):
                        self.rows[index] = dict(document)
                        return
                if upsert:
                    self.rows.append(dict(document))

            def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
                return next(iter(self.find(query)), None)

            def find(self, query: dict[str, Any] | None = None) -> FakeCursor:
                return FakeCursor(
                    [dict(row) for row in self.rows if _fake_matches(row, query or {})]
                )

        class FakeMongoDatabase(dict):
            def __getitem__(self, name: str) -> FakeCollection:
                if name not in self:
                    self[name] = FakeCollection()
                return dict.__getitem__(self, name)

        def _fake_matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
            for key, expected in query.items():
                value = row.get(key)
                if isinstance(expected, dict):
                    if "$in" in expected and value not in expected["$in"]:
                        return False
                    if "$gte" in expected and value < expected["$gte"]:
                        return False
                    if "$lte" in expected and value > expected["$lte"]:
                        return False
                    if "$lt" in expected and value >= expected["$lt"]:
                        return False
                    if "$ne" in expected and value == expected["$ne"]:
                        return False
                    continue
                if value != expected:
                    return False
            return True

        fake_db = FakeMongoDatabase()

        import backend.snapshot_collector.service_factory as sf

        monkeypatch.setattr(sf, "get_runtime_mongodb_database", lambda: fake_db)
        monkeypatch.setattr(sf, "get_settings", lambda: type(
            "FakeSettings",
            (),
            {"storage_backend": "mongodb", "mongodb_uri": "", "mongodb_database": "test"},
        )())

        repo = create_snapshot_collector_repository()

        assert isinstance(
            repo, SnapshotRepository
        ), "Factory must return an instance that satisfies SnapshotRepository"

    def test_service_factory_injects_current_settings(self, monkeypatch: Any) -> None:
        """API and CLI service instances must honor QUANT_BOARD_* settings."""
        import backend.snapshot_collector.service_factory as sf

        fake_settings = _make_simple_settings(
            snapshot_collector_proxy_base_url="http://proxy.example",
            snapshot_collector_bridge_base_url="http://bridge.example",
            snapshot_collector_allow_live_dataset=True,
        )
        monkeypatch.setattr(sf, "get_settings", lambda: fake_settings)

        service = sf.create_snapshot_collector_service(FakeSnapshotRepository())

        assert service._settings is fake_settings
        assert service._proxy_base_url() == "http://proxy.example"
        assert service._bridge_base_url() == "http://bridge.example"
        assert service._allow_live_dataset() is True

    def test_factory_raises_for_sqlite_backend(self, monkeypatch: Any) -> None:
        """SQLite backend is not supported for snapshot collector."""
        import backend.snapshot_collector.service_factory as sf
        from backend.snapshot_collector.service_factory import (
            create_snapshot_collector_repository,
        )

        monkeypatch.setattr(sf, "get_settings", lambda: type(
            "FakeSettings",
            (),
            {"storage_backend": "sqlite"},
        )())

        with __import__("pytest").raises(ValueError, match="snapshot collector requires MongoDB"):
            create_snapshot_collector_repository()


# ═══════════════════════════════════════════════════════════════════════════════
# Fake market data helpers for service orchestration tests
# ═══════════════════════════════════════════════════════════════════════════════


def _fake_market_context(
    *,
    stocks: list[dict[str, Any]] | None = None,
    source_health: list[dict[str, Any]] | None = None,
) -> Any:
    """Build a MarketDataContext suitable for service testing."""
    from backend.snapshot_collector.models import MarketDataContext, SourceHealth

    ctx = MarketDataContext()
    if stocks is not None:
        ctx.stocks = stocks
    if source_health is not None:
        ctx.source_health = [
            SourceHealth(**sh) if isinstance(sh, dict) else sh for sh in source_health
        ]
    return ctx


def _fake_collect_fn(
    stocks: list[dict[str, Any]] | None = None,
    source_health: list[dict[str, Any]] | None = None,
    market_meta: dict[str, Any] | None = None,
):
    """Return a collect_market_context impl that yields the given data."""

    def _collect(providers, codes, *, timeout_ms=5000):
        ctx = _fake_market_context(stocks=stocks, source_health=source_health)
        if market_meta:
            ctx.market_meta = market_meta
        return ctx

    return _collect


def _standard_stocks() -> list[dict[str, Any]]:
    """Valid A-share stock rows for testing."""
    return [
        {"code": "000001", "name": "平安银行", "rank": 1, "price": 12.5, "pctChange": 2.5, "volume": 100000, "amount": 1250000.0, "turnover": 1.2, "heat": 85.0},
        {"code": "600001", "name": "邯郸钢铁", "rank": 2, "price": 5.8, "pctChange": -1.2, "volume": 50000, "amount": 290000.0, "turnover": 0.8, "heat": 70.0},
        {"code": "300001", "name": "特锐德", "rank": 3, "price": 20.0, "pctChange": 5.0, "volume": 20000, "amount": 400000.0, "turnover": 3.5, "heat": 90.0},
    ]


def _standard_health() -> list[dict[str, Any]]:
    """Healthy source health records."""
    return [
        {"source": "hotlist_proxy", "ok": True, "latency_ms": 50, "row_count": 3, "error": "", "captured_at": "2026-06-11T10:00:00Z"},
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Service orchestration tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestServiceDryRun:
    """dry-run returns dryRun=true and does NOT write fact data."""

    def test_dry_run_does_not_call_repo_fact_write(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=True,
        )

        result = service.run_once(request)

        assert result.status == "dry_run"
        assert result.dry_run is True
        assert result.deduped is False
        assert len(repo._ingests) == 0, "dry-run must not write fact data"

    def test_dry_run_still_collects_and_evaluates_quality(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=True,
        )

        result = service.run_once(request)

        # Should have quality evaluation result
        assert result.quality is not None
        assert result.quality.ok is True

    def test_dry_run_does_not_short_circuit_on_existing_snapshot(self) -> None:
        """Dry-run must still go through full pipeline, not short-circuit on dedup."""
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        # Pre-populate the repo with the same snapshot
        repo.save_snapshot_ingest(
            dataset={"id": "dragonboard_backend_shadow"},
            records=[{"snapshotId": "half_hour:2026-06-11:10:00"}],
            frames=[{"snapshotId": "half_hour:2026-06-11:10:00"}],
            stock_rows=[],
            sector_rows=[],
            idempotency_key="k",
        )

        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=True,
        )

        result = service.run_once(request)

        # Even though snapshot already exists, dry_run should still run pipeline
        assert result.status == "dry_run"
        assert result.quality is not None


class TestServiceApply:
    """apply writes one valid snapshot."""

    def test_apply_writes_valid_snapshot(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "completed"
        assert result.deduped is False
        assert result.dry_run is False
        assert len(repo._runs) == 1
        assert repo._runs[0]["status"] == "completed"

    def test_repeated_apply_returns_deduped(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        # First call writes
        result1 = service.run_once(request)
        assert result1.status == "completed"
        assert result1.deduped is False

        # Second call dedupes
        result2 = service.run_once(request)
        assert result2.status == "deduped"
        assert result2.deduped is True
        # Should NOT write a second ingest
        assert len(repo._ingests) == 1

    def test_force_bypasses_dedup(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        # First write
        request1 = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
            force=False,
        )
        result1 = service.run_once(request1)
        assert result1.status == "completed"

        # Second call with force=True should re-save
        request2 = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
            force=True,
        )
        result2 = service.run_once(request2)
        assert result2.status == "completed"
        assert result2.deduped is False
        assert len(repo._ingests) == 2


class TestServiceBlocked:
    """empty provider data or invalid quality returns blocked status."""

    def test_empty_provider_returns_blocked(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        # No stocks
        fake_collect = _fake_collect_fn(stocks=[], source_health=[])
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "blocked"
        assert result.quality is not None
        assert result.quality.ok is False
        assert "empty_stock_rows" in result.quality.blocking_issues
        # No fact write
        assert len(repo._ingests) == 0

    def test_empty_stock_rows_blocked(self) -> None:
        """Specifically test empty_stock_rows blocking."""
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        fake_collect = _fake_collect_fn(
            stocks=[],
            source_health=[{"source": "hotlist_proxy", "ok": True, "latency_ms": 50, "row_count": 0, "error": "", "captured_at": "2026-06-11T10:00:00Z"}],
        )
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "blocked"
        assert "empty_stock_rows" in result.quality.blocking_issues
        assert len(repo._ingests) == 0

    def test_invalid_stock_code_blocked(self) -> None:
        """Stock codes not matching A-share format (6 digits starting 0/3/6) are blocked."""
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        invalid_stocks = [
            {"code": "INVALID", "name": "BadCode", "rank": 1},
        ]
        health = [{"source": "hotlist_proxy", "ok": True, "latency_ms": 50, "row_count": 1, "error": "", "captured_at": "2026-06-11T10:00:00Z"}]
        fake_collect = _fake_collect_fn(stocks=invalid_stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "blocked"
        assert "invalid_stock_code" in result.quality.blocking_issues
        assert len(repo._ingests) == 0

    def test_timestamp_mismatch_blocked(self) -> None:
        """actual_timestamp_ms before slot_timestamp_ms is blocked."""
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        # Use a future slot_time so that actual timestamp (now) is before slot
        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2099-01-01",  # far future
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        # The timestamp for far-future slot will be after current time
        # but since we use time.time() internally for actual, this should trigger timestamp_outside_slot
        assert result.status == "blocked"
        assert "timestamp_outside_slot" in result.quality.blocking_issues


class TestServiceRunStateRecording:
    """run state records success, deduped, dry_run, and blocked attempts."""

    def test_records_completed_run_state(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "completed"
        assert len(repo._runs) == 1
        run = repo._runs[0]
        assert run["status"] == "completed"
        assert run["datasetId"] == "dragonboard_backend_shadow"
        assert run["snapshotId"] == "half_hour:2026-06-11:10:00"
        assert "createdAt" in run

    def test_records_deduped_run_state(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        service.run_once(request)  # first
        service.run_once(request)  # second — should dedupe

        assert len(repo._runs) == 2
        assert repo._runs[0]["status"] == "completed"
        assert repo._runs[1]["status"] == "deduped"
        assert repo._runs[1]["deduped"] is True

    def test_records_dry_run_state(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=True,
        )

        result = service.run_once(request)

        assert result.status == "dry_run"
        assert len(repo._runs) == 1
        run = repo._runs[0]
        assert run["status"] == "dry_run"
        assert run["dryRun"] is True

    def test_records_blocked_run_state(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        fake_collect = _fake_collect_fn(stocks=[], source_health=[])  # empty blocks
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "blocked"
        assert len(repo._runs) == 1
        run = repo._runs[0]
        assert run["status"] == "blocked"
        # Blocking issues should be recorded
        assert run.get("blockingIssues") is not None or result.quality is not None


class TestServiceGetStatus:
    """get_status returns current collector state."""

    def test_get_status_returns_dict(self) -> None:
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        service = SnapshotCollectorService(repo=repo)

        status = service.get_status()
        assert isinstance(status, dict)
        assert "mode" in status

    def test_get_status_reflects_last_run(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        service.run_once(request)
        status = service.get_status()
        assert status.get("mode") is not None


class TestServiceGetRuns:
    """get_runs filters and returns run records."""

    def test_get_runs_no_filter(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="dragonboard_backend_shadow",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        service.run_once(request)
        runs = service.get_runs({})
        assert runs["total"] == 1
        assert len(runs["items"]) == 1

    def test_get_runs_with_filter(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        stocks = _standard_stocks()
        health = _standard_health()
        fake_collect = _fake_collect_fn(stocks=stocks, source_health=health)
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request1 = CollectorRunRequest(
            dataset_id="ds1", snapshot_type="half_hour",
            trading_date="2026-06-11", slot_time="10:00", dry_run=False,
        )
        request2 = CollectorRunRequest(
            dataset_id="ds2", snapshot_type="half_hour",
            trading_date="2026-06-11", slot_time="10:00", dry_run=False,
        )

        service.run_once(request1)
        service.run_once(request2)

        runs = service.get_runs({"datasetId": "ds1"})
        assert runs["total"] == 1
        assert runs["items"][0]["datasetId"] == "ds1"


class TestServiceAudit:
    """audit returns structured coverage summary."""

    def test_audit_returns_expected_structure(self) -> None:
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        service = SnapshotCollectorService(repo=repo)

        audit = service.audit("ds", "half_hour", trading_date="2026-06-11")
        assert audit["datasetId"] == "ds"
        assert "missingSlots" in audit
        assert "emptyFrames" in audit
        assert "missingRecords" in audit
        assert "countDrifts" in audit

    def test_audit_without_trading_date(self) -> None:
        from backend.snapshot_collector.service import SnapshotCollectorService

        repo = FakeSnapshotRepository()
        service = SnapshotCollectorService(repo=repo)

        audit = service.audit("ds", "half_hour")
        assert audit["tradingDate"] is None


# ── Passthrough normalizer (fake) ────────────────────────────────────────────


def _passthrough_normalize(request: Any) -> tuple[Any, list[dict], list[dict], list[dict], list[dict], str]:
    """Fake normalizer that extracts bundle items without pydantic validation."""
    bundle = request.bundle
    records = bundle.get("items") or bundle.get("records") or []
    frames = bundle.get("frames") or []
    stock_rows = bundle.get("stockRows") or bundle.get("stock_rows") or []
    sector_rows = bundle.get("sectorRows") or bundle.get("sector_rows") or []

    class FakeDataset:
        def __init__(self):
            self.id = request.dataset_id or "default"

    dataset = FakeDataset()
    idempotency_key = request.idempotency_key or "test-key"
    return dataset, list(records), list(frames), list(stock_rows), list(sector_rows), idempotency_key


def _make_simple_settings(**overrides):
    """Create a minimal settings-like object for tests."""
    defaults = {
        "snapshot_collector_dataset_id": "dragonboard_backend_shadow",
        "snapshot_collector_types": "half_hour,daily",
        "snapshot_collector_poll_ms": 1000,
        "snapshot_collector_close_grace_minutes": 5,
        "snapshot_collector_proxy_base_url": "http://127.0.0.1:3000",
        "snapshot_collector_bridge_base_url": "http://127.0.0.1:8765",
        "snapshot_collector_provider_timeout_ms": 5000,
        "snapshot_collector_allow_live_dataset": False,
    }
    defaults.update(overrides)
    return type("FakeSettings", (), defaults)()
