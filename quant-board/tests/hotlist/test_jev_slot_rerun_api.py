# -*- coding: utf-8 -*-
"""jev 帧级槽位情绪「单槽复跑」写口测试（2026-10-19 工作台「重跑」按钮后端）。

全 monkeypatch，禁触真实 jev 调用（AGENTS §1.2-7）：`compute_and_upsert_for_slot` 被替换为
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

_DATE, _SLOT = "2026-10-19", "10:00"
_ROUTE = "/api/hotlist-jev/slots/rerun"
_DOC_ID = f"dragonboard_live:half_hour:{_DATE}:{_SLOT}"


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


def test_slot_rerun_passes_snapshot_type_and_returns_doc(monkeypatch, client):
    c, db = client
    seen: dict = {}

    def fake_compute(db_, *, dataset_id, trading_date, slot_time,
                     snapshot_type="half_hour", origin="collector", dry_run=False, **k):
        seen.update(dataset_id=dataset_id, trading_date=trading_date, slot_time=slot_time,
                    snapshot_type=snapshot_type, origin=origin)
        doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:{slot_time}"
        db_.cols["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id},
            {"_id": doc_id, "kind": "slot", "tradingDate": trading_date, "slotTime": slot_time,
             "snapshotType": snapshot_type, "datasetId": dataset_id, "status": "ok",
             "scores": {"temperature": 61.2}, "narrativeRaw": "SECRET"})
        return {"written": True, "status": "ok"}

    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_slot", fake_compute)
    r = c.post(_ROUTE, json={"tradingDate": _DATE, "slotTime": _SLOT,
                             "snapshotType": "quarter_hour"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["status"] == "ok"
    # 返回完整槽文档（reuse /series 形状），供前端子视图复用
    assert body["slot"]["scores"]["temperature"] == 61.2
    # snapshotType 必须透传（防 quarter_hour 槽被按 half_hour 重判）
    assert seen == {"dataset_id": "dragonboard_live", "trading_date": _DATE,
                    "slot_time": _SLOT, "snapshot_type": "quarter_hour", "origin": "manual"}


def test_slot_rerun_defaults_half_hour(monkeypatch, client):
    c, db = client
    seen: dict = {}
    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_slot",
        lambda db_, *, dataset_id, trading_date, slot_time, snapshot_type="half_hour", **k:
        seen.update(snapshot_type=snapshot_type) or
        db_.cols["hotlist_jev_sentiment"].replace_one(
            {"_id": _DOC_ID},
            {"_id": _DOC_ID, "kind": "slot", "status": "ok", "scores": {"temperature": 50.0}}))
    body = c.post(_ROUTE, json={"tradingDate": _DATE, "slotTime": _SLOT}).json()
    assert seen["snapshot_type"] == "half_hour" and body["ok"] is True


def test_slot_rerun_degraded_passthrough_not_faked(monkeypatch, client):
    c, db = client

    def fake_compute(db_, *, dataset_id, trading_date, slot_time, snapshot_type="half_hour", **k):
        doc_id = f"{dataset_id}:{snapshot_type}:{trading_date}:{slot_time}"
        db_.cols["hotlist_jev_sentiment"].replace_one(
            {"_id": doc_id},
            {"_id": doc_id, "kind": "slot", "status": "degraded",
             "errorCode": "http_error", "errorDetail": "network: URLError: SSL EOF",
             "answers": None, "scores": None})
        return {"written": True, "status": "degraded", "errorCode": "http_error"}

    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_slot", fake_compute)
    body = c.post(_ROUTE, json={"tradingDate": _DATE, "slotTime": _SLOT}).json()
    assert body["ok"] is False and body["status"] == "degraded"
    assert body["errorCode"] == "http_error" and "SSL EOF" in body["errorDetail"]


def test_slot_rerun_not_written_guard(monkeypatch, client):
    """计算入口未落文档（异常路径）→ not_written，不伪装成功。"""
    c, db = client
    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_slot",
        lambda *a, **k: {"written": False})
    body = c.post(_ROUTE, json={"tradingDate": _DATE, "slotTime": _SLOT}).json()
    assert body["ok"] is False and body["errorCode"] == "not_written"


def test_slot_rerun_requires_token_and_slot(monkeypatch, client):
    c, db = client
    called: list = []
    monkeypatch.setattr(
        "backend.services.jev.jev_sentiment_compute.compute_and_upsert_for_slot",
        lambda *a, **k: called.append(1))
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    assert c.post(_ROUTE, json={"tradingDate": _DATE, "slotTime": _SLOT}).json()["errorCode"] \
        == "missing_token"
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "test-key")
    # 缺 slotTime → bad_slot（同样不调用模型）
    assert c.post(_ROUTE, json={"tradingDate": _DATE, "slotTime": "  "}).json()["errorCode"] \
        == "bad_slot"
    assert not called


def test_slot_rerun_route_is_post_only(client):
    c, db = client
    assert c.get(_ROUTE).status_code == 405