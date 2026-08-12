from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

import pytest

from backend.market_proxy.akshare_fund_provider import (
    AkshareFundBatch,
    AkshareFundProviderError,
)
from backend.services.market.fund_scheduler import MarketFundScheduler


TZ = ZoneInfo("Asia/Shanghai")


class FakeCache:
    def __init__(self, reject_codes: set[str] | None = None) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.reject_codes = reject_codes or set()
        self.redis_data_present = True

    def has_redis_data(self) -> bool:
        return self.redis_data_present

    def memory_rows(self) -> list[dict[str, object]]:
        return [dict(v) for v in self.rows.values()]

    def get_latest(self, codes: list[str]) -> dict[str, dict[str, object]]:
        return {code: self.rows[code] for code in codes if code in self.rows}

    def put(self, row: dict[str, object]) -> dict[str, object]:
        code = str(row["code"])
        if code in self.reject_codes:
            raise ValueError("rejected row for test")
        saved = {**row, "version": len(self.rows) + 1}
        self.rows[code] = saved
        return saved

    def put_many(
        self,
        rows: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        saved_rows: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
        for row in rows:
            code = str(row.get("code") or "")
            if code in self.reject_codes:
                failures.append({"code": code, "reason": "rejected row for test"})
                continue
            saved = {**row, "version": len(self.rows) + 1}
            self.rows[code] = saved
            saved_rows.append(saved)
        return saved_rows, failures


class FakeStream:
    def __init__(self, codes: list[str]) -> None:
        self.codes = codes
        self.published: list[dict[str, object]] = []

    def market_codes(self) -> list[str]:
        return list(self.codes)

    def publish(self, rows: list[dict[str, object]]) -> None:
        self.published.extend(rows)


class BlockableCache(FakeCache):
    """put() 阻塞直到测试解除，用于模拟 Redis 慢/挂起下的保存超时。"""

    def __init__(self) -> None:
        super().__init__()
        self.release_puts = threading.Event()

    def put(self, row: dict[str, object]) -> dict[str, object]:
        self.release_puts.wait(timeout=10)
        return super().put(row)

    def put_many(
        self,
        rows: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        self.release_puts.wait(timeout=10)
        return super().put_many(rows)


class FakeProvider:
    def __init__(
        self,
        error_code: str | None = None,
        batch: AkshareFundBatch | None = None,
        hang: bool = False,
    ) -> None:
        self.error_code = error_code
        self.batch = batch
        self.hang = hang
        self.calls: list[str] = []

    async def fetch_all(self, *, session_date: str) -> AkshareFundBatch:
        self.calls.append(session_date)
        if self.error_code:
            raise AkshareFundProviderError(self.error_code)
        if self.hang:
            await asyncio.sleep(3600)
        if self.batch is not None:
            return self.batch
        return AkshareFundBatch(
            rows=[self.row("000001", session_date), self.row("000002", session_date)],
            failures=[],
            fetched_at_ms=1,
            session_date=session_date,
        )

    @staticmethod
    def row(code: str, session_date: str, zlje: float = 12.5) -> dict[str, object]:
        return {
            "code": code,
            "zlje": zlje,
            "sessionDate": session_date,
            "tradingDate": session_date,
            "source": "ths_main_monitor",
            "moneyFlowSource": "ths_main_monitor",
            "sourceTs": 1,
        }


def _scheduler(
    *,
    provider: FakeProvider,
    now: Callable[[], datetime] | None = None,
    current: datetime | None = None,
    cache: FakeCache | None = None,
    stream: FakeStream | None = None,
    is_trading_day=lambda _date: True,
    **kwargs,
) -> MarketFundScheduler:
    return MarketFundScheduler(
        cache=cache or FakeCache(),
        stream=stream or FakeStream(["000001", "000002"]),
        provider=provider,
        is_trading_day=is_trading_day,
        now=now or (lambda: current),
        **kwargs,
    )


def _mutable_clock(value: datetime) -> tuple[dict[str, datetime], Callable[[], datetime]]:
    box = {"current": value}
    return box, (lambda: box["current"])


@pytest.mark.asyncio
async def test_no_owner_makes_zero_requests() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    provider = FakeProvider()
    scheduler = _scheduler(provider=provider, current=current, stream=FakeStream([]))

    assert await scheduler.run_once() is False
    assert provider.calls == []


@pytest.mark.asyncio
async def test_fetch_timeout_opens_cooldown_and_exposes_status() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    provider = FakeProvider(hang=True)
    scheduler = _scheduler(
        provider=provider,
        current=current,
        fetch_timeout_seconds=0.1,
    )

    assert await scheduler.run_once() is True

    status = scheduler.status()
    assert status["lastError"] == "ths_timeout"
    assert status["circuitOpenUntil"] >= current.timestamp() + 300
    assert status["lastRowCount"] == 0
    assert status["primedCodes"] == 0


@pytest.mark.asyncio
async def test_empty_batch_is_exposed_in_status_not_silently_successful() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    provider = FakeProvider(
        batch=AkshareFundBatch(
            rows=[],
            failures=[],
            fetched_at_ms=1,
            session_date="2026-07-30",
        )
    )
    scheduler = _scheduler(provider=provider, current=current)

    await scheduler.run_once()

    status = scheduler.status()
    assert status["lastError"] == "empty_batch"
    assert status["lastRowCount"] == 0
    assert status["primedCodes"] == 0


@pytest.mark.asyncio
async def test_startup_warmup_fetches_once_even_without_subscribers() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    provider = FakeProvider()
    cache = FakeCache()
    scheduler = _scheduler(
        provider=provider,
        current=current,
        cache=cache,
        stream=FakeStream([]),
    )

    assert await scheduler.run_once(ignore_subscribers=True) is True

    # 启动预热不依赖 WebSocket 订阅者：全市场抓取写入缓存，首屏可直接命中
    assert provider.calls == ["2026-07-30"]
    assert "000001" in cache.rows
    assert scheduler.status()["primedCodes"] == 2


@pytest.mark.asyncio
async def test_off_session_primes_once_then_idles() -> None:
    current = datetime(2026, 7, 30, 11, 31, 0, tzinfo=TZ)
    provider = FakeProvider()
    scheduler = _scheduler(provider=provider, current=current)

    await scheduler.run_once()
    await scheduler.run_once()

    assert provider.calls == ["2026-07-30"]
    assert scheduler.status()["primedCodes"] == 2


@pytest.mark.asyncio
async def test_intraday_refreshes_on_interval() -> None:
    box, now = _mutable_clock(datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ))
    provider = FakeProvider()
    scheduler = _scheduler(
        provider=provider,
        now=now,
        min_refresh_interval_seconds=60,
        refresh_interval_seconds=300,
    )

    await scheduler.run_once()
    await scheduler.run_once()
    assert provider.calls == ["2026-07-30"]

    box["current"] = datetime(2026, 7, 30, 10, 5, 5, tzinfo=TZ)
    await scheduler.run_once()
    assert provider.calls == ["2026-07-30", "2026-07-30"]


@pytest.mark.asyncio
async def test_partial_cache_rejection_keeps_valid_rows_and_reports() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    cache = FakeCache(reject_codes={"000002"})
    stream = FakeStream(["000001", "000002"])
    provider = FakeProvider()
    scheduler = _scheduler(provider=provider, current=current, cache=cache, stream=stream)

    await scheduler.run_once()

    assert "000001" in cache.rows
    assert "000002" not in cache.rows
    assert [row["code"] for row in stream.published] == ["000001"]
    status = scheduler.status()
    assert status["lastRowCount"] == 1
    assert status["parseFailureCount"] == 1
    assert status["parseFailureSamples"][0]["code"] == "000002"


@pytest.mark.asyncio
async def test_systemic_failure_opens_circuit_and_keeps_last_good() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    provider = FakeProvider(error_code="ths_rate_limited")
    scheduler = _scheduler(provider=provider, current=current)

    await scheduler.run_once()
    assert scheduler.status()["circuitOpenUntil"] >= current.timestamp() + 300

    await scheduler.run_once()
    assert provider.calls == ["2026-07-30"]
    assert scheduler.status()["lastError"] == "ths_rate_limited"


@pytest.mark.asyncio
async def test_non_systemic_failure_retries_after_min_interval() -> None:
    box, now = _mutable_clock(datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ))
    provider = FakeProvider(error_code="ths_timeout")
    scheduler = _scheduler(
        provider=provider,
        now=now,
        min_refresh_interval_seconds=60,
        refresh_interval_seconds=300,
    )

    await scheduler.run_once()
    assert scheduler.status()["circuitOpenUntil"] == 0
    await scheduler.run_once()
    assert provider.calls == ["2026-07-30"]

    box["current"] = datetime(2026, 7, 30, 10, 1, 5, tzinfo=TZ)
    await scheduler.run_once()
    assert provider.calls == ["2026-07-30", "2026-07-30"]


