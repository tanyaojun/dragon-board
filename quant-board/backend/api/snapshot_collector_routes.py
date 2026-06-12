"""Snapshot collector API routes.

Provides HTTP endpoints for the backend snapshot collector:
status, run-once, backfill-slots, runs, and audit.

All responses use the API envelope:
    {"ok": true/false, "status": "...", "data": {...}}
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.snapshot_collector.models import CollectorRunRequest
from backend.snapshot_collector.service import SnapshotCollectorService
from backend.snapshot_collector.service_factory import (
    create_snapshot_collector_repository,
    create_snapshot_collector_service,
)
from backend.snapshot_collector.slots import generate_slots

router = APIRouter(prefix="/api/snapshot-collector")

_VALID_SNAPSHOT_TYPES = frozenset({"quarter_hour", "half_hour", "hourly", "daily"})

# ── helpers ───────────────────────────────────────────────────────────────────


def _validate_snapshot_type(snapshot_type: str) -> None:
    """Raise HTTPException when snapshot_type is not a recognized value."""
    if snapshot_type not in _VALID_SNAPSHOT_TYPES:
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "status": "error",
                "error": f"Invalid snapshotType={snapshot_type!r}, expected one of {sorted(_VALID_SNAPSHOT_TYPES)}",
            },
        )


def _validate_date_format(value: str, field_name: str) -> None:
    """Raise HTTPException when *value* is not YYYY-MM-DD."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "status": "error",
                "error": f"Invalid {field_name}={value!r}, expected YYYY-MM-DD format",
            },
        ) from None


def _build_envelope(ok: bool, status: str, data: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Build a standard API envelope response."""
    envelope: dict[str, Any] = {"ok": ok, "status": status, "data": data}
    envelope.update(extra)
    return envelope


def _run_result_to_data(result: Any) -> dict[str, Any]:
    """Convert a CollectorRunResult to the data section of the envelope."""
    data: dict[str, Any] = {
        "runId": result.run_id,
        "snapshotId": result.snapshot_id,
        "deduped": result.deduped,
        "dryRun": result.dry_run,
        "message": result.message,
    }
    if result.details:
        data["details"] = result.details
    return data


def _quality_to_dict(quality: Any) -> dict[str, Any] | None:
    """Convert a QualityResult to a dict for the response, or None."""
    if quality is None:
        return None
    return {
        "ok": quality.ok,
        "blockingIssues": quality.blocking_issues,
        "warnings": quality.warnings,
        "sourceCounts": quality.source_counts,
    }


def _create_service(repo: Any) -> SnapshotCollectorService:
    """Create the collector service through the shared dependency factory."""
    return create_snapshot_collector_service(repo)


# ── GET /api/snapshot-collector/status ────────────────────────────────────────


@router.get("/status")
def get_collector_status() -> dict[str, Any]:
    """Return the current snapshot collector operational state."""
    repo = create_snapshot_collector_repository()
    service = _create_service(repo)
    status = service.get_status()
    return _build_envelope(ok=True, status="completed", data=status)


# ── POST /api/snapshot-collector/run-once ─────────────────────────────────────


@router.post("/run-once")
def run_collector_once(payload: dict[str, Any]) -> dict[str, Any]:
    """Execute a single snapshot collection run.

    Request body:
        datasetId, snapshotType, tradingDate, slotTime (required)
        dryRun, force (optional, default false)
    """
    dataset_id = payload.get("datasetId", "")
    snapshot_type = payload.get("snapshotType", "")
    trading_date = payload.get("tradingDate", "")
    slot_time = payload.get("slotTime", "")

    if not dataset_id:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "status": "error", "error": "datasetId is required"},
        )
    if not trading_date:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "status": "error", "error": "tradingDate is required"},
        )
    if not slot_time:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "status": "error", "error": "slotTime is required"},
        )

    _validate_snapshot_type(snapshot_type)
    _validate_date_format(trading_date, "tradingDate")

    request = CollectorRunRequest(
        dataset_id=dataset_id,
        snapshot_type=snapshot_type,
        trading_date=trading_date,
        slot_time=slot_time,
        dry_run=bool(payload.get("dryRun", False)),
        force=bool(payload.get("force", False)),
    )

    repo = create_snapshot_collector_repository()
    service = _create_service(repo)
    result = service.run_once(request)

    envelope = _build_envelope(
        ok=result.status in ("completed", "dry_run", "deduped"),
        status=result.status,
        data=_run_result_to_data(result),
    )
    if result.quality is not None:
        envelope["quality"] = _quality_to_dict(result.quality)
    return envelope


# ── POST /api/snapshot-collector/backfill-slots ───────────────────────────────


def _generate_backfill_slots(
    snapshot_type: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, str]]:
    """Generate slot dicts for every trading date in [start_date, end_date]."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if start > end:
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "status": "error",
                "error": f"startDate ({start_date}) must not be after endDate ({end_date})",
            },
        )

    slot_dicts: list[dict[str, str]] = []
    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        slots = generate_slots(date_str, [snapshot_type])
        for slot in slots:
            slot_dicts.append(
                {"trading_date": slot.trading_date, "slot_time": slot.slot_time}
            )
        current += timedelta(days=1)
    return slot_dicts


