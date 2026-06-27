from __future__ import annotations

from backend.data.mongodb_snapshot_repair import (
    backfill_empty_snapshot_rows,
    copy_missing_snapshot_slots_from_dataset,
)


class DeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeCollection:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.fail_insert_many = False

    def count_documents(self, query: dict[str, object]) -> int:
        return len(self.find(query))

    def find(self, query: dict[str, object] | None = None) -> list[dict[str, object]]:
        return [row for row in self.rows if _matches(row, query or {})]

    def find_one(self, query: dict[str, object], projection: dict[str, object] | None = None) -> dict[str, object] | None:
        rows = self.find(query)
        return rows[0] if rows else None

    def insert_many(self, rows: list[dict[str, object]], ordered: bool = False) -> None:
        assert ordered is False
        if self.fail_insert_many:
            raise RuntimeError("insert_many failed")
        self.rows.extend(rows)

    def update_one(self, query: dict[str, object], update: dict[str, object]) -> None:
        row = self.find_one(query)
        if row is None:
            return
        row.update(update.get("$set", {}))  # type: ignore[arg-type]

    def delete_many(self, query: dict[str, object]) -> DeleteResult:
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return DeleteResult(before - len(self.rows))


class FakeMongoDatabase(dict[str, FakeCollection]):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_snapshot_backfill_dry_run_selects_nearest_same_type_donor() -> None:
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
    db = _seed_database()

    result = backfill_empty_snapshot_rows(
        db,
        dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-05-08:14:00"],
        apply=True,
    )

    assert result["ok"] is True
    assert result["applied"][0]["insertedStockRows"] == 2
    rows = db["snapshot_stock_rows"].find({"snapshotId": "half_hour:2026-05-08:14:00"})
    assert [row["rowId"] for row in rows] == [
        "half_hour:2026-05-08:14:00:000001",
        "half_hour:2026-05-08:14:00:000002",
    ]
    assert {row["slotTime"] for row in rows} == {"14:00"}
    assert db["snapshot_frames"].find_one({"snapshotId": "half_hour:2026-05-08:14:00"})["stockRowCount"] == 2
    assert db["datasets"].find_one({"id": "dragonboard_live"})["stockRowCount"] == 4
    assert db["migration_audit"].rows[-1]["opType"] == "mongodb_snapshot_backfill"


def test_snapshot_backfill_cli_parses_as_dry_run_by_default() -> None:
    from backend.cli import build_parser

    args = build_parser().parse_args(["backfill-empty-mongodb-snapshots"])

    assert args.func.__name__ == "cmd_backfill_empty_mongodb_snapshots"
    assert args.dataset_id == "dragonboard_live"
    assert args.snapshot_id is None
    assert args.apply is False


def test_copy_missing_slot_cli_parses_as_dry_run_by_default() -> None:
    from backend.cli import build_parser

    args = build_parser().parse_args(
        [
            "copy-missing-mongodb-snapshot-slots",
            "--target-dataset-id",
            "dragonboard_backend_shadow",
            "--donor-dataset-id",
            "dragonboard_live",
            "--snapshot-id",
            "half_hour:2026-06-22:15:00",
        ]
    )

    assert args.func.__name__ == "cmd_copy_missing_mongodb_snapshot_slots"
    assert args.target_dataset_id == "dragonboard_backend_shadow"
    assert args.donor_dataset_id == "dragonboard_live"
    assert args.snapshot_id == ["half_hour:2026-06-22:15:00"]
    assert args.apply is False


def test_copy_missing_slot_dry_run_plans_live_donor_without_writing() -> None:
    db = _seed_cross_dataset_slot_database()

    result = copy_missing_snapshot_slots_from_dataset(
        db,
        target_dataset_id="dragonboard_backend_shadow",
        donor_dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-06-22:15:00"],
        apply=False,
    )

    assert result["ok"] is True
    assert result["plans"][0]["donorDatasetId"] == "dragonboard_live"
    assert result["plans"][0]["targetDatasetId"] == "dragonboard_backend_shadow"
    assert result["plans"][0]["stockRowsToCopy"] == 2
    assert db["snapshot_frames"].count_documents(
        {
            "datasetId": "dragonboard_backend_shadow",
            "snapshotId": "half_hour:2026-06-22:15:00",
        }
    ) == 0


