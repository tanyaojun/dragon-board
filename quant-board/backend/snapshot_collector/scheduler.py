"""Automatic background scheduler for snapshot collection.

Polls on a configured interval, checks for eligible trading-day slots, and
launches fire-and-forget collection tasks per slot.  Follows the same runner
pattern as ``BackupAutoSyncRunner`` (start / stop / _run_loop / status).

The scheduler auto-disables itself when the storage backend is not MongoDB
or when ``snapshot_collector_enabled`` is False.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import time
from typing import Any

from backend.settings import get_settings
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI


logger = logging.getLogger(__name__)


class SnapshotCollectorScheduler:
    """Background async runner that polls for eligible snapshot slots.

    On each poll tick the scheduler:
    1. Derives the current Asia/Shanghai trading date.
    2. Generates all slots for today across every configured snapshot type.
    3. Fires a background ``_collect_slot`` task for each eligible,
       not-already-in-flight slot.

    Deduplication is checked twice: once via the in-memory ``_in_flight_slots``
    set and a second time (belt-and-suspenders) by asking the repository
    inside ``_collect_slot``.
    """

    def __init__(self) -> None:
        settings = get_settings()
        # Auto-disable if not MongoDB backend
        backend_ok = settings.storage_backend == "mongodb"
        self.enabled = backend_ok and settings.snapshot_collector_enabled
        self.dataset_id = settings.snapshot_collector_dataset_id
        self.snapshot_types = [
            t.strip() for t in settings.snapshot_collector_types.split(",") if t.strip()
        ]
        self.poll_seconds = max(0.1, settings.snapshot_collector_poll_ms / 1000.0)
        self.grace_minutes = settings.snapshot_collector_close_grace_minutes
        self._task: asyncio.Task[None] | None = None
        self._in_flight_slots: set[str] = set()
        self._last_run_at: str | None = None
        self._last_poll_at: str | None = None
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._last_error_slot: str | None = None
        self._last_slot_collected: str | None = None
        self._collection_count: int = 0
        self._error_count: int = 0
        self._health_trading_date: str | None = None
        self._checked_overdue_slots: set[str] = set()
        self._overdue_missing_slots: set[str] = set()
        self._last_missing_recheck_ts: int = 0

    # ── lifecycle ──────────────────────────────────────────────────────────

    def _discard_finished_task(self) -> None:
        if self._task is not None and self._task.done():
            self._task = None

    def start(self) -> None:
        """Schedule the background poll loop on the current event loop.

        Safe to call multiple times — no-op when already running or disabled.
        """
        self._discard_finished_task()
        if not self.enabled or self._task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        """Cancel the background poll loop and wait for it to finish."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def status(self) -> dict[str, Any]:
        """Return a snapshot of the scheduler's current state."""
        self._discard_finished_task()
        return {
            "enabled": self.enabled,
            "running": self._task is not None,
            "dataset_id": self.dataset_id,
            "snapshot_types": self.snapshot_types,
            "poll_seconds": self.poll_seconds,
            "grace_minutes": self.grace_minutes,
            "last_poll_at": self._last_poll_at,
            "last_run_at": self._last_run_at,
            "last_slot_collected": self._last_slot_collected,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
            "last_error_slot": self._last_error_slot,
            "collection_count": self._collection_count,
            "error_count": self._error_count,
            "overdue_missing_slots": sorted(self._overdue_missing_slots),
            "in_flight_slots": sorted(self._in_flight_slots),
        }

    # ── loop ───────────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        """Main polling loop — no initial delay (snapshots are time-sensitive)."""
        while True:
            try:
                await self._poll_once()
                if self._last_error_slot == "scheduler_poll":
                    self._last_error = None
                    self._last_error_at = None
                    self._last_error_slot = None
            except Exception as exc:
                self._last_error = str(exc)
                self._last_error_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
                self._last_error_slot = "scheduler_poll"
                self._error_count += 1
                logger.exception("snapshot collector scheduler poll failed")
            await asyncio.sleep(self.poll_seconds)

    async def _poll_once(self) -> None:
        """Scan for eligible slots and launch fire-and-forget collection tasks."""
        from backend.snapshot_collector.slots import generate_slots, is_slot_eligible
        from backend.snapshot_collector.service_factory import create_snapshot_collector_repository
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        now_ts = int(time.time() * 1000)
        self._last_poll_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
        trading_date = trading_date_from_ts(now_ts)
        if trading_date is None:
            return  # Non-trading day

        if trading_date != self._health_trading_date:
            self._health_trading_date = trading_date
            self._checked_overdue_slots.clear()
            self._overdue_missing_slots.clear()
            self._last_missing_recheck_ts = 0

        # Generate ALL slots for today across all configured types
        all_slots = generate_slots(trading_date, self.snapshot_types)
        repo = create_snapshot_collector_repository()

        for slot in all_slots:
            if not is_slot_eligible(now_ts, slot, grace_minutes=self.grace_minutes):
                continue
            if slot.snapshot_id in self._in_flight_slots:
                continue
            if repo.snapshot_exists(self.dataset_id, slot.snapshot_id):
                continue

            # Fire and forget — dedup is double-checked inside _collect_slot.
            self._in_flight_slots.add(slot.snapshot_id)
            asyncio.create_task(self._collect_slot(slot))

        grace_ms = self.grace_minutes * 60 * 1000
        recheck_missing = now_ts - self._last_missing_recheck_ts >= 30_000
        checked_overdue = False
        for slot in all_slots:
            if now_ts <= slot.timestamp_ms + grace_ms:
                continue
            if slot.snapshot_id in self._in_flight_slots:
                continue
            if slot.snapshot_id in self._checked_overdue_slots:
                if slot.snapshot_id not in self._overdue_missing_slots or not recheck_missing:
                    continue

            exists = repo.snapshot_exists(self.dataset_id, slot.snapshot_id)
            checked_overdue = True
            self._checked_overdue_slots.add(slot.snapshot_id)
            if exists:
                self._overdue_missing_slots.discard(slot.snapshot_id)
                if self._last_error_slot == slot.snapshot_id:
                    self._last_error = None
                    self._last_error_at = None
                    self._last_error_slot = None
                continue
            if slot.snapshot_id not in self._overdue_missing_slots:
                logger.error("snapshot collector overdue slot missing: %s", slot.snapshot_id)
            self._overdue_missing_slots.add(slot.snapshot_id)
        if checked_overdue:
            self._last_missing_recheck_ts = now_ts

    # ── per-slot collection ────────────────────────────────────────────────

    async def _collect_slot(self, slot: Any) -> None:
        """Collect a single snapshot slot and update scheduler counters.

        Creates its own repository and service so connections are scoped
        to this one operation.  Offloads blocking MongoDB I/O to a thread
        via ``asyncio.to_thread``.
        """
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service_factory import (
            create_snapshot_collector_repository,
            create_snapshot_collector_service,
        )

        try:
            repo = create_snapshot_collector_repository()
            # Belt-and-suspenders dedup: skip if already persisted
            if repo.snapshot_exists(self.dataset_id, slot.snapshot_id):
                return

            service = create_snapshot_collector_service(repo)
            request = CollectorRunRequest(
                dataset_id=self.dataset_id,
                snapshot_type=slot.snapshot_type,
                trading_date=slot.trading_date,
                slot_time=slot.slot_time,
                dry_run=False,
                force=False,
            )
            # Offload blocking MongoDB I/O to a thread
            result = await asyncio.to_thread(service.run_once, request)
            self._last_run_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
            if result.status == "completed":
                self._collection_count += 1
            elif result.status != "deduped":
                raise RuntimeError(
                    f"collector slot {slot.snapshot_id} returned {result.status}: {result.message or 'no message'}"
                )
            self._last_slot_collected = slot.snapshot_id
            if self._last_error_slot == slot.snapshot_id:
                self._last_error = None
                self._last_error_at = None
                self._last_error_slot = None
            self._checked_overdue_slots.add(slot.snapshot_id)
            self._overdue_missing_slots.discard(slot.snapshot_id)
        except Exception as exc:
            self._last_error = str(exc)
            self._last_error_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
            self._last_error_slot = slot.snapshot_id
            self._error_count += 1
            logger.exception("snapshot collector slot failed: %s", slot.snapshot_id)
        finally:
            self._in_flight_slots.discard(slot.snapshot_id)


# Module-level singleton — start/stop via the FastAPI lifespan or CLI.
snapshot_collector_scheduler = SnapshotCollectorScheduler()
