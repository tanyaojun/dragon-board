from __future__ import annotations

import pytest


class DeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.indexes: list[dict[str, object]] = []

    def count_documents(self, query: dict[str, object]) -> int:
        return len(self.find(query))

    def find(self, query: dict[str, object] | None = None) -> list[dict[str, object]]:
        return [row for row in self.rows if _matches(row, query or {})]

    def find_one(self, query: dict[str, object], projection: dict[str, object] | None = None) -> dict[str, object] | None:
        rows = self.find(query)
        return rows[0] if rows else None

    def insert_many(self, rows: list[dict[str, object]], ordered: bool = False) -> None:
        assert ordered is False
        self.rows.extend(rows)

    def update_one(self, query: dict[str, object], update: dict[str, object]) -> None:
        row = self.find_one(query)
        if row is None:
            return
        row.update(update.get("$set", {}))  # type: ignore[arg-type]

    def index_information(self) -> dict[str, dict[str, object]]:
        return {
            str(item.get("name") or "_".join(f"{key}_{direction}" for key, direction in item["keys"])): {
                "key": item["keys"],
                "unique": item.get("unique", False),
            }
            for item in self.indexes
        }

    def create_index(self, keys, unique: bool = False, name: str | None = None) -> None:
        self.indexes.append({"keys": list(keys), "unique": unique, "name": name})


class FakeMongoDatabase(dict[str, FakeCollection]):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_snapshot_backfill_dry_run_selects_nearest_same_type_donor() -> None:
    backfill_empty_snapshot_rows = _load_backfill()
    db = _seed_database()

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-05-08:14:00"],
        apply=False,
    )

    assert result["ok"] is True
    assert result["plans"][0]["donorSnapshotId"] == "half_hour:2026-05-08:13:30"
    assert result["plans"][0]["stockRowsToCopy"] == 2
    assert db["snapshot_stock_rows"].count_documents({"snapshotId": "half_hour:2026-05-08:14:00"}) == 0


def test_snapshot_backfill_apply_copies_rows_and_updates_frame_and_dataset_summary() -> None:
    backfill_empty_snapshot_rows = _load_backfill()
    db = _seed_database()

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-05-08:14:00"],
        apply=True,
    )

    assert result["ok"] is True
    applied = result["applied"]["snapshotRepairs"][0] if isinstance(result["applied"], dict) else result["applied"][0]
    assert applied["insertedStockRows"] == 2
    rows = db["snapshot_stock_rows"].find({"snapshotId": "half_hour:2026-05-08:14:00"})
    assert [row["rowId"] for row in rows] == [
        "half_hour:2026-05-08:14:00:000001",
        "half_hour:2026-05-08:14:00:000002",
    ]
    assert {row["slotTime"] for row in rows} == {"14:00"}
    assert db["snapshot_frames"].find_one({"snapshotId": "half_hour:2026-05-08:14:00"})["stockRowCount"] == 2
    assert db["datasets"].find_one({"id": "dragonboard_live"})["stockRowCount"] == 4
    assert db["migration_audit"].rows[-1]["opType"] in {"mongodb_snapshot_backfill", "mongodb_snapshot_repair"}


def test_snapshot_backfill_cli_parses_as_dry_run_by_default() -> None:
    build_parser = _load_build_parser()

    args = build_parser().parse_args(["backfill-empty-mongodb-snapshots"])

    assert args.func.__name__ == "cmd_backfill_empty_mongodb_snapshots"
    assert args.dataset_id == "dragonboard_live"
    assert args.snapshot_id is None
    assert args.apply is False


def test_snapshot_backfill_dry_run_supports_explicit_cross_type_donor() -> None:
    backfill_empty_snapshot_rows = _load_backfill()
    db = FakeMongoDatabase(
        {
            "datasets": FakeCollection([{"id": "dragonboard_live"}]),
            "snapshot_records": FakeCollection(
                [
                    {"datasetId": "dragonboard_live", "snapshotId": "half_hour:2026-05-07:13:00"},
                    {"datasetId": "dragonboard_live", "snapshotId": "quarter_hour:2026-05-07:13:15"},
                ]
            ),
            "snapshot_frames": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-05-07:13:00",
                        "type": "half_hour",
                        "tradingDate": "2026-05-07",
                        "slotTime": "13:00",
                        "timestamp": 100,
                        "stockRowCount": 0,
                        "sectorRowCount": 0,
                    },
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "quarter_hour:2026-05-07:13:15",
                        "type": "quarter_hour",
                        "tradingDate": "2026-05-07",
                        "slotTime": "13:15",
                        "timestamp": 101,
                        "stockRowCount": 1,
                        "sectorRowCount": 0,
                    },
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "quarter_hour:2026-05-07:13:15",
                        "rowId": "quarter_hour:2026-05-07:13:15:000001",
                        "type": "quarter_hour",
                        "tradingDate": "2026-05-07",
                        "slotTime": "13:15",
                        "timestamp": 101,
                        "code": "000001",
                        "rank": 1,
                    }
                ]
            ),
            "snapshot_sector_rows": FakeCollection([]),
            "migration_audit": FakeCollection([]),
        }
    )

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-05-07:13:00"],
        apply=False,
    )

    assert result["ok"] is True
    assert result["plans"][0]["donorSnapshotId"] == "quarter_hour:2026-05-07:13:15"
    assert result["plans"][0]["type"] == "half_hour"


