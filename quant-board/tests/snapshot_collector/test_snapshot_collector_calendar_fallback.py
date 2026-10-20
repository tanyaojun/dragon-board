from __future__ import annotations

from pathlib import Path

import pytest

from backend.snapshot_collector import trading_calendar as tc


def _ts_2026_08_03_13_00() -> int:
    # 2026-08-03 13:00 Asia/Shanghai（周一）
    return 1785733200000


def test_trading_date_from_ts_falls_back_to_weekday_when_bridge_down(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(tc, "_CACHE_PATH", tmp_path / "calendar_cache.json")
    monkeypatch.setattr(tc, "_fetch_bridge_calendar", lambda date: None)
    assert tc.trading_date_from_ts(_ts_2026_08_03_13_00()) == "2026-08-03"
    assert tc._last_calendar_source == "heuristic_weekday"


def test_trading_date_from_ts_uses_cache_when_bridge_down(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "calendar_cache.json"
    cache_path.write_text('{"2026-08-03": false}', encoding="utf-8")
    monkeypatch.setattr(tc, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(tc, "_fetch_bridge_calendar", lambda date: None)
    assert tc.trading_date_from_ts(_ts_2026_08_03_13_00()) is None
    assert tc._last_calendar_source == "cache"


def test_trading_date_from_ts_bridge_result_wins_and_caches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "calendar_cache.json"
    monkeypatch.setattr(tc, "_CACHE_PATH", cache_path)
    monkeypatch.setattr(tc, "_fetch_bridge_calendar", lambda date: True)
    assert tc.trading_date_from_ts(_ts_2026_08_03_13_00()) == "2026-08-03"
    assert tc._last_calendar_source == "bridge"
    assert '"2026-08-03": true' in cache_path.read_text(encoding="utf-8")


def test_is_trading_day_cached_degrades_and_never_raises(monkeypatch, tmp_path):
    """研究/advisory 链（午盘投喂、题材语料）在 bridge 宕机时必须降级而非抛错：
    「桥不可用」不等于「今天不做」，否则一整天证据静默丢失（AGENTS §4.0 fail-visible）。"""
    monkeypatch.setattr(tc, "_CACHE_PATH", tmp_path / "calendar_cache.json")
    monkeypatch.setattr(tc, "_fetch_bridge_calendar", lambda date: None)
    import datetime as dt

    monday = dt.date(2026, 8, 3)
    assert tc.is_trading_day_cached(monday) == (True, "weekday")     # 无缓存 → 周内启发
    with pytest.raises(tc.TradingCalendarUnavailable):               # 抛错版行为不变，供强校验链用
        tc.is_trading_day(monday)

    (tmp_path / "calendar_cache.json").write_text('{"2026-08-03": false}', encoding="utf-8")
    assert tc.is_trading_day_cached(monday) == (False, "cache")      # 缓存优先于启发

    monkeypatch.setattr(tc, "_fetch_bridge_calendar", lambda date: True)
    assert tc.is_trading_day_cached(monday) == (True, "bridge")      # bridge 可用则以它为准
