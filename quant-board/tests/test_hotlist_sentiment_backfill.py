from __future__ import annotations

from typing import Any


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


def stock(snapshot_id: str, code: str, rank: int, change: float, zlje: float = 0) -> dict[str, Any]:
    return {
        "datasetId": "dragonboard_live",
        "snapshotId": snapshot_id,
        "type": "half_hour",
        "tradingDate": "2026-06-05" if snapshot_id == "s2" else "2026-06-04",
        "timestamp": 200 if snapshot_id == "s2" else 100,
        "code": code,
        "name": f"股票{code}",
        "rank": rank,
        "change": change,
        "zlje": zlje,
        "volumeRatio": 1.5,
    }


def test_hotlist_sentiment_service_writes_last_frame_document() -> None:
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "s1",
            "type": "half_hour",
            "tradingDate": "2026-06-04",
            "timestamp": 100,
            "slotTime": "15:00",
        },
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "s2",
            "type": "half_hour",
            "tradingDate": "2026-06-05",
            "timestamp": 200,
            "slotTime": "15:00",
        },
    ]
    db["snapshot_stock_rows"].rows = [
        stock("s1", "000001", 1, 5, 100),
        stock("s1", "000002", 2, -4, -50),
        stock("s2", "000001", 1, 9.9, 500),
        stock("s2", "000003", 2, 3, 300),
    ]

    result = HotListSentimentBackfillService(db).run_for_date(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-06-05",
    )

    assert result["ok"] is True
    assert result["written"] == 1
    query, doc, upsert = db["hotlist_sentiment"].replace_calls[0]
    assert query == {
        "datasetId": "dragonboard_live",
        "snapshotType": "half_hour",
        "tradingDate": "2026-06-05",
    }
    assert doc["_id"] == "dragonboard_live:half_hour:2026-06-05"
    assert doc["metrics"]["poolSize"] == 2
    assert doc["metrics"]["allPoolUpRatio"] == 1
    assert doc["metrics"]["newEntryCount"] == 1
    assert doc["turnover"]["newEntries"] == ["000003"]
    assert doc["turnover"]["eliminated"] == ["000002"]
    assert upsert is True


def test_hotlist_sentiment_stage_keeps_main_direction_when_risk_is_high_but_tape_is_not_broken() -> None:
    from backend.operations.hotlist_sentiment import build_hotlist_sentiment_document

    stocks: list[dict[str, Any]] = []
    for index in range(12):
        stocks.append(
            {
                "code": f"000{index:03d}",
                "name": f"强势{index}",
                "rank": index + 1,
                "change": 6,
                "zlje": 1000,
                "zljzb": 10,
                "cddje": 500,
                "cddjzb": 4,
                "turnover": 1000,
            }
        )
    for index in range(8):
        stocks.append(
            {
                "code": f"300{index:03d}",
                "name": f"背离{index}",
                "rank": index + 20,
                "change": 1,
                "zlje": -1000,
                "zljzb": -9,
                "cddje": -500,
                "cddjzb": -4,
                "turnover": 1000,
            }
        )

    doc = build_hotlist_sentiment_document(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-06-05",
        frame={"snapshotId": "s2", "timestamp": 200},
        stocks=stocks,
        yesterday_stocks=stocks,
    )

    assert doc["riskLevel"] == "高"
    assert doc["stage"] != "退潮"
    assert any("风险等级高" in warning for warning in doc["warnings"])


def test_hotlist_sentiment_backfill_dry_run_does_not_write() -> None:
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        {
            "datasetId": "dragonboard_live",
            "snapshotId": "s2",
            "type": "half_hour",
            "tradingDate": "2026-06-05",
            "timestamp": 200,
            "slotTime": "15:00",
        }
    ]
    db["snapshot_stock_rows"].rows = [stock("s2", "000001", 1, 1, 100)]

    result = HotListSentimentBackfillService(db).backfill(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        dry_run=True,
    )

    assert result["ok"] is True
    assert result["dryRun"] is True
    assert result["written"] == 0
    assert result["planned"] == 1
    assert db["hotlist_sentiment"].replace_calls == []
