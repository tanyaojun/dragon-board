from fastapi.testclient import TestClient

from backend.main import app


class FakeReplaceResult:
    matched_count = 0
    modified_count = 0
    upserted_id = "dragonboard_live:half_hour:2026-06-05"


class FakeMongoCollection:
    def __init__(self) -> None:
        self.replace_calls: list[tuple[dict, dict, bool]] = []

    def replace_one(self, query: dict, doc: dict, upsert: bool = False) -> FakeReplaceResult:
        self.replace_calls.append((query, doc, upsert))
        return FakeReplaceResult()


class FakeMongoDb:
    def __init__(self) -> None:
        self.hotlist_sentiment = FakeMongoCollection()

    def __getitem__(self, name: str) -> FakeMongoCollection:
        assert name == "hotlist_sentiment"
        return self.hotlist_sentiment


def test_hotlist_sentiment_ingest_writes_mongodb_document(monkeypatch) -> None:
    fake_db = FakeMongoDb()
    monkeypatch.setattr(
        "backend.data.repository_factory.get_runtime_mongodb_database",
        lambda: fake_db,
    )
    client = TestClient(app)

    response = client.post(
        "/api/hotlist-sentiment/ingest",
        json={
            "tradingDate": "2026-06-05",
            "stage": "高潮",
            "riskLevel": "低",
            "confidence": 78,
            "summary": "测试",
            "metrics": {"poolSize": 218},
            "turnover": {"newEntries": ["000001"], "eliminated": []},
            "signals": ["资金偏强"],
            "warnings": [],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["datasetId"] == "dragonboard_live"
    assert body["snapshotType"] == "half_hour"
    assert body["tradingDate"] == "2026-06-05"

    query, doc, upsert = fake_db.hotlist_sentiment.replace_calls[0]
    assert query == {
        "datasetId": "dragonboard_live",
        "snapshotType": "half_hour",
        "tradingDate": "2026-06-05",
    }
    assert doc["_id"] == "dragonboard_live:half_hour:2026-06-05"
    assert doc["stage"] == "高潮"
    assert upsert is True


def test_hotlist_sentiment_ingest_rejects_missing_trading_date() -> None:
    client = TestClient(app)

    response = client.post("/api/hotlist-sentiment/ingest", json={"stage": "高潮"})

    assert response.status_code == 422
