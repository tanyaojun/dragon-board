from __future__ import annotations

import asyncio
import datetime
from dataclasses import dataclass, field
from typing import Any
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


# ═══════════════════════════════════════════════════════════════════════════════
# Trading Calendar Tests (existing — do NOT modify)
# ═══════════════════════════════════════════════════════════════════════════════


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


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers for Scheduler Tests
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class FakeRepo:
    """Fake repository for scheduler tests."""
    existing_snapshots: set[str] = field(default_factory=set)
    _should_fail: bool = False

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
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
    timestamp_ms: int = 1000000,
):
    """Create a SnapshotSlot for testing."""
    from backend.snapshot_collector.models import SnapshotSlot
    return SnapshotSlot(snapshot_type, trading_date, slot_time, timestamp_ms)


def _patch_service_factory_repo(monkeypatch: pytest.MonkeyPatch, fake_repo: FakeRepo) -> None:
    """Patch create_snapshot_collector_repository in the service_factory module."""
    monkeypatch.setattr(
        "backend.snapshot_collector.service_factory.create_snapshot_collector_repository",
        lambda: fake_repo,
    )


def _patch_service_factory_service(
    monkeypatch: pytest.MonkeyPatch,
    fake_service: FakeService,
) -> None:
    """Inject a fake ``create_snapshot_collector_service``.

    Use monkeypatch so full-suite runs restore the factory after each test.
    """
    import backend.snapshot_collector.service_factory as sf

    monkeypatch.setattr(sf, "create_snapshot_collector_service", lambda repo: fake_service)


def _patch_collect_slot_imports(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: FakeRepo,
    fake_service: FakeService,
) -> None:
    """Patch all lazy imports used by _collect_slot."""
    _patch_service_factory_repo(monkeypatch, fake_repo)
    _patch_service_factory_service(monkeypatch, fake_service)


def _make_settings(**overrides: Any):
    """Create a Settings instance with MongoDB backend and collector enabled by default.

    Sets environment variables that affect ``model_post_init`` so the
    returned ``Settings`` object matches the overrides exactly.
    """
    from backend.settings import Settings, get_settings

    # Clear lru_cache so we get a fresh settings object.
    get_settings.cache_clear()

    env_overrides: dict[str, str] = {}
    if "storage_backend" in overrides:
        env_overrides["QUANT_BOARD_STORAGE_BACKEND"] = overrides["storage_backend"]
    else:
        env_overrides["QUANT_BOARD_STORAGE_BACKEND"] = "mongodb"

    if "snapshot_collector_enabled" in overrides:
        env_overrides["QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED"] = str(overrides["snapshot_collector_enabled"]).lower()

    defaults: dict[str, Any] = dict(
        storage_backend="mongodb",
        snapshot_collector_enabled=True,
        snapshot_collector_dataset_id="test_dataset",
        snapshot_collector_types="half_hour,daily",
        snapshot_collector_poll_ms=1000,
        snapshot_collector_close_grace_minutes=5,
    )
    defaults.update(overrides)

    # Temporarily set env vars so model_post_init respects the values.
    _saved: dict[str, str] = {}
    for key, val in env_overrides.items():
        import os
        _saved[key] = os.environ.get(key, "")
        os.environ[key] = val

    try:
        settings = Settings(**defaults)
    finally:
        import os
        for key, saved_val in _saved.items():
            if saved_val:
                os.environ[key] = saved_val
            else:
                os.environ.pop(key, None)

    return settings


