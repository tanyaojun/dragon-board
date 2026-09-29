# -*- coding: utf-8 -*-
"""槽位情绪文档读口（GET /api/hotlist-sentiment/slots）单测（2026-09-15）。

背景：槽位文档（slotTime="HH:MM"）此前只有回测 as-of provider 消费，无 HTTP 读口；
采集主链同步化后每槽即 golden 口径，前端「日内情绪轨迹」区块需要一个读口。
覆盖：升序返回当日全部槽位文档、缺省日期回落最新交易日、无数据结构化降级（fail-visible）。

缓存隔离：conftest 未禁 Redis，本文件所有用例把 ``snapshot_cache.get_snapshot_redis_cache``
替换为无客户端的 noop 缓存——断言只走 MongoDB 数据路径，且不向真实 Redis 写入测试响应
（60s TTL 内会污染前端读口）。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import pytest

from backend.data.cache import snapshot_cache
from tests.test_hotlist_sentiment_series_api import FakeMongoDb, _RecordingCache, _seed_frames


@pytest.fixture(autouse=True)
def _noop_redis_cache(monkeypatch):
    noop = snapshot_cache.SnapshotRedisCache(
        redis_client=None, ttl_seconds=60, empty_ttl_seconds=60
    )
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: noop)


def _slot_doc(trading_date: str, slot: str, stage: str = "启动") -> dict:
    return {
        "_id": f"dragonboard_live:half_hour:{trading_date}:{slot}",
        "datasetId": "dragonboard_live",
        "snapshotType": "half_hour",
        "tradingDate": trading_date,
        "snapshotId": f"half_hour:{trading_date}:{slot}",
        "slotTime": slot,
        "stage": stage,
        "riskLevel": "低",
        "confidence": 60,
        "summary": "",
        "metrics": {"topN": 2, "layers": {}, "comparison": {}, "limitEvidence": {}},
        "turnover": {"newEntries": [], "eliminated": []},
        "signals": [],
        "warnings": [],
    }


def test_slots_returns_today_slots_ascending(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    _seed_frames(fake_db, "dragonboard_live", "half_hour", ["2026-06-05"])
    fake_db["hotlist_sentiment"].rows = [
        _slot_doc("2026-06-05", "14:30"),
        _slot_doc("2026-06-05", "09:30"),
        _slot_doc("2026-06-05", "10:00"),
        # EOD 哨兵行与历史日槽位都不属于本读口
        {**_slot_doc("2026-06-05", "15:00"), "slotTime": "EOD", "_id": "dragonboard_live:half_hour:2026-06-05"},
        _slot_doc("2026-06-04", "15:00"),
    ]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    body = client.get(
        "/api/hotlist-sentiment/slots",
        params={"dataset_id": "dragonboard_live", "trading_date": "2026-06-05"},
    ).json()

    assert body["ok"] is True
    assert body["tradingDate"] == "2026-06-05"
    assert [item["slotTime"] for item in body["items"]] == ["09:30", "10:00", "14:30"]
    assert all(item.get("stage") == "启动" for item in body["items"])


def test_slots_defaults_to_latest_trading_date(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    _seed_frames(fake_db, "dragonboard_live", "half_hour", ["2026-06-04", "2026-06-05"])
    fake_db["hotlist_sentiment"].rows = [_slot_doc("2026-06-04", "15:00")]
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    body = client.get("/api/hotlist-sentiment/slots", params={"dataset_id": "dragonboard_live"}).json()

    # 最新交易日（06-05）无槽位文档 → 结构化空列表（fail-visible，不伪装）
    assert body["ok"] is True
    assert body["tradingDate"] == "2026-06-05"
    assert body["items"] == []


def test_slots_no_frames_returns_degraded(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.data.repositories import repository_factory

    fake_db = FakeMongoDb()
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: fake_db
    )
    client = TestClient(app)

    body = client.get("/api/hotlist-sentiment/slots", params={"dataset_id": "dragonboard_live"}).json()

    assert body["ok"] is False
    assert body["degraded"] is True
    assert body["reason"] == "no_snapshot_trading_date"


# ---------------------------------------------------------------------------
# 2026-09-24 阶段多帧确认字段：slots 读口未命中与缓存命中均保留确认字段（v2 缓存）。
# ---------------------------------------------------------------------------


def test_slots_keeps_confirmation_fields_on_miss_and_hit(monkeypatch):
    from backend.data.cache import snapshot_cache
    from backend.main import app

    fake_db = FakeMongoDb()
    _seed_frames(fake_db, "dragonboard_live", "half_hour", ["2026-06-05"])
    doc = _slot_doc("2026-06-05", "14:30", stage="退潮")
    doc["rawStage"] = "高潮"
    doc["stageConfirmState"] = {
        "pending": True,
        "pendingStage": "高潮",
        "pendingSince": "14:30",
        "confirmSlots": 2,
        "historyStatus": "complete",
    }
    fake_db["hotlist_sentiment"].rows.append(doc)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: fake_db,
    )
    cache = _RecordingCache()
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: cache)
    client = TestClient(app)

    first = client.get("/api/hotlist-sentiment/slots?dataset_id=dragonboard_live")
    assert first.status_code == 200
    assert first.json()["cache"]["hit"] is False
    target = [item for item in first.json()["items"] if item.get("slotTime") == "14:30"][0]
    assert target["rawStage"] == "高潮"
    assert target["stageConfirmState"]["pendingSince"] == "14:30"

    second = client.get("/api/hotlist-sentiment/slots?dataset_id=dragonboard_live")
    assert second.status_code == 200
    assert second.json()["cache"]["hit"] is True
    target2 = [item for item in second.json()["items"] if item.get("slotTime") == "14:30"][0]
    assert target2["rawStage"] == "高潮"
    assert target2["stageConfirmState"]["pendingStage"] == "高潮"
