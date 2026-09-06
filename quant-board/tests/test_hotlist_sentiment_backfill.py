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
    # 计划 B Task 5：EOD 模式写库同步改按 _id 精确命中（与 Task 1 upsert 契约同理，
    # 存量行 slotTime 为旧值时业务四键 query 会命中 _id 不同的行导致 DuplicateKeyError）
    assert query == {"_id": "dragonboard_live:half_hour:2026-06-05"}
    assert doc["_id"] == "dragonboard_live:half_hour:2026-06-05"
    assert doc["slotTime"] == "EOD"  # build_hotlist_sentiment_document 无 slot_time → EOD 哨兵
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


def test_build_document_uses_pure_function_schema() -> None:
    from backend.operations.hotlist_sentiment import build_hotlist_sentiment_document

    frame = {"snapshotId": "s1", "slotTime": "14:30", "timestamp": 1757000000}
    stocks = [
        {"code": "000001", "name": "甲", "compRank": 1, "change": 9.9, "turnover": 15e8,
         "zlje": 2e8, "zljzb": 15, "cddje": 8000e4, "cddjzb": 6, "volumeRatio": 2.0, "turnoverRate": 12},
        {"code": "000002", "name": "乙", "compRank": 2, "change": -3.5, "turnover": 3e8,
         "zlje": -1e8, "zljzb": -9, "cddje": -4000e4, "cddjzb": -4},
    ]
    doc = build_hotlist_sentiment_document(
        dataset_id="dragonboard_live", snapshot_type="half_hour",
        trading_date="2026-06-05", frame=frame, stocks=stocks,
    )
    assert doc["_id"] == "dragonboard_live:half_hour:2026-06-05"
    for key in ("datasetId", "snapshotType", "tradingDate", "snapshotId", "slotTime", "timestamp",
                "computedAt", "stage", "riskLevel", "confidence", "summary", "metrics", "turnover", "signals", "warnings"):
        assert key in doc, key
    metrics = doc["metrics"]
    for key in ("poolSize", "allPoolUpRatio", "hotTrin", "retentionRate1d", "retentionRate2d",
                "limitIntersectionRate", "newEntryCount", "eliminatedCount", "nearLimitUpCount",
                "highGainCount", "riskShare", "activeOpportunityShare", "strongMoneyShare", "crowdedShare"):
        assert key in metrics, key
    assert metrics["poolSize"] == 2
    assert doc["stage"] in ("冰点", "启动", "发酵", "高潮", "退潮")
    assert doc["riskLevel"] in ("低", "中", "高")
    assert "layers" in metrics and "limitEvidence" in metrics   # 超集键透出


def test_build_document_passes_previous_trading_dates_to_comparison() -> None:
    # Task 4 审查裁决落实：取数路径能拿到昨日/前日 tradingDate 时透传给纯函数，
    # 回填 comparison.yesterday/dayBefore.tradingDate（安全超集，缺失时保持 None）。
    from backend.operations.hotlist_sentiment import build_hotlist_sentiment_document

    frame = {"snapshotId": "s1", "slotTime": "14:30", "timestamp": 1757000000}
    stocks = [{"code": "000001", "name": "甲", "compRank": 1, "change": 5, "turnover": 10e8}]
    doc = build_hotlist_sentiment_document(
        dataset_id="dragonboard_live", snapshot_type="half_hour",
        trading_date="2026-06-05", frame=frame, stocks=stocks,
        yesterday_stocks=[{"code": "000001", "name": "甲", "compRank": 1, "change": 3, "turnover": 8e8}],
        day_before_stocks=[{"code": "000001", "name": "甲", "compRank": 1, "change": 1, "turnover": 6e8}],
        yesterday_trading_date="2026-06-04",
        day_before_trading_date="2026-06-03",
    )
    assert doc["metrics"]["comparison"]["yesterday"]["tradingDate"] == "2026-06-04"
    assert doc["metrics"]["comparison"]["dayBefore"]["tradingDate"] == "2026-06-03"


def day_stock(snapshot_id: str, trading_date: str, code: str, rank: int, change: float) -> dict[str, Any]:
    return {
        "datasetId": "dragonboard_live",
        "snapshotId": snapshot_id,
        "type": "half_hour",
        "tradingDate": trading_date,
        "timestamp": 100,
        "code": code,
        "name": f"股票{code}",
        "rank": rank,
        "change": change,
    }


