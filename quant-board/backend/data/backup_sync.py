from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.data.models import Dataset, SnapshotFrameModel
from backend.data.repository import Repository
from backend.data.supabase_backup import SupabaseBackupClient, get_backup_client
from backend.settings import get_settings
from backend.utils import json_dumps


class _RetentionPolicy:
    def __init__(self, *, enabled: bool, dataset_ids: list[str], keep_trading_days: int) -> None:
        self.enabled = enabled
        self.dataset_ids = dataset_ids
        self.keep_trading_days = keep_trading_days


class BackupSyncService:
    def __init__(self, session: Session | None, backup_client: SupabaseBackupClient | None = None) -> None:
        self.session = session
        self.backup = backup_client if backup_client is not None else get_backup_client()

    def status(self) -> dict[str, Any]:
        if not self.backup:
            return {"configured": False, "connected": False, "last_error": None}
        return self.backup.health()

    def push_all_to_backup(self, *, full_history: bool = False) -> dict[str, Any]:
        if not self.session:
            return {"ok": False, "direction": "push", "error": "primary database is unavailable"}
        if not self.backup:
            return {"ok": False, "direction": "push", "error": "supabase backup is not configured"}

        repo = Repository(self.session, self.backup, enable_backup=False)
        settings = get_settings()
        retention_policy = _RetentionPolicy(
            enabled=not full_history,
            dataset_ids=_split_dataset_ids(settings.supabase_retention_dataset_ids),
            keep_trading_days=settings.supabase_retention_keep_trading_days,
        )
        result: dict[str, Any] = {
            "ok": True,
            "direction": "push",
            "retention": {
                "enabled": retention_policy.enabled,
                "fullHistory": full_history,
                "keepTradingDays": retention_policy.keep_trading_days,
                "datasetIds": retention_policy.dataset_ids,
            },
            "outbox": {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0, "items": []},
            "datasets": {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0},
            "snapshotBundles": {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0},
            "research": {"policy": "local_research_db_only"},
            "errors": [],
        }
        try:
            result["outbox"] = self.push_outbox_to_backup(repo, retention_policy=retention_policy)
            for dataset in self.session.scalars(select(Dataset).order_by(Dataset.created_at.asc())):
                result["datasets"]["scanned"] += 1
                start_date = self._retention_start_date(dataset.id, retention_policy)
                if retention_policy.enabled and not self._is_retention_dataset(dataset.id, retention_policy):
                    result["datasets"]["skipped"] += 1
                    continue
                bundle = repo.dump_dataset_bundle(dataset.id, start_date=start_date)
                if not bundle:
                    result["datasets"]["skipped"] += 1
                    continue
                saved_dataset, records, frames, stock_rows, sector_rows = bundle
                result["snapshotBundles"]["scanned"] += len(frames)
                if self.backup.mirror_dataset_bundle(saved_dataset, records, frames, stock_rows, sector_rows):
                    result["datasets"]["succeeded"] += 1
                    result["snapshotBundles"]["succeeded"] += len(frames)
                else:
                    result["datasets"]["failed"] += 1
                    result["snapshotBundles"]["failed"] += len(frames)
                    result["errors"].append(
                        {
                            "type": "dataset_bundle",
                            "key": dataset.id,
                            "error": self.backup.last_error or "backup mirror failed",
                        }
                    )
        except SQLAlchemyError as exc:
            result["ok"] = False
            result["errors"].append({"type": "database", "key": None, "error": str(exc)})

        if result["errors"]:
            result["ok"] = False
        return result

    def push_outbox_to_backup(
        self,
        repo: Repository,
        limit: int = 50,
        *,
        retention_policy: "_RetentionPolicy | None" = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0, "items": []}
        for row in repo.list_pending_outbox(limit=limit):
            result["scanned"] += 1
            item = {
                "id": row.id,
                "op_type": row.op_type,
                "idempotency_key": row.idempotency_key,
                "dataset_id": row.dataset_id,
                "snapshot_id": row.snapshot_id,
            }
            start_date = self._retention_start_date(row.dataset_id or "", retention_policy)
            if retention_policy and retention_policy.enabled and not self._is_retention_dataset(row.dataset_id or "", retention_policy):
                result["skipped"] += 1
                item["status"] = "skipped"
                item["error"] = "dataset is outside Supabase retention scope"
                result["items"].append(item)
                continue
            success, error = self._push_outbox_row(repo, row, start_date=start_date)
            if success:
                repo.mark_outbox_succeeded(row.idempotency_key)
                result["succeeded"] += 1
                item["status"] = "done"
            elif error == "unsupported outbox op_type":
                result["skipped"] += 1
                item["status"] = "skipped"
                item["error"] = error
            else:
                failed = repo.mark_outbox_failed(row.idempotency_key, error or "backup mirror failed")
                result["failed"] += 1
                item["status"] = failed.status if failed else "retry"
                item["error"] = error or "backup mirror failed"
            result["items"].append(item)
        return result

    def _push_outbox_row(self, repo: Repository, row: Any, *, start_date: str | None = None) -> tuple[bool, str | None]:
        if row.op_type in {"snapshot_ingest", "dataset_bundle"}:
            return self._push_dataset_outbox_row(repo, row, start_date=start_date)
        return False, "unsupported outbox op_type"

    def _push_dataset_outbox_row(
        self,
        repo: Repository,
        row: Any,
        *,
        start_date: str | None = None,
    ) -> tuple[bool, str | None]:
        if row.op_type == "snapshot_ingest" and row.snapshot_id:
            full_bundle = repo.dump_snapshot_bundle(row.dataset_id or "", row.snapshot_id)
            if not full_bundle:
                return False, "snapshot not found for outbox replay"
        else:
            full_bundle = repo.dump_dataset_bundle(row.dataset_id or "", start_date=start_date)
        if full_bundle:
            dataset, records, frames, stock_rows, sector_rows = full_bundle
        else:
            dataset_payload = {}
            dataset = Dataset(
                id=str(dataset_payload.get("id") or row.dataset_id or ""),
                name=str(dataset_payload.get("name") or row.dataset_id or ""),
                source_type=str(dataset_payload.get("source_type") or "dragon_board_runtime"),
                source_path=str(dataset_payload.get("source_path") or ""),
                db_name=str(dataset_payload.get("db_name") or "DragonBoardData"),
                schema_fingerprint=str(dataset_payload.get("schema_fingerprint") or ""),
                snapshot_count=int(dataset_payload.get("snapshot_count") or 0),
                frame_count=int(dataset_payload.get("frame_count") or 0),
                stock_row_count=int(dataset_payload.get("stock_row_count") or 0),
                sector_row_count=int(dataset_payload.get("sector_row_count") or 0),
                start_date=dataset_payload.get("start_date"),
                end_date=dataset_payload.get("end_date"),
                snapshot_types_json=json_dumps(dataset_payload.get("snapshot_types") or []),
                metadata_json=json_dumps(dataset_payload.get("metadata") or {}),
                created_at=_parse_datetime(dataset_payload.get("created_at")),
            )
            records, frames, stock_rows, sector_rows = [], [], [], []
        ok = self.backup.mirror_dataset_bundle(dataset, records, frames, stock_rows, sector_rows)
        return ok, None if ok else self.backup.last_error

    def _retention_start_date(self, dataset_id: str, policy: "_RetentionPolicy | None") -> str | None:
        if not policy or not policy.enabled:
            return None
        if not self._is_retention_dataset(dataset_id, policy):
            return None
        if not self.session:
            return None
        return _local_retention_start_date(self.session, dataset_id, policy.keep_trading_days)

    @staticmethod
    def _is_retention_dataset(dataset_id: str, policy: "_RetentionPolicy") -> bool:
        return dataset_id in policy.dataset_ids

    def pull_backup_to_primary(self) -> dict[str, Any]:
        if not self.session:
            return {"ok": False, "direction": "pull", "error": "primary database is unavailable"}
        if not self.backup:
            return {"ok": False, "direction": "pull", "error": "supabase backup is not configured"}

        repo = Repository(self.session, self.backup, enable_backup=False)
        result = {
            "ok": True,
            "direction": "pull",
            "datasets": 0,
            "snapshotBundles": 0,
            "research": {"policy": "local_research_db_only"},
            "errors": [],
        }

        try:
            for row in self.backup.list_rows("qb_dataset"):
                dataset = self.backup.dataset_from_row(row)
                bundle_rows = self.backup.list_rows("qb_snapshot_bundle", source=dataset.id)
                records: list[dict[str, Any]] = []
                frames: list[dict[str, Any]] = []
                stock_rows: list[dict[str, Any]] = []
                sector_rows: list[dict[str, Any]] = []
                for bundle_row in bundle_rows:
                    payload = bundle_row.get("payload") if isinstance(bundle_row.get("payload"), dict) else {}
                    frame = payload.get("frame") if isinstance(payload.get("frame"), dict) else None
                    record = payload.get("record") if isinstance(payload.get("record"), dict) else None
                    stocks = payload.get("stocks") if isinstance(payload.get("stocks"), list) else []
                    sectors = payload.get("sectors") if isinstance(payload.get("sectors"), list) else []
                    if frame:
                        frames.append(frame)
                    if record:
                        records.append(record)
                    elif frame:
                        records.append(
                            {
                                "id": frame.get("snapshotId") or frame.get("id"),
                                "type": frame.get("type"),
                                "tradingDate": frame.get("tradingDate"),
                                "slotTime": frame.get("slotTime"),
                                "timestamp": frame.get("timestamp"),
                                "displayKey": frame.get("displayKey") or frame.get("snapshotId") or frame.get("id"),
                                "captureMode": frame.get("captureMode") or "real_time",
                                "source": frame.get("source") or "supabase_backup",
                                "payload": frame.get("payload") or {},
                            }
                        )
                    stock_rows.extend([item for item in stocks if isinstance(item, dict)])
                    sector_rows.extend([item for item in sectors if isinstance(item, dict)])
                repo.save_dataset_bundle(dataset, records, frames, stock_rows, sector_rows)
                result["datasets"] += 1
                result["snapshotBundles"] += len(frames)

            self.session.commit()
        except (SQLAlchemyError, ValueError) as exc:
            self.session.rollback()
            result["ok"] = False
            result["errors"].append(str(exc))

        return result


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    return datetime.utcnow()


def _split_dataset_ids(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()] or ["dragonboard_live"]


def _local_retention_start_date(session: Session, dataset_id: str, keep_trading_days: int) -> str | None:
    if keep_trading_days <= 0:
        return None
    dates = [
        str(row[0])
        for row in session.execute(
            select(SnapshotFrameModel.trading_date)
            .where(SnapshotFrameModel.dataset_id == dataset_id)
            .group_by(SnapshotFrameModel.trading_date)
            .order_by(SnapshotFrameModel.trading_date.desc())
        ).all()
        if row[0]
    ]
    if len(dates) > keep_trading_days:
        return dates[keep_trading_days - 1]
    return None
