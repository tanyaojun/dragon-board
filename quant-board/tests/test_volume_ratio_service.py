from __future__ import annotations

import math
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.market_data_routes import router
from backend.services.market.volume_ratio_service import (
    ashare_expected_volume_progress,
    ashare_volume_clock_minute,
    build_daily_history,
    build_intraday_history,
    calculate_volume_ratio,
    compute_volume_ratios,
    normalize_volume_history,
    raw_volume_ratio,
    resolve_volume_ratio_history,
    warmup_daily_history_cache,
    weighted_average_volume,
)


TZ = ZoneInfo("Asia/Shanghai")


def test_weighted_average_uses_latest_three_positive_finite_volumes() -> None:
    assert weighted_average_volume([100, 80, 60, 40]) == 86
    assert weighted_average_volume([0, math.nan, -1]) is None


def test_intraday_history_is_preferred_when_at_least_two_values() -> None:
    result = calculate_volume_ratio(
        200,
        [1000, 900, 800],
        [100, 80],
        datetime(2026, 5, 6, 10, 0, tzinfo=TZ),
    )
    assert result["value"] == 2.16
    assert result["source"] == "intraday_snapshot"
    assert result["status"] == "fresh"


def test_daily_fallback_drops_same_volume_latest_day_and_uses_progress() -> None:
    history = resolve_volume_ratio_history(500, [500.2, 1000, 800, 600])
    assert history == [1000, 800, 600]
    assert ashare_expected_volume_progress(datetime(2026, 5, 6, 10, 0, tzinfo=TZ)) == 0.24
    result = calculate_volume_ratio(
        500,
        [500.2, 1000, 800, 600],
        [],
        datetime(2026, 5, 6, 10, 0, tzinfo=TZ),
    )
    assert result["value"] == 2.42
    assert result["source"] == "daily_snapshot"


def test_full_day_progress_outside_trading_hours() -> None:
    assert ashare_expected_volume_progress(datetime(2026, 5, 6, 5, 13, tzinfo=TZ)) == 1
    result = calculate_volume_ratio(
        500,
        [1000, 800, 600],
        [],
        datetime(2026, 5, 6, 5, 13, tzinfo=TZ),
    )
    assert result["value"] == 0.58


def test_normalizes_histories_and_clips_raw_ratios() -> None:
    assert normalize_volume_history([100, "90", 0, -1, math.nan, 80], 2) == [100, 90]
    assert raw_volume_ratio(200, 92.5) == 2.16
    assert raw_volume_ratio(1, 1000) == 0.01
    assert raw_volume_ratio(100000, 1) == 99.99
    assert raw_volume_ratio(100, 0) is None


def test_structured_diagnostics_when_raw_ratio_capped() -> None:
    result = calculate_volume_ratio(
        100000,
        [1, 1, 1],
        [],
        datetime(2026, 5, 6, 15, 30, tzinfo=TZ),
    )
    assert result["value"] == 99.99
    assert result["status"] == "suspicious"
    assert result["source"] == "daily_snapshot"
    assert result["currentVolume"] == 100000
    assert result["expectedVolume"] == 1
    assert result["rawRatio"] == 100000
    assert result["capped"] is True
    assert result["reason"] == "ratio_capped"


def test_maps_ashare_trading_time_to_progress_and_clock_minute() -> None:
    assert ashare_expected_volume_progress(datetime(2026, 5, 6, 9, 29, 59, tzinfo=TZ)) == 1
    assert ashare_expected_volume_progress(datetime(2026, 5, 6, 13, 30, tzinfo=TZ)) == 0.625
    assert ashare_expected_volume_progress(datetime(2026, 5, 6, 15, 30, tzinfo=TZ)) == 1
    assert ashare_volume_clock_minute(datetime(2026, 5, 6, 11, 45, tzinfo=TZ)) == 690


