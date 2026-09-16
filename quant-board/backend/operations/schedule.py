from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from backend.data.repositories import repository_factory
from backend.data.archive.auto_archive import run_archive_auto_once
from backend.data.archive.service import ArchiveService
from backend.data.backup.backup_retention import run_backup_retention_once
from backend.data.backup.mongodb_backup import get_mongodb_backup_service
from backend.data.models.database import SessionLocal, init_db
from backend.operations.hotlist_sentiment import run_hotlist_sentiment_for_latest_day
from backend.core.settings import get_settings
from backend.snapshot_collector.trading_calendar import is_trading_day

_TZ = ZoneInfo("Asia/Shanghai")


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
        # 备份链独立于 hotlistSentiment 结果：hotlist 失败也继续备份（快照数据可能已入库）
        backup_result = run_mongodb_backup_once(dry_run=dry_run)
        hotlist_ok = bool(hotlist_result.get("ok"))
        backup_ok = bool(backup_result.get("ok"))
        stopped_at = None
        if not hotlist_ok:
            stopped_at = "hotlistSentiment"
        elif not backup_ok:
            stopped_at = "mongodbBackup"
        return _result(
            ok=hotlist_ok and backup_ok,
            started_at=started_at,
            steps=["hotlistSentiment", "mongodbBackup"],
            results={"hotlistSentiment": hotlist_result, "mongodbBackup": backup_result},
            archive_limit=archive_limit,
            backup_limit=backup_limit,
            dry_run=dry_run,
            stopped_at=stopped_at,
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


def run_mongodb_backup_once(*, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    """盘后 MongoDB 备份链：创建（交易日 light / 周五 full）→ verify → prune →（周五）push R2。

    独立于 hotlistSentiment：任一步失败结构化记录并使整体失败（非零退出可见），
    但不回滚其它步骤已完成的事实。
    """
    now = now or datetime.now(_TZ)
    is_friday = now.weekday() == 4
    summary: dict[str, Any] = {"ok": True, "friday": is_friday, "tradingDate": now.date().isoformat()}
    if dry_run:
        return {**summary, "skipped": True, "reason": "dry_run"}
    if not is_trading_day(now.date()):
        return {**summary, "skipped": True, "reason": "non_trading_day"}

    service = get_mongodb_backup_service()
    strategy = "full_dump" if is_friday else "light_dump"
    summary["strategy"] = strategy
    try:
        created = service.create_full_backup() if is_friday else service.create_light_backup()
    except Exception as exc:
        return {**summary, "ok": False, "failedStep": "create", "error": {"code": "backup_create_exception", "message": str(exc)}}
    if not created.get("ok"):
        return {**summary, "ok": False, "failedStep": "create", "error": created.get("error")}
    backup_id = created["backupId"]
    summary["backupId"] = backup_id

    verify = service.verify_backup(backup_id)
    if not verify.get("ok"):
        return {**summary, "ok": False, "failedStep": "verify", "error": verify.get("error")}

    prune = service.prune_local_backups(dry_run=False)
    summary["pruneDeleted"] = len(prune.get("deleted") or [])
    if not prune.get("ok"):
        return {**summary, "ok": False, "failedStep": "prune", "error": prune.get("error")}

    if is_friday:
        try:
            pushed = service.push_backup(backup_id)
        except Exception as exc:
            pushed = {"ok": False, "error": {"code": "backup_push_exception", "message": str(exc)}}
        summary["push"] = {
            "ok": bool(pushed.get("ok")),
            "fileCount": len(pushed.get("files") or []),
            **({} if pushed.get("ok") else {"error": pushed.get("error")}),
        }
        if not pushed.get("ok"):
            return {**summary, "ok": False, "failedStep": "push"}
    return summary


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