"""Tests for snapshot_collector slots module — Task 2: Slot Model and Time Rules."""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.snapshot_collector.models import SnapshotSlot
from backend.snapshot_collector.slots import (
    SLOT_TIMES,
    generate_slots,
    is_slot_eligible,
)

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _make_ts(date_str: str, time_str: str) -> int:
    """Convert a date and time in Asia/Shanghai to epoch milliseconds."""
    dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return int(dt.timestamp() * 1000)


# ── SLOT_TIMES constant ──────────────────────────────────────────────────────

class TestSlotTimes:
    """Verify the slot table matches the design document."""

    def test_half_hour_includes_1500(self):
        """half_hour slots must include 15:00."""
        assert "15:00" in SLOT_TIMES["half_hour"]

    def test_daily_slot_is_exactly_1500(self):
        """daily slot is exactly 15:00."""
        assert SLOT_TIMES["daily"] == ["15:00"]

    def test_quarter_hour_has_18_slots(self):
        """quarter_hour has 18 slots (09:30-11:30 + 13:00-15:00)."""
        assert len(SLOT_TIMES["quarter_hour"]) == 18

    def test_half_hour_has_10_slots(self):
        assert len(SLOT_TIMES["half_hour"]) == 10

    def test_hourly_has_5_slots(self):
        assert len(SLOT_TIMES["hourly"]) == 5

    def test_daily_has_1_slot(self):
        assert len(SLOT_TIMES["daily"]) == 1

    def test_quarter_hour_starts_at_0930(self):
        assert SLOT_TIMES["quarter_hour"][0] == "09:30"

    def test_quarter_hour_ends_at_1500(self):
        assert SLOT_TIMES["quarter_hour"][-1] == "15:00"

    def test_no_lunch_break_slots(self):
        """Verify no slots fall in the lunch break period 11:31-12:59."""
        for st_name, times in SLOT_TIMES.items():
            for t in times:
                assert not ("12:" in t and t != "12:00"), (
                    f"{st_name} has unexpected slot {t}"
                )


# ── SnapshotSlot model ────────────────────────────────────────────────────────

class TestSnapshotSlot:
    """Verify the frozen SnapshotSlot dataclass."""

    def test_snapshot_id_format_half_hour(self):
        """2026-06-11 15:00 Asia/Shanghai produces half_hour:2026-06-11:15:00."""
        ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot(
            snapshot_type="half_hour",
            trading_date="2026-06-11",
            slot_time="15:00",
            timestamp_ms=ts,
        )
        assert slot.snapshot_id == "half_hour:2026-06-11:15:00"

    def test_snapshot_id_format_quarter_hour(self):
        ts = _make_ts("2026-06-11", "09:45")
        slot = SnapshotSlot(
            snapshot_type="quarter_hour",
            trading_date="2026-06-11",
            slot_time="09:45",
            timestamp_ms=ts,
        )
        assert slot.snapshot_id == "quarter_hour:2026-06-11:09:45"

    def test_snapshot_id_format_daily(self):
        ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot(
            snapshot_type="daily",
            trading_date="2026-06-11",
            slot_time="15:00",
            timestamp_ms=ts,
        )
        assert slot.snapshot_id == "daily:2026-06-11:15:00"

    def test_frozen_dataclass_prevents_mutation(self):
        """SnapshotSlot is frozen — attribute assignment must raise."""
        ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot("half_hour", "2026-06-11", "15:00", ts)
        with pytest.raises(Exception):
            slot.snapshot_type = "daily"  # type: ignore[misc]

    def test_timestamp_ms_is_milliseconds_range(self):
        """timestamp_ms should be in epoch-ms range (> 1e12 for 2026)."""
        ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot("half_hour", "2026-06-11", "15:00", ts)
        assert slot.timestamp_ms > 1_000_000_000_000

    def test_invalid_snapshot_type_raises_valueerror(self):
        """Constructing a SnapshotSlot with an unknown type must raise."""
        ts = _make_ts("2026-06-11", "15:00")
        with pytest.raises(ValueError, match="Unknown snapshot_type"):
            SnapshotSlot("five_minute", "2026-06-11", "15:00", ts)

    def test_equality_by_value(self):
        """Two slots with same fields should be equal."""
        ts = _make_ts("2026-06-11", "15:00")
        a = SnapshotSlot("half_hour", "2026-06-11", "15:00", ts)
        b = SnapshotSlot("half_hour", "2026-06-11", "15:00", ts)
        assert a == b
        assert hash(a) == hash(b)


# ── generate_slots ────────────────────────────────────────────────────────────

