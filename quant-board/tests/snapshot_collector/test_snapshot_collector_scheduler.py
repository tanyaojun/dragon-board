from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest


TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _ts_ms(dt: datetime.datetime) -> int:
    """Convert a timezone-aware datetime to epoch milliseconds."""
    return int(dt.timestamp() * 1000)


# ═══════════════════════════════════════════════════════════════════════════════
# Trading Calendar Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestTradingCalendar:
    """Tests for quant-board/backend/snapshot_collector/trading_calendar.py."""

    def test_uses_bridge_standard_calendar_for_trading_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.snapshot_collector.trading_calendar import is_trading_day

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar._fetch_bridge_calendar",
            lambda date: True,
        )
        assert is_trading_day(datetime.date(2026, 7, 25)) is True

    def test_uses_bridge_standard_calendar_for_non_trading_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.snapshot_collector.trading_calendar import is_trading_day

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar._fetch_bridge_calendar",
            lambda date: False,
        )
        assert is_trading_day(datetime.date(2026, 7, 24)) is False

    def test_calendar_unavailable_stops_instead_of_guessing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.snapshot_collector.trading_calendar import (
            TradingCalendarUnavailable,
            is_trading_day,
        )

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar._fetch_bridge_calendar",
            lambda date: None,
        )
        with pytest.raises(TradingCalendarUnavailable):
            is_trading_day(datetime.date(2026, 7, 25))

    def test_trading_date_from_ts_normal_day(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Timestamp during a Monday afternoon in Shanghai gives the correct date string."""
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar._CACHE_PATH",
            tmp_path / "calendar_cache.json",
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar._fetch_bridge_calendar",
            lambda date: True,
        )

        dt = datetime.datetime(2026, 6, 15, 14, 30, 0, tzinfo=TZ_SHANGHAI)
        result = trading_date_from_ts(_ts_ms(dt))
        assert result == "2026-06-15"

    def test_trading_date_from_ts_non_trading_day(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The bridge calendar decides whether the date is a trading day."""
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar._CACHE_PATH",
            tmp_path / "calendar_cache.json",
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar._fetch_bridge_calendar",
            lambda date: False,
        )

        dt = datetime.datetime(2026, 6, 13, 10, 0, 0, tzinfo=TZ_SHANGHAI)
        result = trading_date_from_ts(_ts_ms(dt))
        assert result is None

    def test_trading_date_from_ts_midnight_edge(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Timestamp at exactly midnight Asia/Shanghai on a trading day."""
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar._CACHE_PATH",
            tmp_path / "calendar_cache.json",
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar._fetch_bridge_calendar",
            lambda date: True,
        )

        dt = datetime.datetime(2026, 6, 15, 0, 0, 0, tzinfo=TZ_SHANGHAI)
        result = trading_date_from_ts(_ts_ms(dt))
        assert result == "2026-06-15"


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers for Scheduler Tests
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FakeRepo:
    """Fake repository for scheduler tests."""

    existing_snapshots: set[str] = field(default_factory=set)
    _should_fail: bool = False

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
        del dataset_id
        if self._should_fail:
            raise RuntimeError("Simulated MongoDB error")
        return snapshot_id in self.existing_snapshots


@dataclass
class FakeService:
    """Fake collector service that records calls."""

    calls: list = field(default_factory=list)
    _result_status: str = "completed"

    def run_once(self, request: Any) -> Any:
        self.calls.append(request)
        from backend.snapshot_collector.models import CollectorRunResult

        return CollectorRunResult(
            status=self._result_status,
            snapshot_id=f"{request.snapshot_type}:{request.trading_date}:{request.slot_time}",
        )


def make_test_slot(
    snapshot_type: str = "half_hour",
    trading_date: str = "2026-06-15",
    slot_time: str = "10:00",
    timestamp_ms: int = 1_000_000,
):
    """Create a SnapshotSlot for testing."""
    from backend.snapshot_collector.models import SnapshotSlot

    return SnapshotSlot(snapshot_type, trading_date, slot_time, timestamp_ms)


def _make_settings(**overrides: Any):
    """Create a Settings instance with MongoDB backend and collector enabled by default."""
    from backend.core.settings import Settings, get_settings

    get_settings.cache_clear()

    env_overrides: dict[str, str] = {}
    if "storage_backend" in overrides:
        env_overrides["QUANT_BOARD_STORAGE_BACKEND"] = overrides["storage_backend"]
    else:
        env_overrides["QUANT_BOARD_STORAGE_BACKEND"] = "mongodb"

    if "snapshot_collector_enabled" in overrides:
        env_overrides["QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED"] = str(
            overrides["snapshot_collector_enabled"]
        ).lower()
    if "snapshot_collector_dataset_id" in overrides:
        env_overrides["QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID"] = overrides[
            "snapshot_collector_dataset_id"
        ]
    if "snapshot_collector_types" in overrides:
        env_overrides["QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES"] = overrides[
            "snapshot_collector_types"
        ]
    if "snapshot_collector_close_grace_minutes" in overrides:
        env_overrides["QUANT_BOARD_SNAPSHOT_COLLECTOR_GRACE_MINUTES"] = str(
            overrides["snapshot_collector_close_grace_minutes"]
        )

    defaults: dict[str, Any] = dict(
        storage_backend="mongodb",
        snapshot_collector_enabled=True,
        snapshot_collector_dataset_id="test_dataset",
        snapshot_collector_types="half_hour,daily",
        snapshot_collector_close_grace_minutes=5,
    )
    defaults.update(overrides)
    env_overrides.setdefault(
        "QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES", defaults["snapshot_collector_types"]
    )
    env_overrides.setdefault(
        "QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID",
        defaults["snapshot_collector_dataset_id"],
    )

    import os

    _saved: dict[str, str] = {}
    for key, val in env_overrides.items():
        _saved[key] = os.environ.get(key, "")
        os.environ[key] = val

    try:
        settings = Settings(**defaults)
    finally:
        for key, saved_val in _saved.items():
            if saved_val:
                os.environ[key] = saved_val
            else:
                os.environ.pop(key, None)

    return settings


def _scheduler(monkeypatch: pytest.MonkeyPatch, **settings_overrides: Any) -> Any:
    """Build a SnapshotCollectorScheduler with patched settings."""
    from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

    fake_settings = _make_settings(**settings_overrides)
    monkeypatch.setattr(
        "backend.snapshot_collector.scheduler.get_settings",
        lambda: fake_settings,
    )
    return SnapshotCollectorScheduler()


def _patch_clock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    now_ms: int,
    trading_date: str | None = "2026-06-15",
) -> None:
    monkeypatch.setattr("backend.snapshot_collector.scheduler.time.time", lambda: now_ms / 1000.0)
    monkeypatch.setattr(
        "backend.snapshot_collector.trading_calendar.trading_date_from_ts",
        lambda ts: trading_date,
    )


def _patch_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    slots: list[Any],
    *,
    repo: FakeRepo | None = None,
    service: FakeService | None = None,
) -> None:
    monkeypatch.setattr(
        "backend.snapshot_collector.slots.generate_slots",
        lambda date, types: slots,
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.service_factory.create_snapshot_collector_repository",
        lambda: repo or FakeRepo(),
    )
    if service is not None:
        monkeypatch.setattr(
            "backend.snapshot_collector.service_factory.create_snapshot_collector_service",
            lambda repo_: service,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Scheduler Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSnapshotCollectorScheduler:
    """Tests for the timer-based SnapshotCollectorScheduler."""

    # ── init ─────────────────────────────────────────────────────────────

    def test_init_reads_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler = _scheduler(
            monkeypatch,
            snapshot_collector_types="hourly,quarter_hour",
            snapshot_collector_close_grace_minutes=10,
        )

        assert scheduler.enabled is True
        assert scheduler.dataset_id == "test_dataset"
        assert scheduler.snapshot_types == ["hourly", "quarter_hour"]
        assert scheduler.grace_minutes == 10
        assert scheduler._task is None
        assert scheduler._collection_count == 0
        assert scheduler._error_count == 0

    def test_init_disabled_when_not_mongodb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler = _scheduler(monkeypatch, storage_backend="sqlite", snapshot_collector_enabled=True)
        assert scheduler.enabled is False

    def test_init_disabled_when_flag_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler = _scheduler(
            monkeypatch,
            storage_backend="mongodb",
            snapshot_collector_enabled=False,
        )
        assert scheduler.enabled is False

    # ── start / stop ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_start_creates_task_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler = _scheduler(monkeypatch)
        scheduler.start()
        assert scheduler._task is not None
        assert scheduler.running is True
        await scheduler.stop()

    def test_start_noop_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler = _scheduler(monkeypatch, snapshot_collector_enabled=False)
        scheduler.start()
        assert scheduler._task is None

    @pytest.mark.asyncio
    async def test_start_noop_when_already_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler = _scheduler(monkeypatch)
        scheduler.start()
        first_task = scheduler._task
        scheduler.start()
        assert scheduler._task is first_task
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler = _scheduler(monkeypatch)
        scheduler.start()
        assert scheduler._task is not None
        await scheduler.stop()
        assert scheduler._task is None

    @pytest.mark.asyncio
    async def test_stop_noop_when_not_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        scheduler = _scheduler(monkeypatch)
        await scheduler.stop()
        assert scheduler._task is None

    @pytest.mark.asyncio
    async def test_finished_task_is_not_reported_running_and_can_restart(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        scheduler = _scheduler(monkeypatch)
        scheduler._task = asyncio.create_task(asyncio.sleep(0))
        await scheduler._task

        assert scheduler.running is False

        scheduler.start()
        assert scheduler._task is not None
        assert scheduler._task.done() is False
        await scheduler.stop()

    # ── status ───────────────────────────────────────────────────────────

    def test_status_returns_expected_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now_ms = _ts_ms(datetime.datetime(2026, 6, 15, 10, 0, 0, tzinfo=TZ_SHANGHAI))
        slot = make_test_slot(timestamp_ms=now_ms + 1000)
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot])
        scheduler = _scheduler(monkeypatch)

        status = scheduler.status()

        required_keys = {
            "enabled",
            "running",
            "dataset_id",
            "snapshot_types",
            "grace_minutes",
            "is_trading_day",
            "trading_date",
            "in_session",
            "upcoming_slot",
            "last_run_at",
            "last_slot_collected",
            "last_error",
            "last_error_at",
            "last_error_slot",
            "collection_count",
            "error_count",
            "in_flight_slots",
        }
        assert required_keys.issubset(set(status.keys()))
        assert status["enabled"] is True
        assert status["running"] is False
        assert status["is_trading_day"] is True
        assert status["trading_date"] == "2026-06-15"
        assert status["in_session"] is True
        assert status["upcoming_slot"] == slot.snapshot_id
        assert status["collection_count"] == 0
        assert status["error_count"] == 0

    # ── next-slot timer ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_seconds_until_next_slot_on_trading_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot(
            timestamp_ms=_ts_ms(datetime.datetime(2026, 6, 15, 10, 0, 0, tzinfo=TZ_SHANGHAI))
        )
        now_ms = _ts_ms(datetime.datetime(2026, 6, 15, 9, 0, 0, tzinfo=TZ_SHANGHAI))
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot])
        scheduler = _scheduler(monkeypatch)

        assert await scheduler._seconds_until_next_slot() == pytest.approx(3600.0)

    @pytest.mark.asyncio
    async def test_seconds_until_next_slot_non_trading_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_clock(monkeypatch, now_ms=1_000_000, trading_date=None)
        scheduler = _scheduler(monkeypatch)

        assert await scheduler._seconds_until_next_slot() == 1800.0

    @pytest.mark.asyncio
    async def test_seconds_until_next_slot_all_done_returns_idle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot(
            timestamp_ms=_ts_ms(datetime.datetime(2026, 6, 15, 10, 0, 0, tzinfo=TZ_SHANGHAI))
        )
        # 10:00 槽位已完成，但时钟仍处采集窗口内（10:00 < 16:00）：应返回 1800s 空闲轮询。
        _patch_clock(monkeypatch, now_ms=slot.timestamp_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot])
        scheduler = _scheduler(monkeypatch)
        scheduler._completed_today.add(slot.snapshot_id)

        assert await scheduler._seconds_until_next_slot() == 1800.0

    @pytest.mark.asyncio
    async def test_seconds_until_next_slot_skips_in_flight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot(
            timestamp_ms=_ts_ms(datetime.datetime(2026, 6, 15, 10, 0, 0, tzinfo=TZ_SHANGHAI))
        )
        # 时钟 09:59:59（窗口内），槽位 in-flight：返回 1800s 空闲轮询。
        now_ms = slot.timestamp_ms - 1000
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot])
        scheduler = _scheduler(monkeypatch)
        scheduler._in_flight_slots.add(slot.snapshot_id)

        assert await scheduler._seconds_until_next_slot() == 1800.0

    @pytest.mark.asyncio
    async def test_seconds_until_next_slot_after_close_sleeps_until_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 16:00 后（非采集窗口）：即使有未完成槽位也不调度，睡到次日 09:00 窗口再开。
        slot = make_test_slot(
            timestamp_ms=_ts_ms(datetime.datetime(2026, 6, 15, 15, 30, 0, tzinfo=TZ_SHANGHAI))
        )
        now_ms = _ts_ms(datetime.datetime(2026, 6, 15, 17, 0, 0, tzinfo=TZ_SHANGHAI))
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot])
        scheduler = _scheduler(monkeypatch)

        # 17:00 -> 次日 09:00 = 16 小时
        assert await scheduler._seconds_until_next_slot() == 16 * 3600.0

    # ── due-slot dispatch ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_collect_due_slots_dispatches_eligible_slot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slot = make_test_slot()
        fake_repo = FakeRepo()
        fake_service = FakeService()
        _patch_clock(monkeypatch, now_ms=slot.timestamp_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot], repo=fake_repo, service=fake_service)
        scheduler = _scheduler(monkeypatch)

        await scheduler._collect_due_slots()
        assert slot.snapshot_id in scheduler._in_flight_slots

        await asyncio.sleep(0.1)
        assert len(fake_service.calls) == 1
        assert scheduler._collection_count == 1
        assert slot.snapshot_id in scheduler._completed_today

    @pytest.mark.asyncio
    async def test_collect_due_slots_dispatches_within_grace_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slot = make_test_slot(timestamp_ms=1_000_000)
        fake_service = FakeService()
        _patch_clock(monkeypatch, now_ms=1_000_000 + 60_000, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot], service=fake_service)
        scheduler = _scheduler(monkeypatch)

        await scheduler._collect_due_slots()
        await asyncio.sleep(0.1)
        assert len(fake_service.calls) == 1

    @pytest.mark.asyncio
    async def test_collect_due_slots_skips_non_trading_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_clock(monkeypatch, now_ms=1_000_000, trading_date=None)
        scheduler = _scheduler(monkeypatch)
        generate_called = False

        def _tracking_generate(date, types):
            nonlocal generate_called
            generate_called = True
            return []

        monkeypatch.setattr(
            "backend.snapshot_collector.slots.generate_slots",
            _tracking_generate,
        )

        await scheduler._collect_due_slots()
        assert not generate_called

    @pytest.mark.asyncio
    async def test_collect_due_slots_skips_not_yet_due(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot(timestamp_ms=1_000_000)
        fake_service = FakeService()
        _patch_clock(monkeypatch, now_ms=999_999, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot], service=fake_service)
        scheduler = _scheduler(monkeypatch)

        await scheduler._collect_due_slots()
        await asyncio.sleep(0.1)
        assert len(fake_service.calls) == 0
        assert slot.snapshot_id not in scheduler._in_flight_slots

    @pytest.mark.asyncio
    async def test_collect_due_slots_skips_expired_beyond_grace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slot = make_test_slot(timestamp_ms=1_000_000)
        fake_service = FakeService()
        grace_ms = 5 * 60 * 1000
        _patch_clock(monkeypatch, now_ms=1_000_000 + grace_ms + 1, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot], service=fake_service)
        scheduler = _scheduler(monkeypatch)

        await scheduler._collect_due_slots()
        await asyncio.sleep(0.1)
        assert len(fake_service.calls) == 0
        assert slot.snapshot_id in scheduler._completed_today

    @pytest.mark.asyncio
    async def test_collect_due_slots_skips_in_flight(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot(timestamp_ms=1_000_000)
        fake_service = FakeService()
        _patch_clock(monkeypatch, now_ms=slot.timestamp_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot], service=fake_service)
        scheduler = _scheduler(monkeypatch)
        scheduler._in_flight_slots.add(slot.snapshot_id)

        await scheduler._collect_due_slots()
        await asyncio.sleep(0.1)
        assert len(fake_service.calls) == 0

    @pytest.mark.asyncio
    async def test_collect_due_slots_skips_persisted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot(timestamp_ms=1_000_000)
        fake_repo = FakeRepo(existing_snapshots={slot.snapshot_id})
        fake_service = FakeService()
        _patch_clock(monkeypatch, now_ms=slot.timestamp_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot], repo=fake_repo, service=fake_service)
        scheduler = _scheduler(monkeypatch)

        await scheduler._collect_due_slots()
        await asyncio.sleep(0.1)
        assert len(fake_service.calls) == 0
        assert slot.snapshot_id not in scheduler._in_flight_slots
        assert slot.snapshot_id in scheduler._completed_today

    # ── per-slot collection ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_tracked_collect_updates_counters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot()
        _patch_dispatch(monkeypatch, [slot], repo=FakeRepo(), service=FakeService())
        scheduler = _scheduler(monkeypatch)
        scheduler._in_flight_slots.add(slot.snapshot_id)

        await scheduler._tracked_collect(slot)

        assert scheduler._collection_count == 1
        assert scheduler._last_slot_collected == slot.snapshot_id
        assert scheduler._last_run_at is not None
        assert slot.snapshot_id in scheduler._completed_today
        assert slot.snapshot_id not in scheduler._in_flight_slots

    @pytest.mark.asyncio
    async def test_tracked_collect_skips_existing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot()
        fake_service = FakeService()
        _patch_dispatch(
            monkeypatch,
            [slot],
            repo=FakeRepo(existing_snapshots={slot.snapshot_id}),
            service=fake_service,
        )
        scheduler = _scheduler(monkeypatch)
        scheduler._in_flight_slots.add(slot.snapshot_id)

        await scheduler._tracked_collect(slot)

        assert scheduler._collection_count == 0
        assert len(fake_service.calls) == 0
        assert slot.snapshot_id in scheduler._completed_today
        assert slot.snapshot_id not in scheduler._in_flight_slots

    @pytest.mark.asyncio
    async def test_tracked_collect_handles_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot()
        _patch_dispatch(monkeypatch, [slot], repo=FakeRepo(_should_fail=True))
        scheduler = _scheduler(monkeypatch)
        scheduler._in_flight_slots.add(slot.snapshot_id)

        await scheduler._tracked_collect(slot)

        assert scheduler._error_count == 1
        assert scheduler._last_error is not None
        assert "Simulated MongoDB error" in scheduler._last_error
        assert scheduler._last_error_slot == slot.snapshot_id
        assert slot.snapshot_id not in scheduler._in_flight_slots

    @pytest.mark.asyncio
    async def test_tracked_collect_deduped_not_counted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        slot = make_test_slot()
        _patch_dispatch(
            monkeypatch,
            [slot],
            repo=FakeRepo(),
            service=FakeService(_result_status="deduped"),
        )
        scheduler = _scheduler(monkeypatch)
        scheduler._in_flight_slots.add(slot.snapshot_id)

        await scheduler._tracked_collect(slot)

        assert scheduler._collection_count == 0
        assert scheduler._error_count == 0
        assert slot.snapshot_id in scheduler._completed_today
        assert slot.snapshot_id not in scheduler._in_flight_slots

    @pytest.mark.asyncio
    async def test_tracked_collect_treats_blocked_result_as_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slot = make_test_slot()
        _patch_dispatch(
            monkeypatch,
            [slot],
            repo=FakeRepo(),
            service=FakeService(_result_status="blocked"),
        )
        scheduler = _scheduler(monkeypatch)
        scheduler._in_flight_slots.add(slot.snapshot_id)

        await scheduler._tracked_collect(slot)

        assert scheduler._collection_count == 0
        assert scheduler._error_count == 1
        assert "blocked" in (scheduler._last_error or "")

    @pytest.mark.asyncio
    async def test_successful_slot_does_not_clear_another_slot_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slot = make_test_slot(slot_time="10:00")
        _patch_dispatch(monkeypatch, [slot], repo=FakeRepo(), service=FakeService())
        scheduler = _scheduler(monkeypatch)
        scheduler._last_error = "slot A failed"
        scheduler._last_error_at = "2026-06-15T10:06:00+08:00"
        scheduler._last_error_slot = "half_hour:2026-06-15:09:30"
        scheduler._in_flight_slots.add(slot.snapshot_id)

        await scheduler._tracked_collect(slot)

        assert scheduler._last_error == "slot A failed"
        assert scheduler._last_error_slot == "half_hour:2026-06-15:09:30"

    @pytest.mark.asyncio
    async def test_tracked_collect_clears_resolved_slot_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slot = make_test_slot()
        _patch_dispatch(monkeypatch, [slot], repo=FakeRepo(), service=FakeService())
        scheduler = _scheduler(monkeypatch)
        scheduler._last_error = "slot collection failed"
        scheduler._last_error_at = "2026-06-15T10:06:00+08:00"
        scheduler._last_error_slot = slot.snapshot_id
        scheduler._in_flight_slots.add(slot.snapshot_id)

        await scheduler._tracked_collect(slot)

        assert scheduler._last_error is None
        assert scheduler._last_error_at is None
        assert scheduler._last_error_slot is None


# ═══════════════════════════════════════════════════════════════════════════════
# Missed-slot visibility (fail-visible) — 2026-09-11 机器睡眠丢数据复盘
#
# 场景：机器 12:00 进入待机、19:02 唤醒，下午 6 个槽位跨过 grace 窗口且从未
# 触发采集。旧实现把过期槽位静默标记完成（无 run 记录、无 last_error），
# 数据无痕丢失。契约：唤醒后自检必须对「过期且未入库」的槽位写 blocked
# run 记录（blockingIssues=["slot_missed_grace_window"]）并置 last_error，
# 且同一槽位只写一次。
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class RunRecordingRepo(FakeRepo):
    """FakeRepo with run-record capture for missed-slot assertions."""

    inserted_runs: list = field(default_factory=list)

    def insert_run(self, run: dict) -> None:
        self.inserted_runs.append(dict(run))


def _day_slot(slot_time: str, trading_date: str = "2026-06-15"):
    ts = _ts_ms(
        datetime.datetime.strptime(
            f"{trading_date} {slot_time}", "%Y-%m-%d %H:%M"
        ).replace(tzinfo=TZ_SHANGHAI)
    )
    return make_test_slot(trading_date=trading_date, slot_time=slot_time, timestamp_ms=ts)


class TestMissedSlotVisibility:
    """_record_missed_slots_now：睡眠/冻结唤醒后的缺失槽位 fail-visible 自检。"""

    @pytest.mark.asyncio
    async def test_wakeup_after_freeze_records_missed_run_docs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now_ms = _ts_ms(datetime.datetime(2026, 6, 15, 19, 2, 0, tzinfo=TZ_SHANGHAI))
        slots = [_day_slot("11:30"), _day_slot("13:00"), _day_slot("15:30")]
        repo = RunRecordingRepo()
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, slots, repo=repo)
        scheduler = _scheduler(monkeypatch)

        await scheduler._record_missed_slots_now()

        assert {r["snapshotId"] for r in repo.inserted_runs} == {s.snapshot_id for s in slots}
        for run in repo.inserted_runs:
            assert run["status"] == "blocked"
            assert "slot_missed_grace_window" in (run.get("blockingIssues") or [])
            assert run["datasetId"] == "test_dataset"
            assert run["tradingDate"] == "2026-06-15"
            assert run["snapshotType"] == "half_hour"
        assert scheduler._last_error is not None
        assert "grace window" in scheduler._last_error
        assert scheduler._last_error_slot is not None
        assert scheduler._error_count == len(slots)
        assert {s.snapshot_id for s in slots} <= scheduler._completed_today

    @pytest.mark.asyncio
    async def test_missed_slots_recorded_only_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """idle recheck 反复唤醒时，同一缺失槽位不得重复写记录。"""
        now_ms = _ts_ms(datetime.datetime(2026, 6, 15, 19, 2, 0, tzinfo=TZ_SHANGHAI))
        slots = [_day_slot("13:00")]
        repo = RunRecordingRepo()
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, slots, repo=repo)
        scheduler = _scheduler(monkeypatch)

        await scheduler._record_missed_slots_now()
        first_count = len(repo.inserted_runs)
        assert first_count == 1

        await scheduler._record_missed_slots_now()
        assert len(repo.inserted_runs) == first_count

    @pytest.mark.asyncio
    async def test_persisted_slots_not_recorded_missed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """已入库的过期槽位只标完成，不得误报缺失。"""
        now_ms = _ts_ms(datetime.datetime(2026, 6, 15, 19, 2, 0, tzinfo=TZ_SHANGHAI))
        slots = [_day_slot("13:00")]
        repo = RunRecordingRepo(existing_snapshots={slots[0].snapshot_id})
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, slots, repo=repo)
        scheduler = _scheduler(monkeypatch)

        await scheduler._record_missed_slots_now()

        assert repo.inserted_runs == []
        assert slots[0].snapshot_id in scheduler._completed_today
        assert scheduler._last_error is None

    @pytest.mark.asyncio
    async def test_slots_within_grace_not_recorded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """grace 窗口内的槽位尚未过期，自检不得抢跑。"""
        slot = _day_slot("13:00")
        now_ms = slot.timestamp_ms + 2 * 60 * 1000  # 过期前 3 分钟
        repo = RunRecordingRepo()
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot], repo=repo)
        scheduler = _scheduler(monkeypatch)

        await scheduler._record_missed_slots_now()

        assert repo.inserted_runs == []
        assert slot.snapshot_id not in scheduler._completed_today

    @pytest.mark.asyncio
    async def test_in_flight_slots_not_recorded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """仍在采集中的槽位不得被误报缺失。"""
        slot = _day_slot("13:00")
        now_ms = slot.timestamp_ms + 10 * 60 * 1000  # 已超 grace，但采集还在跑
        repo = RunRecordingRepo()
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date="2026-06-15")
        _patch_dispatch(monkeypatch, [slot], repo=repo)
        scheduler = _scheduler(monkeypatch)
        scheduler._in_flight_slots.add(slot.snapshot_id)

        await scheduler._record_missed_slots_now()

        assert repo.inserted_runs == []

    @pytest.mark.asyncio
    async def test_non_trading_day_is_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now_ms = _ts_ms(datetime.datetime(2026, 6, 14, 19, 2, 0, tzinfo=TZ_SHANGHAI))
        repo = RunRecordingRepo()
        _patch_clock(monkeypatch, now_ms=now_ms, trading_date=None)
        _patch_dispatch(monkeypatch, [], repo=repo)
        scheduler = _scheduler(monkeypatch)

        await scheduler._record_missed_slots_now()

        assert repo.inserted_runs == []
        assert scheduler._last_error is None
