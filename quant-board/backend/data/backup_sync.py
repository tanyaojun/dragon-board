from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.data.models import BacktestRun, Dataset, GoldenRankTrendCase, OptimizationRun
from backend.data.repository import Repository
from backend.data.supabase_backup import SupabaseBackupClient, get_backup_client
from backend.utils import json_dumps, json_loads


class BackupSyncService:
    def __init__(self, session: Session | None, backup_client: SupabaseBackupClient | None = None) -> None:
        self.session = session
        self.backup = backup_client if backup_client is not None else get_backup_client()

    def status(self) -> dict[str, Any]:
        if not self.backup:
            return {"configured": False, "connected": False, "last_error": None}
        return self.backup.health()

    def push_all_to_backup(self) -> dict[str, Any]:
        if not self.session:
            return {"ok": False, "direction": "push", "error": "primary database is unavailable"}
        if not self.backup:
            return {"ok": False, "direction": "push", "error": "supabase backup is not configured"}

        repo = Repository(self.session, self.backup, enable_backup=False)
        result = {
            "ok": True,
            "direction": "push",
            "outbox": 0,
            "datasets": 0,
            "snapshotBundles": 0,
            "backtestRuns": 0,
            "optimizationRuns": 0,
            "goldenCases": 0,
            "errors": [],
        }
        try:
            result["outbox"] = self.push_outbox_to_backup(repo)
            for dataset in self.session.scalars(select(Dataset).order_by(Dataset.created_at.asc())):
                bundle = repo.dump_dataset_bundle(dataset.id)
                if not bundle:
                    continue
                saved_dataset, records, frames, stock_rows, sector_rows = bundle
                if self.backup.mirror_dataset_bundle(saved_dataset, records, frames, stock_rows, sector_rows):
                    result["datasets"] += 1
                    result["snapshotBundles"] += len(frames)
                else:
                    result["errors"].append(self.backup.last_error or f"failed to mirror dataset {dataset.id}")

            for run in self.session.scalars(select(BacktestRun).order_by(BacktestRun.created_at.asc())):
                if self.backup.mirror_backtest_run(run):
                    result["backtestRuns"] += 1
                else:
                    result["errors"].append(self.backup.last_error or f"failed to mirror backtest {run.id}")

            for run in self.session.scalars(select(OptimizationRun).order_by(OptimizationRun.created_at.asc())):
                if self.backup.mirror_optimization_run(run):
                    result["optimizationRuns"] += 1
                else:
                    result["errors"].append(self.backup.last_error or f"failed to mirror optimization {run.id}")

            for case in self.session.scalars(select(GoldenRankTrendCase).order_by(GoldenRankTrendCase.created_at.asc())):
                if self.backup.mirror_golden_case(case):
                    result["goldenCases"] += 1
                else:
                    result["errors"].append(self.backup.last_error or f"failed to mirror golden case {case.id}")
        except SQLAlchemyError as exc:
            result["ok"] = False
            result["errors"].append(str(exc))

        if result["errors"]:
            result["ok"] = False
        return result

    def push_outbox_to_backup(self, repo: Repository, limit: int = 50) -> int:
        synced = 0
        for row in repo.list_pending_outbox(limit=limit):
            if row.op_type != "snapshot_ingest":
                continue
            full_bundle = repo.dump_dataset_bundle(row.dataset_id or "")
            if full_bundle:
                dataset, records, frames, stock_rows, sector_rows = full_bundle
            else:
                payload = json_loads(row.payload_json, {})
                if not isinstance(payload, dict):
                    repo.mark_outbox_failed(row.idempotency_key, "invalid outbox payload")
                    continue
                dataset_payload = payload.get("dataset") if isinstance(payload.get("dataset"), dict) else {}
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
                )
                records = payload.get("records") if isinstance(payload.get("records"), list) else []
                frames = payload.get("frames") if isinstance(payload.get("frames"), list) else []
                stock_rows = payload.get("stockRows") if isinstance(payload.get("stockRows"), list) else []
                sector_rows = payload.get("sectorRows") if isinstance(payload.get("sectorRows"), list) else []
            if self.backup.mirror_dataset_bundle(dataset, records, frames, stock_rows, sector_rows):
                repo.mark_outbox_succeeded(row.idempotency_key)
                synced += 1
            else:
                repo.mark_outbox_failed(row.idempotency_key, self.backup.last_error or "backup mirror failed")
        return synced

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
            "backtestRuns": 0,
            "optimizationRuns": 0,
            "goldenCases": 0,
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

            for row in self.backup.list_rows("qb_backtest_run"):
                self.session.merge(self.backup.backtest_run_from_row(row))
                result["backtestRuns"] += 1
            for row in self.backup.list_rows("qb_optimization_run"):
                self.session.merge(self.backup.optimization_run_from_row(row))
                result["optimizationRuns"] += 1
            for row in self.backup.list_rows("qb_golden_case"):
                self.session.merge(self.backup.golden_case_from_row(row))
                result["goldenCases"] += 1
            self.session.commit()
        except (SQLAlchemyError, ValueError) as exc:
            self.session.rollback()
            result["ok"] = False
            result["errors"].append(str(exc))

        return result
