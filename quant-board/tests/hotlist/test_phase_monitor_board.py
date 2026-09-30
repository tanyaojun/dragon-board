# -*- coding: utf-8 -*-
"""phase-monitor board 读口测试：Mongo phase_monitor 集合 → northstar + months 装配。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from backend.main import app


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def find(self, _query: dict) -> FakeCursor:
        return FakeCursor(self._docs)


class FakeDb:
    def __init__(self, docs: list[dict]) -> None:
        self.phase_monitor = FakeCollection(docs)

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "phase_monitor"
        return self.phase_monitor


def _patch(monkeypatch, docs: list[dict]) -> None:
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(docs),
    )


def test_board_assembles_northstar_and_sorted_months(monkeypatch) -> None:
    docs = [
        {"_id": "monthly:2026-09", "kind": "monthly", "month": "2026-09",
         "report": {"meta": {"month": "2026-09"}, "supervision": {"northstar": {"pass": {"offense": False, "defense": True}}}}, "updatedAt": "t2"},
        {"_id": "northstar:gen7-sentiment2b", "kind": "northstar", "key": "gen7-sentiment2b",
         "report": {"meta": {"candidate": "sentiment_2b"}, "fullWindow": {"maxDD": -0.0487}}, "updatedAt": "t1"},
        {"_id": "monthly:2026-10", "kind": "monthly", "month": "2026-10", "report": {"meta": {"month": "2026-10"}}, "updatedAt": "t3"},
    ]
    _patch(monkeypatch, docs)
    client = TestClient(app)

    response = client.get("/api/phase-monitor/board")

    assert response.status_code == 200
    body = response.json()
    assert body["northstar"]["key"] == "gen7-sentiment2b"
    assert body["northstar"]["report"]["fullWindow"]["maxDD"] == -0.0487
    assert [m["month"] for m in body["months"]] == ["2026-09", "2026-10"]
    assert body["count"] == 2


def test_board_empty_collection_fail_visible(monkeypatch) -> None:
    _patch(monkeypatch, [])
    client = TestClient(app)

    response = client.get("/api/phase-monitor/board")

    assert response.status_code == 200
    body = response.json()
    assert body["northstar"] is None
    assert body["northstarMissingReason"]  # 结构化缺失原因，不伪造
    assert body["months"] == [] and body["count"] == 0
