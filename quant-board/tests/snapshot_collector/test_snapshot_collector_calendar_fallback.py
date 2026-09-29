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
