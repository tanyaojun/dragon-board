from __future__ import annotations

from backend.snapshot_collector.instance_lock import RedisInstanceLock


class FakeRedis:
    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self._values:
            return False
        self._values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self._values.get(key)

    def expire(self, key: str, seconds: int) -> bool:
        return key in self._values

    def delete(self, key: str) -> int:
        return 1 if self._values.pop(key, None) is not None else 0


def test_lock_acquire_and_release() -> None:
    redis = FakeRedis()
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=300)
    assert lock.acquire() is True
    # 第二实例拿不到锁
    assert RedisInstanceLock(redis, "collector", ttl_seconds=300).acquire() is False
    assert lock.renew() is True
    lock.release()
    assert RedisInstanceLock(redis, "collector", ttl_seconds=300).acquire() is True


def test_lock_redis_unavailable_is_not_fatal() -> None:
    lock = RedisInstanceLock(None, "collector")
    assert lock.acquire() is True
    assert lock.renew() is True


def test_stale_lock_from_dead_pid_is_reclaimed() -> None:
    """被 taskkill 强杀后残留的锁（持有者 PID 已死）应被立即清理并重抢。"""
    redis = FakeRedis()
    redis._values["snapshot-collector:instance-lock:collector"] = "deadbeef:99999999"
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    assert lock.acquire() is True
    assert redis.get("snapshot-collector:instance-lock:collector") is not None
    # 重抢后锁归新持有者，第三个实例仍拿不到
    assert RedisInstanceLock(redis, "collector", ttl_seconds=120).acquire() is False


def test_live_holder_lock_is_not_reclaimed() -> None:
    """持有者进程存活时，锁不能被清理（防止误清活跃采集进程）。"""
    redis = FakeRedis()
    import os

    redis._values[
        "snapshot-collector:instance-lock:collector"
    ] = f"liveholder:{os.getpid()}"
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    assert lock.acquire() is False


def test_lock_renew_recovers_after_redis_restart() -> None:
    """Redis 重启导致锁 key 丢失后，持有者 renew 应重新夺回而不是放弃。"""
    redis = FakeRedis()
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    assert lock.acquire() is True
    # 模拟 Redis 重启：内存清空，锁 key 消失
    redis._values.clear()
    assert lock.renew() is True
    assert redis.get("snapshot-collector:instance-lock:collector") is not None
    # 重新夺回后仍是唯一持有者，其它实例拿不到
    assert RedisInstanceLock(redis, "collector", ttl_seconds=120).acquire() is False


def test_lock_renew_does_not_steal_from_live_holder() -> None:
    """锁被其它存活实例抢走时，renew 必须返回 False（不得覆盖他人锁）。"""
    redis = FakeRedis()
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    assert lock.acquire() is True
    other = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    # 模拟本进程锁过期被清理后，其它实例抢占了锁
    redis._values.clear()
    assert other.acquire() is True
    assert lock.renew() is False
