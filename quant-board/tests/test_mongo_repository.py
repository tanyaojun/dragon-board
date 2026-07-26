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
        self.find_queries: list[dict[str, Any]] = []
        self.aggregate_pipelines: list[list[dict[str, Any]]] = []

    def count_documents(self, query: dict[str, Any]) -> int:
        return len(list(self.find(query)))

    def delete_many(self, query: dict[str, Any]) -> Any:
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return type("DeleteResult", (), {"deleted_count": before - len(self.rows)})()

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
        normalized_query = dict(query or {})
        self.find_queries.append(normalized_query)
        return FakeCursor([dict(row) for row in self.rows if _matches(row, normalized_query)])

    def aggregate(self, pipeline: list[dict[str, Any]], **_kwargs: Any) -> FakeCursor:
        self.aggregate_pipelines.append(pipeline)
        rows = [dict(row) for row in self.rows if _matches(row, pipeline[0]["$match"])]
        if "$sort" in pipeline[1]:
            for key, direction in reversed(list(pipeline[1]["$sort"].items())):
                rows.sort(key=lambda row: row.get(key) or 0, reverse=int(direction) < 0)
            target_codes = set(pipeline[4]["$match"]["rows.code"]["$in"])
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                grouped.setdefault(str(row.get("snapshotId") or ""), []).append(row)
            projected = []
            for snapshot_id, group_rows in grouped.items():
                for index, row in enumerate(group_rows):
                    if row.get("code") in target_codes:
                        projected.append({
                            "_id": snapshot_id,
                            "rows": {"code": row.get("code")},
                            "totalCount": len(group_rows),
                            "attentionIndex": index,
                        })
            return FakeCursor(projected)

        window = pipeline[1]["$setWindowFields"]
        partition_key = window["partitionBy"].removeprefix("$")
        sort_by = list(window["sortBy"].items())
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row.get(partition_key) or ""), []).append(row)
        ranked_rows: list[dict[str, Any]] = []
        for group_rows in grouped.values():
            for key, direction in reversed(sort_by):
                group_rows.sort(key=lambda row: row.get(key) or 0, reverse=int(direction) < 0)
            for index, row in enumerate(group_rows, start=1):
                row["_rankSeriesWindow"] = index
                row["_rankSeriesTotalCount"] = len(group_rows)
                ranked_rows.append(row)
        return FakeCursor([row for row in ranked_rows if _matches(row, pipeline[2]["$match"])])


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
            {**_stock("s1", "000001", 1), "timestamp": 1778569200001},
            {**_stock("s1", "000002", 2), "timestamp": 1778569200001},
            {**_stock("s2", "000001", 3), "timestamp": 1778569200002},
        ],
        sector_rows=[],
        idempotency_key="ingest-1",
        trading_date="2026-05-12",
    )

    assert result["status"] == "done"
    assert result["deduped"] is False

    rank_series = repo.load_rank_series("dragonboard_live", snapshot_type="half_hour")
    frames = rank_series["frames"]
    series = rank_series["series"]

    assert [frame["snapshotId"] for frame in frames] == ["s1", "s2"]
    assert frames[0]["ranks"] == {"000001": 1, "000002": 2}
    assert frames[1]["ranks"] == {"000001": 3}
    assert [bar["rank"] for bar in series["000001"]["bars"]] == [1, 3]
    assert series["000001"]["totalCount"] == 2

    desc_rank_series = repo.load_rank_series(
        "dragonboard_live",
        snapshot_type="half_hour",
        codes=["000001"],
        sort="desc",
        limit=1,
    )
    assert [bar["rank"] for bar in desc_rank_series["series"]["000001"]["bars"]] == [3]
    assert desc_rank_series["series"]["000001"]["totalCount"] == 2


