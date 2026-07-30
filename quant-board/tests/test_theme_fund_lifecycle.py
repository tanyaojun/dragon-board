from __future__ import annotations

import pytest

import backend.main as main


def test_fastapi_module_does_not_own_theme_fund_scheduler() -> None:
    assert not hasattr(main, "theme_fund_scheduler")


def test_fastapi_module_owns_market_fund_scheduler() -> None:
    assert hasattr(main, "market_fund_scheduler")


def test_market_fund_stream_uses_market_api_namespace() -> None:
    paths = {route.path for route in main.app.routes}
    assert "/api/market/fund-stream" in paths
    assert "/api/themes/fund-stream" not in paths


@pytest.mark.asyncio
async def test_fastapi_lifecycle_starts_and_stops_stock_name_scheduler_once(monkeypatch) -> None:
    events: list[str] = []

    class FakeScheduler:
        def start(self) -> None:
            events.append("start")

        async def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(main, "stock_name_refresh_scheduler", FakeScheduler())
    monkeypatch.setattr(main.snapshot_collector_scheduler, "start", lambda: None)
    monkeypatch.setattr(main.theme_mapping_refresh_scheduler, "start", lambda: None)
    monkeypatch.setattr(main.snapshot_collector_scheduler, "stop", _noop_async)
    monkeypatch.setattr(main.theme_mapping_refresh_scheduler, "stop", _noop_async)
    monkeypatch.setattr(
        main,
        "close_ths_main_monitor_service",
        lambda: _record_async(events, "ths-close"),
        raising=False,
    )

    await main.on_startup()
    await main.on_shutdown()

    assert events == ["start", "stop", "ths-close"]


async def _noop_async() -> None:
    return None


async def _record_async(events: list[str], value: str) -> None:
    events.append(value)
