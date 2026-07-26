from __future__ import annotations

from backend.data.snapshot_cache import (
    SnapshotCacheKeyBuilder,
    SnapshotRedisCache,
    build_snapshot_cache_generation_key,
    build_snapshot_cache_index_keys,
    create_snapshot_redis_client,
)


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.expires: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key: str) -> str | None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.values.get(key)

    def setex(self, key: str, ttl: int, value: str) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.values[key] = value
        self.ttls[key] = ttl

    def sadd(self, key: str, *values: str) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.sets.setdefault(key, set()).update(values)

    def expire(self, key: str, ttl: int) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.expires[key] = ttl

    def smembers(self, key: str) -> set[str]:
        if self.fail:
            raise RuntimeError("redis unavailable")
        return set(self.sets.get(key, set()))

    def delete(self, *keys: str) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        for key in keys:
            self.values.pop(key, None)
            self.ttls.pop(key, None)
            self.sets.pop(key, None)

    def incr(self, key: str) -> int:
        if self.fail:
            raise RuntimeError("redis unavailable")
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value


def test_snapshot_cache_key_uses_namespace_and_resolved_dataset() -> None:
    builder = SnapshotCacheKeyBuilder(prefix="hellobiga:dragon-board:test")

    key = builder.response_key(
        "frames",
        resolved_dataset_id="dragonboard_live",
        params={
            "dataset_id": "",
            "snapshot_type": "half_hour",
            "trading_date": "2026-05-11",
            "allowed_capture_modes": "delayed,real_time",
            "exclude_restored": True,
            "sort": "desc",
            "limit": 50,
        },
    )

    assert key.startswith("hellobiga:dragon-board:test:snapshot:frames:v1:dragonboard_live:")
    assert "dataset_id" not in key


def test_snapshot_cache_key_normalizes_csv_parameter_order() -> None:
    builder = SnapshotCacheKeyBuilder(prefix="hellobiga:dragon-board:test")

    left = builder.response_key(
        "records",
        resolved_dataset_id="dragonboard_live",
        params={"types": "half_hour,daily,half_hour", "allowed_capture_modes": "delayed,real_time"},
    )
    right = builder.response_key(
        "records",
        resolved_dataset_id="dragonboard_live",
        params={"allowed_capture_modes": "real_time,delayed", "types": "daily,half_hour"},
    )

    assert left == right


def test_snapshot_cache_key_isolated_by_namespace() -> None:
    left = SnapshotCacheKeyBuilder(prefix="hellobiga:dragon-board:test").response_key(
        "stock_rows",
        resolved_dataset_id="dragonboard_live",
        params={"snapshot_id": "half_hour:2026-05-11:10:00", "codes": "000001,000002"},
    )
    right = SnapshotCacheKeyBuilder(prefix="hellobiga:trading-agents:test").response_key(
        "stock_rows",
        resolved_dataset_id="dragonboard_live",
        params={"snapshot_id": "half_hour:2026-05-11:10:00", "codes": "000001,000002"},
    )

    assert left != right


def test_snapshot_redis_cache_returns_miss_then_hit() -> None:
    redis = FakeRedis()
    cache = SnapshotRedisCache(redis_client=redis, ttl_seconds=300, empty_ttl_seconds=10)
    key = "hellobiga:dragon-board:test:snapshot:frames:v1:dataset:abc"
    response = {"ok": True, "source": "sqlite", "frames": [{"snapshotId": "s1"}], "count": 1}

    assert cache.get_response(key) is None
    cache.set_response(key, response)

    cached = cache.get_response(key)
    assert cached == {
        "ok": True,
        "source": "sqlite",
        "frames": [{"snapshotId": "s1"}],
        "count": 1,
        "cache": {"hit": True, "store": "redis"},
    }
    assert redis.ttls[key] == 300


def test_snapshot_redis_cache_uses_short_ttl_for_empty_results() -> None:
    redis = FakeRedis()
    cache = SnapshotRedisCache(redis_client=redis, ttl_seconds=300, empty_ttl_seconds=10)
    key = "hellobiga:dragon-board:test:snapshot:frames:v1:dataset:empty"

    cache.set_response(key, {"ok": True, "source": "sqlite", "frames": [], "count": 0})

    assert redis.ttls[key] == 10


def test_snapshot_redis_cache_fails_open_when_redis_errors() -> None:
    cache = SnapshotRedisCache(redis_client=FakeRedis(fail=True), ttl_seconds=300, empty_ttl_seconds=10)
    key = "hellobiga:dragon-board:test:snapshot:frames:v1:dataset:abc"

    assert cache.get_response(key) is None
    cache.set_response(key, {"ok": True, "source": "sqlite", "frames": [], "count": 0})


