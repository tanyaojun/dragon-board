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
            "temperature": {"type": "score", "score": 5, "legend": {"0": "0", "11": "11", "22": "22",
                                                                    "33": "33", "44": "44", "56": "56",
                                                                    "67": "67", "78": "78", "89": "89",
                                                                    "100": "100"}},
            "crowding": {"type": "choice", "choice": "no_crowding", "probabilities": {"no_crowding": 0.6}},
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
                     "day_pattern": {"type": "choice", "choice": "wide_swing", "probabilities": {"wide_swing": 0.4}},
                     "day_temperature": {"type": "score", "score": 5, "legend": {"0": "0", "11": "11", "22": "22",
                                                                                 "33": "33", "44": "44", "56": "56",
                                                                                 "67": "67", "78": "78", "89": "89",
                                                                                 "100": "100"}},
                     "day_crowding": {"type": "choice", "choice": "no_crowding", "probabilities": {"no_crowding": 0.5}}},
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


# ── GET /api/hotlist-jev/quotes-review（热榜行情：15:00 帧全量 + 五维 + 双题集台账，纯读零调用）──

def _seed_quotes_review(db: FakeMongoDb) -> None:
    """两股样本：甲(S/buy→agree，带 LC 一致)、乙(D/buy→diverge，LC diverge，带留痕文档)。"""
    db["snapshot_frames"].rows = [frame(DATE, "15:00")]
    db["snapshot_stock_rows"].rows = [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "000001",
         "name": "甲", "rank": 1, "price": 9.66, "change": 9.9, "amount": 1.2e9,
         "cirMV": 5.0e9, "turnoverRate": 12.5, "volumeRatio": 2.3, "compRank": 2,
         "compScore": 88.1},
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "000002",
         "name": "乙", "rank": 2, "price": 4.44, "change": -2.1, "amount": 8.0e8,
         "cirMV": 3.0e9},
    ]
    db["snapshot_analysis"].rows = [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "000001",
         "analysis": {"resonance": {"signalTier": "S", "direction": "buy", "score": 91.0},
                      "observation": {"rankTrend": {"signalTier": "A"},
                                       "crossSection": {"signalTier": "B"},
                                       "volumePrice": {"signalTier": "C"},
                                       "lifecycle": {"stage": "ignition", "veto": False},
                                       "synergy": {"signalTier": "S"}}}},
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "000002",
         "analysis": {"resonance": {"signalTier": "B", "score": 55.0},
                      "observation": {"lifecycle": {"stage": "ignition"},
                                       "synergy": {"signalTier": "D"}}}},
    ]
    db["hotlist_jev_vote_confirm_pilot"].rows = [
        {"_id": f"{DATE}:15:00:000001:VOTE", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000001", "name": "甲", "status": "ok", "origin": "vote_confirm_pilot",
         "ammoVersion": "vote_ammo_v3", "synergyTier": "S", "voteDirection": "buy", "voteConfidence": 0.72,
         "voteProbabilities": {"buy": 0.72}, "riskFlag": {"level": "ok", "reasons": []},
         "questionSetVersion": "v1", "questionSetHash": "abc123",
         "narrative": "【头行】叙事原料", "questionsRaw": {"vote_direction": {}},
         "responseRaw": {"result": "envelope"}, "model": "jev", "usage": {}, "latencyMs": 800},
        {"_id": f"{DATE}:15:00:000002:VOTE", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000002", "name": "乙", "status": "ok", "origin": "vote_confirm_pilot",
         "synergyTier": "D", "voteDirection": "buy", "voteConfidence": 0.5,
         "riskFlag": {"level": "partial", "reasons": ["evidence_missing:zlje"]},
         "questionSetVersion": "v1", "questionSetHash": "abc123",
         "narrative": "叙事乙", "questionsRaw": {}, "responseRaw": None},
    ]
    db["hotlist_jev_lifecycle_recheck_pilot"].rows = [
        {"_id": f"{DATE}:15:00:000001:LC", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000001", "name": "甲", "status": "ok", "origin": "lifecycle_recheck_pilot",
         "ammoVersion": "vote_ammo_v3", "ruleStage": "ignition", "ruleAction": "allow",
         "prevTradingDate": "2026-09-29", "prevStage": "ignition",
         "lcStage": "ignition", "lcConfidence": 0.66,
         "riskFlag": {"level": "ok", "reasons": []},
         "questionSetVersion": "v1", "questionSetHash": "def456",
         "narrative": "LC 叙事", "questionsRaw": {}, "responseRaw": {"ok": 1}},
    ]


