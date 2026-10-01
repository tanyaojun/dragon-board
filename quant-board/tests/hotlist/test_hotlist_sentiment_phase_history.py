# -*- coding: utf-8 -*-
"""phase-history 读口测试：EOD 序列按 sentiment_2b 映射相位（offense≥60/defense<60/unknown，2026-10-01 章程 Q1 边界 50→60）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from backend.main import app


class FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, key: str, direction: int) -> "FakeCursor":
        self._docs = sorted(self._docs, key=lambda d: d.get(key) or "", reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self._docs)


class FakeCollection:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs
        self.find_queries: list[dict] = []

    def find(self, query: dict, _projection: dict | None = None) -> FakeCursor:
        self.find_queries.append(query)
        return FakeCursor(self._docs)


class FakeDb:
    def __init__(self, docs: list[dict]) -> None:
        self.hotlist_sentiment = FakeCollection(docs)

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "hotlist_sentiment"
        return self.hotlist_sentiment


def _patch(monkeypatch, docs: list[dict]) -> None:
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: FakeDb(docs),
    )


def test_phase_history_maps_sentiment_2b(monkeypatch) -> None:
    docs = [
        {"tradingDate": "2026-09-27", "slotTime": "EOD", "emotionScore": {"score": 48.3}},
        {"tradingDate": "2026-09-26", "slotTime": "EOD", "emotionScore": {"score": 65.6}},
        {"tradingDate": "2026-09-25", "slotTime": "EOD", "emotionScore": None},
    ]
    _patch(monkeypatch, docs)
    client = TestClient(app)

    response = client.get("/api/hotlist-sentiment/phase-history")

    assert response.status_code == 200
    body = response.json()
    assert body["threshold"] == 60.0
    assert body["count"] == 3
    # 升序：09-25 → 09-26 → 09-27
    assert [d["tradingDate"] for d in body["days"]] == ["2026-09-25", "2026-09-26", "2026-09-27"]
    assert [d["phase"] for d in body["days"]] == ["unknown", "offense", "defense"]
    assert body["days"][1]["eodScore"] == 65.6
    # 查询只取 EOD
    assert body["datasetId"] == "dragonboard_live"


def test_phase_history_boundary_60(monkeypatch) -> None:
    """Q1 边界语义：60 含下沿（≥60 → offense），59.9 → defense。"""
    docs = [
        {"tradingDate": "2026-09-26", "slotTime": "EOD", "emotionScore": {"score": 60.0}},
        {"tradingDate": "2026-09-27", "slotTime": "EOD", "emotionScore": {"score": 59.9}},
    ]
    _patch(monkeypatch, docs)
    client = TestClient(app)

    response = client.get("/api/hotlist-sentiment/phase-history")

    assert response.status_code == 200
    body = response.json()
    assert [d["phase"] for d in body["days"]] == ["offense", "defense"]


def test_phase_history_empty_collection(monkeypatch) -> None:
    _patch(monkeypatch, [])
    client = TestClient(app)

    response = client.get("/api/hotlist-sentiment/phase-history")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0 and body["days"] == []