def test_snapshot_redis_cache_invalidates_registered_dependencies() -> None:
    redis = FakeRedis()
    cache = SnapshotRedisCache(redis_client=redis, ttl_seconds=300, empty_ttl_seconds=10)
    response_key = "hellobiga:dragon-board:test:snapshot:frames:v1:dataset:abc"
    index_keys = [
        "hellobiga:dragon-board:test:snapshot:index:dataset:dragonboard_live",
        "hellobiga:dragon-board:test:snapshot:index:date:dragonboard_live:half_hour:2026-05-11",
    ]

    cache.set_response(response_key, {"ok": True, "source": "sqlite", "frames": [{"snapshotId": "s1"}], "count": 1})
    cache.register_dependencies(response_key, index_keys)

    assert redis.expires[index_keys[0]] == 310
    assert redis.expires[index_keys[1]] == 310

    cache.invalidate_indexes(index_keys)

    assert response_key not in redis.values
    assert index_keys[0] not in redis.sets
    assert index_keys[1] not in redis.sets


def test_snapshot_cache_generation_is_dataset_scoped_and_monotonic() -> None:
    redis = FakeRedis()
    cache = SnapshotRedisCache(redis_client=redis, ttl_seconds=300, empty_ttl_seconds=10)
    live_key = build_snapshot_cache_generation_key(
        prefix="hellobiga:dragon-board:test",
        dataset_id="dragonboard_live",
    )
    other_key = build_snapshot_cache_generation_key(
        prefix="hellobiga:dragon-board:test",
        dataset_id="other",
    )

    assert cache.get_generation(live_key) == 0
    assert cache.bump_generation(live_key) == 1
    assert cache.bump_generation(live_key) == 2
    assert cache.get_generation(live_key) == 2
    assert cache.get_generation(other_key) == 0


def test_cached_snapshot_response_does_not_write_after_ingest_generation_changes(monkeypatch) -> None:
    from types import SimpleNamespace

    from backend import main

    redis = FakeRedis()
    cache = SnapshotRedisCache(redis_client=redis, ttl_seconds=300, empty_ttl_seconds=10)
    generation_key = build_snapshot_cache_generation_key(
        prefix="hellobiga:dragon-board:test",
        dataset_id="dragonboard_live",
    )
    writes: list[str] = []
    registrations: list[str] = []
    original_set_response = cache.set_response
    original_register_dependencies = cache.register_dependencies
    monkeypatch.setattr(main.snapshot_cache, "get_snapshot_redis_cache", lambda: cache)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(redis_key_prefix="hellobiga:dragon-board:test"),
    )
    monkeypatch.setattr(
        cache,
        "set_response",
        lambda key, response: (writes.append(key), original_set_response(key, response)),
    )
    monkeypatch.setattr(
        cache,
        "register_dependencies",
        lambda key, indexes: (registrations.append(key), original_register_dependencies(key, indexes)),
    )

    def slow_loader():
        cache.bump_generation(generation_key)
        return {"ok": True, "frames": [{"snapshotId": "old"}], "count": 1}

    response = main._cached_snapshot_response(
        "frames",
        resolved_dataset_id="dragonboard_live",
        params={"snapshot_type": "half_hour"},
        snapshot_type="half_hour",
        loader=slow_loader,
    )

    assert response["frames"][0]["snapshotId"] == "old"
    assert writes == []
    assert registrations == []


def test_snapshot_cache_index_keys_include_dataset_date_and_snapshot() -> None:
    keys = build_snapshot_cache_index_keys(
        prefix="hellobiga:dragon-board:test",
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-05-11",
        snapshot_ids=["s1", "s2"],
    )

    assert "hellobiga:dragon-board:test:snapshot:index:dataset:dragonboard_live" in keys
    assert "hellobiga:dragon-board:test:snapshot:index:date:dragonboard_live:half_hour:2026-05-11" in keys
    assert "hellobiga:dragon-board:test:snapshot:index:snapshot:dragonboard_live:s1" in keys
    assert "hellobiga:dragon-board:test:snapshot:index:snapshot:dragonboard_live:s2" in keys


def test_create_snapshot_redis_client_returns_none_when_disabled() -> None:
    assert create_snapshot_redis_client(
        enabled=False,
        redis_url="redis://127.0.0.1:6379/0",
        connect_timeout=0.2,
        socket_timeout=0.2,
    ) is None
