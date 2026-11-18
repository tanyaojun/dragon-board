from __future__ import annotations

import json
import time

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.market_data_routes as market_data_routes
from backend.market_proxy.indices import MarketOverviewService
from backend.market_proxy.quotes import MarketQuotesCache, to_tencent_diff_item


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

    def hmget(self, key: str, fields: list[str]):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return [self.hashes.get(key, {}).get(field) for field in fields]

    def get(self, key: str):
        if self.fail:
            raise RuntimeError("redis unavailable")
        return self.values.get(key)

    def setex(self, key: str, ttl_seconds: int, value: str) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.values[key] = str(value)
        self.expires[key] = int(ttl_seconds)

    def set(self, key: str, value: str) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.values[key] = str(value)

    def expire(self, key: str, ttl_seconds: int) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.expires[key] = int(ttl_seconds)

    def pipeline(self, transaction: bool = False):
        return _FakeRedisPipeline(self)


class _FakeRedisPipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.ops: list[tuple] = []

    def hset(self, key: str, field: str, value: str):
        self.ops.append(("hset", key, field, value))
        return self

    def set(self, key: str, value: str):
        self.ops.append(("set", key, value))
        return self

    def expire(self, key: str, ttl_seconds: int):
        self.ops.append(("expire", key, ttl_seconds))
        return self

    def execute(self) -> None:
        for op in self.ops:
            if op[0] == "hset":
                self.redis.hset(op[1], op[2], op[3])
            elif op[0] == "set":
                self.redis.set(op[1], op[2])
            elif op[0] == "expire":
                self.redis.expire(op[1], op[2])
        self.ops = []


class FakeTxAkshare:
    def __init__(self, frame=None, error=None) -> None:
        self.frame = frame
        self.error = error
        self.calls = 0

    def stock_zh_a_spot_tx(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.frame


class FakeIndexAkshare:
    def __init__(self, frame=None, error=None) -> None:
        self.frame = frame
        self.error = error
        self.calls = 0

    def stock_zh_index_spot_sina(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.frame


def _tx_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "code": "sh600519",
                "name": "贵州茅台",
                "zxj": 1350.6,
                "zdf": -0.82,
                "volume": 55128.0,
                "hsl": 0.44,
                "lb": 1.08,
                "pe_ttm": 20.41,
                "pn": 7.25,
                "zsz": 16883.6,
                "ltsz": 16883.6,
            },
            {
                "code": "sz000001",
                "name": "平安银行",
                "zxj": 11.5,
                "zdf": 1.2,
                "volume": 1000.0,
                "hsl": 0.9,
                "lb": 0.8,
                "pe_ttm": 6.1,
                "pn": 0.9,
                "zsz": 2230.0,
                "ltsz": 2230.0,
            },
        ]
    )


def _client(monkeypatch: pytest.MonkeyPatch, cache: MarketQuotesCache) -> TestClient:
    app = FastAPI()
    app.include_router(market_data_routes.router)
    monkeypatch.setattr(
        market_data_routes,
        "get_market_quotes_cache",
        lambda: cache,
    )
    return TestClient(app)


def test_to_tencent_diff_item_maps_units() -> None:
    item = to_tencent_diff_item(
        {
            "code": "sh600519",
            "name": "贵州茅台",
            "zxj": 1350.6,
            "zdf": -0.82,
            "volume": 55128.0,
            "hsl": 0.44,
            "lb": 1.08,
            "pe_ttm": 20.41,
            "pn": 7.25,
            "zsz": 16883.6,
            "ltsz": 16883.6,
        }
    )

    assert item["f12"] == "600519"
    assert item["f14"] == "贵州茅台"
    assert item["f2"] == 1350.6
    assert item["f3"] == -0.82
    assert item["f6"] == 55128.0
    assert item["f5"] == pytest.approx(1350.6 * 55128.0 * 100, abs=0.01)
    assert item["f8"] == 0.44
    assert item["f9"] == 20.41
    assert item["f10"] == 1.08
    # zsz/ltsz 亿元 → f20/f21 万元（前端再乘 10000 得元）
    assert item["f20"] == 16883.6 * 10000
    assert item["f21"] == 16883.6 * 10000
    assert item["f23"] == 7.25
    assert item["f62"] == 0
    assert item["f184"] == 0


