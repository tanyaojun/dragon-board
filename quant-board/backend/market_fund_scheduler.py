from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from backend.akshare_fund_provider import (
    SYSTEMIC_ERRORS,
    AkshareFundBatch,
    AkshareFundProvider,
    AkshareFundProviderError,
    get_akshare_fund_provider,
)
from backend.market_fund_stream import MarketFundStream, get_market_fund_stream
from backend.settings import get_settings
from backend.snapshot_collector.trading_calendar import is_trading_day
from backend.theme_fund_cache import ThemeFundCache, get_theme_fund_cache


logger = logging.getLogger(__name__)
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketFundScheduler:
    """Full-market THS fund flow refresher backed by akshare.

    One akshare call returns the whole market, so the scheduler replaces the
    old per-stock polling with a periodic full refresh. Rows are written to
    Redis with a TTL (shared across processes/restarts) and kept as last-good
    in the in-memory ThemeFundCache. Startup warmup prefetches the whole
    market once without waiting for WebSocket subscribers so the first screen
    can be served from cache immediately. Upstream failures never clear
    existing rows; they open a cooldown and expose a structured status so
    consumers can keep last-good.
    """

    def __init__(
        self,
        *,
        cache: ThemeFundCache,
        stream: MarketFundStream,
        provider: AkshareFundProvider,
        is_trading_day: Callable = is_trading_day,
        now: Callable[[], datetime] | None = None,
        min_refresh_interval_seconds: float = 60.0,
        refresh_interval_seconds: float = 300.0,
        systemic_cooldown_seconds: float = 300.0,
        enabled: bool = True,
    ) -> None:
        self.cache = cache
        self.stream = stream
        self.provider = provider
        self._is_trading_day = is_trading_day
        self._now = now or (lambda: datetime.now(TZ_SHANGHAI))
        self.min_refresh_interval_seconds = max(30.0, float(min_refresh_interval_seconds))
        self.refresh_interval_seconds = max(
            self.min_refresh_interval_seconds,
            float(refresh_interval_seconds),
        )
        self.systemic_cooldown_seconds = max(30.0, float(systemic_cooldown_seconds))
        self.enabled = enabled
        self._next_refresh_at = 0.0
        self._circuit_open_until = 0.0
        self._current_session_date: str | None = None
        self._primed = False
        self._finalized = False
        self._final_session_date: str | None = None
        self._last_error: str | None = None
        self._last_saved_at: float | None = None
        self._last_session_date: str | None = None
        self._last_row_count = 0
        self._last_code: str | None = None
        self._parse_failure_count = 0
        self._parse_failure_samples: list[dict[str, object]] = []
        self._request_times: list[float] = []
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.enabled or (self._task and not self._task.done()):
            return
        self._task = asyncio.create_task(
            self._warmup_then_run(),
            name="market-fund-scheduler",
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def run_once(self, *, ignore_subscribers: bool = False) -> bool:
        codes = self.stream.market_codes()
        if not codes and not ignore_subscribers:
            return False
        current = self._now()
        now_ts = current.timestamp()
        if now_ts < max(self._next_refresh_at, self._circuit_open_until):
            return False

        try:
            trading_day = await asyncio.to_thread(self._is_trading_day, current.date())
        except Exception:
            # Calendar unavailable: keep last-good rows and surface the reason.
            self._last_error = "trading_calendar_unavailable"
            self._next_refresh_at = now_ts + self.min_refresh_interval_seconds
            return True

        session_date = self._resolve_session_date(current.date(), trading_day)
        if session_date != self._current_session_date:
            self._current_session_date = session_date
            self._primed = False
            self._finalized = False
            self._final_session_date = None

        minute = current.hour * 60 + current.minute
        intraday = trading_day and (570 <= minute <= 690 or 780 <= minute < 900)
        after_close = trading_day and 900 <= minute <= 930

        if intraday and self._primed:
            if now_ts < self._next_refresh_at:
                return False
        elif after_close and self._finalized:
            return False
        elif not intraday and not after_close and self._primed:
            return False

        self._next_refresh_at = now_ts + self.min_refresh_interval_seconds
        self._record_request(now_ts)
        try:
            batch = await self.provider.fetch_all(session_date=session_date)
        except AkshareFundProviderError as error:
            self._last_error = error.code
            if error.code in SYSTEMIC_ERRORS:
                self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
            return True
        except Exception:
            logger.exception("market fund akshare refresh failed unexpectedly")
            self._last_error = "unexpected_fetch_error"
            self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
            return True

        saved_rows, validation_failures = await self._save_batch(batch)
        if saved_rows:
            self.stream.publish(saved_rows)

        self._primed = True
        self._final_session_date = session_date
        if after_close:
            self._finalized = True
        if intraday:
            self._next_refresh_at = now_ts + self.refresh_interval_seconds
        self._last_error = None
        self._last_saved_at = now_ts
        self._last_session_date = session_date
        self._last_row_count = len(saved_rows)
        self._last_code = str(saved_rows[-1].get("code") or "") if saved_rows else None
        self._parse_failure_count = len(batch.failures) + len(validation_failures)
        self._parse_failure_samples = (batch.failures + validation_failures)[:10]
        return True

    async def _warmup_then_run(self) -> None:
        """启动预热：立即抓取一轮全市场资金流写入 Redis，首屏可直接命中；随后进入正常周期。"""
        try:
            await self.run_once(ignore_subscribers=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("market fund warmup cycle failed")
        await self._run()

    async def _save_batch(
        self,
        batch: AkshareFundBatch,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        saved_rows: list[dict[str, object]] = []
        validation_failures: list[dict[str, object]] = []
        for row in batch.rows:
            try:
                saved = await asyncio.to_thread(self.cache.put, dict(row))
            except ValueError as error:
                # One malformed row must not block the rest of the batch.
                validation_failures.append(
                    {"code": str(row.get("code") or ""), "reason": str(error)}
                )
                continue
            saved_rows.append(saved)
        return saved_rows, validation_failures

    def _resolve_session_date(self, today: date, trading_day: bool) -> str:
        if trading_day:
            return today.isoformat()
        if self._last_session_date:
            return self._last_session_date
        # First run on a non-trading day: walk back to the latest trading day.
        candidate = today
        for _ in range(10):
            candidate = candidate - timedelta(days=1)
            try:
                if self._is_trading_day(candidate):
                    return candidate.isoformat()
            except Exception:
                break
        return today.isoformat()

    def _record_request(self, now_ts: float) -> None:
        self._request_times.append(now_ts)
        self._request_times = [ts for ts in self._request_times if now_ts - ts < 60]

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "running": self._task is not None,
            "source": "akshare_ths_individual",
            "queueLength": len(self.stream.market_codes()),
            "currentCode": self._last_code,
            "requestsLastMinute": len(self._request_times),
            "circuitOpenUntil": self._circuit_open_until,
            "lastError": self._last_error,
            "refreshIntervalSeconds": self.refresh_interval_seconds,
            "lastSavedAt": self._last_saved_at,
            "lastSessionDate": self._last_session_date,
            "primedCodes": self._last_row_count,
            "lastRowCount": self._last_row_count,
            "parseFailureCount": self._parse_failure_count,
            "parseFailureSamples": self._parse_failure_samples,
        }

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
                await asyncio.sleep(self.min_refresh_interval_seconds)
            else:
                self.stream.codes_changed.clear()
                wait_for = min(120.0, self.refresh_interval_seconds)
                try:
                    await asyncio.wait_for(self.stream.codes_changed.wait(), timeout=wait_for)
                except asyncio.TimeoutError:
                    pass


market_fund_scheduler = MarketFundScheduler(
    cache=get_theme_fund_cache(),
    stream=get_market_fund_stream(),
    provider=get_akshare_fund_provider(),
    refresh_interval_seconds=get_settings().theme_fund_refresh_interval_seconds,
)