class TestGenerateSlots:
    """Verify generate_slots produces correct slot lists."""

    def test_generates_half_hour_slots(self):
        slots = generate_slots("2026-06-11", ["half_hour"])
        assert len(slots) == 10
        slot_times = [s.slot_time for s in slots]
        assert "15:00" in slot_times
        assert "09:30" in slot_times

    def test_generates_daily_slot(self):
        slots = generate_slots("2026-06-11", ["daily"])
        assert len(slots) == 1
        assert slots[0].slot_time == "15:00"
        assert slots[0].snapshot_type == "daily"
        assert slots[0].trading_date == "2026-06-11"

    def test_generates_quarter_hour_slots(self):
        slots = generate_slots("2026-06-11", ["quarter_hour"])
        assert len(slots) == 18

    def test_generates_multiple_types(self):
        slots = generate_slots("2026-06-11", ["half_hour", "daily"])
        # 10 half_hour + 1 daily = 11
        assert len(slots) == 11
        types = {s.snapshot_type for s in slots}
        assert types == {"half_hour", "daily"}

    def test_all_have_correct_trading_date(self):
        slots = generate_slots("2026-06-11", ["half_hour", "daily"])
        for slot in slots:
            assert slot.trading_date == "2026-06-11"

    def test_timestamp_ms_matches_expected(self):
        slots = generate_slots("2026-06-11", ["daily"])
        expected_ts = _make_ts("2026-06-11", "15:00")
        assert slots[0].timestamp_ms == expected_ts

    def test_slots_are_sorted_by_time(self):
        for st_name in SLOT_TIMES:
            slots = generate_slots("2026-06-11", [st_name])
            for i in range(len(slots) - 1):
                assert slots[i].timestamp_ms <= slots[i + 1].timestamp_ms, (
                    f"{st_name} slots not sorted: {slots[i].slot_time} > {slots[i+1].slot_time}"
                )

    def test_each_slot_has_unique_snapshot_id(self):
        slots = generate_slots("2026-06-11", ["half_hour", "daily"])
        ids = [s.snapshot_id for s in slots]
        assert len(ids) == len(set(ids))

    def test_grace_minutes_accepted_but_does_not_affect_generation(self):
        """grace_minutes is a scheduler concern; generate_slots accepts it."""
        slots_default = generate_slots("2026-06-11", ["half_hour"])
        slots_custom = generate_slots("2026-06-11", ["half_hour"], grace_minutes=10)
        assert len(slots_default) == len(slots_custom)
        for a, b in zip(slots_default, slots_custom):
            assert a.snapshot_id == b.snapshot_id


# ── is_slot_eligible ──────────────────────────────────────────────────────────

class TestIsSlotEligible:
    """Verify slot eligibility based on time and grace window."""

    def test_slot_at_exact_time_is_eligible(self):
        slot_ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot("half_hour", "2026-06-11", "15:00", slot_ts)
        assert is_slot_eligible(slot_ts, slot, grace_minutes=5) is True

    def test_before_slot_time_is_not_eligible(self):
        slot_ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot("half_hour", "2026-06-11", "15:00", slot_ts)
        before_ts = slot_ts - 60_000  # 1 minute before
        assert is_slot_eligible(before_ts, slot, grace_minutes=5) is False

    def test_inside_grace_window_is_eligible(self):
        """A slot should be eligible within grace_minutes after its time."""
        slot_ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot("half_hour", "2026-06-11", "15:00", slot_ts)
        after_ts = slot_ts + 4 * 60_000  # 4 minutes after
        assert is_slot_eligible(after_ts, slot, grace_minutes=5) is True

    def test_outside_grace_window_is_not_eligible(self):
        slot_ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot("half_hour", "2026-06-11", "15:00", slot_ts)
        after_ts = slot_ts + 6 * 60_000  # 6 minutes after
        assert is_slot_eligible(after_ts, slot, grace_minutes=5) is False

    def test_1500_remains_eligible_inside_close_grace_window(self):
        """Acceptance test: 15:00 is eligible even minutes after close."""
        slot_ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot("half_hour", "2026-06-11", "15:00", slot_ts)
        at_boundary = slot_ts + 5 * 60_000  # exactly at grace boundary
        assert is_slot_eligible(at_boundary, slot, grace_minutes=5) is True

    def test_different_grace_minutes_are_respected(self):
        slot_ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot("half_hour", "2026-06-11", "15:00", slot_ts)
        after_ts = slot_ts + 3 * 60_000  # 3 minutes after
        assert is_slot_eligible(after_ts, slot, grace_minutes=2) is False
        assert is_slot_eligible(after_ts, slot, grace_minutes=5) is True

    def test_default_grace_minutes_is_5(self):
        slot_ts = _make_ts("2026-06-11", "15:00")
        slot = SnapshotSlot("half_hour", "2026-06-11", "15:00", slot_ts)
        after_ts = slot_ts + 4 * 60_000
        assert is_slot_eligible(after_ts, slot) is True  # default grace_minutes=5

    def test_non_close_slot_also_respects_grace(self):
        """The grace window applies to all slots, not just 15:00."""
        slot_ts = _make_ts("2026-06-11", "09:30")
        slot = SnapshotSlot("half_hour", "2026-06-11", "09:30", slot_ts)
        assert is_slot_eligible(slot_ts, slot) is True
        assert is_slot_eligible(slot_ts - 1, slot) is False
        assert is_slot_eligible(slot_ts + 10 * 60_000, slot) is False  # 10 min after