@pytest.mark.asyncio
async def test_after_close_finalizes_once() -> None:
    current = datetime(2026, 7, 30, 15, 1, 0, tzinfo=TZ)
    provider = FakeProvider()
    scheduler = _scheduler(provider=provider, current=current)

    await scheduler.run_once()
    await scheduler.run_once()

    assert provider.calls == ["2026-07-30"]


@pytest.mark.asyncio
async def test_new_session_date_resets_prime() -> None:
    non_trading_days = {"2026-08-01", "2026-08-02"}

    def is_trading(d: object) -> bool:
        return str(d) not in non_trading_days

    box, now = _mutable_clock(datetime(2026, 8, 1, 9, 0, 0, tzinfo=TZ))
    provider = FakeProvider()
    scheduler = _scheduler(
        provider=provider,
        now=now,
        is_trading_day=is_trading,
    )

    await scheduler.run_once()
    assert provider.calls == ["2026-07-31"]

    box["current"] = datetime(2026, 8, 3, 10, 0, 0, tzinfo=TZ)
    await scheduler.run_once()
    assert provider.calls == ["2026-07-31", "2026-08-03"]


@pytest.mark.asyncio
async def test_provider_batch_failures_are_exposed_in_status() -> None:
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    provider = FakeProvider(
        batch=AkshareFundBatch(
            rows=[FakeProvider.row("000001", "2026-07-30")],
            failures=[{"code": "300999", "reason": "invalid_stock_code_or_zlje"}],
            fetched_at_ms=1,
            session_date="2026-07-30",
        )
    )
    scheduler = _scheduler(provider=provider, current=current)

    await scheduler.run_once()

    status = scheduler.status()
    assert status["parseFailureCount"] == 1
    assert status["parseFailureSamples"][0]["code"] == "300999"
    assert status["lastRowCount"] == 1


