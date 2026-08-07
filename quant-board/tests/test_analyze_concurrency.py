"""analyze 并发闸门专项测试。

端点是 async def：等待信号量的请求是 asyncio 协程（不占线程池），
重计算通过 asyncio.to_thread 执行。这里用 asyncio.run 包装并发驱动
_analyze_with_cache_gate，验证 per-key 单飞与全局有界并发语义。
"""

import asyncio
import threading
import time

import pytest

from backend.api import ranktrend_routes
from backend.api.ranktrend_routes import _analyze_with_cache_gate


@pytest.fixture(autouse=True)
def _reset_analyze_async_primitives():
    """每用例前重置 asyncio 信号量/锁：asyncio 原语首次 acquire 时绑定事件循环，
    而 asyncio.run 每次新建 loop，跨用例复用会触发 'bound to a different event loop'。"""
    ranktrend_routes._ANALYZE_SEMAPHORE = None
    ranktrend_routes._ANALYZE_KEY_LOCKS.clear()
    yield
    ranktrend_routes._ANALYZE_SEMAPHORE = None
    ranktrend_routes._ANALYZE_KEY_LOCKS.clear()


class FakeCache:
    def __init__(self, generation: str = "g1") -> None:
        self.data: dict = {}
        self.generation = generation
        self.deps = None

    def get_response(self, key: str):
        return self.data.get(key)

    def set_response(self, key: str, value, ttl_seconds=None) -> None:
        self.data[key] = value

    def get_generation(self, key: str) -> str:
        return self.generation

    def register_dependencies(self, key: str, deps) -> None:
        self.deps = (key, deps)


def test_same_key_concurrent_requests_compute_once():
    cache = FakeCache()
    compute_count = 0
    counter_lock = threading.Lock()
    results = []

    def compute():
        nonlocal compute_count
        with counter_lock:
            compute_count += 1
        time.sleep(0.05)
        return {"value": compute_count}

    async def worker(_index: int):
        return await _analyze_with_cache_gate(
            cache=cache,
            cache_key="same-key",
            generation_key="gen",
            generation="g1",
            ttl_seconds=60,
            dataset_id="ds",
            compute=compute,
        )

    async def main():
        return await asyncio.gather(*(worker(i) for i in range(5)))

    results = asyncio.run(main())

    assert compute_count == 1
    assert len(results) == 5
    assert all(result == results[0] for result in results)


def test_different_keys_concurrent_compute_bounded_by_semaphore():
    cache = FakeCache()
    active = 0
    max_active = 0
    compute_count = 0
    counter_lock = threading.Lock()

    def compute():
        nonlocal active, max_active, compute_count
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
            compute_count += 1
        time.sleep(0.2)
        with counter_lock:
            active -= 1
        return {"ok": True}

    async def worker(index: int):
        return await _analyze_with_cache_gate(
            cache=cache,
            cache_key=f"key-{index}",
            generation_key="gen",
            generation="g1",
            ttl_seconds=60,
            dataset_id="ds",
            compute=compute,
        )

    async def main():
        await asyncio.gather(*(worker(i) for i in range(4)))

    asyncio.run(main())

    assert compute_count == 4
    # QUANT_BOARD_ANALYZE_MAX_CONCURRENCY 默认 2，全局并发不得超过该上限
    assert max_active <= 2


def test_cache_hit_skips_compute():
    cache = FakeCache()
    cache.set_response("cached-key", {"cached": True})
    compute_count = 0

    def compute():
        nonlocal compute_count
        compute_count += 1
        return {"computed": True}

    async def run():
        return await _analyze_with_cache_gate(
            cache=cache,
            cache_key="cached-key",
            generation_key="gen",
            generation="g1",
            ttl_seconds=60,
            dataset_id="ds",
            compute=compute,
        )

    result = asyncio.run(run())

    assert result == {"cached": True}
    assert compute_count == 0
