from __future__ import annotations

import pytest

from backend.snapshot_collector.gateway import InProcessMarketDataGateway


class FakeQuotesCache:
    def __init__(self, row_count: int = 2, last_error: str | None = None) -> None:
        self._row_count = row_count
        self._last_error = last_error

    def status(self) -> dict:
        return {"rowCount": self._row_count, "lastError": self._last_error}

    def get_diff(self, codes: list[str]) -> dict:
        return {
            "rc": 0,
            "data": {
                "diff": [
                    {"f12": codes[0], "f14": "测试", "f2": 10.0},
                    {"f12": codes[1], "f14": "测试2", "f2": 20.0},
                ]
            },
        }


def test_inprocess_gateway_quotes_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeQuotesCache()
    monkeypatch.setattr(
        "backend.market_proxy.quotes.get_market_quotes_cache", lambda: fake
    )
    gateway = InProcessMarketDataGateway()
    body = gateway.get_json(
        "http://127.0.0.1:1/api/quotes/tencent?codes=000001,600000", 5.0
    )
    assert body["rc"] == 0
    assert len(body["data"]["diff"]) == 2


def test_inprocess_gateway_quotes_cold_cache_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeQuotesCache(row_count=0, last_error="fetch_timeout")
    monkeypatch.setattr(
        "backend.market_proxy.quotes.get_market_quotes_cache", lambda: fake
    )
    gateway = InProcessMarketDataGateway()
    body = gateway.get_json("http://127.0.0.1:1/api/quotes/tencent?codes=000001", 5.0)
    assert body["ok"] is False
    assert body["degraded"] is True
    assert body["errorCode"] == "fetch_timeout"


def test_inprocess_gateway_hotlist_cold_cache_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeHotlistService:
        _cache: dict = {}
        _ttl_ms = 60000

    monkeypatch.setattr(
        "backend.market_proxy.hotlists.get_hotlist_service",
        lambda: FakeHotlistService(),
    )
    gateway = InProcessMarketDataGateway()
    body = gateway.post_json("http://127.0.0.1:1/api/eastmoney/hot", 5.0, {})
    assert body["ok"] is False
    assert body["degraded"] is True
    assert body["errorCode"] == "cache_not_ready"


def test_inprocess_gateway_unsupported_path_raises() -> None:
    gateway = InProcessMarketDataGateway()
    with pytest.raises(RuntimeError):
        gateway.get_json("http://127.0.0.1:1/api/unknown", 5.0)


def test_collector_http_client_disables_env_proxy() -> None:
    """采集器本地客户端禁用系统代理（iKuuuVPN 等会把 localhost 劫持为 502）。"""
    from backend.snapshot_collector.providers import _get_proxy_http_client

    client = _get_proxy_http_client()
    assert client.trust_env is False
