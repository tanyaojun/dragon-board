"""Core models for the backend snapshot collector.

These models service the collection and build pipeline only.  They do NOT
import Dragon Board frontend runtime objects.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SnapshotSlot:
    """A universal key identifying one collection target.

    Fields align with the MongoDB / API camelCase contract but use Python
    snake_case internally:

    * snapshot_type  — ``quarter_hour`` | ``half_hour`` | ``hourly`` | ``daily``
    * trading_date   — ``YYYY-MM-DD`` in Asia/Shanghai calendar
    * slot_time      — ``HH:MM`` (24h)
    * timestamp_ms   — epoch milliseconds of the slot instant in Asia/Shanghai
    """

    snapshot_type: str
    trading_date: str
    slot_time: str
    timestamp_ms: int

    @property
    def snapshot_id(self) -> str:
        """Canonical snapshot identifier: ``<type>:<date>:<time>``."""
        return f"{self.snapshot_type}:{self.trading_date}:{self.slot_time}"