@pytest.mark.asyncio
async def test_quotes_cache_refresh_and_last_good() -> None:
    ak = FakeTxAkshare(frame=_tx_frame())
    cache = MarketQuotesCache(
        refresh_interval_seconds=300,
        akshare_module=ak,
        now_ms=lambda: 1000,
    )

    assert await cache.refresh() is True
    assert cache.status()["rowCount"] == 2
    assert cache.status()["lastError"] is None

    ak.error = RuntimeError("upstream down")
    assert await cache.refresh() is False
    assert cache.status()["lastError"].startswith("RuntimeError")
    # last-good 保留
    assert cache.status()["rowCount"] == 2


@pytest.mark.asyncio
async def test_quotes_cache_get_diff_orders_by_request() -> None:
    ak = FakeTxAkshare(frame=_tx_frame())
    cache = MarketQuotesCache(
        refresh_interval_seconds=300,
        akshare_module=ak,
        now_ms=lambda: 1000,
    )
    await cache.refresh()

    diff = cache.get_diff(["000002", "000001", "000001", "bad", "600519"])["data"]["diff"]
    # 000002 不在缓存中，跳过；000001 去重；bad 非法。
    assert [row["f12"] for row in diff] == ["000001", "600519"]


def test_quotes_routes_missing_codes_400(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, MarketQuotesCache(refresh_interval_seconds=300))

    response = client.get("/api/quotes/tencent")
    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["errorCode"] == "missing_codes"

    response = client.get("/api/quotes/sina?codes=abc,1")
    assert response.status_code == 400
    assert response.json()["errorCode"] == "missing_codes"


def test_quotes_routes_serve_cache_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = MarketQuotesCache(refresh_interval_seconds=300)
    cache._rows = {
        "000001": {"f12": "000001", "f2": 11.5, "f20": 22300000.0},
        "600519": {"f12": "600519", "f2": 1350.6, "f20": 168836000.0},
    }
    client = _client(monkeypatch, cache)

    response = client.get("/api/quotes/tencent?codes=600519,000001")
    assert response.status_code == 200
    body = response.json()
    assert body["rc"] == 0
    assert [row["f12"] for row in body["data"]["diff"]] == ["600519", "000001"]


def test_quotes_routes_accept_prefixed_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = MarketQuotesCache(refresh_interval_seconds=300)
    cache._rows = {
        "000001": {"f12": "000001", "f2": 11.5, "f20": 22300000.0},
        "600519": {"f12": "600519", "f2": 1350.6, "f20": 168836000.0},
    }
    client = _client(monkeypatch, cache)

    response = client.get("/api/quotes/tencent?codes=sh600519,sz000001,000001")
    assert response.status_code == 200
    body = response.json()
    assert [row["f12"] for row in body["data"]["diff"]] == ["600519", "000001"]


def test_quotes_routes_degrade_when_cache_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = MarketQuotesCache(refresh_interval_seconds=300)
    client = _client(monkeypatch, cache)

    response = client.get("/api/quotes/tencent?codes=600519,000001")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["degraded"] is True
    assert body["errorCode"] == "cache_not_ready"
    assert body["data"] == {"diff": []}


