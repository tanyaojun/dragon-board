from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from backend.snapshot_collector import instance_lock
from backend.snapshot_collector.instance_lock import RedisInstanceLock

LOCK_KEY = "snapshot-collector:instance-lock:collector"


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


# ── 2026-10-19 复盘：残留锁判活精度（8001 等锁超时 RuntimeError 自杀） ──
# 只凭 PID 判活会把两种情况下的死者误判成活人：① 强杀后 launcher 仍持有句柄
# （OpenProcess 成功）；② PID 被系统复用。两种都会让残留锁熬满 TTL(120s)。


def test_terminated_holder_with_open_handle_is_reclaimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """持有者已终止（退出码非 STILL_ACTIVE）：残留锁必须被立即清理重抢。"""
    monkeypatch.setattr(instance_lock, "_process_identity", lambda pid: (False, None))
    redis = FakeRedis()
    redis._values[LOCK_KEY] = "v2:deadbeef:5752:134368522690637013"
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)

    assert lock.acquire() is True
    assert instance_lock._parse_value(redis.get(LOCK_KEY))[0] == lock._token


def test_lock_holder_pid_reuse_is_reclaimed(monkeypatch: pytest.MonkeyPatch) -> None:
    """写入锁的 PID 与探测到的创建时间不一致（PID 已复用给新进程）→ 判残留。"""
    monkeypatch.setattr(instance_lock, "_process_identity", lambda pid: (True, 999))
    redis = FakeRedis()
    redis._values[LOCK_KEY] = "v2:deadbeef:4242:111"  # 创建时间 111 ≠ 999
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)

    assert lock.acquire() is True
    assert instance_lock._parse_value(redis.get(LOCK_KEY))[0] == lock._token


