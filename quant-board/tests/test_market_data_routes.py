from __future__ import annotations

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.market_data_routes as market_data_routes
from backend.market_proxy.indices import MarketOverviewService
from backend.market_proxy.quotes import MarketQuotesCache, to_tencent_diff_item


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
