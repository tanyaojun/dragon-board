from __future__ import annotations

from typing import Any

from backend.operations.hotlist_sentiment import build_hotlist_sentiment_document
from backend.services.theme.hotlist_sentiment_service import HotListSentimentService


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
        # 相对复制源（test_hotlist_sentiment_backfill.py）的扩展：支持 $ne——
        # list_slot_documents 的 EOD 双条件排除依赖该操作符（计划 B 台账 R1）
        for key, expected in query.items():
            actual = row.get(key)
            if isinstance(expected, dict) and "$in" in expected:
                if actual not in expected["$in"]:
                    return False
            elif isinstance(expected, dict) and "$ne" in expected:
                if actual == expected["$ne"]:
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


def _frame(slot: str) -> dict:
    return {"snapshotId": f"snap-{slot}", "slotTime": slot, "timestamp": 1757000000}


def _stocks() -> list[dict]:
    return [{"code": "000001", "name": "甲", "compRank": 1, "change": 5.0, "turnover": 8e8,
             "zlje": 1e8, "zljzb": 12, "cddje": 5000e4, "cddjzb": 5, "volumeRatio": 1.4,
             "turnoverRate": 8, "rank": 1}]


def test_build_document_eod_sentinel_without_slot_time():
    doc = build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05",
        frame=_frame("15:00"), stocks=_stocks(),
    )
    assert doc["_id"] == "d1:half_hour:2026-06-05"
    assert doc["slotTime"] == "EOD"


def test_build_document_slot_suffix_with_slot_time():
    doc = build_hotlist_sentiment_document(
        dataset_id="d1", snapshot_type="half_hour", trading_date="2026-06-05",
        frame=_frame("10:30"), stocks=_stocks(), slot_time="10:30",
    )
    assert doc["_id"] == "d1:half_hour:2026-06-05:10:30"
    assert doc["slotTime"] == "10:30"


def test_upsert_query_includes_slot_time():
    fake_db = FakeMongoDb()
    service = HotListSentimentService(fake_db)
    service.upsert({"_id": "d1:half_hour:2026-06-05:10:30", "datasetId": "d1",
                    "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                    "slotTime": "10:30", "stage": "启动"})
    service.upsert({"_id": "d1:half_hour:2026-06-05:11:00", "datasetId": "d1",
                    "snapshotType": "half_hour", "tradingDate": "2026-06-05",
                    "slotTime": "11:00", "stage": "发酵"})
    rows = fake_db["hotlist_sentiment"].rows
    assert len(rows) == 2  # 同日两槽不互吞
    assert rows[0]["_id"] == "d1:half_hour:2026-06-05:10:30"


def test_get_by_date_hits_eod_only():
    fake_db = FakeMongoDb()
    service = HotListSentimentService(fake_db)
    service.upsert({"datasetId": "d1", "snapshotType": "half_hour",
                    "tradingDate": "2026-06-05", "slotTime": "EOD", "stage": "退潮"})
    doc = service.get_by_date("d1", "half_hour", "2026-06-05")
    assert doc is not None and doc["slotTime"] == "EOD"
    assert service.get_by_date("d1", "half_hour", "2026-06-99") is None


def test_list_slot_documents_sorted_and_excludes_eod():
    fake_db = FakeMongoDb()
    service = HotListSentimentService(fake_db)
    for slot in ("11:00", "10:00", "EOD"):
        service.upsert({"datasetId": "d1", "snapshotType": "half_hour",
                        "tradingDate": "2026-06-05", "slotTime": slot, "stage": "启动"})
    slots = service.list_slot_documents("d1", "half_hour", "2026-06-05")
    assert [doc["slotTime"] for doc in slots] == ["10:00", "11:00"]
    assert service.get_eod_document("d1", "half_hour", "2026-06-05")["slotTime"] == "EOD"
    assert service.get_eod_document("d1", "half_hour", "2026-06-04") is None
