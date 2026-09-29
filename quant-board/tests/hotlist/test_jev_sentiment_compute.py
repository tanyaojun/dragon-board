# -*- coding: utf-8 -*-
"""jev 双问题编排服务测试（观察轨道 v3）。

FakeMongo + monkeypatch call_jev，不触网不入生产库；合同见
quant-board/docs/hotlist-jev/hotlist-jev-emotion-observe-design.md §6/§8。
"""
from __future__ import annotations

from typing import Any

import pytest

import backend.services.jev.jev_sentiment_compute as jev_module
from backend.services.jev.jev_sentiment_compute import (
    compute_and_upsert_for_day,
    compute_and_upsert_for_slot,
    run_jev_post_persist,
)

DATASET = "dragonboard_live"
DATE = "2026-10-08"


# ── FakeMongo（同 test_hotlist_sentiment_backfill 模式：$in/$ne/点投影/幂等替换）──


class FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __iter__(self):
        return iter(self._rows)

    def sort(self, keys):
        for key, direction in reversed(keys):
            self._rows.sort(key=lambda row: row.get(key) or "", reverse=direction < 0)
        return self


class FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.replace_calls = []

    def find(self, query=None, projection=None):
        query = query or {}
        matched = [row for row in self.rows if self._matches(row, query)]
        return FakeCursor(matched)

    def find_one(self, query=None, sort=None):
        rows = list(self.find(query or {}))
        if sort:
            rows = list(FakeCursor(rows).sort(sort))
        return rows[0] if rows else None

    def replace_one(self, query, doc, upsert=False):
        self.replace_calls.append((query, doc, upsert))
        self.rows = [row for row in self.rows if not self._matches(row, query)]
        self.rows.append(doc)

    @staticmethod
    def _matches(row, query):
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
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


# ── fixtures ──


def frame(date: str, slot: str) -> dict[str, Any]:
    return {
        "datasetId": DATASET, "snapshotId": f"half_hour:{date}:{slot}", "type": "half_hour",
        "tradingDate": date, "slotTime": slot, "timestamp": f"{date}T{slot}:00+08:00",
        "indices": {"sh": {"change": -12.2}},
        "limitSummary": {
            "continuousBoards": {"yiban": 40, "erban": 18, "sanban": 7, "sibanPlus": 3, "maxBoard": 6},
            "zhaban": {"count": 12, "rate": 15.0, "fengbanRate": 85.0, "ztCount": 68},
        },
    }


def rows(date: str, slot: str) -> list[dict[str, Any]]:
    return [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{date}:{slot}", "code": "000001",
         "name": "甲", "rank": 1, "heat": 99, "pctChange": 9.98, "change": 9.98,
         "price": 9.66, "limitUpPrice": 9.66, "mainTheme": "算力", "zlje": 5.0e6,
         "reason": "算力租赁"},
        {"datasetId": DATASET, "snapshotId": f"half_hour:{date}:{slot}", "code": "000002",
         "name": "乙", "rank": 2, "heat": 60, "pctChange": -1.0, "change": -1.0, "zlje": -1.0e6},
    ]


def analysis(date: str, slot: str) -> list[dict[str, Any]]:
    return [
        {"datasetId": DATASET, "snapshotId": f"half_hour:{date}:{slot}", "code": "000001",
         "analysis": {"displayStatus": {"stage": "ignition"}}},
    ]


def seed_day(db: FakeMongoDb) -> None:
    db["snapshot_frames"].rows = [frame("2026-10-07", "15:00"), frame(DATE, "09:30"), frame(DATE, "10:00")]
    db["snapshot_stock_rows"].rows = [
        *rows("2026-10-07", "15:00"), *rows(DATE, "09:30"), *rows(DATE, "10:00")]
    db["snapshot_analysis"].rows = [
        *analysis("2026-10-07", "15:00"), *analysis(DATE, "09:30"), *analysis(DATE, "10:00")]


def ok_envelope(answers_keys=("frame_stage", "sequence_stage", "temperature", "crowding")) -> dict[str, Any]:
    score_legend = {"0": "0", "1": "11", "2": "22", "3": "33", "4": "44",
                    "5": "56", "6": "67", "7": "78", "8": "89", "9": "100"}
    answers: dict[str, Any] = {}
    for key in answers_keys:
        if "temperature" in key or "crowding" in key:
            answers[key] = {"type": "score", "score": 5.0, "legend": dict(score_legend)}
        elif key == "day_pattern":
            answers[key] = {"type": "choice", "choice": "rally_fade", "probabilities": {"rally_fade": 0.5}, "confidence": 0.6}
        else:
            choice = "ferment" if key == "frame_stage" else "start"
            answers[key] = {"type": "choice", "choice": choice, "probabilities": {choice: 0.6}, "confidence": 0.7}
    return {"result": {"state": "Completed", "result": {
        "model": "jev-1.13.0", "answers": answers,
        "usage": {"input_tokens": 1200, "output_tokens": 130}}}, "success": True}