def test_previous_day_stocks_returns_yesterday_and_day_before_rows() -> None:
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        {"datasetId": "dragonboard_live", "snapshotId": "s0", "type": "half_hour", "tradingDate": "2026-06-03", "timestamp": 90},
        {"datasetId": "dragonboard_live", "snapshotId": "s1", "type": "half_hour", "tradingDate": "2026-06-04", "timestamp": 100},
        {"datasetId": "dragonboard_live", "snapshotId": "s2", "type": "half_hour", "tradingDate": "2026-06-05", "timestamp": 200},
    ]
    db["snapshot_stock_rows"].rows = [
        day_stock("s0", "2026-06-03", "000001", 1, 5),
        day_stock("s0", "2026-06-03", "000009", 2, 2),
        day_stock("s1", "2026-06-04", "000002", 1, 4),
        day_stock("s1", "2026-06-04", "000009", 2, 1),
        day_stock("s2", "2026-06-05", "000002", 1, 6),
        day_stock("s2", "2026-06-05", "000003", 2, 3),
    ]

    previous = HotListSentimentBackfillService(db).previous_day_stocks(
        "dragonboard_live", "half_hour", "2026-06-05"
    )

    assert [row["code"] for row in previous["yesterday"]] == ["000002", "000009"]
    assert [row["code"] for row in previous["day_before"]] == ["000001", "000009"]


def test_previous_day_stocks_returns_empty_lists_without_history() -> None:
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        {"datasetId": "dragonboard_live", "snapshotId": "s0", "type": "half_hour", "tradingDate": "2026-06-03", "timestamp": 90},
        {"datasetId": "dragonboard_live", "snapshotId": "s2", "type": "half_hour", "tradingDate": "2026-06-05", "timestamp": 200},
    ]
    db["snapshot_stock_rows"].rows = [
        day_stock("s0", "2026-06-03", "000001", 1, 5),
        day_stock("s2", "2026-06-05", "000002", 1, 6),
    ]

    previous = HotListSentimentBackfillService(db).previous_day_stocks(
        "dragonboard_live", "half_hour", "2026-06-05"
    )

    # 只有 06-03 一个先前交易日：yesterday 命中，day_before 无历史返回空（不伪造）
    assert [row["code"] for row in previous["yesterday"]] == ["000001"]
    assert previous["day_before"] == []

    earliest = HotListSentimentBackfillService(db).previous_day_stocks(
        "dragonboard_live", "half_hour", "2026-06-03"
    )
    assert earliest["yesterday"] == []
    assert earliest["day_before"] == []


def test_run_for_date_persists_day_before_metrics() -> None:
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        {"datasetId": "dragonboard_live", "snapshotId": "s0", "type": "half_hour", "tradingDate": "2026-06-03", "timestamp": 90},
        {"datasetId": "dragonboard_live", "snapshotId": "s1", "type": "half_hour", "tradingDate": "2026-06-04", "timestamp": 100},
        {"datasetId": "dragonboard_live", "snapshotId": "s2", "type": "half_hour", "tradingDate": "2026-06-05", "timestamp": 200},
    ]
    db["snapshot_stock_rows"].rows = [
        day_stock("s0", "2026-06-03", "000001", 1, 5),
        day_stock("s0", "2026-06-03", "000003", 2, 2),
        day_stock("s1", "2026-06-04", "000002", 1, 4),
        day_stock("s1", "2026-06-04", "000009", 2, 1),
        day_stock("s2", "2026-06-05", "000002", 1, 6),
        day_stock("s2", "2026-06-05", "000003", 2, 3),
    ]

    result = HotListSentimentBackfillService(db).run_for_date(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-06-05",
    )

    assert result["ok"] is True
    query, doc, upsert = db["hotlist_sentiment"].replace_calls[0]
    # top 留榜：今日 {000002,000003} ∩ 昨日 {000002,000009} = 1/2；∩ 前日 {000001,000003} = 1/2
    assert doc["metrics"]["retentionRate1d"] == 0.5
    assert doc["metrics"]["retentionRate2d"] == 0.5
    assert doc["metrics"]["comparison"]["dayBefore"] is not None
