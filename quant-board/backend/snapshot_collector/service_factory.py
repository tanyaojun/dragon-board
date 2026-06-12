"""Service factory for snapshot collector dependency wiring.

Creates ``SnapshotRepository`` instances based on the configured storage
backend.  API routes and CLI handlers obtain their repository through this
factory so they share the same wiring and settings.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from backend.data import mongo_repository
from backend.data.models import Dataset
from backend.data.repository_factory import get_runtime_mongodb_database
from backend.settings import get_settings

from .repository_port import SnapshotRepository
from .service import SnapshotCollectorService


class _MongoSnapshotCollectorRepository:
    """Real MongoDB implementation of ``SnapshotRepository``.

    Delegates snapshot CRUD to ``MongoRepository`` and manages
    operational collections (``snapshot_collector_runs``,
    ``snapshot_collector_state``) directly.
    """

    def __init__(self, mongo_repo: mongo_repository.MongoRepository, db: Any) -> None:
        self._mongo = mongo_repo
        self._db = db

    # ── snapshot layer (reuses MongoRepository) ──────────────────────────

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
        ids = self._mongo.existing_snapshot_ids(dataset_id, [snapshot_id])
        return snapshot_id in ids

    def save_snapshot_ingest(
        self,
        dataset: dict[str, Any],
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        dataset_model = _dict_to_dataset(dataset)
        key = idempotency_key or _fallback_idempotency_key(
            dataset.get("id", ""),
            records,
            frames,
            stock_rows,
            sector_rows,
        )
        return self._mongo.save_snapshot_ingest(
            dataset_model,
            records,
            frames,
            stock_rows,
            sector_rows,
            idempotency_key=key,
            source="quantboard_backend_collector",
        )

    # ── operational collections (writes to snapshot_collector_runs / state) ──

    def insert_run(self, run: dict[str, Any]) -> None:
        doc = dict(run)
        doc.setdefault("createdAt", datetime.utcnow())
        self._db["snapshot_collector_runs"].insert_many([doc], ordered=False)

    def list_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
        query = dict(filters)
        limit = int(query.pop("limit", 50) or 50)
        offset = int(query.pop("offset", 0) or 0)
        cursor = self._db["snapshot_collector_runs"].find(query).sort(
            [("createdAt", -1)]
        )
        items = list(cursor)
        total = len(items)
        return {"items": items[offset:offset + limit], "total": total}

    def collector_status(self) -> dict[str, Any]:
        row = self._db["snapshot_collector_state"].find_one({"key": "collector"})
        if row:
            return dict(row)
        return {"key": "collector", "mode": "idle", "lastRunAt": None}

    def audit_dataset(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str | None = None,
    ) -> dict[str, Any]:
        frame_query: dict[str, Any] = {
            "datasetId": dataset_id,
            "type": snapshot_type,
        }
        if trading_date:
            frame_query["tradingDate"] = trading_date

        frames = list(self._db["snapshot_frames"].find(frame_query).sort("timestamp", 1))
        snapshot_ids = [
            str(row.get("snapshotId"))
            for row in frames
            if row.get("snapshotId")
        ]
        records = (
            list(
                self._db["snapshot_records"].find(
                    {"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}
                )
            )
            if snapshot_ids
            else []
        )
        stock_rows = (
            list(
                self._db["snapshot_stock_rows"].find(
                    {"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}
                )
            )
            if snapshot_ids
            else []
        )
        record_ids = {str(r.get("snapshotId")) for r in records}

        missing_records = sorted(set(snapshot_ids) - record_ids)
        empty_frames = sorted(
            sid for sid in snapshot_ids
            if not any(
                r.get("snapshotId") == sid and r.get("stockRowCount", 0) > 0
                for r in frames
            )
        )

        return {
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "totalFrames": len(frames),
            "totalRecords": len(records),
            "missingSlots": [],
            "emptyFrames": empty_frames,
            "missingRecords": missing_records,
            "countDrifts": _detect_count_drifts(frames, stock_rows),
        }


# ── factory ────────────────────────────────────────────────────────────────


def create_snapshot_collector_repository() -> SnapshotRepository:
    """Create and return a ``SnapshotRepository`` wired to the active backend.

    Requires ``QUANT_BOARD_STORAGE_BACKEND=mongodb``.  SQLite is not
    supported for the snapshot collector.

    The returned repository satisfies the ``SnapshotRepository`` protocol
    and can be used identically from API routes and CLI handlers.
    """
    settings = get_settings()
    if settings.storage_backend != "mongodb":
        raise ValueError(
            f"snapshot collector requires MongoDB storage backend, "
            f"got QUANT_BOARD_STORAGE_BACKEND={settings.storage_backend!r}"
        )
    db = get_runtime_mongodb_database()
    return _MongoSnapshotCollectorRepository(
        mongo_repository.MongoRepository(db), db
    )


def create_snapshot_collector_service(
    repo: SnapshotRepository | None = None,
) -> SnapshotCollectorService:
    """Create and return a ``SnapshotCollectorService``.

    When *repo* is not supplied a default repository is created via
    ``create_snapshot_collector_repository()``.
    """
    settings = get_settings()
    if repo is None:
        repo = create_snapshot_collector_repository()
    return SnapshotCollectorService(repo=repo, settings=settings)


# ── helpers ────────────────────────────────────────────────────────────────


def _dict_to_dataset(data: dict[str, Any]) -> Dataset:
    """Build a minimal ``Dataset`` model from a plain dict.

    The collector uses dict for the protocol boundary so callers do not
    need to import SQLAlchemy models.
    """
    return Dataset(
        id=str(data.get("id") or ""),
        name=str(data.get("name") or data.get("id") or ""),
        source_type=str(data.get("source_type") or "dragon_board_runtime"),
        source_path=str(data.get("source_path") or ""),
        db_name=str(data.get("db_name") or "DragonBoardData"),
        schema_fingerprint=str(data.get("schema_fingerprint") or ""),
        snapshot_count=int(data.get("snapshot_count") or 0),
        frame_count=int(data.get("frame_count") or 0),
        stock_row_count=int(data.get("stock_row_count") or 0),
        sector_row_count=int(data.get("sector_row_count") or 0),
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        snapshot_types_json=json.dumps(
            data.get("snapshot_types") or data.get("snapshot_types_json") or []
        ),
        metadata_json=json.dumps(data.get("metadata") or data.get("metadata_json") or {}),
        created_at=data.get("created_at") or datetime.utcnow(),
    )


def _fallback_idempotency_key(
    dataset_id: str,
    records: list[dict[str, Any]],
    frames: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
) -> str:
    """Derive a content-based idempotency key when none is provided."""
    snapshot_ids = sorted(
        {
            str(item.get("snapshotId") or item.get("snapshot_id") or "")
            for items in [records, frames, stock_rows, sector_rows]
            for item in items
            if isinstance(item, dict)
        }
        - {""}
    )
    raw = f"{dataset_id}:{','.join(snapshot_ids)}"
    return f"sc-{hashlib.sha1(raw.encode()).hexdigest()[:12]}"


def _detect_count_drifts(
    frames: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare frame stockRowCount with actual stock row counts per snapshot."""
    frame_counts: dict[str, int] = {}
    for row in frames:
        sid = str(row.get("snapshotId") or "")
        if sid and row.get("stockRowCount"):
            frame_counts[sid] = int(row["stockRowCount"])

    stock_row_counts: dict[str, int] = {}
    for row in stock_rows:
        sid = str(row.get("snapshotId") or "")
        if sid:
            stock_row_counts[sid] = stock_row_counts.get(sid, 0) + 1

    drifts: list[dict[str, Any]] = []
    for sid in sorted(set(frame_counts) & set(stock_row_counts)):
        fc = frame_counts[sid]
        rc = stock_row_counts[sid]
        if fc != rc:
            drifts.append(
                {"snapshotId": sid, "frameCount": fc, "recordCount": rc}
            )
    return drifts
