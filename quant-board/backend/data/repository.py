from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.data.models import (
    BacktestRun,
    Dataset,
    GoldenRankTrendCase,
    OptimizationRun,
    SnapshotFrameModel,
    SnapshotRecordModel,
    SnapshotSectorRowModel,
    SnapshotStockRowModel,
    SyncOutboxModel,
)
from backend.data.supabase_backup import SupabaseBackupClient, get_backup_client
from backend.utils import json_dumps, json_loads, stable_hash


class Repository:
    def __init__(
        self,
        session: Session | None,
        backup_client: SupabaseBackupClient | None = None,
        *,
        enable_backup: bool = True,
    ):
        self.session = session
        self.enable_backup = enable_backup
        self.backup = None if not enable_backup else (backup_client if backup_client is not None else get_backup_client())

    def list_datasets(self) -> list[Dataset]:
        if self.session is None:
            return self._backup_datasets()
        try:
            datasets = list(self.session.scalars(select(Dataset).order_by(Dataset.created_at.desc())))
            backup_by_id = {dataset.id: dataset for dataset in self._backup_datasets()}
            merged = []
            for dataset in datasets:
                backup_by_id.pop(dataset.id, None)
                merged.append(dataset)
            merged.extend(backup_by_id.values())
            return sorted(merged, key=lambda item: item.created_at, reverse=True)
        except SQLAlchemyError:
            return self._backup_datasets()

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        if self.session is None:
            return self._backup_dataset(dataset_id)
        try:
            return self.session.get(Dataset, dataset_id) or self._backup_dataset(dataset_id)
        except SQLAlchemyError:
            return self._backup_dataset(dataset_id)

    def delete_dataset_children(self, dataset_id: str) -> None:
        if self.session is None:
            return
        for model in [SnapshotSectorRowModel, SnapshotStockRowModel, SnapshotFrameModel, SnapshotRecordModel]:
            self.session.execute(delete(model).where(model.dataset_id == dataset_id))

    def delete_snapshot_children(self, dataset_id: str, snapshot_ids: list[str]) -> None:
        if self.session is None or not snapshot_ids:
            return
        self.session.execute(
            delete(SnapshotSectorRowModel).where(
                SnapshotSectorRowModel.dataset_id == dataset_id,
                SnapshotSectorRowModel.snapshot_id.in_(snapshot_ids),
            )
        )
        self.session.execute(
            delete(SnapshotStockRowModel).where(
                SnapshotStockRowModel.dataset_id == dataset_id,
                SnapshotStockRowModel.snapshot_id.in_(snapshot_ids),
            )
        )
        self.session.execute(
            delete(SnapshotFrameModel).where(
                SnapshotFrameModel.dataset_id == dataset_id,
                SnapshotFrameModel.snapshot_id.in_(snapshot_ids),
            )
        )
        self.session.execute(
            delete(SnapshotRecordModel).where(
                SnapshotRecordModel.dataset_id == dataset_id,
                SnapshotRecordModel.snapshot_id.in_(snapshot_ids),
            )
        )

    def save_dataset_bundle(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
    ) -> Dataset:
        if self.session is None:
            if not self._mirror_dataset_bundle(dataset, records, frames, stock_rows, sector_rows):
                raise RuntimeError("primary database is unavailable and Supabase backup is not configured or writable")
            return dataset

        try:
            self.session.merge(dataset)
            self.delete_dataset_children(dataset.id)

            self.session.add_all([self._record_model(dataset.id, item) for item in records])
            self.session.add_all([self._frame_model(dataset.id, item) for item in frames])
            self.session.add_all([self._stock_model(dataset.id, item) for item in stock_rows])
            self.session.add_all([self._sector_model(dataset.id, item) for item in sector_rows])
            self.session.flush()
            self._refresh_dataset_summary(dataset.id)
            saved_for_sync = self.session.get(Dataset, dataset.id) or dataset
            outbox_key = self._queue_backup_outbox(
                "dataset_bundle",
                {"dataset": self.dataset_to_dict(saved_for_sync)},
                dataset_id=dataset.id,
                snapshot_id=None,
            )
            self.session.commit()
            saved = self.session.get(Dataset, dataset.id)
        except SQLAlchemyError:
            self.session.rollback()
            if not self._mirror_dataset_bundle(dataset, records, frames, stock_rows, sector_rows):
                raise RuntimeError("primary database write failed and Supabase backup write also failed")
            return dataset
        mirror_ok = self._mirror_dataset_bundle(saved or dataset, records, frames, stock_rows, sector_rows)
        self._finalize_outbox_mirror(outbox_key, mirror_ok)
        return saved or dataset

    def save_snapshot_ingest(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
        *,
        idempotency_key: str,
        trading_date: str | None = None,
        source: str = "dragon_board_runtime",
    ) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("primary database is unavailable")

        existing = self.get_outbox_by_idempotency_key(idempotency_key)
        if existing:
            return {
                "dataset": self.dataset_to_dict(dataset),
                "status": existing.status,
                "outbox": self.outbox_to_dict(existing),
                "deduped": True,
            }

        snapshot_ids = sorted(
            {
                str(item.get("id") or item.get("snapshotId") or "")
                for item in [*records, *frames, *stock_rows, *sector_rows]
                if isinstance(item, dict) and (item.get("id") or item.get("snapshotId"))
            }
        )
        self.session.merge(dataset)
        self.delete_snapshot_children(dataset.id, snapshot_ids)
        self.session.add_all([self._record_model(dataset.id, item) for item in records])
        self.session.add_all([self._frame_model(dataset.id, item) for item in frames])
        self.session.add_all([self._stock_model(dataset.id, item) for item in stock_rows])
        self.session.add_all([self._sector_model(dataset.id, item) for item in sector_rows])
        self.session.flush()
        self._refresh_dataset_summary(dataset.id)

        outbox = self._add_outbox_row(
            "snapshot_ingest",
            {
                "dataset": self.dataset_to_dict(dataset),
                "records": records,
                "frames": frames,
                "stockRows": stock_rows,
                "sectorRows": sector_rows,
                "tradingDate": trading_date,
                "source": source,
            },
            idempotency_key=idempotency_key,
            dataset_id=dataset.id,
            snapshot_id=snapshot_ids[0] if snapshot_ids else None,
        )
        self.session.commit()
        saved_dataset = self.session.get(Dataset, dataset.id) or dataset
        mirror_ok = False
        if self.backup:
            full_bundle = self.dump_dataset_bundle(dataset.id)
            if full_bundle:
                mirror_dataset, mirror_records, mirror_frames, mirror_stock_rows, mirror_sector_rows = full_bundle
                mirror_ok = self._mirror_dataset_bundle(
                    mirror_dataset,
                    mirror_records,
                    mirror_frames,
                    mirror_stock_rows,
                    mirror_sector_rows,
                )
            else:
                mirror_ok = self._mirror_dataset_bundle(saved_dataset, records, frames, stock_rows, sector_rows)
            refreshed_outbox = self._finalize_outbox_mirror(idempotency_key, mirror_ok)
            if refreshed_outbox:
                outbox = refreshed_outbox
        return {
            "dataset": self.dataset_to_dict(saved_dataset),
            "status": outbox.status,
            "outbox": self.outbox_to_dict(outbox),
            "deduped": False,
        }

    def get_outbox_by_idempotency_key(self, idempotency_key: str) -> SyncOutboxModel | None:
        if self.session is None:
            return None
        try:
            return self.session.scalar(
                select(SyncOutboxModel).where(SyncOutboxModel.idempotency_key == idempotency_key)
            )
        except SQLAlchemyError:
            return None

    def enqueue_outbox(
        self,
        op_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        dataset_id: str | None = None,
        snapshot_id: str | None = None,
        status: str = "pending",
        next_retry_at: datetime | None = None,
    ) -> SyncOutboxModel:
        if self.session is None:
            raise RuntimeError("primary database is unavailable")
        existing = self.get_outbox_by_idempotency_key(idempotency_key)
        if existing:
            return existing
        row = SyncOutboxModel(
            op_type=op_type,
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            payload_json=json_dumps(payload),
            idempotency_key=idempotency_key,
            status=status,
            retry_count=0,
            next_retry_at=next_retry_at,
        )
        self.session.add(row)
        self.session.commit()
        return row

    def _add_outbox_row(
        self,
        op_type: str,
        payload: dict[str, Any],
        *,
        idempotency_key: str,
        dataset_id: str | None = None,
        snapshot_id: str | None = None,
        status: str = "pending",
        next_retry_at: datetime | None = None,
    ) -> SyncOutboxModel:
        if self.session is None:
            raise RuntimeError("primary database is unavailable")
        existing = self.get_outbox_by_idempotency_key(idempotency_key)
        if existing:
            return existing
        row = SyncOutboxModel(
            op_type=op_type,
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            payload_json=json_dumps(payload),
            idempotency_key=idempotency_key,
            status=status,
            retry_count=0,
            next_retry_at=next_retry_at,
        )
        self.session.add(row)
        return row

    def _queue_backup_outbox(
        self,
        op_type: str,
        payload: dict[str, Any],
        *,
        dataset_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> str | None:
        if self.session is None or not self.enable_backup:
            return None
        idempotency_key = f"{op_type}:{snapshot_id or dataset_id or stable_hash(payload)[:24]}:{stable_hash(payload)[:24]}"
        self._add_outbox_row(
            op_type,
            payload,
            idempotency_key=idempotency_key[:160],
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
        )
        return idempotency_key[:160]

    def _finalize_outbox_mirror(self, idempotency_key: str | None, mirror_ok: bool) -> SyncOutboxModel | None:
        if not idempotency_key or self.session is None or not self.enable_backup:
            return None
        if mirror_ok:
            return self.mark_outbox_succeeded(idempotency_key)
        if self.backup:
            return self.mark_outbox_failed(idempotency_key, self.backup.last_error or "backup mirror failed")
        return self.get_outbox_by_idempotency_key(idempotency_key)

    def list_pending_outbox(self, limit: int = 50) -> list[SyncOutboxModel]:
        if self.session is None:
            return []
        try:
            now = datetime.utcnow()
            query = (
                select(SyncOutboxModel)
                .where(SyncOutboxModel.status.in_(["pending", "retry"]))
                .where((SyncOutboxModel.next_retry_at.is_(None)) | (SyncOutboxModel.next_retry_at <= now))
                .order_by(SyncOutboxModel.updated_at.asc(), SyncOutboxModel.id.asc())
                .limit(limit)
            )
            return list(self.session.scalars(query))
        except SQLAlchemyError:
            return []

    def mark_outbox_succeeded(self, idempotency_key: str) -> SyncOutboxModel | None:
        if self.session is None:
            return None
        row = self.get_outbox_by_idempotency_key(idempotency_key)
        if not row:
            return None
        row.status = "done"
        row.last_error = None
        row.next_retry_at = None
        row.retry_count = int(row.retry_count or 0)
        self.session.commit()
        return row

    def mark_outbox_failed(
        self,
        idempotency_key: str,
        error: str,
        *,
        delay_seconds: int = 60,
        max_retries: int = 5,
    ) -> SyncOutboxModel | None:
        if self.session is None:
            return None
        row = self.get_outbox_by_idempotency_key(idempotency_key)
        if not row:
            return None
        row.retry_count = int(row.retry_count or 0) + 1
        row.last_error = error
        if row.retry_count >= max_retries:
            row.status = "failed"
            row.next_retry_at = None
        else:
            row.status = "retry"
            row.next_retry_at = datetime.utcnow() + timedelta(seconds=max(0, delay_seconds))
        self.session.commit()
        return row

    def get_outbox(self, outbox_id: int) -> SyncOutboxModel | None:
        if self.session is None:
            return None
        try:
            return self.session.get(SyncOutboxModel, outbox_id)
        except SQLAlchemyError:
            return None

    def list_outbox(self, limit: int = 50) -> list[SyncOutboxModel]:
        return self.list_pending_outbox(limit)

    def outbox_status(self) -> dict[str, int]:
        if self.session is None:
            return {"pending": 0, "retry": 0, "done": 0, "failed": 0, "total": 0}
        rows = self.session.execute(
            select(SyncOutboxModel.status, func.count()).group_by(SyncOutboxModel.status)
        ).all()
        counts = {"pending": 0, "retry": 0, "done": 0, "failed": 0}
        total = 0
        for status, count in rows:
            key = str(status or "pending")
            value = int(count or 0)
            counts[key] = value
            total += value
        counts["total"] = total
        return counts

    def load_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
    ) -> list[dict[str, Any]]:
        if self.session is None:
            return self._backup_frames(dataset_id, snapshot_type, start_date, end_date, include_payload)
        query = select(SnapshotFrameModel).where(
            SnapshotFrameModel.dataset_id == dataset_id,
            SnapshotFrameModel.type == snapshot_type,
        )
        if start_date:
            query = query.where(SnapshotFrameModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotFrameModel.trading_date <= end_date)
        try:
            frame_models = list(self.session.scalars(query.order_by(SnapshotFrameModel.timestamp.asc())))
        except SQLAlchemyError:
            return self._backup_frames(dataset_id, snapshot_type, start_date, end_date, include_payload)

        snapshot_ids = [frame.snapshot_id for frame in frame_models]
        rows_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if snapshot_ids:
            row_query = (
                select(SnapshotStockRowModel)
                .where(
                    SnapshotStockRowModel.dataset_id == dataset_id,
                    SnapshotStockRowModel.snapshot_id.in_(snapshot_ids),
                )
                .order_by(SnapshotStockRowModel.timestamp.asc(), SnapshotStockRowModel.rank.asc())
            )
            try:
                for row in self.session.scalars(row_query):
                    rows_by_snapshot[row.snapshot_id].append(self.stock_row_to_dict(row, include_payload=include_payload))
            except SQLAlchemyError:
                return self._backup_frames(dataset_id, snapshot_type, start_date, end_date, include_payload)

        frames: list[dict[str, Any]] = []
        for frame in frame_models:
            item = self.frame_to_dict(frame)
            item["stocks"] = rows_by_snapshot.get(frame.snapshot_id, [])
            frames.append(item)
        return frames or self._backup_frames(dataset_id, snapshot_type, start_date, end_date, include_payload)

    def save_backtest_run(self, run: BacktestRun) -> BacktestRun:
        if self.session is None:
            if not self._mirror_backtest_run(run):
                raise RuntimeError("primary database is unavailable and Supabase backup is not configured or writable")
            return run
        try:
            managed = self.session.merge(run)
            outbox_key = self._queue_backup_outbox(
                "backtest_run",
                {"run": self.backtest_run_to_dict(managed)},
                dataset_id=managed.dataset_id,
                snapshot_id=managed.id,
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            if not self._mirror_backtest_run(run):
                raise RuntimeError("primary database write failed and Supabase backup write also failed")
            return run
        saved = self.session.get(BacktestRun, run.id) or run
        mirror_ok = self._mirror_backtest_run(saved)
        self._finalize_outbox_mirror(outbox_key, mirror_ok)
        return saved

    def get_backtest_run(self, run_id: str) -> BacktestRun | None:
        if self.session is None:
            return self._backup_backtest_run(run_id)
        try:
            return self.session.get(BacktestRun, run_id) or self._backup_backtest_run(run_id)
        except SQLAlchemyError:
            return self._backup_backtest_run(run_id)

    def save_optimization_run(self, run: OptimizationRun) -> OptimizationRun:
        if self.session is None:
            if not self._mirror_optimization_run(run):
                raise RuntimeError("primary database is unavailable and Supabase backup is not configured or writable")
            return run
        try:
            managed = self.session.merge(run)
            outbox_key = self._queue_backup_outbox(
                "optimization_run",
                {"run": self.optimization_run_to_dict(managed)},
                dataset_id=managed.dataset_id,
                snapshot_id=managed.id,
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            if not self._mirror_optimization_run(run):
                raise RuntimeError("primary database write failed and Supabase backup write also failed")
            return run
        saved = self.session.get(OptimizationRun, run.id) or run
        mirror_ok = self._mirror_optimization_run(saved)
        self._finalize_outbox_mirror(outbox_key, mirror_ok)
        return saved

    def get_optimization_run(self, run_id: str) -> OptimizationRun | None:
        if self.session is None:
            return self._backup_optimization_run(run_id)
        try:
            return self.session.get(OptimizationRun, run_id) or self._backup_optimization_run(run_id)
        except SQLAlchemyError:
            return self._backup_optimization_run(run_id)

    def save_golden_case(self, case: GoldenRankTrendCase) -> GoldenRankTrendCase:
        if self.session is None:
            if not self._mirror_golden_case(case):
                raise RuntimeError("primary database is unavailable and Supabase backup is not configured or writable")
            return case
        try:
            managed = self.session.merge(case)
            outbox_key = self._queue_backup_outbox(
                "golden_case",
                {"case": self.golden_case_to_dict(managed)},
                dataset_id=managed.dataset_id,
                snapshot_id=managed.id,
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            if not self._mirror_golden_case(case):
                raise RuntimeError("primary database write failed and Supabase backup write also failed")
            return case
        saved = self.session.get(GoldenRankTrendCase, case.id) or case
        mirror_ok = self._mirror_golden_case(saved)
        self._finalize_outbox_mirror(outbox_key, mirror_ok)
        return saved

    def get_golden_case(self, case_id: str) -> GoldenRankTrendCase | None:
        if self.session is None:
            return self._backup_golden_case(case_id)
        try:
            return self.session.get(GoldenRankTrendCase, case_id) or self._backup_golden_case(case_id)
        except SQLAlchemyError:
            return self._backup_golden_case(case_id)

    def dump_dataset_bundle(
        self,
        dataset_id: str,
    ) -> tuple[Dataset, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
        if self.session is None:
            return None
        dataset = self.session.get(Dataset, dataset_id)
        if not dataset:
            return None
        records = [
            self.record_to_dict(row)
            for row in self.session.scalars(
                select(SnapshotRecordModel)
                .where(SnapshotRecordModel.dataset_id == dataset_id)
                .order_by(SnapshotRecordModel.timestamp.asc())
            )
        ]
        frames = [
            self.local_frame_to_bundle_dict(row)
            for row in self.session.scalars(
                select(SnapshotFrameModel)
                .where(SnapshotFrameModel.dataset_id == dataset_id)
                .order_by(SnapshotFrameModel.timestamp.asc())
            )
        ]
        stock_rows = [
            self.local_stock_to_bundle_dict(row)
            for row in self.session.scalars(
                select(SnapshotStockRowModel)
                .where(SnapshotStockRowModel.dataset_id == dataset_id)
                .order_by(SnapshotStockRowModel.timestamp.asc(), SnapshotStockRowModel.rank.asc())
            )
        ]
        sector_rows = [
            self.local_sector_to_bundle_dict(row)
            for row in self.session.scalars(
                select(SnapshotSectorRowModel)
                .where(SnapshotSectorRowModel.dataset_id == dataset_id)
                .order_by(SnapshotSectorRowModel.timestamp.asc(), SnapshotSectorRowModel.rank.asc())
            )
        ]
        return dataset, records, frames, stock_rows, sector_rows

    @staticmethod
    def dataset_to_dict(model: Dataset) -> dict[str, Any]:
        return {
            "id": model.id,
            "name": model.name,
            "source_type": model.source_type,
            "source_path": model.source_path,
            "db_name": model.db_name,
            "schema_fingerprint": model.schema_fingerprint,
            "snapshot_count": model.snapshot_count,
            "frame_count": model.frame_count,
            "stock_row_count": model.stock_row_count,
            "sector_row_count": model.sector_row_count,
            "start_date": model.start_date,
            "end_date": model.end_date,
            "snapshot_types": json_loads(model.snapshot_types_json, []),
            "metadata": json_loads(model.metadata_json, {}),
            "created_at": model.created_at.isoformat(),
        }

    @staticmethod
    def backtest_run_to_dict(model: BacktestRun) -> dict[str, Any]:
        return {
            "id": model.id,
            "dataset_id": model.dataset_id,
            "strategy_name": model.strategy_name,
            "strategy_version": model.strategy_version,
            "snapshot_type": model.snapshot_type,
            "config_hash": model.config_hash,
            "random_seed": model.random_seed,
            "status": model.status,
            "request_json": model.request_json,
            "result_json": model.result_json,
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }

    @staticmethod
    def optimization_run_to_dict(model: OptimizationRun) -> dict[str, Any]:
        return {
            "id": model.id,
            "dataset_id": model.dataset_id,
            "strategy_name": model.strategy_name,
            "method": model.method,
            "config_hash": model.config_hash,
            "random_seed": model.random_seed,
            "status": model.status,
            "request_json": model.request_json,
            "result_json": model.result_json,
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }

    @staticmethod
    def golden_case_to_dict(model: GoldenRankTrendCase) -> dict[str, Any]:
        return {
            "id": model.id,
            "name": model.name,
            "dataset_id": model.dataset_id,
            "input_json": model.input_json,
            "expected_json": model.expected_json,
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }

    @staticmethod
    def record_to_dict(model: SnapshotRecordModel) -> dict[str, Any]:
        payload = json_loads(model.payload_json, {})
        if isinstance(payload, dict):
            payload = dict(payload)
        else:
            payload = {}
        payload.update(
            {
                "id": model.snapshot_id,
                "snapshotId": model.snapshot_id,
                "type": model.type,
                "tradingDate": model.trading_date,
                "slotTime": model.slot_time,
                "timestamp": model.timestamp,
                "displayKey": model.display_key,
                "captureMode": model.capture_mode,
                "source": model.source,
            }
        )
        return payload

    @staticmethod
    def frame_to_dict(model: SnapshotFrameModel) -> dict[str, Any]:
        context = json_loads(model.market_context_json, {})
        return {
            "snapshotId": model.snapshot_id,
            "timestamp": model.timestamp,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "type": model.type,
            "captureMode": model.capture_mode,
            "source": model.source,
            "marketContext": context,
            "stocks": [],
        }

    @staticmethod
    def local_frame_to_bundle_dict(model: SnapshotFrameModel) -> dict[str, Any]:
        context = json_loads(model.market_context_json, {})
        return {
            "id": model.snapshot_id,
            "snapshotId": model.snapshot_id,
            "timestamp": model.timestamp,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "type": model.type,
            "captureMode": model.capture_mode,
            "source": model.source,
            "marketStats": context.get("marketStats"),
            "sentiment": context.get("sentiment"),
            "moneyFlow": context.get("moneyFlow"),
            "indices": context.get("indices"),
            "limitSummary": context.get("limitSummary"),
            "rotationSummary": context.get("rotationSummary"),
            "payload": context.get("payload"),
            "stockRowCount": model.stock_row_count,
            "sectorRowCount": model.sector_row_count,
        }

    @staticmethod
    def stock_row_to_dict(model: SnapshotStockRowModel, include_payload: bool = True) -> dict[str, Any]:
        payload = json_loads(model.payload_json, {}) if include_payload else {}
        payload.update(
            {
                "code": model.code,
                "name": model.name,
                "rank": model.rank,
                "price": model.price,
                "change": model.change,
                "volumeRatio": model.volume_ratio,
                "zlje": model.zlje,
                "zljzb": model.zljzb,
                "turnover": model.turnover,
                "turnoverRate": model.turnover_rate,
            }
        )
        return payload

    @staticmethod
    def local_stock_to_bundle_dict(model: SnapshotStockRowModel) -> dict[str, Any]:
        payload = json_loads(model.payload_json, {})
        if isinstance(payload, dict):
            payload = dict(payload)
        else:
            payload = {}
        payload.update(
            {
                "id": model.row_id,
                "rowId": model.row_id,
                "snapshotId": model.snapshot_id,
                "type": model.type,
                "tradingDate": model.trading_date,
                "slotTime": model.slot_time,
                "timestamp": model.timestamp,
                "captureMode": model.capture_mode,
                "code": model.code,
                "name": model.name,
                "rank": model.rank,
                "price": model.price,
                "change": model.change,
                "volumeRatio": model.volume_ratio,
                "zlje": model.zlje,
                "zljzb": model.zljzb,
                "turnover": model.turnover,
                "turnoverRate": model.turnover_rate,
            }
        )
        return payload

    @staticmethod
    def local_sector_to_bundle_dict(model: SnapshotSectorRowModel) -> dict[str, Any]:
        payload = json_loads(model.payload_json, {})
        if isinstance(payload, dict):
            payload = dict(payload)
        else:
            payload = {}
        payload.update(
            {
                "id": model.row_id,
                "rowId": model.row_id,
                "snapshotId": model.snapshot_id,
                "type": model.type,
                "tradingDate": model.trading_date,
                "slotTime": model.slot_time,
                "timestamp": model.timestamp,
                "entityType": model.entity_type,
                "entityKey": model.entity_key,
                "entityName": model.entity_name,
                "rank": model.rank,
            }
        )
        return payload

    @staticmethod
    def _record_model(dataset_id: str, item: dict[str, Any]) -> SnapshotRecordModel:
        return SnapshotRecordModel(
            dataset_id=dataset_id,
            snapshot_id=str(item.get("id") or item.get("snapshotId")),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            display_key=str(item.get("displayKey") or ""),
            capture_mode=str(item.get("captureMode") or "real_time"),
            source=str(item.get("source") or "browser_runtime"),
            payload_json=json_dumps(item.get("payload") or item),
        )

    @staticmethod
    def _frame_model(dataset_id: str, item: dict[str, Any]) -> SnapshotFrameModel:
        context = {
            "marketStats": item.get("marketStats"),
            "sentiment": item.get("sentiment"),
            "moneyFlow": item.get("moneyFlow"),
            "indices": item.get("indices"),
            "limitSummary": item.get("limitSummary"),
            "rotationSummary": item.get("rotationSummary"),
            "payload": item.get("payload"),
        }
        return SnapshotFrameModel(
            dataset_id=dataset_id,
            snapshot_id=str(item.get("snapshotId") or item.get("id")),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            capture_mode=str(item.get("captureMode") or "real_time"),
            source=str(item.get("source") or "browser_runtime"),
            market_context_json=json_dumps(context),
            stock_row_count=int(item.get("stockRowCount") or 0),
            sector_row_count=int(item.get("sectorRowCount") or 0),
        )

    @staticmethod
    def _stock_model(dataset_id: str, item: dict[str, Any]) -> SnapshotStockRowModel:
        row_id = str(item.get("id") or f"{item.get('snapshotId')}:{item.get('code')}")
        return SnapshotStockRowModel(
            dataset_id=dataset_id,
            row_id=row_id,
            snapshot_id=str(item.get("snapshotId") or ""),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            capture_mode=str(item.get("captureMode") or "real_time"),
            code=str(item.get("code") or ""),
            name=str(item.get("name") or item.get("code") or ""),
            rank=int(float(item.get("rank") or item.get("compRank") or 0)),
            price=_maybe_float(item.get("price")),
            change=_maybe_float(item.get("change")),
            volume_ratio=_maybe_float(item.get("volumeRatio")),
            zlje=_maybe_float(item.get("zlje")),
            zljzb=_maybe_float(item.get("zljzb")),
            turnover=_maybe_float(item.get("turnover")),
            turnover_rate=_maybe_float(item.get("turnoverRate")),
            payload_json=json_dumps(item),
        )

    @staticmethod
    def _sector_model(dataset_id: str, item: dict[str, Any]) -> SnapshotSectorRowModel:
        row_id = str(item.get("id") or f"{item.get('snapshotId')}:{item.get('entityType')}:{item.get('entityKey')}")
        return SnapshotSectorRowModel(
            dataset_id=dataset_id,
            row_id=row_id,
            snapshot_id=str(item.get("snapshotId") or ""),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            entity_type=str(item.get("entityType") or ""),
            entity_key=str(item.get("entityKey") or ""),
            entity_name=str(item.get("entityName") or ""),
            rank=int(float(item.get("rank") or 0)),
            payload_json=json_dumps(item),
        )

    def _backup_datasets(self) -> list[Dataset]:
        if not self.backup:
            return []
        rows = self.backup.list_rows("qb_dataset")
        return sorted(
            [self.backup.dataset_from_row(row) for row in rows],
            key=lambda item: item.created_at,
            reverse=True,
        )

    def _backup_dataset(self, dataset_id: str) -> Dataset | None:
        if not self.backup:
            return None
        row = self.backup.get_row("qb_dataset", dataset_id, source=dataset_id)
        return self.backup.dataset_from_row(row) if row else None

    def _backup_frames(
        self,
        dataset_id: str,
        snapshot_type: str,
        start_date: str | None,
        end_date: str | None,
        include_payload: bool,
    ) -> list[dict[str, Any]]:
        if not self.backup:
            return []
        rows = self.backup.list_rows("qb_snapshot_bundle", source=dataset_id)
        return self.backup.frames_from_rows(rows, snapshot_type, start_date, end_date, include_payload)

    def _backup_backtest_run(self, run_id: str) -> BacktestRun | None:
        if not self.backup:
            return None
        row = self.backup.get_row("qb_backtest_run", run_id)
        return self.backup.backtest_run_from_row(row) if row else None

    def _backup_optimization_run(self, run_id: str) -> OptimizationRun | None:
        if not self.backup:
            return None
        row = self.backup.get_row("qb_optimization_run", run_id)
        return self.backup.optimization_run_from_row(row) if row else None

    def _backup_golden_case(self, case_id: str) -> GoldenRankTrendCase | None:
        if not self.backup:
            return None
        row = self.backup.get_row("qb_golden_case", case_id)
        return self.backup.golden_case_from_row(row) if row else None

    def _mirror_dataset_bundle(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
    ) -> bool:
        if self.backup:
            return self.backup.mirror_dataset_bundle(dataset, records, frames, stock_rows, sector_rows)
        return False

    def _mirror_backtest_run(self, run: BacktestRun) -> bool:
        if self.backup:
            return self.backup.mirror_backtest_run(run)
        return False

    def _mirror_optimization_run(self, run: OptimizationRun) -> bool:
        if self.backup:
            return self.backup.mirror_optimization_run(run)
        return False

    def _mirror_golden_case(self, case: GoldenRankTrendCase) -> bool:
        if self.backup:
            return self.backup.mirror_golden_case(case)
        return False

    def _refresh_dataset_summary(self, dataset_id: str) -> None:
        dataset = self.session.get(Dataset, dataset_id)
        if not dataset:
            return

        snapshot_count = self.session.scalar(
            select(func.count()).select_from(SnapshotRecordModel).where(SnapshotRecordModel.dataset_id == dataset_id)
        ) or 0
        frame_count = self.session.scalar(
            select(func.count()).select_from(SnapshotFrameModel).where(SnapshotFrameModel.dataset_id == dataset_id)
        ) or 0
        stock_row_count = self.session.scalar(
            select(func.count()).select_from(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == dataset_id)
        ) or 0
        sector_row_count = self.session.scalar(
            select(func.count()).select_from(SnapshotSectorRowModel).where(SnapshotSectorRowModel.dataset_id == dataset_id)
        ) or 0
        start_date = self.session.scalar(
            select(func.min(SnapshotFrameModel.trading_date)).where(SnapshotFrameModel.dataset_id == dataset_id)
        )
        end_date = self.session.scalar(
            select(func.max(SnapshotFrameModel.trading_date)).where(SnapshotFrameModel.dataset_id == dataset_id)
        )
        snapshot_types = list(
            self.session.scalars(select(SnapshotFrameModel.type).where(SnapshotFrameModel.dataset_id == dataset_id).distinct())
        )

        dataset.snapshot_count = int(snapshot_count)
        dataset.frame_count = int(frame_count)
        dataset.stock_row_count = int(stock_row_count)
        dataset.sector_row_count = int(sector_row_count)
        dataset.start_date = start_date
        dataset.end_date = end_date
        dataset.snapshot_types_json = json_dumps(sorted(snapshot_types))
        self.session.flush()

    @staticmethod
    def outbox_to_dict(model: SyncOutboxModel) -> dict[str, Any]:
        return {
            "id": model.id,
            "op_type": model.op_type,
            "dataset_id": model.dataset_id,
            "snapshot_id": model.snapshot_id,
            "payload": json_loads(model.payload_json, {}),
            "idempotency_key": model.idempotency_key,
            "status": model.status,
            "retry_count": model.retry_count,
            "last_error": model.last_error,
            "next_retry_at": model.next_retry_at.isoformat() if model.next_retry_at else None,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }


def _maybe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
