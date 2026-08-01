"""Automatic background scheduler for snapshot collection.

Uses a next-slot timer: calculates the upcoming snapshot time, sleeps until
then, and collects all slots that become due at that instant.  Falls back to
idle recheck on non-trading days.

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

# Wake exactly at slot time — no advance (avoids busy-loop when slot isn't eligible yet)
_ADVANCE_SECONDS = 0
# Max idle sleep on a non-trading day before re-checking (seconds)
_IDLE_RECHECK_SECONDS = 1800


class SnapshotCollectorScheduler:
    """Background async runner driven by the next-snapshot-slot timer.

    Instead of polling, the scheduler computes the next due slot, sleeps
    precisely until that moment, then fires a collection.  Multiple types
    that share the same ``HH:MM`` are collected in the same wake-up.
    """

    def __init__(self) -> None:
        settings = get_settings()
        backend_ok = settings.storage_backend == "mongodb"
        self.enabled = backend_ok and settings.snapshot_collector_enabled
        self.dataset_id = settings.snapshot_collector_dataset_id
        self.snapshot_types = [
            t.strip() for t in settings.snapshot_collector_types.split(",") if t.strip()
        ]
        self.grace_minutes = settings.snapshot_collector_close_grace_minutes
        self._task: asyncio.Task[None] | None = None
        self._in_flight_slots: set[str] = set()
        self._last_run_at: str | None = None
        self._last_slot_collected: str | None = None
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._last_error_slot: str | None = None
        self._collection_count: int = 0
        self._error_count: int = 0
        # Tracks collected snapshot_ids for the current trading date so the
        # timer can skip already-persisted slots without a round-trip to Mongo.
        self._completed_today: set[str] = set()
        self._completed_date: str | None = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.enabled or (self._task is not None and not self._task.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, Any]:
        from backend.snapshot_collector.slots import generate_slots
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        now_ts = int(time.time() * 1000)
        trading_date = trading_date_from_ts(now_ts)
        is_trading_day = trading_date is not None
        now_dt = datetime.datetime.fromtimestamp(now_ts / 1000, TZ_SHANGHAI)
        minute = now_dt.hour * 60 + now_dt.minute
        in_session = 570 <= minute < 900  # 09:30-15:00
        upcoming_slot = None
        if is_trading_day and trading_date:
            all_slots = generate_slots(trading_date, self.snapshot_types)
            for slot in all_slots:
                if slot.timestamp_ms > now_ts and slot.snapshot_id not in self._completed_today:
                    upcoming_slot = slot.snapshot_id
                    break

        return {
            "enabled": self.enabled,
            "running": self.running,
            "dataset_id": self.dataset_id,
            "snapshot_types": self.snapshot_types,
            "grace_minutes": self.grace_minutes,
            "is_trading_day": is_trading_day,
            "trading_date": trading_date,
            "in_session": in_session,
            "upcoming_slot": upcoming_slot,
            "last_run_at": self._last_run_at,
            "last_slot_collected": self._last_slot_collected,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
            "last_error_slot": self._last_error_slot,
            "collection_count": self._collection_count,
            "error_count": self._error_count,
            "in_flight_slots": sorted(self._in_flight_slots),
        }

    # ── timer loop ──────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        while True:
            try:
                until_next = self._seconds_until_next_slot()
                await asyncio.sleep(until_next)
                await self._collect_due_slots()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                self._last_error_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
                self._last_error_slot = "scheduler_cycle"
                self._error_count += 1
                logger.exception("snapshot collector scheduler cycle failed")
                await asyncio.sleep(30)

    # ── next-slot calculation ───────────────────────────────────────────────

    def _seconds_until_next_slot(self) -> float:
        """Return seconds to sleep before the next snapshot slot becomes due.

        On a trading day returns the precise interval; on a non-trading day
        sleeps for ``_IDLE_RECHECK_SECONDS``.
        """
        from backend.snapshot_collector.slots import generate_slots
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        now_ts = int(time.time() * 1000)
        trading_date = trading_date_from_ts(now_ts)
        if trading_date is None:
            return float(_IDLE_RECHECK_SECONDS)

        if trading_date != self._completed_date:
            self._completed_date = trading_date
            self._completed_today.clear()

        all_slots = generate_slots(trading_date, self.snapshot_types)

        for slot in all_slots:
            sid = slot.snapshot_id
            if sid in self._in_flight_slots or sid in self._completed_today:
                continue
            # Target the slot's scheduled time (not the end of grace window)
            wait_ms = slot.timestamp_ms - now_ts
            if wait_ms > -_ADVANCE_SECONDS * 1000:
                return max(0.0, wait_ms / 1000.0 - _ADVANCE_SECONDS)

        # All today's slots are either done or expired — re-check later
        return float(_IDLE_RECHECK_SECONDS)

    # ── collection ──────────────────────────────────────────────────────────

    async def _collect_due_slots(self) -> None:
        """Collect every slot whose timestamp has arrived and whose grace
        window has not yet expired.  Multiple types at the same ``HH:MM``
        are collected together.
        """
        from backend.snapshot_collector.slots import generate_slots
        from backend.snapshot_collector.service_factory import create_snapshot_collector_repository
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        now_ts = int(time.time() * 1000)
        trading_date = trading_date_from_ts(now_ts)
        if trading_date is None:
            return

        grace_ms = self.grace_minutes * 60 * 1000
        all_slots = generate_slots(trading_date, self.snapshot_types)
        repo = create_snapshot_collector_repository()

        for slot in all_slots:
            sid = slot.snapshot_id
            # Not yet due
            if now_ts < slot.timestamp_ms:
                continue
            # Expired
            if now_ts > slot.timestamp_ms + grace_ms:
                self._completed_today.add(sid)
                continue
            # Already handled
            if sid in self._in_flight_slots or sid in self._completed_today:
                continue
            # Already persisted
            if repo.snapshot_exists(self.dataset_id, sid):
                self._completed_today.add(sid)
                continue

            self._in_flight_slots.add(sid)
            asyncio.create_task(self._tracked_collect(slot))

    # ── per-slot collection ────────────────────────────────────────────────

    async def _tracked_collect(self, slot: Any) -> None:
        """Collect a single slot and update counters / completed set."""
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service_factory import (
            create_snapshot_collector_repository,
            create_snapshot_collector_service,
        )

        try:
            repo = create_snapshot_collector_repository()
            if repo.snapshot_exists(self.dataset_id, slot.snapshot_id):
                self._completed_today.add(slot.snapshot_id)
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
            result = await asyncio.to_thread(service.run_once, request)
            self._last_run_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
            if result.status == "completed":
                self._collection_count += 1
                self._completed_today.add(slot.snapshot_id)
            elif result.status == "deduped":
                self._completed_today.add(slot.snapshot_id)
            else:
                raise RuntimeError(
                    f"collector slot {slot.snapshot_id} returned {result.status}: "
                    f"{result.message or 'no message'}"
                )
            self._last_slot_collected = slot.snapshot_id
            if self._last_error_slot == slot.snapshot_id:
                self._last_error = None
                self._last_error_at = None
                self._last_error_slot = None
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
