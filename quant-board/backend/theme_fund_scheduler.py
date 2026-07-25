from __future__ import annotations

import asyncio
import logging
import random
from datetime import date, datetime
from typing import Callable
from zoneinfo import ZoneInfo

from backend.snapshot_collector.trading_calendar import (
    TradingCalendarUnavailable,
    is_trading_day,
)
from backend.theme_fund_cache import ThemeFundCache, get_theme_fund_cache
from backend.theme_fund_stream import ThemeFundStream, get_theme_fund_stream
from backend.ths_main_monitor_service import (
    ThsMainMonitorService,
    get_ths_main_monitor_service,
)


logger = logging.getLogger(__name__)
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class ThemeFundScheduler:
    def __init__(
        self,
        *,
        cache: ThemeFundCache,
        stream: ThemeFundStream,
        service: ThsMainMonitorService,
        is_trading_day: Callable = is_trading_day,
        now: Callable[[], datetime] | None = None,
        batch_size: int = 5,
        p0_interval_seconds: int = 30,
        p1_interval_seconds: int = 180,
        concurrency: int = 2,
        jitter: Callable[[int], float] | None = None,
        enabled: bool = True,
    ) -> None:
        self.cache = cache
        self.stream = stream
        self.service = service
        self._is_trading_day = is_trading_day
        self._now = now or (lambda: datetime.now(TZ_SHANGHAI))
        self.batch_size = max(1, min(5, batch_size))
        self.p0_interval_seconds = max(1, p0_interval_seconds)
        self.p1_interval_seconds = max(1, p1_interval_seconds)
        self.concurrency = max(1, min(2, concurrency))
        self._jitter = jitter or (
            lambda interval: random.uniform(0, min(5.0, interval * 0.1))
        )
        self.enabled = enabled
        self._next_due: dict[str, float] = {}
        self._failures: dict[str, int] = {}
        self._p0_batches = 0
        self._success_batches = 0
        self._final_session_date: date | None = None
        self._finalized_codes: set[str] = set()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if not self.enabled or (self._task and not self._task.done()):
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="theme-fund-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    def failure_count(self, code: str) -> int:
        return self._failures.get(code, 0)

    async def run_once(self) -> None:
        current = self._now()
        market = await asyncio.to_thread(self.stream.market_codes)
        priority = self.stream.priority_codes()
        owners = self._merge(priority, market)
        if not owners:
            return
        trading_day = await asyncio.to_thread(self._is_trading_day, current.date())

        cached = await asyncio.to_thread(self.cache.get_latest, owners)
        now_ts = current.timestamp()
        missing_p0 = [
            code
            for code in priority
            if code not in cached and self._next_due.get(code, 0) <= now_ts
        ]
        missing_p0_set = set(missing_p0)
        missing_p1 = [
            code
            for code in market
            if code not in cached
            and code not in missing_p0_set
            and self._next_due.get(code, 0) <= now_ts
        ]
        batch: list[str] = []
        after_close = trading_day and current.hour * 100 + current.minute >= 1500

        if self._final_session_date != current.date():
            self._final_session_date = current.date()
            self._finalized_codes.clear()

        if missing_p0:
            batch = missing_p0[: self.batch_size]
            self._p0_batches += 1
        elif missing_p1:
            batch = missing_p1[: self.batch_size]
            self._p0_batches = 0
        elif not trading_day:
            return
        elif after_close:
            batch = [
                code
                for code in owners
                if code not in self._finalized_codes and self._next_due.get(code, 0) <= now_ts
            ][: self.batch_size]
        else:
            hhmm = current.hour * 100 + current.minute
            if hhmm < 930 or 1130 < hhmm < 1300:
                return
            due_p0 = [code for code in priority if self._next_due.get(code, 0) <= now_ts]
            priority_set = set(priority)
            due_p1 = [
                code
                for code in market
                if code not in priority_set and self._next_due.get(code, 0) <= now_ts
            ]
            if due_p1 and self._p0_batches >= 2:
                batch = due_p1[: self.batch_size]
                self._p0_batches = 0
            elif due_p0:
                batch = due_p0[: self.batch_size]
                self._p0_batches += 1
            elif due_p1:
                batch = due_p1[: self.batch_size]
                self._p0_batches = 0
        if not batch:
            return

        result = await self.service.load_batch(batch, concurrency=self.concurrency)
        stored: list[dict[str, object]] = []
        priority_set = set(priority)
        for row in result["rows"]:
            previous_version = int(cached.get(str(row["code"]), {}).get("version") or 0)
            saved = await asyncio.to_thread(self.cache.put, row)
            stored.append(saved)
            code = str(saved["code"])
            self._failures.pop(code, None)
            interval = self.p0_interval_seconds if code in priority_set else self.p1_interval_seconds
            self._next_due[code] = now_ts + interval + max(0.0, self._jitter(interval))
            was_written = int(saved.get("version") or 0) > previous_version
            if (
                after_close
                and was_written
                and saved.get("sessionDate") == current.date().isoformat()
            ):
                self._finalized_codes.add(code)
        if stored:
            self.stream.publish(stored)

        systemic = False
        failures = result["failures"]
        for failure in failures:
            code = str(failure["code"])
            count = self._failures.get(code, 0) + 1
            self._failures[code] = count
            self._next_due[code] = now_ts + min(300, 30 * (2 ** (count - 1)))
            if failure.get("errorCode") in {"ths_rate_limited", "ths_captcha_required"}:
                systemic = True
        if (
            len(failures) == len(batch)
            and all(item.get("errorCode") == "ths_upstream_unavailable" for item in failures)
        ):
            systemic = True
        if systemic:
            self._success_batches = 0
            self.service.enter_cooldown(30)
            await self.service.set_effective_concurrency(1)
        elif failures:
            self._success_batches = 0
        else:
            self._success_batches += 1
            if self._success_batches >= 3:
                await self.service.set_effective_concurrency(self.concurrency)

    async def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self.run_once()
            except TradingCalendarUnavailable as error:
                logger.warning("theme fund refresh paused: %s", error)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("theme fund scheduler cycle failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=0.5)
            except TimeoutError:
                pass

    @staticmethod
    def _merge(*groups: list[str]) -> list[str]:
        return list(dict.fromkeys(code for group in groups for code in group))


def _create_scheduler() -> ThemeFundScheduler:
    from backend.settings import get_settings

    settings = get_settings()
    return ThemeFundScheduler(
        cache=get_theme_fund_cache(),
        stream=get_theme_fund_stream(),
        service=get_ths_main_monitor_service(),
        batch_size=settings.theme_fund_batch_size,
        p0_interval_seconds=settings.theme_fund_p0_interval_seconds,
        p1_interval_seconds=settings.theme_fund_p1_interval_seconds,
        concurrency=settings.theme_fund_concurrency,
        enabled=settings.theme_fund_scheduler_enabled,
    )


theme_fund_scheduler = _create_scheduler()
