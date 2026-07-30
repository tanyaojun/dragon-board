from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.market_fund_scheduler import MarketFundScheduler


TZ = ZoneInfo("Asia/Shanghai")


class FakeCache:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}

    def get_latest(self, codes: list[str]) -> dict[str, dict[str, object]]:
        return {code: self.rows[code] for code in codes if code in self.rows}

    def put(self, row: dict[str, object]) -> dict[str, object]:
        saved = {**row, "version": len(self.rows) + 1}
        self.rows[str(row["code"])] = saved
        return saved


class FakeStream:
    def __init__(self, codes: list[str]) -> None:
        self.codes = codes
        self.published: list[dict[str, object]] = []

    def market_codes(self) -> list[str]:
        return list(self.codes)

    def publish(self, rows: list[dict[str, object]]) -> None:
        self.published.extend(rows)


class FakeService:
    def __init__(self, error_code: str | None = None) -> None:
        self.error_code = error_code
        self.calls: list[str] = []

    async def load_summary_row(self, code: str) -> dict:
        self.calls.append(code)
        if self.error_code:
            from backend.ths_main_monitor_service import ThsMainMonitorError
            raise ThsMainMonitorError(self.error_code)
        return {"code": code, "zlje": 12.5, "sessionDate": "2026-07-30", "moneyFlowSource": "ths_main_monitor", "sourceTs": 1}


@pytest.mark.asyncio
async def test_no_owner_and_lunch_break_make_zero_requests() -> None:
    service = FakeService()
    current = datetime(2026, 7, 30, 11, 31, tzinfo=TZ)
    scheduler = MarketFundScheduler(
        cache=FakeCache(), stream=FakeStream([]), service=service,
        is_trading_day=lambda _date: True, now=lambda: current,
    )
    await scheduler.run_once()
    scheduler.stream.codes = ["000001"]
    await scheduler.run_once()
    assert service.calls == []


@pytest.mark.asyncio
async def test_single_flight_hard_rate_limit_and_last_good_publish() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    service = FakeService()
    stream = FakeStream(["000001", "000002"])
    scheduler = MarketFundScheduler(
        cache=FakeCache(), stream=stream, service=service,
        is_trading_day=lambda _date: True, now=lambda: current, min_request_interval_seconds=2,
    )
    await scheduler.run_once()
    await scheduler.run_once()
    assert service.calls == ["000001"]
    assert stream.published[0]["zlje"] == 12.5
    assert "zljzb" not in stream.published[0]


@pytest.mark.asyncio
async def test_systemic_failure_opens_five_minute_circuit() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    service = FakeService("ths_rate_limited")
    scheduler = MarketFundScheduler(
        cache=FakeCache(), stream=FakeStream(["000001", "000002"]), service=service,
        is_trading_day=lambda _date: True, now=lambda: current,
    )
    await scheduler.run_once()
    assert scheduler.status()["circuitOpenUntil"] >= current.timestamp() + 300
    await scheduler.run_once()
    assert service.calls == ["000001"]


@pytest.mark.asyncio
async def test_visible_p0_deadline_preempts_market_remainder() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    service = FakeService()
    scheduler = MarketFundScheduler(
        cache=FakeCache(), stream=FakeStream(["000001", "000002", "000003"]),
        service=service, is_trading_day=lambda _date: True, now=lambda: current,
        p0_size=1, p0_interval_seconds=60, p1_interval_seconds=900,
    )
    await scheduler.run_once()
    scheduler._next_request_at = 0
    current = datetime(2026, 7, 30, 10, 0, 2, tzinfo=TZ)
    await scheduler.run_once()
    scheduler._next_request_at = 0
    current = datetime(2026, 7, 30, 10, 1, 0, tzinfo=TZ)
    await scheduler.run_once()
    assert service.calls == ["000001", "000002", "000001"]


@pytest.mark.asyncio
async def test_after_close_covers_each_owner_once_then_freezes() -> None:
    current = datetime(2026, 7, 30, 15, 1, tzinfo=TZ)
    service = FakeService()
    scheduler = MarketFundScheduler(
        cache=FakeCache(), stream=FakeStream(["000001", "000002"]),
        service=service, is_trading_day=lambda _date: True, now=lambda: current,
    )
    for second in (1, 3, 5):
        current = datetime(2026, 7, 30, 15, 1, second, tzinfo=TZ)
        await scheduler.run_once()
    assert service.calls == ["000001", "000002"]
