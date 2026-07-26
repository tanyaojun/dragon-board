from __future__ import annotations

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from backend.stock_name_refresh_scheduler import StockNameRefreshScheduler


class _Settings:
    storage_backend = 'mongodb'


def test_stock_name_refresh_scheduler_runs_refresh_in_mongodb_mode() -> None:
    calls: list[str] = []
    scheduler = StockNameRefreshScheduler(
        settings=_Settings(),
        database_factory=lambda: 'database',
        refresh_fn=lambda database: calls.append(database) or {'ok': True, 'inserted': 2},
    )

    asyncio.run(scheduler._refresh_once())

    status = scheduler.status()
    assert calls == ['database']
    assert status['enabled'] is True
    assert status['running'] is False
    assert status['targetHour'] == 8
    assert status['targetMinute'] == 30
    assert status['lastRunAt'] is not None
    assert status['lastResult'] == {'ok': True, 'inserted': 2}
    assert status['lastError'] is None


def test_stock_name_refresh_scheduler_uses_shanghai_time_for_target() -> None:
    scheduler = StockNameRefreshScheduler(settings=_Settings())

    seconds = scheduler._seconds_until_next_target(
        datetime(2026, 7, 26, 0, 0, tzinfo=ZoneInfo('UTC'))
    )

    assert seconds == 30 * 60
