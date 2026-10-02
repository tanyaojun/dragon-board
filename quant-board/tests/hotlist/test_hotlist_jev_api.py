# -*- coding: utf-8 -*-
"""jev 观察轨道读写 API 测试（evaluate + series）。

evaluate 不受 gate 限制（显式意图）；series 只读不缓存（v1）。
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

import backend.services.jev.jev_sentiment_compute as jev_module
import backend.services.jev.jev_sentiment_compute as jev_v2_module
from backend.main import app

DATASET = "dragonboard_live"
DATE = "2026-10-08"


class FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        query = query or {}

        def matches(row):
            for key, expected in query.items():
                if row.get(key) != expected:
                    return False
            return True

        return iter([row for row in self.rows if matches(row)])

    def find_one(self, query=None, sort=None):
        best = None
        first = None
        for row in self.find(query):
            if first is None:
                first = row
            if best is None or str(row.get("timestamp") or "") > str(best.get("timestamp") or ""):
                best = row
        # 无 timestamp 字段的集合（如 v2 EOD）回退取首条匹配
        return best if best is not None else first

    def replace_one(self, query, doc, upsert=False):
        self.rows = [row for row in self.rows if row.get("_id") != query.get("_id")]
        self.rows.append(doc)


class FakeMongoDb:
    def __init__(self):
        self.collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


def frame(date: str, slot: str) -> dict[str, Any]:
    return {
        "datasetId": DATASET, "snapshotId": f"half_hour:{date}:{slot}", "type": "half_hour",
        "tradingDate": date, "slotTime": slot, "timestamp": f"{date}T{slot}:00+08:00",
        "indices": {"sh": {"change": -5.0}},
        "limitSummary": {"continuousBoards": {"yiban": 30, "erban": 10, "sanban": 2, "sibanPlus": 1, "maxBoard": 4},
                          "zhaban": {"count": 8, "rate": 12.0, "fengbanRate": 88.0, "ztCount": 43}},
    }


def rows(date: str, slot: str) -> list[dict[str, Any]]:
    return [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{date}:{slot}", "code": "000001",
         "name": "甲", "rank": 1, "heat": 90, "pctChange": 9.9, "change": 9.9,
         "price": 9.66, "limitUpPrice": 9.66, "zlje": 3.0e6},
    ]


def analysis(date: str, slot: str) -> list[dict[str, Any]]:
    return [{"datasetId": DATASET, "snapshotId": f"half_hour:{date}:{slot}", "code": "000001",
             "analysis": {"displayStatus": {"stage": "ignition"}}}]


def seed(db: FakeMongoDb) -> None:
    db["snapshot_frames"].rows = [frame(DATE, "09:30"), frame(DATE, "10:00")]
    db["snapshot_stock_rows"].rows = [*rows(DATE, "09:30"), *rows(DATE, "10:00")]
    db["snapshot_analysis"].rows = [*analysis(DATE, "09:30"), *analysis(DATE, "10:00")]


def _mock_jev_ok(monkeypatch):
    envelope = {"result": {"state": "Completed", "result": {
        "model": "jev-1.13.0",
        "answers": {
            "frame_stage": {"type": "choice", "choice": "start", "probabilities": {"start": 0.7}},
            "sequence_stage": {"type": "choice", "choice": "start", "probabilities": {"start": 0.6}},
        },
        "usage": {"input_tokens": 900, "output_tokens": 90}}}, "success": True}

    def fake_call(account_id, api_token, state, questions, model="typesafe/jev", timeout=60):
        return envelope, 800

    monkeypatch.setattr(jev_module, "call_jev", fake_call)
    monkeypatch.setattr(jev_v2_module, "call_jev", fake_call)


@pytest.fixture()
def client(monkeypatch):
    db = FakeMongoDb()
    seed(db)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    # 2026-10-02 单一事实源裁决：gate 环境变量已删，evaluate 无门控
    monkeypatch.setenv("JEV_CF_TOKEN", "test-token")
    _mock_jev_ok(monkeypatch)
    test_client = TestClient(app)
    yield test_client, db


def test_evaluate_slot_bypasses_gate(monkeypatch):
    db = FakeMongoDb()
    seed(db)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    monkeypatch.setenv("JEV_CF_TOKEN", "test-token")
    _mock_jev_ok(monkeypatch)
    client = TestClient(app)

    response = client.post("/api/hotlist-jev/evaluate", json={
        "tradingDate": DATE, "scope": "slot", "slotTime": "10:00"})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["status"] == "ok"
    docs = db["hotlist_jev_sentiment"].rows
    assert len(docs) == 1 and docs[0]["origin"] == "manual"
    assert docs[0]["_id"] == f"{DATASET}:half_hour:{DATE}:10:00"


def test_evaluate_day(monkeypatch):
    db = FakeMongoDb()
    seed(db)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    monkeypatch.setenv("JEV_CF_TOKEN", "test-token")

    envelope = {"result": {"state": "Completed", "result": {
        "model": "jev-1.13.0",
        "answers": {"day_stage": {"type": "choice", "choice": "start", "probabilities": {"start": 0.6}},
                     "day_pattern": {"type": "choice", "choice": "wide_swing", "probabilities": {"wide_swing": 0.4}}},
        "usage": {"input_tokens": 1500, "output_tokens": 120}}}, "success": True}

    def fake_call(*args, **kwargs):
        return envelope, 900

    monkeypatch.setattr(jev_module, "call_jev", fake_call)
    monkeypatch.setattr(jev_v2_module, "call_jev", fake_call)
    client = TestClient(app)

    response = client.post("/api/hotlist-jev/evaluate", json={"tradingDate": DATE, "scope": "day"})

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    docs = db["hotlist_jev_sentiment"].rows
    assert len(docs) == 1 and docs[0]["kind"] == "eod"
    assert docs[0]["answers"]["day_pattern"]["choice"] == "wide_swing"


def test_evaluate_slot_no_time_and_no_frames_returns_404(monkeypatch):
    db = FakeMongoDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    monkeypatch.setenv("JEV_CF_TOKEN", "test-token")
    _mock_jev_ok(monkeypatch)
    client = TestClient(app)

    response = client.post("/api/hotlist-jev/evaluate", json={"tradingDate": DATE, "scope": "slot"})

    assert response.status_code == 404
    assert response.json()["errorCode"] == "no_slot"


def test_series_empty_is_ok_not_error(monkeypatch):
    db = FakeMongoDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    client = TestClient(app)

    response = client.get("/api/hotlist-jev/series")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["date"] is None and body["slots"] == [] and body["eod"] is None


def test_series_returns_slots_ascending_and_eod(monkeypatch, client):
    test_client, db = client
    # 先用 evaluate 造槽位文档（09:30 与 10:00 各一条）+ 手工造 eod
    assert test_client.post("/api/hotlist-jev/evaluate",
                            json={"tradingDate": DATE, "scope": "slot", "slotTime": "10:00"}).status_code == 200
    assert test_client.post("/api/hotlist-jev/evaluate",
                            json={"tradingDate": DATE, "scope": "slot", "slotTime": "09:30"}).status_code == 200
    db["hotlist_jev_sentiment"].rows.append({
        "_id": f"{DATASET}:half_hour:{DATE}:eod", "kind": "eod", "slotTime": "EOD",
        "tradingDate": DATE, "datasetId": DATASET, "status": "ok",
        "answers": {"day_stage": {"type": "choice", "choice": "start"}}, "scores": {},
        "errorCode": None, "errorDetail": None, "quality": {"degradedSources": []}})

    response = test_client.get("/api/hotlist-jev/series", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["date"] == DATE
    assert [slot["slotTime"] for slot in body["slots"]] == ["09:30", "10:00"]
    assert body["eod"]["answers"]["day_stage"]["choice"] == "start"
    assert body["degradedCount"] == 0


def test_series_latest_date_when_date_missing(monkeypatch, client):
    test_client, db = client
    assert test_client.post("/api/hotlist-jev/evaluate",
                            json={"tradingDate": DATE, "scope": "slot", "slotTime": "10:00"}).status_code == 200

    response = test_client.get("/api/hotlist-jev/series")

    assert response.status_code == 200
    body = response.json()
    assert body["date"] == DATE and len(body["slots"]) == 1


# ── GET /api/hotlist-jev/range（多日窗口读口，2026-09-30 前端 jev 图表消费） ──

def test_range_returns_docs_and_structured_missing_days(monkeypatch, client):
    test_client, db = client
    # 快照帧日历两天：DATE 有 jev 文档，NEXT 无 → missing 结构化返回不吞掉
    next_date = "2026-10-09"
    db["snapshot_frames"].rows.append(frame(next_date, "09:30"))
    assert test_client.post("/api/hotlist-jev/evaluate",
                            json={"tradingDate": DATE, "scope": "slot", "slotTime": "09:30"}).status_code == 200

    response = test_client.get("/api/hotlist-jev/range", params={"days": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    days = body["days"]
    assert [day["tradingDate"] for day in days] == [DATE, next_date]
    assert days[0]["slots"][0]["slotTime"] == "09:30" and days[0]["eod"] is None
    assert days[1]["missing"] is True and days[1]["reason"] == "no_jev_docs"
    assert body["degradedCount"] == 0


def test_range_no_trading_dates_degraded(monkeypatch):
    db = FakeMongoDb()  # 不 seed：无快照帧 → 无交易日历
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    client = TestClient(app)

    response = client.get("/api/hotlist-jev/range")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False and body["degraded"] is True
    assert body["reason"] == "no_snapshot_trading_date" and body["days"] == []


def test_range_days_capped_to_min_one(monkeypatch, client):
    test_client, db = client
    assert test_client.post("/api/hotlist-jev/evaluate",
                            json={"tradingDate": DATE, "scope": "slot", "slotTime": "09:30"}).status_code == 200

    response = test_client.get("/api/hotlist-jev/range", params={"days": 0})

    assert response.status_code == 200
    body = response.json()
    assert len(body["days"]) == 1 and body["days"][0]["tradingDate"] == DATE
    assert body["degradedCount"] == 0


def test_sentiment_overview_dual_table(monkeypatch):
    """v2 双表读口：v2 EOD + 规则 EOD 同包返回；缺任一表如实 degraded 注记。"""
    db = FakeMongoDb()
    db["hotlist_jev_sentiment"].rows = [{
        "_id": f"{DATASET}:half_hour:{DATE}:EOD", "kind": "eod", "origin": "collector",
        "datasetId": DATASET, "snapshotType": "half_hour", "tradingDate": DATE, "slotTime": "EOD",
        "status": "ok", "historyAnchorRange": "2026-09-01 → 2026-09-29，20 个交易日收盘统计",
        "answers": {"day_stage": {"type": "choice", "choice": "ferment",
                                  "probabilities": {"ferment": 0.7}},
                    "day_crowding": {"type": "choice", "choice": "no_crowding",
                                     "probabilities": {"no_crowding": 0.6}}},
        "scores": {"day_temperature": 64.0},
        "computedAt": 1790000000,
    }]
    db["hotlist_sentiment"].rows = [{
        "_id": f"{DATASET}:half_hour:{DATE}:EOD", "datasetId": DATASET,
        "snapshotType": "half_hour", "slotTime": "EOD", "tradingDate": DATE,
        "emotionScore": {"score": 59.1, "stageCandidate": "启动", "slope": -9.8, "version": "score-v1"},
    }]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    client = TestClient(app)

    response = client.get("/api/hotlist-jev/sentiment-overview")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["date"] == DATE
    assert body["jev"]["dayTemperature"] == 64.0
    assert body["jev"]["dayStage"] == "ferment" and body["jev"]["dayCrowding"] == "no_crowding"
    assert body["rule"]["score"] == 59.1 and body["rule"]["stageCandidate"] == "启动"
    assert body["degraded"] is False


def test_sentiment_overview_missing_jev_doc_degraded(monkeypatch):
    db = FakeMongoDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    client = TestClient(app)
    response = client.get("/api/hotlist-jev/sentiment-overview?date=2026-10-09")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["jev"] is None and body["degraded"] is True
    assert "未落库" in body["reason"]


def _seed_no_data_v2(db, date):
    db["hotlist_jev_sentiment"].rows = [{
        "_id": f"{DATASET}:half_hour:{date}:EOD", "kind": "eod", "origin": "collector",
        "datasetId": DATASET, "snapshotType": "half_hour", "tradingDate": date, "slotTime": "EOD",
        "status": "no_data", "errorDetail": "no half_hour frames",
    }]


def test_sentiment_overview_no_data_latest_reason_distinct(monkeypatch):
    """已落库但 no_data ≠ 未落库：reason 带 no_data + errorDetail，不误述排查方向。"""
    db = FakeMongoDb()
    _seed_no_data_v2(db, DATE)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    client = TestClient(app)
    response = client.get("/api/hotlist-jev/sentiment-overview")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["jev"] is None and body["degraded"] is True
    assert body["date"] == DATE
    assert "no_data" in body["reason"] and "no half_hour frames" in body["reason"]
    assert "未落库" not in body["reason"]


def test_sentiment_overview_no_data_with_date_reason_distinct(monkeypatch):
    db = FakeMongoDb()
    _seed_no_data_v2(db, DATE)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    client = TestClient(app)
    response = client.get(f"/api/hotlist-jev/sentiment-overview?date={DATE}")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["jev"] is None and body["degraded"] is True
    assert "no_data" in body["reason"] and "no half_hour frames" in body["reason"]