def test_quotes_routes_degrade_with_last_error(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = MarketQuotesCache(refresh_interval_seconds=300)
    cache._last_error = "RuntimeError: upstream down"
    client = _client(monkeypatch, cache)

    response = client.get("/api/quotes/sina?codes=600519")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["errorCode"] == "upstream_unavailable"
    assert body["message"].startswith("RuntimeError")


@pytest.mark.asyncio
async def test_quotes_cache_get_diff_keeps_last_good_after_failure() -> None:
    ak = FakeTxAkshare(frame=_tx_frame())
    cache = MarketQuotesCache(
        refresh_interval_seconds=300,
        akshare_module=ak,
        now_ms=lambda: 1000,
    )
    assert await cache.refresh() is True

    ak.error = RuntimeError("upstream down")
    assert await cache.refresh() is False

    diff = cache.get_diff(["600519"])["data"]["diff"]
    assert [row["f12"] for row in diff] == ["600519"]
    assert cache.status()["lastError"].startswith("RuntimeError")


@pytest.mark.asyncio
async def test_quotes_cache_refresh_writes_redis_with_ttl() -> None:
    ak = FakeTxAkshare(frame=_tx_frame())
    redis = FakeRedis()
    cache = MarketQuotesCache(
        refresh_interval_seconds=300,
        akshare_module=ak,
        redis_client=redis,
        redis_key_prefix="test",
        now_ms=lambda: 1000,
    )

    assert await cache.refresh() is True

    key = "test:market:quotes:tencent:v1"
    assert redis.expires[key] == 300
    assert "600519" in redis.hashes[key]
    assert "000001" in redis.hashes[key]
    # 2026-11-18 快照 ts 单源透出（试盘现价读侧披露档龄）
    assert redis.expires[key + ":ts"] == 300
    assert redis.values[key + ":ts"] == "1000"


def test_quotes_cache_serves_redis_rows_when_memory_cold() -> None:
    redis = FakeRedis()
    redis.hashes["test:market:quotes:tencent:v1"] = {
        "600519": json.dumps({"f12": "600519", "f14": "贵州茅台", "f2": 1350.6}),
        "000001": json.dumps({"f12": "000001", "f14": "平安银行", "f2": 11.5}),
    }
    cache = MarketQuotesCache(
        refresh_interval_seconds=300,
        redis_client=redis,
        redis_key_prefix="test",
    )

    diff = cache.get_diff(["600519", "000001"])["data"]["diff"]

    assert [row["f12"] for row in diff] == ["600519", "000001"]


@pytest.mark.asyncio
async def test_quotes_cache_redis_failure_falls_back_to_memory() -> None:
    ak = FakeTxAkshare(frame=_tx_frame())
    cache = MarketQuotesCache(
        refresh_interval_seconds=300,
        akshare_module=ak,
        redis_client=FakeRedis(fail=True),
        redis_key_prefix="test",
        now_ms=lambda: 1000,
    )

    assert await cache.refresh() is True
    diff = cache.get_diff(["600519"])["data"]["diff"]

    assert [row["f12"] for row in diff] == ["600519"]  # Redis 故障不阻断


def test_market_overview_normalizes_indices() -> None:
    ak = FakeIndexAkshare(
        frame=pd.DataFrame(
            [
                {
                    "代码": "sh000001",
                    "名称": "上证指数",
                    "最新价": 3832.26,
                    "涨跌额": 27.57,
                    "涨跌幅": 0.725,
                    "昨收": 3804.69,
                    "今开": 3833.53,
                    "最高": 3847.09,
                    "最低": 3822.37,
                    "成交量": 597529427,
                    "成交额": 1187681546393,
                }
            ]
        )
    )
    service = MarketOverviewService(akshare_module=ak, now_ms=lambda: 1)
    snapshot = asyncio_run(service.get_overview())

    assert snapshot["ok"] is True
    assert snapshot["source"] == "akshare-sina-index"
    item = snapshot["items"][0]
    assert item["code"] == "sh000001"
    assert item["name"] == "上证指数"
    assert item["price"] == 3832.26
    assert item["changePct"] == 0.725


def test_market_overview_caches_within_ttl() -> None:
    ak = FakeIndexAkshare(
        frame=pd.DataFrame(
            [
                {
                    "代码": "sh000001",
                    "名称": "上证指数",
                    "最新价": 3832.26,
                    "涨跌额": 27.57,
                    "涨跌幅": 0.725,
                    "昨收": 3804.69,
                    "今开": 3833.53,
                    "最高": 3847.09,
                    "最低": 3822.37,
                    "成交量": 1,
                    "成交额": 2,
                }
            ]
        )
    )
    service = MarketOverviewService(akshare_module=ak, ttl_seconds=10, now_ms=lambda: 100)
    asyncio_run(service.get_overview())
    asyncio_run(service.get_overview())
    assert ak.calls == 1


@pytest.mark.asyncio
async def test_market_overview_serves_from_redis_without_upstream() -> None:
    redis = FakeRedis()
    redis.values["test:market:overview:v1"] = json.dumps(
        {
            "ok": True,
            "source": "akshare-sina-index",
            "timestamp": 1,
            "stale": False,
            "items": [{"code": "sh000001", "name": "上证指数", "price": 3832.26}],
        }
    )
    ak = FakeIndexAkshare()
    service = MarketOverviewService(
        akshare_module=ak,
        redis_client=redis,
        redis_key_prefix="test",
        now_ms=lambda: 1000,
    )

    snapshot = await service.get_overview()

    assert snapshot["items"][0]["code"] == "sh000001"
    assert ak.calls == 0  # Redis 命中不打上游


@pytest.mark.asyncio
async def test_market_overview_writes_redis_after_fetch() -> None:
    redis = FakeRedis()
    ak = FakeIndexAkshare(
        frame=pd.DataFrame(
            [
                {
                    "代码": "sh000001",
                    "名称": "上证指数",
                    "最新价": 3832.26,
                    "涨跌额": 27.57,
                    "涨跌幅": 0.725,
                    "昨收": 3804.69,
                    "今开": 3833.53,
                    "最高": 3847.09,
                    "最低": 3822.37,
                    "成交量": 1,
                    "成交额": 2,
                }
            ]
        )
    )
    service = MarketOverviewService(
        akshare_module=ak,
        redis_client=redis,
        redis_key_prefix="test",
        ttl_seconds=10,
        now_ms=lambda: 1,
    )

    snapshot = await service.get_overview()

    assert snapshot["items"][0]["code"] == "sh000001"
    assert "test:market:overview:v1" in redis.values
    assert redis.expires["test:market:overview:v1"] == 10


@pytest.mark.asyncio
async def test_market_overview_redis_failure_falls_back_to_upstream() -> None:
    ak = FakeIndexAkshare(
        frame=pd.DataFrame(
            [
                {
                    "代码": "sh000001",
                    "名称": "上证指数",
                    "最新价": 3832.26,
                    "涨跌额": 27.57,
                    "涨跌幅": 0.725,
                    "昨收": 3804.69,
                    "今开": 3833.53,
                    "最高": 3847.09,
                    "最低": 3822.37,
                    "成交量": 1,
                    "成交额": 2,
                }
            ]
        )
    )
    service = MarketOverviewService(
        akshare_module=ak,
        redis_client=FakeRedis(fail=True),
        redis_key_prefix="test",
        now_ms=lambda: 1,
    )

    snapshot = await service.get_overview()

    assert snapshot["items"][0]["code"] == "sh000001"  # Redis 故障不阻断


def test_market_overview_route_503_without_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    service = MarketOverviewService(akshare_module=FakeIndexAkshare(error=RuntimeError("boom")))
    monkeypatch.setattr(market_data_routes, "get_market_overview_service", lambda: service)
    app = FastAPI()
    app.include_router(market_data_routes.router)
    client = TestClient(app)

    response = client.get("/api/market/overview")
    assert response.status_code == 503
    body = response.json()
    assert body["ok"] is False
    assert body["errorCode"] == "upstream_unavailable"
    assert body["staleData"] is None


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)


