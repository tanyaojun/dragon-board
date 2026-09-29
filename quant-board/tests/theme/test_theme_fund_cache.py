import json
from datetime import date

import pytest

from backend.services.theme.fund_cache import ThemeFundCache, get_theme_fund_cache


class FakePipeline:
    def __init__(self, redis: "FakeRedis") -> None:
        self.redis = redis
        self.commands: list[tuple] = []

    def hset(self, key: str, field: str, value: str) -> "FakePipeline":
        self.commands.append(("hset", key, field, value))
        return self

    def hdel(self, key: str, *fields: str) -> "FakePipeline":
        self.commands.append(("hdel", key, *fields))
        return self

    def expire(self, key: str, ttl_seconds: int) -> "FakePipeline":
        self.commands.append(("expire", key, ttl_seconds))
        return self

    def execute(self) -> list:
        for command in self.commands:
            if command[0] == "hset":
                self.redis.hset(command[1], command[2], command[3])
            elif command[0] == "hdel":
                self.redis.hdel(command[1], *command[2:])
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

    def hdel(self, key: str, *fields: str) -> int:
        if self.fail:
            raise RuntimeError("redis unavailable")
        removed = 0
        for field in fields:
            if self.hashes.get(key, {}).pop(field, None) is not None:
                removed += 1
        return removed

    def hmget(self, key: str, fields: list[str]):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return [self.hashes.get(key, {}).get(field) for field in fields]

    def hgetall(self, key: str):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return dict(self.hashes.get(key, {}))

    def hdel(self, key: str, *fields: str) -> int:
        if self.fail:
            raise RuntimeError("redis unavailable")
        mapping = self.hashes.get(key)
        removed = 0
        if mapping:
            for field in fields:
                if mapping.pop(field, None) is not None:
                    removed += 1
        return removed

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


def row(
    code: str,
    session_date: str,
    zlje: float,
    source_ts: int = 1,
    source: str = "ths_main_monitor",
) -> dict[str, object]:
    return {
        "code": code,
        "zlje": zlje,
        "source": source,
        "moneyFlowSource": source,
        "sessionDate": session_date,
        "sourceTs": source_ts,
    }


def seed_row(
    code: str,
    session_date: str,
    zlje: float,
    source_ts: int = 1,
    source: str = "eastmoney_seed",
) -> dict[str, object]:
    """全市场种子行（东财排行接口，估算），默认 source=eastmoney_seed。"""
    return {
        **row(code, session_date, zlje, source_ts, source=source),
        "moneyFlowEstimated": True,
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
            row("000001", "2026-07-24", 12.5, source="akshare_ths_individual"),
            row("000002", "2026-07-24", 8.0, source="akshare_ths_individual"),
            row("000003", "2026-07-24", 9.5, source="akshare_ths_individual"),
        ]
    )

    assert failures == []
    assert [item["version"] for item in saved] == [1, 2, 3]
    assert cache.current_version() == 3
    # put_many 写 akshare 题材源独立 hash（2026-08-14），读 get_akshare_latest
    latest = cache.get_akshare_latest(["000001", "000002", "000003"])
    assert latest["000001"]["zlje"] == 12.5
    assert latest["000003"]["zlje"] == 9.5


def test_put_many_preserves_older_rows_and_increments_after_existing_versions() -> None:
    cache = ThemeFundCache(FakeRedis(), prefix="test")
    cache.put_many([row("000001", "2026-07-24", 12.5, source_ts=20, source="akshare_ths_individual")])

    saved, failures = cache.put_many(
        [
            row("000001", "2026-07-24", 88.0, source_ts=10, source="akshare_ths_individual"),  # 旧 sourceTs → 保留既有行
            row("000002", "2026-07-24", 8.0, source="akshare_ths_individual"),
        ]
    )

    assert failures == []
    assert saved[0]["zlje"] == 12.5
    assert saved[0]["version"] == 1
    assert saved[1]["zlje"] == 8.0
    assert saved[1]["version"] == 2
    assert cache.get_akshare_latest(["000001"])["000001"]["zlje"] == 12.5


def test_put_many_isolates_invalid_rows_and_saves_valid_ones() -> None:
    cache = ThemeFundCache(FakeRedis(), prefix="test")
    invalid = {"code": "bad", "zlje": "not-a-number", "source": "akshare_ths_individual", "sessionDate": "2026-07-24"}

    saved, failures = cache.put_many(
        [row("000001", "2026-07-24", 12.5, source="akshare_ths_individual"), invalid]
    )

    assert len(saved) == 1
    assert failures == [{"code": "bad", "reason": "invalid fund row"}]
    assert cache.get_akshare_latest(["000001"])["000001"]["zlje"] == 12.5


def test_put_many_falls_back_to_memory_when_redis_fails() -> None:
    cache = ThemeFundCache(FakeRedis(fail=True), prefix="test")

    saved, failures = cache.put_many(
        [
            row("000001", "2026-07-24", 12.5, source="akshare_ths_individual"),
            row("000002", "2026-07-24", 8.0, source="akshare_ths_individual"),
        ]
    )

    assert failures == []
    assert [item["version"] for item in saved] == [1, 2]
    latest = cache.get_akshare_latest(["000001", "000002"])
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
    # 清理策略（2026-08-12）：version 与 latest 同生命周期（TTL 兜底），
    # 停止写入后过期重置，前端 full_state 清空本地版本记录兜底
    assert redis.expires["test:theme-fund:v3:version"] == 900


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


