# -*- coding: utf-8 -*-
"""phase_monitor Mongo 落库测试：northstar/monthly 幂等 upsert（前端可见化数据源）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import phase_monitor_persistence


class FakeReplaceResult:
    matched_count = 0
    modified_count = 1
    upserted_id = "x"


class FakeCollection:
    def __init__(self) -> None:
        self.replace_calls: list[tuple[dict, dict, bool]] = []

    def replace_one(self, query: dict, doc: dict, upsert: bool = False) -> FakeReplaceResult:
        self.replace_calls.append((query, doc, upsert))
        return FakeReplaceResult()


class FakeDb:
    def __init__(self) -> None:
        self.phase_monitor = FakeCollection()

    def __getitem__(self, name: str) -> FakeCollection:
        assert name == "phase_monitor"
        return self.phase_monitor


def test_persist_northstar_upserts_with_key(monkeypatch) -> None:
    fake_db = FakeDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: fake_db,
    )
    report = {"meta": {"candidate": "sentiment_2b"}, "northstar": {"offense": {"pass": False}}}
    persisted = phase_monitor_persistence.persist_northstar(report, key="gen7-sentiment2b")
    query, doc, upsert = fake_db.phase_monitor.replace_calls[0]
    assert query == {"_id": "northstar:gen7-sentiment2b"}
    assert upsert is True
    assert doc["kind"] == "northstar"
    assert doc["key"] == "gen7-sentiment2b"
    assert doc["report"] == report
    assert "updatedAt" in doc
    assert persisted == "northstar:gen7-sentiment2b"


def test_persist_monthly_upserts_with_month(monkeypatch) -> None:
    fake_db = FakeDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: fake_db,
    )
    report = {"meta": {"month": "2026-09"}, "coverage": {"sentimentDocs": 230}}
    persisted = phase_monitor_persistence.persist_monthly(report)
    query, doc, upsert = fake_db.phase_monitor.replace_calls[0]
    assert query == {"_id": "monthly:2026-09"}
    assert upsert is True
    assert doc["kind"] == "monthly"
    assert doc["month"] == "2026-09"
    assert doc["report"] == report
    assert persisted == "monthly:2026-09"


def test_persist_never_raises_on_mongo_failure(monkeypatch) -> None:
    """研究链不因落库失败中断（本地 JSON 仍是即时产物）：连接异常吞掉并返回 None（fail-visible 打印）。"""

    class BrokenDb:
        def __getitem__(self, name: str) -> None:
            raise RuntimeError("mongo down")

    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: BrokenDb(),
    )
    assert phase_monitor_persistence.persist_monthly({"meta": {"month": "2026-10"}}) is None