# ═══════════════════════════════════════════════════════════════════════════════
# Scheduler Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestSnapshotCollectorScheduler:
    """Tests for the SnapshotCollectorScheduler background runner."""

    # ── init ─────────────────────────────────────────────────────────────

    def test_init_reads_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scheduler reads enabled, dataset_id, snapshot_types, poll_seconds, grace_minutes from settings."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings(
            snapshot_collector_types="hourly,quarter_hour",
            snapshot_collector_poll_ms=5000,
            snapshot_collector_close_grace_minutes=10,
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()

        assert s.enabled is True
        assert s.dataset_id == "test_dataset"
        assert s.snapshot_types == ["hourly", "quarter_hour"]
        assert s.poll_seconds == pytest.approx(5.0)
        assert s.grace_minutes == 10
        assert s._task is None
        assert s._collection_count == 0
        assert s._error_count == 0

    def test_init_disabled_when_not_mongodb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scheduler auto-disables when storage_backend is not 'mongodb'."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings(
            storage_backend="sqlite",
            snapshot_collector_enabled=True,
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        assert s.enabled is False

    def test_init_disabled_when_flag_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scheduler is disabled when snapshot_collector_enabled is False even with MongoDB."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings(
            storage_backend="mongodb",
            snapshot_collector_enabled=False,
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        assert s.enabled is False

    # ── start ────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_start_creates_task_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """start() creates a background asyncio.Task when enabled."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        s.start()
        assert s._task is not None
        await s.stop()

    def test_start_noop_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """start() is a no-op when the scheduler is disabled."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings(snapshot_collector_enabled=False)
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        s.start()
        assert s._task is None

    @pytest.mark.asyncio
    async def test_start_noop_when_already_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Calling start() twice does not create a second task."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        s.start()
        first_task = s._task
        s.start()  # second call should be no-op
        assert s._task is first_task
        await s.stop()

    # ── stop ─────────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """stop() cancels the background task and clears the reference."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        s.start()
        assert s._task is not None
        await s.stop()
        assert s._task is None

    @pytest.mark.asyncio
    async def test_stop_noop_when_not_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """stop() is safe to call when the scheduler was never started."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        await s.stop()  # should not raise
        assert s._task is None

    # ── status ───────────────────────────────────────────────────────────

    def test_status_returns_expected_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """status() returns a dict with all required keys."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        status = s.status()

        required_keys = {
            "enabled",
            "running",
            "dataset_id",
            "snapshot_types",
            "poll_seconds",
            "grace_minutes",
            "last_run_at",
            "last_slot_collected",
            "last_error",
            "collection_count",
            "error_count",
            "in_flight_slots",
        }
        assert required_keys.issubset(set(status.keys()))
        assert status["enabled"] is True
        assert status["running"] is False
        assert status["collection_count"] == 0
        assert status["error_count"] == 0

    # ── _poll_once dispatch ──────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_poll_once_dispatches_eligible_slot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_poll_once dispatches an eligible slot to a background collection task."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()

        # Patch lazy imports in _poll_once and _collect_slot at their source modules
        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar.trading_date_from_ts",
            lambda ts: "2026-06-15",
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.generate_slots",
            lambda date, types: [slot],
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.is_slot_eligible",
            lambda now_ts, slot_, grace_minutes=5: True,
        )

        fake_repo = FakeRepo()
        fake_service = FakeService()

        _patch_collect_slot_imports(monkeypatch, fake_repo, fake_service)

        await s._poll_once()

        # Slot should be added to in-flight immediately
        assert slot.snapshot_id in s._in_flight_slots

        # Let the background task complete
        await asyncio.sleep(0.1)

        # After background task completes, the service should have been called
        assert len(fake_service.calls) == 1

    @pytest.mark.asyncio
    async def test_poll_once_skips_non_trading_day(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_poll_once returns early when the current date is not a trading day."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()

        # Non-trading day: trading_date_from_ts returns None
        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar.trading_date_from_ts",
            lambda ts: None,
        )

        generate_called = False
        def _tracking_generate(date, types):
            nonlocal generate_called
            generate_called = True
            return []

        monkeypatch.setattr(
            "backend.snapshot_collector.slots.generate_slots",
            _tracking_generate,
        )

        await s._poll_once()
        assert not generate_called, "generate_slots should not be called on non-trading days"

    @pytest.mark.asyncio
    async def test_poll_once_skips_in_flight_slots(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_poll_once does not dispatch a slot that is already in-flight."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()

        # Pre-populate in-flight
        s._in_flight_slots.add(slot.snapshot_id)

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar.trading_date_from_ts",
            lambda ts: "2026-06-15",
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.generate_slots",
            lambda date, types: [slot],
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.is_slot_eligible",
            lambda now_ts, slot_, grace_minutes=5: True,
        )

        fake_repo = FakeRepo()
        fake_service = FakeService()
        _patch_collect_slot_imports(monkeypatch, fake_repo, fake_service)

        await s._poll_once()
        await asyncio.sleep(0.1)

        # The in-flight slot should have been skipped — no collection happened
        assert len(fake_service.calls) == 0

    @pytest.mark.asyncio
    async def test_poll_once_skips_persisted_slots_before_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_poll_once checks persisted snapshots before creating a task."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar.trading_date_from_ts",
            lambda ts: "2026-06-15",
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.generate_slots",
            lambda date, types: [slot],
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.is_slot_eligible",
            lambda now_ts, slot_, grace_minutes=5: True,
        )

        fake_repo = FakeRepo(existing_snapshots={slot.snapshot_id})
        fake_service = FakeService()
        _patch_collect_slot_imports(monkeypatch, fake_repo, fake_service)

        created_tasks: list[Any] = []
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.asyncio.create_task",
            lambda coro: created_tasks.append(coro),
        )

        await s._poll_once()

        assert created_tasks == []
        assert len(fake_service.calls) == 0
        assert slot.snapshot_id not in s._in_flight_slots

    @pytest.mark.asyncio
    async def test_poll_once_skips_ineligible_slots(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_poll_once does not dispatch slots that fail the eligibility check."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar.trading_date_from_ts",
            lambda ts: "2026-06-15",
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.generate_slots",
            lambda date, types: [slot],
        )
        # All slots are ineligible
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.is_slot_eligible",
            lambda now_ts, slot_, grace_minutes=5: False,
        )

        fake_repo = FakeRepo()
        fake_service = FakeService()
        _patch_collect_slot_imports(monkeypatch, fake_repo, fake_service)

        await s._poll_once()
        await asyncio.sleep(0.1)

        assert len(fake_service.calls) == 0
        assert slot.snapshot_id not in s._in_flight_slots

    # ── _collect_slot ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_collect_slot_updates_counters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Successful collection increments _collection_count and sets _last_slot_collected."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()
        s._in_flight_slots.add(slot.snapshot_id)

        fake_repo = FakeRepo()
        fake_service = FakeService(_result_status="completed")

        _patch_collect_slot_imports(monkeypatch, fake_repo, fake_service)

        await s._collect_slot(slot)

        assert s._collection_count == 1
        assert s._last_slot_collected == slot.snapshot_id
        assert slot.snapshot_id not in s._in_flight_slots

    @pytest.mark.asyncio
    async def test_collect_slot_skips_existing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When snapshot already exists in repo, collection is skipped and counter not incremented."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()
        s._in_flight_slots.add(slot.snapshot_id)

        # Repo says the snapshot already exists
        fake_repo = FakeRepo(existing_snapshots={slot.snapshot_id})
        fake_service = FakeService()

        _patch_collect_slot_imports(monkeypatch, fake_repo, fake_service)

        await s._collect_slot(slot)

        assert s._collection_count == 0  # skipped
        assert len(fake_service.calls) == 0
        assert slot.snapshot_id not in s._in_flight_slots

    @pytest.mark.asyncio
    async def test_collect_slot_handles_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When repo raises, _error_count is incremented and slot is still removed from in-flight."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()
        s._in_flight_slots.add(slot.snapshot_id)

        fake_repo = FakeRepo(_should_fail=True)
        monkeypatch.setattr(
            "backend.snapshot_collector.service_factory.create_snapshot_collector_repository",
            lambda: fake_repo,
        )

        await s._collect_slot(slot)

        assert s._error_count == 1
        assert s._last_error is not None
        assert "Simulated MongoDB error" in s._last_error
        # Finally block always cleans up in_flight_slots
        assert slot.snapshot_id not in s._in_flight_slots

    @pytest.mark.asyncio
    async def test_collect_slot_does_not_increment_on_deduped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Deduped result does not increment _collection_count."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()
        s._in_flight_slots.add(slot.snapshot_id)

        fake_repo = FakeRepo()
        fake_service = FakeService(_result_status="deduped")

        _patch_collect_slot_imports(monkeypatch, fake_repo, fake_service)

        await s._collect_slot(slot)

        # "deduped" status should NOT increment collection_count
        assert s._collection_count == 0
        assert s._error_count == 0
        assert slot.snapshot_id not in s._in_flight_slots

    # ── grace window ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_poll_once_with_grace_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Slots within the grace window are dispatched for collection."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar.trading_date_from_ts",
            lambda ts: "2026-06-15",
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.generate_slots",
            lambda date, types: [slot],
        )
        # Simulate grace window: slot is eligible (now_ts is within grace_ms after slot timestamp)
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.is_slot_eligible",
            lambda now_ts, slot_, grace_minutes=5: True,
        )

        fake_repo = FakeRepo()
        fake_service = FakeService()
        _patch_collect_slot_imports(monkeypatch, fake_repo, fake_service)

        await s._poll_once()
        await asyncio.sleep(0.1)

        assert len(fake_service.calls) == 1

    # ── concurrent protection ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_in_flight_prevents_duplicate_dispatch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Once a slot is in _in_flight_slots, a second poll does not re-dispatch it."""
        from backend.snapshot_collector.scheduler import SnapshotCollectorScheduler

        fake_settings = _make_settings()
        monkeypatch.setattr(
            "backend.snapshot_collector.scheduler.get_settings",
            lambda: fake_settings,
        )

        s = SnapshotCollectorScheduler()
        slot = make_test_slot()

        monkeypatch.setattr(
            "backend.snapshot_collector.trading_calendar.trading_date_from_ts",
            lambda ts: "2026-06-15",
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.generate_slots",
            lambda date, types: [slot],
        )
        monkeypatch.setattr(
            "backend.snapshot_collector.slots.is_slot_eligible",
            lambda now_ts, slot_, grace_minutes=5: True,
        )

        fake_repo = FakeRepo()
        fake_service = FakeService()
        _patch_collect_slot_imports(monkeypatch, fake_repo, fake_service)

        # First poll dispatches the slot
        await s._poll_once()
        assert slot.snapshot_id in s._in_flight_slots

        # Second poll while still in-flight should skip
        await s._poll_once()
        # Only one task was created; the second poll skipped the in-flight slot
        await asyncio.sleep(0.1)
        assert len(fake_service.calls) == 1
