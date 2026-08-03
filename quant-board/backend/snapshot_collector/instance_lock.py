"""Redis single-instance lock for the snapshot collector.

Both the standalone collector process (``backend.collector_main``, port 8001)
and the full API process (``backend.main``, port 8000) compete for this lock
before starting the collector scheduler.  Only the process that holds the lock
runs the scheduler, which prevents duplicate collection when both processes are
managed by the same launcher.

Redis unavailable is fail-open (lock disabled) so the lock itself can never
stop collection; a stale lock expires after ``ttl_seconds`` and is renewed by
the running scheduler's heartbeat.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any


logger = logging.getLogger(__name__)


def _pid_alive(pid: int) -> bool:
    """Best-effort process liveness check (Windows-safe)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            # PROCESS_QUERY_LIMITED_INFORMATION
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            # 无法探测时按存活处理，避免误清活跃锁
            return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class RedisInstanceLock:
    def __init__(
        self,
        redis_client: Any,
        name: str,
        ttl_seconds: int = 120,
    ) -> None:
        self._redis = redis_client
        self._key = f"snapshot-collector:instance-lock:{name}"
        self._token = uuid.uuid4().hex
        self._pid = os.getpid()
        self.ttl_seconds = max(60, ttl_seconds)

    def _value(self) -> str:
        return f"{self._token}:{self._pid}"

    @staticmethod
    def _token_of(value: str | None) -> str:
        return str(value).split(":")[0] if value else ""

    @staticmethod
    def _pid_of(value: str | None) -> int | None:
        if not value or ":" not in str(value):
            return None
        try:
            return int(str(value).rsplit(":", 1)[1])
        except (TypeError, ValueError):
            return None

    def acquire(self) -> bool:
        if self._redis is None:
            logger.warning("Redis unavailable: collector instance lock disabled (fail-open)")
            return True
        try:
            if self._redis.set(self._key, self._value(), nx=True, ex=self.ttl_seconds):
                return True
            # 锁已存在：若持有者进程已死（如 launcher taskkill 强杀后残留），
            # 清理残留并重抢一次，避免每次启动都等 TTL 过期。
            holder_pid = self._pid_of(self._redis.get(self._key))
            if holder_pid is not None and not _pid_alive(holder_pid):
                logger.warning(
                    "clearing stale collector lock held by dead PID %s", holder_pid
                )
                self._redis.delete(self._key)
                return bool(
                    self._redis.set(self._key, self._value(), nx=True, ex=self.ttl_seconds)
                )
            return False
        except Exception as exc:
            logger.warning("collector instance lock acquire failed: %s", exc)
            return True

    def renew(self) -> bool:
        """Refresh the lock TTL; returns False when this process lost ownership."""
        if self._redis is None:
            return True
        try:
            if self._token_of(self._redis.get(self._key)) == self._token:
                return bool(self._redis.expire(self._key, self.ttl_seconds))
            return False
        except Exception as exc:
            logger.warning("collector instance lock renew failed: %s", exc)
            return True

    def remaining_ttl(self) -> int | None:
        """Return the lock's remaining TTL in seconds (None when unavailable)."""
        if self._redis is None:
            return None
        try:
            ttl = self._redis.ttl(self._key)
            return int(ttl) if ttl is not None else None
        except Exception:
            return None

    def release(self) -> None:
        if self._redis is None:
            return
        try:
            if self._token_of(self._redis.get(self._key)) == self._token:
                self._redis.delete(self._key)
        except Exception as exc:
            logger.warning("collector instance lock release failed: %s", exc)
