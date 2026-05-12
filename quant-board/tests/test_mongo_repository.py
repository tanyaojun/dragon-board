from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.data.models import Dataset
from backend.data.mongo_repository import MongoRepository


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def sort(self, keys) -> "FakeCursor":
        sort_keys = list(keys if isinstance(keys, list) else [keys])
        for key, direction in reversed(sort_keys):
            self.rows.sort(key=lambda row: row.get(key) or 0, reverse=int(direction) < 0)
        return self

    def limit(self, count: int) -> "FakeCursor":
        if count and count > 0:
            self.rows = self.rows[:count]
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeCollection:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def count_documents(self, query: dict[str, Any]) -> int:
        return len(list(self.find(query)))

    def delete_many(self, query: dict[str, Any]) -> None:
        self.rows = [row for row in self.rows if not _matches(row, query)]

    def insert_many(self, rows: list[dict[str, Any]], ordered: bool = False) -> None:
        assert ordered is False
        self.rows.extend(dict(row) for row in rows)

    def replace_one(self, query: dict[str, Any], document: dict[str, Any], upsert: bool = False) -> None:
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                self.rows[index] = dict(document)
                return
        if upsert:
            self.rows.append(dict(document))

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next(iter(self.find(query)), None)

    def find(self, query: dict[str, Any] | None = None) -> FakeCursor:
        return FakeCursor([dict(row) for row in self.rows if _matches(row, query or {})])


class FakeMongoDatabase(dict):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_mongo_repository_ingests_and_reads_rank_series() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset()

    result = repo.save_snapshot_ingest(
        dataset,
        records=[_record("s1"), _record("s2")],
        frames=[_frame("s1", 1), _frame("s2", 2)],
        stock_rows=[
            _stock("s1", "000001", 1),
            _stock("s1", "000002", 2),
            _stock("s2", "000001", 3),
        ],
        sector_rows=[],
        idempotency_key="ingest-1",
        trading_date="2026-05-12",
    )

    assert result["status"] == "done"
    assert result["deduped"] is False

    rank_series = repo.load_rank_series("dragonboard_live", snapshot_type="half_hour")

    assert [frame["snapshotId"] for frame in rank_series] == ["s1", "s2"]
    assert rank_series[0]["ranks"] == {"000001": 1, "000002": 2}
    assert rank_series[1]["ranks"] == {"000001": 3}


def test_mongo_repository_frame_bundles_return_mongodb_source_rows() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset()
    repo.save_snapshot_ingest(
        dataset,
        records=[_record("s1")],
        frames=[_frame("s1", 1)],
        stock_rows=[_stock("s1", "000001", 1)],
        sector_rows=[],
        idempotency_key="ingest-1",
        trading_date="2026-05-12",
    )

    bundles = repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour")
    rows = repo.list_snapshot_stock_rows("dragonboard_live", snapshot_id="s1")

    assert bundles[0]["source"] == "dragon_board_runtime"
    assert bundles[0]["rows"][0]["code"] == "000001"
    assert rows["source"] == "mongodb"
    assert rows["rows"][0]["rowId"] == "s1:000001"


def test_mongo_repository_records_sectors_and_frame_list_contracts() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset()
    repo.save_snapshot_ingest(
        dataset,
        records=[_record("s1"), _record("s2")],
        frames=[_frame("s1", 1), _frame("s2", 2)],
        stock_rows=[_stock("s1", "000001", 1), _stock("s2", "000002", 2)],
        sector_rows=[_sector("s1", "bank", 1), _sector("s2", "ai", 2)],
        idempotency_key="ingest-1",
        trading_date="2026-05-12",
    )

    frames = repo.load_frames("dragonboard_live", snapshot_type="half_hour")
    records = repo.list_snapshot_records("dragonboard_live", sort="asc")
    record = repo.get_snapshot_record("s1", dataset_id="dragonboard_live")
    sectors = repo.list_snapshot_sector_rows("dragonboard_live", snapshot_id="s1")
    bundle_slice = repo.load_dataset_bundle_slice("dragonboard_live", snapshot_types=["half_hour"])

    assert frames[0]["stocks"][0]["code"] == "000001"
    assert [item["id"] for item in records] == ["s1", "s2"]
    assert record and record["snapshotId"] == "s1"
    assert sectors["source"] == "mongodb"
    assert sectors["rows"][0]["entityKey"] == "bank"
    assert len(bundle_slice[0]) == 2
    assert len(bundle_slice[1]) == 2
    assert len(bundle_slice[2]) == 2
    assert len(bundle_slice[3]) == 2


