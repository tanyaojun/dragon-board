"""Repository port for the snapshot collector.

Defines the ``SnapshotRepository`` protocol that real (MongoDB) and fake
(in-memory) implementations must satisfy.  The collector service and its
callers (API, CLI) depend on this protocol rather than concrete classes.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SnapshotRepository(Protocol):
    """Abstract repository for snapshot collector persistence.

    Declares the read/write methods that the collector service needs.
    Real implementations delegate to MongoDB (via ``MongoRepository`` and
    new operational collections ``snapshot_collector_runs`` /
    ``snapshot_collector_state``).  Fake implementations keep everything
    in memory for testing.
    """

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
        """Return `True` when *snapshot_id* already exists in *dataset_id*."""
        ...

    def save_snapshot_ingest(
        self,
        dataset: dict[str, Any],
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """Persist snapshot data and return status dict with ``status`` and ``deduped``."""
        ...

    def insert_run(self, run: dict[str, Any]) -> None:
        """Write a collector run record to the operational log."""
        ...

    def list_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
        """Return ``{"items": [...], "total": N}`` for runs matching *filters*."""
        ...

    def collector_status(self) -> dict[str, Any]:
        """Return the current collector state dict."""
        ...

    def audit_dataset(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str | None = None,
    ) -> dict[str, Any]:
        """Audit snapshot coverage and return structured summary."""
        ...