def test_mongo_repository_rank_series_rebuilds_attention_rank_from_avg_rank_num() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset()
    repo.save_snapshot_ingest(
        dataset,
        records=[_record("s1"), _record("s2")],
        frames=[_frame("s1", 1), _frame("s2", 2)],
        stock_rows=[
            {**_stock("s1", "000001", 1), "avgRankNum": 20},
            {**_stock("s1", "000002", 2), "avgRankNum": 5},
            {**_stock("s1", "000003", 3), "avgRankNum": 0},
            {**_stock("s2", "000001", 3), "avgRankNum": 2},
            {**_stock("s2", "000002", 1), "avgRankNum": 10},
            {**_stock("s2", "000003", 2)},
        ],
        sector_rows=[],
        idempotency_key="ingest-attention-rank-series",
        trading_date="2026-05-12",
    )

    result = repo.load_rank_series(
        "dragonboard_live",
        snapshot_type="half_hour",
        codes=["000001", "000003"],
        rank_basis="attention",
    )

    assert [bar["rank"] for bar in result["series"]["000001"]["bars"]] == [2, 1]
    assert [bar["totalCount"] for bar in result["series"]["000001"]["bars"]] == [2, 2]
    assert result["frames"][0]["ranks"] == {"000001": 2}
    assert result["frames"][0]["totalCount"] == 2
    assert "000003" not in result["series"]


def test_attention_rank_series_filters_invalid_avg_rank_before_per_code_window() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset()
    frames = [_frame(f"s{index}", index) for index in range(5)]
    repo.save_snapshot_ingest(
        dataset,
        records=[_record(str(frame["snapshotId"])) for frame in frames],
        frames=frames,
        stock_rows=[
            {
                **_stock(str(frame["snapshotId"]), "000001", index + 1),
                "timestamp": frame["timestamp"],
                "avgRankNum": 5 if index == 0 else 0,
            }
            for index, frame in enumerate(frames)
        ],
        sector_rows=[],
        idempotency_key="ingest-attention-valid-window",
        trading_date="2026-05-12",
    )

    result = repo.load_rank_series(
        "dragonboard_live",
        snapshot_type="half_hour",
        codes=["000001"],
        rank_basis="attention",
        window_bars=1,
    )

    assert [bar["snapshotId"] for bar in result["series"]["000001"]["bars"]] == ["s0"]


def test_mongo_repository_rank_series_uses_per_code_window_for_large_code_batches() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset()
    codes = [f"60{index:04d}" for index in range(60)]
    special_code = codes[-1]
    frames = [_frame(f"s{index}", index) for index in range(8)]
    stock_rows = []
    for frame_index, frame in enumerate(frames):
        for code_index, code in enumerate(codes):
            if code == special_code and frame_index >= 5:
                continue
            stock_rows.append(
                {
                    **_stock(str(frame["snapshotId"]), code, code_index + 1 + frame_index),
                    "timestamp": frame["timestamp"],
                    "slotTime": frame["slotTime"],
                }
            )

    repo.save_snapshot_ingest(
        dataset,
        records=[_record(str(frame["snapshotId"])) for frame in frames],
        frames=frames,
        stock_rows=stock_rows,
        sector_rows=[],
        idempotency_key="ingest-large-rank-series",
        trading_date="2026-05-12",
    )
    repo.db["snapshot_stock_rows"].find_queries.clear()
    repo.db["snapshot_stock_rows"].aggregate_pipelines.clear()

    rank_series = repo.load_rank_series(
        "dragonboard_live",
        snapshot_type="half_hour",
        codes=codes,
        sort="desc",
        limit=2,
        window_bars=2,
    )

    pipelines = repo.db["snapshot_stock_rows"].aggregate_pipelines
    assert len(pipelines) == 1
    assert pipelines[0][0]["$match"] == {
        "datasetId": "dragonboard_live",
        "type": {"$in": ["half_hour"]},
        "code": {"$in": codes},
    }
    assert pipelines[0][1]["$setWindowFields"]["partitionBy"] == "$code"
    assert pipelines[0][2] == {"$match": {"_rankSeriesWindow": {"$lte": 2}}}
    assert set(rank_series["series"]) == set(codes)
    assert all(len(item["bars"]) == 2 for item in rank_series["series"].values())
    assert [bar["snapshotId"] for bar in rank_series["series"][special_code]["bars"]] == ["s3", "s4"]


