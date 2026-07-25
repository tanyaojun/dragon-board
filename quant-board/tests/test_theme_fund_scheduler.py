from __future__ import annotations

from datetime import datetime
from threading import get_ident
import asyncio
import time
from zoneinfo import ZoneInfo

import pytest

from backend.theme_fund_scheduler import ThemeFundScheduler


TZ = ZoneInfo("Asia/Shanghai")


class FakeCache:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.version = 0

    def get_latest(self, codes: list[str]) -> dict[str, dict[str, object]]:
        return {code: self.rows[code] for code in codes if code in self.rows}

    def put(self, row: dict[str, object]) -> dict[str, object]:
        self.version += 1
        stored = {**row, "version": self.version}
        self.rows[str(row["code"])] = stored
        return stored


class FakeStream:
    def __init__(self, market: list[str], priority: list[str]) -> None:
        self.market = market
        self.priority = priority
        self.published: list[list[dict[str, object]]] = []

    def market_codes(self) -> list[str]:
        return list(self.market)

    def priority_codes(self) -> list[str]:
        return list(self.priority)

    def publish(self, rows: list[dict[str, object]]) -> None:
        self.published.append(rows)


class FakeService:
    def __init__(self, failures: set[str] | dict[str, str] | None = None) -> None:
        self.failures = (
            {code: "ths_timeout" for code in failures}
            if isinstance(failures, set)
            else failures or {}
        )
        self.calls: list[tuple[list[str], int]] = []
        self.cooldowns: list[int] = []
        self.concurrency: list[int] = []

    async def load_batch(self, codes: list[str], *, concurrency: int) -> dict:
        self.calls.append((list(codes), concurrency))
        return {
            "rows": [
                {
                    "code": code,
                    "zlje": 10.0,
                    "sessionDate": "2026-07-24",
                    "moneyFlowSource": "ths_main_monitor",
                    "sourceTs": 100,
                }
                for code in codes
                if code not in self.failures
            ],
            "failures": [
                {"code": code, "errorCode": self.failures[code]}
                for code in codes
                if code in self.failures
            ],
        }

    def enter_cooldown(self, seconds: int) -> None:
        self.cooldowns.append(seconds)

    async def set_effective_concurrency(self, value: int) -> None:
        self.concurrency.append(value)


@pytest.mark.asyncio
async def test_missing_priority_is_published_before_market_remainder() -> None:
    cache = FakeCache()
    stream = FakeStream(["000001", "000002"], ["600000"])
    service = FakeService()
    scheduler = ThemeFundScheduler(
        cache=cache,
        stream=stream,
        service=service,
        is_trading_day=lambda value: True,
        now=lambda: datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
        batch_size=1,
    )

    await scheduler.run_once()

    assert service.calls[0][0] == ["600000"]
    assert stream.published[0][0]["code"] == "600000"


@pytest.mark.asyncio
async def test_success_uses_configured_concurrency_and_refresh_jitter() -> None:
    current = datetime(2026, 7, 24, 10, 0, tzinfo=TZ)
    cache = FakeCache()
    service = FakeService()
    scheduler = ThemeFundScheduler(
        cache=cache,
        stream=FakeStream(["000001"], ["000001"]),
        service=service,
        is_trading_day=lambda value: True,
        now=lambda: current,
        concurrency=1,
        jitter=lambda interval: 2.5,
    )

    await scheduler.run_once()

    assert service.calls == [(["000001"], 1)]
    assert scheduler._next_due["000001"] == current.timestamp() + 32.5


@pytest.mark.asyncio
async def test_success_recovery_never_exceeds_configured_concurrency() -> None:
    service = FakeService()
    scheduler = ThemeFundScheduler(
        cache=FakeCache(),
        stream=FakeStream(["000001", "000002", "000003"], []),
        service=service,
        is_trading_day=lambda value: True,
        now=lambda: datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
        batch_size=1,
        concurrency=1,
        jitter=lambda interval: 0,
    )

    await scheduler.run_once()
    await scheduler.run_once()
    await scheduler.run_once()

    assert [call[1] for call in service.calls] == [1, 1, 1]
    assert service.concurrency == [1]


@pytest.mark.asyncio
async def test_partial_failure_keeps_success_and_retries_only_failed_code() -> None:
    cache = FakeCache()
    stream = FakeStream(["000001", "000002"], [])
    service = FakeService({"000002"})
    scheduler = ThemeFundScheduler(
        cache=cache,
        stream=stream,
        service=service,
        is_trading_day=lambda value: True,
        now=lambda: datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
        batch_size=5,
    )

    await scheduler.run_once()

    assert set(cache.rows) == {"000001"}
    assert scheduler.failure_count("000002") == 1
    assert stream.published[0][0]["code"] == "000001"


@pytest.mark.asyncio
async def test_non_trading_warm_cache_does_not_request_upstream() -> None:
    cache = FakeCache()
    cache.rows["000001"] = {"code": "000001", "zlje": 1}
    stream = FakeStream(["000001"], [])
    service = FakeService()
    scheduler = ThemeFundScheduler(
        cache=cache,
        stream=stream,
        service=service,
        is_trading_day=lambda value: False,
        now=lambda: datetime(2026, 7, 25, 10, 0, tzinfo=TZ),
    )

    await scheduler.run_once()

    assert service.calls == []


