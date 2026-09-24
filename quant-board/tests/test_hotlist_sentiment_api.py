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
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
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
    # 计划 B Task 1 契约：upsert 按 _id 精确命中（业务四键 query 在存量行 slotTime
    # 为旧值时会命中 _id 不同的行导致 DuplicateKeyError，故弃用）
    assert query == {"_id": "dragonboard_live:half_hour:2026-06-05"}
    assert doc["_id"] == "dragonboard_live:half_hour:2026-06-05"
    assert doc["slotTime"] == "EOD"  # ingest 无 slotTime → EOD 哨兵兜底
    assert doc["stage"] == "高潮"
    assert upsert is True


def test_hotlist_sentiment_ingest_rejects_missing_trading_date() -> None:
    client = TestClient(app)

    response = client.post("/api/hotlist-sentiment/ingest", json={"stage": "高潮"})

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 2026-09-24 阶段多帧确认字段合同：ingest 必须透传 rawStage/stageConfirmState/diagnostics
# （禁止 Pydantic 静默丢弃）；旧结构 payload 不伪造确认字段（exclude_none）。
# ---------------------------------------------------------------------------


def test_hotlist_sentiment_ingest_preserves_confirmation_fields(monkeypatch) -> None:
    fake_db = FakeMongoDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: fake_db,
    )
    client = TestClient(app)

    response = client.post(
        "/api/hotlist-sentiment/ingest",
        json={
            "tradingDate": "2026-06-05",
            "stage": "退潮",
            "riskLevel": "高",
            "confidence": 70,
            "summary": "确认阶段投影",
            "metrics": {},
            "turnover": {},
            "signals": [],
            "warnings": [],
            "rawStage": "高潮",
            "stageConfirmState": {
                "pending": True,
                "pendingStage": "高潮",
                "pendingSince": "11:00",
                "confirmSlots": 2,
                "historyStatus": "complete",
            },
            "diagnostics": ["stage_confirm_legacy_fallback:1"],
        },
    )

    assert response.status_code == 200
    _, doc, _ = fake_db.hotlist_sentiment.replace_calls[0]
    assert doc["rawStage"] == "高潮"
    assert doc["stageConfirmState"] == {
        "pending": True,
        "pendingStage": "高潮",
        "pendingSince": "11:00",
        "confirmSlots": 2,
        "historyStatus": "complete",
    }
    assert doc["diagnostics"] == ["stage_confirm_legacy_fallback:1"]


def test_hotlist_sentiment_ingest_legacy_payload_does_not_invent_confirmation(monkeypatch) -> None:
    fake_db = FakeMongoDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: fake_db,
    )
    client = TestClient(app)

    response = client.post(
        "/api/hotlist-sentiment/ingest",
        json={
            "tradingDate": "2026-06-05",
            "stage": "高潮",
            "metrics": {},
            "turnover": {},
            "signals": [],
            "warnings": [],
        },
    )

    assert response.status_code == 200
    _, doc, _ = fake_db.hotlist_sentiment.replace_calls[0]
    # 旧结构 payload：未提供确认字段时不得伪造（None 被 exclude_none 排除）
    assert "rawStage" not in doc
    assert "stageConfirmState" not in doc