@pytest.mark.asyncio
async def test_quotes_cache_all_codes_in_memory_and_redis_fallback() -> None:
    """all_codes：进程内优先；未就绪回退 Redis hash 字段（东财 universe 唯一来源）。"""
    ak = FakeTxAkshare(frame=_tx_frame())
    cache = MarketQuotesCache(
        refresh_interval_seconds=300,
        akshare_module=ak,
        now_ms=lambda: 1000,
    )

    # 未刷新且无 Redis：空列表（调用方按 universe 缺失处理，不伪装空成功）
    assert cache.all_codes() == []

    await cache.refresh()
    codes = cache.all_codes()
    assert "600519" in codes
    assert all(len(code) == 6 and code.isdigit() for code in codes)

    # 冷启动/重启场景：内存空，Redis hash 兜底（含非法字段过滤）
    class FakeRedis:
        def __init__(self, mapping: dict[bytes, bytes]) -> None:
            self._mapping = mapping

        def hkeys(self, key: str) -> list[bytes]:
            return list(self._mapping.keys())

        def hmget(self, key: str, fields: list[str]) -> list[bytes | None]:
            return [self._mapping.get(field.encode()) for field in fields]

    cold = MarketQuotesCache(
        refresh_interval_seconds=300,
        akshare_module=ak,
        redis_client=FakeRedis(
            {
                b"000001": b"{}",
                b"600519": b"{}",
                b"bad": b"{}",
            }
        ),
        redis_key_prefix="test",
        ttl_seconds=300,
    )
    assert cold.all_codes() == ["000001", "600519"]

    # Redis 异常：告警并返回空，不炸调用方
    class BrokenRedis:
        def hkeys(self, key: str) -> list[bytes]:
            raise RuntimeError("redis down")

    broken = MarketQuotesCache(
        refresh_interval_seconds=300,
        akshare_module=ak,
        redis_client=BrokenRedis(),
        redis_key_prefix="test",
        ttl_seconds=300,
    )
    assert broken.all_codes() == []


