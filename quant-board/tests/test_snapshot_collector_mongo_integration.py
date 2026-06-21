"""Integration tests for snapshot collector + MongoRepository (Task 8).

Uses the FakeMongoDatabase pattern from test_mongo_repository.py to verify
end-to-end behaviour through the service orchestration layer backed by a
real MongoRepository.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

# ── Fake MongoDB infrastructure (matching test_mongo_repository.py) ──────────


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def sort(self, keys: Any, direction: int | None = None) -> "FakeCursor":
        # Support both .sort([(k, d), ...]) and .sort("key", direction)
        if isinstance(keys, str) and direction is not None:
            sort_keys = [(keys, direction)]
        elif isinstance(keys, tuple) and len(keys) == 2 and isinstance(keys[0], str):
            sort_keys = [keys]
        elif isinstance(keys, list):
            sort_keys = list(keys)
        else:
            sort_keys = []
        for key, dir_val in reversed(sort_keys):
            self.rows.sort(
                key=lambda row: row.get(key) or 0,
                reverse=int(dir_val) < 0,
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
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return type("DeleteResult", (), {"deleted_count": before - len(self.rows)})()

    def insert_many(self, rows: list[dict[str, Any]], ordered: bool = False) -> None:
        assert ordered is False
        self.rows.extend(dict(row) for row in rows)

    def replace_one(
        self,
        query: dict[str, Any],
        document: dict[str, Any],
        upsert: bool = False,
    ) -> None:
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                self.rows[index] = dict(document)
                return
        if upsert:
            self.rows.append(dict(document))

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next(iter(self.find(query)), None)

    def find(self, query: dict[str, Any] | None = None) -> FakeCursor:
        return FakeCursor(
            [dict(row) for row in self.rows if _matches(row, query or {})]
        )


class FakeMongoDatabase(dict):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
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


# ── Helpers ───────────────────────────────────────────────────────────────────


def _mongo_repo(db: FakeMongoDatabase):
    """Create a MongoRepository backed by FakeMongoDatabase."""
    from backend.data.mongo_repository import MongoRepository

    return MongoRepository(db)


def _standard_stocks() -> list[dict[str, Any]]:
    return [
        {
            "code": "000001",
            "name": "平安银行",
            "rank": 1,
            "price": 12.5,
            "pctChange": 2.5,
            "volume": 100000,
            "amount": 1250000.0,
            "turnover": 1.2,
            "heat": 85.0,
        },
        {
            "code": "600001",
            "name": "邯郸钢铁",
            "rank": 2,
            "price": 5.8,
            "pctChange": -1.2,
            "volume": 50000,
            "amount": 290000.0,
            "turnover": 0.8,
            "heat": 70.0,
        },
    ]


def _standard_health() -> list[dict[str, Any]]:
    return [
        {
            "source": "hotlist_proxy",
            "ok": True,
            "latency_ms": 50,
            "row_count": 2,
            "error": "",
            "captured_at": "2026-06-11T10:00:00Z",
        },
    ]


def _fake_market_context(
    stocks: list[dict[str, Any]] | None = None,
    source_health: list[dict[str, Any]] | None = None,
) -> Any:
    """Build a MarketDataContext."""
    from backend.snapshot_collector.models import MarketDataContext, SourceHealth

    ctx = MarketDataContext()
    if stocks is not None:
        ctx.stocks = list(stocks)
    if source_health is not None:
        ctx.source_health = [
            SourceHealth(**sh) if isinstance(sh, dict) else sh for sh in source_health
        ]
    return ctx


def _fake_collect_fn(
    stocks: list[dict[str, Any]] | None = None,
    source_health: list[dict[str, Any]] | None = None,
):
    """Return a collect_market_context impl that yields the given data."""

    def _collect(providers, codes, *, timeout_ms=5000):
        ctx = _fake_market_context(stocks=stocks, source_health=source_health)
        return ctx

    return _collect


def _passthrough_normalize(request: Any) -> tuple[Any, list[dict], list[dict], list[dict], list[dict], str]:
    """Fake normalizer that extracts bundle items."""
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


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestMongoIntegrationDryRun:
    """dry-run writes no fact collections."""

    def test_dry_run_no_facts_written(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)

        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
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
            dataset_id="test_dry",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=True,
        )

        result = service.run_once(request)

        assert result.status == "dry_run"

        # No snapshot records should be written
        record_count = db.get("snapshot_records", FakeCollection()).count_documents({})
        frame_count = db.get("snapshot_frames", FakeCollection()).count_documents({})
        stock_count = db.get("snapshot_stock_rows", FakeCollection()).count_documents({})
        sector_count = db.get("snapshot_sector_rows", FakeCollection()).count_documents({})

        assert record_count == 0, "dry-run must not write snapshot_records"
        assert frame_count == 0, "dry-run must not write snapshot_frames"
        assert stock_count == 0, "dry-run must not write snapshot_stock_rows"
        assert sector_count == 0, "dry-run must not write snapshot_sector_rows"

    def test_dry_run_still_writes_run_record(self) -> None:
        """dry-run must record the attempt in snapshot_collector_runs even without fact write."""
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
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
            dataset_id="test_dry",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=True,
        )

        result = service.run_once(request)

        assert result.status == "dry_run"

        # Run record should exist
        runs_coll = db.get("snapshot_collector_runs", FakeCollection())
        assert runs_coll.count_documents({}) == 1
        run = next(iter(runs_coll.find()))
        assert run["status"] == "dry_run"
        assert run["dryRun"] is True


class TestMongoIntegrationApply:
    """apply writes records, frames, stock rows, and sector rows."""

    def test_apply_writes_all_collections(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
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
            dataset_id="test_apply",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "completed"

        # Check all collections have data
        from backend.data.mongo_repository import MongoRepository

        mongo_repo = MongoRepository(db)
        counts = mongo_repo.snapshot_table_counts("test_apply")
        assert counts["snapshots"] >= 1, f"Expected snapshots, got {counts}"
        assert counts["snapshot_frames"] >= 1, f"Expected frames, got {counts}"
        assert counts["snapshot_stock_rows"] == 2, f"Expected 2 stock rows, got {counts}"
        assert counts["snapshot_sector_rows"] >= 0, f"Expected sector rows >= 0, got {counts}"

    def test_apply_writes_run_record(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
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
            dataset_id="test_apply_run",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "completed"

        runs_coll = db.get("snapshot_collector_runs", FakeCollection())
        assert runs_coll.count_documents({}) == 1
        run = next(iter(runs_coll.find()))
        assert run["status"] == "completed"
        assert run["datasetId"] == "test_apply_run"


class TestMongoIntegrationDedup:
    """repeated apply dedupes."""

    def test_repeated_apply_dedupes(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
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
            dataset_id="test_dedup",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        # First apply
        result1 = service.run_once(request)
        assert result1.status == "completed"
        assert result1.deduped is False

        # Second apply
        result2 = service.run_once(request)
        assert result2.status == "deduped"
        assert result2.deduped is True

        # Run records for both attempts
        runs_coll = db.get("snapshot_collector_runs", FakeCollection())
        assert runs_coll.count_documents({}) == 2

        runs = list(runs_coll.find().sort([("createdAt", -1)]))
        assert runs[0]["status"] == "deduped"
        assert runs[1]["status"] == "completed"

    def test_dedup_does_not_double_write_facts(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        from backend.data.mongo_repository import MongoRepository

        mongo = MongoRepository(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
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
            dataset_id="test_dedup_counts",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        service.run_once(request)
        counts_after_first = mongo.snapshot_table_counts("test_dedup_counts")

        service.run_once(request)
        counts_after_second = mongo.snapshot_table_counts("test_dedup_counts")

        # Counts should remain the same
        assert counts_after_second == counts_after_first


class TestMongoIntegrationBlocked:
    """blocked quality writes run record but no fact collections."""

    def test_blocked_quality_writes_run_record_no_facts(self) -> None:
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
        # Empty stocks => blocked
        fake_collect = _fake_collect_fn(stocks=[], source_health=[])
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="test_blocked",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "blocked"
        assert result.quality is not None
        assert result.quality.ok is False

        # Run record should exist
        runs_coll = db.get("snapshot_collector_runs", FakeCollection())
        assert runs_coll.count_documents({}) == 1
        run = next(iter(runs_coll.find()))
        assert run["status"] == "blocked"

        # But no fact collections
        record_count = db.get("snapshot_records", FakeCollection()).count_documents({})
        frame_count = db.get("snapshot_frames", FakeCollection()).count_documents({})
        assert record_count == 0, "blocked must not write snapshot_records"
        assert frame_count == 0, "blocked must not write snapshot_frames"

    def test_blocked_run_records_blocking_issues(self) -> None:
        """Blocking issues should be captured in the run record."""
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
        # Empty stocks => blocked with empty_stock_rows
        fake_collect = _fake_collect_fn(stocks=[], source_health=[])
        fake_normalize = _passthrough_normalize

        service = SnapshotCollectorService(
            repo=repo,
            collect_fn=fake_collect,
            normalize_fn=fake_normalize,
        )

        request = CollectorRunRequest(
            dataset_id="test_blocked_issues",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        result = service.run_once(request)

        assert result.status == "blocked"
        runs_coll = db.get("snapshot_collector_runs", FakeCollection())
        run = next(iter(runs_coll.find()))
        assert run["status"] == "blocked"
        # Blocking issues should be recorded
        blocking = run.get("blockingIssues") or run.get("blocking_issues") or []
        if isinstance(blocking, str):
            blocking = [blocking]
        assert "empty_stock_rows" in blocking or any(
            "empty" in str(b).lower() for b in blocking
        )


class TestMongoIntegrationAudit:
    """audit reports missing or blocked slots in structured form."""

    def test_audit_returns_structured_summary(self) -> None:
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)

        service = SnapshotCollectorService(repo=repo)
        audit = service.audit("test_audit", "half_hour", trading_date="2026-06-11")

        assert isinstance(audit, dict)
        assert audit["datasetId"] == "test_audit"
        assert "missingSlots" in audit
        assert "emptyFrames" in audit
        assert "missingRecords" in audit
        assert "countDrifts" in audit

    def test_audit_detects_missing_frames(self) -> None:
        """After writing some frames, audit should reflect existing data."""
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
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
            dataset_id="test_audit_detect",
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="10:00",
            dry_run=False,
        )

        service.run_once(request)

        audit = service.audit("test_audit_detect", "half_hour", trading_date="2026-06-11")
        assert audit["totalFrames"] >= 1

    def test_audit_count_drifts_compare_stock_rows_not_records(self) -> None:
        """One snapshot record with two stock rows must not look like a drift."""
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
        snapshot_id = "half_hour:2026-06-11:10:00"
        db["snapshot_frames"].insert_many(
            [
                {
                    "datasetId": "test_audit_stock_rows",
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-06-11",
                    "timestamp": 1781143200000,
                    "stockRowCount": 2,
                }
            ],
            ordered=False,
        )
        db["snapshot_records"].insert_many(
            [
                {
                    "datasetId": "test_audit_stock_rows",
                    "snapshotId": snapshot_id,
                }
            ],
            ordered=False,
        )
        db["snapshot_stock_rows"].insert_many(
            [
                {
                    "datasetId": "test_audit_stock_rows",
                    "snapshotId": snapshot_id,
                    "code": "000001",
                },
                {
                    "datasetId": "test_audit_stock_rows",
                    "snapshotId": snapshot_id,
                    "code": "600001",
                },
            ],
            ordered=False,
        )

        audit = SnapshotCollectorService(repo=repo).audit(
            "test_audit_stock_rows",
            "half_hour",
            trading_date="2026-06-11",
        )

        assert audit["countDrifts"] == []

    def test_audit_reports_empty_state_for_empty_dataset(self) -> None:
        """Audit on a dataset with no data returns zeros."""
        from backend.snapshot_collector.service import SnapshotCollectorService

        db = FakeMongoDatabase()
        mongo = _mongo_repo(db)
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        repo = _MongoSnapshotCollectorRepository(mongo, db)
        service = SnapshotCollectorService(repo=repo)

        audit = service.audit("empty_ds", "half_hour", trading_date="2026-06-11")
        assert audit["totalFrames"] == 0
        assert audit["totalRecords"] == 0


class TestMongoCollectorCompareContract:
    def test_compare_counts_all_expected_slots_and_missing_both(self) -> None:
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        db = FakeMongoDatabase()
        db["snapshot_frames"].insert_many(
            [
                {
                    "datasetId": "live",
                    "snapshotId": "half_hour:2026-06-11:10:00",
                    "type": "half_hour",
                    "tradingDate": "2026-06-11",
                    "stockRowCount": 10,
                },
                {
                    "datasetId": "shadow",
                    "snapshotId": "half_hour:2026-06-11:10:00",
                    "type": "half_hour",
                    "tradingDate": "2026-06-11",
                    "stockRowCount": 9,
                },
            ],
            ordered=False,
        )
        repo = _MongoSnapshotCollectorRepository(_mongo_repo(db), db)

        result = repo.compare_datasets(
            "live", "shadow", "half_hour", trading_date="2026-06-11"
        )

        assert result["summary"]["totalSlotsCompared"] == 10
        assert result["summary"]["slotsMissingInBoth"] == 9
        assert len(result["perDate"][0]["slotsMissingInBoth"]) == 9

    def test_compare_uses_canonical_stock_fields(self) -> None:
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        db = FakeMongoDatabase()
        sid = "half_hour:2026-06-11:10:00"
        for dataset_id in ("live", "shadow"):
            db["snapshot_frames"].insert_many(
                [
                    {
                        "datasetId": dataset_id,
                        "snapshotId": sid,
                        "type": "half_hour",
                        "tradingDate": "2026-06-11",
                        "stockRowCount": 1,
                    }
                ],
                ordered=False,
            )
            db["snapshot_stock_rows"].insert_many(
                [
                    {
                        "datasetId": dataset_id,
                        "snapshotId": sid,
                        "code": "000001",
                        "name": "平安银行",
                        "price": 10.0,
                        "change": 1.2,
                        "volume": 100,
                        "turnover": 1000.0,
                        "turnoverRate": 2.0,
                        "hotness": 80.0,
                        "rank": 1,
                        "totalMV": 100000.0,
                    }
                ],
                ordered=False,
            )
        repo = _MongoSnapshotCollectorRepository(_mongo_repo(db), db)

        result = repo.compare_datasets(
            "live", "shadow", "half_hour", trading_date="2026-06-11"
        )
        rates = result["perDate"][0]["slotDetails"][0]["fieldMissingRatesA"]

        assert rates["change"]["rate"] == 0.0
        assert rates["totalMV"]["rate"] == 0.0

    def test_force_replace_overwrites_existing_snapshot(self) -> None:
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        db = FakeMongoDatabase()
        repo = _MongoSnapshotCollectorRepository(_mongo_repo(db), db)
        sid = "half_hour:2026-06-11:10:00"
        dataset = {"id": "shadow", "name": "shadow"}
        records = [{"snapshotId": sid, "id": sid, "tradingDate": "2026-06-11"}]
        frames = [
            {
                "snapshotId": sid,
                "id": sid,
                "type": "half_hour",
                "tradingDate": "2026-06-11",
                "stockRowCount": 1,
            }
        ]

        repo.save_snapshot_ingest(
            dataset,
            records,
            frames,
            [{"snapshotId": sid, "code": "000001", "price": 10.0}],
            [],
            idempotency_key="first",
        )
        repo.replace_snapshot_ingest(
            dataset,
            records,
            frames,
            [{"snapshotId": sid, "code": "000001", "price": 20.0}],
            [],
            idempotency_key="force-second",
        )

        rows = list(
            db["snapshot_stock_rows"].find(
                {"datasetId": "shadow", "snapshotId": sid}
            )
        )
        assert len(rows) == 1
        assert rows[0]["price"] == 20.0

    def test_force_replace_restores_existing_snapshot_when_insert_fails(self) -> None:
        from backend.snapshot_collector.service_factory import _MongoSnapshotCollectorRepository

        db = FakeMongoDatabase()
        repo = _MongoSnapshotCollectorRepository(_mongo_repo(db), db)
        sid = "half_hour:2026-06-11:10:00"
        dataset = {"id": "shadow", "name": "shadow"}
        records = [{"snapshotId": sid, "id": sid, "tradingDate": "2026-06-11"}]
        frames = [
            {
                "snapshotId": sid,
                "id": sid,
                "type": "half_hour",
                "tradingDate": "2026-06-11",
                "stockRowCount": 1,
            }
        ]
        repo.save_snapshot_ingest(
            dataset,
            records,
            frames,
            [{"snapshotId": sid, "code": "000001", "price": 10.0}],
            [],
            idempotency_key="first",
        )

        frame_collection = db["snapshot_frames"]
        original_insert = frame_collection.insert_many

        def fail_once(rows: list[dict[str, Any]], ordered: bool = False) -> None:
            frame_collection.insert_many = original_insert
            raise RuntimeError("simulated insert failure")

        frame_collection.insert_many = fail_once

        with pytest.raises(RuntimeError, match="simulated insert failure"):
            repo.replace_snapshot_ingest(
                dataset,
                records,
                frames,
                [{"snapshotId": sid, "code": "000001", "price": 20.0}],
                [],
                idempotency_key="force-second",
            )

        restored_frames = list(
            db["snapshot_frames"].find({"datasetId": "shadow", "snapshotId": sid})
        )
        restored_rows = list(
            db["snapshot_stock_rows"].find(
                {"datasetId": "shadow", "snapshotId": sid}
            )
        )
        assert len(restored_frames) == 1
        assert len(restored_rows) == 1
        assert restored_rows[0]["price"] == 10.0