@pytest.fixture()
def gate_on(monkeypatch):
    monkeypatch.setenv("JEV_SENTIMENT_ENABLED", "true")
    monkeypatch.setenv("JEV_CF_TOKEN", "test-token")
    monkeypatch.delenv("JEV_CF_ACCOUNT", raising=False)


def _mock_jev_ok(monkeypatch, calls: list, answers_keys=("frame_stage", "sequence_stage", "temperature", "crowding")):
    envelope = ok_envelope(answers_keys)

    def fake_call(account_id, api_token, state, questions, model="typesafe/jev", timeout=60):
        calls.append({"state": state, "questions": questions, "timeout": timeout})
        return envelope, 1100

    monkeypatch.setattr(jev_module, "call_jev", fake_call)


# ── 槽位路径 ──


def test_slot_ok_path_full_contract(monkeypatch, gate_on):
    db = FakeMongoDb()
    seed_day(db)
    calls: list = []
    _mock_jev_ok(monkeypatch, calls)
    result = compute_and_upsert_for_slot(db, dataset_id=DATASET, trading_date=DATE, slot_time="10:00")
    assert result["written"] is True and result["status"] == "ok"
    coll = db["hotlist_jev_sentiment"]
    assert len(coll.rows) == 1
    doc = coll.rows[0]
    assert doc["_id"] == f"{DATASET}:half_hour:{DATE}:10:00"
    assert doc["kind"] == "slot" and doc["origin"] == "collector"
    assert doc["status"] == "ok" and doc["model"] == "jev-1.13.0"
    assert doc["answers"]["frame_stage"]["choice"] == "ferment"
    assert doc["answers"]["sequence_stage"]["choice"] == "start"
    assert doc["scores"]["temperature"] == 55.6  # idx5/9*100
    assert doc["narrativeRaw"] and doc["questionsRaw"] and doc["evidenceRaw"]["slotTime"] == "10:00"
    assert doc["responseRaw"] == ok_envelope()
    assert doc["usage"]["input_tokens"] == 1200 and doc["latencyMs"] == 1100
    # 零规则输出：顶层无规则档位键
    for key in ("stage", "rawStage", "ruleStage", "ruleConfirmedStage", "summary", "signals"):
        assert key not in doc
    # 叙事输入审计：questions 无 noul；state 含当前帧与已走帧段
    assert "noul" not in str(doc["questionsRaw"])
    assert "【当前帧证据】" in doc["narrativeRaw"] and "【当日已走帧证据】" in doc["narrativeRaw"]
    assert len(calls) == 1 and calls[0]["timeout"] == 30


def test_slot_narrative_includes_prior_slots_ascending(monkeypatch, gate_on):
    db = FakeMongoDb()
    seed_day(db)
    calls: list = []
    _mock_jev_ok(monkeypatch, calls)
    compute_and_upsert_for_slot(db, dataset_id=DATASET, trading_date=DATE, slot_time="10:00")
    state = db["hotlist_jev_sentiment"].rows[0]["narrativeRaw"]
    assert "09:30｜" in state  # 前序槽压缩行
    # 缺失槽位（标准 10 槽中 10:00 之前只采到 09:30，其余为缺）不在则不虚构——09:30 是唯一前序
    assert "10:00｜" not in state.split("【当日已走帧证据】")[-1].split("【数据质量】")[0]


def test_slot_no_data_persists_explicit_doc(monkeypatch, gate_on):
    db = FakeMongoDb()
    calls: list = []
    _mock_jev_ok(monkeypatch, calls)
    result = compute_and_upsert_for_slot(db, dataset_id=DATASET, trading_date=DATE, slot_time="10:00")
    assert result["written"] is True and result["status"] == "no_data"
    doc = db["hotlist_jev_sentiment"].rows[0]
    assert doc["status"] == "no_data" and doc["kind"] == "slot"
    assert len(calls) == 0  # 无数据不调用模型