# ── 上游超时封顶（2026-10-19 复盘：akshare 同步抓取无超时，曾单源阻塞 130~299s，
#    把采集槽位组拖过 240s 看门狗 —— 当日 6 次掉槽的全部来源）──────────────────


class _HangingIndexAkshare:
    """模拟新浪限流：同步抓取挂住很久（超时后才返回）。"""

    def __init__(self, hang_s: float = 5.0) -> None:
        self.hang_s = hang_s
        self.calls = 0

    def stock_zh_index_spot_sina(self):
        self.calls += 1
        time.sleep(self.hang_s)
        return pd.DataFrame([{"代码": "sh000001", "名称": "上证指数", "最新价": 1.0}])


def test_market_overview_fetch_timeout_raises_without_last_good() -> None:
    ak = _HangingIndexAkshare(hang_s=1.5)
    service = MarketOverviewService(akshare_module=ak, fetch_timeout_s=0.05)

    async def _measure() -> float:
        # 生产是常驻事件循环：调用方在 timeout 后立即拿回控制权。
        # （asyncio.run 的收尾会 join 卡死的线程，故不能在 asyncio.run 外层计时。）
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            await service.get_overview()
        return time.monotonic() - started

    elapsed = asyncio_run(_measure())
    assert elapsed < 1.0  # 调用方不再被 130~299s 的上游拖住


def test_market_overview_fetch_timeout_serves_stale_and_backs_off() -> None:
    good = pd.DataFrame(
        [
            {
                "代码": "sh000001",
                "名称": "上证指数",
                "最新价": 3832.26,
                "涨跌额": 27.57,
                "涨跌幅": 0.725,
            }
        ]
    )
    clock = {"now": 1_000_000}
    good_ak = FakeIndexAkshare(frame=good)
    service = MarketOverviewService(
        akshare_module=good_ak,
        ttl_seconds=10,
        now_ms=lambda: clock["now"],
        fetch_timeout_s=0.05,
        timeout_backoff_s=60.0,
    )
    first = asyncio_run(service.get_overview())
    assert first["stale"] is False

    # TTL 过期 + 上游挂死：超时后退避，返回 last-good 并显式标 stale（暴露不隐藏）
    clock["now"] += 60_000
    service._ak = _HangingIndexAkshare(hang_s=1.5)
    stale = asyncio_run(service.get_overview())
    assert stale["stale"] is True
    assert stale["errorCode"] == "upstream_timeout"
    assert stale["items"][0]["code"] == "sh000001"

    # 退避窗口内不再等上游：立刻返回，且不产生新的上游调用
    calls_before = service._ak.calls
    started = time.monotonic()
    again = asyncio_run(service.get_overview())
    assert time.monotonic() - started < 0.5
    assert again["errorCode"] == "upstream_timeout_backoff"
    assert service._ak.calls == calls_before


def test_market_overview_recovers_after_backoff_window() -> None:
    clock = {"now": 1_000_000}
    hanging = _HangingIndexAkshare(hang_s=0.3)
    service = MarketOverviewService(
        akshare_module=hanging,
        now_ms=lambda: clock["now"],
        fetch_timeout_s=0.05,
        timeout_backoff_s=60.0,
    )
    with pytest.raises(TimeoutError):
        asyncio_run(service.get_overview())

    clock["now"] += 61_000
    time.sleep(0.5)  # 等挂死的抓取真正结束（单 worker 断路器释放）
    good = FakeIndexAkshare(
        frame=pd.DataFrame([{"代码": "sh000001", "名称": "上证指数", "最新价": 3832.26}])
    )
    service._ak = good
    snapshot = asyncio_run(service.get_overview())
    assert snapshot["stale"] is False
    assert good.calls == 1  # 退避窗口结束后恢复真实取数
    assert hanging.calls == 1