def _quotes_client(monkeypatch, db):
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    return TestClient(app)


def test_quotes_review_join_summary_and_agree(monkeypatch):
    db = FakeMongoDb()
    _seed_quotes_review(db)
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["noData"] is False
    assert body["slotTime"] == "15:00"
    rows = body["rows"]
    assert [r["code"] for r in rows] == ["000001", "000002"]  # rank 升序
    first = rows[0]
    assert first["price"] == 9.66 and first["amount"] == 1.2e9 and first["cirMV"] == 5.0e9
    assert first["tiers"] == {"resonance": "S", "trend": "A", "heat": "B",
                               "volumePrice": "C", "cycle": "ignition", "synergy": "S"}
    assert first["jev"]["vote"]["direction"] == "buy"
    assert first["jev"]["agree"] == "agree"      # S→buy ↔ jev buy
    assert first["jev"]["lcAgree"] == "agree"    # 规则 ignition ↔ jev ignition
    assert "docs" not in first                    # 缺省不嵌大字段
    second = rows[1]
    assert second["jev"]["agree"] == "diverge"   # D→sell ↔ jev buy
    assert second["jev"]["lc"] is None
    assert second["turnoverRate"] is None          # 缺失如实 None 不伪造
    s = body["summary"]
    assert s["total"] == 2 and s["tiered"] == 2
    assert s["vote"]["buy"] == 2 and s["vote"]["unreviewed"] == 0
    assert s["lc"]["stages"] == {"ignition": 1} and s["lc"]["unreviewed"] == 1
    assert s["agree"] == 1 and s["diverge"] == 1
    assert s["risk"] == {"ok": 2, "partial": 1}  # 甲 VOTE+LC 双 ok 留痕 + 乙 partial


def test_quotes_review_with_docs_embeds_raw(monkeypatch):
    db = FakeMongoDb()
    _seed_quotes_review(db)
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review",
                          params={"date": DATE, "with_docs": 1})

    assert response.status_code == 200
    rows = response.json()["rows"]
    assert rows[0]["docs"]["vote"]["narrative"] == "【头行】叙事原料"
    assert rows[0]["docs"]["vote"]["questionsRaw"] == {"vote_direction": {}}
    assert rows[0]["docs"]["vote"]["responseRaw"] == {"result": "envelope"}
    assert rows[0]["docs"]["lc"]["responseRaw"] == {"ok": 1}
    # 预登记 §八「全保留」：原料代际戳与 LC 对照原料不裁剪（review #4）
    assert rows[0]["docs"]["vote"]["ammoVersion"] == "vote_ammo_v3"
    assert rows[0]["docs"]["lc"]["ruleStage"] == "ignition"
    assert rows[0]["docs"]["lc"]["ruleAction"] == "allow"
    assert rows[0]["docs"]["lc"]["prevTradingDate"] == "2026-09-29"
    assert rows[0]["docs"]["lc"]["prevStage"] == "ignition"
    assert rows[1]["docs"]["lc"] is None           # 无 LC 文档股如实 null


def test_quotes_review_no_frame_no_data(monkeypatch):
    db = FakeMongoDb()  # 无任何帧
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["noData"] is True and body["rows"] == []
    assert "15:00" in body["reason"]


