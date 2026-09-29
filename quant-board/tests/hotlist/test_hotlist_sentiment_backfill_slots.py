from __future__ import annotations

from typing import Any

from backend.operations.hotlist_sentiment import HotListSentimentBackfillService


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


def _seed_two_slots(fake_db) -> None:
    frames = fake_db["snapshot_frames"]
    rows = fake_db["snapshot_stock_rows"]
    for slot in ("10:00", "11:00"):
        frames.rows.append({"datasetId": "d1", "type": "half_hour", "tradingDate": "2026-06-05",
                            "snapshotId": f"snap-{slot}", "slotTime": slot, "timestamp": 1})
        rows.rows.append({"datasetId": "d1", "snapshotId": f"snap-{slot}", "code": "000001",
                          "name": "甲", "compRank": 1, "change": 5.0, "turnover": 8e8,
                          "zlje": 1e8, "zljzb": 12, "cddje": 5000e4, "cddjzb": 5,
                          "volumeRatio": 1.4, "turnoverRate": 8, "rank": 1})


def test_run_for_date_slots_writes_one_doc_per_slot_plus_eod():
    fake_db = FakeMongoDb()
    _seed_two_slots(fake_db)
    result = HotListSentimentBackfillService(fake_db).run_for_date_slots(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05")
    assert result["ok"] is True and result["written"] == 2
    docs = fake_db["hotlist_sentiment"].rows
    assert sorted(doc["slotTime"] for doc in docs) == ["10:00", "11:00", "EOD"]  # 收尾补写当日 EOD
    assert all(doc["_id"].endswith(doc["slotTime"]) for doc in docs if doc["slotTime"] != "EOD")
    assert all(doc["stage"] in ("冰点", "启动", "发酵", "高潮", "退潮") for doc in docs)


def test_run_for_date_slots_dry_run_writes_nothing():
    fake_db = FakeMongoDb()
    _seed_two_slots(fake_db)
    result = HotListSentimentBackfillService(fake_db).run_for_date_slots(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05", dry_run=True)
    assert result["written"] == 0 and not fake_db["hotlist_sentiment"].rows


def test_run_for_date_slots_continues_on_empty_slot():
    fake_db = FakeMongoDb()
    _seed_two_slots(fake_db)
    fake_db["snapshot_stock_rows"].rows = [
        row for row in fake_db["snapshot_stock_rows"].rows if row["snapshotId"] != "snap-10:00"
    ]
    result = HotListSentimentBackfillService(fake_db).run_for_date_slots(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05")
    assert result["written"] == 1
    assert len(result["slotErrors"]) == 1 and result["slotErrors"][0]["slotTime"] == "10:00"
