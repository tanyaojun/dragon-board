# -*- coding: utf-8 -*-
"""日级 EOD 情绪「单日复跑」写口测试（2026-10-19 工作台「重跑」按钮后端）。

全 monkeypatch，禁触真实 jev 调用（AGENTS §1.2-7）：`compute_and_upsert_for_day` 被替换为
直接写假库的 stub，本测试只验路由适配 / token 前置 / snapshotType 透传 / 返回形状。

fail-visible 约定：重跑失败照常返回 degraded/no_data 文档的 errorCode/errorDetail（不伪造 ok）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

from backend.main import app

_DATE = "2026-10-19"
_ROUTE = "/api/hotlist-jev/eod/rerun"
_DOC_ID = f"dragonboard_live:half_hour:{_DATE}:EOD"


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find_one(self, query=None, projection=None, sort=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in (query or {}).items()):
                return dict(r)
        return None

    def replace_one(self, query, doc, upsert=False):
        for i, r in enumerate(self.rows):
            if all(r.get(k) == v for k, v in (query or {}).items()):
                self.rows[i] = dict(doc)
                return
        self.rows.append(dict(doc))


class FakeDb:
    def __init__(self, cols=None):
        self.cols = cols or {}

    def __getitem__(self, k):
        return self.cols.setdefault(k, FakeCol())


@pytest.fixture()
def client(monkeypatch):
    db = FakeDb({"hotlist_jev_sentiment": FakeCol()})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "test-key")
    return TestClient(app), db


def test_eod_rerun_calls_production_entry_and_returns_doc(monkeypatch, client):
    c, db = client
    seen: dict = {}

    def fake_compute(db_, *, dataset_id, trading_date, snapshot_type="half_hour",
                     origin="collector", dry_run=False, **k):
        seen.update(dataset_id=dataset_id, trading_date=trading_date,
                    snapshot_type=snapshot_type, origin=origin)
        doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:EOD"
        db_.cols["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id},
            {"_id": doc_id, "kind": "eod", "tradingDate": trading_date, "slotTime": "EOD",
             "snapshotType": snapshot_type, "datasetId": dataset_id, "status": "ok",
             "scores": {"day_temperature": 55.9}, "narrativeRaw": "SECRET"})
        return {"written": True, "status": "ok"}

    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_day", fake_compute)
    r = c.post(_ROUTE, json={"tradingDate": _DATE})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["status"] == "ok"
    assert body["eod"]["scores"]["day_temperature"] == 55.9
    # 复用生产入口，origin=manual（与 /evaluate 手动补评同源）
    assert seen == {"dataset_id": "dragonboard_live", "trading_date": _DATE,
                    "snapshot_type": "half_hour", "origin": "manual"}


def test_eod_rerun_passes_snapshot_type(monkeypatch, client):
    c, db = client
    seen: dict = {}
    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_day",
        lambda db_, *, dataset_id, trading_date, snapshot_type="half_hour", **k:
        seen.update(snapshot_type=snapshot_type) or
        db_.cols["hotlist_jev_sentiment"].replace_one(
            {"_id": f"{dataset_id}:{snapshot_type}:{trading_date}:EOD"},
            {"_id": f"{dataset_id}:{snapshot_type}:{trading_date}:EOD", "kind": "eod",
             "status": "ok", "scores": {"day_temperature": 40.0}}))
    body = c.post(_ROUTE, json={"tradingDate": _DATE, "snapshotType": "quarter_hour"}).json()
    assert seen["snapshot_type"] == "quarter_hour" and body["ok"] is True


def test_eod_rerun_degraded_passthrough_not_faked(monkeypatch, client):
    c, db = client

    def fake_compute(db_, *, dataset_id, trading_date, snapshot_type="half_hour", **k):
        doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:EOD"
        db_.cols["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id},
            {"_id": doc_id, "kind": "eod", "status": "degraded",
             "errorCode": "http_error", "errorDetail": "network: URLError: SSL EOF",
             "answers": None, "scores": None})
        return {"written": True, "status": "degraded", "errorCode": "http_error"}

    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_day", fake_compute)
    body = c.post(_ROUTE, json={"tradingDate": _DATE}).json()
    assert body["ok"] is False and body["status"] == "degraded"
    assert body["errorCode"] == "http_error" and "SSL EOF" in body["errorDetail"]


def test_eod_rerun_not_written_guard(monkeypatch, client):
    c, db = client
    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_day",
        lambda *a, **k: {"written": False})
    body = c.post(_ROUTE, json={"tradingDate": _DATE}).json()
    assert body["ok"] is False and body["errorCode"] == "not_written"


def test_eod_rerun_requires_token_and_date(monkeypatch, client):
    c, db = client
    called: list = []
    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_day",
        lambda *a, **k: called.append(1))
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    assert c.post(_ROUTE, json={"tradingDate": _DATE}).json()["errorCode"] == "missing_token"
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "test-key")
    assert c.post(_ROUTE, json={"tradingDate": "  "}).json()["errorCode"] == "bad_date"
    assert not called


def test_eod_rerun_route_is_post_only(client):
    c, db = client
    assert c.get(_ROUTE).status_code == 405