def test_mongo_repository_saves_imported_dataset_bundle_without_outbox() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset()

    saved = repo.save_dataset_bundle(
        dataset,
        records=[_record("s1")],
        frames=[_frame("s1", 1)],
        stock_rows=[_stock("s1", "000001", 1)],
        sector_rows=[_sector("s1", "bank", 1)],
    )

    assert saved.id == "dragonboard_live"
    assert repo.get_dataset("dragonboard_live").snapshot_count == 1
    assert repo.snapshot_table_counts("dragonboard_live") == {
        "snapshots": 1,
        "snapshot_frames": 1,
        "snapshot_stock_rows": 1,
        "snapshot_sector_rows": 1,
    }
    assert repo.load_dataset_bundle_slice("dragonboard_live")[1][0]["snapshotId"] == "s1"
    assert repo.db["migration_audit"].count_documents({}) == 0


def test_repository_factory_uses_mongo_backend_without_sqlite_session(monkeypatch) -> None:
    import backend.data.repository_factory as factory

    fake_db = FakeMongoDatabase()
    monkeypatch.setattr(factory, "get_settings", lambda: type("Settings", (), {"storage_backend": "mongodb"})())
    monkeypatch.setattr(factory, "get_runtime_mongodb_database", lambda: fake_db)

    repo = factory.create_repository(None)

    assert isinstance(repo, MongoRepository)
    assert repo.db is fake_db


def _dataset() -> Dataset:
    return Dataset(
        id="dragonboard_live",
        name="DragonBoard Live",
        source_type="snapshot_ingest",
        source_path="",
        db_name="DragonBoardData",
        schema_fingerprint="",
        snapshot_count=0,
        frame_count=0,
        stock_row_count=0,
        sector_row_count=0,
        start_date=None,
        end_date=None,
        snapshot_types_json="[]",
        metadata_json="{}",
        created_at=datetime.utcnow(),
    )


def _record(snapshot_id: str) -> dict[str, Any]:
    return {
        "id": snapshot_id,
        "snapshotId": snapshot_id,
        "type": "half_hour",
        "tradingDate": "2026-05-12",
        "slotTime": "15:00",
        "timestamp": 1778569200000,
        "captureMode": "real_time",
        "source": "dragon_board_runtime",
    }


def _frame(snapshot_id: str, offset: int) -> dict[str, Any]:
    return {
        "id": snapshot_id,
        "snapshotId": snapshot_id,
        "type": "half_hour",
        "tradingDate": "2026-05-12",
        "slotTime": f"15:0{offset}",
        "timestamp": 1778569200000 + offset,
        "displayKey": snapshot_id,
        "captureMode": "real_time",
        "source": "dragon_board_runtime",
        "stockRowCount": 1,
        "sectorRowCount": 0,
    }


def _stock(snapshot_id: str, code: str, rank: int) -> dict[str, Any]:
    return {
        "id": f"{snapshot_id}:{code}",
        "rowId": f"{snapshot_id}:{code}",
        "snapshotId": snapshot_id,
        "type": "half_hour",
        "tradingDate": "2026-05-12",
        "slotTime": "15:00",
        "timestamp": 1778569200000,
        "captureMode": "real_time",
        "source": "dragon_board_runtime",
        "code": code,
        "name": code,
        "rank": rank,
    }


def _sector(snapshot_id: str, key: str, rank: int) -> dict[str, Any]:
    return {
        "id": f"{snapshot_id}:sector:{key}",
        "rowId": f"{snapshot_id}:sector:{key}",
        "snapshotId": snapshot_id,
        "type": "half_hour",
        "tradingDate": "2026-05-12",
        "slotTime": "15:00",
        "timestamp": 1778569200000,
        "captureMode": "real_time",
        "source": "dragon_board_runtime",
        "entityType": "sector",
        "entityKey": key,
        "entityName": key,
        "rank": rank,
    }


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
