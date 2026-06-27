"""Core models for the backend snapshot collector.

These models service the collection and build pipeline only.  They do NOT
import Dragon Board frontend runtime objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class SourceHealth:
    """Health record for a single data-source provider.

    Each provider writes a health snapshot into the ``MarketDataContext``
    so the builder and quality gate can decide whether to proceed, warn,
    or block.
    """

    source: str
    ok: bool
    latency_ms: int = 0
    row_count: int = 0
    error: str = ""
    captured_at: str = ""
    requested_count: int = 0
    returned_count: int = 0
    coverage_ratio: float = 0.0
    started_at: str = ""
    completed_at: str = ""
    failed_batches: list[int] = field(default_factory=list)
    stale: bool = False


@dataclass
class MarketDataContext:
    """Backend-side snapshot build context.

    Holds the raw material collected from providers.  Does NOT import
    Dragon Board frontend runtime objects — this is a Python-native
    dataclass that mirrors the shape the builder needs.
    """

    stocks: list[dict[str, Any]] = field(default_factory=list)
    quotes: list[dict[str, Any]] = field(default_factory=list)
    depth: list[dict[str, Any]] = field(default_factory=list)
    money_flow: list[dict[str, Any]] = field(default_factory=list)
    themes: dict[str, list[str]] = field(default_factory=dict)
    limit_up: dict[str, dict[str, Any]] = field(default_factory=dict)
    sectors: list[dict[str, Any]] = field(default_factory=list)
    source_health: list[SourceHealth] = field(default_factory=list)
    market_meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectorRunRequest:
    """Single-collect request parameters.

    Fields:
    * dataset_id    — target dataset (e.g. ``dragonboard_backend_shadow``)
    * snapshot_type — ``quarter_hour`` | ``half_hour`` | ``hourly`` | ``daily``
    * trading_date  — ``YYYY-MM-DD`` in Asia/Shanghai calendar
    * slot_time     — ``HH:MM`` (24h)
    * dry_run       — when True, go through the full pipeline except the fact write
    * force         — when True, skip dedup check and re-save
    """

    dataset_id: str
    snapshot_type: str
    trading_date: str
    slot_time: str
    dry_run: bool = False
    force: bool = False


@dataclass
class CollectorRunResult:
    """Result of a single ``run_once`` call.

    *status* is one of ``"completed"``, ``"dry_run"``, ``"deduped"``, ``"blocked"``.
    *details* carries extra diagnostic information (quality, run state, etc.).
    """

    status: str
    snapshot_id: str
    deduped: bool = False
    dry_run: bool = False
    quality: QualityResult | None = None
    run_id: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
