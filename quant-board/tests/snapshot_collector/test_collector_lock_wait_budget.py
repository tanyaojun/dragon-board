"""collector 等锁预算测试（2026-10-12 重启风暴复盘）。

契约：
- 等锁总预算必须覆盖残留锁最长寿命（TTL）：launcher taskkill 强杀后锁残留
  0~TTL 秒，预算小于 TTL 时新实例必然 RuntimeError 自杀（旧值 10×5s=50s <
  TTL 120s），喂大 launcher 连续失败计数直至熔断。
- 预算从锁 TTL 动态推导（TTL/interval + 8 次余量），TTL 变更时自动跟随。
"""

from __future__ import annotations

import asyncio

import pytest

from backend.collector_main import _acquire_lock_with_retry, _lock_wait_tries


def test_budget_exceeds_lock_ttl() -> None:
    tries = _lock_wait_tries(120, 5.0)
    assert tries * 5.0 > 120  # 总等待覆盖 TTL 全长
    assert tries == 32  # 120/5 + 8 余量


def test_budget_follows_ttl_change() -> None:
    assert _lock_wait_tries(240, 5.0) == 56
    assert _lock_wait_tries(60, 5.0) == 20


class _NeverReleasedLock:
    """模拟残留锁：acquire 永远失败，TTL 120s（与生产 RedisInstanceLock 一致）。"""

    ttl_seconds = 120

    def __init__(self) -> None:
        self.acquire_calls = 0

    def acquire(self) -> bool:
        self.acquire_calls += 1
        return False


@pytest.mark.asyncio
async def test_default_tries_derived_from_lock_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """默认 tries 由 lock.ttl_seconds 推导：失败 32 次后才放弃（160s > 120s）。"""
    lock = _NeverReleasedLock()
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    assert await _acquire_lock_with_retry(lock) is False
    assert lock.acquire_calls == 32
    assert sleeps and all(s == 5.0 for s in sleeps)


@pytest.mark.asyncio
async def test_explicit_tries_still_honoured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = _NeverReleasedLock()

    async def _fake_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)
    assert await _acquire_lock_with_retry(lock, tries=3, interval_seconds=0.1) is False
    assert lock.acquire_calls == 3
