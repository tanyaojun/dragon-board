from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.data.database import ResearchSessionLocal
from backend.data.models import (
    BacktestEquityCurve,
    BacktestQualityReport,
    BacktestRun,
    BacktestSignal,
    BacktestTrade,
    Dataset,
    GoldenRankTrendCase,
    OptimizationRun,
    ArchiveManifestModel,
    SnapshotFrameModel,
    SnapshotRecordModel,
    SnapshotSectorRowModel,
    SnapshotStockRowModel,
    SyncOutboxModel,
)
from backend.data.supabase_backup import SupabaseBackupClient, get_backup_client
from backend.data.json_codec import dumps_json_field, loads_json_field
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
        self._research_session: Session | None = None

    @property
    def research_session(self) -> Session:
        if self._research_session is None:
            self._research_session = ResearchSessionLocal()
        return self._research_session

    def close(self) -> None:
        if self._research_session is not None:
            self._research_session.close()
            self._research_session = None

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

    def existing_snapshot_ids(self, dataset_id: str, snapshot_ids: list[str]) -> set[str]:
        if self.session is None or not snapshot_ids:
            return set()
        try:
            frame_rows = self.session.scalars(
                select(SnapshotFrameModel.snapshot_id).where(
                    SnapshotFrameModel.dataset_id == dataset_id,
                    SnapshotFrameModel.snapshot_id.in_(snapshot_ids),
                )
            )
            record_rows = self.session.scalars(
                select(SnapshotRecordModel.snapshot_id).where(
                    SnapshotRecordModel.dataset_id == dataset_id,
                    SnapshotRecordModel.snapshot_id.in_(snapshot_ids),
                )
            )
            return {str(item) for item in [*frame_rows, *record_rows] if item}
        except SQLAlchemyError:
            return set()

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
            return self._save_snapshot_ingest_to_backup(
                dataset,
                records,
                frames,
                stock_rows,
                sector_rows,
                idempotency_key=idempotency_key,
                reason="primary_database_unavailable",
            )

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
                str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or "")
                for item in [*records, *frames, *stock_rows, *sector_rows]
                if isinstance(item, dict)
                and (item.get("snapshotId") or item.get("snapshot_id") or item.get("id"))
            }
        )
        existing_snapshot_ids = self.existing_snapshot_ids(dataset.id, snapshot_ids)
        if existing_snapshot_ids and len(existing_snapshot_ids) == len(snapshot_ids):
            outbox = self.get_outbox_by_idempotency_key(idempotency_key)
            if outbox is None:
                outbox = self._add_outbox_row(
                    "snapshot_ingest",
                    {
                        "dataset": self.dataset_to_dict(self.session.get(Dataset, dataset.id) or dataset),
                        "records": [],
                        "frames": [],
                        "stockRows": [],
                        "sectorRows": [],
                        "tradingDate": trading_date,
                        "source": source,
                        "dedupeReason": "snapshot_ids_exist",
                        "snapshotIds": snapshot_ids,
                    },
                    idempotency_key=idempotency_key,
                    dataset_id=dataset.id,
                    snapshot_id=snapshot_ids[0] if snapshot_ids else None,
                )
                self.session.commit()
            saved_dataset = self.session.get(Dataset, dataset.id) or dataset
            return {
                "dataset": self.dataset_to_dict(saved_dataset),
                "status": outbox.status,
                "outbox": self.outbox_to_dict(outbox),
                "deduped": True,
            }
        if existing_snapshot_ids:
            missing_snapshot_ids = set(snapshot_ids) - existing_snapshot_ids
            records = self._filter_snapshot_payloads(records, missing_snapshot_ids)
            frames = self._filter_snapshot_payloads(frames, missing_snapshot_ids)
            stock_rows = self._filter_snapshot_payloads(stock_rows, missing_snapshot_ids)
            sector_rows = self._filter_snapshot_payloads(sector_rows, missing_snapshot_ids)
            snapshot_ids = sorted(missing_snapshot_ids)
        try:
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
        except SQLAlchemyError:
            self.session.rollback()
            return self._save_snapshot_ingest_to_backup(
                dataset,
                records,
                frames,
                stock_rows,
                sector_rows,
                idempotency_key=idempotency_key,
                reason="primary_database_write_failed",
            )
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

    def _save_snapshot_ingest_to_backup(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
        *,
        idempotency_key: str,
        reason: str,
    ) -> dict[str, Any]:
        if not self._mirror_dataset_bundle(dataset, records, frames, stock_rows, sector_rows):
            detail = self.backup.last_error if self.backup else "Supabase backup is not configured"
            raise RuntimeError(f"{reason} and Supabase backup write failed: {detail}")
        return {
            "dataset": self.dataset_to_dict(dataset),
            "status": "backup_only",
            "outbox": None,
            "deduped": False,
            "failover": {
                "active": True,
                "reason": reason,
                "idempotency_key": idempotency_key,
                "recovery": "run pull-backup after SQLite primary is restored",
            },
        }

    @staticmethod
    def _snapshot_id_from_payload(item: dict[str, Any]) -> str:
        return str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or "")

    @classmethod
    def _filter_snapshot_payloads(
        cls,
        items: list[dict[str, Any]],
        snapshot_ids: set[str],
    ) -> list[dict[str, Any]]:
        return [item for item in items if isinstance(item, dict) and cls._snapshot_id_from_payload(item) in snapshot_ids]

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
        payload: dict[str, Any] | None = None,
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
        payload: dict[str, Any] | None = None,
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
        idempotency_key = f"{op_type}:{snapshot_id or dataset_id or stable_hash(payload or {})[:24]}:{stable_hash(payload or {})[:24]}"
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

    def load_frame_bundles(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "asc",
    ) -> list[dict[str, Any]]:
        if self.session is None:
            return self._backup_frames(dataset_id, snapshot_type, start_date, end_date, include_payload=True)
        query = select(SnapshotFrameModel).where(
            SnapshotFrameModel.dataset_id == dataset_id,
            SnapshotFrameModel.type == snapshot_type,
        )
        if start_date:
            query = query.where(SnapshotFrameModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotFrameModel.trading_date <= end_date)
        if before_trading_date:
            query = query.where(SnapshotFrameModel.trading_date < before_trading_date)
        if allowed_capture_modes:
            query = query.where(SnapshotFrameModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotFrameModel.capture_mode != "restored")
        order = SnapshotFrameModel.timestamp.desc() if sort == "desc" else SnapshotFrameModel.timestamp.asc()
        if limit and limit > 0:
            query = query.limit(limit)
        try:
            frame_models = list(self.session.scalars(query.order_by(order)))
        except SQLAlchemyError:
            return self._backup_frames(dataset_id, snapshot_type, start_date, end_date, include_payload=True)

        snapshot_ids = [frame.snapshot_id for frame in frame_models]
        stock_rows_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        sector_rows_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if snapshot_ids:
            try:
                stock_query = (
                    select(SnapshotStockRowModel)
                    .where(
                        SnapshotStockRowModel.dataset_id == dataset_id,
                        SnapshotStockRowModel.snapshot_id.in_(snapshot_ids),
                    )
                    .order_by(SnapshotStockRowModel.timestamp.asc(), SnapshotStockRowModel.rank.asc())
                )
                for row in self.session.scalars(stock_query):
                    stock_rows_by_snapshot[row.snapshot_id].append(self.local_stock_to_bundle_dict(row))

                sector_query = (
                    select(SnapshotSectorRowModel)
                    .where(
                        SnapshotSectorRowModel.dataset_id == dataset_id,
                        SnapshotSectorRowModel.snapshot_id.in_(snapshot_ids),
                    )
                    .order_by(SnapshotSectorRowModel.timestamp.asc(), SnapshotSectorRowModel.rank.asc())
                )
                for row in self.session.scalars(sector_query):
                    sector_rows_by_snapshot[row.snapshot_id].append(self.local_sector_to_bundle_dict(row))
            except SQLAlchemyError:
                return self._backup_frames(dataset_id, snapshot_type, start_date, end_date, include_payload=True)

        bundles: list[dict[str, Any]] = []
        for frame in frame_models:
            item = self.local_frame_to_bundle_dict(frame)
            item["rows"] = stock_rows_by_snapshot.get(frame.snapshot_id, [])
            item["hotlist"] = item["rows"]
            item["entities"] = sector_rows_by_snapshot.get(frame.snapshot_id, [])
            item["sectors"] = [
                self._sector_entity_to_view(row)
                for row in item["entities"]
                if row.get("entityType") == "sector"
            ]
            item["hotThemes"] = [
                self._sector_entity_to_view(row)
                for row in item["entities"]
                if row.get("entityType") == "hot_theme"
            ]
            main_lines = [
                self._sector_entity_to_view(row)
                for row in item["entities"]
                if row.get("entityType") == "rotation_main_line"
            ]
            rotation_summary = item.get("rotationSummary") if isinstance(item.get("rotationSummary"), dict) else None
            if rotation_summary:
                item["rotationSummary"] = {**rotation_summary, "mainLines": main_lines}
            elif main_lines:
                item["rotationSummary"] = {"mainLines": main_lines}
            bundles.append(item)
        return bundles

    def list_snapshot_records(
        self,
        dataset_id: str,
        snapshot_type: str | None = None,
        snapshot_types: list[str] | None = None,
        trading_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "desc",
    ) -> list[dict[str, Any]]:
        if self.session is None:
            return []
        query = select(SnapshotRecordModel).where(SnapshotRecordModel.dataset_id == dataset_id)
        types = self._merge_types(snapshot_type, snapshot_types)
        if types:
            query = query.where(SnapshotRecordModel.type.in_(types))
        if trading_date:
            query = query.where(SnapshotRecordModel.trading_date == trading_date)
        if start_date:
            query = query.where(SnapshotRecordModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotRecordModel.trading_date <= end_date)
        if before_trading_date:
            query = query.where(SnapshotRecordModel.trading_date < before_trading_date)
        if allowed_capture_modes:
            query = query.where(SnapshotRecordModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotRecordModel.capture_mode != "restored")
        order = SnapshotRecordModel.timestamp.asc() if sort == "asc" else SnapshotRecordModel.timestamp.desc()
        if limit and limit > 0:
            query = query.limit(limit)
        try:
            return [self.record_to_dict(row) for row in self.session.scalars(query.order_by(order))]
        except SQLAlchemyError:
            return []

    def get_snapshot_record(
        self,
        snapshot_id: str,
        dataset_id: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
    ) -> dict[str, Any] | None:
        if self.session is None:
            return None
        query = select(SnapshotRecordModel).where(SnapshotRecordModel.snapshot_id == snapshot_id)
        if dataset_id:
            query = query.where(SnapshotRecordModel.dataset_id == dataset_id)
        if allowed_capture_modes:
            query = query.where(SnapshotRecordModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotRecordModel.capture_mode != "restored")
        query = query.order_by(SnapshotRecordModel.timestamp.desc())
        try:
            row = self.session.scalars(query).first()
            return self.record_to_dict(row) if row else None
        except SQLAlchemyError:
            return None

    def list_snapshot_stock_rows(
        self,
        dataset_id: str,
        snapshot_id: str | None = None,
        snapshot_type: str | None = None,
        snapshot_types: list[str] | None = None,
        trading_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        code: str | None = None,
        codes: list[str] | None = None,
        slot_time: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "desc",
    ) -> dict[str, Any]:
        if self.session is None:
            return {"rows": [], "source": "sqlite"}
        query = select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == dataset_id)
        types = self._merge_types(snapshot_type, snapshot_types)
        stock_codes = self._merge_values(code, codes)
        if snapshot_id:
            query = query.where(SnapshotStockRowModel.snapshot_id == snapshot_id)
        if types:
            query = query.where(SnapshotStockRowModel.type.in_(types))
        if trading_date:
            query = query.where(SnapshotStockRowModel.trading_date == trading_date)
        if start_date:
            query = query.where(SnapshotStockRowModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotStockRowModel.trading_date <= end_date)
        if before_trading_date:
            query = query.where(SnapshotStockRowModel.trading_date < before_trading_date)
        if stock_codes:
            query = query.where(SnapshotStockRowModel.code.in_(stock_codes))
        if slot_time:
            query = query.where(SnapshotStockRowModel.slot_time == slot_time)
        if allowed_capture_modes:
            query = query.where(SnapshotStockRowModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotStockRowModel.capture_mode != "restored")
        order = SnapshotStockRowModel.timestamp.asc() if sort == "asc" else SnapshotStockRowModel.timestamp.desc()
        if limit and limit > 0:
            query = query.limit(limit)
        try:
            rows = [self.local_stock_to_bundle_dict(row) for row in self.session.scalars(query.order_by(order, SnapshotStockRowModel.rank.asc()))]
        except SQLAlchemyError:
            return {"rows": [], "source": "sqlite"}
        archived = self._archived_stock_rows(
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            snapshot_type=types[0] if len(types) == 1 else snapshot_type,
            trading_date=trading_date,
            code=code,
            slot_time=slot_time,
            sort=sort,
            limit=limit if not rows else None,
        )
        merged = self._merge_archived_rows(rows, archived, limit=limit, sort=sort)
        source = _compute_archive_source(bool(rows), bool(archived))
        return {"rows": merged, "source": source}

    def list_snapshot_sector_rows(
        self,
        dataset_id: str,
        snapshot_id: str | None = None,
        snapshot_type: str | None = None,
        snapshot_types: list[str] | None = None,
        trading_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        entity_type: str | None = None,
        entity_types: list[str] | None = None,
        entity_key: str | None = None,
        entity_keys: list[str] | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "desc",
    ) -> dict[str, Any]:
        if self.session is None:
            return {"rows": [], "source": "sqlite"}
        query = select(SnapshotSectorRowModel).where(SnapshotSectorRowModel.dataset_id == dataset_id)
        types = self._merge_types(snapshot_type, snapshot_types)
        row_entity_types = self._merge_values(entity_type, entity_types)
        row_entity_keys = self._merge_values(entity_key, entity_keys)
        if snapshot_id:
            query = query.where(SnapshotSectorRowModel.snapshot_id == snapshot_id)
        if types:
            query = query.where(SnapshotSectorRowModel.type.in_(types))
        if trading_date:
            query = query.where(SnapshotSectorRowModel.trading_date == trading_date)
        if start_date:
            query = query.where(SnapshotSectorRowModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotSectorRowModel.trading_date <= end_date)
        if before_trading_date:
            query = query.where(SnapshotSectorRowModel.trading_date < before_trading_date)
        if row_entity_types:
            query = query.where(SnapshotSectorRowModel.entity_type.in_(row_entity_types))
        if row_entity_keys:
            query = query.where(SnapshotSectorRowModel.entity_key.in_(row_entity_keys))
        order = SnapshotSectorRowModel.timestamp.asc() if sort == "asc" else SnapshotSectorRowModel.timestamp.desc()
        if limit and limit > 0 and not allowed_capture_modes and not exclude_restored:
            query = query.limit(limit)
        try:
            rows = [self.local_sector_to_bundle_dict(row) for row in self.session.scalars(query.order_by(order, SnapshotSectorRowModel.rank.asc()))]
        except SQLAlchemyError:
            return {"rows": [], "source": "sqlite"}
        if allowed_capture_modes:
            allowed = set(allowed_capture_modes)
            rows = [row for row in rows if str(row.get("captureMode") or "real_time") in allowed]
        if exclude_restored:
            rows = [row for row in rows if str(row.get("captureMode") or "real_time") != "restored"]
        if limit and limit > 0:
            rows = rows[:limit]
        archived = self._archived_sector_rows(
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            snapshot_type=types[0] if len(types) == 1 else snapshot_type,
            trading_date=trading_date,
            entity_type=entity_type,
            entity_key=entity_key,
            sort=sort,
            limit=limit if not rows else None,
        )
        merged = self._merge_archived_rows(rows, archived, limit=limit, sort=sort)
        source = _compute_archive_source(bool(rows), bool(archived))
        return {"rows": merged, "source": source}

    def snapshot_table_counts(self, dataset_id: str | None = None) -> dict[str, int]:
        if self.session is None:
            return {"snapshots": 0, "snapshot_frames": 0, "snapshot_stock_rows": 0, "snapshot_sector_rows": 0}
        filters = {
            "snapshots": SnapshotRecordModel.dataset_id == dataset_id if dataset_id else None,
            "snapshot_frames": SnapshotFrameModel.dataset_id == dataset_id if dataset_id else None,
            "snapshot_stock_rows": SnapshotStockRowModel.dataset_id == dataset_id if dataset_id else None,
            "snapshot_sector_rows": SnapshotSectorRowModel.dataset_id == dataset_id if dataset_id else None,
        }
        models = {
            "snapshots": SnapshotRecordModel,
            "snapshot_frames": SnapshotFrameModel,
            "snapshot_stock_rows": SnapshotStockRowModel,
            "snapshot_sector_rows": SnapshotSectorRowModel,
        }
        counts: dict[str, int] = {}
        try:
            for key, model in models.items():
                query = select(func.count()).select_from(model)
                table_filter = filters[key]
                if table_filter is not None:
                    query = query.where(table_filter)
                counts[key] = int(self.session.scalar(query) or 0)
        except SQLAlchemyError:
            return {"snapshots": 0, "snapshot_frames": 0, "snapshot_stock_rows": 0, "snapshot_sector_rows": 0}
        return counts

    def _archived_stock_rows(self, **filters: Any) -> list[dict[str, Any]]:
        if self.session is None:
            return []
        try:
            from backend.data.archive.service import ArchiveService

            return ArchiveService(self.session).query_archived_stock_rows(**filters)
        except Exception:
            return []

    def _archived_sector_rows(self, **filters: Any) -> list[dict[str, Any]]:
        if self.session is None:
            return []
        try:
            from backend.data.archive.service import ArchiveService

            return ArchiveService(self.session).query_archived_sector_rows(**filters)
        except Exception:
            return []

    @staticmethod
    def _merge_archived_rows(
        sqlite_rows: list[dict[str, Any]],
        archived_rows: list[dict[str, Any]],
        *,
        limit: int | None,
        sort: str,
    ) -> list[dict[str, Any]]:
        if not archived_rows:
            return sqlite_rows
        by_id: dict[str, dict[str, Any]] = {}
        for row in [*sqlite_rows, *archived_rows]:
            key = str(row.get("rowId") or row.get("id") or f"{row.get('snapshotId')}:{row.get('code') or row.get('entityKey')}")
            by_id[key] = row
        rows = list(by_id.values())
        rows.sort(key=lambda row: (int(row.get("timestamp") or 0), int(row.get("rank") or 0)), reverse=sort != "asc")
        if limit and limit > 0:
            return rows[:limit]
        return rows



    def save_backtest_run(self, run: BacktestRun) -> BacktestRun:
        try:
            run.request_json = dumps_json_field(run.request_json or "{}")
            run.result_json = dumps_json_field(run.result_json or "{}")
            managed = self.research_session.merge(run)
            self.research_session.commit()
        except SQLAlchemyError:
            self.research_session.rollback()
            raise RuntimeError("research database write failed") from None
        return self.research_session.get(BacktestRun, managed.id) or run

    def get_backtest_run(self, run_id: str) -> BacktestRun | None:
        try:
            return self.research_session.get(BacktestRun, run_id)
        except SQLAlchemyError:
            return None

    # ── 归一化结果存取 ─────────────────────────────

    def save_backtest_trades(self, run_id: str, trades: list[dict[str, Any]]) -> int:
        count = 0
        try:
            for t in trades:
                row = BacktestTrade(
                    backtest_run_id=run_id,
                    code=str(t.get("code") or ""),
                    name=str(t.get("name") or ""),
                    side=str(t.get("side") or t.get("action") or "buy"),
                    entry_snapshot_id=str(t.get("entrySnapshotId") or "") or None,
                    exit_snapshot_id=str(t.get("exitSnapshotId") or "") or None,
                    entry_time=int(t.get("entryTime") or 0) or None,
                    exit_time=int(t.get("exitTime") or 0) or None,
                    entry_trading_date=str(t.get("entryTradingDate") or "") or None,
                    exit_trading_date=str(t.get("exitTradingDate") or "") or None,
                    entry_price=float(t.get("entryPrice")) if t.get("entryPrice") is not None else None,
                    exit_price=float(t.get("exitPrice")) if t.get("exitPrice") is not None else None,
                    quantity=int(t.get("quantity") or 0),
                    gross_return=float(t.get("grossReturn")) if t.get("grossReturn") is not None else None,
                    net_return=float(t.get("netReturn")) if t.get("netReturn") is not None else None,
                    profit=float(t.get("profit")) if t.get("profit") is not None else None,
                    holding_bars=int(t.get("holdingBars") or 0),
                    reason=str(t.get("reason") or "") or None,
                    candidate_tier=str(t.get("candidateTier") or "") or None,
                    stage=str(t.get("stage") or "") or None,
                    regime=str(t.get("regime") or "") or None,
                    explanation=str(t.get("explanation") or "") or None,
                    fill_detail_json=dumps_json_field(t.get("fill") or {}),
                )
                self.research_session.add(row)
                count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to save normalized backtest trades") from exc
        return count

    def get_backtest_trades(self, run_id: str, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        try:
            query = select(BacktestTrade).where(BacktestTrade.backtest_run_id == run_id).order_by(BacktestTrade.id)
            if offset:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
            rows = self.research_session.scalars(query).all()
            return [self._trade_to_dict(r) for r in rows]
        except SQLAlchemyError:
            return []

    def count_backtest_trades(self, run_id: str) -> int:
        try:
            return int(
                self.research_session.scalar(
                    select(func.count()).select_from(BacktestTrade).where(BacktestTrade.backtest_run_id == run_id)
                )
                or 0
            )
        except SQLAlchemyError:
            return 0

    def save_backtest_equity_curve(self, run_id: str, curve: list[dict[str, Any]]) -> int:
        count = 0
        try:
            for pt in curve:
                row = BacktestEquityCurve(
                    backtest_run_id=run_id,
                    snapshot_id=str(pt.get("snapshotId") or "") or None,
                    timestamp=int(pt.get("timestamp") or 0) or None,
                    trading_date=str(pt.get("tradingDate") or "") or None,
                    equity=float(pt.get("equity")) if pt.get("equity") is not None else None,
                    cash=float(pt.get("cash")) if pt.get("cash") is not None else None,
                    market_value=float(pt.get("marketValue")) if pt.get("marketValue") is not None else None,
                    position_count=int(pt.get("positionCount") or 0),
                )
                self.research_session.add(row)
                count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to save normalized backtest equity curve") from exc
        return count

    def save_backtest_equity_rows(self, run_id: str, rows: list[dict[str, Any]]) -> int:
        count = 0
        try:
            for pt in rows:
                self.research_session.add(
                    BacktestEquityCurve(
                        backtest_run_id=run_id,
                        snapshot_id=str(pt.get("snapshotId") or "") or None,
                        timestamp=int(pt.get("timestamp") or 0) or None,
                        trading_date=str(pt.get("tradingDate") or "") or None,
                        equity=float(pt.get("equity")) if pt.get("equity") is not None else None,
                        cash=float(pt.get("cash")) if pt.get("cash") is not None else None,
                        market_value=float(pt.get("marketValue")) if pt.get("marketValue") is not None else None,
                        position_count=int(pt.get("positionCount") or 0),
                    )
                )
                count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to restore normalized backtest equity curve") from exc
        return count

    def get_backtest_equity_curve(self, run_id: str) -> list[dict[str, Any]]:
        try:
            rows = self.research_session.scalars(
                select(BacktestEquityCurve).where(BacktestEquityCurve.backtest_run_id == run_id).order_by(BacktestEquityCurve.id)
            ).all()
            return [self._equity_to_dict(r) for r in rows]
        except SQLAlchemyError:
            return []

    def save_backtest_signals(self, run_id: str, strategy_decisions: dict[str, Any]) -> int:
        count = 0
        try:
            for fr in strategy_decisions.get("frameResults") or []:
                snapshot_id = str(fr.get("snapshotId") or "")
                trading_date = str(fr.get("tradingDate") or "")
                for d in fr.get("buyCandidates") or []:
                    row = self._signal_from_decision(run_id, snapshot_id, trading_date, d)
                    self.research_session.add(row)
                    count += 1
                for d in fr.get("watchCandidates") or []:
                    row = self._signal_from_decision(run_id, snapshot_id, trading_date, d)
                    self.research_session.add(row)
                    count += 1
                for d in fr.get("excludedCandidates") or []:
                    row = self._signal_from_decision(run_id, snapshot_id, trading_date, d)
                    self.research_session.add(row)
                    count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to save normalized backtest signals") from exc
        return count

    def save_backtest_signal_rows(self, run_id: str, rows: list[dict[str, Any]]) -> int:
        count = 0
        try:
            for item in rows:
                self.research_session.add(
                    BacktestSignal(
                        backtest_run_id=run_id,
                        snapshot_id=str(item.get("snapshotId") or "") or None,
                        trading_date=str(item.get("tradingDate") or "") or None,
                        code=str(item.get("code") or ""),
                        name=str(item.get("name") or ""),
                        candidate_tier=str(item.get("candidateTier") or "") or None,
                        signal=str(item.get("signal") or "") or None,
                        confidence=float(item.get("confidence")) if item.get("confidence") is not None else None,
                        rank=int(item.get("rank")) if item.get("rank") is not None else None,
                        stage=str(item.get("stage") or "") or None,
                        regime=str(item.get("regime") or "") or None,
                        reasons_json=dumps_json_field(item.get("reasons") or []),
                        risk_flags_json=dumps_json_field(item.get("riskFlags") or []),
                    )
                )
                count += 1
            self.research_session.commit()
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to restore normalized backtest signals") from exc
        return count

    @staticmethod
    def _signal_from_decision(run_id: str, snapshot_id: str, trading_date: str, d: dict[str, Any]) -> BacktestSignal:
        return BacktestSignal(
            backtest_run_id=run_id,
            snapshot_id=snapshot_id or None,
            trading_date=trading_date or None,
            code=str(d.get("code") or ""),
            name=str(d.get("name") or ""),
            candidate_tier=str(d.get("candidateTier") or "") or None,
            signal=str(d.get("signal") or "") or None,
            confidence=float(d.get("confidence")) if d.get("confidence") is not None else None,
            rank=int(d.get("rank")) if d.get("rank") is not None else None,
            stage=str(d.get("stage") or "") or None,
            regime=str(d.get("regime") or "") or None,
            reasons_json=dumps_json_field(d.get("reasons") or []),
            risk_flags_json=dumps_json_field(d.get("riskFlags") or []),
        )

    def get_backtest_signals(
        self,
        run_id: str,
        limit: int | None = None,
        offset: int = 0,
        tier: str | None = None,
        regime: str | None = None,
    ) -> list[dict[str, Any]]:
        try:
            query = self._backtest_signal_query(run_id, tier=tier, regime=regime).order_by(BacktestSignal.id)
            if offset:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)
            rows = self.research_session.scalars(query).all()
            return [self._signal_to_dict(r) for r in rows]
        except SQLAlchemyError:
            return []

    def count_backtest_signals(self, run_id: str, tier: str | None = None, regime: str | None = None) -> int:
        try:
            return int(
                self.research_session.scalar(
                    select(func.count()).select_from(
                        self._backtest_signal_query(run_id, tier=tier, regime=regime).subquery()
                    )
                )
                or 0
            )
        except SQLAlchemyError:
            return 0

    @staticmethod
    def _backtest_signal_query(run_id: str, tier: str | None = None, regime: str | None = None):
        query = select(BacktestSignal).where(BacktestSignal.backtest_run_id == run_id)
        if tier:
            query = query.where(BacktestSignal.candidate_tier == tier)
        if regime:
            query = query.where(BacktestSignal.regime == regime)
        return query

    def save_backtest_quality_report(self, run_id: str, data_quality: dict[str, Any], quality_gate: dict[str, Any] | None = None) -> bool:
        try:
            gate = quality_gate if isinstance(quality_gate, dict) else {}
            stats = gate.get("stats") if isinstance(gate.get("stats"), dict) else {}
            row = BacktestQualityReport(
                backtest_run_id=run_id,
                passed=bool(data_quality.get("severity") == "pass"),
                severity=str(data_quality.get("severity") or "pass"),
                research_grade=str(data_quality.get("researchGrade") or "research_ready"),
                frame_count=int(data_quality.get("snapshotCount") or 0),
                stock_count=int(gate.get("stockCount") or 0),
                sector_count=int(gate.get("sectorCount") or 0),
                missing_fields_json=dumps_json_field(stats.get("missingFields") or {}),
                nan_counts_json=dumps_json_field(stats.get("nanCounts") or {}),
                inf_counts_json=dumps_json_field(stats.get("infCounts") or {}),
                negative_price_count=int(stats.get("negativePriceCount") or 0),
                non_positive_price_count=int(stats.get("nonPositivePriceCount") or 0),
                negative_volume_count=int(stats.get("negativeVolumeCount") or 0),
                coverage_ratio=float(stats.get("coverageRatio")) if stats.get("coverageRatio") is not None else None,
                time_order_fixed=bool(gate.get("timeOrderFixed") or False),
                time_order_fix_count=int(gate.get("timeOrderFixCount") or 0),
                warnings_json=dumps_json_field(data_quality.get("warnings") or []),
            )
            self.research_session.add(row)
            self.research_session.commit()
            return True
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to save normalized backtest quality report") from exc

    def get_backtest_quality_report(self, run_id: str) -> dict[str, Any] | None:
        try:
            row = self.research_session.scalar(
                select(BacktestQualityReport).where(BacktestQualityReport.backtest_run_id == run_id).limit(1)
            )
            return self._quality_to_dict(row) if row else None
        except SQLAlchemyError:
            return None

    # ── research SQLite 维护 ───────────────────────

    def research_storage_summary(self) -> dict[str, Any]:
        tables = {
            "backtest_runs": BacktestRun,
            "backtest_trades": BacktestTrade,
            "backtest_equity_curve": BacktestEquityCurve,
            "backtest_signals": BacktestSignal,
            "backtest_quality_reports": BacktestQualityReport,
            "optimization_runs": OptimizationRun,
            "golden_ranktrend_cases": GoldenRankTrendCase,
        }
        try:
            counts = {
                name: int(self.research_session.scalar(select(func.count()).select_from(model)) or 0)
                for name, model in tables.items()
            }
            oldest = self.research_session.scalar(select(func.min(BacktestRun.created_at)))
            newest = self.research_session.scalar(select(func.max(BacktestRun.created_at)))
            return {
                "ok": True,
                "tables": counts,
                "backtestCreatedAt": {
                    "oldest": oldest.isoformat() if oldest else None,
                    "newest": newest.isoformat() if newest else None,
                },
            }
        except SQLAlchemyError as exc:
            return {"ok": False, "error": str(exc), "tables": {}}

    def delete_backtest_run(self, run_id: str, *, checkpoint: bool = False) -> dict[str, Any] | None:
        if not self.get_backtest_run(run_id):
            return None
        try:
            deleted: dict[str, int] = {}
            child_specs = [
                ("backtest_trades", BacktestTrade),
                ("backtest_equity_curve", BacktestEquityCurve),
                ("backtest_signals", BacktestSignal),
                ("backtest_quality_reports", BacktestQualityReport),
            ]
            for name, model in child_specs:
                result = self.research_session.execute(delete(model).where(model.backtest_run_id == run_id))
                deleted[name] = int(result.rowcount or 0)
            result = self.research_session.execute(delete(BacktestRun).where(BacktestRun.id == run_id))
            deleted["backtest_runs"] = int(result.rowcount or 0)
            self.research_session.commit()
            if checkpoint:
                self._checkpoint_research_sqlite()
            return {"ok": True, "runId": run_id, "deleted": deleted}
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to delete backtest run") from exc

    def cleanup_research_backtests(
        self,
        *,
        older_than_days: int = 30,
        keep_latest_per_group: int = 10,
        dataset_id: str | None = None,
        snapshot_type: str | None = None,
        include_failed: bool = False,
        apply: bool = False,
        checkpoint: bool = False,
    ) -> dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=max(0, older_than_days))
        try:
            query = select(BacktestRun).where(BacktestRun.created_at < cutoff)
            if dataset_id:
                query = query.where(BacktestRun.dataset_id == dataset_id)
            if snapshot_type:
                query = query.where(BacktestRun.snapshot_type == snapshot_type)
            if not include_failed:
                query = query.where(BacktestRun.status == "completed")
            rows = list(self.research_session.scalars(query).all())
            protected = self._protected_backtest_run_ids(keep_latest_per_group, dataset_id=dataset_id, snapshot_type=snapshot_type)
            candidates = [row for row in rows if row.id not in protected]
            run_ids = [row.id for row in candidates]
            counts = self._backtest_delete_counts(run_ids)
            result: dict[str, Any] = {
                "ok": True,
                "apply": bool(apply),
                "cutoff": cutoff.isoformat(),
                "matchedBacktestRuns": len(run_ids),
                "deleteCounts": counts,
                "protectedRuns": sorted(protected),
                "runs": [self.backtest_run_to_dict(row) for row in candidates[:200]],
                "truncated": len(candidates) > 200,
            }
            if apply and run_ids:
                deleted = self._delete_backtest_runs(run_ids)
                if checkpoint:
                    self._checkpoint_research_sqlite()
                result["deleted"] = deleted
            elif apply:
                result["deleted"] = {key: 0 for key in counts}
            return result
        except SQLAlchemyError as exc:
            self.research_session.rollback()
            raise RuntimeError("failed to cleanup research backtests") from exc

    def _protected_backtest_run_ids(
        self,
        keep_latest_per_group: int,
        *,
        dataset_id: str | None = None,
        snapshot_type: str | None = None,
    ) -> set[str]:
        if keep_latest_per_group <= 0:
            return set()
        query = select(BacktestRun).order_by(BacktestRun.created_at.desc())
        if dataset_id:
            query = query.where(BacktestRun.dataset_id == dataset_id)
        if snapshot_type:
            query = query.where(BacktestRun.snapshot_type == snapshot_type)
        grouped: dict[tuple[Any, ...], list[str]] = defaultdict(list)
        for row in self.research_session.scalars(query):
            key = (
                row.dataset_id,
                row.strategy_name,
                row.strategy_version,
                row.snapshot_type,
                row.config_hash,
                row.random_seed,
            )
            if len(grouped[key]) < keep_latest_per_group:
                grouped[key].append(row.id)
        protected: set[str] = set()
        for ids in grouped.values():
            protected.update(ids)
        return protected

    def _backtest_delete_counts(self, run_ids: list[str]) -> dict[str, int]:
        if not run_ids:
            return {
                "backtest_runs": 0,
                "backtest_trades": 0,
                "backtest_equity_curve": 0,
                "backtest_signals": 0,
                "backtest_quality_reports": 0,
            }
        specs = [
            ("backtest_runs", BacktestRun, BacktestRun.id),
            ("backtest_trades", BacktestTrade, BacktestTrade.backtest_run_id),
            ("backtest_equity_curve", BacktestEquityCurve, BacktestEquityCurve.backtest_run_id),
            ("backtest_signals", BacktestSignal, BacktestSignal.backtest_run_id),
            ("backtest_quality_reports", BacktestQualityReport, BacktestQualityReport.backtest_run_id),
        ]
        return {
            name: int(self.research_session.scalar(select(func.count()).select_from(model).where(column.in_(run_ids))) or 0)
            for name, model, column in specs
        }

    def _delete_backtest_runs(self, run_ids: list[str]) -> dict[str, int]:
        if not run_ids:
            return self._backtest_delete_counts([])
        deleted: dict[str, int] = {}
        for name, model in [
            ("backtest_trades", BacktestTrade),
            ("backtest_equity_curve", BacktestEquityCurve),
            ("backtest_signals", BacktestSignal),
            ("backtest_quality_reports", BacktestQualityReport),
        ]:
            result = self.research_session.execute(delete(model).where(model.backtest_run_id.in_(run_ids)))
            deleted[name] = int(result.rowcount or 0)
        result = self.research_session.execute(delete(BacktestRun).where(BacktestRun.id.in_(run_ids)))
        deleted["backtest_runs"] = int(result.rowcount or 0)
        self.research_session.commit()
        return deleted

    def _checkpoint_research_sqlite(self) -> None:
        bind = self.research_session.get_bind()
        if bind and bind.dialect.name == "sqlite":
            self.research_session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            self.research_session.commit()

    def vacuum_research_sqlite(self) -> dict[str, Any]:
        bind = self.research_session.get_bind()
        if not bind or bind.dialect.name != "sqlite":
            return {"ok": False, "skipped": True, "reason": "research database is not sqlite"}
        self.research_session.rollback()
        with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))
        return {"ok": True, "vacuum": True}

    # ── 序列化 ─────────────────────────────────────

    @staticmethod
    def _trade_to_dict(model: BacktestTrade) -> dict[str, Any]:
        return {
            "id": model.id,
            "backtestRunId": model.backtest_run_id,
            "code": model.code,
            "name": model.name,
            "side": model.side,
            "entrySnapshotId": model.entry_snapshot_id,
            "exitSnapshotId": model.exit_snapshot_id,
            "entryTime": model.entry_time,
            "exitTime": model.exit_time,
            "entryTradingDate": model.entry_trading_date,
            "exitTradingDate": model.exit_trading_date,
            "entryPrice": model.entry_price,
            "exitPrice": model.exit_price,
            "quantity": model.quantity,
            "grossReturn": model.gross_return,
            "netReturn": model.net_return,
            "profit": model.profit,
            "holdingBars": model.holding_bars,
            "reason": model.reason,
            "candidateTier": model.candidate_tier,
            "stage": model.stage,
            "regime": model.regime,
            "explanation": model.explanation,
            "fillDetail": loads_json_field(model.fill_detail_json, {}),
        }

    @staticmethod
    def _equity_to_dict(model: BacktestEquityCurve) -> dict[str, Any]:
        return {
            "id": model.id,
            "backtestRunId": model.backtest_run_id,
            "snapshotId": model.snapshot_id,
            "timestamp": model.timestamp,
            "tradingDate": model.trading_date,
            "equity": model.equity,
            "cash": model.cash,
            "marketValue": model.market_value,
            "positionCount": model.position_count,
        }

    @staticmethod
    def _signal_to_dict(model: BacktestSignal) -> dict[str, Any]:
        return {
            "id": model.id,
            "backtestRunId": model.backtest_run_id,
            "snapshotId": model.snapshot_id,
            "tradingDate": model.trading_date,
            "code": model.code,
            "name": model.name,
            "candidateTier": model.candidate_tier,
            "signal": model.signal,
            "confidence": model.confidence,
            "rank": model.rank,
            "stage": model.stage,
            "regime": model.regime,
            "reasons": loads_json_field(model.reasons_json, []),
            "riskFlags": loads_json_field(model.risk_flags_json, []),
        }

    @staticmethod
    def _quality_to_dict(model: BacktestQualityReport) -> dict[str, Any]:
        return {
            "id": model.id,
            "backtestRunId": model.backtest_run_id,
            "passed": model.passed,
            "severity": model.severity,
            "researchGrade": model.research_grade,
            "frameCount": model.frame_count,
            "stockCount": model.stock_count,
            "sectorCount": model.sector_count,
            "missingFields": loads_json_field(model.missing_fields_json, {}),
            "nanCounts": loads_json_field(model.nan_counts_json, {}),
            "infCounts": loads_json_field(model.inf_counts_json, {}),
            "negativePriceCount": model.negative_price_count,
            "nonPositivePriceCount": model.non_positive_price_count,
            "negativeVolumeCount": model.negative_volume_count,
            "coverageRatio": model.coverage_ratio,
            "timeOrderFixed": model.time_order_fixed,
            "timeOrderFixCount": model.time_order_fix_count,
            "warnings": loads_json_field(model.warnings_json, []),
        }

    def save_optimization_run(self, run: OptimizationRun) -> OptimizationRun:
        try:
            run.request_json = dumps_json_field(run.request_json or "{}")
            run.result_json = dumps_json_field(run.result_json or "{}")
            managed = self.research_session.merge(run)
            self.research_session.commit()
        except SQLAlchemyError:
            self.research_session.rollback()
            raise RuntimeError("research database write failed") from None
        return self.research_session.get(OptimizationRun, managed.id) or run

    def get_optimization_run(self, run_id: str) -> OptimizationRun | None:
        try:
            return self.research_session.get(OptimizationRun, run_id)
        except SQLAlchemyError:
            return None

    def save_golden_case(self, case: GoldenRankTrendCase) -> GoldenRankTrendCase:
        try:
            case.input_json = dumps_json_field(case.input_json or "{}")
            case.expected_json = dumps_json_field(case.expected_json or "{}")
            managed = self.research_session.merge(case)
            self.research_session.commit()
        except SQLAlchemyError:
            self.research_session.rollback()
            raise RuntimeError("research database write failed") from None
        return self.research_session.get(GoldenRankTrendCase, managed.id) or case

    def get_golden_case(self, case_id: str) -> GoldenRankTrendCase | None:
        try:
            return self.research_session.get(GoldenRankTrendCase, case_id)
        except SQLAlchemyError:
            return None

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

    def load_dataset_bundle_slice(
        self,
        dataset_id: str,
        *,
        snapshot_types: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        max_snapshots: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if self.session is None:
            return [], [], [], []

        query = select(SnapshotFrameModel).where(SnapshotFrameModel.dataset_id == dataset_id)
        if snapshot_types:
            query = query.where(SnapshotFrameModel.type.in_(snapshot_types))
        if start_date:
            query = query.where(SnapshotFrameModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotFrameModel.trading_date <= end_date)
        query = query.order_by(SnapshotFrameModel.timestamp.asc(), SnapshotFrameModel.snapshot_id.asc())
        if max_snapshots and max_snapshots > 0:
            query = query.limit(max_snapshots)

        try:
            frame_models = list(self.session.scalars(query))
        except SQLAlchemyError:
            return [], [], [], []

        snapshot_ids = [frame.snapshot_id for frame in frame_models if frame.snapshot_id]
        if not snapshot_ids:
            return [], [], [], []

        try:
            records = [
                self.record_to_dict(row)
                for row in self.session.scalars(
                    select(SnapshotRecordModel)
                    .where(
                        SnapshotRecordModel.dataset_id == dataset_id,
                        SnapshotRecordModel.snapshot_id.in_(snapshot_ids),
                    )
                    .order_by(SnapshotRecordModel.timestamp.asc(), SnapshotRecordModel.snapshot_id.asc())
                )
            ]
            frames = [self.local_frame_to_bundle_dict(row) for row in frame_models]
            stock_rows = [
                self.local_stock_to_bundle_dict(row)
                for row in self.session.scalars(
                    select(SnapshotStockRowModel)
                    .where(
                        SnapshotStockRowModel.dataset_id == dataset_id,
                        SnapshotStockRowModel.snapshot_id.in_(snapshot_ids),
                    )
                    .order_by(
                        SnapshotStockRowModel.timestamp.asc(),
                        SnapshotStockRowModel.rank.asc(),
                        SnapshotStockRowModel.code.asc(),
                    )
                )
            ]
            sector_rows = [
                self.local_sector_to_bundle_dict(row)
                for row in self.session.scalars(
                    select(SnapshotSectorRowModel)
                    .where(
                        SnapshotSectorRowModel.dataset_id == dataset_id,
                        SnapshotSectorRowModel.snapshot_id.in_(snapshot_ids),
                    )
                    .order_by(
                        SnapshotSectorRowModel.timestamp.asc(),
                        SnapshotSectorRowModel.rank.asc(),
                        SnapshotSectorRowModel.entity_type.asc(),
                        SnapshotSectorRowModel.entity_key.asc(),
                    )
                )
            ]
        except SQLAlchemyError:
            return [], [], [], []

        return records, frames, stock_rows, sector_rows

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
            "snapshot_types": loads_json_field(model.snapshot_types_json, []),
            "metadata": loads_json_field(model.metadata_json, {}),
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
            "dateStart": model.date_start,
            "dateEnd": model.date_end,
            "errorReason": model.error_reason,
            "request_json": model.request_json,
            "result_json": model.result_json,
            "request": loads_json_field(model.request_json, {}),
            "result": loads_json_field(model.result_json, {}),
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "finished_at": model.finished_at.isoformat() if model.finished_at else None,
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
            "request": loads_json_field(model.request_json, {}),
            "result": loads_json_field(model.result_json, {}),
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
            "input": loads_json_field(model.input_json, {}),
            "expected": loads_json_field(model.expected_json, {}),
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }

    @staticmethod
    def record_to_dict(model: SnapshotRecordModel) -> dict[str, Any]:
        return {
            "id": model.snapshot_id,
            "snapshotId": model.snapshot_id,
            "type": model.type,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "timestamp": model.timestamp,
            "displayKey": model.display_key,
            "captureMode": model.capture_mode,
            "capturedAt": model.captured_at or model.timestamp,
            "dataTimestamp": model.data_timestamp or model.timestamp,
            "delayMs": model.delay_ms or 0,
            "qualityFlags": json_loads(model.quality_flags_json, []),
            "source": model.source,
            "payload": {},
        }

    @staticmethod
    def frame_to_dict(model: SnapshotFrameModel) -> dict[str, Any]:
        context = Repository._frame_context(model)
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
        context = Repository._frame_context(model)
        return {
            "id": model.snapshot_id,
            "snapshotId": model.snapshot_id,
            "timestamp": model.timestamp,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "type": model.type,
            "displayKey": model.display_key or model.snapshot_id,
            "captureMode": model.capture_mode,
            "source": model.source,
            "qualityFlags": json_loads(model.quality_flags_json, []),
            "delayMs": model.delay_ms or 0,
            "marketStats": context.get("marketStats"),
            "sentiment": context.get("sentiment"),
            "moneyFlow": context.get("moneyFlow"),
            "indices": context.get("indices"),
            "limitSummary": context.get("limitSummary"),
            "rotationSummary": context.get("rotationSummary"),
            "stockRowCount": model.stock_row_count,
            "sectorRowCount": model.sector_row_count,
        }

    @staticmethod
    def stock_row_to_dict(model: SnapshotStockRowModel, include_payload: bool = True) -> dict[str, Any]:
        return Repository.local_stock_to_bundle_dict(model)

    @staticmethod
    def local_stock_to_bundle_dict(model: SnapshotStockRowModel) -> dict[str, Any]:
        item = {
            "id": model.row_id,
            "rowId": model.row_id,
            "snapshotId": model.snapshot_id,
            "type": model.type,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "timestamp": model.timestamp,
            "captureMode": model.capture_mode,
            "source": model.source,
            "code": model.code,
            "name": model.name,
            "rank": model.rank,
            "compRank": model.comp_rank,
            "platforms": model.platforms,
            "avgRank": model.avg_rank,
            "avgRankNum": model.avg_rank_num,
            "price": model.price,
            "change": model.change,
            "volume": model.volume,
            "turnover": model.turnover,
            "turnoverRate": model.turnover_rate,
            "totalMV": model.total_mv,
            "cirMV": model.cir_mv,
            "volumeRatio": model.volume_ratio,
            "zlje": model.zlje,
            "zljzb": model.zljzb,
            "cddje": model.cddje,
            "cddjzb": model.cddjzb,
            "pe": model.pe,
            "pb": model.pb,
            "depth10": json_loads(model.depth10_json, {}),
            "bid1Price": model.bid1_price,
            "bid1Volume": model.bid1_volume,
            "ask1Price": model.ask1_price,
            "ask1Volume": model.ask1_volume,
            "spread": model.spread,
            "bid10Total": model.bid10_total,
            "ask10Total": model.ask10_total,
            "depthImbalance": model.depth_imbalance,
            "tickBuyVolume": model.tick_buy_volume,
            "tickSellVolume": model.tick_sell_volume,
            "tickBuyCount": model.tick_buy_count,
            "tickSellCount": model.tick_sell_count,
            "lastTradePrice": model.last_trade_price,
            "lastTradeVolume": model.last_trade_volume,
            "speed": model.speed,
            "leadStatus": model.lead_status,
            "leadTimes": model.lead_times,
            "lianbanStr": model.lianban_str,
            "fengdan": model.fengdan,
            "maxFengdan": model.max_fengdan,
            "popularity": model.popularity,
            "popularityChange": model.popularity_change,
            "institutionBuy": model.institution_buy,
            "bigMoney300": model.big_money300,
            "themes": json_loads(model.themes_json, []),
            "isNew": bool(model.is_new),
            "firstZtTime": model.first_zt_time,
            "lastZtTime": model.last_zt_time,
            "boardHeight": model.board_height,
            "highDays": model.high_days,
            "hotness": model.hotness,
            "mainTheme": model.main_theme,
            "themeHeat": model.theme_heat,
            "themeLevel": model.theme_level,
            "rankChange": model.rank_change,
            "directionSignal": model.direction_signal,
            "directionConfidence": model.direction_confidence,
            "accelerationSignal": model.acceleration_signal,
            "accelerationConfidence": model.acceleration_confidence,
            "crossSignal": model.cross_signal,
            "crossConfidence": model.cross_confidence,
            "finalSignal": model.final_signal,
            "finalConfidence": model.final_confidence,
        }
        return {key: value for key, value in item.items() if value is not None}

    @staticmethod
    def local_sector_to_bundle_dict(model: SnapshotSectorRowModel) -> dict[str, Any]:
        item = {
            "id": model.row_id,
            "rowId": model.row_id,
            "snapshotId": model.snapshot_id,
            "type": model.type,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "timestamp": model.timestamp,
            "captureMode": model.capture_mode,
            "source": model.source,
            "entityType": model.entity_type,
            "entityKey": model.entity_key,
            "entityCode": model.entity_code,
            "entityName": model.entity_name,
            "rank": model.rank,
            "strength": model.strength,
            "heatScore": model.heat_score,
            "heatLevel": model.heat_level,
            "change": model.change,
            "mainNetInflow": model.main_net_inflow,
            "bigMoney300": model.big_money300,
            "institutionBuy": model.institution_buy,
            "volumeRatio": model.volume_ratio,
            "ztCount": model.zt_count,
            "leaderCount": model.leader_count,
            "persistentDays": model.persistent_days,
            "netInflow": model.net_inflow,
            "metadata": json_loads(model.metadata_json, {}),
        }
        return {key: value for key, value in item.items() if value is not None}

    @staticmethod
    def _frame_context(model: SnapshotFrameModel) -> dict[str, Any]:
        return {
            "metadata": json_loads(model.metadata_json, {}),
            "marketStats": json_loads(model.market_stats_json, {}),
            "sentiment": json_loads(model.sentiment_json, {}),
            "moneyFlow": json_loads(model.money_flow_json, {}),
            "indices": json_loads(model.indices_json, {}),
            "limitSummary": json_loads(model.limit_summary_json, {}),
            "rotationSummary": json_loads(model.rotation_summary_json, {}),
        }

    @staticmethod
    def _sector_entity_to_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "id": row.get("entityKey") or row.get("rowId") or row.get("id"),
            "code": row.get("entityCode") or row.get("entityKey"),
            "name": row.get("entityName"),
            "themeName": row.get("entityName"),
        }

    @staticmethod
    def _merge_types(value: str | None, values: list[str] | None) -> list[str]:
        return Repository._merge_values(value, values)

    @staticmethod
    def _merge_values(value: str | None, values: list[str] | None) -> list[str]:
        output: list[str] = []
        if value:
            output.append(str(value))
        output.extend(str(item) for item in values or [] if item)
        return list(dict.fromkeys(output))

    @staticmethod
    def _record_model(dataset_id: str, item: dict[str, Any]) -> SnapshotRecordModel:
        timestamp = int(item.get("timestamp") or 0)
        return SnapshotRecordModel(
            dataset_id=dataset_id,
            snapshot_id=str(item.get("id") or item.get("snapshotId")),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=timestamp,
            display_key=str(item.get("displayKey") or ""),
            capture_mode=str(item.get("captureMode") or "real_time"),
            captured_at=int(item.get("capturedAt") or timestamp),
            data_timestamp=int(item.get("dataTimestamp") or timestamp),
            delay_ms=int(item.get("delayMs") or 0),
            quality_flags_json=json_dumps(item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else []),
            source=str(item.get("source") or "browser_runtime"),
        )

    @staticmethod
    def _frame_model(dataset_id: str, item: dict[str, Any]) -> SnapshotFrameModel:
        return SnapshotFrameModel(
            dataset_id=dataset_id,
            snapshot_id=str(item.get("snapshotId") or item.get("id")),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            display_key=str(item.get("displayKey") or item.get("snapshotId") or item.get("id") or ""),
            capture_mode=str(item.get("captureMode") or "real_time"),
            quality_flags_json=json_dumps(item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else []),
            delay_ms=int(item.get("delayMs") or 0),
            source=str(item.get("source") or "browser_runtime"),
            metadata_json=json_dumps(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
            market_stats_json=json_dumps(item.get("marketStats") if isinstance(item.get("marketStats"), dict) else {}),
            sentiment_json=json_dumps(item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {}),
            money_flow_json=json_dumps(item.get("moneyFlow") if isinstance(item.get("moneyFlow"), dict) else {}),
            indices_json=json_dumps(item.get("indices") if isinstance(item.get("indices"), dict) else {}),
            limit_summary_json=json_dumps(item.get("limitSummary") if isinstance(item.get("limitSummary"), dict) else {}),
            rotation_summary_json=json_dumps(item.get("rotationSummary") if isinstance(item.get("rotationSummary"), dict) else {}),
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
            source=str(item.get("source") or "browser_runtime"),
            code=str(item.get("code") or ""),
            name=str(item.get("name") or item.get("code") or ""),
            rank=int(float(item.get("rank") or item.get("compRank") or 0)),
            comp_rank=int(float(item.get("compRank") or item.get("rank") or 0)),
            platforms=int(float(item.get("platforms") or 0)),
            avg_rank=item.get("avgRank"),
            avg_rank_num=_maybe_float(item.get("avgRankNum")),
            price=_maybe_float(item.get("price")),
            change=_maybe_float(item.get("change")),
            volume=_maybe_float(item.get("volume")),
            turnover=_maybe_float(item.get("turnover")),
            turnover_rate=_maybe_float(item.get("turnoverRate")),
            total_mv=_maybe_float(item.get("totalMV")),
            cir_mv=_maybe_float(item.get("cirMV")),
            volume_ratio=_maybe_float(item.get("volumeRatio")),
            zlje=_maybe_float(item.get("zlje")),
            zljzb=_maybe_float(item.get("zljzb")),
            cddje=_maybe_float(item.get("cddje")),
            cddjzb=_maybe_float(item.get("cddjzb")),
            pe=_maybe_float(item.get("pe")),
            pb=_maybe_float(item.get("pb")),
            depth10_json=json_dumps(item.get("depth10") if isinstance(item.get("depth10"), dict) else {}),
            bid1_price=_maybe_float(item.get("bid1Price")),
            bid1_volume=_maybe_float(item.get("bid1Volume")),
            ask1_price=_maybe_float(item.get("ask1Price")),
            ask1_volume=_maybe_float(item.get("ask1Volume")),
            spread=_maybe_float(item.get("spread")),
            bid10_total=_maybe_float(item.get("bid10Total")),
            ask10_total=_maybe_float(item.get("ask10Total")),
            depth_imbalance=_maybe_float(item.get("depthImbalance")),
            tick_buy_volume=_maybe_float(item.get("tickBuyVolume")),
            tick_sell_volume=_maybe_float(item.get("tickSellVolume")),
            tick_buy_count=_maybe_int(item.get("tickBuyCount")),
            tick_sell_count=_maybe_int(item.get("tickSellCount")),
            last_trade_price=_maybe_float(item.get("lastTradePrice")),
            last_trade_volume=_maybe_float(item.get("lastTradeVolume")),
            speed=_maybe_float(item.get("speed")),
            lead_status=item.get("leadStatus"),
            lead_times=_maybe_int(item.get("leadTimes")),
            lianban_str=item.get("lianbanStr"),
            fengdan=_maybe_float(item.get("fengdan")),
            max_fengdan=_maybe_float(item.get("maxFengdan")),
            popularity=_maybe_float(item.get("popularity")),
            popularity_change=_maybe_float(item.get("popularityChange")),
            institution_buy=_maybe_float(item.get("institutionBuy")),
            big_money300=_maybe_float(item.get("bigMoney300")),
            themes_json=json_dumps(item.get("themes") if isinstance(item.get("themes"), list) else []),
            is_new=bool(item.get("isNew")) if item.get("isNew") is not None else False,
            first_zt_time=item.get("firstZtTime"),
            last_zt_time=item.get("lastZtTime"),
            board_height=_maybe_int(item.get("boardHeight")),
            high_days=_maybe_int(item.get("highDays")),
            hotness=_maybe_float(item.get("hotness")),
            main_theme=item.get("mainTheme"),
            theme_heat=_maybe_float(item.get("themeHeat")),
            theme_level=item.get("themeLevel"),
            rank_change=_maybe_float(item.get("rankChange")),
            direction_signal=item.get("directionSignal"),
            direction_confidence=_maybe_float(item.get("directionConfidence")),
            acceleration_signal=item.get("accelerationSignal"),
            acceleration_confidence=_maybe_float(item.get("accelerationConfidence")),
            cross_signal=item.get("crossSignal"),
            cross_confidence=_maybe_float(item.get("crossConfidence")),
            final_signal=item.get("finalSignal"),
            final_confidence=_maybe_float(item.get("finalConfidence")),
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
            capture_mode=str(item.get("captureMode") or "real_time"),
            source=str(item.get("source") or "browser_runtime"),
            entity_type=str(item.get("entityType") or ""),
            entity_key=str(item.get("entityKey") or ""),
            entity_code=item.get("entityCode"),
            entity_name=str(item.get("entityName") or ""),
            rank=int(float(item.get("rank") or 0)),
            strength=_maybe_float(item.get("strength")),
            heat_score=_maybe_float(item.get("heatScore")),
            heat_level=item.get("heatLevel"),
            change=_maybe_float(item.get("change")),
            main_net_inflow=_maybe_float(item.get("mainNetInflow")),
            big_money300=_maybe_float(item.get("bigMoney300")),
            institution_buy=_maybe_float(item.get("institutionBuy")),
            volume_ratio=_maybe_float(item.get("volumeRatio")),
            zt_count=_maybe_int(item.get("ztCount")),
            leader_count=_maybe_int(item.get("leaderCount")),
            persistent_days=_maybe_int(item.get("persistentDays")),
            net_inflow=_maybe_float(item.get("netInflow")),
            metadata_json=json_dumps(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
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
            "payload": {},
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


def _maybe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _compute_archive_source(has_sqlite: bool, has_archive: bool) -> str:
    if has_sqlite and has_archive:
        return "mixed"
    if has_archive:
        return "parquet_archive"
    return "sqlite"