def test_invalid_current_volume_is_structured_unavailable() -> None:
    result = calculate_volume_ratio(
        0,
        [1000, 800, 600],
        [],
        datetime(2026, 5, 6, 10, 0, tzinfo=TZ),
    )
    assert result["status"] == "unavailable"
    assert result["reason"] == "invalid_current_volume"


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def sort(self, *_args: Any, **_kwargs: Any) -> "_FakeCursor":
        return self

    def limit(self, size: int) -> list[dict[str, Any]]:
        return self.rows[:size]

    def __iter__(self):  # noqa: D105
        return iter(self.rows)


class _FakeCollection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        filtered = list(self.rows)
        match = pipeline[0].get("$match", {}) if pipeline else {}
        codes = match.get("code", {})
        if isinstance(codes, dict) and "$in" in codes:
            code_set = set(codes["$in"])
            filtered = [row for row in filtered if row.get("code") in code_set]
        types = match.get("type", {})
        if isinstance(types, dict) and "$in" in types:
            type_set = set(types["$in"])
            filtered = [row for row in filtered if row.get("type") in type_set]
        elif isinstance(types, str):
            filtered = [row for row in filtered if row.get("type") == types]
        date_filter = match.get("tradingDate", {})
        if isinstance(date_filter, dict) and "$lt" in date_filter:
            before = date_filter["$lt"]
            filtered = [row for row in filtered if row.get("tradingDate", "") < before]
        dates = sorted({str(row.get("tradingDate") or "") for row in filtered if row.get("tradingDate")}, reverse=True)
        limit = 0
        for stage in pipeline:
            if "$limit" in stage:
                limit = int(stage["$limit"])
        if limit > 0:
            dates = dates[:limit]
        return [{"_id": date} for date in dates]

    def find(self, query: dict[str, Any], _projection: dict[str, Any] | None = None) -> _FakeCursor:
        filtered = list(self.rows)
        codes = query.get("code", {})
        if isinstance(codes, dict) and "$in" in codes:
            code_set = set(codes["$in"])
            filtered = [row for row in filtered if row.get("code") in code_set]
        types = query.get("type", {})
        if isinstance(types, dict) and "$in" in types:
            type_set = set(types["$in"])
            filtered = [row for row in filtered if row.get("type") in type_set]
        elif isinstance(types, str):
            filtered = [row for row in filtered if row.get("type") == types]
        date_filter = query.get("tradingDate", {})
        if isinstance(date_filter, dict) and "$in" in date_filter:
            date_set = set(date_filter["$in"])
            filtered = [row for row in filtered if row.get("tradingDate") in date_set]
        if isinstance(date_filter, dict) and "$gte" in date_filter:
            after = date_filter["$gte"]
            filtered = [row for row in filtered if row.get("tradingDate", "") >= after]
        if isinstance(date_filter, dict) and "$lt" in date_filter:
            before = date_filter["$lt"]
            filtered = [row for row in filtered if row.get("tradingDate", "") < before]
        slot_filter = query.get("slotTime", {})
        if isinstance(slot_filter, dict) and "$in" in slot_filter:
            slot_set = set(slot_filter["$in"])
            filtered = [row for row in filtered if row.get("slotTime") in slot_set]
        return _FakeCursor(filtered)


class _FakeDb:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.snapshot_stock_rows = _FakeCollection(rows)

    def __getitem__(self, name: str) -> _FakeCollection:
        return getattr(self, name)


def test_build_daily_history_returns_latest_first_volumes() -> None:
    db = _FakeDb(
        [
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-06", "volume": 1000, "timestamp": 3},
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-05", "volume": 800, "timestamp": 2},
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-04", "volume": 600, "timestamp": 1},
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-07", "volume": 9999, "timestamp": 4},
            {"code": "600001", "type": "daily", "tradingDate": "2026-05-06", "volume": 500, "timestamp": 3},
        ]
    )
    history = build_daily_history(db, ["600000"], "2026-05-07")
    assert history == {"600000": [1000, 800, 600]}