def test_snapshot_backfill_apply_can_materialize_missing_half_hour_slot_from_daily() -> None:
    backfill_empty_snapshot_rows = _load_backfill()
    db = FakeMongoDatabase(
        {
            "datasets": FakeCollection([{"id": "dragonboard_live"}]),
            "snapshot_records": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "daily:2026-06-11:15:00",
                        "type": "daily",
                        "tradingDate": "2026-06-11",
                        "slotTime": "15:00",
                        "timestamp": 900,
                    }
                ]
            ),
            "snapshot_frames": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "daily:2026-06-11:15:00",
                        "type": "daily",
                        "tradingDate": "2026-06-11",
                        "slotTime": "15:00",
                        "timestamp": 900,
                        "stockRowCount": 1,
                        "sectorRowCount": 1,
                    }
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "daily:2026-06-11:15:00",
                        "rowId": "daily:2026-06-11:15:00:000001",
                        "type": "daily",
                        "tradingDate": "2026-06-11",
                        "slotTime": "15:00",
                        "timestamp": 900,
                        "code": "000001",
                        "rank": 1,
                    }
                ]
            ),
            "snapshot_sector_rows": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "daily:2026-06-11:15:00",
                        "rowId": "daily:2026-06-11:15:00:sector:bank",
                        "type": "daily",
                        "tradingDate": "2026-06-11",
                        "slotTime": "15:00",
                        "timestamp": 900,
                        "entityType": "sector",
                        "entityKey": "bank",
                        "rank": 1,
                    }
                ]
            ),
            "migration_audit": FakeCollection([]),
        }
    )

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-06-11:15:00"],
        apply=True,
    )

    assert result["ok"] is True
    assert db["snapshot_frames"].find_one({"snapshotId": "half_hour:2026-06-11:15:00"}) is not None
    assert db["snapshot_records"].find_one({"snapshotId": "half_hour:2026-06-11:15:00"}) is not None
    assert db["snapshot_stock_rows"].count_documents({"snapshotId": "half_hour:2026-06-11:15:00"}) == 1
    assert db["snapshot_sector_rows"].count_documents({"snapshotId": "half_hour:2026-06-11:15:00"}) == 1


def test_snapshot_backfill_apply_can_materialize_missing_close_slot_from_same_type_previous_slot() -> None:
    backfill_empty_snapshot_rows = _load_backfill()
    db = FakeMongoDatabase(
        {
            "datasets": FakeCollection([{"id": "dragonboard_live"}]),
            "snapshot_records": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-06-10:14:30",
                        "type": "half_hour",
                        "tradingDate": "2026-06-10",
                        "slotTime": "14:30",
                        "timestamp": 1,
                    }
                ]
            ),
            "snapshot_frames": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-06-10:14:30",
                        "type": "half_hour",
                        "tradingDate": "2026-06-10",
                        "slotTime": "14:30",
                        "timestamp": 1,
                        "stockRowCount": 1,
                        "sectorRowCount": 0,
                        "qualityFlags": [],
                        "metadata": {},
                    }
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-06-10:14:30",
                        "rowId": "half_hour:2026-06-10:14:30:000001",
                        "type": "half_hour",
                        "tradingDate": "2026-06-10",
                        "slotTime": "14:30",
                        "timestamp": 1,
                        "code": "000001",
                        "rank": 1,
                    }
                ]
            ),
            "snapshot_sector_rows": FakeCollection([]),
            "migration_audit": FakeCollection([]),
        }
    )

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-06-10:15:00"],
        apply=True,
    )

    assert result["ok"] is True
    frame = db["snapshot_frames"].find_one({"snapshotId": "half_hour:2026-06-10:15:00"})
    assert frame is not None
    assert frame["captureMode"] == "synthesized"
    assert frame["source"] == "same_type_backfill"
    assert "backfilled_from_nearest_snapshot" in frame["qualityFlags"]
    assert db["snapshot_records"].find_one({"snapshotId": "half_hour:2026-06-10:15:00"}) is not None
    assert db["snapshot_stock_rows"].count_documents({"snapshotId": "half_hour:2026-06-10:15:00"}) == 1