@pytest.mark.asyncio
async def test_empty_owner_never_uses_theme_mapping_or_calls_upstream() -> None:
    calendar_calls = 0

    def calendar(value) -> bool:
        nonlocal calendar_calls
        calendar_calls += 1
        return False

    service = FakeService()
    scheduler = ThemeFundScheduler(
        cache=FakeCache(),
        stream=FakeStream([], []),
        service=service,
        is_trading_day=calendar,
        now=lambda: datetime(2026, 7, 25, 10, 0, tzinfo=TZ),
    )

    await scheduler.run_once()

    assert service.calls == []
    assert calendar_calls == 0


@pytest.mark.asyncio
async def test_missing_failure_respects_per_code_backoff() -> None:
    current = datetime(2026, 7, 24, 10, 0, tzinfo=TZ)
    service = FakeService({"000001"})
    scheduler = ThemeFundScheduler(
        cache=FakeCache(),
        stream=FakeStream(["000001"], []),
        service=service,
        is_trading_day=lambda value: True,
        now=lambda: current,
    )

    await scheduler.run_once()
    await scheduler.run_once()

    assert len(service.calls) == 1


@pytest.mark.asyncio
async def test_partial_upstream_unavailable_does_not_trigger_global_cooldown() -> None:
    service = FakeService({"000002": "ths_upstream_unavailable"})
    scheduler = ThemeFundScheduler(
        cache=FakeCache(),
        stream=FakeStream(["000001", "000002"], []),
        service=service,
        is_trading_day=lambda value: True,
        now=lambda: datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
    )

    await scheduler.run_once()

    assert service.cooldowns == []
    assert service.concurrency == []


@pytest.mark.asyncio
async def test_calendar_lookup_runs_off_the_event_loop_thread() -> None:
    event_loop_thread = get_ident()
    calendar_threads: list[int] = []

    def calendar(value) -> bool:
        calendar_threads.append(get_ident())
        return True

    scheduler = ThemeFundScheduler(
        cache=FakeCache(),
        stream=FakeStream(["000001"], []),
        service=FakeService(),
        is_trading_day=calendar,
        now=lambda: datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
    )

    await scheduler.run_once()

    assert calendar_threads
    assert calendar_threads[0] != event_loop_thread


@pytest.mark.asyncio
async def test_cache_io_does_not_block_the_event_loop() -> None:
    events: list[str] = []

    class SlowCache(FakeCache):
        def get_latest(self, codes: list[str]) -> dict[str, dict[str, object]]:
            events.append("cache-start")
            time.sleep(0.05)
            events.append("cache-end")
            return super().get_latest(codes)

    scheduler = ThemeFundScheduler(
        cache=SlowCache(),
        stream=FakeStream(["000001"], []),
        service=FakeService(),
        is_trading_day=lambda value: True,
        now=lambda: datetime(2026, 7, 24, 10, 0, tzinfo=TZ),
    )

    refresh = asyncio.create_task(scheduler.run_once())
    await asyncio.sleep(0.01)
    events.append("event-loop-tick")
    await refresh

    assert events.index("event-loop-tick") < events.index("cache-end")


@pytest.mark.asyncio
async def test_after_close_refreshes_each_owner_once_per_trading_day() -> None:
    cache = FakeCache()
    cache.rows["000001"] = {"code": "000001", "zlje": 1}
    service = FakeService()
    scheduler = ThemeFundScheduler(
        cache=cache,
        stream=FakeStream(["000001"], []),
        service=service,
        is_trading_day=lambda value: True,
        now=lambda: datetime(2026, 7, 24, 15, 1, tzinfo=TZ),
    )

    await scheduler.run_once()
    await scheduler.run_once()

    assert [call[0] for call in service.calls] == [["000001"]]


@pytest.mark.asyncio
async def test_after_close_retries_when_cache_rejects_older_candidate() -> None:
    current = datetime(2026, 7, 24, 15, 1, tzinfo=TZ)

    class RejectingOlderCache(FakeCache):
        def put(self, row: dict[str, object]) -> dict[str, object]:
            return dict(self.rows[str(row["code"])])

    cache = RejectingOlderCache()
    cache.rows["000001"] = {
        "code": "000001",
        "zlje": 1.0,
        "sessionDate": "2026-07-24",
        "moneyFlowSource": "ths_main_monitor",
        "sourceTs": 200,
        "version": 7,
    }
    service = FakeService()
    scheduler = ThemeFundScheduler(
        cache=cache,
        stream=FakeStream(["000001"], []),
        service=service,
        is_trading_day=lambda value: True,
        now=lambda: current,
    )

    await scheduler.run_once()
    current = datetime(2026, 7, 24, 15, 5, tzinfo=TZ)
    await scheduler.run_once()

    assert [call[0] for call in service.calls] == [["000001"], ["000001"]]