def test_live_holder_with_matching_identity_keeps_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PID 与创建时间都对得上（真活跃持有者）：锁不得被清理。"""
    monkeypatch.setattr(instance_lock, "_process_identity", lambda pid: (True, 777))
    redis = FakeRedis()
    holder = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    assert holder.acquire() is True

    waiter = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    assert waiter.acquire() is False
    assert instance_lock._parse_value(redis.get(LOCK_KEY))[0] == holder._token


def test_undecidable_identity_is_treated_as_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """创建时间不可判定（权限/平台不支持）时保守判活，绝不误清活跃锁。"""
    monkeypatch.setattr(instance_lock, "_process_identity", lambda pid: (True, None))
    redis = FakeRedis()
    redis._values[LOCK_KEY] = "v2:someone:1234:555"
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)

    assert lock.acquire() is False
    assert instance_lock._parse_value(redis.get(LOCK_KEY))[0] == "someone"


def test_legacy_lock_value_still_parsed() -> None:
    """旧格式（token:pid，无创建时间）仍可解析；持有者已死时同样能清锁。"""
    assert instance_lock._parse_value("deadbeef:5752") == ("deadbeef", 5752, None)
    token, pid, created = instance_lock._parse_value("v2:abc:5752:123")
    assert (token, pid, created) == ("abc", 5752, 123)
    assert instance_lock._parse_value(None) == ("", None, None)


def test_mis_taken_lock_is_restored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """判残留后原子取锁的瞬间他人已持新锁：必须放回并放弃，绝不双持。"""
    monkeypatch.setattr(instance_lock, "_process_identity", lambda pid: (False, None))
    redis = FakeRedis()
    redis._values[LOCK_KEY] = "v2:deadbeef:5752:111"
    live_value = "v2:liveholder:123:222"

    def _racing_getdel(key: str) -> str:
        # 模拟：GETDEL 取到的是他人刚写入的新锁
        return live_value

    redis.getdel = _racing_getdel  # type: ignore[attr-defined]
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)

    assert lock.acquire() is False
    assert redis.get(LOCK_KEY) == live_value


@pytest.mark.skipif(os.name != "nt", reason="Windows 句柄语义下才有该残留锁形态")
def test_windows_terminated_process_with_open_handle_detected_as_dead() -> None:
    """真进程回归（2026-10-19 生产机制复现）：taskkill/杀进程后父进程仍持有句柄时
    ``OpenProcess`` 仍成功，只凭 PID 会判活；必须以退出码判死，否则残留锁熬满 TTL。"""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert instance_lock._process_identity(proc.pid)[0] is True
        proc.kill()  # 不 wait：父进程继续持有进程句柄（等价 launcher 的 Process 对象）
        deadline = time.time() + 5
        while time.time() < deadline and instance_lock._process_identity(proc.pid)[0]:
            time.sleep(0.05)
        assert instance_lock._process_identity(proc.pid)[0] is False
        # 旧格式锁值（无创建时间）也必须判死——退出码那一层就足够
        assert instance_lock._holder_is_dead(f"liveholder:{proc.pid}") is True
    finally:
        proc.wait(timeout=10)


class BrokenRedis:
    """Redis 不可达：任何操作都抛连接错误（模拟 Redis 挂了/重启中）。"""

    def set(self, *args, **kwargs):
        raise ConnectionError("Error 10061 connecting to 127.0.0.1:6379")

    def get(self, *args, **kwargs):
        raise ConnectionError("Error 10061 connecting to 127.0.0.1:6379")


def test_lock_fail_open_records_degraded_reason() -> None:
    """Redis 不可达：fail-open（不能因为协调层挂了就起不来），但必须留痕。"""
    lock = RedisInstanceLock(BrokenRedis(), "collector")
    assert lock.acquire() is True
    assert lock.degraded_reason is not None
    assert "lock backend unavailable" in lock.degraded_reason


def test_lock_healthy_path_has_no_degraded_reason() -> None:
    redis = FakeRedis()
    lock = RedisInstanceLock(redis, "collector")
    assert lock.acquire() is True
    assert lock.degraded_reason is None
    # Redis 正常但锁被别人持有：不是降级，是“确实是别人的锁”
    other = RedisInstanceLock(redis, "collector")
    assert other.acquire() is False
    assert other.degraded_reason is None


def test_degraded_reason_cleared_when_redis_recovers_on_renew() -> None:
    """一次瞬时抖动不得把 health 永久钉在 degraded（code review 修正）。

    ``lockBackend`` 是 launcher/运维判断“当前有没有 Redis 协调”的依据，
    恢复后必须回到 redis；否则重启风暴防护会一直按 degraded（restartable=false）走。
    """

    class FlakyRedis(FakeRedis):
        def __init__(self) -> None:
            super().__init__()
            self.broken = False

        def get(self, key: str):
            if self.broken:
                raise ConnectionError("blip")
            return super().get(key)

        def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
            if self.broken:
                raise ConnectionError("blip")
            return super().set(key, value, nx=nx, ex=ex)

        def expire(self, key: str, seconds: int) -> bool:
            if self.broken:
                raise ConnectionError("blip")
            return super().expire(key, seconds)

    redis = FlakyRedis()
    redis.broken = True
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    assert lock.acquire() is True
    assert lock.degraded_reason is not None

    # Redis 恢复 → 续期成功即证明协调恢复，降级标记应被清掉
    redis.broken = False
    assert lock.renew() is True
    assert lock.degraded_reason is None


def test_degraded_reason_set_when_renew_fails() -> None:
    """续期时 Redis 挂掉：fail-open 继续采集，但必须暴露“当下无协调”。"""
    redis = FakeRedis()
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    assert lock.acquire() is True
    assert lock.degraded_reason is None

    def _boom(*args, **kwargs):
        raise ConnectionError("down")

    redis.get = _boom  # type: ignore[method-assign]
    assert lock.renew() is True  # fail-open：采集不中断
    assert lock.degraded_reason is not None
    assert "renew" in lock.degraded_reason


def test_bytes_lock_value_is_parsed() -> None:
    """锁值可能是 bytes（不同 Redis 客户端 decode_responses 配置）：

    若按 bytes 直接 str() 会得到 "b'...'"，PID 解析失败 → 残留锁永远清不掉，
    R2 修复静默失效。这里锁定 bytes 兼容。
    """
    assert instance_lock._parse_value(b"v2:abc:4242:171234567890") == (
        "abc",
        4242,
        171234567890,
    )
    assert instance_lock._parse_value(b"tok:4242") == ("tok", 4242, None)


def test_bytes_lock_value_from_dead_pid_is_reclaimed() -> None:
    redis = FakeRedis()
    redis._values["snapshot-collector:instance-lock:collector"] = b"v2:deadbeef:99999999:1"
    lock = RedisInstanceLock(redis, "collector", ttl_seconds=120)
    assert lock.acquire() is True
