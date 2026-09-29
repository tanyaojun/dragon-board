# -*- coding: utf-8 -*-
"""hotlist series 读口缓存 + analyze 全字段落库 + 并行回填（2026-09-10 用户要求）。

三个独立断言面：

1. **读口走 Redis TTL 缓存**：命中标注 ``cache.hit``；成功响应才缓存并注册
   ``...:snapshot:index:dataset:<dataset_id>`` 依赖；降级响应**不入缓存**（fail-visible）。
2. **analyze 全字段落库**：四信号（共振/趋势/横截面/量价）之外，technical / risk /
   strategy / executionStrategy / jump / decision / themeMomentum 也必须落库。
3. **全量回填**：``backfill_frames`` 支持 ``workers`` 并行，串行与 worker 共用
   ``_backfill_single``（禁止另写一套组装）。
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.api import hotlist_routes
from backend.core.settings import get_settings
from backend.data.cache import snapshot_cache
from backend.main import app
from backend.services.snapshot_analysis_backfill import backfill_frames
from backend.services.snapshot_analysis_service import (
    ANALYSIS_PERSIST_FIELDS,
    persist_snapshot_analysis,
)


class FakeCache:
    def __init__(self) -> None:
        self.responses: dict[str, dict[str, Any]] = {}
        self.dependencies: dict[str, list[str]] = {}
        self.invalidated: list[list[str]] = []
        self.generations: dict[str, int] = {}
        self.last_ttl: int | None = None

    def get_response(self, key: str) -> dict[str, Any] | None:
        return self.responses.get(key)

    def set_response(self, key: str, response: dict[str, Any], *, ttl_seconds: int | None = None) -> None:
        self.responses[key] = response
        self.last_ttl = ttl_seconds

    def register_dependencies(self, response_key: str, index_keys: list[str]) -> None:
        self.dependencies[response_key] = list(index_keys)

    def invalidate_indexes(self, index_keys: list[str]) -> None:
        self.invalidated.append(list(index_keys))

    def get_generation(self, key: str) -> int:
        return int(self.generations.get(key, 0))

    def bump_generation(self, key: str) -> int:
        self.generations[key] = int(self.generations.get(key, 0)) + 1
        return self.generations[key]


class FakeRepo:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def upsert_snapshot_analysis(
        self, dataset_id: str, snapshot_id: str, code: str, payload: dict[str, Any]
    ) -> bool:
        self.calls.append(
            {"dataset_id": dataset_id, "snapshot_id": snapshot_id, "code": code, "payload": payload}
        )
        return True


# ── 1. 读口缓存 ──────────────────────────────────────────────────────────────


def test_series_cache_key_is_versioned_and_scoped() -> None:
    key = hotlist_routes._series_cache_key("dragonboard_live", "half_hour", 10)
    # 2026-09-24 阶段多帧确认：响应合同新增确认字段，缓存版本随共享常量升 v2
    assert key.endswith(f":{hotlist_routes._HOTLIST_SENTIMENT_CACHE_VERSION}")
    assert key.endswith(":v2")
    assert "hotlist:sentiment:series:dragonboard_live:half_hour:10" in key
    assert hotlist_routes._series_cache_key("dragonboard_live", "half_hour", 10) == key
    assert hotlist_routes._series_cache_key("dragonboard_live", "half_hour", 3) != key
    assert hotlist_routes._series_cache_key("other_dataset", "half_hour", 10) != key


def test_series_route_serves_from_cache_and_marks_hit(monkeypatch) -> None:
    fake = FakeCache()
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: fake)
    key = hotlist_routes._series_cache_key("dragonboard_live", "half_hour", 3)
    fake.responses[key] = {
        "ok": True,
        "items": [{"tradingDate": "2026-09-10"}],
        "cache": {"hit": False, "store": "mongodb"},
    }

    client = TestClient(app)
    response = client.get(
        "/api/hotlist-sentiment/series?dataset_id=dragonboard_live&snapshot_type=half_hour&days=3"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cache"] == {"hit": True, "store": "redis"}
    assert body["items"] == [{"tradingDate": "2026-09-10"}]


def test_series_route_caches_success_and_registers_dataset_index(monkeypatch) -> None:
    fake = FakeCache()
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: fake)
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )

    class FakeService:
        def __init__(self, _db: Any) -> None:
            pass

        def ensure_series(self, dataset_id: str, snapshot_type: str, days: int) -> dict[str, Any]:
            return {"ok": True, "items": [{"tradingDate": "2026-09-10"}]}

    monkeypatch.setattr(
        "backend.services.theme.hotlist_sentiment_compute.HotListSentimentComputeService",
        FakeService,
    )

    client = TestClient(app)
    response = client.get("/api/hotlist-sentiment/series?days=3")
    body = response.json()

    assert body["cache"] == {"hit": False, "store": "mongodb"}
    key = hotlist_routes._series_cache_key("dragonboard_live", "half_hour", 3)
    assert fake.responses[key]["ok"] is True
    assert fake.last_ttl == get_settings().hotlist_sentiment_cache_ttl_seconds
    # 依赖口径必须与实际失效口径一致（任何快照写入 / hotlist 重算都失效该 key）
    assert fake.dependencies[key] == snapshot_cache.build_snapshot_cache_index_keys(
        prefix=get_settings().redis_key_prefix,
        dataset_id="dragonboard_live",
    )


def test_series_route_does_not_cache_degraded_response(monkeypatch) -> None:
    fake = FakeCache()
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: fake)

    def _mongo_down() -> Any:
        raise RuntimeError("mongo down")

    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        _mongo_down,
    )

    client = TestClient(app)
    response = client.get("/api/hotlist-sentiment/series?days=3")
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is False
    assert body["degraded"] is True
    assert "mongodb_unavailable" in body["reason"]
    # fail-visible：降级结果不得被缓存成"看起来正常的历史序列"
    assert fake.responses == {}
    assert fake.dependencies == {}


def test_hotlist_write_path_invalidates_series_cache_index() -> None:
    source = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "services"
        / "theme"
        / "hotlist_sentiment_compute.py"
    ).read_text(encoding="utf-8")

    assert "_invalidate_hotlist_sentiment_cache(dataset_id)" in source
    assert "invalidate_indexes(" in source


# ── 2. analyze 全字段落库 ────────────────────────────────────────────────────


def test_analysis_persist_fields_cover_four_signals_and_full_toplevel() -> None:
    # 四信号：共振 resonance / 趋势 observation.rankTrend / 横截面 observation.crossSection
    # / 量价 observation.volumePrice —— 前两者以顶层字段落库，后两者在 observation 内。
    for field in (
        "observation",
        "resonance",
        "technical",
        "risk",
        "strategy",
        "executionStrategy",
        "jump",
        "decision",
        "cycle",
        "meta",
        "displayStatus",
        "themeMomentum",
    ):
        assert field in ANALYSIS_PERSIST_FIELDS, field


def test_persist_snapshot_analysis_writes_all_top_level_fields() -> None:
    repo = FakeRepo()
    analysis = {field: {"marker": field} for field in ANALYSIS_PERSIST_FIELDS}
    analysis["cycle"] = {"stage": "启动"}

    count = persist_snapshot_analysis(
        repo,
        "ds",
        "half_hour:2026-09-10:15:30",
        [{"code": "600000", "analysis": analysis}],
    )

    assert count == 1
    payload = repo.calls[0]["payload"]
    assert set(payload) == set(ANALYSIS_PERSIST_FIELDS)
    assert payload["cycle"] == {"stage": "启动"}
    assert payload["technical"] == {"marker": "technical"}
    assert payload["risk"] == {"marker": "risk"}
    assert payload["jump"] == {"marker": "jump"}
    assert payload["decision"] == {"marker": "decision"}
    assert payload["executionStrategy"] == {"marker": "executionStrategy"}
    assert payload["themeMomentum"] == {"marker": "themeMomentum"}


def test_persist_snapshot_analysis_keeps_observation_dict_on_missing() -> None:
    repo = FakeRepo()
    persist_snapshot_analysis(repo, "ds", "snap", [{"code": "600000", "analysis": {}}])

    payload = repo.calls[0]["payload"]
    # observation 缺失时保持空 dict（读口/join 层按 dict 访问，不得变成 None）
    assert payload["observation"] == {}
    assert payload["cycle"] is None


# ── 3. 全量回填（并行） ──────────────────────────────────────────────────────


def test_backfill_frames_defaults_to_serial_dry_run() -> None:
    params = inspect.signature(backfill_frames).parameters
    assert params["workers"].default == 1
    assert params["apply"].default is False


def test_parallel_backfill_shares_single_frame_implementation() -> None:
    source = (
        Path(__file__).resolve().parent.parent
        / "backend"
        / "services"
        / "snapshot_analysis_backfill.py"
    ).read_text(encoding="utf-8")

    # spawn context：Windows/Linux 行为一致
    assert 'multiprocessing.get_context("spawn")' in source
    # 子进程自建 Mongo 连接（连接对象不可跨进程）
    assert "repository_factory.get_runtime_mongodb_database()" in source
    # 串行与 worker 共用单帧实现：定义 1 处 + 调用 2 处
    assert source.count("_backfill_single(") >= 3
