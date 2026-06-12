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
        if snapshot_ids.issubset(existing):
            return {"status": "deduped", "deduped": True}
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

    def test_repeated_snapshot_ids_return_deduped(self) -> None:
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
        assert result["deduped"] is True

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
