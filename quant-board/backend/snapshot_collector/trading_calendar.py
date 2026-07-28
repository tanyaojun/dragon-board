"""A-share trading dates sourced only from the python-bridge TDX calendar."""

from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.request
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
CONTINUOUS_SESSION_START_HHMM = 930
MORNING_SESSION_END_HHMM = 1130
AFTERNOON_SESSION_START_HHMM = 1300
POST_CLOSE_END_HHMM = 1530

class TradingCalendarUnavailable(RuntimeError):
    pass


def _hhmm(value: datetime.datetime) -> int:
    return value.hour * 100 + value.minute


def is_post_close(value: datetime.datetime) -> bool:
    """Whether Shanghai fixed-price trading has completed for this date."""
    return _hhmm(value) > POST_CLOSE_END_HHMM


def is_intraday_refresh_time(value: datetime.datetime) -> bool:
    """Allow live refresh only during continuous auction sessions."""
    hhmm = _hhmm(value)
    return (
        CONTINUOUS_SESSION_START_HHMM <= hhmm <= MORNING_SESSION_END_HHMM
        or AFTERNOON_SESSION_START_HHMM <= hhmm <= POST_CLOSE_END_HHMM
    )


def _fetch_bridge_calendar(date: datetime.date) -> bool | None:
    from backend.settings import get_settings

    base_url = get_settings().snapshot_collector_bridge_base_url.rstrip("/")
    url = f"{base_url}/api/calendar?{urlencode({'date': date.isoformat()})}"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    value = payload.get("isTradingDay") if payload.get("ok") is True else None
    return value if isinstance(value, bool) else None


def is_trading_day(date: datetime.date) -> bool:
    """Return the bridge TDX calendar result, or stop when it is unavailable."""
    result = _fetch_bridge_calendar(date)
    if result is None:
        raise TradingCalendarUnavailable(
            f"TDX trading calendar unavailable for {date.isoformat()}"
        )
    return result


def trading_date_from_ts(now_ts_ms: int) -> str | None:
    """Convert epoch milliseconds to an Asia/Shanghai date.

    Returns the date as "YYYY-MM-DD" if it is a trading day, or None otherwise.
    """
    dt = datetime.datetime.fromtimestamp(now_ts_ms / 1000.0, tz=TZ_SHANGHAI)
    d = dt.date()
    if is_trading_day(d):
        return d.isoformat()
    return None
