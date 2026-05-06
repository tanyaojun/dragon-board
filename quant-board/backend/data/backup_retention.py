from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.data.supabase_backup import SupabaseBackupClient, get_backup_client
from backend.settings import get_settings


EMPTY_DELETED_ROWS = {
    "records": 0,
    "frames": 0,
    "stockRows": 0,
    "sectorRows": 0,
    "outbox": 0,
}


class BackupRetentionService:
    def __init__(self, backup_client: SupabaseBackupClient | None = None) -> None:
        self.backup = backup_client if backup_client is not None else get_backup_client()

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "enabled": settings.supabase_retention_enabled,
            "keepTradingDays": settings.supabase_retention_keep_trading_days,
            "datasetIds": _split_dataset_ids(settings.supabase_retention_dataset_ids),
            "interval_seconds": settings.supabase_retention_interval_seconds,
            "initial_delay_seconds": settings.supabase_retention_initial_delay_seconds,
        }

    def prune(
        self,
        *,
        dataset_ids: list[str] | None = None,
        keep_trading_days: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        settings = get_settings()
        if not self.backup:
            return {
                "ok": False,
                "dryRun": dry_run,
                "error": {"code": "supabase_backup_not_configured"},
                "datasetIds": dataset_ids or [],
                "results": [],
                "errors": [{"code": "supabase_backup_not_configured"}],
            }
        keep_days = max(1, int(keep_trading_days or settings.supabase_retention_keep_trading_days))
        target_ids = dataset_ids or _split_dataset_ids(settings.supabase_retention_dataset_ids)
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for dataset_id in target_ids:
            result = self._prune_dataset(dataset_id, keep_days, dry_run=dry_run)
            results.append(result)
            if not result.get("ok"):
                errors.append(result.get("error") or {"code": "backup_prune_failed", "datasetId": dataset_id})
        return {
            "ok": not errors,
            "dryRun": dry_run,
            "datasetIds": target_ids,
            "keepTradingDays": keep_days,
            "results": results,
            "errors": errors,
        }

    def _prune_dataset(self, dataset_id: str, keep_trading_days: int, *, dry_run: bool) -> dict[str, Any]:
        dates = sorted(set(self.backup.list_snapshot_trading_dates(dataset_id)))
        if len(dates) <= keep_trading_days:
            return {
                "ok": True,
                "datasetId": dataset_id,
                "skipped": True,
                "reason": "not_enough_history",
                "tradingDayCount": len(dates),
                "keepTradingDays": keep_trading_days,
                "keptTradingDays": dates,
                "cutoffTradingDate": None,
                "deletedRows": dict(EMPTY_DELETED_ROWS),
            }
        kept = dates[-keep_trading_days:]
        cutoff = kept[0]
        deleted = self.backup.prune_snapshot_facts_before(dataset_id, cutoff, dry_run=dry_run)
        if not deleted.get("ok"):
            return {
                "ok": False,
                "datasetId": dataset_id,
                "cutoffTradingDate": cutoff,
                "keptTradingDays": kept,
                "error": deleted.get("error") or {"code": "backup_prune_failed"},
                "deletedRows": dict(EMPTY_DELETED_ROWS),
            }
        summary = {"ok": True}
        if not dry_run:
            summary = self.backup.refresh_dataset_summary(dataset_id)
        if not summary.get("ok"):
            return {
                "ok": False,
                "datasetId": dataset_id,
                "cutoffTradingDate": cutoff,
                "keptTradingDays": kept,
                "deletedRows": deleted.get("deletedRows") or dict(EMPTY_DELETED_ROWS),
                "error": summary.get("error") or {"code": "backup_dataset_summary_refresh_failed"},
            }
        return {
            "ok": True,
            "datasetId": dataset_id,
            "dryRun": dry_run,
            "tradingDayCount": len(dates),
            "keepTradingDays": keep_trading_days,
            "cutoffTradingDate": cutoff,
            "keptTradingDays": kept,
            "deletedRows": deleted.get("deletedRows") or dict(EMPTY_DELETED_ROWS),
            "summary": summary,
        }


class BackupRetentionRunner:
    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.supabase_retention_enabled
        self.interval_seconds = settings.supabase_retention_interval_seconds
        self.initial_delay_seconds = settings.supabase_retention_initial_delay_seconds
        self._task: Any | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._last_started_at: str | None = None
        self._last_finished_at: str | None = None

    def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop())

    async def stop(self) -> None:
        import asyncio
        import contextlib

        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def status(self) -> dict[str, Any]:
        return {
            **BackupRetentionService().status(),
            "running": self._task is not None and not self._task.done(),
            "last_result": self._last_result,
            "last_error": self._last_error,
            "last_started_at": self._last_started_at,
            "last_finished_at": self._last_finished_at,
        }

    async def _run_loop(self) -> None:
        import asyncio

        if self.initial_delay_seconds > 0:
            await asyncio.sleep(self.initial_delay_seconds)
        while True:
            try:
                self._last_started_at = datetime.now(timezone.utc).isoformat()
                self._last_result = await asyncio.to_thread(run_backup_retention_once)
                self._last_error = None if self._last_result.get("ok") else str(self._last_result.get("errors") or self._last_result)
            except Exception as exc:
                self._last_error = str(exc)
            finally:
                self._last_finished_at = datetime.now(timezone.utc).isoformat()
            await asyncio.sleep(self.interval_seconds)


def run_backup_retention_once(*, dry_run: bool = False) -> dict[str, Any]:
    return BackupRetentionService().prune(dry_run=dry_run)


def _split_dataset_ids(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()] or ["dragonboard_live"]


backup_retention_runner = BackupRetentionRunner()
