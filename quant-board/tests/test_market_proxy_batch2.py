from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.market_data_routes as market_data_routes
from backend.market_proxy.hotlists import HotlistService, generate_cls_sign
from backend.market_proxy.limitup import LimitUpService
from backend.market_proxy.sentiment import SentimentCompositeService
from backend.market_proxy.surge import SurgeStockService


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class FakeRedisClient:
    """进程内 Redis 假实现：get/setex 足够 HotlistService 共享缓存使用。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.writes: list[tuple[str, int, str]] = []

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(self, key: str, ttl_seconds: int, value: str) -> None:
        self.store[key] = value
        self.writes.append((key, int(ttl_seconds), value))


def test_cls_sign_matches_legacy_js() -> None:
    params, sign = generate_cls_sign()
    assert params == {"app": "cailianpress", "os": "android", "sv": "835"}
    text = "app=cailianpress&os=android&sv=835"
    expected = hashlib.md5(hashlib.sha1(text.encode()).hexdigest().encode()).hexdigest()
    assert sign == expected


@pytest.mark.asyncio
async def test_hotlist_xueqiu_requires_cookie_and_fetches() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert "Cookie" in request.headers
        return httpx.Response(200, json={"data": {"items": [{"code": "SH600519"}]}})

    client = _mock_client(handler)
    service = HotlistService(client=client, xueqiu_cookie="abc", now_ms=lambda: 1)
    payload = await service.get("xueqiu")
    assert payload["data"]["items"][0]["code"] == "SH600519"
    await service.get("xueqiu")
    assert calls["n"] == 1  # TTL 缓存命中


@pytest.mark.asyncio
async def test_hotlist_xueqiu_without_cookie_degrades() -> None:
    client = _mock_client(lambda request: httpx.Response(200, json={}))
    service = HotlistService(client=client, xueqiu_cookie="", now_ms=lambda: 1)
    payload = await service.get("xueqiu")
    assert payload["ok"] is False
    assert payload["data"] == {"data": {"items": []}}


@pytest.mark.asyncio
async def test_hotlist_ths_parses_text_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "eq.10jqka.com.cn" in str(request.url)
        return httpx.Response(
            200,
            text=json.dumps({"data": {"stock_list": [{"code": "1", "name": "x", "rate": "10.0"}]}}),
            headers={"content-type": "application/json"},
        )

    client = _mock_client(handler)
    service = HotlistService(client=client, now_ms=lambda: 1)
    payload = await service.get("ths")
    assert payload["data"]["stock_list"][0]["code"] == "1"


@pytest.mark.asyncio
async def test_hotlist_eastmoney_post_and_stale_on_failure() -> None:
    state = {"fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        if state["fail"]:
            raise httpx.ConnectError("blocked")
        return httpx.Response(200, json={"data": [{"sc": "SZ000001", "sn": "平安银行"}]})

    client = _mock_client(handler)
    service = HotlistService(client=client, now_ms=lambda: 1)
    first = await service.get("eastmoney")
    assert first["data"][0]["sc"] == "SZ000001"

    state["fail"] = True
    stale = await service.get("eastmoney")
    # 上游失败仍返回 last-good（fail-visible）
    assert stale["data"][0]["sc"] == "SZ000001"


@pytest.mark.asyncio
async def test_hotlist_failure_without_cache_returns_fallback() -> None:
    client = _mock_client(lambda request: (_ for _ in ()).throw(httpx.ConnectError("boom")))
    service = HotlistService(client=client, now_ms=lambda: 1)
    payload = await service.get("dzh")
    assert payload["ok"] is False
    assert payload["data"] == {"result": []}


@pytest.mark.asyncio
async def test_hotlist_retries_once_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("flaky upstream")
        return httpx.Response(200, json={"data": {"result": [{"600000": 100}]}})

    client = _mock_client(handler)
    service = HotlistService(client=client, retry_delay_seconds=0, now_ms=lambda: 1)
    payload = await service.get("dzh")
    assert calls["n"] == 2
    assert payload["data"] == {"result": [{"600000": 100}]}


@pytest.mark.asyncio
async def test_hotlist_failure_is_negative_cached() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("upstream down")

    client = _mock_client(handler)
    service = HotlistService(client=client, retries=0, now_ms=lambda: 1000)
    first = await service.get("dzh")
    assert first["ok"] is False
    assert calls["n"] == 1

    second = await service.get("dzh")
    assert second["ok"] is False
    assert calls["n"] == 1  # 负缓存 TTL 内不再打上游


@pytest.mark.asyncio
async def test_hotlist_negative_cache_expires_and_refetches() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("upstream down")

    client = _mock_client(handler)
    now_times = iter([1000, 1000, 1000, 12000, 12000])
    service = HotlistService(
        client=client,
        retries=0,
        negative_ttl_seconds=10,
        now_ms=lambda: next(now_times),
    )
    first = await service.get("dzh")
    assert first["ok"] is False
    second = await service.get("dzh")
    assert second["ok"] is False
    assert calls["n"] == 1

    third = await service.get("dzh")
    assert third["ok"] is False
    assert calls["n"] == 2  # 负缓存过期后重新打上游


@pytest.mark.asyncio
async def test_hotlist_success_cache_ttl_counts_from_completion() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": {"result": [{"600000": 1}]}})

    client = _mock_client(handler)
    now_times = iter([1000, 65000, 66000])
    service = HotlistService(
        client=client,
        ttl_seconds=60,
        retries=0,
        now_ms=lambda: next(now_times),
    )
    await service.get("dzh")
    payload = await service.get("dzh")
    assert payload["data"] == {"result": [{"600000": 1}]}
    assert calls["n"] == 1  # TTL 从抓取完成时刻起算


@pytest.mark.asyncio
async def test_hotlist_negative_cache_ttl_counts_from_completion() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("upstream down")

    client = _mock_client(handler)
    now_times = iter([1000, 65000, 66000])
    service = HotlistService(
        client=client,
        retries=0,
        negative_ttl_seconds=15,
        now_ms=lambda: next(now_times),
    )
    first = await service.get("dzh")
    assert first["ok"] is False
    second = await service.get("dzh")
    assert second["ok"] is False
    assert calls["n"] == 1  # 负缓存 TTL 从失败完成时刻起算


@pytest.mark.asyncio
async def test_hotlist_redis_hit_skips_upstream() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": {"result": [{"600000": 1}]}})

    client = _mock_client(handler)
    redis_client = FakeRedisClient()
    redis_client.store["market:hotlist:dzh:v1"] = json.dumps(
        {
            "payload": {"data": {"result": [{"600000": 1}]}},
            "fetched_at_ms": 1,
            "degraded": False,
        }
    )
    service = HotlistService(client=client, redis_client=redis_client, now_ms=lambda: 1000)

    payload = await service.get("dzh")

    assert payload["data"]["result"][0]["600000"] == 1
    assert calls["n"] == 0  # Redis 命中不打上游


@pytest.mark.asyncio
async def test_hotlist_redis_miss_fetches_and_writes_success() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": {"result": [{"600000": 1}]}})

    client = _mock_client(handler)
    redis_client = FakeRedisClient()
    service = HotlistService(client=client, redis_client=redis_client, now_ms=lambda: 1000)

    payload = await service.get("dzh")

    assert payload["data"]["result"][0]["600000"] == 1
    assert calls["n"] == 1
    assert "market:hotlist:dzh:v1" in redis_client.store
    entry = json.loads(redis_client.store["market:hotlist:dzh:v1"])
    assert entry["degraded"] is False


@pytest.mark.asyncio
async def test_hotlist_failure_writes_negative_redis_cache() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("upstream down")

    client = _mock_client(handler)
    redis_client = FakeRedisClient()
    service = HotlistService(client=client, redis_client=redis_client, retries=0, now_ms=lambda: 1000)

    payload = await service.get("dzh")

    assert payload["ok"] is False
    entry = json.loads(redis_client.store["market:hotlist:dzh:v1"])
    assert entry["degraded"] is True
    assert entry["payload"]["ok"] is False
    key, ttl_seconds, _ = redis_client.writes[-1]
    assert key == "market:hotlist:dzh:v1"
    assert ttl_seconds == 15  # 负缓存短 TTL


@pytest.mark.asyncio
async def test_hotlist_redis_unavailable_falls_back_without_blocking() -> None:
    class BrokenRedisClient:
        def get(self, key: str) -> str:
            raise RuntimeError("redis down")

        def setex(self, key: str, ttl_seconds: int, value: str) -> None:
            raise RuntimeError("redis down")

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"data": {"result": [{"600000": 1}]}})

    client = _mock_client(handler)
    service = HotlistService(
        client=client,
        redis_client=BrokenRedisClient(),
        now_ms=lambda: 1000,
    )

    payload = await service.get("dzh")

    # 缓存故障不阻断数据：仍打上游并返回
    assert payload["data"]["result"][0]["600000"] == 1
    assert calls["n"] == 1


def _hotlist_ok_handler(request: httpx.Request) -> httpx.Response:
    """按平台返回合法载荷，覆盖八平台全部上游 URL。"""
    url = str(request.url)
    if "xueqiu.com" in url:
        return httpx.Response(200, json={"data": {"items": [{"code": "SH600519"}]}})
    if "cls.cn" in url:
        return httpx.Response(200, json={"errno": 0, "data": [{"stock": {"StockID": "1"}}]})
    if "eastmoney.com" in url:
        return httpx.Response(200, json={"data": [{"sc": "SZ000001"}]})
    if "10jqka.com" in url:
        return httpx.Response(
            200,
            text=json.dumps({"data": {"stock_list": [{"code": "1"}]}}),
            headers={"content-type": "application/json"},
        )
    if "longhuvip.com" in url:
        return httpx.Response(200, json={"List": [["1", "开盘啦", "1", "1", "1"]]})
    if "tdx.com.cn" in url:
        return httpx.Response(200, json=[["0", "", "100", ""], ["1", "600000", "浦发银行", "1", "1", "1", "1", "1", "1", "1", "1"]])
    if "tgb.cn" in url:
        return httpx.Response(200, json={"dto": [{"fullCode": "600000"}]})
    if "dzh.com.cn" in url:
        return httpx.Response(200, json={"result": [{"600000": 100}]})
    return httpx.Response(404)


@pytest.mark.asyncio
async def test_hotlist_refresh_all_prefetches_every_platform_into_redis() -> None:
    client = _mock_client(_hotlist_ok_handler)
    redis_client = FakeRedisClient()
    service = HotlistService(
        client=client,
        redis_client=redis_client,
        xueqiu_cookie="test-cookie",
        retry_delay_seconds=0,
        now_ms=lambda: 1,
    )

    summary = await service.refresh_all()

    assert summary["total"] == 8
    assert summary["ok"] == 8
    assert summary["degraded"] == 0
    for platform in ("xueqiu", "cls", "eastmoney", "ths", "kpl", "tdx", "tgb", "dzh"):
        assert summary["platforms"][platform]["ok"] is True
        key = f"market:hotlist:{platform}:v1"
        assert key in redis_client.store
        entry = json.loads(redis_client.store[key])
        assert entry["degraded"] is False


@pytest.mark.asyncio
async def test_hotlist_refresh_all_keeps_other_platforms_when_one_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "tdx.com.cn" in str(request.url):
            raise httpx.ConnectError("tdx upstream down")
        return _hotlist_ok_handler(request)

    client = _mock_client(handler)
    redis_client = FakeRedisClient()
    service = HotlistService(
        client=client,
        redis_client=redis_client,
        xueqiu_cookie="test-cookie",
        retry_delay_seconds=0,
        now_ms=lambda: 1,
    )

    summary = await service.refresh_all()

    assert summary["total"] == 8
    assert summary["ok"] == 7
    assert summary["degraded"] == 1
    assert summary["platforms"]["tdx"]["ok"] is False
    tdx_entry = json.loads(redis_client.store["market:hotlist:tdx:v1"])
    assert tdx_entry["degraded"] is True
    # 其余平台照常写入正缓存
    ths_entry = json.loads(redis_client.store["market:hotlist:ths:v1"])
    assert ths_entry["degraded"] is False


@pytest.mark.asyncio
async def test_hotlist_scheduler_prefetches_immediately_and_stops() -> None:
    client = _mock_client(_hotlist_ok_handler)
    service = HotlistService(
        client=client,
        xueqiu_cookie="test-cookie",
        retry_delay_seconds=0,
        now_ms=lambda: 1,
    )

    service.start(interval_seconds=3600)
    assert service.status()["running"] is True

    # 启动后应立即完成一轮预取（首屏零等待的数据源）
    for _ in range(100):
        if service.status()["lastRefresh"] is not None:
            break
        await asyncio.sleep(0.01)
    assert service.status()["lastRefresh"] is not None
    assert service.status()["lastRefresh"]["ok"] == 8

    await service.stop()
    assert service.status()["running"] is False


@pytest.mark.asyncio
async def test_hotlist_scheduler_start_is_idempotent() -> None:
    client = _mock_client(_hotlist_ok_handler)
    service = HotlistService(client=client, retry_delay_seconds=0, now_ms=lambda: 1)

    service.start(interval_seconds=3600)
    first_task = service._task
    service.start(interval_seconds=3600)
    assert service._task is first_task

    await service.stop()
    assert service.status()["running"] is False


@pytest.mark.asyncio
async def test_limitup_list_validates_and_caches() -> None:
    calls = {"n": 0}
    payload_body = {"status_code": 0, "data": {"info": [{"code": "000001"}], "page_info": {"total": 1}}}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=payload_body)

    client = _mock_client(handler)
    service = LimitUpService(client=client, now_ms=lambda: 1)
    payload = await service.get_limit_up_list("20260731")
    assert payload["data"]["info"][0]["code"] == "000001"
    await service.get_limit_up_list("20260731")
    assert calls["n"] == 1

    bad_client = _mock_client(lambda request: httpx.Response(200, json={"data": {}}))
    bad_service = LimitUpService(client=bad_client, now_ms=lambda: 1)
    with pytest.raises(ValueError):
        await bad_service.get_limit_up_list("20260731")


@pytest.mark.asyncio
async def test_limitup_ths_pools_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "get_drawdown_stocks" in url:
            return httpx.Response(200, json={"data": {"stock_list": [{"code": "1"}]}})
        return httpx.Response(200, json={"data": {"info": [{"code": "2"}]}})

    client = _mock_client(handler)
    service = LimitUpService(client=client, now_ms=lambda: 1)
    payload = await service.get_ths_pools("20260731")
    assert payload["ok"] is True
    assert set(payload["pools"].keys()) == {"one", "two", "three", "four", "high", "failed", "rushing", "drawdown"}
    assert payload["pools"]["drawdown"]["items"][0]["code"] == "1"
    assert payload["pools"]["one"]["items"][0]["code"] == "2"
    assert payload["errors"] == []


@pytest.mark.asyncio
async def test_surge_stock_service() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "flash-api.xuangubao.cn" in str(request.url)
        return httpx.Response(200, json={"data": [{"code": "000001"}]})

    client = _mock_client(handler)
    service = SurgeStockService(client=client, now_ms=lambda: 1)
    payload = await service.get_performance()
    assert payload["data"][0]["code"] == "000001"


@pytest.mark.asyncio
async def test_sentiment_composite_degrades_per_leg() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/market/overview":
            return httpx.Response(200, json={"ok": True, "items": []})
        if path == "/api/limitup/10jqka":
            return httpx.Response(503, json={"ok": False})
        if path == "/api/surge-stock/performance":
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    client = _mock_client(handler)
    service = SentimentCompositeService(client=client, now_ms=lambda: 1)
    payload = await service.get()
    assert payload["ok"] is True
    assert payload["degraded"] is True
    assert payload["overview"]["items"] == []
    assert payload["limitup"] is None
    assert payload["yesterdayPerformance"]["data"] == []


def _route_app(monkeypatch: pytest.MonkeyPatch, **services: Any) -> TestClient:
    app = FastAPI()
    app.include_router(market_data_routes.router)

    class Stub:
        def __init__(self, payload=None, error: Exception | None = None) -> None:
            self.payload = payload
            self.error = error

        async def get(self, *args, **kwargs):
            if self.error is not None:
                raise self.error
            return self.payload

        async def get_limit_up_list(self, date):
            return await self.get(date)

        async def get_ths_pools(self, date):
            return await self.get(date)

    monkeypatch.setattr(market_data_routes, "get_hotlist_service", lambda: Stub(payload={"data": {"items": []}}))
    monkeypatch.setattr(market_data_routes, "get_limitup_service", lambda: Stub(payload={"data": {"info": []}}))
    monkeypatch.setattr(market_data_routes, "get_surge_stock_service", lambda: Stub(payload={"data": []}))
    monkeypatch.setattr(
        market_data_routes,
        "get_sentiment_service",
        lambda: Stub(payload={"ok": True, "degraded": False}),
    )
    return TestClient(app)


def test_platform_hot_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _route_app(monkeypatch)
    response = client.get("/api/xueqiu/hot")
    assert response.status_code == 200
    assert response.json()["data"]["items"] == []

    response = client.post("/api/eastmoney/hot")
    assert response.status_code == 200

    response = client.get("/api/eastmoney/hot")
    assert response.status_code == 404


def test_limitup_and_surge_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _route_app(monkeypatch)
    response = client.get("/api/limitup/10jqka?date=20260731")
    assert response.status_code == 200
    assert response.json()["data"]["info"] == []

    response = client.get("/api/limitup/ths/pools?date=20260731")
    assert response.status_code == 200

    response = client.get("/api/surge-stock/performance")
    assert response.status_code == 200

    response = client.get("/api/sentiment/composite")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_limitup_route_degrades_on_upstream_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing:
        async def get_limit_up_list(self, date):
            raise RuntimeError("blocked")

    monkeypatch.setattr(market_data_routes, "get_limitup_service", lambda: Failing())
    app = FastAPI()
    app.include_router(market_data_routes.router)
    client = TestClient(app)

    response = client.get("/api/limitup/10jqka")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["data"] == {"data": {"info": []}}
