from __future__ import annotations

import asyncio

import httpx
import pytest

from backend.ths_main_monitor_service import ThsMainMonitorService


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
async def test_load_row_parses_yuan_and_session_date() -> None:
    service = _service(lambda request: httpx.Response(200, json=_payload()))

    row = await service.load_row("002297")

    assert row == {
        "code": "002297",
        "zlje": 85_000_000.0,
        "sessionDate": "2026-07-24",
        "source": "ths_main_monitor",
        "moneyFlowSource": "ths_main_monitor",
        "sourceTs": 1_000_000,
    }
    await service.aclose()


@pytest.mark.asyncio
async def test_load_row_uses_configured_upstream_url() -> None:
    requested_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, json=_payload())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    service = ThsMainMonitorService(
        client=client,
        upstream_url="https://ths.example.test/custom",
        request_timeout_seconds=1,
        now_ms=lambda: 1_785_151_200_123,
    )

    await service.load_row("002297")

    assert requested_urls == [
        "https://ths.example.test/custom?op=mainMonitorDetail&stockcode=002297&_=1785151200123"
    ]
    await service.aclose()


@pytest.mark.asyncio
async def test_effective_concurrency_never_exceeds_configured_maximum() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=_payload()))
    )
    service = ThsMainMonitorService(client=client, max_concurrency=1)

    await service.set_effective_concurrency(2)

    assert service._effective_concurrency == 1
    await service.aclose()


@pytest.mark.asyncio
async def test_batch_keeps_success_when_another_payload_is_invalid() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        code = request.url.params["stockcode"]
        return httpx.Response(200, json=_payload() if code == "002297" else _payload(buy="bad"))

    service = _service(handler)

    result = await service.load_batch(["002297", "600000"], concurrency=2)

    assert [row["code"] for row in result["rows"]] == ["002297"]
    assert result["failures"] == [{"code": "600000", "errorCode": "ths_invalid_payload"}]
    await service.aclose()


@pytest.mark.asyncio
async def test_non_numeric_errorcode_is_reported_as_invalid_payload() -> None:
    payload = _payload()
    payload["errorcode"] = "invalid"
    service = _service(lambda request: httpx.Response(200, json=payload))

    result = await service.load_batch(["002297"], concurrency=1)

    assert result["rows"] == []
    assert result["failures"] == [{"code": "002297", "errorCode": "ths_invalid_payload"}]
    await service.aclose()


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


@pytest.mark.asyncio
async def test_shared_cooldown_blocks_raw_and_batch_upstream_calls() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_payload())

    service = _service(handler)
    service.enter_cooldown(30)

    with pytest.raises(RuntimeError, match="ths_rate_limited"):
        await service.load_raw("002297", force=True)
    result = await service.load_batch(["002297"], concurrency=2)

    assert calls == 0
    assert result["failures"] == [{"code": "002297", "errorCode": "ths_rate_limited"}]
    await service.aclose()


@pytest.mark.asyncio
async def test_service_gate_caps_combined_concurrency() -> None:
    active = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, json=_payload())

    service = _service(handler)

    await asyncio.gather(
        service.load_batch(["000001", "000002"], concurrency=2),
        service.load_raw("002297", force=True),
    )

    assert peak <= 2
    await service.aclose()
