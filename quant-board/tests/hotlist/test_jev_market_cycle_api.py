# -*- coding: utf-8 -*-
"""market-cycle 读口 + 单日复跑测试（第4课 P2，预登记 market-cycle-preregistration-20261112.md）。

全 monkeypatch，禁触真实 jev（AGENTS §1.2-7）。market_cycle 零 token 确定性轨道：
- GET 读口：单日全文档 + 近 N 日轻量序列（eventTypes 换算）；盘中回退 dateFallback。
- POST rerun：复用 omc.settle_day，**不受 jev token gate 限制**（与 relay-index/rerun 不同）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

import pytest

from backend.main import app

_D1, _D2, _D3 = "2026-11-09", "2026-11-10", "2026-11-11"


class Cursor(list):
    def sort(self, *args):
        key = args[0]
        reverse = len(args) > 1 and args[1] < 0
        list.sort(self, key=lambda r: str(r.get(key) or ""), reverse=reverse)
        return self

    def limit(self, n):
        return Cursor(self[:n])


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        q = query or {}

        def match(r):
            for k, v in q.items():
                if isinstance(v, dict):
                    for op, ov in v.items():
                        if op == "$ne" and r.get(k) == ov:
                            return False
                        if op == "$lt" and not (r.get(k) is not None and str(r.get(k)) < ov):
                            return False
                elif r.get(k) != v:
                    return False
            return True

        return Cursor([dict(r) for r in self.rows if match(r)])

    def find_one(self, query=None, projection=None, sort=None):
        found = self.find(query)
        if sort:
            for key, direction in reversed(sort):
                found = found.sort(key, direction)
        return found[0] if found else None


class FakeDb:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, k):
        return self.cols.setdefault(k, FakeCol())


def _doc(date, state="wzs"):
    return {"_id": f"{date}:MARKET_CYCLE", "tradingDate": date, "version": "v1",
            "status": "ok", "state": state, "daysInState": 2,
            "ceiling": {"maxBoard": 5, "threePlusN": 2, "prevWindowValidDays": 20},
            "events": [{"type": "highTolerance", "track": "main"}],
            "transition": {"trigger": "high_tolerance", "to": state},
            "reference": {"relayPhase": "divergence", "ruleStage": "高潮"}}


@pytest.fixture()
def client(monkeypatch):
    db = FakeDb({"hotlist_jev_market_cycle": FakeCol(
        [_doc(_D1, "loss"), _doc(_D2, "wzs"), _doc(_D3, "gain")])})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    return TestClient(app)


def test_no_date_returns_latest(client):
    r = client.get("/api/hotlist-jev/market-cycle")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["doc"]["tradingDate"] == _D3
    assert body["doc"]["state"] == "gain" and "dateFallback" not in body


def test_existing_date_no_fallback(client):
    r = client.get("/api/hotlist-jev/market-cycle", params={"date": _D2})
    body = r.json()
    assert body["doc"]["tradingDate"] == _D2 and "dateFallback" not in body


def test_intraday_falls_back(client):
    r = client.get("/api/hotlist-jev/market-cycle", params={"date": "2026-11-12"})
    body = r.json()
    assert body["ok"] is True and body["date"] == _D3
    assert body["dateFallback"] == {"requested": "2026-11-12", "served": _D3}


def test_series_event_types_transformed(client):
    r = client.get("/api/hotlist-jev/market-cycle", params={"days": 10})
    body = r.json()
    assert len(body["series"]) == 3
    for s in body["series"]:
        assert s["eventTypes"] == ["highTolerance"]   # events.type → eventTypes
        assert "events" not in s                       # 轻量序列不带全载荷
        assert s["state"] in ("loss", "wzs", "gain")


def test_rerun_zero_token_not_jev_gated(monkeypatch):
    # 零 token：无需 JEV token env，复用 omc.settle_day（不另写调用链）
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb({}))
    called = {}

    def fake_settle(db_, date, ds=None, **kw):
        called["date"], called["force"] = date, kw.get("force")
        return _doc(date, state="gain")

    monkeypatch.setattr("backend.operations.market_cycle.settle_day", fake_settle)
    client = TestClient(app)
    r = client.post("/api/hotlist-jev/market-cycle/rerun",
                    json={"date": _D2, "force": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["state"] == "gain" and body["events"] == 1
    assert called["date"] == _D2 and called["force"] is True


def test_rerun_bad_date(monkeypatch):
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb({}))
    client = TestClient(app)
    r = client.post("/api/hotlist-jev/market-cycle/rerun", json={"date": "  "})
    assert r.json()["errorCode"] == "bad_date"
