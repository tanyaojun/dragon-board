from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from backend.services.market.ths_main_monitor_service import ThsMainMonitorService


def _payload(*, buy: object = "1.2亿", sell: object = "3500万", date: str = "2026-07-24") -> dict:
    return {
        "errorcode": 0,
        "title": {"mainbuy": buy, "mainsell": sell},
        "list": [{"otime": f"{date} 14:59:59", "nature": "主力主买"}],
        "pricechange": [[0, date.replace("-", "") + "1459"]],
    }


def _service(handler, *, now_ms=lambda: 1_000_000) -> ThsMainMonitorService:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ThsMainMonitorService(client=client, now_ms=now_ms, request_timeout_seconds=1)

@pytest.mark.asyncio
async def test_raw_payload_returns_stale_last_good_after_upstream_failure() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, json=_payload())
        return httpx.Response(503, json={"message": "unavailable"})

    now = 1_000_000
    service = _service(handler, now_ms=lambda: now)

    fresh = await service.load_raw("002297")
    now += 4_000
    stale = await service.load_raw("002297", force=True)

    assert fresh["stale"] is False
    assert stale["stale"] is True
    assert stale["sessionDate"] == "2026-07-24"
    assert stale["fetchedAt"] == 1_000_000
    assert stale["servedAt"] == 1_004_000
    assert stale["data"]["title"]["mainbuy"] == "1.2亿"
    await service.aclose()


