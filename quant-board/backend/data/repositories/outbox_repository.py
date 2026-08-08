from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from backend.data.models.models import SyncOutboxModel
from backend.core.utils import stable_hash


class OutboxRepositoryMixin:
    def get_outbox_by_idempotency_key(self, idempotency_key: str) -> SyncOutboxModel | None:
        if self.session is None:
            return None
        try:
            return self.session.scalar(
                select(SyncOutboxModel).where(SyncOutboxModel.idempotency_key == idempotency_key)
            )
        except SQLAlchemyError:
            return None

    def _latest_snapshot_ingest_outbox(
        self, dataset_id: str, snapshot_ids: list[str]
    ) -> SyncOutboxModel | None:
        if self.session is None or not snapshot_ids:
            return None
        try:
            return self.session.scalars(
                select(SyncOutboxModel)
                .where(
                    SyncOutboxModel.op_type == "snapshot_ingest",
                    SyncOutboxModel.dataset_id == dataset_id,
                    SyncOutboxModel.snapshot_id.in_(snapshot_ids),
                )
                .order_by(SyncOutboxModel.created_at.desc())
            ).first()
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
