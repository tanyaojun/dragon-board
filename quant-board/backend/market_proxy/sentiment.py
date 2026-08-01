from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import httpx


class SentimentCompositeService:
    """综合情绪聚合：overview（指数）+ 涨停池 + 昨日涨停/异动。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        quant_board_base: str = "http://127.0.0.1:8000",
        ttl_seconds: float = 30.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._base = quant_board_base.rstrip("/")
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache: dict[str, Any] | None = None
        self._cached_at_ms = 0

    async def get(self) -> dict[str, Any]:
        now_ms = self._now_ms()
        if self._cache is not None and now_ms - self._cached_at_ms < self._ttl_ms:
            return self._cache
        client = self._client or _get_sentiment_client()
        urls = [
            f"{self._base}/api/market/overview",
            f"{self._base}/api/limitup/10jqka",
            f"{self._base}/api/surge-stock/performance",
        ]
        results = await asyncio.gather(*(client.get(url, timeout=8.0) for url in urls), return_exceptions=True)
        overview = limitup = surge = None
        degraded = False
        for index, result in enumerate(results):
            if isinstance(result, Exception) or result.status_code >= 400:
                degraded = True
                continue
            try:
                body = result.json()
            except ValueError:
                degraded = True
                continue
            if index == 0:
                overview = body
            elif index == 1:
                limitup = body
            else:
                surge = body
        payload = {
            "ok": True,
            "degraded": degraded,
            "timestamp": now_ms,
            "overview": overview,
            "limitup": limitup,
            "yesterdayPerformance": surge,
        }
        self._cache = payload
        self._cached_at_ms = now_ms
        return payload


_sentiment_client: httpx.AsyncClient | None = None
_sentiment_service: SentimentCompositeService | None = None


def _get_sentiment_client() -> httpx.AsyncClient:
    global _sentiment_client
    if _sentiment_client is None:
        _sentiment_client = httpx.AsyncClient(timeout=8.0)
    return _sentiment_client


def get_sentiment_service() -> SentimentCompositeService:
    global _sentiment_service
    if _sentiment_service is None:
        _sentiment_service = SentimentCompositeService()
    return _sentiment_service


async def close_sentiment_client() -> None:
    global _sentiment_client
    client = _sentiment_client
    _sentiment_client = None
    if client is not None:
        await client.aclose()