def test_market_overview_single_worker_acts_as_circuit_breaker() -> None:
    """挂死的抓取占用唯一 worker：后续提交排队并被超时取消，不再打上游、不堆积线程。"""
    ak = _HangingIndexAkshare(hang_s=0.8)
    clock = {"now": 1_000_000}
    service = MarketOverviewService(
        akshare_module=ak,
        now_ms=lambda: clock["now"],
        fetch_timeout_s=0.05,
        timeout_backoff_s=1.0,
    )

    async def _two_misses() -> tuple[bool, bool]:
        try:
            await service.get_overview()
        except TimeoutError:
            pass
        clock["now"] += 2_000  # 退出退避窗口
        clock["now"] += 0
        service._next_attempt_ms = 0
        second_timed_out = False
        try:
            await service.get_overview()
        except TimeoutError:
            second_timed_out = True
        return True, second_timed_out

    _, second_timed_out = asyncio_run(_two_misses())
    assert ak.calls == 1  # 卡死期间不产生第二次上游调用（断路器生效）
    assert second_timed_out is True


# ── last-good 兜底库（2026-10-19：新鲜缓存 TTL 10s 撑不过重启/上游故障）───────


def _ok_frame(price: float = 3832.26) -> pd.DataFrame:
    return pd.DataFrame(
        [{"代码": "sh000001", "名称": "上证指数", "最新价": price, "涨跌额": 1.0, "涨跌幅": 0.1}]
    )


def test_market_overview_writes_separate_last_good_key() -> None:
    redis = FakeRedis()
    service = MarketOverviewService(
        akshare_module=FakeIndexAkshare(frame=_ok_frame()),
        redis_client=redis,
        redis_key_prefix="test",
        ttl_seconds=10,
        now_ms=lambda: 1000,
    )
    asyncio_run(service.get_overview())

    assert redis.expires["test:market:overview:v1"] == 10  # 新鲜缓存 TTL 不变
    assert redis.expires["test:market:overview:last-good:v1"] == 300  # 兜底库更长


def test_market_overview_timeout_uses_redis_last_good_of_previous_process() -> None:
    """进程重启（内存态丢失）+ 上游超时：仍能拿到 last-good，且必须标 stale。"""
    redis = FakeRedis()
    first = MarketOverviewService(
        akshare_module=FakeIndexAkshare(frame=_ok_frame()),
        redis_client=redis,
        redis_key_prefix="test",
        ttl_seconds=10,
        now_ms=lambda: 1000,
    )
    asyncio_run(first.get_overview())

    # 模拟重启后的新实例：无内存快照、新鲜缓存已过期（10s）
    clock = {"now": 1_000_000}  # 距 timestamp=1000 已很久
    restarted = MarketOverviewService(
        akshare_module=_HangingIndexAkshare(hang_s=0.3),
        redis_client=redis,
        redis_key_prefix="test",
        now_ms=lambda: clock["now"],
        fetch_timeout_s=0.05,
    )
    # 新鲜缓存 key 已过期 → 用会失效的语义：直接从 Redis 删掉新鲜 key 模拟 TTL 到期
    redis.values.pop("test:market:overview:v1", None)
    snapshot = asyncio_run(restarted.get_overview())

    assert snapshot["stale"] is True
    assert snapshot["errorCode"] == "upstream_timeout"
    assert snapshot["items"][0]["code"] == "sh000001"
    assert snapshot["staleSeconds"] is not None and snapshot["staleSeconds"] > 0


def test_market_overview_happy_path_ignores_last_good() -> None:
    """新鲜取数成功时绝不使用 last-good（不把旧数据当新鲜）。"""
    redis = FakeRedis()
    redis.values["test:market:overview:last-good:v1"] = json.dumps(
        {
            "ok": True,
            "source": "akshare-sina-index",
            "timestamp": 1,  # 很旧
            "stale": False,
            "items": [{"code": "sh000001", "name": "旧值", "price": 1.0}],
        }
    )
    service = MarketOverviewService(
        akshare_module=FakeIndexAkshare(frame=_ok_frame(price=3999.0)),
        redis_client=redis,
        redis_key_prefix="test",
        now_ms=lambda: 5000,
    )
    snapshot = asyncio_run(service.get_overview())
    assert snapshot["stale"] is False
    assert snapshot["items"][0].get("price") == 3999.0


# ── 指数源切换：行情桥为主源（2026-10-19，akshare 被风控限流） ──────────────────