def test_build_intraday_history_interpolates_to_target_minute() -> None:
    rows = []
    for date, slot, volume in [
        ("2026-05-06", "10:00", 100),
        ("2026-05-06", "10:30", 200),
        ("2026-05-05", "10:00", 80),
        ("2026-05-05", "10:30", 160),
    ]:
        rows.append(
            {
                "code": "600000",
                "type": "half_hour",
                "tradingDate": date,
                "slotTime": slot,
                "volume": volume,
                "rowId": f"{date}:{slot}",
            }
        )
    db = _FakeDb(rows)
    history = build_intraday_history(db, ["600000"], "2026-05-07", 615)
    # 10:15 插值：100 + (200-100)*(15/30) = 150；05-05 同理 120
    assert history == {"600000": [150, 120]}


def test_compute_volume_ratios_is_partial_fail_visible() -> None:
    db = _FakeDb(
        [
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-06", "volume": 1000, "timestamp": 3},
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-05", "volume": 800, "timestamp": 2},
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-04", "volume": 600, "timestamp": 1},
        ]
    )
    items = compute_volume_ratios(
        db,
        [
            {"code": "600000", "volume": 500},
            {"code": "600002", "volume": 100},
            {"code": "bad", "volume": 10},
        ],
        now=datetime(2026, 5, 7, 10, 0, tzinfo=TZ),
    )
    assert set(items.keys()) == {"600000", "600002"}
    assert items["600000"]["status"] == "fresh"
    assert items["600002"]["reason"] == "insufficient_history"


def test_volume_ratio_route_returns_items(monkeypatch) -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    def fake_db() -> object:
        return object()

    def fake_compute(db: Any, stocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            "600000": {
                "value": 2.16,
                "status": "fresh",
                "source": "intraday_snapshot",
                "currentVolume": 200,
                "expectedVolume": 92.5,
                "historyVolumes": [100, 80],
                "rawRatio": 2.1622,
                "capped": False,
                "calculatedAt": 1,
            }
        }

    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        fake_db,
    )
    monkeypatch.setattr("backend.api.market_data_routes.compute_volume_ratios", fake_compute)

    response = client.post(
        "/api/quotes/volume-ratio",
        json={"stocks": [{"code": "600000", "volume": 200}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["items"]["600000"]["value"] == 2.16

    empty = client.post("/api/quotes/volume-ratio", json={"stocks": []})
    assert empty.json()["ok"] is False
    assert empty.json()["errorCode"] == "missing_stocks"


def test_warmup_daily_history_cache_loads_full_market_without_code_filter() -> None:
    db = _FakeDb(
        [
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-06", "volume": 1000, "timestamp": 3},
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-05", "volume": 800, "timestamp": 2},
            {"code": "600001", "type": "daily", "tradingDate": "2026-05-06", "volume": 500, "timestamp": 3},
        ]
    )
    history = warmup_daily_history_cache(db, "2026-05-07")
    # 全市场装入：不按 code 过滤，两只票都进缓存，最新在前
    assert history["600000"] == [1000, 800]
    assert history["600001"] == [500]


def test_warmup_populates_cache_so_build_daily_skips_mongo(monkeypatch) -> None:
    store: dict[str, Any] = {}

    monkeypatch.setattr(
        "backend.services.market.volume_ratio_service._cache_get",
        lambda key: store.get(key),
    )
    monkeypatch.setattr(
        "backend.services.market.volume_ratio_service._cache_set",
        lambda key, value, ttl: store.__setitem__(key, value),
    )
    db = _FakeDb(
        [
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-06", "volume": 1000, "timestamp": 3},
            {"code": "600000", "type": "daily", "tradingDate": "2026-05-05", "volume": 800, "timestamp": 2},
        ]
    )
    warmup_daily_history_cache(db, "2026-05-07")

    # 预热后缓存已含 600000：build_daily_history 应命中缓存，不再触发 Mongo find
    find_calls = {"count": 0}
    original_find = db.snapshot_stock_rows.find

    def counting_find(query: dict[str, Any], projection: dict[str, Any] | None = None):
        find_calls["count"] += 1
        return original_find(query, projection)

    db.snapshot_stock_rows.find = counting_find  # type: ignore[method-assign]
    history = build_daily_history(db, ["600000"], "2026-05-07")
    assert history == {"600000": [1000, 800]}
    assert find_calls["count"] == 0
