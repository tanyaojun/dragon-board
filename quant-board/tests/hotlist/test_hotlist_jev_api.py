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


class _FakeCursor:
    """最小 pymongo 游标替身：可迭代 + .sort()（链式返回新游标）。"""

    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def sort(self, key, direction=1):
        ordered = sorted(self._rows,
                         key=lambda row: (row.get(key) is None, str(row.get(key) or "")))
        return _FakeCursor(ordered if direction >= 0 else list(reversed(ordered)))


class FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        query = query or {}

        def matches(row):
            for key, expected in query.items():
                if isinstance(expected, dict) and "$in" in expected:
                    if row.get(key) not in expected["$in"]:
                        return False
                elif row.get(key) != expected:
                    return False
            return True

        return _FakeCursor([row for row in self.rows if matches(row)])

    def distinct(self, key, query=None):
        """pymongo distinct 替身：quotes_review 的 voteSlots / 选帧回退用。"""
        return sorted({row.get(key) for row in self.find(query) if row.get(key) is not None},
                     key=lambda value: (value is None, str(value)))

    def find_one(self, query=None, projection=None, sort=None):
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
        "corpusCaliberVersion": "eod-2026-10-22",
        "frameCoverage": {"expectedCount": 10, "frameCount": 9,
                          "missingSlots": ["14:30"], "lastSlot": "15:00",
                          "hasCloseFrame": True},
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
    assert body["jev"]["frameCoverage"]["hasCloseFrame"] is True
    assert body["jev"]["frameCoverage"]["missingSlots"] == ["14:30"]
    assert body["jev"]["corpusCaliberVersion"] == "eod-2026-10-22"
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
    """两股样本：甲(S/buy→agree，带 LC 一致)、乙(D/buy→diverge，LC diverge，带留痕文档)；
    韭研 final 供 board/连板 join（THS 池缺失 → board 仍挂、二分口径降级旗标）。"""
    db["snapshot_frames"].rows = [frame(DATE, "15:00")]
    db["jiuyan_action"].rows = [
        {"_id": f"{DATE}:final",
         "fields": [
             {"name": "AI影视", "stocks": [
                 {"code": "000001", "name": "甲", "num": None, "time": "09:25:00"}]},
             {"name": "大消费", "stocks": [
                 {"code": "000002", "name": "乙", "num": None, "time": None}]},
         ]}]

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
                                       "volumePrice": {"signalTier": "A",
                                                       "quadrant": "rise_volume",
                                                       "score": 62, "direction": "up"},
                                       "lifecycle": {"stage": "ignition", "veto": False},
                                       "synergy": {"signalTier": "S"}}}},
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "000002",
         "analysis": {"resonance": {"signalTier": "B", "direction": "hold", "score": 55.0},
                      "observation": {"lifecycle": {"stage": "ignition"},
                                       "crossSection": {"signalTier": "B"},
                                       "volumePrice": {"signalTier": "D",
                                                       "quadrant": "fall_shrink",
                                                       "score": 30, "direction": "down"},
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
    # 共振维独立判读（RES 试点题集）：甲走强↔引擎 buy 一致；乙走弱↔引擎 hold 分歧
    db["hotlist_jev_resonance_recheck_pilot"].rows = [
        {"_id": f"{DATE}:15:00:000001:RES", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000001", "name": "甲", "status": "ok", "origin": "resonance_recheck_pilot",
         "ammoVersion": "2026-10-14a", "bars": 50,
         "resonanceDirection": "buy", "resonanceConfidence": 0.7, "resonanceScore": 62.0,
         "resonanceProbabilities": {"buy": 0.7},
         "engineDirection": "buy", "engineScore": 91.0, "engineTier": "S",
         "engineLabel": "非常强", "engineStatus": "ok",
         "riskFlag": {"level": "ok", "reasons": []},
         "questionSetVersion": "v1", "questionSetHash": "res789",
         "narrative": "RES 叙事", "questionsRaw": {}, "responseRaw": {"ok": 1}},
        {"_id": f"{DATE}:15:00:000002:RES", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000002", "name": "乙", "status": "ok", "origin": "resonance_recheck_pilot",
         "ammoVersion": "2026-10-14a", "bars": 4,
         "resonanceDirection": "sell", "resonanceConfidence": 0.55, "resonanceScore": 30.0,
         "engineDirection": "hold", "engineScore": 55.0, "engineTier": "B",
         "riskFlag": {"level": "ok", "reasons": []},
         "questionSetVersion": "v1", "questionSetHash": "res789"},
    ]
    # 热度维独立判读（HEA 试点题集）：甲复现 A↔引擎 B 分歧；乙复现 C↔引擎 B 分歧
    db["hotlist_jev_heat_recheck_pilot"].rows = [
        {"_id": f"{DATE}:15:00:000001:HEA", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000001", "name": "甲", "status": "ok", "origin": "heat_recheck_pilot",
         "ammoVersion": "2026-10-15b", "bars": 50,
         "heatAttribution": "individual_strong", "heatAttributionConfidence": 0.8,
         "attributionAnchor": "individual_strong",
         "heatEvolution": "igniting", "heatEvolutionConfidence": 0.7,
         "evolutionAnchor": "igniting",
         "heatTier": "A", "heatTierConfidence": 0.8, "heatDirection": "buy",
         "heatConfidence": 0.7, "heatProbabilities": {"buy": 0.7},
         "enginePercentile": 72.0, "enginePercentileDelta": 6.0,
         "engineRelativeToMarket": 22.0, "engineTier": "B",
         "riskFlag": {"level": "ok", "reasons": []},
         "questionSetVersion": "v2", "questionSetHash": "hea789",
         "narrative": "HEA 叙事", "questionsRaw": {}, "responseRaw": {"ok": 1}},
        {"_id": f"{DATE}:15:00:000002:HEA", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000002", "name": "乙", "status": "ok", "origin": "heat_recheck_pilot",
         "ammoVersion": "2026-10-15b", "bars": 4,
         "heatAttribution": "market_wide_rise", "heatAttributionConfidence": 0.5,
         "attributionAnchor": "follow_market",
         "heatEvolution": "dormant", "heatEvolutionConfidence": 0.5,
         "evolutionAnchor": "dormant",
         "heatTier": "C", "heatTierConfidence": 0.5, "heatDirection": "hold",
         "heatConfidence": 0.5,
         "enginePercentile": 30.0, "enginePercentileDelta": None,
         "engineRelativeToMarket": -20.0, "engineTier": "B",
         "riskFlag": {"level": "partial", "reasons": ["delta 缺失（首帧/单点）"]},
         "questionSetVersion": "v2", "questionSetHash": "hea789"},
    ]
    # 量价维独立判读（VPQ 试点题集）：甲复现 A↔引擎 A 一致；乙复现 D↔引擎 D 一致
    db["hotlist_jev_volume_recheck_pilot"].rows = [
        {"_id": f"{DATE}:15:00:000001:VPQ", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000001", "name": "甲", "status": "ok", "origin": "volume_recheck_pilot",
         "ammoVersion": "2026-10-15b",
         "volumeCause": "volume_expansion_up", "volumeCauseConfidence": 0.9,
         "causeAnchor": "volume_expansion_up",
         "volumeTradability": "tradable", "volumeTradabilityConfidence": 0.9,
         "tradabilityAnchor": "tradable",
         "volumeTier": "A", "volumeTierConfidence": 0.9, "volumeQuadrant": "rise_volume",
         "volumeDirection": "buy", "volumeConfidence": 0.8,
         "volumeProbabilities": {"buy": 0.8},
         "engineScore": 62, "engineDirection": "up", "engineQuadrant": "rise_volume",
         "engineTier": "A", "engineAmountRatio": None,
         "riskFlag": {"level": "ok", "reasons": []},
         "questionSetVersion": "v2", "questionSetHash": "vpq789",
         "narrative": "VPQ 叙事", "questionsRaw": {}, "responseRaw": {"ok": 1}},
        {"_id": f"{DATE}:15:00:000002:VPQ", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000002", "name": "乙", "status": "ok", "origin": "volume_recheck_pilot",
         "ammoVersion": "2026-10-15b",
         "volumeCause": "fund_outflow", "volumeCauseConfidence": 0.8,
         "causeAnchor": "fund_outflow",
         "volumeTradability": "limit_up_blocked", "volumeTradabilityConfidence": 0.9,
         "tradabilityAnchor": "tradable",
         "volumeTier": "D", "volumeTierConfidence": 0.9, "volumeQuadrant": "fall_shrink",
         "volumeDirection": "sell", "volumeConfidence": 0.8,
         "engineScore": 30, "engineDirection": "down", "engineQuadrant": "fall_shrink",
         "engineTier": "D", "engineAmountRatio": None,
         "riskFlag": {"level": "ok", "reasons": []},
         "questionSetVersion": "v2", "questionSetHash": "vpq789"},
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
    assert first["board"] == "AI影视"          # 板块=韭研 final field.name
    assert rows[1]["board"] == "大消费"
    assert first["tiers"] == {"resonance": "S", "trend": "A", "heat": "B",
                               "volumePrice": "A", "cycle": "ignition", "synergy": "S"}
    assert first["jev"]["vote"]["direction"] == "buy"
    assert first["jev"]["agree"] == "agree"      # S→buy ↔ jev buy
    assert first["jev"]["lcAgree"] == "agree"    # 规则 ignition ↔ jev ignition
    # 共振维（RES）：读数 + 同帧引擎对照锚（就地改【共振】列的数据源）
    assert first["jev"]["res"] == {"status": "ok", "direction": "buy",
                                    "confidence": 0.7, "score": 62.0, "riskLevel": "ok"}
    assert first["jev"]["resAgree"] == "agree"    # 引擎 buy ↔ jev buy
    assert "docs" not in first                    # 缺省不嵌大字段
    second = rows[1]
    assert second["jev"]["agree"] == "diverge"   # D→sell ↔ jev buy
    assert second["jev"]["resAgree"] == "diverge"  # 引擎 hold ↔ jev sell
    assert second["jev"]["lc"] is None
    assert second["turnoverRate"] is None          # 缺失如实 None 不伪造
    s = body["summary"]
    assert s["total"] == 2 and s["tiered"] == 2
    assert s["vote"]["buy"] == 2 and s["vote"]["unreviewed"] == 0
    assert s["lc"]["stages"] == {"ignition": 1} and s["lc"]["unreviewed"] == 1
    assert s["resonance"]["buy"] == 1 and s["resonance"]["sell"] == 1
    assert s["resonance"]["unreviewed"] == 0 and s["resonance"]["ok"] == 2
    assert s["resAgree"] == 1 and s["resDiverge"] == 1
    assert s["agree"] == 1 and s["diverge"] == 1
    # 甲 VOTE+LC+RES+HEA+VPQ 五 ok + TRD 无 → 乙 VOTE partial + HEA partial
    assert s["risk"] == {"ok": 7, "partial": 2}


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
    # RES 存档全保留（原料代际戳/出现次数/引擎对照锚快照）
    assert rows[0]["docs"]["res"]["resonanceScore"] == 62.0
    assert rows[0]["docs"]["res"]["bars"] == 50
    assert rows[0]["docs"]["res"]["engineDirection"] == "buy"
    assert rows[0]["docs"]["res"]["ammoVersion"] == "2026-10-14a"
    assert rows[1]["docs"]["res"]["resonanceDirection"] == "sell"


def test_quotes_review_no_frame_no_data(monkeypatch):
    """全日无 half_hour 帧：noData + 结构化 reason（帧口径已从「只认 15:00」扩为当日任一帧）。"""
    db = FakeMongoDb()  # 无任何帧
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True and body["noData"] is True and body["rows"] == []
    assert body["slotTime"] is None and body["snapshotId"] is None
    assert "half_hour" in body["reason"]


def test_quotes_review_frame_fallback_order(monkeypatch):
    """选帧顺序：15:00 > 有 vote 判读的最新帧 > 当天最新帧（帧选择器上线后仍保收盘优先）。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    # 只有 10:00 / 14:00 两个帧（无 15:00），vote 判读落在 10:00 → 回退取 10:00
    db["snapshot_frames"].rows = [frame(DATE, "14:00"), frame(DATE, "10:00")]
    db["snapshot_stock_rows"].rows = [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:10:00", "code": "000001",
         "name": "甲", "rank": 1}]
    db["hotlist_jev_vote_confirm_pilot"].rows = [
        {"_id": f"{DATE}:10:00:000001:VOTE", "tradingDate": DATE, "slotTime": "10:00",
         "code": "000001", "name": "甲", "status": "ok", "origin": "vote_confirm_pilot",
         "synergyTier": "S", "voteDirection": "buy", "voteConfidence": 0.72,
         "riskFlag": {"level": "ok", "reasons": []},
         "questionSetVersion": "v1", "questionSetHash": "abc123"}]
    client = _quotes_client(monkeypatch, db)

    body = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE}).json()

    assert body["noData"] is False and body["slotTime"] == "10:00"
    assert body["voteSlots"] == ["10:00"]  # 前端帧选择器数据源


def test_quotes_review_explicit_slot_time_pins_frame(monkeypatch):
    """传 slotTime 固定帧：帧不存在 → noData + 点名该槽位的 reason，不静默回退。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    client = _quotes_client(monkeypatch, db)

    ok = client.get("/api/hotlist-jev/quotes-review",
                    params={"date": DATE, "slotTime": "15:00"}).json()
    assert ok["noData"] is False and ok["slotTime"] == "15:00"

    missing = client.get("/api/hotlist-jev/quotes-review",
                         params={"date": DATE, "slotTime": "11:30"}).json()
    assert missing["noData"] is True and missing["rows"] == []
    assert "11:30" in missing["reason"]


def test_quotes_review_resonance_locks_judgment_frame(monkeypatch):
    """共振判读锁判读帧（与 LC 同规，跨槽拼接禁令）：所选帧无判读 → 全 '--' + 结构化说明，
    不用别帧判读填充；判读帧=序列末项，换帧读数即换原料。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    # 把 RES 判读全部改到 11:00 帧（引擎共振对照锚同帧），15:00 帧则无判读
    db["hotlist_jev_resonance_recheck_pilot"].rows = [
        {**doc, "_id": f"{DATE}:11:00:{doc['code']}:RES", "slotTime": "11:00"}
        for doc in db["hotlist_jev_resonance_recheck_pilot"].rows]
    client = _quotes_client(monkeypatch, db)

    body = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE}).json()

    assert body["slotTime"] == "15:00"
    assert body["resonanceSlots"] == ["11:00"]
    assert body["resonanceSlotNote"] and "11:00" in body["resonanceSlotNote"]
    # 该帧无共振判读：读数缺失如实 '--'（前端列位回落引擎档位），一致率不计票
    assert all(r["jev"]["res"] is None for r in body["rows"])
    assert all(r["jev"]["resAgree"] is None for r in body["rows"])
    assert body["summary"]["resonance"]["unreviewed"] == body["summary"]["total"]
    assert body["summary"]["resAgree"] == 0 and body["summary"]["resDiverge"] == 0


def test_quotes_review_heat_volume_join_and_reproduction(monkeypatch):
    """热度/量价维独立判读 join 合同：行级 jev.hea/jvv.vpq + heaAgree/vpqAgree（档位复现），
    summary.heat/volumePrice 块（tiers/quadrants/direction 分布 + unreviewed），
    帧锁定的 heatSlots/volumeSlots + slotNote；语义 direction 无锚只落分布。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    client = _quotes_client(monkeypatch, db)

    body = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE}).json()

    rows = body["rows"]
    a, b = rows[0], rows[1]
    # 行级 V2 逻辑主问：热度归因（甲 individual_strong 对锚一致；乙 market_wide_rise 对锚分歧）
    assert a["jev"]["hea"]["attribution"] == "individual_strong"
    assert a["jev"]["hea"]["attributionAnchor"] == "individual_strong"
    assert a["jev"]["hea"]["evolution"] == "igniting"
    assert a["jev"]["heaAgree"] == "agree" and b["jev"]["heaAgree"] == "diverge"
    # 行级 V2 逻辑主问：量价主因（甲/乙均对锚一致）+ 可交易性（乙涨停封板 vs 锚 tradable 分歧）
    assert a["jev"]["vpq"]["cause"] == "volume_expansion_up"
    assert a["jev"]["vpq"]["tradability"] == "tradable"
    assert b["jev"]["vpq"]["tradability"] == "limit_up_blocked"
    assert b["jev"]["vpq"]["tradabilityAnchor"] == "tradable"
    assert a["jev"]["vpqAgree"] == "agree" and b["jev"]["vpqAgree"] == "agree"
    # summary V2：归因/演化分布 + 主问一致分歧 + 基线 tier 一致分歧 + 语义方向分布
    heat, vp = body["summary"]["heat"], body["summary"]["volumePrice"]
    assert heat["attributions"] == {"individual_strong": 1, "market_wide_rise": 1}
    assert heat["evolutions"] == {"igniting": 1, "dormant": 1}
    assert heat["attrAgree"] == 1 and heat["attrDiverge"] == 1
    assert heat["evolAgree"] == 2 and heat["evolDiverge"] == 0   # 甲 igniting、乙 dormant 均对锚一致
    assert heat["tiers"] == {"A": 1, "C": 1}
    assert heat["tierAgree"] == 0 and heat["tierDiverge"] == 2   # A vs B、C vs B
    assert heat["direction"] == {"buy": 1, "hold": 1}
    assert heat["ok"] == 2 and heat["unreviewed"] == 0
    assert vp["causes"] == {"volume_expansion_up": 1, "fund_outflow": 1}
    assert vp["tradability"] == {"tradable": 1, "limit_up_blocked": 1}
    assert vp["causeAgree"] == 2 and vp["causeDiverge"] == 0
    assert vp["tradAgree"] == 1 and vp["tradDiverge"] == 1
    assert vp["tiers"] == {"A": 1, "D": 1} and vp["tierAgree"] == 2
    assert vp["quadrants"] == {"rise_volume": 1, "fall_shrink": 1}
    assert vp["direction"] == {"buy": 1, "sell": 1} and vp["ok"] == 2 and vp["unreviewed"] == 0
    # 顶层 Agree/Diverge = V2 逻辑主问（归因/主因）对复算锚
    assert body["summary"]["heaAgree"] == 1 and body["summary"]["heaDiverge"] == 1
    assert body["summary"]["vpqAgree"] == 2 and body["summary"]["vpqDiverge"] == 0
    assert body["heatSlots"] == ["15:00"] and body["volumeSlots"] == ["15:00"]
    assert body["heatSlotNote"] is None and body["volumeSlotNote"] is None


def test_quotes_review_heat_volume_locks_judgment_frame(monkeypatch):
    """热度/量价判读锁判读帧（与 LC/RES/TRD 同规）：所选帧无判读 → 全 '--' + 结构化说明，
    不用别帧判读填充；复现率不计票。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    for col, suffix in (("hotlist_jev_heat_recheck_pilot", "HEA"),
                        ("hotlist_jev_volume_recheck_pilot", "VPQ")):
        db[col].rows = [{**doc, "_id": f"{DATE}:11:00:{doc['code']}:{suffix}",
                         "slotTime": "11:00"} for doc in db[col].rows]
    client = _quotes_client(monkeypatch, db)

    body = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE}).json()

    assert body["slotTime"] == "15:00"
    assert body["heatSlots"] == ["11:00"] and body["volumeSlots"] == ["11:00"]
    assert body["heatSlotNote"] and "11:00" in body["heatSlotNote"]
    assert body["volumeSlotNote"] and "11:00" in body["volumeSlotNote"]
    assert all(r["jev"]["hea"] is None for r in body["rows"])
    assert all(r["jev"]["vpq"] is None for r in body["rows"])
    assert all(r["jev"]["heaAgree"] is None and r["jev"]["vpqAgree"] is None
               for r in body["rows"])
    assert body["summary"]["heat"]["unreviewed"] == body["summary"]["total"]
    assert body["summary"]["volumePrice"]["unreviewed"] == body["summary"]["total"]
    assert body["summary"]["heaAgree"] == 0 and body["summary"]["heaDiverge"] == 0
    assert body["summary"]["vpqAgree"] == 0 and body["summary"]["vpqDiverge"] == 0


def test_quotes_review_vote_join_ignores_dataset_id_field(monkeypatch):
    """两个 pilot 集合文档不带 datasetId：读口不得按 datasetId 过滤（否则整列台账静默清空）。

    回归护栏：若给 vote/LC 查询补 datasetId 条件，生产文档（无该字段）会一条都匹配不上，
    复核台账整列变空——正是「有数据不展示」。
    """
    db = FakeMongoDb()
    _seed_quotes_review(db)
    # 给 vote 文档打一个与请求 dataset_id 无关的 datasetId：仍必须 join 上
    db["hotlist_jev_vote_confirm_pilot"].rows = [
        {**doc, "datasetId": "unrelated_dataset"}
        for doc in db["hotlist_jev_vote_confirm_pilot"].rows]
    client = _quotes_client(monkeypatch, db)

    body = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE}).json()

    assert body["noData"] is False and body["voteSlots"] == ["15:00"]
    assert body["summary"]["vote"]["ok"] == 2
    assert all(r["jev"] is not None for r in body["rows"])


def test_quotes_review_vote_priority_is_deterministic(monkeypatch):
    """同 code 多 slot 并存：11:00 > 15:00 > 其他；同优先级取 computedAt 新者（与游标顺序无关）。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    base = dict(db["hotlist_jev_vote_confirm_pilot"].rows[1])  # 乙 15:00 buy
    # 插入顺序刻意让「旧者」在前：若按先到先得/游标顺序，结果会漂
    db["hotlist_jev_vote_confirm_pilot"].rows = [
        {**base, "_id": f"{DATE}:14:00:000002:VOTE", "slotTime": "14:00",
         "voteDirection": "sell", "voteConfidence": 0.9,
         "computedAt": "2026-10-08T14:05:00"},
        {**base, "_id": f"{DATE}:11:00:000002:VOTE", "slotTime": "11:00",
         "voteDirection": "sell", "voteConfidence": 0.9,
         "computedAt": "2026-10-08T11:05:00"},
        {**base, "computedAt": "2026-10-08T15:05:00"},
    ]
    client = _quotes_client(monkeypatch, db)

    body = client.get("/api/hotlist-jev/quotes-review",
                      params={"date": DATE, "with_docs": 1}).json()

    row2 = next(r for r in body["rows"] if r["code"] == "000002")
    # 11:00（代际新）压过 15:00 与 14:00，尽管它在 rows 里排中间
    assert row2["jev"]["vote"]["direction"] == "sell"
    assert row2["docs"]["vote"]["slotTime"] == "11:00"


def test_quotes_review_same_priority_prefers_newer_computed_at(monkeypatch):
    """同为 15:00 槽（重跑覆盖场景）：取 computedAt 更新者，且不把私有排序键泄进 docs。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    stale = dict(db["hotlist_jev_vote_confirm_pilot"].rows[0])   # 甲 15:00 buy
    fresh = {**stale, "_id": f"{DATE}:15:00:000001:VOTE", "voteDirection": "hold",
             "voteConfidence": 0.4, "computedAt": "2026-10-09T09:00:00"}
    stale = {**stale, "computedAt": "2026-10-08T15:05:00"}
    db["hotlist_jev_vote_confirm_pilot"].rows = [fresh, stale]
    client = _quotes_client(monkeypatch, db)

    body = client.get("/api/hotlist-jev/quotes-review",
                      params={"date": DATE, "with_docs": 1}).json()

    row1 = next(r for r in body["rows"] if r["code"] == "000001")
    assert row1["jev"]["vote"]["direction"] == "hold"
    assert "_priority" not in row1["docs"]["vote"] and "_rank" not in row1["docs"]["vote"]


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
    # 乙 VOTE 留痕(data_insufficient)；甲 LC/RES/HEA/VPQ + 乙 RES/VPQ 共 6 ok；乙 HEA partial
    assert s["risk"] == {"data_insufficient": 1, "ok": 6, "partial": 1}
    row = body["rows"][1]
    assert row["jev"]["vote"]["direction"] is None and row["jev"]["agree"] is None


def test_quotes_review_boards_join_passthrough(monkeypatch):
    '''连板口径：N==M 直接计板；N>M 断板股回溯逐日封板链取真实连续高度（用户口径）。

    韭研 num「N天M板」：3天3板=纯连板 3；10天8板=断板股——今日+昨日封、前日未封
    → 真实连续高度 2（min(2,8)），非 8。
    '''
    db = FakeMongoDb()
    _seed_quotes_review(db)
    import backend.operations.jev_label_jiuyan as jiuyan_mod
    captured = {}

    def fake_board_info(db_, date_):
        captured["date"] = date_
        return ({"000001": {"boards": 3, "days": 3, "limitUpTime": "09:31"},
                 "000002": {"boards": 8, "days": 10}},
                {"jiuyanFinalFound": True, "prevPoolFound": True, "thsPoolFound": True,
                 "prevThsPoolFound": True, "thsZhabanTotal": 5})

    monkeypatch.setattr(jiuyan_mod, "jiuyan_board_info", fake_board_info)
    # 回溯链：2026-09-29 封 000002、2026-09-28 未封（断板日）→ 今日起连 2 板
    monkeypatch.setattr(jiuyan_mod, "trading_dates_before",
                        lambda db_, date_, n=20, dataset_id="dragonboard_live":
                        ["2026-09-28", "2026-09-29"])
    monkeypatch.setattr(jiuyan_mod, "_ths_failed_codes", lambda db_, d: (set(), True))
    db["jiuyan_action"].rows = [
        {"_id": "2026-09-29:final", "fields": [{"stocks": [{"code": "000002"}]}]},
        {"_id": "2026-09-28:final", "fields": [{"stocks": [{"code": "000001"}]}]},
    ]
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    assert captured["date"] == DATE
    assert body["rows"][0]["boards"] == 3        # 3天3板 = 纯连板
    assert body["rows"][1]["boards"] == 2        # 10天8板 → 真实连续高度 2（非 8）
    assert body["summary"]["streakUnverified"] == 0
    assert body["boardJoinDegraded"] is None


def test_quotes_review_broken_streak_today_zhaban_none(monkeypatch):
    '''断板股今日炸板：无「至今日」连续高度 → None，计 streakUnverified。'''
    db = FakeMongoDb()
    _seed_quotes_review(db)
    import backend.operations.jev_label_jiuyan as jiuyan_mod

    def fake_board_info(db_, date_):
        return ({"000002": {"boards": 8, "days": 10, "zhaban": True}},
                {"jiuyanFinalFound": True, "prevPoolFound": True, "thsPoolFound": True,
                 "prevThsPoolFound": True})

    monkeypatch.setattr(jiuyan_mod, "jiuyan_board_info", fake_board_info)
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    assert body["rows"][1]["boards"] is None
    assert body["summary"]["streakUnverified"] == 1


def test_quotes_review_broken_streak_history_unverifiable_none(monkeypatch):
    '''回溯历史日韭研 final 缺失：不可验证 → None（宁缺毋猜），不把可疑日当封板。'''
    db = FakeMongoDb()
    _seed_quotes_review(db)
    import backend.operations.jev_label_jiuyan as jiuyan_mod

    def fake_board_info(db_, date_):
        return ({"000002": {"boards": 8, "days": 10}},
                {"jiuyanFinalFound": True, "prevPoolFound": True, "thsPoolFound": True,
                 "prevThsPoolFound": True})

    monkeypatch.setattr(jiuyan_mod, "jiuyan_board_info", fake_board_info)
    monkeypatch.setattr(jiuyan_mod, "trading_dates_before",
                        lambda db_, date_, n=20, dataset_id="dragonboard_live":
                        ["2026-09-28", "2026-09-29"])
    monkeypatch.setattr(jiuyan_mod, "_ths_failed_codes", lambda db_, d: (set(), True))
    # 只种 09-28 的 final（09-29 缺失 → 不可验）
    db["jiuyan_action"].rows = [
        {"_id": "2026-09-28:final", "fields": [{"stocks": [{"code": "000002"}]}]},
    ]
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    assert body["rows"][1]["boards"] is None
    assert body["summary"]["streakUnverified"] == 1
    assert body["ok"] is True  # 主读口不阻断


def test_quotes_review_boards_source_missing_degraded(monkeypatch):
    """韭研 final 缺失：连板全缺 + boardJoinDegraded 结构化旗标，不阻断主读口（fail-visible）。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    db["jiuyan_action"].rows = []  # 本测试专测 final 缺失：清掉共享种子的韭研 final（jiuyanFinalFound=False）
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    assert body["boardJoinDegraded"] == "jiuyan_final_missing"
    assert all(r["boards"] is None for r in body["rows"])
    assert body["ok"] is True and len(body["rows"]) == 2  # 主读口不阻断


def test_quotes_review_unknown_values_shown_as_missing(monkeypatch):
    """引擎 unknown 字面值（档位/阶段/方向）：读口归一 None（前端统一 '--'），不进排序与台账。"""
    db = FakeMongoDb()
    _seed_quotes_review(db)
    db["snapshot_stock_rows"].rows.append(
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00",
         "code": "000009", "name": "丁", "rank": 9})
    db["snapshot_analysis"].rows.append(
        {"datasetId": DATASET, "snapshotId": f"half_hour:{DATE}:15:00", "code": "000009",
         "analysis": {"resonance": {"signalTier": "unknown"},
                      "observation": {"rankTrend": {"signalTier": "unknown"},
                                       "crossSection": {"signalTier": "unknown"},
                                       "volumePrice": {"signalTier": "unknown"},
                                       "lifecycle": {"stage": "unknown"},
                                       "synergy": {"signalTier": "unknown"}}}})
    db["hotlist_jev_vote_confirm_pilot"].rows.append(
        {"_id": f"{DATE}:15:00:000009:VOTE", "tradingDate": DATE, "slotTime": "15:00",
         "code": "000009", "name": "丁", "status": "ok", "origin": "vote_confirm_pilot",
         "synergyTier": "unknown", "voteDirection": "unknown", "voteConfidence": 0.4,
         "riskFlag": {"level": "partial", "reasons": []},
         "questionSetVersion": "v1", "questionSetHash": "abc123"})
    client = _quotes_client(monkeypatch, db)

    response = client.get("/api/hotlist-jev/quotes-review", params={"date": DATE})

    assert response.status_code == 200
    body = response.json()
    row = next(r for r in body["rows"] if r["code"] == "000009")
    assert all(v is None for v in row["tiers"].values())
    assert row["jev"]["vote"]["direction"] is None and row["jev"]["agree"] is None
    s = body["summary"]
    assert s["vote"]["buy"] == 2 and s["vote"]["hold"] == 0  # unknown 不计方向
    assert s["lc"]["stages"] == {"ignition": 1}              # unknown 不进阶段分布
    assert s["total"] == 3 and s["tiered"] == 2              # unknown 五维不算可算


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
