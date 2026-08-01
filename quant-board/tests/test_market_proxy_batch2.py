from __future__ import annotations

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
