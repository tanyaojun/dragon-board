"""Collector run-state recording module.

Persists run attempts into ``snapshot_collector_runs`` and maintains a
lightweight operational state.  All persistence goes through the
``SnapshotRepository`` protocol — this module does NOT perform direct
MongoDB operations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def record_run(repo: Any, run: dict[str, Any]) -> None:
    """Write a run attempt record through the repository.

    *run* must contain at least ``runId``, ``datasetId``, ``snapshotId``,
    and ``status``.  ``createdAt`` is stamped automatically when absent.
    """
    doc = dict(run)
    doc.setdefault("createdAt", datetime.now(timezone.utc))
    repo.insert_run(doc)


def get_status(repo: Any) -> dict[str, Any]:
    """Return the current collector operational state."""
    return repo.collector_status()
