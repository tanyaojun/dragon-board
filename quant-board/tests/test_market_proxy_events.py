from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.market_data_routes as market_data_routes
from backend.market_proxy.longhu import LonghuBigOrderService, LonghuIntegrityError
from backend.market_proxy.xuangubao import (
    DEFAULT_EVENT_TYPES,
    _extract_events,
    _filter_supported_events,
    _normalize_count,
    _normalize_types,
    XuangubaoEventService,
)


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _order_row(order_id: int, minute: str) -> list[str]:
    return ["2", str(order_id), "100", "1000", "10", f"2026-07-17 {minute}:00"]


@pytest.mark.asyncio
async def test_longhu_load_page_contract_and_form() -> None:
    forms = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        form = dict(pair.split("=", 1) for pair in body.split("&"))
        forms.append(form)
        rows = [_order_row(i, "09:30") for i in range(250)]
        return httpx.Response(200, json={"errcode": "0", "Total": 250, "List": rows})

    client = _mock_client(handler)
    service = LonghuBigOrderService(client=client, now_ms=lambda: 1)
    payload = await service.load_page("002297", money=0, index=0, limit=300)

    assert payload["errcode"] == "0"
    assert payload["Total"] == 250
    assert len(payload["List"]) == 250
    assert forms[0]["a"] == "GetMainMonitor_w30"
    assert forms[0]["st"] == "200"
    assert forms[0]["StockID"] == "002297"


