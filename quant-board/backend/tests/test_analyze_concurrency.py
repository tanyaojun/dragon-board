"""analyze 并发闸门测试：per-key 单飞 + 全局有界并发 + 双检缓存。"""

import threading
import time

from backend.api.ranktrend_routes import _analyze_with_cache_gate


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


def _run_concurrently(worker, count: int) -> list:
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_same_key_concurrent_requests_compute_once():
    cache = FakeCache()
    compute_count = 0
    counter_lock = threading.Lock()
    results = []
    errors = []

    def compute():
        nonlocal compute_count
        with counter_lock:
            compute_count += 1
        time.sleep(0.05)
        return {"value": compute_count}

    def worker(_index: int) -> None:
        try:
            results.append(
                _analyze_with_cache_gate(
                    cache=cache,
                    cache_key="same-key",
                    generation_key="gen",
                    generation="g1",
                    ttl_seconds=60,
                    dataset_id="ds",
                    compute=compute,
                )
            )
        except Exception as exc:  # pragma: no cover - 失败时暴露原因
            errors.append(exc)

    _run_concurrently(worker, 5)

    assert not errors
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

    def worker(index: int) -> None:
        _analyze_with_cache_gate(
            cache=cache,
            cache_key=f"key-{index}",
            generation_key="gen",
            generation="g1",
            ttl_seconds=60,
            dataset_id="ds",
            compute=compute,
        )

    _run_concurrently(worker, 4)

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

    result = _analyze_with_cache_gate(
        cache=cache,
        cache_key="cached-key",
        generation_key="gen",
        generation="g1",
        ttl_seconds=60,
        dataset_id="ds",
        compute=compute,
    )

    assert result == {"cached": True}
    assert compute_count == 0
