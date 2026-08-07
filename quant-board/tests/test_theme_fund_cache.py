import json
from datetime import date

import pytest

from backend.services.theme.fund_cache import ThemeFundCache


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.commands: list[tuple] = []

    def hset(self, key: str, field: str, value: str) -> "FakePipeline":
        self.commands.append(("hset", key, field, value))
        return self

    def expire(self, key: str, ttl_seconds: int) -> "FakePipeline":
        self.commands.append(("expire", key, ttl_seconds))
        return self

    def execute(self) -> list:
        for command in self.commands:
            if command[0] == "hset":
                self.redis.hset(command[1], command[2], command[3])
            elif command[0] == "expire":
                self.redis.expire(command[1], command[2])
        return []


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}
        self.expires: dict[str, int] = {}

    def hset(self, key: str, field: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.hashes.setdefault(key, {})[field] = value

    def hget(self, key: str, field: str):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.hashes.get(key, {}).get(field)

    def hmget(self, key: str, fields: list[str]):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return [self.hashes.get(key, {}).get(field) for field in fields]

    def get(self, key: str):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.values[key] = str(value)

    def incr(self, key: str) -> int:
        if self.fail:
            raise RuntimeError("redis unavailable")
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    def incrby(self, key: str, amount: int) -> int:
        if self.fail:
            raise RuntimeError("redis unavailable")
        value = int(self.values.get(key, "0")) + amount
        self.values[key] = str(value)
        return value

    def pipeline(self, transaction: bool = True) -> FakePipeline:
        if self.fail:
            raise RuntimeError("redis unavailable")
        return FakePipeline(self)

    def expire(self, key: str, ttl_seconds: int) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.expires[key] = int(ttl_seconds)


def row(code: str, session_date: str, zlje: float, source_ts: int = 1) -> dict[str, object]:
    return {
        "code": code,
        "zlje": zlje,
        "source": "ths_main_monitor",
        "moneyFlowSource": "ths_main_monitor",
        "sessionDate": session_date,
        "sourceTs": source_ts,
    }


def test_non_trading_day_reads_latest_last_good_without_final_flag() -> None:
    cache = ThemeFundCache(FakeRedis(), prefix="test")
    cache.put(row("000001", "2026-07-24", 12.5))

    latest = cache.get_latest(["000001"], as_of=date(2026, 7, 25))

    assert latest["000001"]["zlje"] == 12.5
    assert latest["000001"]["sessionDate"] == "2026-07-24"


def test_put_many_batch_writes_with_monotonic_versions() -> None:
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test")

    saved, failures = cache.put_many(
        [
            row("000001", "2026-07-24", 12.5),
            row("000002", "2026-07-24", 8.0),
            row("000003", "2026-07-24", 9.5),
        ]
    )

    assert failures == []
    assert [item["version"] for item in saved] == [1, 2, 3]
    assert cache.current_version() == 3
    latest = cache.get_latest(["000001", "000002", "000003"])
    assert latest["000001"]["zlje"] == 12.5
    assert latest["000003"]["zlje"] == 9.5


def test_put_many_preserves_older_rows_and_increments_after_existing_versions() -> None:
    cache = ThemeFundCache(FakeRedis(), prefix="test")
    cache.put(row("000001", "2026-07-24", 12.5, source_ts=20))

    saved, failures = cache.put_many(
        [
            row("000001", "2026-07-24", 88.0, source_ts=10),  # 旧 sourceTs → 保留既有行
            row("000002", "2026-07-24", 8.0),
        ]
    )

    assert failures == []
    assert saved[0]["zlje"] == 12.5
    assert saved[0]["version"] == 1
    assert saved[1]["zlje"] == 8.0
    assert saved[1]["version"] == 2
    assert cache.get_latest(["000001"])["000001"]["zlje"] == 12.5


def test_put_many_isolates_invalid_rows_and_saves_valid_ones() -> None:
    cache = ThemeFundCache(FakeRedis(), prefix="test")
    invalid = {"code": "bad", "zlje": "not-a-number", "source": "ths_main_monitor", "sessionDate": "2026-07-24"}

    saved, failures = cache.put_many([row("000001", "2026-07-24", 12.5), invalid])

    assert len(saved) == 1
    assert failures == [{"code": "bad", "reason": "invalid ths_main_monitor fund row"}]
    assert cache.get_latest(["000001"])["000001"]["zlje"] == 12.5


def test_put_many_falls_back_to_memory_when_redis_fails() -> None:
    cache = ThemeFundCache(FakeRedis(fail=True), prefix="test")

    saved, failures = cache.put_many(
        [
            row("000001", "2026-07-24", 12.5),
            row("000002", "2026-07-24", 8.0),
        ]
    )

    assert failures == []
    assert [item["version"] for item in saved] == [1, 2]
    latest = cache.get_latest(["000001", "000002"])
    assert latest["000001"]["zlje"] == 12.5
    assert latest["000002"]["zlje"] == 8.0


def test_invalid_or_missing_value_never_overwrites_last_good() -> None:
    cache = ThemeFundCache(FakeRedis(), prefix="test")
    cache.put(row("000001", "2026-07-24", 12.5, source_ts=20))

    for value in (float("nan"), float("inf"), None):
        candidate = row("000001", "2026-07-24", 0, source_ts=30)
        candidate["zlje"] = value
        with pytest.raises(ValueError):
            cache.put(candidate)

    assert cache.get_latest(["000001"])["000001"]["zlje"] == 12.5


def test_older_session_or_source_timestamp_cannot_overwrite_last_good() -> None:
    cache = ThemeFundCache(FakeRedis(), prefix="test")
    cache.put(row("000001", "2026-07-24", 12.5, source_ts=20))

    older_date = cache.put(row("000001", "2026-07-23", 99.0, source_ts=30))
    older_time = cache.put(row("000001", "2026-07-24", 88.0, source_ts=10))

    assert older_date["zlje"] == 12.5
    assert older_time["zlje"] == 12.5


def test_redis_failure_keeps_process_last_good() -> None:
    cache = ThemeFundCache(FakeRedis(fail=True), prefix="test")

    stored = cache.put(row("000001", "2026-07-24", 8.0))

    assert cache.get_latest(["000001"])["000001"]["zlje"] == 8.0
    assert stored["version"] == 1


def test_v3_namespace_does_not_read_tdx_v2_rows() -> None:
    redis = FakeRedis()
    redis.hashes["test:theme-fund:v2:latest"] = {
        "000001": json.dumps(
            {
                "code": "000001",
                "zlje": 12.5,
                "moneyFlowSource": "tdx_transaction",
                "tradingDate": "2026-07-24",
            }
        )
    }
    cache = ThemeFundCache(redis, prefix="test")

    assert cache.get_latest(["000001"]) == {}

    cache.put(row("000001", "2026-07-24", 125_000))
    assert "000001" in redis.hashes["test:theme-fund:v3:latest"]


def test_owner_codes_round_trip_through_redis() -> None:
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test")

    cache.set_owner_codes("dragon-board", ["000001", "000002", "000001"])
    restored = ThemeFundCache(redis, prefix="test")

    assert restored.get_owner_codes() == {"dragon-board": ["000001", "000002"]}


def test_version_remains_monotonic_after_redis_recovers() -> None:
    redis = FakeRedis(fail=True)
    cache = ThemeFundCache(redis, prefix="test")
    first = cache.put(row("000001", "2026-07-24", 1.0, source_ts=1))
    second = cache.put(row("000001", "2026-07-24", 2.0, source_ts=2))
    redis.fail = False

    recovered = cache.put(row("000001", "2026-07-24", 3.0, source_ts=3))

    assert first["version"] == 1
    assert second["version"] == 2
    assert recovered["version"] == 3
    assert redis.values["test:theme-fund:v3:version"] == "3"


def test_get_latest_reads_cold_codes_with_one_redis_hmget() -> None:
    redis = FakeRedis()
    redis.hashes["test:theme-fund:v3:latest"] = {
        code: json.dumps(row(code, "2026-07-24", value))
        for code, value in (("000001", 1.0), ("000002", 2.0))
    }
    calls: list[tuple[str, list[str]]] = []
    original_hmget = redis.hmget

    def record_hmget(key: str, fields: list[str]):
        calls.append((key, list(fields)))
        return original_hmget(key, fields)

    redis.hmget = record_hmget  # type: ignore[method-assign]
    cache = ThemeFundCache(redis, prefix="test")

    latest = cache.get_latest(["000001", "000002", "000001"])

    assert set(latest) == {"000001", "000002"}
    assert calls == [("test:theme-fund:v3:latest", ["000001", "000002"])]


def test_put_refreshes_latest_hash_ttl_in_redis() -> None:
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test", ttl_seconds=900)

    cache.put(row("000001", "2026-07-24", 12.5))

    assert redis.expires["test:theme-fund:v3:latest"] == 900
    # 版本与 owners 键保持单调，不因 TTL 过期而重置
    assert "test:theme-fund:v3:version" not in redis.expires


def test_redis_ttl_expiry_keeps_process_last_good() -> None:
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test", ttl_seconds=900)
    cache.put(row("000001", "2026-07-24", 12.5))

    # 模拟 Redis hash 已过期（数据被清理），进程内 last-good 仍可读（fail-visible）
    redis.hashes.clear()

    assert cache.get_latest(["000001"])["000001"]["zlje"] == 12.5


def test_redis_ttl_controls_cross_instance_cold_read() -> None:
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test", ttl_seconds=900)
    cache.put(row("000001", "2026-07-24", 12.5))

    # 新实例（进程内空）从 Redis 命中
    cold = ThemeFundCache(redis, prefix="test", ttl_seconds=900)
    assert cold.get_latest(["000001"])["000001"]["zlje"] == 12.5
