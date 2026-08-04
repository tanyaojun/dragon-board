"""Market data gateway for snapshot collector providers.

``HttpMarketDataGateway`` keeps the legacy path (requests go through the
proxy-server, which forwards to the 8000 API).  ``InProcessMarketDataGateway``
calls ``market_proxy`` service singletons directly inside the standalone
collector process (``backend.collector_main``), so snapshot collection no
longer depends on the 8000 API process (removes the collector -> proxy -> 8000
self-loop).
"""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse


class MarketDataGateway(Protocol):
    def get_json(self, url: str, timeout_s: float) -> Any: ...
    def post_json(self, url: str, timeout_s: float, payload: Any | None = None) -> Any: ...


class HttpMarketDataGateway:
    """Legacy behaviour: HTTP requests to the configured base URL."""

    def __init__(self, client: Any = None) -> None:
        self._client_override = client

    def _client(self) -> Any:
        if self._client_override is not None:
            return self._client_override
        # 每次请求解析：兼容测试对 providers._get_proxy_http_client 的 patch，
        # 避免共享网关单例缓存跨用例的假客户端。
        from .providers import _get_proxy_http_client

        return _get_proxy_http_client()

    def get_json(self, url: str, timeout_s: float) -> Any:
        response = self._client().get(url, timeout=timeout_s)
        response.raise_for_status()
        return response.json()

    def post_json(self, url: str, timeout_s: float, payload: Any | None = None) -> Any:
        headers = {"Content-Type": "application/json"} if payload is not None else None
        response = self._client().post(
            url,
            content=json.dumps(payload) if payload is not None else None,
            headers=headers,
            timeout=timeout_s,
        )
        response.raise_for_status()
        return response.json()


def _degraded(error_code: str, message: str) -> dict[str, Any]:
    """Explicit degraded envelope (fail-visible); never fakes an empty success."""
    return {
        "ok": False,
        "degraded": True,
        "errorCode": error_code,
        "message": message,
        "rc": 0,
        "data": {"diff": []},
    }


class InProcessMarketDataGateway:
    """Direct in-process access to market_proxy service singletons.

    Supports only the routes the collector providers use.  Cold caches return
    an explicit degraded envelope; the collector process's background refresh
    tasks keep the caches warm.
    """

    def get_json(self, url: str, timeout_s: float) -> Any:
        del timeout_s
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        path = parsed.path

        if path == "/api/quotes/tencent":
            from backend.market_proxy.quotes import get_market_quotes_cache

            cache = get_market_quotes_cache()
            status = cache.status()
            if status["rowCount"] == 0:
                return _degraded(
                    status["lastError"] or "cache_not_ready",
                    status["lastError"] or "cache_not_ready",
                )
            codes = (query.get("codes") or [""])[0].split(",")
            return cache.get_diff(codes)

        raise RuntimeError(f"in-process gateway does not support GET {path}")

    def post_json(self, url: str, timeout_s: float, payload: Any | None = None) -> Any:
        del timeout_s, payload
        raise RuntimeError(f"in-process gateway does not support POST {urlparse(url).path}")


def create_gateway(in_process: bool = False) -> MarketDataGateway:
    return InProcessMarketDataGateway() if in_process else HttpMarketDataGateway()