def test_copy_missing_slot_apply_creates_target_facts_and_audit() -> None:
    db = _seed_cross_dataset_slot_database()

    result = copy_missing_snapshot_slots_from_dataset(
        db,
        target_dataset_id="dragonboard_backend_shadow",
        donor_dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-06-22:15:00"],
        apply=True,
    )

    assert result["ok"] is True
    assert result["applied"][0]["insertedStockRows"] == 2
    frame = db["snapshot_frames"].find_one(
        {
            "datasetId": "dragonboard_backend_shadow",
            "snapshotId": "half_hour:2026-06-22:15:00",
        }
    )
    assert frame["stockRowCount"] == 2
    assert frame["metadata"]["repair"]["sourceDatasetId"] == "dragonboard_live"
    assert "copied_from_donor_dataset" in frame["qualityFlags"]
    rows = db["snapshot_stock_rows"].find(
        {
            "datasetId": "dragonboard_backend_shadow",
            "snapshotId": "half_hour:2026-06-22:15:00",
        }
    )
    assert [row["rowId"] for row in rows] == [
        "half_hour:2026-06-22:15:00:000001",
        "half_hour:2026-06-22:15:00:000002",
    ]
    assert db["datasets"].find_one({"id": "dragonboard_backend_shadow"})["frameCount"] == 1
    assert db["datasets"].find_one({"id": "dragonboard_backend_shadow"})["stockRowCount"] == 2
    assert db["migration_audit"].rows[-1]["opType"] == "mongodb_snapshot_slot_copy"


def test_copy_missing_slot_apply_rolls_back_target_docs_when_row_insert_fails() -> None:
    db = _seed_cross_dataset_slot_database()
    db["snapshot_stock_rows"].fail_insert_many = True

    try:
        copy_missing_snapshot_slots_from_dataset(
            db,
            target_dataset_id="dragonboard_backend_shadow",
            donor_dataset_id="dragonboard_live",
            snapshot_ids=["half_hour:2026-06-22:15:00"],
            apply=True,
        )
    except RuntimeError as exc:
        assert str(exc) == "insert_many failed"
    else:
        raise AssertionError("expected row insert failure")

    target_query = {
        "datasetId": "dragonboard_backend_shadow",
        "snapshotId": "half_hour:2026-06-22:15:00",
    }
    assert db["snapshot_records"].count_documents(target_query) == 0
    assert db["snapshot_frames"].count_documents(target_query) == 0

    db["snapshot_stock_rows"].fail_insert_many = False
    result = copy_missing_snapshot_slots_from_dataset(
        db,
        target_dataset_id="dragonboard_backend_shadow",
        donor_dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-06-22:15:00"],
        apply=False,
    )

    assert result["ok"] is True


def test_copy_missing_slot_apply_marks_target_record_with_copied_quality_flag() -> None:
    db = _seed_cross_dataset_slot_database()

    result = copy_missing_snapshot_slots_from_dataset(
        db,
        target_dataset_id="dragonboard_backend_shadow",
        donor_dataset_id="dragonboard_live",
        snapshot_ids=["half_hour:2026-06-22:15:00"],
        apply=True,
    )

    assert result["ok"] is True
    record = db["snapshot_records"].find_one(
        {
            "datasetId": "dragonboard_backend_shadow",
            "snapshotId": "half_hour:2026-06-22:15:00",
        }
    )
    assert "copied_from_donor_dataset" in record["qualityFlags"]


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


def _seed_cross_dataset_slot_database() -> FakeMongoDatabase:
    return FakeMongoDatabase(
        {
            "datasets": FakeCollection(
                [
                    {"id": "dragonboard_live", "frameCount": 1, "stockRowCount": 2},
                    {"id": "dragonboard_backend_shadow", "frameCount": 0, "stockRowCount": 0},
                ]
            ),
            "snapshot_records": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-06-22:15:00",
                        "type": "half_hour",
                        "tradingDate": "2026-06-22",
                        "slotTime": "15:00",
                        "timestamp": 300,
                        "stockRowCount": 2,
                        "sectorRowCount": 0,
                        "metadata": {"source": "live"},
                    },
                ]
            ),
            "snapshot_frames": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-06-22:15:00",
                        "type": "half_hour",
                        "tradingDate": "2026-06-22",
                        "slotTime": "15:00",
                        "timestamp": 300,
                        "displayKey": "half_hour:2026-06-22:15:00",
                        "stockRowCount": 2,
                        "sectorRowCount": 0,
                        "metadata": {"source": "live"},
                        "qualityFlags": [],
                    },
                ]
            ),
            "snapshot_stock_rows": FakeCollection(
                [
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-06-22:15:00",
                        "rowId": "half_hour:2026-06-22:15:00:000001",
                        "type": "half_hour",
                        "tradingDate": "2026-06-22",
                        "slotTime": "15:00",
                        "timestamp": 300,
                        "code": "000001",
                        "rank": 1,
                    },
                    {
                        "datasetId": "dragonboard_live",
                        "snapshotId": "half_hour:2026-06-22:15:00",
                        "rowId": "half_hour:2026-06-22:15:00:000002",
                        "type": "half_hour",
                        "tradingDate": "2026-06-22",
                        "slotTime": "15:00",
                        "timestamp": 300,
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