def test_quotes_review_missing_analysis_and_quotes_fail_visible(monkeypatch):
    """帧存在但无 analysis / 行情字段缺：行照常返回，档位/价格如实 None，不伪造空成功。"""
    db = FakeMongoDb()
    db["snapshot_frames"].rows = [frame(DATE, "15:00")]
    db["snapshot_stock_rows"].rows = [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00",
         "code": "000003", "name": "丙", "rank": 3}]
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    row = body["rows"][0]
    assert row["tiers"] == {"resonance": None, "trend": None, "heat": None,
                             "volumePrice": None, "cycle": None, "synergy": None}
    assert row["price"] is None and row["jev"] is None
    assert body["summary"]["tiered"] == 0
    assert body["summary"]["vote"]["unreviewed"] == 1


def test_quotes_review_insufficient_doc_exposed(monkeypatch):
    """留痕文档（data_insufficient 不调用）：状态/风险如实进 summary，方向缺失不进台账。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    db["hotlist_jev_vote_confirm_pilot"].rows = [
        {"_id": f"{DATE}:15:00:000002:VOTE", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000002", "name": "乙", "status": "data_insufficient",
         "origin": "vote_confirm_pilot", "synergyTier": "D", "voteDirection": None,
         "riskFlag": {"level": "data_insufficient", "reasons": ["tiers<2"]},
         "questionSetVersion": "v1", "questionSetHash": "abc123"}]
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    s = body["summary"]
    assert s["vote"]["insufficient"] == 1 and s["vote"]["ok"] == 0
    assert s["vote"]["buy"] == 0
    assert s["risk"] == {"data_insufficient": 1, "ok": 1}  # 乙留痕 + 甲 LC ok
    row = body["rows"][1]
    assert row["jev"]["vote"]["direction"] is None and row["jev"]["agree"] is None


def test_quotes_review_missing_date_422(monkeypatch):
    db = FakeMongoDb()
    client = _quotes_client(monkeypatch, db)
    response = client.get("/api/hotlist-jev/quotes-review")
    assert response.status_code == 422  # FastAPI 必填参数校验


def test_quotes_review_other_slot_doc_not_merged(monkeypatch):
    """watch 模式同集合按槽写（11:30/15:00）：台账只认 15:00 槽，11:30 判读不冒充不拼接（review blocker）。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    db["hotlist_jev_vote_confirm_pilot"].rows.append({
        "_id": f"{DATE}:11:30:000002:VOTE", "tradingDate": DATE, "slotTime": "11:30",
        "code": "000002", "name": "乙", "status": "ok", "origin": "vote_confirm_pilot",
        "synergyTier": "S", "voteDirection": "sell", "voteConfidence": 0.9,
        "riskFlag": {"level": "ok", "reasons": []},
        "questionSetVersion": "v1", "questionSetHash": "abc123"})
    db["hotlist_jev_lifecycle_recheck_pilot"].rows.append({
        "_id": f"{DATE}:11:30:000002:LC", "tradingDate": DATE, "slotTime": "11:30",
        "code": "000002", "name": "乙", "status": "ok", "origin": "lifecycle_recheck_pilot",
        "lcStage": "reversal", "riskFlag": {"level": "ok", "reasons": []},
        "questionSetVersion": "v1", "questionSetHash": "def456"})
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    s = body["summary"]
    # 11:30 文档不计入覆盖与台账：乙仍按 15:00 口径（vote buy→diverge），方向分布不变
    assert s["vote"]["buy"] == 2 and s["vote"]["sell"] == 0
    assert s["agree"] == 1 and s["diverge"] == 1
    assert s["lc"]["stages"] == {"ignition": 1}
    # unreviewed 按行统计：乙 15:00 无 LC 文档 → 仍 1；其余全覆盖
    assert s["vote"]["unreviewed"] == 0 and s["lc"]["unreviewed"] == 1
    row2 = body["rows"][1]
    assert row2["jev"]["vote"]["direction"] == "buy" and row2["jev"]["agree"] == "diverge"
    assert row2["jev"]["lc"] is None


def test_quotes_review_db_unavailable_degraded(monkeypatch):
    def _raise():
        raise RuntimeError("mongodb down")

    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", _raise)
    client = TestClient(app)
    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})
    assert response.status_code == 502
    assert response.json()["ok"] is False and "mongodb down" in response.json()["reason"]