def test_rank_series_count_window_preserves_compound_snapshot_sort() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset()
    repo.save_snapshot_ingest(
        dataset,
        records=[_record("s1")],
        frames=[_frame("s1", 1)],
        stock_rows=[_stock("s1", "000001", 1)],
        sector_rows=[],
        idempotency_key="rank-series-count-window-sort",
        trading_date="2026-05-12",
    )

    repo.load_rank_series("dragonboard_live", snapshot_type="half_hour", codes=["000001"])

    window = repo.db["snapshot_stock_rows"].aggregate_pipelines[0][1]["$setWindowFields"]
    assert window["sortBy"] == {"timestamp": -1, "snapshotId": -1}
    assert window["output"]["_rankSeriesWindow"] == {
        "$count": {},
        "window": {"documents": ["unbounded", "current"]},
    }


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
    assert bundles[0]["stocks"] == bundles[0]["rows"]
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


def test_mongo_repository_deletes_non_primary_dataset_bundle() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset(id="ds_delete", source_type="json_bundle")
    repo.save_dataset_bundle(
        dataset,
        records=[_record("s1")],
        frames=[_frame("s1", 1)],
        stock_rows=[_stock("s1", "000001", 1)],
        sector_rows=[_sector("s1", "bank", 1)],
    )

    result = repo.delete_dataset("ds_delete")

    assert result == {
        "ok": True,
        "datasetId": "ds_delete",
        "deleted": {
            "snapshot_sector_rows": 1,
            "snapshot_stock_rows": 1,
            "snapshot_frames": 1,
            "snapshot_records": 1,
            "datasets": 1,
        },
        "source": "mongodb",
    }
    assert repo.get_dataset("ds_delete") is None
    assert repo.snapshot_table_counts("ds_delete") == {
        "snapshots": 0,
        "snapshot_frames": 0,
        "snapshot_stock_rows": 0,
        "snapshot_sector_rows": 0,
    }


def test_mongo_repository_rejects_primary_dataset_delete() -> None:
    repo = MongoRepository(FakeMongoDatabase())
    dataset = _dataset(id="dragonboard_live", source_type="dragon_board_runtime")
    repo.save_dataset_bundle(dataset, records=[_record("s1")], frames=[_frame("s1", 1)], stock_rows=[], sector_rows=[])

    try:
        repo.delete_dataset("dragonboard_live")
    except ValueError as error:
        assert str(error) == "snapshot primary dataset cannot be deleted from UI/API: dragonboard_live"
    else:
        raise AssertionError("delete_dataset should reject dragonboard_live")

    assert repo.get_dataset("dragonboard_live") is not None
    assert repo.snapshot_table_counts("dragonboard_live")["snapshot_frames"] == 1


def test_repository_factory_uses_mongo_backend_without_sqlite_session(monkeypatch) -> None:
    import backend.data.repository_factory as factory

    fake_db = FakeMongoDatabase()
    monkeypatch.setattr(factory, "get_settings", lambda: type("Settings", (), {"storage_backend": "mongodb"})())
    monkeypatch.setattr(factory, "get_runtime_mongodb_database", lambda: fake_db)

    repo = factory.create_repository(None)

    assert isinstance(repo, MongoRepository)
    assert repo.db is fake_db


def _dataset(id: str = "dragonboard_live", source_type: str = "snapshot_ingest") -> Dataset:
    return Dataset(
        id=id,
        name="DragonBoard Live",
        source_type=source_type,
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
            if "$type" in expected and expected["$type"] == "number" and not isinstance(value, (int, float)):
                return False
            if "$gt" in expected and value <= expected["$gt"]:
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