@pytest.mark.asyncio
async def test_save_timeout_keeps_rows_for_retry() -> None:
    """保存超时进入待重试缓冲，不丢弃原始行；冷却后先重试缓冲再保存新批次。"""
    current = datetime(2026, 7, 30, 10, 0, 0, tzinfo=TZ)
    box, now = _mutable_clock(current)
    cache = BlockableCache()
    stream = FakeStream(["000001", "000002"])
    provider = FakeProvider()
    scheduler = _scheduler(
        provider=provider,
        now=now,
        cache=cache,
        stream=stream,
        save_timeout_seconds=0.2,
        systemic_cooldown_seconds=60.0,
        min_refresh_interval_seconds=30.0,
        refresh_interval_seconds=300.0,
    )

    assert await scheduler.run_once() is True
    assert scheduler._last_error == "save_timeout"
    assert len(scheduler._pending_save_rows) == 2
    assert cache.rows == {}

    # 解除阻塞并越过冷却期：下个周期先重试缓冲（2 行），再保存新批次（2 行）
    cache.release_puts.set()
    box["current"] = current.replace(minute=current.minute + 5)
    assert await scheduler.run_once() is True
    assert scheduler._last_error is None
    assert scheduler._pending_save_rows == []
    assert len(cache.rows) == 2
    assert len(stream.published) == 4

