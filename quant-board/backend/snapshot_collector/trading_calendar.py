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


# 非采集窗口：交易日下午 16:00 至次日 09:00（含）不采集，避免收盘后空转补采。
_COLLECT_WINDOW_START_HHMM = 900
_COLLECT_WINDOW_END_HHMM = 1600


def is_in_collect_window(value: datetime.datetime) -> bool:
    """Whether snapshot collection should run for this moment.

    交易日下午 16:00 至隔日早上 09:00 之间不采集（当日槽位已全部完成，
    收盘后数据已定格；次日数据需等开盘后才有意义）。09:00 起进入窗口，
    覆盖盘前到收盘后 15:30 的最后槽位；16:00 后退出窗口。
    """
    hhmm = _hhmm(value)
    return _COLLECT_WINDOW_START_HHMM <= hhmm < _COLLECT_WINDOW_END_HHMM


def seconds_until_collect_window(
    value: datetime.datetime,
    *,
    tz: datetime.tzinfo = TZ_SHANGHAI,
) -> float:
    """Seconds from *value* until the next collection window opens (09:00 next day).

    非窗口内（16:00-次日 09:00）返回到次日 09:00 的秒数；窗口内返回 0。
    用于调度器在收盘后深度休眠，避免每 30 分钟空转轮询。
    """
    if is_in_collect_window(value):
        return 0.0
    now = value
    # 计算下一个窗口起点：若今天已过 16:00，则次日 09:00；否则（09:00 前）今天 09:00。
    target_date = now.date()
    if _hhmm(now) >= _COLLECT_WINDOW_END_HHMM:
        target_date = target_date + datetime.timedelta(days=1)
    target = datetime.datetime.combine(
        target_date,
        datetime.time(_COLLECT_WINDOW_START_HHMM // 100, _COLLECT_WINDOW_START_HHMM % 100),
        tzinfo=tz,
    )
    return max(0.0, (target - now).total_seconds())


def is_intraday_refresh_time(value: datetime.datetime) -> bool:
    """Allow live refresh only during continuous auction sessions."""
    hhmm = _hhmm(value)
    return (
        CONTINUOUS_SESSION_START_HHMM <= hhmm <= MORNING_SESSION_END_HHMM
        or AFTERNOON_SESSION_START_HHMM <= hhmm <= POST_CLOSE_END_HHMM
    )


def _fetch_bridge_calendar(date: datetime.date) -> bool | None:
    from backend.core.settings import get_settings

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