def test_snapshot_backfill_apply_can_materialize_missing_daily_close_slot_from_latest_intraday_slot() -> None:
    backfill_empty_snapshot_rows = _load_backfill()
    db = FakeMongoDatabase(
        {
            "datasets": FakeCollection([{"id": "dragonboard_live"}]),
            "snapshot_records": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "quarter_hour:2026-06-10:14:45",
                        "type": "quarter_hour",
                        "tradingDate": "2026-06-10",
                        "slotTime": "14:45",
                        "timestamp": 1,
                    }
                ]
            ),
            "snapshot_frames": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "quarter_hour:2026-06-10:14:45",
                        "type": "quarter_hour",
                        "tradingDate": "2026-06-10",
                        "slotTime": "14:45",
                        "timestamp": 1,
                        "stockRowCount": 1,
                        "sectorRowCount": 0,
                        "qualityFlags": [],
                        "metadata": {},
                    }
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "quarter_hour:2026-06-10:14:45",
                        "rowId": "quarter_hour:2026-06-10:14:45:000001",
                        "type": "quarter_hour",
                        "tradingDate": "2026-06-10",
                        "slotTime": "14:45",
                        "timestamp": 1,
                        "code": "000001",
                        "rank": 1,
                    }
                ]
            ),
            "snapshot_sector_rows": FakeCollection([]),
            "migration_audit": FakeCollection([]),
        }
    )

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        snapshot_ids=["daily:2026-06-10:15:00"],
        apply=True,
    )

    assert result["ok"] is True
    frame = db["snapshot_frames"].find_one({"snapshotId": "daily:2026-06-10:15:00"})
    assert frame is not None
    assert frame["captureMode"] == "synthesized"
    assert frame["source"] == "cross_type_backfill"
    assert "backfilled_from_cross_type_snapshot" in frame["qualityFlags"]
    assert db["snapshot_records"].find_one({"snapshotId": "daily:2026-06-10:15:00"}) is not None
    assert db["snapshot_stock_rows"].count_documents({"snapshotId": "daily:2026-06-10:15:00"}) == 1


def test_snapshot_backfill_apply_repairs_count_mismatch_and_missing_record() -> None:
    backfill_empty_snapshot_rows = _load_backfill()
    db = FakeMongoDatabase(
        {
            "datasets": FakeCollection([{"id": "dragonboard_live"}]),
            "snapshot_records": FakeCollection([]),
            "snapshot_frames": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-04-16:10:00",
                        "type": "half_hour",
                        "tradingDate": "2026-04-16",
                        "slotTime": "10:00",
                        "timestamp": 500,
                        "stockRowCount": 237,
                        "sectorRowCount": 75,
                        "qualityFlags": [],
                        "metadata": {},
                    }
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-04-16:10:00",
                        "rowId": "half_hour:2026-04-16:10:00:000001",
                        "type": "half_hour",
                        "tradingDate": "2026-04-16",
                        "slotTime": "10:00",
                        "timestamp": 500,
                        "code": "000001",
                        "rank": 1,
                    },
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-04-16:10:00",
                        "rowId": "half_hour:2026-04-16:10:00:000002",
                        "type": "half_hour",
                        "tradingDate": "2026-04-16",
                        "slotTime": "10:00",
                        "timestamp": 500,
                        "code": "000002",
                        "rank": 2,
                    },
                ]
            ),
            "snapshot_sector_rows": FakeCollection([]),
            "migration_audit": FakeCollection([]),
        }
    )

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-04-16:10:00"],
        apply=True,
    )

    assert result["ok"] is True
    assert db["snapshot_frames"].find_one({"snapshotId": "half_hour:2026-04-16:10:00"})["stockRowCount"] == 2
    assert db["snapshot_frames"].find_one({"snapshotId": "half_hour:2026-04-16:10:00"})["sectorRowCount"] == 0
    assert db["snapshot_records"].find_one({"snapshotId": "half_hour:2026-04-16:10:00"}) is not None


