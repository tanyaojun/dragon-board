"""Chinese A-share trading day detection.

Provides two public functions:
  - is_trading_day(date) -> bool
  - trading_date_from_ts(now_ts_ms) -> str | None

The holiday list is a hardcoded frozenset. Dates are approximate and should be
verified against the official exchange calendar before production use. The module
is correct for weekends (always non-trading).

NOTE: Holiday dates are approximate for 2026. Verify against the official
Shanghai/Shenzhen exchange calendar before relying on holiday detection.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# Approximate 2026 Chinese A-share market closure dates.
# These are based on typical calendar patterns and should be verified
# against the official exchange holiday schedule.
# Key principle: better to miss a holiday (treat as trading day)
# than to miss a trading day (treat as holiday).
_KNOWN_HOLIDAYS: frozenset[str] = frozenset({
    "2026-01-01", "2026-01-02",  # New Year
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",  # Spring Festival (approximate)
    "2026-04-06",  # Qing Ming
    "2026-05-01", "2026-05-04", "2026-05-05",  # Labor Day
    "2026-06-19",  # Dragon Boat
    "2026-09-25",  # Mid-Autumn
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07",  # National Day
})


def is_trading_day(date: datetime.date) -> bool:
    """Return True if *date* is a Chinese A-share trading day.

    Returns False for Saturdays, Sundays, and dates in the known holiday set.
    """
    # Saturday=5, Sunday=6
    if date.weekday() >= 5:
        return False
    if date.isoformat() in _KNOWN_HOLIDAYS:
        return False
    return True


def trading_date_from_ts(now_ts_ms: int) -> str | None:
    """Convert epoch milliseconds to an Asia/Shanghai date.

    Returns the date as "YYYY-MM-DD" if it is a trading day, or None otherwise.
    """
    dt = datetime.datetime.fromtimestamp(now_ts_ms / 1000.0, tz=TZ_SHANGHAI)
    d = dt.date()
    if is_trading_day(d):
        return d.isoformat()
    return None
