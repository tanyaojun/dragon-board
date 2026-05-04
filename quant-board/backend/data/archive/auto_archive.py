from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import Any

from backend.data.database import SessionLocal
from backend.settings import get_settings


class ArchiveAutoRunner:
    def __init__(
        self,
        *,
        enabled: bool | None = None,
        archive_dir: Path | None = None,
        interval_seconds: float | None = None,
        initial_delay_seconds: float | None = None,
        max_partitions: int | None = None,
    ) -> None:
        settings = get_settings()
        self.enabled = settings.archive_auto_enabled if enabled is None else bool(enabled)
        self.archive_dir = archive_dir or settings.archive_dir
        self.interval_seconds = interval_seconds or settings.archive_auto_interval_seconds
        self.initial_delay_seconds = initial_delay_seconds or settings.archive_auto_initial_delay_seconds
        self.max_partitions = max_partitions or settings.archive_auto_max_partitions
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
            "max_partitions": self.max_partitions,
            "last_result": self._last_result,
            "last_error": self._last_error,
        }

    async def _run_loop(self) -> None:
        if self.initial_delay_seconds > 0:
            await asyncio.sleep(self.initial_delay_seconds)
        while True:
            try:
                self._last_result = await asyncio.to_thread(run_archive_auto_once, self.max_partitions)
                self._last_error = None
            except Exception as exc:
                self._last_error = str(exc)
            await asyncio.sleep(self.interval_seconds)


def run_archive_auto_once(limit: int | None = None) -> dict[str, Any]:
    from backend.data.archive.service import ArchiveService
    from backend.data.database import ResearchSessionLocal

    settings = get_settings()
    snapshot_types = [item.strip() for item in settings.archive_auto_snapshot_types.split(",") if item.strip()]
    results = []
    with SessionLocal() as session:
        service = ArchiveService(session)
        cutoff = service.retention_cutoff_trading_date(
            dataset_id=settings.archive_auto_dataset_id,
            snapshot_types=snapshot_types,
            keep_trading_days=settings.archive_retention_trading_days,
        )
        if not cutoff:
            return {"ok": True, "skipped": True, "reason": "not_enough_history"}
        for snapshot_type in snapshot_types[: max(1, int(limit or settings.archive_auto_max_partitions))]:
            preview = service.archive_snapshots(
                dataset_id=settings.archive_auto_dataset_id,
                snapshot_type=snapshot_type,
                before_trading_date=cutoff,
                dry_run=True,
                max_partitions=limit,
            )
            if preview.get("rowCounts", {}).get("stockRows", 0) or preview.get("rowCounts", {}).get("sectorRows", 0):
                results.append(
                    service.archive_snapshots(
                        dataset_id=settings.archive_auto_dataset_id,
                        snapshot_type=snapshot_type,
                        before_trading_date=cutoff,
                        apply=True,
                        max_partitions=limit,
                    )
                )
        if settings.archive_auto_research_enabled:
            with ResearchSessionLocal() as research_session:
                research_service = ArchiveService(session, research_session=research_session)
                research_result = research_service.archive_research(
                    older_than_days=settings.archive_retention_trading_days,
                    keep_latest_per_group=10,
                    dry_run=False,
                    apply=True,
                )
                results.append(research_result)
    return {"ok": all(item.get("ok") for item in results), "results": results, "cutoff": cutoff}


archive_auto_runner = ArchiveAutoRunner()
