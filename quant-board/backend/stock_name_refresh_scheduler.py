from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta
from typing import Any, Callable

from backend.data.repository_factory import get_runtime_mongodb_database
from backend.data.stock_name_refresh import refresh_stock_names
from backend.settings import get_settings
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI


class StockNameRefreshScheduler:
    def __init__(
        self,
        *,
        settings: Any | None = None,
        database_factory: Callable[[], Any] = get_runtime_mongodb_database,
        refresh_fn: Callable[[Any], dict[str, Any]] = refresh_stock_names,
    ) -> None:
        current_settings = settings or get_settings()
        self.enabled = current_settings.storage_backend == 'mongodb'
        self.target_hour = 8
        self.target_minute = 30
        self._database_factory = database_factory
        self._refresh_fn = refresh_fn
        self._task: asyncio.Task[None] | None = None
        self._last_run_at: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def status(self) -> dict[str, Any]:
        return {
            'enabled': self.enabled,
            'running': self._task is not None,
            'targetHour': self.target_hour,
            'targetMinute': self.target_minute,
            'lastRunAt': self._last_run_at,
            'lastResult': self._last_result,
            'lastError': self._last_error,
        }

    async def _run_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._seconds_until_next_target())
                await self._refresh_once()
            except asyncio.CancelledError:
                return
            except Exception as error:
                self._last_error = str(error)

    async def _refresh_once(self) -> None:
        result = await asyncio.to_thread(self._refresh_fn, self._database_factory())
        self._last_run_at = datetime.now(TZ_SHANGHAI).isoformat()
        self._last_result = result
        self._last_error = None if result.get('ok') else str(result.get('error') or 'unknown error')

    def _seconds_until_next_target(self, now: datetime | None = None) -> float:
        now = (now or datetime.now(TZ_SHANGHAI)).astimezone(TZ_SHANGHAI)
        target = now.replace(hour=self.target_hour, minute=self.target_minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return max(1.0, (target - now).total_seconds())


stock_name_refresh_scheduler = StockNameRefreshScheduler()