def test_put_many_accepts_akshare_ths_individual_source() -> None:
    # 2026-08-14：akshare 题材源独立 hash——用 put_many 写入、get_akshare_latest 读取
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test", ttl_seconds=900)
    akshare_row = {
        "code": "000001",
        "zlje": 12.5,
        "source": "akshare_ths_individual",
        "moneyFlowSource": "akshare_ths_individual",
        "sessionDate": "2026-07-24",
        "sourceTs": 1,
    }

    saved, _failures = cache.put_many([akshare_row])

    assert saved[0]["source"] == "akshare_ths_individual"
    assert cache.get_akshare_latest(["000001"])["000001"]["source"] == "akshare_ths_individual"


def test_put_many_prunes_stale_trading_session_rows() -> None:
    # 2026-08-14：put_many 写 akshare 独立 hash，旧交易日清理针对 akshare hash
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test", ttl_seconds=900)
    cache.put_many(
        [
            row("000001", "2026-07-24", 1.0, source="akshare_ths_individual"),
            row("000002", "2026-07-24", 2.0, source="akshare_ths_individual"),
        ]
    )

    saved, failures = cache.put_many(
        [
            row("000001", "2026-07-25", 3.0, source="akshare_ths_individual"),
            row("000003", "2026-07-25", 4.0, source="akshare_ths_individual"),
        ]
    )

    assert failures == []
    assert len(saved) == 2
    # 旧交易日行（000002 07-24，未在本批写入）从内存与 akshare hash 一并清除
    assert "000002" not in cache._akshare
    assert "000002" not in redis.hashes["test:theme-fund:v3:akshare"]
    # 本批写入的行保留
    assert "000001" in redis.hashes["test:theme-fund:v3:akshare"]
    assert "000003" in redis.hashes["test:theme-fund:v3:akshare"]


def test_put_many_version_gets_ttl() -> None:
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test", ttl_seconds=900)
    cache.put_many([row("000001", "2026-07-24", 1.0, source="akshare_ths_individual")])

    assert redis.expires["test:theme-fund:v3:version"] == 900


def test_put_many_rejects_ths_main_monitor() -> None:
    # 2026-08-14：akshare 题材源 hash 只接受 akshare_ths_individual；L2 主源行
    # 必须走 put（写 latest hash），否则串线（MongoDB 冷启动恢复曾误写）。
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test")
    saved, failures = cache.put_many([row("000001", "2026-07-24", 1.0)])  # 默认 ths_main_monitor

    assert saved == []
    assert len(failures) == 1
    assert failures[0]["code"] == "000001"
    assert "test:theme-fund:v3:akshare" not in redis.hashes


def test_put_rejects_akshare_source() -> None:
    # 2026-08-14：latest hash 只接受 ths_main_monitor；akshare 题材源必须走 put_many。
    cache = ThemeFundCache(FakeRedis(), prefix="test")
    with pytest.raises(ValueError):
        cache.put(row("000001", "2026-07-24", 1.0, source="akshare_ths_individual"))


def test_put_many_accepts_eastmoney_main_source() -> None:
    # 2026-XX 题材主力资金切换东财：eastmoney_main 路由到题材 hash，get_akshare_latest 可读
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test", ttl_seconds=900)
    em_row = {
        "code": "600000",
        "zlje": -9876543.21,
        "cddje": -12345678.0,
        "cddjzb": -5.5,
        "zljzb": -2.34,
        "source": "eastmoney_main",
        "moneyFlowSource": "eastmoney_main",
        "sessionDate": "2026-07-30",
        "sourceTs": 1,
    }

    saved, failures = cache.put_many([em_row])

    assert failures == []
    assert saved[0]["source"] == "eastmoney_main"
    stored = cache.get_akshare_latest(["600000"])["600000"]
    assert stored["source"] == "eastmoney_main"
    assert stored["zlje"] == -9876543.21


def test_eastmoney_row_overwrites_same_day_akshare_row_by_rank() -> None:
    # 同一 sessionDate 下 rank：eastmoney(2) > akshare(1)——切换东财后同日残留
    # akshare 行被东财行自动覆盖；反向（akshare 覆盖东财）被拒绝
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test", ttl_seconds=900)
    cache.put_many([row("600000", "2026-07-30", 1.0, source="akshare_ths_individual", source_ts=200)])

    saved, _failures = cache.put_many(
        [row("600000", "2026-07-30", 2.0, source="eastmoney_main", source_ts=100)]
    )

    assert saved[0]["source"] == "eastmoney_main"
    assert saved[0]["zlje"] == 2.0

    rejected, _failures = cache.put_many(
        [row("600000", "2026-07-30", 3.0, source="akshare_ths_individual", source_ts=999)]
    )

    # akshare 行 rank 低 + sourceTs 虽新：同日 rank 高者权威，akshare 不能覆盖东财
    assert rejected[0]["source"] == "eastmoney_main"
    assert cache.get_akshare_latest(["600000"])["600000"]["zlje"] == 2.0


def test_eastmoney_memory_rows_exported_for_redis_restore() -> None:
    # Redis 题材 hash key 丢失时，东财行同样从内存 last-good 写回
    redis = FakeRedis()
    cache = ThemeFundCache(redis, prefix="test", ttl_seconds=900)
    cache.put_many(
        [
            row("600000", "2026-07-30", 1.0, source="eastmoney_main"),
            row("000001", "2026-07-30", 2.0, source="ths_main_monitor"),
        ]
    )

    exported = cache.akshare_memory_rows()

    assert [entry["code"] for entry in exported] == ["600000"]
    assert exported[0]["source"] == "eastmoney_main"
