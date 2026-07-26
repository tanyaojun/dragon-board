from __future__ import annotations

import pytest

import backend.main as main


@pytest.mark.asyncio
async def test_fastapi_lifecycle_starts_and_stops_fund_scheduler_once(monkeypatch) -> None:
    events: list[str] = []

    class FakeScheduler:
        class Service:
            async def aclose(self) -> None:
                events.append("close")

        service = Service()

        def start(self) -> None:
            events.append("start")

        async def stop(self) -> None:
            events.append("stop")

    monkeypatch.setattr(main, "theme_fund_scheduler", FakeScheduler())
    monkeypatch.setattr(main, "stock_name_refresh_scheduler", FakeScheduler())
    monkeypatch.setattr(main.snapshot_collector_scheduler, "start", lambda: None)
    monkeypatch.setattr(main.theme_mapping_refresh_scheduler, "start", lambda: None)
    monkeypatch.setattr(main.snapshot_collector_scheduler, "stop", _noop_async)
    monkeypatch.setattr(main.theme_mapping_refresh_scheduler, "stop", _noop_async)

    await main.on_startup()
    await main.on_shutdown()

    assert events == ["start", "start", "stop", "stop", "close"]


async def _noop_async() -> None:
    return None