@pytest.mark.asyncio
async def test_longhu_load_all_day_pagination_and_last_good() -> None:
    calls = {"n": 0, "fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["fail"]:
            raise httpx.ConnectError("blocked")
        form = dict(
            pair.split("=", 1) for pair in request.content.decode().split("&")
        )
        index = int(form["Index"])
        if index == 0:
            return httpx.Response(
                200,
                json={
                    "errcode": "0",
                    "Total": 201,
                    "List": [_order_row(i, "09:30") for i in range(200)],
                },
            )
        return httpx.Response(
            200,
            json={"errcode": "0", "Total": 201, "List": [_order_row(200, "15:00")]},
        )

    client = _mock_client(handler)
    service = LonghuBigOrderService(client=client, now_ms=lambda: 1)
    first = await service.load_all_day("002297")
    assert len(first["List"]) == 201

    calls["fail"] = True
    # 上游失败保留 last-good（fail-visible）
    stale = await service.load_all_day("002297")
    assert len(stale["List"]) == 201


@pytest.mark.asyncio
async def test_longhu_load_all_day_empty_and_failure() -> None:
    client = _mock_client(
        lambda request: httpx.Response(200, json={"errcode": "0", "Total": 0, "List": []})
    )
    service = LonghuBigOrderService(client=client, now_ms=lambda: 1)
    payload = await service.load_all_day("002297")
    assert payload == {"List": []}

    failing = _mock_client(lambda request: (_ for _ in ()).throw(httpx.ConnectError("boom")))
    empty_service = LonghuBigOrderService(client=failing, now_ms=lambda: 1)
    with pytest.raises(httpx.ConnectError):
        await empty_service.load_all_day("002297")


@pytest.mark.asyncio
async def test_longhu_rebuild_rejects_truncated_page() -> None:
    """短页不得被静默拼接：缺行会导致后续偏移错位，必须抛完整性错误（fail-visible）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        form = dict(
            pair.split("=", 1) for pair in request.content.decode().split("&")
        )
        index = int(form["Index"])
        if index == 0:
            # 第一页应返回 200 行，只给 150 行 = 截断
            return httpx.Response(
                200,
                json={
                    "errcode": "0",
                    "Total": 250,
                    "List": [_order_row(i, "09:30") for i in range(150)],
                },
            )
        return httpx.Response(
            200,
            json={
                "errcode": "0",
                "Total": 250,
                "List": [_order_row(150 + i, "09:30") for i in range(100)],
            },
        )

    client = _mock_client(handler)
    service = LonghuBigOrderService(client=client, now_ms=lambda: 1)
    with pytest.raises(LonghuIntegrityError, match="truncated Longhu page response"):
        await service.load_all_day("002297")


def test_xuangubao_normalize_count_and_types() -> None:
    assert _normalize_count(None) == 100
    assert _normalize_count("500") == 200
    assert _normalize_count("0") == 100
    assert _normalize_types("10001,99999,10005") == [10001, 10005]
    assert _normalize_types("") == DEFAULT_EVENT_TYPES
    assert all(t in set(_normalize_types("")) for t in (10001, 11001))


def test_xuangubao_extract_and_filter_events() -> None:
    events = [
        {"event_type": 10001, "title": "a"},
        {"event_type": 999, "title": "b"},
        {"stock_abnormal_event_data": {"event_type": 11001}},
    ]
    filtered = _filter_supported_events(events)
    assert [e.get("title") for e in filtered] == ["a", None]


def test_xuangubao_extract_list_data_shape() -> None:
    payload = {
        "code": 20000,
        "message": "ok",
        "data": [
            {"id": 1, "event_type": 10001},
            {"id": 2, "event_type": 10002},
        ],
    }
    assert len(_extract_events(payload)) == 2
    assert len(_filter_supported_events(_extract_events(payload))) == 2


@pytest.mark.asyncio
async def test_xuangubao_events_host_fallback() -> None:
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("first host down")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "stock_abnormal_event_data": [{"event_type": 10001}],
                    "plate_abnormal_event_data": [{"event_type": 999}],
                },
            },
        )

    client = _mock_client(handler)
    service = XuangubaoEventService(client=client, now_ms=lambda: 1)
    payload = await service.get_events()
    assert payload["ok"] is True
    assert len(payload["data"]) == 1
    assert state["n"] == 2


def _route_app(monkeypatch: pytest.MonkeyPatch, **services: Any) -> TestClient:
    app = FastAPI()
    app.include_router(market_data_routes.router)

    class StubLonghu:
        async def load_page(self, stock_code, **kwargs):
            return {"errcode": "0", "Total": 1, "List": [["2", "1", "100", "1000", "10", "2026-07-17 09:30:00"]]}

        async def load_all_day(self, stock_code, **kwargs):
            return {"List": [["2", "1", "100", "1000", "10", "2026-07-17 09:30:00"]]}

    class StubEvents:
        async def get_events(self, count=None, types=None):
            return {"ok": True, "source": "xuangubao-events", "data": [{"event_type": 10001}]}

    monkeypatch.setattr(market_data_routes, "get_longhu_service", lambda: StubLonghu())
    monkeypatch.setattr(market_data_routes, "get_xuangubao_service", lambda: StubEvents())
    return TestClient(app)


def test_big_order_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _route_app(monkeypatch)

    response = client.get("/api/big-order/main-monitor?stockCode=002297&limit=10")
    assert response.status_code == 200
    assert response.json()["List"][0][0] == "2"
    assert "ok" not in response.json()

    response = client.get("/api/big-order/all-day?stockCode=002297")
    assert response.status_code == 200
    assert len(response.json()["List"]) == 1

    response = client.get("/api/big-order/main-monitor")
    assert response.status_code == 400
    assert response.json()["errorCode"] == "missing_stock_code"


def test_big_order_routes_coerce_invalid_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class CapturingLonghu:
        async def load_page(self, stock_code, **kwargs):
            captured["page"] = kwargs
            return {"errcode": "0", "Total": 0, "List": []}

        async def load_all_day(self, stock_code, **kwargs):
            captured["all_day"] = kwargs
            return {"List": []}

    monkeypatch.setattr(market_data_routes, "get_longhu_service", lambda: CapturingLonghu())
    app = FastAPI()
    app.include_router(market_data_routes.router)
    client = TestClient(app)

    response = client.get(
        "/api/big-order/main-monitor?stockCode=002297&money=abc&index=xyz&limit=99999"
    )
    assert response.status_code == 200
    assert captured["page"] == {"money": 0, "index": 0, "limit": 500}

    response = client.get("/api/big-order/all-day?stockCode=002297&money=-3")
    assert response.status_code == 200
    assert captured["all_day"] == {"money": 0}


def test_big_order_routes_degrade_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Failing:
        async def load_page(self, *args, **kwargs):
            raise RuntimeError("blocked")

        async def load_all_day(self, *args, **kwargs):
            raise RuntimeError("blocked")

    monkeypatch.setattr(market_data_routes, "get_longhu_service", lambda: Failing())
    app = FastAPI()
    app.include_router(market_data_routes.router)
    client = TestClient(app)

    response = client.get("/api/big-order/all-day?stockCode=002297")
    body = response.json()
    assert response.status_code == 200
    assert body["degraded"] is True
    assert body["data"] == {"List": []}


def test_xuangubao_events_route(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _route_app(monkeypatch)
    response = client.get("/api/xuangubao/events?count=50&types=10001")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"][0]["event_type"] == 10001
