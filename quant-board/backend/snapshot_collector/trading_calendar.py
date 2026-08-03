"""A-share trading dates sourced only from the python-bridge TDX calendar."""

from __future__ import annotations

import datetime
import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
CONTINUOUS_SESSION_START_HHMM = 930
MORNING_SESSION_END_HHMM = 1130
AFTERNOON_SESSION_START_HHMM = 1300
POST_CLOSE_END_HHMM = 1530

# 交易日历本地缓存：bridge 不可用时回退，避免桥挂导致整天停采。
_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "trading_calendar_cache.json"
_last_calendar_source: str = "bridge"

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


def _read_calendar_cache() -> dict[str, bool]:
    try:
        if _CACHE_PATH.exists():
            raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return {str(k): bool(v) for k, v in raw.items()}
    except Exception:
        pass
    return {}


def _write_calendar_cache(date: str, value: bool) -> None:
    try:
        data = _read_calendar_cache()
        data[date] = value
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _weekday_heuristic(date: datetime.date) -> bool:
    """Weekday fallback (Mon-Fri).  Over-collects on holidays, which is safer
    than silently missing a trading day (empty snapshots stay visible with
    quality flags); the bridge result corrects the cache as soon as it is back.
    """
    return date.weekday() < 5


def is_trading_day(date: datetime.date) -> bool:
    """Return the bridge TDX calendar result, or stop when it is unavailable."""
    result = _fetch_bridge_calendar(date)
    if result is None:
        raise TradingCalendarUnavailable(
            f"TDX trading calendar unavailable for {date.isoformat()}"
        )
    return result


def trading_date_from_ts(now_ts_ms: int) -> str | None:
    """Convert epoch milliseconds to an Asia/Shanghai trading date.

    Source priority: bridge (writes cache) -> local cache -> weekday heuristic.
    Never raises, so a python-bridge outage degrades collection instead of
    stopping it.  Returns "YYYY-MM-DD" when the day is a trading day.
    """
    global _last_calendar_source
    dt = datetime.datetime.fromtimestamp(now_ts_ms / 1000.0, tz=TZ_SHANGHAI)
    d = dt.date()
    date_key = d.isoformat()

    result = _fetch_bridge_calendar(d)
    if result is not None:
        _write_calendar_cache(date_key, result)
        _last_calendar_source = "bridge"
        return date_key if result else None

    cached = _read_calendar_cache().get(date_key)
    if cached is not None:
        _last_calendar_source = "cache"
        return date_key if cached else None

    _last_calendar_source = "heuristic_weekday"
    if _weekday_heuristic(d):
        return d.isoformat()
    return None