def test_snapshot_backfill_default_scope_includes_missing_records_and_count_only_frames() -> None:
    backfill_empty_snapshot_rows = _load_backfill()
    db = FakeMongoDatabase(
        {
            "datasets": FakeCollection([{"id": "dragonboard_live"}]),
            "snapshot_records": FakeCollection([]),
            "snapshot_frames": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-04-16:10:00",
                        "type": "half_hour",
                        "tradingDate": "2026-04-16",
                        "slotTime": "10:00",
                        "timestamp": 500,
                        "stockRowCount": 237,
                        "sectorRowCount": 0,
                    }
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-04-16:10:00",
                        "rowId": "half_hour:2026-04-16:10:00:000001",
                        "type": "half_hour",
                        "tradingDate": "2026-04-16",
                        "slotTime": "10:00",
                        "timestamp": 500,
                        "code": "000001",
                        "rank": 1,
                    }
                ]
            ),
            "snapshot_sector_rows": FakeCollection([]),
            "migration_audit": FakeCollection([]),
        }
    )

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        apply=False,
    )

    assert result["ok"] is True
    assert result["missingRecordRepairs"] == [
        {
            "snapshotId": "half_hour:2026-04-16:10:00",
            "type": "half_hour",
            "tradingDate": "2026-04-16",
            "slotTime": "10:00",
        }
    ]
    assert result["countFixes"] == [
        {
            "snapshotId": "half_hour:2026-04-16:10:00",
            "type": "half_hour",
            "tradingDate": "2026-04-16",
            "slotTime": "10:00",
            "declaredStockRowCount": 237,
            "actualStockRowCount": 1,
            "declaredSectorRowCount": 0,
            "actualSectorRowCount": 0,
        }
    ]


def test_snapshot_backfill_apply_creates_missing_runtime_indexes() -> None:
    backfill_empty_snapshot_rows = _load_backfill()
    db = _seed_database()

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-05-08:14:00"],
        apply=True,
    )

    assert result["ok"] is True
    backtest_trade_keys = [item["keys"] for item in db["backtest_trades"].indexes]
    backtest_equity_keys = [item["keys"] for item in db["backtest_equity_curve"].indexes]
    assert [("backtestRunId", 1), ("sequence", 1)] in backtest_trade_keys
    assert [("backtestRunId", 1), ("sequence", 1)] in backtest_equity_keys


def _seed_database() -> FakeMongoDatabase:
    return FakeMongoDatabase(
        {
            "datasets": FakeCollection([{"id": "dragonboard_live", "stockRowCount": 2}]),
            "snapshot_records": FakeCollection(
                [
                    {"datasetId": "dragonboard_live", "snapshotId": "half_hour:2026-05-08:13:30"},
                    {"datasetId": "dragonboard_live", "snapshotId": "half_hour:2026-05-08:14:00"},
                ]
            ),
            "snapshot_frames": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-05-08:13:30",
                        "type": "half_hour",
                        "tradingDate": "2026-05-08",
                        "slotTime": "13:30",
                        "timestamp": 100,
                        "stockRowCount": 2,
                        "sectorRowCount": 0,
                    },
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-05-08:14:00",
                        "type": "half_hour",
                        "tradingDate": "2026-05-08",
                        "slotTime": "14:00",
                        "timestamp": 200,
                        "stockRowCount": 0,
                        "sectorRowCount": 0,
                        "metadata": {},
                        "qualityFlags": [],
                    },
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-05-08:14:30",
                        "type": "half_hour",
                        "tradingDate": "2026-05-08",
                        "slotTime": "14:30",
                        "timestamp": 300,
                        "stockRowCount": 2,
                        "sectorRowCount": 0,
                    },
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-05-08:13:30",
                        "rowId": "half_hour:2026-05-08:13:30:000001",
                        "type": "half_hour",
                        "tradingDate": "2026-05-08",
                        "slotTime": "13:30",
                        "timestamp": 100,
                        "code": "000001",
                        "rank": 1,
                    },
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-05-08:13:30",
                        "rowId": "half_hour:2026-05-08:13:30:000002",
                        "type": "half_hour",
                        "tradingDate": "2026-05-08",
                        "slotTime": "13:30",
                        "timestamp": 100,
                        "code": "000002",
                        "rank": 2,
                    },
                ]
            ),
            "snapshot_sector_rows": FakeCollection([]),
            "migration_audit": FakeCollection([]),
        }
    )


def _matches(row: dict[str, object], query: dict[str, object]) -> bool:
    for key, expected in query.items():
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and actual not in expected["$in"]:
                return False
            if "$ne" in expected and actual == expected["$ne"]:
                return False
            continue
        if actual != expected:
            return False
    return True


def _load_backfill():
    try:
        from backend.data.mongodb_snapshot_repair import backfill_empty_snapshot_rows
    except ModuleNotFoundError as exc:  # pragma: no cover - current RED state is the point of the test
        pytest.fail(f"mongodb snapshot repair module missing: {exc}")
    return backfill_empty_snapshot_rows


def _load_build_parser():
    try:
        from backend.cli import build_parser
    except ModuleNotFoundError as exc:  # pragma: no cover - current RED state is the point of the test
        pytest.fail(f"cli import failed because snapshot repair module is missing: {exc}")
    return build_parser
