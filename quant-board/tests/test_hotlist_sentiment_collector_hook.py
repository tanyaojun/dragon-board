from __future__ import annotations

from typing import Any

from backend.services.theme.hotlist_sentiment_compute import compute_and_upsert_for_slot


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


def _seed_slot(fake_db) -> None:
    fake_db["snapshot_frames"].rows.append({
        "datasetId": "d1", "type": "half_hour", "tradingDate": "2026-06-05",
        "snapshotId": "snap-1030", "slotTime": "10:30", "timestamp": 5,
        "limitSummary": {"continuousBoards": {"yiban": 3, "erban": 1}, "zhaban": {}, "yesterdayZt": {}, "thsPools": {}},
    })
    fake_db["snapshot_stock_rows"].rows.append({
        "datasetId": "d1", "snapshotId": "snap-1030", "code": "000001", "name": "甲",
        "compRank": 1, "change": 5.0, "turnover": 8e8, "zlje": 1e8, "zljzb": 12,
        "cddje": 5000e4, "cddjzb": 5, "volumeRatio": 1.4, "turnoverRate": 8, "rank": 1,
    })


def test_compute_and_upsert_for_slot_persists_slot_doc():
    fake_db = FakeMongoDb()
    _seed_slot(fake_db)
    result = compute_and_upsert_for_slot(
        fake_db, dataset_id="d1", snapshot_type="half_hour",
        trading_date="2026-06-05", slot_time="10:30")
    assert result["written"] is True
    docs = fake_db["hotlist_sentiment"].rows
    assert len(docs) == 1
    assert docs[0]["_id"] == "d1:half_hour:2026-06-05:10:30"
    assert docs[0]["slotTime"] == "10:30"
    assert "stage" in docs[0] and "metrics" in docs[0]


def test_compute_and_upsert_for_slot_missing_frame_reports_reason():
    fake_db = FakeMongoDb()
    result = compute_and_upsert_for_slot(
        fake_db, dataset_id="d1", snapshot_type="half_hour",
        trading_date="2026-06-05", slot_time="10:30")
    assert result["written"] is False and result["reason"]


def test_compute_and_upsert_for_slot_idempotent():
    fake_db = FakeMongoDb()
    _seed_slot(fake_db)
    compute_and_upsert_for_slot(fake_db, dataset_id="d1", snapshot_type="half_hour",
                                trading_date="2026-06-05", slot_time="10:30")
    compute_and_upsert_for_slot(fake_db, dataset_id="d1", snapshot_type="half_hour",
                                trading_date="2026-06-05", slot_time="10:30")
    assert len(fake_db["hotlist_sentiment"].rows) == 1  # replace_one 幂等