@pytest.mark.asyncio
async def test_market_overview_defaults_to_bridge_source() -> None:
    from backend.market_proxy.indices import MarketOverviewService

    calls: list[float] = []

    async def fake_bridge(*, timeout_s: float):
        calls.append(timeout_s)
        return [
            {
                "code": "sh000001",
                "name": "上证指数",
                "price": 3716.02,
                "change": -0.26,
                "changePct": -0.007,
                "prevClose": 3716.28,
                "open": 3694.12,
                "high": 3733.86,
                "low": 3692.29,
                "volume": 303356328,
                "amount": 501436579840.0,
            }
        ]

    service = MarketOverviewService(bridge_fetcher=fake_bridge, now_ms=lambda: 1)
    snapshot = await service.get_overview()

    assert snapshot["ok"] is True
    assert snapshot["source"] == "tdx-bridge-index"
    assert snapshot["items"][0]["code"] == "sh000001"
    assert calls, "桥取数应被调用"


@pytest.mark.asyncio
async def test_market_overview_bridge_failure_serves_last_good_stale() -> None:
    from backend.market_proxy.indices import MarketOverviewService

    state = {"fail": False, "now": 1_000}

    async def fake_bridge(*, timeout_s: float):
        if state["fail"]:
            raise RuntimeError("index bridge snapshot unusable: HTTP 404")
        return [{"code": "sh000001", "price": 3716.02, "change": -0.26, "changePct": -0.007}]

    service = MarketOverviewService(bridge_fetcher=fake_bridge, now_ms=lambda: state["now"])
    first = await service.get_overview()
    assert first["stale"] is False and first["source"] == "tdx-bridge-index"

    # 新鲜缓存过期 + 桥失败 → 必须回退 last-good 并显式标 stale（fail-visible）
    state["fail"] = True
    state["now"] += 60_000
    second = await service.get_overview()

    assert second["stale"] is True
    assert second["errorCode"] == "upstream_error"
    assert second["items"][0]["price"] == 3716.02


@pytest.mark.asyncio
async def test_market_overview_bridge_failure_without_last_good_raises() -> None:
    from backend.market_proxy.indices import MarketOverviewService

    async def failing_bridge(*, timeout_s: float):
        raise RuntimeError("bridge down")

    service = MarketOverviewService(bridge_fetcher=failing_bridge, now_ms=lambda: 1000)
    with pytest.raises(RuntimeError, match="bridge down"):
        await service.get_overview()


@pytest.mark.asyncio
async def test_market_overview_bridge_then_akshare_falls_back() -> None:
    """迁移期选项：桥失败时回退 akshare（默认不走这条路）。"""
    from backend.market_proxy.indices import MarketOverviewService

    async def failing_bridge(*, timeout_s: float):
        raise RuntimeError("bridge down")

    ak = FakeIndexAkshare(
        frame=pd.DataFrame(
            [{"代码": "sh000001", "名称": "上证指数", "最新价": 3716.02, "涨跌额": -0.26}]
        )
    )
    service = MarketOverviewService(
        akshare_module=ak,
        bridge_fetcher=failing_bridge,
        source="bridge_then_akshare",
        now_ms=lambda: 1,
    )

    snapshot = await service.get_overview()

    assert snapshot["source"] == "akshare-sina-index"
    assert snapshot["items"][0]["code"] == "sh000001"
    assert ak.calls == 1


@pytest.mark.asyncio
async def test_market_overview_empty_bridge_result_is_not_cached_as_success() -> None:
    """空 items 不得当成功写缓存/last-good（否则兜底库被清空）。"""
    from backend.market_proxy.indices import MarketOverviewService

    async def empty_bridge(*, timeout_s: float):
        return []

    service = MarketOverviewService(bridge_fetcher=empty_bridge, now_ms=lambda: 1000)
    with pytest.raises(RuntimeError, match="empty items"):
        await service.get_overview()
    assert service._snapshot is None


def test_market_overview_source_resolution_precedence() -> None:
    from backend.market_proxy.indices import MarketOverviewService

    assert MarketOverviewService._resolve_source(None, None, lambda **_: []) == "bridge"
    assert MarketOverviewService._resolve_source(None, object(), None) == "akshare"
    assert MarketOverviewService._resolve_source("akshare", None, None) == "akshare"
    assert MarketOverviewService._resolve_source("bridge_then_akshare", None, None) == "bridge_then_akshare"
    assert MarketOverviewService._resolve_source("nonsense", None, None) == "bridge"
    # 显式 source 优先于"注入即锁定"的启发式（bridge_then_akshare 需要两个源都在）
    assert (
        MarketOverviewService._resolve_source("bridge_then_akshare", object(), lambda **_: [])
        == "bridge_then_akshare"
    )
