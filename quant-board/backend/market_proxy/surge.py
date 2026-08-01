from __future__ import annotations

import time
from typing import Any, Callable

import httpx


class SurgeStockService:
    """昨日涨停/异动股表现：选股宝 flash-api 直连，进程内短缓存。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        ttl_seconds: float = 30.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache: dict[str, Any] | None = None
        self._cached_at_ms = 0

    async def get_performance(self) -> Any:
        now_ms = self._now_ms()
        if self._cache is not None and now_ms - self._cached_at_ms < self._ttl_ms:
            return self._cache
        response = await (self._client or _get_surge_client()).get(
            "https://flash-api.xuangubao.cn/api/surge_stock/stocks",
            params={"normal": "true", "uplimit": "true"},
            timeout=8.0,
        )
        response.raise_for_status()
        payload = response.json()
        self._cache = payload
        self._cached_at_ms = now_ms
        return payload


_surge_client: httpx.AsyncClient | None = None
_surge_service: SurgeStockService | None = None


def _get_surge_client() -> httpx.AsyncClient:
    global _surge_client
    if _surge_client is None:
        _surge_client = httpx.AsyncClient(timeout=8.0)
    return _surge_client


def get_surge_stock_service() -> SurgeStockService:
    global _surge_service
    if _surge_service is None:
        _surge_service = SurgeStockService()
    return _surge_service


async def close_surge_client() -> None:
    global _surge_client
    client = _surge_client
    _surge_client = None
    if client is not None:
        await client.aclose()
