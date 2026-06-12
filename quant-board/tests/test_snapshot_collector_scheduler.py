from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

# Module under test will be in backend/snapshot_collector/trading_calendar.py
# We define TZ_SHANGHAI locally for test timestamp construction.
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# Same holiday set as the production module, for parametrized holiday tests.
_KNOWN_HOLIDAY_DATES = frozenset({
    "2026-01-01", "2026-01-02",  # New Year
    "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20",  # Spring Festival (approximate)
    "2026-04-06",  # Qing Ming
    "2026-05-01", "2026-05-04", "2026-05-05",  # Labor Day
    "2026-06-19",  # Dragon Boat
    "2026-09-25",  # Mid-Autumn
    "2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07",  # National Day
})


def _ts_ms(dt: datetime.datetime) -> int:
    """Convert a timezone-aware datetime to epoch milliseconds."""
    return int(dt.timestamp() * 1000)


class TestTradingCalendar:
    """Tests for quant-board/backend/snapshot_collector/trading_calendar.py."""

    def test_weekdays_are_trading_days(self) -> None:
        """Monday through Friday in a non-holiday week all return True."""
        from backend.snapshot_collector.trading_calendar import is_trading_day

        # Week of 2026-06-08 (Mon) through 2026-06-12 (Fri) — no holidays.
        for day in range(8, 13):
            assert is_trading_day(datetime.date(2026, 6, day)) is True

    def test_weekends_are_not_trading_days(self) -> None:
        """Saturday and Sunday both return False."""
        from backend.snapshot_collector.trading_calendar import is_trading_day

        # 2026-06-13 is Saturday, 2026-06-14 is Sunday
        assert is_trading_day(datetime.date(2026, 6, 13)) is False
        assert is_trading_day(datetime.date(2026, 6, 14)) is False

    def test_is_trading_day_non_holiday_friday(self) -> None:
        """A regular Friday with no holiday is a trading day."""
        from backend.snapshot_collector.trading_calendar import is_trading_day

        # 2026-06-12 is a Friday and not in the holiday set.
        assert is_trading_day(datetime.date(2026, 6, 12)) is True

    @pytest.mark.parametrize("date_str", sorted(_KNOWN_HOLIDAY_DATES))
    def test_known_holidays(self, date_str: str) -> None:
        """Every date in the known holiday set returns False."""
        from backend.snapshot_collector.trading_calendar import is_trading_day

        year, month, day = date_str.split("-")
        d = datetime.date(int(year), int(month), int(day))
        assert is_trading_day(d) is False, f"{date_str} should be a non-trading holiday"

    def test_trading_date_from_ts_normal_day(self) -> None:
        """Timestamp during a Monday afternoon in Shanghai gives the correct date string."""
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        # 2026-06-15 is a Monday (June 1, 2026 is Monday).
        dt = datetime.datetime(2026, 6, 15, 14, 30, 0, tzinfo=TZ_SHANGHAI)
        result = trading_date_from_ts(_ts_ms(dt))
        assert result == "2026-06-15"

    def test_trading_date_from_ts_weekend(self) -> None:
        """Timestamp during a Saturday returns None (not a trading day)."""
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        # 2026-06-13 is a Saturday.
        dt = datetime.datetime(2026, 6, 13, 10, 0, 0, tzinfo=TZ_SHANGHAI)
        result = trading_date_from_ts(_ts_ms(dt))
        assert result is None

    def test_trading_date_from_ts_midnight_edge(self) -> None:
        """Timestamp at exactly midnight Asia/Shanghai on a trading day."""
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        # 2026-06-15 00:00:00 Asia/Shanghai is a Monday.
        dt = datetime.datetime(2026, 6, 15, 0, 0, 0, tzinfo=TZ_SHANGHAI)
        result = trading_date_from_ts(_ts_ms(dt))
        assert result == "2026-06-15"

    def test_trading_date_from_ts_holiday(self) -> None:
        """Timestamp during a known holiday returns None."""
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        # 2026-05-01 is Labor Day holiday.
        dt = datetime.datetime(2026, 5, 1, 11, 0, 0, tzinfo=TZ_SHANGHAI)
        result = trading_date_from_ts(_ts_ms(dt))
        assert result is None, "Labor Day should be a non-trading holiday"
