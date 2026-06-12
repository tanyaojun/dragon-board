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

    _VALID_TYPES: frozenset[str] = frozenset({"quarter_hour", "half_hour", "hourly", "daily"})

    def __post_init__(self) -> None:
        if self.snapshot_type not in self._VALID_TYPES:
            raise ValueError(
                f"Unknown snapshot_type={self.snapshot_type!r}, "
                f"expected one of {sorted(self._VALID_TYPES)}"
            )

    @property
    def snapshot_id(self) -> str:
        """Canonical snapshot identifier: ``<type>:<date>:<time>``."""
        return f"{self.snapshot_type}:{self.trading_date}:{self.slot_time}"


@dataclass(frozen=True)
class QualityResult:
    """Structured quality gate outcome.

    *ok* is ``True`` when no hard blockers were found.  Warnings do NOT
    flip *ok* to ``False`` — they are informational only.

    *source_counts* maps ``"ok"`` and ``"failed"`` to integer tallies
    derived from the ``source_health`` list.
    """

    ok: bool
    blocking_issues: list[str]
    warnings: list[str]
    source_counts: dict[str, int]
