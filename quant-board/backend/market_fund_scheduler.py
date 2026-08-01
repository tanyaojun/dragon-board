from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from backend.market_fund_stream import MarketFundStream, get_market_fund_stream
from backend.snapshot_collector.trading_calendar import is_trading_day
from backend.theme_fund_cache import ThemeFundCache, get_theme_fund_cache
from backend.ths_main_monitor_service import ThsMainMonitorError, ThsMainMonitorService, get_ths_main_monitor_service


logger = logging.getLogger(__name__)
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
SYSTEMIC_ERRORS = {"ths_rate_limited", "ths_captcha_required", "ths_upstream_unavailable"}


class MarketFundScheduler:
    def __init__(self, *, cache: ThemeFundCache, stream: MarketFundStream, service: ThsMainMonitorService, is_trading_day: Callable = is_trading_day, now: Callable[[], datetime] | None = None, min_request_interval_seconds: float = 2.0, p0_size: int = 15, p0_interval_seconds: float = 60, p1_interval_seconds: float = 900, enabled: bool = True) -> None:
        self.cache = cache
        self.stream = stream
        self.service = service
        self._is_trading_day = is_trading_day
        self._now = now or (lambda: datetime.now(TZ_SHANGHAI))
        self.min_request_interval_seconds = max(2.0, float(min_request_interval_seconds))
        self.p0_size = max(1, int(p0_size))
        self.p0_interval_seconds = max(60.0, float(p0_interval_seconds))
        self.p1_interval_seconds = max(900.0, float(p1_interval_seconds))
        self.enabled = enabled
        self._next_request_at = 0.0
        self._next_due: dict[str, float] = {}
        self._final_session_date = None
        self._finalized_codes: set[str] = set()
        self._circuit_open_until = 0.0
        self._last_error: str | None = None
        self._request_times: list[float] = []
        self._cache_hits = 0
        self._current_code: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._primed_codes: set[str] = set()

    def start(self) -> None:
        if not self.enabled or (self._task and not self._task.done()):
            return
        self._task = asyncio.create_task(self._run(), name="market-fund-scheduler")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def run_once(self) -> bool:
        codes = self.stream.market_codes()
        if not codes:
            return False
        current = self._now()
        now_ts = current.timestamp()
        if now_ts < max(self._next_request_at, self._circuit_open_until):
            return False
        is_trading = await asyncio.to_thread(self._is_trading_day, current.date())
        minute = current.hour * 60 + current.minute
        intraday = 570 <= minute <= 690 or 780 <= minute < 900
        after_close = 900 <= minute <= 930
        in_session = is_trading and (intraday or after_close)

        if not in_session:
            unprimed = [code for code in codes if code not in self._primed_codes]
            if not unprimed:
                return False
            due_codes = unprimed[:1]
        elif after_close:
            due_codes = [code for code in codes if code not in self._finalized_codes]
        else:
            p0 = codes[: self.p0_size]
            p1 = codes[self.p0_size :]
            due_codes = sorted(
                [code for code in [*p0, *p1] if self._next_due.get(code, 0) <= now_ts],
                key=lambda code: (code not in p0, self._next_due.get(code, 0), codes.index(code)),
            )
        if not due_codes:
            return False
        code = due_codes[0]
        self._current_code = code
        self._next_request_at = now_ts + self.min_request_interval_seconds
        self._request_times = [ts for ts in self._request_times if now_ts - ts < 60]
        self._request_times.append(now_ts)
        try:
            row = await self.service.load_summary_row(code)
        except ThsMainMonitorError as error:
            self._last_error = error.code
            if error.code in SYSTEMIC_ERRORS:
                self._circuit_open_until = now_ts + 300
            return True
        else:
            saved = await asyncio.to_thread(self.cache.put, row)
            self.stream.publish([saved])
            self._primed_codes.add(code)
            self._last_error = None
            if after_close:
                self._finalized_codes.add(code)
            else:
                interval = self.p0_interval_seconds if code in codes[: self.p0_size] else self.p1_interval_seconds
                self._next_due[code] = now_ts + interval

    def status(self) -> dict[str, object]:
        return {"enabled": self.enabled, "running": self._task is not None, "queueLength": len(self.stream.market_codes()), "currentCode": self._current_code, "requestsLastMinute": len(self._request_times), "cacheHits": self._cache_hits, "circuitOpenUntil": self._circuit_open_until, "lastError": self._last_error, "primedCodes": len(self._primed_codes)}

    async def _run(self) -> None:
        while True:
            try:
                has_work = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market fund scheduler cycle failed")
                has_work = False
            if has_work:
                await asyncio.sleep(self.min_request_interval_seconds)
            else:
                self.stream.codes_changed.clear()
                try:
                    await asyncio.wait_for(self.stream.codes_changed.wait(), timeout=120)
                except asyncio.TimeoutError:
                    pass


market_fund_scheduler = MarketFundScheduler(cache=get_theme_fund_cache(), stream=get_market_fund_stream(), service=get_ths_main_monitor_service())
