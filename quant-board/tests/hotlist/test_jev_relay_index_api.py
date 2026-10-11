# -*- coding: utf-8 -*-
"""relay-index 读口测试（2026-10-11 毒带观察 chip 原料：series join EOD day_temperature）。

全 monkeypatch，禁触真实 jev 调用（AGENTS §1.2-7）。join 语义：
- EOD ok 文档存在 → dayTemperature=round(温度,1)
- 缺 EOD / 温度字段非数值 → dayTemperature=None 原样透传（fail-visible，不伪造）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

from backend.main import app

_D1, _D2, _D3 = "2026-09-22", "2026-09-23", "2026-09-24"


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
                        if op == "$in" and r.get(k) not in ov:
                            return False
                        if op == "$ne" and r.get(k) == ov:
                            return False
                elif r.get(k) != v:
                    return False
            return True
        excl = {k for k, v in (projection or {}).items() if v == 0}
        return Cursor([{k: v for k, v in dict(r).items() if k not in excl}
                       for r in self.rows if match(r)])

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


def _relay(date, idx):
    return {"_id": f"{date}:RELAY", "tradingDate": date, "status": "ok",
            "questionSetVersion": "v3", "relayIndex": idx, "relayPhase": "divergence",
            "narrative": "SECRET", "usage": {"input_tokens": 1, "output_tokens": 2},
            "computedAt": f"{date}T18:00:00"}


@pytest.fixture()
def client(monkeypatch):
    db = FakeDb({
        "hotlist_jev_relay_index": FakeCol(
            [_relay(_D1, 46.3), _relay(_D2, 64.4), _relay(_D3, 51.1)]),
        # EOD：D1 有 ok 温度（58.36，不取整原值透传）；D2 degraded（99 不得泄漏）；
        # D3 ok 但 scores 缺 day_temperature 字段 → 同样 None（三路降级全锁）
        "hotlist_jev_sentiment": FakeCol([
            {"_id": f"{_D1}:eod", "tradingDate": _D1, "kind": "eod", "status": "ok",
             "scores": {"day_temperature": 58.36}},
            {"_id": f"{_D2}:eod", "tradingDate": _D2, "kind": "eod", "status": "degraded",
             "scores": {"day_temperature": 99.0}},
            {"_id": f"{_D3}:eod", "tradingDate": _D3, "kind": "eod", "status": "ok",
             "scores": {}},
        ]),
    })
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    return TestClient(app)


def test_relay_index_joins_day_temperature(client):
    r = client.get("/api/hotlist-jev/relay-index")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    series = {s["tradingDate"]: s for s in body["series"]}
    assert series[_D1]["dayTemperature"] == 58.36
    # 缺 ok EOD → None 原样透传（degraded 温度 99 不得泄漏成假温度）
    assert series[_D2]["dayTemperature"] is None
    # ok EOD 但缺 day_temperature 字段 → None（不伪造）
    assert series[_D3]["dayTemperature"] is None
    # day 文档（最新日）同样携带
    assert body["day"]["dayTemperature"] is None
    # 投影边界：narrative 不出读口
    assert "narrative" not in series[_D1]


def test_relay_index_without_any_eod(monkeypatch):
    """全库无 EOD 文档：join 静默降级 None，读口不报错（fail-visible）。"""
    db = FakeDb({"hotlist_jev_relay_index": FakeCol([_relay(_D1, 46.3), _relay(_D2, 64.4)])})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    client = TestClient(app)
    r = client.get("/api/hotlist-jev/relay-index", params={"days": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and len(body["series"]) == 2
    assert all(s["dayTemperature"] is None for s in body["series"])
    assert "dayTemperatureDegraded" not in body


def test_relay_index_join_failure_degrades_field_not_route(monkeypatch):
    """EOD 集合查询异常：温度字段整体降级 None + 结构化标记，relay 序列照常返回（§4.0 部分失败不阻断）。"""
    class BoomCol(FakeCol):
        def find(self, query=None, projection=None):
            if query and "scores.day_temperature" in (projection or {}):
                raise RuntimeError("mongo down")
            return super().find(query, projection)

    db = FakeDb({"hotlist_jev_relay_index": FakeCol([_relay(_D1, 46.3)])})
    db.cols["hotlist_jev_sentiment"] = BoomCol([])
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    client = TestClient(app)
    r = client.get("/api/hotlist-jev/relay-index")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and len(body["series"]) == 1
    assert body["series"][0]["dayTemperature"] is None
    assert "dayTemperatureDegraded" in body
