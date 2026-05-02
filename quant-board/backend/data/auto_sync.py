from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from backend.data.backup_sync import BackupSyncService
from backend.data.database import SessionLocal
from backend.data.repository import Repository
from backend.settings import get_settings


class BackupAutoSyncRunner:
    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = bool(settings.backup_auto_sync_enabled)
        self.interval_seconds = settings.backup_auto_sync_interval_seconds
        self.initial_delay_seconds = settings.backup_auto_sync_initial_delay_seconds
        self.batch_size = settings.backup_auto_sync_batch_size
        self._task: asyncio.Task[None] | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if not self.enabled or self._task is not None:
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

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self._task is not None and not self._task.done(),
            "interval_seconds": self.interval_seconds,
            "initial_delay_seconds": self.initial_delay_seconds,
            "batch_size": self.batch_size,
            "last_result": self._last_result,
            "last_error": self._last_error,
        }

    async def _run_loop(self) -> None:
        if self.initial_delay_seconds > 0:
            await asyncio.sleep(self.initial_delay_seconds)
        while True:
            try:
                self._last_result = await asyncio.to_thread(run_outbox_auto_sync_once, self.batch_size)
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
            await asyncio.sleep(self.interval_seconds)


def run_outbox_auto_sync_once(limit: int | None = None) -> dict[str, Any]:
    limit = max(1, int(limit or get_settings().backup_auto_sync_batch_size))
    with SessionLocal() as session:
        repo = Repository(session, enable_backup=False)
        return BackupSyncService(session).push_outbox_to_backup(repo, limit=limit)


auto_sync_runner = BackupAutoSyncRunner()