def test_slot_degraded_on_jev_error(monkeypatch, gate_on):
    db = FakeMongoDb()
    seed_day(db)

    def fake_error(account_id, api_token, state, questions, model="typesafe/jev", timeout=60):
        return {"success": False, "errors": [{"message": "HTTP 402 insufficient balance"}]}, 40

    monkeypatch.setattr(jev_module, "call_jev", fake_error)
    result = compute_and_upsert_for_slot(db, dataset_id=DATASET, trading_date=DATE, slot_time="10:00")
    assert result["status"] == "degraded"
    doc = db["hotlist_jev_sentiment"].rows[0]
    assert doc["status"] == "degraded" and "402" in doc["errorDetail"]
    assert doc["errorCode"] == "http_error"
    assert "answers" not in doc or not doc.get("answers")  # 不伪造档位


def test_slot_degraded_when_token_missing(monkeypatch, gate_on):
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    db = FakeMongoDb()
    seed_day(db)
    calls: list = []
    _mock_jev_ok(monkeypatch, calls)
    result = compute_and_upsert_for_slot(db, dataset_id=DATASET, trading_date=DATE, slot_time="10:00")
    assert result["status"] == "degraded" and result["errorCode"] == "missing_token"
    assert db["hotlist_jev_sentiment"].rows[0]["errorCode"] == "missing_token"
    assert len(calls) == 0


def test_gate_off_skips_without_write(monkeypatch):
    monkeypatch.delenv("JEV_SENTIMENT_ENABLED", raising=False)
    db = FakeMongoDb()
    seed_day(db)
    result = compute_and_upsert_for_slot(db, dataset_id=DATASET, trading_date=DATE, slot_time="10:00")
    assert result == {"written": False, "skipped": True, "reason": "jev_disabled"}
    assert len(db["hotlist_jev_sentiment"].rows) == 0


def test_slot_idempotent_upsert(monkeypatch, gate_on):
    db = FakeMongoDb()
    seed_day(db)
    calls: list = []
    _mock_jev_ok(monkeypatch, calls)
    compute_and_upsert_for_slot(db, dataset_id=DATASET, trading_date=DATE, slot_time="10:00")
    compute_and_upsert_for_slot(db, dataset_id=DATASET, trading_date=DATE, slot_time="10:00")
    assert len(db["hotlist_jev_sentiment"].rows) == 1


# ── 日级路径 ──


def test_day_ok_path(monkeypatch, gate_on):
    db = FakeMongoDb()
    seed_day(db)
    calls: list = []
    _mock_jev_ok(monkeypatch, calls, answers_keys=("day_stage", "day_pattern", "day_temperature", "day_crowding"))
    result = compute_and_upsert_for_day(db, dataset_id=DATASET, trading_date=DATE)
    assert result["written"] is True and result["status"] == "ok"
    doc = db["hotlist_jev_sentiment"].rows[0]
    assert doc["_id"] == f"{DATASET}:half_hour:{DATE}:eod"
    assert doc["kind"] == "eod" and doc["slotTime"] == "EOD"
    assert doc["anchoredSlotTime"] == "10:00"
    assert "day_stage" in doc["answers"] and "day_pattern" in doc["answers"]
    assert "【逐帧证据】" in doc["narrativeRaw"] and "09:30｜" in doc["narrativeRaw"]


def test_day_no_data(monkeypatch, gate_on):
    db = FakeMongoDb()
    calls: list = []
    _mock_jev_ok(monkeypatch, calls)
    result = compute_and_upsert_for_day(db, dataset_id=DATASET, trading_date=DATE)
    assert result["status"] == "no_data"
    assert db["hotlist_jev_sentiment"].rows[0]["status"] == "no_data"
    assert len(calls) == 0


# ── 链分派 ──


def test_run_jev_post_persist_dispatch(monkeypatch, gate_on):
    db = FakeMongoDb()
    seed_day(db)
    calls: list = []
    _mock_jev_ok(monkeypatch, calls)
    assert run_jev_post_persist(db, dataset_id=DATASET, snapshot_type="half_hour",
                                trading_date=DATE, slot_time="10:00")["status"] == "ok"
    assert run_jev_post_persist(db, dataset_id=DATASET, snapshot_type="daily",
                                trading_date=DATE, slot_time="15:30")["status"] == "ok"
    skipped = run_jev_post_persist(db, dataset_id=DATASET, snapshot_type="five_minutes",
                                   trading_date=DATE, slot_time="09:35")
    assert skipped["skipped"] is True and skipped["reason"] == "snapshot_type_not_applicable"
    kinds = sorted(doc["kind"] for doc in db["hotlist_jev_sentiment"].rows)
    assert kinds == ["eod", "slot"]
