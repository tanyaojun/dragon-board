# -*- coding: utf-8 -*-
"""竞价龙头读口/重跑 API 合同测试（零 jev / 零网络；FakeDb 注入）。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.api import hotlist_jev_auction_routes as R
from backend.data.repositories import repository_factory

DATE = "2026-11-13"


class FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def find(self, query=None, projection=None):
        out = []
        for d in self.docs.values():
            ok = True
            for k, v in (query or {}).items():
                val = d.get(k)
                if isinstance(v, dict):
                    if "$gte" in v and not (val is not None and val >= v["$gte"]):
                        ok = False
                    if "$lte" in v and not (val is not None and val <= v["$lte"]):
                        ok = False
                elif val != v:
                    ok = False
            if ok:
                out.append(dict(d))
        return FakeCursor(out)

    def find_one(self, query=None, projection=None):
        for d in self.find(query):
            return d
        return None


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


@pytest.fixture()
def client(monkeypatch):
    db = FakeDb()
    col = db[R.COLLECTION]
    col.docs[f"{DATE}:603135"] = {
        "_id": f"{DATE}:603135", "tradingDate": DATE, "docKind": "leader",
        "code": "603135", "name": "中重科技", "board": "机器人", "auctionPct": 3.0,
        "auctionSealToday": "mid_45_65", "auctionSealProbabilities": {"mid_45_65": 0.6},
        "status": "ok", "questionSetVersion": "vA1", "narrative": "叙事全文",
        "questionsRaw": {"auction_leader_seal_today": {}},
        "answers": {"auction_leader_seal_today": {"choice": "mid_45_65", "confidence": 0.7}},
        "outcomeSealedToday": None, "computedAt": "2026-11-13T09:26:00.000"}
    col.docs[f"{DATE}:board:机器人"] = {
        "_id": f"{DATE}:board:机器人", "tradingDate": DATE, "docKind": "sector",
        "board": "机器人", "status": "ok",
        "answers": {"theme_speculation_depth": {"choice": "fermenting"},
                    "theme_continuation": {"choice": "weak_extend"}}}
    db[R.LIVE_COLLECTION].docs[DATE] = {
        "_id": DATE, "auctionPush": {"stocks": [
            {"code": "603135", "name": "中重科技", "board": "机器人", "pct": 3.0},
            {"code": "600327", "name": "大东方", "board": "大消费", "pct": -8.64}]}}
    monkeypatch.setattr(repository_factory, "get_runtime_mongodb_database", lambda: db)
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(R.router)
    return TestClient(app), db


def test_get_single_date_merges_sector_and_roster(client):
    c, db = client
    r = c.get("/api/hotlist-jev/auction-leaders", params={"date": DATE})
    doc = r.json()
    assert doc["ok"] and not doc.get("no_data")
    rows = {x["code"]: x for x in doc["leaders"]}
    assert rows["603135"]["choice"] == "mid_45_65"
    assert rows["603135"]["themeSpeculationDepth"] == "fermenting"
    assert rows["603135"]["labelMissing"] is False
    assert rows["600327"]["labelMissing"] is True     # 推送 roster 缺档行披露
    assert doc["nodeFilter"]["labelMissingRows"] == 1
    assert doc["sectorCount"] == 1


def test_get_with_narrative(client):
    c, db = client
    doc = c.get("/api/hotlist-jev/auction-leaders",
                params={"date": DATE, "with_narrative": 1}).json()
    row = next(x for x in doc["leaders"] if x["code"] == "603135")
    assert row["narrative"] == "叙事全文"
    assert "auction_leader_seal_today" in row["questionsRaw"]


def test_get_range_and_no_data(client):
    c, db = client
    doc = c.get("/api/hotlist-jev/auction-leaders",
                params={"start": "2026-11-01", "end": "2026-11-30"}).json()
    assert doc["ok"] and len(doc["leaders"]) == 2
    empty = c.get("/api/hotlist-jev/auction-leaders", params={"date": "2026-11-12"}).json()
    assert empty["no_data"] is True


def test_rerun_missing_token(client):
    c, db = client
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"})
    assert r.json()["errorCode"] == "missing_token"


def test_rerun_bad_payload(client):
    c, db = client
    import os
    os.environ["JEV_CF_TOKEN"] = "x"
    try:
        r = c.post("/api/hotlist-jev/auction-leaders/rerun", json={"date": "", "code": ""})
        assert r.json()["errorCode"] == "bad_payload"
    finally:
        del os.environ["JEV_CF_TOKEN"]

def test_rerun_success_summary_and_force(client, monkeypatch):
    c, db = client
    import backend.operations.auction_leader_label as AL
    monkeypatch.setenv("JEV_CF_TOKEN", "x")
    seen = {}

    def fake_run(date, **kw):
        seen.update(kw)
        db[AL.COLLECTION].docs[f"{date}:603135"]["computedAt"] = "2026-11-13T09:30:00.000"
        return {"leaders": 1, "okCount": 2, "degraded": 0, "tokensUsed": 240}

    monkeypatch.setattr(AL, "run", fake_run)
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"}).json()
    assert r["ok"] and r["summary"]["labeled"] == 1 and r["summary"]["okCount"] == 2
    assert seen["force"] is True and seen["codes"] == {"603135"}
    assert seen["sample_origin"] == "live"


def test_rerun_not_rerun_when_computedAt_stale(client, monkeypatch):
    c, db = client
    import backend.operations.auction_leader_label as AL
    monkeypatch.setenv("JEV_CF_TOKEN", "x")
    monkeypatch.setattr(AL, "run", lambda date, **kw: {"leaders": 0})
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"}).json()
    assert r["errorCode"] == "not_rerun"


def test_rerun_not_written(client, monkeypatch):
    c, db = client
    import backend.operations.auction_leader_label as AL
    monkeypatch.setenv("JEV_CF_TOKEN", "x")

    def fake_run(date, **kw):
        db[AL.COLLECTION].docs.pop(f"{date}:603135", None)
        return {"leaders": 0}

    monkeypatch.setattr(AL, "run", fake_run)
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"}).json()
    assert r["errorCode"] == "not_written"


def test_rerun_backfill_origin_passthrough(client, monkeypatch):
    c, db = client
    import backend.operations.auction_leader_label as AL
    monkeypatch.setenv("JEV_CF_TOKEN", "x")
    db[AL.COLLECTION].docs[f"{DATE}:603135"]["sampleOrigin"] = "backfill"
    seen = {}

    def fake_run(date, **kw):
        seen.update(kw)
        db[AL.COLLECTION].docs[f"{date}:603135"]["computedAt"] = "2026-11-13T09:31:00.000"
        return {"leaders": 1, "okCount": 1}

    monkeypatch.setattr(AL, "run", fake_run)
    r = c.post("/api/hotlist-jev/auction-leaders/rerun",
               json={"date": DATE, "code": "603135"}).json()
    assert r["ok"] and seen["sample_origin"] == "backfill"


def test_no_param_500_cap_truncated(client):
    c, db = client
    col = db[R.COLLECTION]
    col.docs.pop(f"{DATE}:board:机器人", None)   # sector 档占帽会让 leader 窗=499
    for i in range(501):
        code = f"{i:06d}"
        col.docs[f"{DATE}:{code}"] = {
            "_id": f"{DATE}:{code}", "tradingDate": DATE, "docKind": "leader",
            "code": code, "name": f"股{i}", "board": "机器人", "status": "ok"}
    doc = c.get("/api/hotlist-jev/auction-leaders").json()
    assert doc["truncated"] is True
    labeled = [r for r in doc["leaders"] if not r.get("labelMissing")]
    assert len(labeled) == 500
