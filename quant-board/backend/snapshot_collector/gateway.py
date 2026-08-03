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
import re
import time
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


def _read_service_cache(service: Any, key: str, ttl_ms: int) -> Any | None:
    """Synchronously read a market_proxy service's process-local last-good cache.

    Returns the cached payload when fresh, else ``None`` (cold cache).  This
    lets the in-process gateway avoid awaiting async service singletons from
    collector worker threads.
    """
    cache = getattr(service, "_cache", None)
    if isinstance(cache, dict):
        entry = cache.get(key)
        if isinstance(entry, dict):
            fetched_at = int(entry.get("fetched_at_ms") or 0)
            if fetched_at > 0 and int(time.time() * 1000) - fetched_at < ttl_ms:
                return entry.get("payload")
    return None


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

        if path == "/api/limitup/ths/pools":
            from backend.market_proxy.limitup import get_limitup_service

            date = (query.get("date") or [""])[0]
            service = get_limitup_service()
            payload = _read_service_cache(
                service, f"ths-pools:{date}", ttl_ms=int(getattr(service, "_ttl_ms", 30000))
            )
            if payload is None:
                return {
                    "ok": False,
                    "degraded": True,
                    "date": date,
                    "source": "limitup-ths-pools",
                    "errorCode": "cache_not_ready",
                    "message": "in-process limitup cache not ready",
                    "pools": {},
                    "errors": [],
                }
            return payload

        raise RuntimeError(f"in-process gateway does not support GET {path}")

    def post_json(self, url: str, timeout_s: float, payload: Any | None = None) -> Any:
        del timeout_s, payload
        path = urlparse(url).path
        match = re.fullmatch(r"/api/([a-z0-9]+)/hot", path)
        if match:
            platform = match.group(1)
            from backend.market_proxy.hotlists import get_hotlist_service

            service = get_hotlist_service()
            entry = _read_service_cache(
                service, platform, ttl_ms=int(getattr(service, "_ttl_ms", 60000))
            )
            if entry is None:
                return {
                    "ok": False,
                    "degraded": True,
                    "source": platform,
                    "errorCode": "cache_not_ready",
                    "message": "in-process hotlist cache not ready",
                    "data": [],
                }
            return entry
        raise RuntimeError(f"in-process gateway does not support POST {path}")


def create_gateway(in_process: bool = False) -> MarketDataGateway:
    return InProcessMarketDataGateway() if in_process else HttpMarketDataGateway()
