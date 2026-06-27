"""Service factory for snapshot collector dependency wiring.

Creates ``SnapshotRepository`` instances based on the configured storage
backend.  API routes and CLI handlers obtain their repository through this
factory so they share the same wiring and settings.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any

from backend.data import mongo_repository
from backend.data.models import Dataset
from backend.data.repository_factory import get_runtime_mongodb_database
from backend.settings import get_settings
from backend.theme_heat_service import get_theme_heat_service

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

    def replace_snapshot_ingest(
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
            dataset.get("id", ""), records, frames, stock_rows, sector_rows
        )
        return self._mongo.save_snapshot_ingest(
            dataset_model,
            records,
            frames,
            stock_rows,
            sector_rows,
            idempotency_key=key,
            source="quantboard_backend_collector",
            replace_existing=True,
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
        sector_rows = (
            list(
                self._db["snapshot_sector_rows"].find(
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

        # Compute missingSlots by comparing expected slots against actual frames
        missing_slots = _compute_missing_slots(
            snapshot_type, frames, trading_date
        )

        return {
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "totalFrames": len(frames),
            "totalRecords": len(records),
            "totalStockRows": len(stock_rows),
            "totalSectorRows": len(sector_rows),
            "missingSlots": missing_slots,
            "emptyFrames": empty_frames,
            "missingRecords": missing_records,
            "countDrifts": _detect_count_drifts(frames, stock_rows),
            "fieldMissingRates": _compute_field_missing_rates(
                stock_rows, _STOCK_ROW_AUDIT_FIELDS
            ),
        }

    def compare_datasets(
        self,
        dataset_id_a: str,
        dataset_id_b: str,
        snapshot_type: str,
        trading_date: str | None = None,
    ) -> dict[str, Any]:
        """Compare snapshot coverage and field completeness across two datasets.

        Returns a structured diff suitable for shadow-vs-live auditing.
        """
        from .slots import SLOT_TIMES

        if snapshot_type not in SLOT_TIMES:
            return {
                "ok": False,
                "error": f"Unknown snapshot_type: {snapshot_type!r}",
                "datasetA": dataset_id_a,
                "datasetB": dataset_id_b,
                "snapshotType": snapshot_type,
            }

        expected_times = SLOT_TIMES[snapshot_type]

        # Determine the set of trading dates to compare
        if trading_date:
            trading_dates: set[str] = {trading_date}
        else:
            dates_a = set(
                str(r.get("tradingDate") or "")
                for r in self._db["snapshot_frames"].find(
                    {"datasetId": dataset_id_a, "type": snapshot_type},
                    {"tradingDate": 1},
                )
            )
            dates_b = set(
                str(r.get("tradingDate") or "")
                for r in self._db["snapshot_frames"].find(
                    {"datasetId": dataset_id_b, "type": snapshot_type},
                    {"tradingDate": 1},
                )
            )
            trading_dates = dates_a | dates_b

        trading_dates.discard("")

        if not trading_dates:
            return {
                "ok": True,
                "datasetA": dataset_id_a,
                "datasetB": dataset_id_b,
                "snapshotType": snapshot_type,
                "tradingDates": [],
                "perDate": [],
                "summary": {
                    "totalSlotsCompared": 0,
                    "slotsInBoth": 0,
                    "slotsOnlyInA": 0,
                    "slotsOnlyInB": 0,
                    "slotsMissingInBoth": 0,
                    "avgStockRowDiff": 0.0,
                    "emptyFramesA": 0,
                    "emptyFramesB": 0,
                },
            }

        per_date: list[dict[str, Any]] = []
        slots_in_both = 0
        slots_only_in_a = 0
        slots_only_in_b = 0
        total_compared = 0
        slots_missing_in_both = 0
        empty_frames_a = 0
        empty_frames_b = 0
        all_stock_row_diffs: list[int] = []

        for td in sorted(trading_dates):
            if not td:
                continue

            # Generate all expected slots for this date
            expected_set = {f"{snapshot_type}:{td}:{t}" for t in expected_times}

            # Query frames for both datasets in one batch per dataset
            frames_a = list(
                self._db["snapshot_frames"].find(
                    {
                        "datasetId": dataset_id_a,
                        "type": snapshot_type,
                        "tradingDate": td,
                    }
                )
            )
            frames_b = list(
                self._db["snapshot_frames"].find(
                    {
                        "datasetId": dataset_id_b,
                        "type": snapshot_type,
                        "tradingDate": td,
                    }
                )
            )

            sid_a = {str(r.get("snapshotId") or "") for r in frames_a}
            sid_b = {str(r.get("snapshotId") or "") for r in frames_b}
            sid_a.discard("")
            sid_b.discard("")

            # Only count expected slots so summary and slotDetails stay aligned
            sid_a_exp = sid_a & expected_set
            sid_b_exp = sid_b & expected_set

            slots_in_both += len(sid_a_exp & sid_b_exp)
            slots_only_in_a += len(sid_a_exp - sid_b_exp)
            slots_only_in_b += len(sid_b_exp - sid_a_exp)
            missing_in_both = expected_set - sid_a_exp - sid_b_exp
            slots_missing_in_both += len(missing_in_both)
            total_compared += len(expected_set)

            all_sids = sorted(sid_a_exp | sid_b_exp)
            slot_details: list[dict[str, Any]] = []

            for sid in all_sids:
                in_a = sid in sid_a
                in_b = sid in sid_b

                detail: dict[str, Any] = {
                    "snapshotId": sid,
                    "inA": in_a,
                    "inB": in_b,
                }

                # Row counts
                if in_a:
                    fa = next((r for r in frames_a if r.get("snapshotId") == sid), {})
                    detail["stockRowCountA"] = fa.get("stockRowCount", 0) or 0
                    detail["sectorRowCountA"] = fa.get("sectorRowCount", 0) or 0
                    if detail["stockRowCountA"] == 0:
                        empty_frames_a += 1

                if in_b:
                    fb = next((r for r in frames_b if r.get("snapshotId") == sid), {})
                    detail["stockRowCountB"] = fb.get("stockRowCount", 0) or 0
                    detail["sectorRowCountB"] = fb.get("sectorRowCount", 0) or 0
                    if detail["stockRowCountB"] == 0:
                        empty_frames_b += 1

                if in_a and in_b:
                    diff = abs(detail.get("stockRowCountA", 0) - detail.get("stockRowCountB", 0))
                    all_stock_row_diffs.append(diff)

                # Field missing rates for common slots (query stock rows)
                if in_a:
                    srows_a = list(
                        self._db["snapshot_stock_rows"].find(
                            {"datasetId": dataset_id_a, "snapshotId": sid}
                        )
                    )
                    detail["fieldMissingRatesA"] = _compute_field_missing_rates(
                        srows_a, _STOCK_ROW_AUDIT_FIELDS
                    )
                if in_b:
                    srows_b = list(
                        self._db["snapshot_stock_rows"].find(
                            {"datasetId": dataset_id_b, "snapshotId": sid}
                        )
                    )
                    detail["fieldMissingRatesB"] = _compute_field_missing_rates(
                        srows_b, _STOCK_ROW_AUDIT_FIELDS
                    )

                slot_details.append(detail)

            per_date.append(
                {
                    "tradingDate": td,
                    "totalExpectedSlots": len(expected_times),
                    "slotsInBoth": sorted(sid_a_exp & sid_b_exp),
                    "slotsOnlyInA": sorted(sid_a_exp - sid_b_exp),
                    "slotsOnlyInB": sorted(sid_b_exp - sid_a_exp),
                    "slotsMissingInBoth": sorted(missing_in_both),
                    "slotDetails": slot_details,
                }
            )

        avg_diff = (
            round(sum(all_stock_row_diffs) / len(all_stock_row_diffs), 2)
            if all_stock_row_diffs
            else 0.0
        )

        return {
            "ok": True,
            "datasetA": dataset_id_a,
            "datasetB": dataset_id_b,
            "snapshotType": snapshot_type,
            "tradingDates": sorted(trading_dates),
            "perDate": per_date,
            "summary": {
                "totalSlotsCompared": total_compared,
                "slotsInBoth": slots_in_both,
                "slotsOnlyInA": slots_only_in_a,
                "slotsOnlyInB": slots_only_in_b,
                "slotsMissingInBoth": slots_missing_in_both,
                "avgStockRowDiff": avg_diff,
                "emptyFramesA": empty_frames_a,
                "emptyFramesB": empty_frames_b,
            },
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
    return SnapshotCollectorService(
        repo=repo,
        settings=settings,
        theme_heat_service=get_theme_heat_service(),
    )


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
        if sid:
            frame_counts[sid] = int(row.get("stockRowCount") or 0)

    stock_row_counts: dict[str, int] = {}
    for row in stock_rows:
        sid = str(row.get("snapshotId") or "")
        if sid:
            stock_row_counts[sid] = stock_row_counts.get(sid, 0) + 1

    drifts: list[dict[str, Any]] = []
    for sid in sorted(set(frame_counts) | set(stock_row_counts)):
        fc = frame_counts.get(sid, 0)
        rc = stock_row_counts.get(sid, 0)
        if fc != rc:
            drifts.append(
                {"snapshotId": sid, "frameCount": fc, "recordCount": rc}
            )
    return drifts


# ── audit helpers ────────────────────────────────────────────────────────────

_STOCK_ROW_AUDIT_FIELDS = [
    "code",
    "name",
    "price",
    "change",
    "volume",
    "turnover",
    "turnoverRate",
    "volumeRatio",
    "hotness",
    "rank",
    "depth10",
    "bid1Price",
    "ask1Price",
    "limitUpPool",
    "firstZtTime",
    "boardHeight",
    "highDays",
    "fengdan",
    "themes",
    "mainTheme",
    "sectorLabel",
    "moneyFlow",
    "amplitude",
    "totalMV",
]


def _compute_missing_slots(
    snapshot_type: str,
    frames: list[dict[str, Any]],
    trading_date: str | None,
) -> list[str]:
    """Compare expected slot table against actual frames.

    Returns sorted list of ``snapshotId`` strings that should exist per the
    slot table but have no matching frame in *frames*.
    """
    from .slots import SLOT_TIMES

    if snapshot_type not in SLOT_TIMES:
        return []

    existing_ids: set[str] = set()
    trading_dates: set[str] = set()
    for row in frames:
        sid = str(row.get("snapshotId") or "")
        if sid:
            existing_ids.add(sid)
        td = str(row.get("tradingDate") or "")
        if td:
            trading_dates.add(td)

    if trading_date:
        trading_dates = {trading_date}

    if not trading_dates:
        return []

    expected_times = SLOT_TIMES[snapshot_type]
    missing: list[str] = []
    for td in sorted(trading_dates):
        for t in expected_times:
            sid = f"{snapshot_type}:{td}:{t}"
            if sid not in existing_ids:
                missing.append(sid)

    return sorted(missing)


def _compute_field_missing_rates(
    rows: list[dict[str, Any]],
    fields: list[str],
) -> dict[str, dict[str, Any]]:
    """Calculate per-field missing rates across *rows*.

    Returns ``{field: {"present": N, "missing": N, "rate": float}}``.
    """
    total = len(rows)
    if total == 0:
        return {}

    counts: dict[str, int] = {f: 0 for f in fields}
    for row in rows:
        for f in fields:
            val = row.get(f)
            if val is not None and val != "" and val != []:
                # NaN check
                if isinstance(val, float):
                    if math.isfinite(val):
                        counts[f] += 1
                else:
                    counts[f] += 1

    result: dict[str, dict[str, Any]] = {}
    for f in fields:
        present = counts[f]
        missing = total - present
        result[f] = {
            "present": present,
            "missing": missing,
            "rate": round(missing / total, 4) if total > 0 else 0.0,
        }
    return result
