"""Slot table, trading-time helpers, and eligibility rules.

Every time is Asia/Shanghai.  The slot table is the single source of truth
for which HH:MM times belong to each snapshot type.
"""

from __future__ import annotations

import datetime
from zoneinfo import ZoneInfo

from .models import SnapshotSlot

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# ── Slot table ───────────────────────────────────────────────────────────────
#
# Matches the design document and the frontend schedule.
#
# quarter_hour: 18 slots  (09:30-11:30 + 13:00-15:00)
# half_hour:    10 slots
# hourly:        5 slots
# daily:         1 slot  (only 15:00)

SLOT_TIMES: dict[str, list[str]] = {
    "quarter_hour": [
        "09:30", "09:45",
        "10:00", "10:15", "10:30", "10:45",
        "11:00", "11:15", "11:30",
        "13:00", "13:15", "13:30", "13:45",
        "14:00", "14:15", "14:30", "14:45",
        "15:00",
    ],
    "half_hour": [
        "09:30",
        "10:00", "10:30",
        "11:00", "11:30",
        "13:00", "13:30",
        "14:00", "14:30",
        "15:00",
    ],
    "hourly": [
        "10:00", "11:00",
        "13:00", "14:00",
        "15:00",
    ],
    "daily": ["15:00"],
}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _make_timestamp_ms(trading_date: str, slot_time: str) -> int:
    """Return the epoch-ms instant of *trading_date* + *slot_time* in TZ_SHANGHAI."""
    dt = datetime.datetime.strptime(
        f"{trading_date} {slot_time}", "%Y-%m-%d %H:%M"
    )
    dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return int(dt.timestamp() * 1000)


# ── Public API ───────────────────────────────────────────────────────────────

def generate_slots(
    trading_date: str,
    snapshot_types: list[str],
    *,
    grace_minutes: int = 5,  # noqa: ARG001 — accepted for scheduler API consistency
) -> list[SnapshotSlot]:
    """Generate every `SnapshotSlot` for *trading_date* and *snapshot_types*.

    Slots are returned sorted by ``timestamp_ms`` ascending.  Unknown
    *snapshot_types* are silently skipped.
    """
    slots: list[SnapshotSlot] = []
    for st in snapshot_types:
        times = SLOT_TIMES.get(st)
        if times is None:
            continue
        for t in times:
            ts = _make_timestamp_ms(trading_date, t)
            slots.append(SnapshotSlot(st, trading_date, t, ts))
    slots.sort(key=lambda s: s.timestamp_ms)
    return slots


def is_slot_eligible(
    now_ts: int,
    slot: SnapshotSlot,
    *,
    grace_minutes: int = 5,
) -> bool:
    """Return `True` when *slot* can be collected at *now_ts*.

    A slot is eligible once the wall clock reaches its scheduled time and
    stays eligible for at most *grace_minutes* afterward.  The grace window
    is particularly important for the close slot (15:00) so the collector
    has time to receive final market data after the session ends.
    """
    grace_ms = grace_minutes * 60 * 1000
    return slot.timestamp_ms <= now_ts <= slot.timestamp_ms + grace_ms
