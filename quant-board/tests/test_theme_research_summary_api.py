# -*- coding: utf-8 -*-
"""GET /api/research/theme-summary 读口缓存合同（2026-09-12）。

该读口每次请求全量 ``load_frame_bundles(limit=200)`` + ThemeTrend 引擎重放（实测 8~18s），
前端 8s 超时必然 abort（用户看到 "signal is aborted without reason"）。修复：Redis TTL 缓存 +
快照依赖失效（与 ``GET /api/hotlist-sentiment/series`` 读口同口径）；
``available=False`` 的降级响应不缓存（fail-visible）。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.data.cache import snapshot_cache
from backend.data.cache.snapshot_cache import SnapshotRedisCache
from backend.main import app


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self._redis = redis
        self._ops: list[tuple[str, str, str]] = []

    def sadd(self, key: str, member: str) -> "FakePipeline":
        self._ops.append(("sadd", key, member))
        return self

    def expire(self, key: str, ttl: int) -> "FakePipeline":
        return self

    def execute(self) -> list:
        for _, key, member in self._ops:
            self._redis.sets.setdefault(key, set()).add(member)
        return []


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key: str):
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value

    def smembers(self, key: str):
        return set(self.sets.get(key, set()))

    def delete(self, *keys: str) -> None:
        for key in keys:
            self.store.pop(key, None)
            self.sets.pop(key, None)

    def pipeline(self, transaction: bool = False) -> FakePipeline:
        return FakePipeline(self)


class FakeRepo:
    def load_frame_bundles(self, dataset_id: str, snapshot_type: str = "half_hour", limit: int = 200):
        assert dataset_id == "dragonboard_live"
        return [{"tradingDate": "2026-09-10"}, {"tradingDate": "2026-09-11"}]


class FakeEngine:
    calls = 0

    def replay_sequence(self, frames):
        type(self).calls += 1
        return {
            "factors": [
                {"themeId": "AI", "themeName": "人工智能", "lifecycle": "mainline", "heatScore": 88}
            ],
            "qualityReport": {},
        }


@pytest.fixture()
def fake_cache(monkeypatch) -> FakeRedis:
    redis = FakeRedis()
    cache = SnapshotRedisCache(redis_client=redis, ttl_seconds=600, empty_ttl_seconds=10)
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: cache)
    return redis


def _install_fakes(monkeypatch) -> type[FakeEngine]:
    engine_cls = FakeEngine
    engine_cls.calls = 0
    monkeypatch.setattr("backend.main.create_repository", lambda db: FakeRepo())
    from backend.analysis.theme import trend as theme_trend

    monkeypatch.setattr(theme_trend, "ThemeTrendPythonEngine", engine_cls)
    return engine_cls


def test_theme_summary_replay_runs_once_then_cache_hits(monkeypatch, fake_cache) -> None:
    engine_cls = _install_fakes(monkeypatch)
    client = TestClient(app)

    first = client.get("/api/research/theme-summary?dataset_id=dragonboard_live&snapshot_type=half_hour")
    assert first.status_code == 200
    assert first.json()["available"] is True
    assert first.json()["mainlineThemes"][0]["themeName"] == "人工智能"
    assert engine_cls.calls == 1

    second = client.get("/api/research/theme-summary?dataset_id=dragonboard_live&snapshot_type=half_hour")
    assert second.status_code == 200
    # 第二次命中缓存：引擎不再重放（修复前每次请求全量重放 8~18s）
    assert engine_cls.calls == 1
    assert second.json()["cache"] == {"hit": True, "store": "redis"}
    assert second.json()["mainlineThemes"][0]["themeName"] == "人工智能"


def test_theme_summary_unavailable_is_not_cached(monkeypatch, fake_cache) -> None:
    engine_cls = _install_fakes(monkeypatch)

    class EmptyRepo:
        def load_frame_bundles(self, dataset_id: str, snapshot_type: str = "half_hour", limit: int = 200):
            return []

    monkeypatch.setattr("backend.main.create_repository", lambda db: EmptyRepo())
    client = TestClient(app)

    first = client.get("/api/research/theme-summary")
    assert first.status_code == 200
    assert first.json()["available"] is False
    assert first.json()["reason"] == "insufficient_frames"

    # 降级响应不缓存（fail-visible）：再次请求仍重试计算，且没有任何 key 被写入
    second = client.get("/api/research/theme-summary")
    assert second.status_code == 200
    assert second.json()["available"] is False
    assert engine_cls.calls == 0
    assert not fake_cache.store