class _BackfillRequest:
    """Simple namespace for the backfill_slots request."""

    __slots__ = ("dataset_id", "snapshot_type", "slots", "dry_run", "force")

    def __init__(
        self,
        dataset_id: str,
        snapshot_type: str,
        slots: list[dict[str, str]],
        dry_run: bool,
        force: bool,
    ) -> None:
        self.dataset_id = dataset_id
        self.snapshot_type = snapshot_type
        self.slots = slots
        self.dry_run = dry_run
        self.force = force


@router.post("/backfill-slots")
def backfill_collector_slots(payload: dict[str, Any]) -> dict[str, Any]:
    """Run collection for multiple slots across a date range.

    Request body:
        datasetId, snapshotType (required)
        startDate, endDate (at least endDate required)
        dryRun (default true), force (default false)

    Generates all slot times for each trading date in the inclusive range
    and delegates to the service backfill pipeline.
    """
    dataset_id = payload.get("datasetId", "")
    snapshot_type = payload.get("snapshotType", "")
    start_date = payload.get("startDate", "")
    end_date = payload.get("endDate", "")

    if not dataset_id:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "status": "error", "error": "datasetId is required"},
        )
    if not end_date:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "status": "error", "error": "endDate is required"},
        )

    _validate_snapshot_type(snapshot_type)

    # startDate defaults to endDate when absent
    if not start_date:
        start_date = end_date

    _validate_date_format(start_date, "startDate")
    _validate_date_format(end_date, "endDate")

    dry_run = bool(payload.get("dryRun", True))
    force = bool(payload.get("force", False))

    slot_dicts = _generate_backfill_slots(snapshot_type, start_date, end_date)
    if not slot_dicts:
        return _build_envelope(
            ok=True,
            status="completed",
            data={
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "blocked": 0,
                "deduped": 0,
                "details": [],
            },
        )

    backfill_request = _BackfillRequest(
        dataset_id=dataset_id,
        snapshot_type=snapshot_type,
        slots=slot_dicts,
        dry_run=dry_run,
        force=force,
    )

    repo = create_snapshot_collector_repository()
    service = _create_service(repo)
    result = service.backfill_slots(backfill_request)

    ok = result.get("failed", 0) == 0 and result.get("blocked", 0) == 0
    return _build_envelope(ok=ok, status="completed", data=result)


# ── GET /api/snapshot-collector/runs ──────────────────────────────────────────


@router.get("/runs")
def list_collector_runs(
    datasetId: str | None = None,
    status: str | None = None,
    snapshotType: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List recent collector run records with optional filters."""
    filters: dict[str, Any] = {}
    if datasetId:
        filters["datasetId"] = datasetId
    if status:
        filters["status"] = status
    if snapshotType:
        filters["snapshotType"] = snapshotType
    filters["limit"] = limit
    filters["offset"] = offset

    repo = create_snapshot_collector_repository()
    service = _create_service(repo)
    runs = service.get_runs(filters)

    return _build_envelope(
        ok=True,
        status="completed",
        data={
            "items": runs.get("items", []),
            "total": runs.get("total", 0),
            "limit": limit,
            "offset": offset,
        },
    )


# ── POST /api/snapshot-collector/audit ────────────────────────────────────────


@router.post("/audit")
def audit_collector_snapshots(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit snapshot coverage for a dataset/type/date.

    Request body:
        datasetId, snapshotType (required)
        tradingDate (optional)
    """
    dataset_id = payload.get("datasetId", "")
    snapshot_type = payload.get("snapshotType", "")

    if not dataset_id:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "status": "error", "error": "datasetId is required"},
        )
    if not snapshot_type:
        raise HTTPException(
            status_code=400,
            detail={"ok": False, "status": "error", "error": "snapshotType is required"},
        )

    _validate_snapshot_type(snapshot_type)

    trading_date = payload.get("tradingDate", None)
    if trading_date and isinstance(trading_date, str):
        _validate_date_format(trading_date, "tradingDate")

    repo = create_snapshot_collector_repository()
    service = _create_service(repo)
    result = service.audit(dataset_id, snapshot_type, trading_date=trading_date)

    return _build_envelope(ok=True, status="completed", data=result)


@router.get("/scheduler/status")
def get_scheduler_status() -> dict[str, Any]:
    """Return the current collector scheduler operational state."""
    from backend.snapshot_collector.scheduler import snapshot_collector_scheduler

    status_data = snapshot_collector_scheduler.status()
    return _build_envelope(ok=True, status="completed", data=status_data)
