from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.data import repository_factory
from backend.data.archive.auto_archive import run_archive_auto_once
from backend.data.archive.service import ArchiveService
from backend.data.backup_retention import run_backup_retention_once
from backend.data.database import SessionLocal, init_db
from backend.operations.hotlist_sentiment import run_hotlist_sentiment_for_latest_day
from backend.settings import get_settings


def run_after_market_once(
    *,
    archive_limit: int | None = None,
    backup_limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc).isoformat()
    results: dict[str, Any] = {}
    steps = ["dailySnapshotBackup", "archive", "pushArchiveBackup", "pruneBackup"]

    settings = get_settings()
    if settings.storage_backend == "mongodb":
        snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
        try:
            hotlist_result = run_hotlist_sentiment_for_latest_day(
                repository_factory.get_runtime_mongodb_database(),
                dataset_id=settings.archive_auto_dataset_id,
                snapshot_type=snapshot_type,
                dry_run=dry_run,
            )
        except Exception as exc:
            hotlist_result = {
                "ok": False,
                "error": {
                    "code": "hotlist_sentiment_after_market_failed",
                    "message": str(exc),
                },
                "datasetId": settings.archive_auto_dataset_id,
                "snapshotType": snapshot_type,
            }
        return _result(
            ok=bool(hotlist_result.get("ok")),
            started_at=started_at,
            steps=["hotlistSentiment"],
            results={"hotlistSentiment": hotlist_result},
            archive_limit=archive_limit,
            backup_limit=backup_limit,
            dry_run=dry_run,
            stopped_at=None if hotlist_result.get("ok") else "hotlistSentiment",
        )
    snapshot_type = _first_snapshot_type(settings.archive_auto_snapshot_types)
    init_db()
    with SessionLocal() as session:
        service = ArchiveService(session)
        trading_date = service.latest_snapshot_trading_date(
            dataset_id=settings.archive_auto_dataset_id,
            snapshot_type=snapshot_type,
        )
        if trading_date:
            daily_result = service.backup_snapshot_day_to_object(
                dataset_id=settings.archive_auto_dataset_id,
                snapshot_type=snapshot_type,
                trading_date=trading_date,
                dry_run=dry_run,
            )
        else:
            daily_result = {
                "ok": True,
                "skipped": True,
                "reason": "no_snapshot_trading_date",
                "datasetId": settings.archive_auto_dataset_id,
                "snapshotType": snapshot_type,
            }
    results["dailySnapshotBackup"] = daily_result

    archive_result = run_archive_auto_once(archive_limit, dry_run=dry_run)
    results["archive"] = archive_result
    if not archive_result.get("ok"):
        return _result(
            ok=False,
            started_at=started_at,
            steps=steps,
            results=results,
            archive_limit=archive_limit,
            backup_limit=backup_limit,
            dry_run=dry_run,
            stopped_at="archive",
        )

    if dry_run:
        results["pushArchiveBackup"] = {
            "ok": True,
            "skipped": True,
            "reason": "dry_run",
        }
    else:
        init_db()
        with SessionLocal() as session:
            push_result = ArchiveService(session).push_archive_backup(limit=backup_limit)
        results["pushArchiveBackup"] = push_result
        if not push_result.get("ok"):
            return _result(
                ok=False,
                started_at=started_at,
                steps=steps,
                results=results,
                archive_limit=archive_limit,
                backup_limit=backup_limit,
                dry_run=dry_run,
                stopped_at="pushArchiveBackup",
            )

    prune_result = run_backup_retention_once(dry_run=dry_run)
    results["pruneBackup"] = prune_result
    if not prune_result.get("ok"):
        return _result(
            ok=False,
            started_at=started_at,
            steps=steps,
            results=results,
            archive_limit=archive_limit,
            backup_limit=backup_limit,
            dry_run=dry_run,
            stopped_at="pruneBackup",
        )

    return _result(
        ok=True,
        started_at=started_at,
        steps=steps,
        results=results,
        archive_limit=archive_limit,
        backup_limit=backup_limit,
        dry_run=dry_run,
    )


def _result(
    *,
    ok: bool,
    started_at: str,
    steps: list[str],
    results: dict[str, Any],
    archive_limit: int | None,
    backup_limit: int | None,
    dry_run: bool,
    stopped_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": ok,
        "dryRun": dry_run,
        "startedAt": started_at,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "archiveLimit": archive_limit,
        "backupLimit": backup_limit,
        "steps": steps,
        "results": results,
    }
    if stopped_at:
        payload["stoppedAt"] = stopped_at
    return payload


def _first_snapshot_type(raw: str) -> str:
    items = [item.strip() for item in (raw or "").split(",") if item.strip()]
    return items[0] if items else "half_hour"
