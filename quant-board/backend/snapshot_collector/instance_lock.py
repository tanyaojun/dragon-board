"""Redis single-instance lock for the snapshot collector.

Both the standalone collector process (``backend.collector_main``, port 8001)
and the full API process (``backend.main``, port 8000) compete for this lock
before starting the collector scheduler.  Only the process that holds the lock
runs the scheduler, which prevents duplicate collection when both processes are
managed by the same launcher.

Redis unavailable is fail-open (lock disabled) so the lock itself can never
stop collection; a stale lock expires after ``ttl_seconds`` and is renewed by
the running scheduler's heartbeat.

持有者身份 = ``token`` + PID + **进程创建时间**（v2 锁值：``v2:<token>:<pid>:<创建时间>``）。
只凭 PID 判活会在 Launcher 强杀后的两种场景里把死者误判成活人，残留锁因此
熬满 TTL（最长 120s），新实例等锁超时 RuntimeError 自杀，8001 看似"起不来"
（2026-10-19 复盘，见 ``docs/launcher-control-center/2026-10-19-collector-8001-lock-wait-review.md``）：

1. 进程已被强杀终止、但 Launcher 仍持有该进程句柄（Process 对象/管道/事件注册）
   → ``OpenProcess`` 依然成功，只有 ``GetExitCodeProcess`` 能区分；
2. PID 被系统复用给无关进程 → 与写入锁时的创建时间比对不上，判定为残留。

创建时间不可判定（权限不足、平台不支持 /proc）时退回 PID 判活 —— 保守方向，
宁可多等 TTL，绝不误清活跃持有者的锁。
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any


logger = logging.getLogger(__name__)

_PROTO_V2 = "v2"
# GetExitCodeProcess 返回 STILL_ACTIVE 表示进程仍在运行
_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INVALID_PARAMETER = 87


def _to_int(text: Any) -> int | None:
    try:
        return int(str(text))
    except (TypeError, ValueError):
        return None


def _windows_identity(pid: int) -> tuple[bool, int | None]:
    """Windows: ``(是否仍在运行, 进程创建时间)``。

    ``OpenProcess`` 对"已终止但句柄未释放"的进程仍会成功（Launcher 停止服务时
    持有 Process 对象/管道句柄），所以必须看退出码是否 STILL_ACTIVE；创建时间
    用于识别 PID 复用。探测失败返回 ``(True, None)``——按存活处理。
    """
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        # 87 = ERROR_INVALID_PARAMETER：PID 不存在；其它错误（拒绝访问等）不可判定
        return (ctypes.get_last_error() != _ERROR_INVALID_PARAMETER, None)
    try:
        exit_code = ctypes.c_ulong()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and (
            exit_code.value != _STILL_ACTIVE
        ):
            return (False, None)
        creation = ctypes.c_ulonglong()
        exit_time = ctypes.c_ulonglong()
        kernel_time = ctypes.c_ulonglong()
        user_time = ctypes.c_ulonglong()
        if kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return (True, creation.value)
        return (True, None)
    finally:
        kernel32.CloseHandle(handle)


def _posix_identity(pid: int) -> tuple[bool, int | None]:
    """POSIX: ``(是否仍在运行, 进程启动 tick)``，/proc 不可用时退回 kill(0)。"""
    try:
        with open(f"/proc/{pid}/stat", "r", encoding="utf-8", errors="replace") as stat_file:
            stat = stat_file.read()
    except FileNotFoundError:
        return (False, None)
    except OSError:
        # 无 /proc 的平台：只能判存在性，创建时间不可判定
        try:
            os.kill(pid, 0)
        except OSError:
            return (False, None)
        return (True, None)

    # comm（第 2 字段）可能含空格与括号，从最后一个 ')' 之后切分剩余字段
    fields = stat[stat.rfind(")") + 2 :].split()
    state = fields[0] if fields else ""
    if state == "Z":  # 僵尸：已退出，父进程尚未回收
        return (False, None)
    starttime = _to_int(fields[19]) if len(fields) > 19 else None
    return (True, starttime)


def _process_identity(pid: int) -> tuple[bool, int | None]:
    """``(是否仍在运行, 进程创建时间/启动 tick)``；无法探测时按存活处理。"""
    if pid <= 0:
        return (False, None)
    try:
        if os.name == "nt":
            return _windows_identity(pid)
        return _posix_identity(pid)
    except Exception:
        # 探测异常按存活处理，避免误清活跃锁
        return (True, None)


def _parse_value(value: Any) -> tuple[str, int | None, int | None]:
    """锁值 → ``(token, pid, 创建时间)``；兼容旧格式 ``token:pid``（创建时间 None）。"""
    text = value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value or "")
    if not text:
        return ("", None, None)
    parts = text.split(":")
    if parts[0] == _PROTO_V2 and len(parts) >= 4:
        return (parts[1], _to_int(parts[2]), _to_int(parts[3]))
    if len(parts) >= 2:
        return (parts[0], _to_int(parts[-1]), None)
    return (text, None, None)


def _holder_is_dead(value: Any) -> bool:
    """锁持有者是否已不在运行（残留锁判定）。不可判定时返回 False（保守）。"""
    _, pid, created = _parse_value(value)
    if pid is None:
        return False
    alive, current_created = _process_identity(pid)
    if not alive:
        return True
    if created is not None and current_created is not None and created != current_created:
        logger.warning(
            "collector lock holder PID %s was reused (creation time mismatch); "
            "treating lock as stale",
            pid,
        )
        return True
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
        self._created = _process_identity(self._pid)[1]
        self.ttl_seconds = max(60, ttl_seconds)
        # 锁后端（Redis）不可用时的降级原因（fail-open 后的可见性，2026-10-19 复盘）。
        # None = 协调正常；非 None = 本次 acquire 建立在“无 Redis 协调”之上，
        # 调用方必须自行防双采（例如再查 8001 是否已被别的实例服务）并在 health 暴露。
        self.degraded_reason: str | None = None

    def _value(self) -> str:
        return f"{_PROTO_V2}:{self._token}:{self._pid}:{self._created}"

    @staticmethod
    def _token_of(value: Any) -> str:
        return _parse_value(value)[0]

    @staticmethod
    def _pid_of(value: Any) -> int | None:
        return _parse_value(value)[1]

    def _try_acquire(self) -> bool:
        return bool(self._redis.set(self._key, self._value(), nx=True, ex=self.ttl_seconds))

    def _take(self) -> str | None:
        """原子取走锁值（GETDEL），避免与其它等待实例互相误删对方的新锁。"""
        getdel = getattr(self._redis, "getdel", None)
        if callable(getdel):
            try:
                return getdel(self._key)
            except Exception as exc:
                logger.warning("GETDEL unavailable, falling back to GET+DELETE: %s", exc)
        value = self._redis.get(self._key)
        if value is not None:
            self._redis.delete(self._key)
        return value

    def _put_back(self, value: str) -> None:
        """放回误取到的他人新锁（尽力恢复；失败只让该锁提前过期，等下个续期夺回）。"""
        try:
            self._redis.set(self._key, value, ex=self.ttl_seconds)
        except Exception as exc:
            logger.warning("restoring mis-taken collector lock failed: %s", exc)

    def acquire(self) -> bool:
        if self._redis is None:
            logger.warning("Redis unavailable: collector instance lock disabled (fail-open)")
            return True
        try:
            if self._try_acquire():
                # 抢锁成功即证明 Redis 协调可用：清掉历史降级标记，
                # 避免 health 把“曾经降级”永久当成“当前降级”。
                self.degraded_reason = None
                return True

            current = self._redis.get(self._key)
            if current is None:
                # 锁刚好自然过期：直接重抢
                return self._try_acquire()

            if not _holder_is_dead(current):
                return False

            # 残留锁（持有者已终止或被 PID 复用）：原子取走后再重抢。取走的值若
            # 不是刚读到的那份，说明期间他人已持新锁——放回并放弃，绝不双持。
            logger.warning(
                "clearing stale collector lock left by dead holder pid=%s",
                self._pid_of(current),
            )
            removed = self._take()
            if removed is not None and removed != current:
                self._put_back(removed)
                return False
            return self._try_acquire()
        except Exception as exc:
            # fail-open：Redis 挂了不能让采集进程起不来（可用性优先），但必须留痕——
            # `degraded_reason` 供 collector_main 做“是否已有实例在服务 8001”的
            # 防双采复检，并让 /api/health 能显示“单实例协调降级”（2026-10-19 复盘）。
            self.degraded_reason = f"lock backend unavailable: {str(exc)[:120]}"
            logger.warning("collector instance lock acquire failed: %s", exc)
            return True

    def renew(self) -> bool:
        """Refresh the lock TTL; returns False when this process lost ownership."""
        if self._redis is None:
            return True
        try:
            current = self._redis.get(self._key)
            if self._token_of(current) == self._token:
                renewed = bool(self._redis.expire(self._key, self.ttl_seconds))
                if renewed:
                    # Redis 又通了：清掉降级标记（与 acquire 同语义，让 health 反映当下）。
                    self.degraded_reason = None
                return renewed
            if current is None:
                # Redis 重启/锁过期导致 key 丢失：本进程仍是唯一调度者，
                # 重新夺回（nx 防并发双采；若被其它实例抢走则返回 False）。
                reclaimed = bool(
                    self._redis.set(self._key, self._value(), nx=True, ex=self.ttl_seconds)
                )
                if reclaimed:
                    self.degraded_reason = None
                return reclaimed
            return False
        except Exception as exc:
            # 续期失败 = 当前 Redis 协调不可用（fail-open 返回 True 让采集继续，
            # 但必须留痕：health 的 lockBackend 会转 degraded）。
            self.degraded_reason = f"lock backend unavailable during renew: {str(exc)[:120]}"
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
