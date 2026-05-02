from __future__ import annotations

from datetime import datetime, timezone
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
        result: dict[str, Any] = {
            "ok": True,
            "direction": "push",
            "outbox": {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0, "items": []},
            "datasets": {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0},
            "snapshotBundles": {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0},
            "backtestRuns": {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0},
            "optimizationRuns": {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0},
            "goldenCases": {"scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0},
            "errors": [],
        }
        try:
            result["outbox"] = self.push_outbox_to_backup(repo)
            for dataset in self.session.scalars(select(Dataset).order_by(Dataset.created_at.asc())):
                result["datasets"]["scanned"] += 1
                bundle = repo.dump_dataset_bundle(dataset.id)
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

            for run in self.session.scalars(select(BacktestRun).order_by(BacktestRun.created_at.asc())):
                result["backtestRuns"]["scanned"] += 1
                if self.backup.mirror_backtest_run(run):
                    result["backtestRuns"]["succeeded"] += 1
                else:
                    result["backtestRuns"]["failed"] += 1
                    result["errors"].append(
                        {
                            "type": "backtest_run",
                            "key": run.id,
                            "error": self.backup.last_error or "backup mirror failed",
                        }
                    )

            for run in self.session.scalars(select(OptimizationRun).order_by(OptimizationRun.created_at.asc())):
                result["optimizationRuns"]["scanned"] += 1
                if self.backup.mirror_optimization_run(run):
                    result["optimizationRuns"]["succeeded"] += 1
                else:
                    result["optimizationRuns"]["failed"] += 1
                    result["errors"].append(
                        {
                            "type": "optimization_run",
                            "key": run.id,
                            "error": self.backup.last_error or "backup mirror failed",
                        }
                    )

            for case in self.session.scalars(select(GoldenRankTrendCase).order_by(GoldenRankTrendCase.created_at.asc())):
                result["goldenCases"]["scanned"] += 1
                if self.backup.mirror_golden_case(case):
                    result["goldenCases"]["succeeded"] += 1
                else:
                    result["goldenCases"]["failed"] += 1
                    result["errors"].append(
                        {
                            "type": "golden_case",
                            "key": case.id,
                            "error": self.backup.last_error or "backup mirror failed",
                        }
                    )
        except SQLAlchemyError as exc:
            result["ok"] = False
            result["errors"].append({"type": "database", "key": None, "error": str(exc)})

        if result["errors"]:
            result["ok"] = False
        return result

    def push_outbox_to_backup(self, repo: Repository, limit: int = 50) -> dict[str, Any]:
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
            success, error = self._push_outbox_row(repo, row)
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

    def _push_outbox_row(self, repo: Repository, row: Any) -> tuple[bool, str | None]:
        if row.op_type in {"snapshot_ingest", "dataset_bundle"}:
            return self._push_dataset_outbox_row(repo, row)
        if row.op_type == "backtest_run":
            run = self.session.get(BacktestRun, row.snapshot_id or "") if self.session else None
            if not run:
                run = self._backtest_from_outbox(row)
            ok = self.backup.mirror_backtest_run(run)
            return ok, None if ok else self.backup.last_error
        if row.op_type == "optimization_run":
            run = self.session.get(OptimizationRun, row.snapshot_id or "") if self.session else None
            if not run:
                run = self._optimization_from_outbox(row)
            ok = self.backup.mirror_optimization_run(run)
            return ok, None if ok else self.backup.last_error
        if row.op_type == "golden_case":
            case = self.session.get(GoldenRankTrendCase, row.snapshot_id or "") if self.session else None
            if not case:
                case = self._golden_from_outbox(row)
            ok = self.backup.mirror_golden_case(case)
            return ok, None if ok else self.backup.last_error
        return False, "unsupported outbox op_type"

    def _push_dataset_outbox_row(self, repo: Repository, row: Any) -> tuple[bool, str | None]:
        full_bundle = repo.dump_dataset_bundle(row.dataset_id or "")
        if full_bundle:
            dataset, records, frames, stock_rows, sector_rows = full_bundle
        else:
            payload = json_loads(row.payload_json, {})
            if not isinstance(payload, dict):
                return False, "invalid outbox payload"
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
                created_at=_parse_datetime(dataset_payload.get("created_at")),
            )
            records = payload.get("records") if isinstance(payload.get("records"), list) else []
            frames = payload.get("frames") if isinstance(payload.get("frames"), list) else []
            stock_rows = payload.get("stockRows") if isinstance(payload.get("stockRows"), list) else []
            sector_rows = payload.get("sectorRows") if isinstance(payload.get("sectorRows"), list) else []
        ok = self.backup.mirror_dataset_bundle(dataset, records, frames, stock_rows, sector_rows)
        return ok, None if ok else self.backup.last_error

    def _backtest_from_outbox(self, row: Any) -> BacktestRun:
        payload = json_loads(row.payload_json, {})
        run_payload = payload.get("run") if isinstance(payload, dict) and isinstance(payload.get("run"), dict) else {}
        return BacktestRun(
            id=str(run_payload.get("id") or row.snapshot_id or ""),
            dataset_id=str(run_payload.get("dataset_id") or row.dataset_id or ""),
            strategy_name=str(run_payload.get("strategy_name") or "rank_trend_candidate"),
            strategy_version=str(run_payload.get("strategy_version") or "0.1.0"),
            snapshot_type=str(run_payload.get("snapshot_type") or "half_hour"),
            config_hash=str(run_payload.get("config_hash") or ""),
            random_seed=int(run_payload.get("random_seed") or 0),
            status=str(run_payload.get("status") or "completed"),
            request_json=str(run_payload.get("request_json") or "{}"),
            result_json=str(run_payload.get("result_json") or "{}"),
            created_at=_parse_datetime(run_payload.get("created_at")),
        )

    def _optimization_from_outbox(self, row: Any) -> OptimizationRun:
        payload = json_loads(row.payload_json, {})
        run_payload = payload.get("run") if isinstance(payload, dict) and isinstance(payload.get("run"), dict) else {}
        return OptimizationRun(
            id=str(run_payload.get("id") or row.snapshot_id or ""),
            dataset_id=str(run_payload.get("dataset_id") or row.dataset_id or ""),
            strategy_name=str(run_payload.get("strategy_name") or "rank_trend_candidate"),
            method=str(run_payload.get("method") or "grid"),
            config_hash=str(run_payload.get("config_hash") or ""),
            random_seed=int(run_payload.get("random_seed") or 0),
            status=str(run_payload.get("status") or "completed"),
            request_json=str(run_payload.get("request_json") or "{}"),
            result_json=str(run_payload.get("result_json") or "{}"),
            created_at=_parse_datetime(run_payload.get("created_at")),
        )

    def _golden_from_outbox(self, row: Any) -> GoldenRankTrendCase:
        payload = json_loads(row.payload_json, {})
        case_payload = payload.get("case") if isinstance(payload, dict) and isinstance(payload.get("case"), dict) else {}
        return GoldenRankTrendCase(
            id=str(case_payload.get("id") or row.snapshot_id or ""),
            name=str(case_payload.get("name") or row.snapshot_id or ""),
            dataset_id=case_payload.get("dataset_id") or row.dataset_id,
            input_json=str(case_payload.get("input_json") or "{}"),
            expected_json=str(case_payload.get("expected_json") or "{}"),
            created_at=_parse_datetime(case_payload.get("created_at")),
        )

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
