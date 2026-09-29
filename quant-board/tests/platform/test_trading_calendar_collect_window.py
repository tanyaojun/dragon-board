"""Trading-calendar collection-window tests (scheduler non-collect hours).

Guards the 16:00-09:00 non-collect window: after close the scheduler must
sleep until the next window instead of polling every 30 minutes, and the
catch-up loop must not backfill historical slots with live data after close.
"""

import datetime

from backend.snapshot_collector.trading_calendar import (
    TZ_SHANGHAI,
    is_in_collect_window,
    seconds_until_collect_window,
)


def _dt(hhmm: int, day: int = 5) -> datetime.datetime:
    """2026-08-{day} HH:MM in Shanghai tz."""
    return datetime.datetime(2026, 8, day, hhmm // 100, hhmm % 100, tzinfo=TZ_SHANGHAI)


def test_in_window_morning():
    assert is_in_collect_window(_dt(900)) is True
    assert is_in_collect_window(_dt(930)) is True


def test_in_window_afternoon_through_close():
    assert is_in_collect_window(_dt(1500)) is True
    assert is_in_collect_window(_dt(1530)) is True
    assert is_in_collect_window(_dt(1559)) is True


def test_outside_window_after_close():
    assert is_in_collect_window(_dt(1600)) is False
    assert is_in_collect_window(_dt(1800)) is False
    assert is_in_collect_window(_dt(2359)) is False


def test_outside_window_before_open():
    assert is_in_collect_window(_dt(0)) is False
    assert is_in_collect_window(_dt(800)) is False
    assert is_in_collect_window(_dt(859)) is False


def test_seconds_until_window_after_close():
    # 18:00 -> 次日 09:00 = 15 小时
    seconds = seconds_until_collect_window(_dt(1800))
    assert seconds == 15 * 3600


def test_seconds_until_window_before_open():
    # 08:00 -> 当日 09:00 = 1 小时
    seconds = seconds_until_collect_window(_dt(800))
    assert seconds == 1 * 3600


def test_seconds_until_window_zero_inside_window():
    assert seconds_until_collect_window(_dt(1000)) == 0.0


def test_seconds_until_window_rolls_to_next_day():
    # 23:59 -> 次日 09:00 = 9 小时 1 分钟
    seconds = seconds_until_collect_window(_dt(2359))
    assert seconds == 9 * 3600 + 60
