from __future__ import annotations

from typing import Any

from backend.operations.migrate_hotlist_sentiment_slot_eod import (
    drop_legacy_unique_index,
    migrate_eod_slot_time,
)


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = list(rows)

    def sort(self, spec: list[tuple[str, int]]) -> "FakeCursor":
        for key, direction in reversed(spec):
            self.rows.sort(key=lambda row: row.get(key) or 0, reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeReplaceResult:
    matched_count = 0
    modified_count = 0
    upserted_id = "dragonboard_live:half_hour:2026-06-05"


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    def find(self, query: dict[str, Any] | None = None, projection: dict[str, Any] | None = None) -> FakeCursor:
        query = query or {}
        rows = [row for row in self.rows if self._matches(row, query)]
        if projection:
            projected = []
            for row in rows:
                projected.append({key: row.get(key) for key, enabled in projection.items() if enabled})
            rows = projected
        return FakeCursor(rows)

    def find_one(
        self,
        query: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        rows = list(self.find(query or {}))
        if sort:
            rows = list(FakeCursor(rows).sort(sort))
        return rows[0] if rows else None

    def replace_one(
        self,
        query: dict[str, Any],
        doc: dict[str, Any],
        upsert: bool = False,
    ) -> FakeReplaceResult:
        self.replace_calls.append((query, doc, upsert))
        self.rows = [row for row in self.rows if not self._matches(row, query)]
        self.rows.append(doc)
        return FakeReplaceResult()

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        # 相对复制源（test_hotlist_sentiment_backfill.py）的扩展：迁移脚本 $set 语义（计划 B Task 2）
        set_body = update.get("$set") or {}
        for row in self.rows:
            if all(row.get(k) == v for k, v in query.items()):
                row.update(set_body)
                return

    def drop_index(self, name_or_keys: Any) -> None:
        # 相对复制源的扩展：模拟索引不存在（计划 B Task 2 容错路径）
        raise KeyError(f"index not found: {name_or_keys}")

    @staticmethod
    def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, expected in query.items():
            actual = row.get(key)
            if isinstance(expected, dict) and "$in" in expected:
                if actual not in expected["$in"]:
                    return False
            elif actual != expected:
                return False
        return True


class FakeMongoDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {
            "snapshot_frames": FakeCollection(),
            "snapshot_stock_rows": FakeCollection(),
            "hotlist_sentiment": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


def test_migrate_legacy_eod_slot_time():
    fake_db = FakeMongoDb()
    coll = fake_db["hotlist_sentiment"]
    coll.rows.append({"_id": "d1:half_hour:2026-06-04", "datasetId": "d1",
                      "snapshotType": "half_hour", "tradingDate": "2026-06-04",
                      "slotTime": "15:00", "stage": "退潮"})
    coll.rows.append({"_id": "d1:half_hour:2026-06-05:10:30", "datasetId": "d1",
                      "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                      "slotTime": "10:30", "stage": "启动"})
    result = migrate_eod_slot_time(fake_db)
    assert result["updated"] == 1
    assert coll.rows[0]["slotTime"] == "EOD"
    assert coll.rows[1]["slotTime"] == "10:30"  # 槽位文档不动


def test_migrate_idempotent():
    fake_db = FakeMongoDb()
    fake_db["hotlist_sentiment"].rows.append({
        "_id": "d1:half_hour:2026-06-04", "datasetId": "d1", "snapshotType": "half_hour",
        "tradingDate": "2026-06-04", "slotTime": "EOD", "stage": "退潮"})
    result = migrate_eod_slot_time(fake_db)
    assert result["updated"] == 0


def test_drop_legacy_index_tolerates_missing():
    fake_db = FakeMongoDb()
    result = drop_legacy_unique_index(fake_db)
    assert result["dropped"] is None and result["reason"]  # 容错不抛
