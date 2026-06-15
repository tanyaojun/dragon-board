"""Snapshot collector service orchestration.

``SnapshotCollectorService.run_once`` is the central entry point that
coordinates the full pipeline: provider collection, payload building,
normalization, quality evaluation, and repository persistence.

Design
------
All external dependencies (collect, normalize, quality) are injectable
at construction time so that unit tests can supply fake implementations
without mocking imports.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from . import builder as builder_module
from . import providers as providers_module
from . import quality_gate as quality_gate_module
from .models import (
    CollectorRunRequest,
    CollectorRunResult,
    MarketDataContext,
    QualityResult,
    SnapshotSlot,
)
from .state import record_run as _record_run

# ── helpers ───────────────────────────────────────────────────────────────────


def _slot_timestamp_ms(snapshot_type: str, trading_date: str, slot_time: str) -> int:
    """Compute the epoch-millisecond timestamp for a snapshot slot.

    Delegates to ``slots._make_timestamp_ms`` which is the canonical
    implementation used by the slot generator and eligibility checker.
    """
    from .slots import _make_timestamp_ms

    try:
        return _make_timestamp_ms(trading_date, slot_time)
    except (ValueError, OverflowError):
        return 0


def _generate_run_id() -> str:
    """Generate a short, unique run identifier."""
    raw = f"run-{uuid.uuid4().hex[:12]}-{int(time.time())}"
    return f"sc-{hashlib.sha1(raw.encode()).hexdigest()[:12]}"


def _actual_timestamp_ms() -> int:
    """Current wall-clock time in epoch milliseconds (UTC)."""
    return int(time.time() * 1000)


def _capture_mode_for_slot(
    *,
    slot_timestamp_ms: int,
    actual_timestamp_ms: int,
    grace_minutes: int,
) -> str:
    """Classify a capture as real-time or delayed using the quality grace window."""
    grace_ms = grace_minutes * 60 * 1000
    if slot_timestamp_ms > 0 and actual_timestamp_ms > slot_timestamp_ms + grace_ms:
        return "delayed"
    return "real_time"


def _source_health_dicts(market_context: MarketDataContext) -> list[dict[str, Any]]:
    """Convert SourceHealth objects to JSON-safe run/audit dictionaries."""
    return [
        {
            "source": sh.source,
            "ok": sh.ok,
            "latency_ms": sh.latency_ms,
            "row_count": sh.row_count,
            "error": sh.error,
            "captured_at": sh.captured_at,
        }
        for sh in market_context.source_health
    ]


def _run_audit_fields(
    *,
    source_health: list[dict[str, Any]],
    capture_mode: str,
    started_at: str,
    stock_rows: list[dict[str, Any]] | None = None,
    frames: list[dict[str, Any]] | None = None,
    sector_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build common run audit fields for collector run records."""
    return {
        "sourceHealth": source_health,
        "captureMode": capture_mode,
        "stockRowCount": len(stock_rows or []),
        "frameCount": len(frames or []),
        "sectorRowCount": len(sector_rows or []),
        "startedAt": started_at,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SnapshotCollectorService
# ═══════════════════════════════════════════════════════════════════════════════


class SnapshotCollectorService:
    """Orchestrates the snapshot collection pipeline.

    Constructor parameters:

    *repo*:
        A ``SnapshotRepository`` implementation (real Mongo or fake).
    *settings*:
        Optional settings object.  Used for dataset_id, grace_minutes, and
        other defaults when the request does not supply them.
    *collect_fn*, *normalize_fn*, *quality_fn*:
        Injectable callables for testing.  When absent, the real module-level
        functions are used.
    """

    def __init__(
        self,
        repo: Any,
        settings: Any = None,
        *,
        collect_fn: Callable[..., MarketDataContext] | None = None,
        normalize_fn: Callable[..., tuple] | None = None,
        quality_fn: Callable[..., QualityResult] | None = None,
    ) -> None:
        from backend.data.schemas import SnapshotIngestRequest

        self._repo = repo
        self._settings = settings
        self._collect_fn = collect_fn or providers_module.collect_market_context
        self._quality_fn = quality_fn or quality_gate_module.evaluate_quality

        if normalize_fn is not None:
            self._normalize_fn = normalize_fn
        else:
            from backend.data.snapshot_ingest_normalizer import normalize_snapshot_ingest

            self._normalize_fn = normalize_snapshot_ingest  # type: ignore[assignment]

        self._SnapshotIngestRequest = SnapshotIngestRequest

    # ── run_once ──────────────────────────────────────────────────────────

    def run_once(self, request: CollectorRunRequest) -> CollectorRunResult:
        """Execute a single collection run.

        Pipeline order:
        1. Create ``SnapshotSlot`` from request parameters
        2. If not dry_run and not force, check dedup via repository
        3. Collect provider data into ``MarketDataContext``
        4. Build ingest payload dict
        5. Normalize payload through normalizer
        6. Evaluate quality gate
        7. Record and return blocked when blocked
        8. Record and return dry-run when dry_run
        9. Save through repository
        10. Record and return completed
        """
        run_id = _generate_run_id()
        dataset_id = request.dataset_id
        snapshot_type = request.snapshot_type
        trading_date = request.trading_date
        slot_time = request.slot_time
        started_at = datetime.now(timezone.utc).isoformat()

        # 1 — Create SnapshotSlot
        slot_timestamp = _slot_timestamp_ms(snapshot_type, trading_date, slot_time)
        slot = SnapshotSlot(
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            slot_time=slot_time,
            timestamp_ms=slot_timestamp,
        )
        snapshot_id = slot.snapshot_id

        # 2 — Dedup check (skip when dry_run or force)
        if not request.dry_run and not request.force:
            if self._repo.snapshot_exists(dataset_id, snapshot_id):
                run_doc = {
                    "runId": run_id,
                    "datasetId": dataset_id,
                    "snapshotId": snapshot_id,
                    "snapshotType": snapshot_type,
                    "tradingDate": trading_date,
                    "slotTime": slot_time,
                    "status": "deduped",
                    "deduped": True,
                    "dryRun": False,
                }
                _record_run(self._repo, run_doc)
                return CollectorRunResult(
                    status="deduped",
                    snapshot_id=snapshot_id,
                    deduped=True,
                    run_id=run_id,
                    message="Snapshot already exists",
                )

        # 3 — Collect providers
        providers_list = self._create_providers()
        codes: list[str] = []
        timeout_ms = self._provider_timeout_ms()
        market_context = self._collect_fn(providers_list, codes, timeout_ms=timeout_ms)
        source_health = _source_health_dicts(market_context)
        actual_ts = _actual_timestamp_ms()
        grace_minutes = self._close_grace_minutes()
        capture_mode = _capture_mode_for_slot(
            slot_timestamp_ms=slot_timestamp,
            actual_timestamp_ms=actual_ts,
            grace_minutes=grace_minutes,
        )

        # 4 — Build ingest payload
        bundle = builder_module.build_ingest_payload(
            slot,
            market_context,
            dataset_id=dataset_id,
            source="quantboard_backend_collector",
            capture_mode=capture_mode,
        )

        # 5 — Normalize
        norm_request = self._SnapshotIngestRequest(
            dataset_id=dataset_id,
            bundle=bundle,
            source="quantboard_backend_collector",
        )
        try:
            normalized = self._normalize_fn(norm_request)
        except Exception as exc:
            # Normalization failure is recorded as blocked
            run_doc = {
                "runId": run_id,
                "datasetId": dataset_id,
                "snapshotId": snapshot_id,
                "snapshotType": snapshot_type,
                "tradingDate": trading_date,
                "slotTime": slot_time,
                "status": "blocked",
                "deduped": False,
                "dryRun": request.dry_run,
                "error": str(exc),
                "blockingIssues": ["normalization_failed"],
                **_run_audit_fields(
                    source_health=source_health,
                    capture_mode=capture_mode,
                    started_at=started_at,
                ),
            }
            _record_run(self._repo, run_doc)
            quality = QualityResult(
                ok=False,
                blocking_issues=["normalization_failed"],
                warnings=[],
                source_counts={"ok": 0, "failed": 0},
            )
            return CollectorRunResult(
                status="blocked",
                snapshot_id=snapshot_id,
                run_id=run_id,
                quality=quality,
                message=f"Normalization failed: {exc}",
            )

        dataset_model, records, frames, stock_rows, sector_rows, idempotency_key = normalized

        # 6 — Evaluate quality
        allow_live = self._allow_live_dataset()

        quality = self._quality_fn(
            stock_rows=stock_rows,
            frames=frames,
            source_health=source_health,
            dataset_id=dataset_id,
            allow_live_dataset=allow_live,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            slot_time=slot_time,
            slot_timestamp_ms=slot_timestamp,
            actual_timestamp_ms=actual_ts,
            grace_minutes=grace_minutes,
        )

        # 7 — Blocked
        if not quality.ok:
            run_doc = {
                "runId": run_id,
                "datasetId": dataset_id,
                "snapshotId": snapshot_id,
                "snapshotType": snapshot_type,
                "tradingDate": trading_date,
                "slotTime": slot_time,
                "status": "blocked",
                "deduped": False,
                "dryRun": request.dry_run,
                "blockingIssues": quality.blocking_issues,
                "warnings": quality.warnings,
                **_run_audit_fields(
                    source_health=source_health,
                    capture_mode=capture_mode,
                    started_at=started_at,
                    stock_rows=stock_rows,
                    frames=frames,
                    sector_rows=sector_rows,
                ),
            }
            _record_run(self._repo, run_doc)
            return CollectorRunResult(
                status="blocked",
                snapshot_id=snapshot_id,
                run_id=run_id,
                quality=quality,
                message=f"Quality gate blocked: {quality.blocking_issues}",
            )

        # 8 — Dry run
        if request.dry_run:
            run_doc = {
                "runId": run_id,
                "datasetId": dataset_id,
                "snapshotId": snapshot_id,
                "snapshotType": snapshot_type,
                "tradingDate": trading_date,
                "slotTime": slot_time,
                "status": "dry_run",
                "deduped": False,
                "dryRun": True,
                "warnings": quality.warnings,
                **_run_audit_fields(
                    source_health=source_health,
                    capture_mode=capture_mode,
                    started_at=started_at,
                    stock_rows=stock_rows,
                    frames=frames,
                    sector_rows=sector_rows,
                ),
            }
            _record_run(self._repo, run_doc)
            return CollectorRunResult(
                status="dry_run",
                snapshot_id=snapshot_id,
                dry_run=True,
                run_id=run_id,
                quality=quality,
                message="Dry-run completed successfully",
            )

        # 9 — Save through repository
        dataset_dict = {
            "id": dataset_id,
            "name": dataset_id,
            "source_type": "dragon_board_runtime",
        }
        save_result = self._repo.save_snapshot_ingest(
            dataset_dict,
            records,
            frames,
            stock_rows,
            sector_rows,
            idempotency_key=idempotency_key,
        )

        # 10 — Record and return
        deduped = bool(save_result.get("deduped", False))
        if deduped:
            run_status = "deduped"
        else:
            run_status = "completed"

        run_doc = {
            "runId": run_id,
            "datasetId": dataset_id,
            "snapshotId": snapshot_id,
            "snapshotType": snapshot_type,
            "tradingDate": trading_date,
            "slotTime": slot_time,
            "status": run_status,
            "deduped": deduped,
            "dryRun": False,
            "warnings": quality.warnings,
            **_run_audit_fields(
                source_health=source_health,
                capture_mode=capture_mode,
                started_at=started_at,
                stock_rows=stock_rows,
                frames=frames,
                sector_rows=sector_rows,
            ),
        }
        _record_run(self._repo, run_doc)

        return CollectorRunResult(
            status=run_status,
            snapshot_id=snapshot_id,
            deduped=deduped,
            run_id=run_id,
            quality=quality,
            message=save_result.get("status", ""),
            details={
                "stockRowCount": len(stock_rows),
                "frameCount": len(frames),
                "sectorRowCount": len(sector_rows),
                "idempotencyKey": idempotency_key,
                "captureMode": capture_mode,
            },
        )

    # ── backfill_slots ────────────────────────────────────────────────────

    def backfill_slots(self, request: Any) -> dict[str, Any]:
        """Run multiple slot collections (backfill).

        Returns a summary dict with total, succeeded, failed, blocked,
        and deduped counts.
        """
        slots = getattr(request, "slots", [])
        if not slots:
            return {
                "total": 0,
                "succeeded": 0,
                "failed": 0,
                "blocked": 0,
                "deduped": 0,
                "details": [],
            }

        summary = {"total": 0, "succeeded": 0, "failed": 0, "blocked": 0, "deduped": 0, "details": []}
        for slot_item in slots:
            sub_req = CollectorRunRequest(
                dataset_id=getattr(request, "dataset_id", ""),
                snapshot_type=getattr(request, "snapshot_type", ""),
                trading_date=slot_item.get("trading_date", ""),
                slot_time=slot_item.get("slot_time", ""),
                dry_run=getattr(request, "dry_run", False),
                force=getattr(request, "force", False),
            )
            try:
                result = self.run_once(sub_req)
                summary["total"] += 1
                # Map run_once statuses to backfill counters
                status_key = "succeeded" if result.status == "completed" else result.status
                summary[status_key] = summary.get(status_key, 0) + 1
                summary["details"].append(
                    {
                        "snapshotId": result.snapshot_id,
                        "status": result.status,
                        "message": result.message,
                    }
                )
            except Exception as exc:
                summary["total"] += 1
                summary["failed"] += 1
                summary["details"].append(
                    {
                        "snapshotId": f"{sub_req.snapshot_type}:{sub_req.trading_date}:{sub_req.slot_time}",
                        "status": "failed",
                        "message": str(exc),
                    }
                )
        return summary

    # ── get_status / get_runs / audit ─────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return the current collector state."""
        from .state import get_status as _get_status

        return _get_status(self._repo)

    def get_runs(self, filters: dict[str, Any]) -> dict[str, Any]:
        """Return run records matching *filters*."""
        return self._repo.list_runs(filters)

    def audit(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str | None = None,
    ) -> dict[str, Any]:
        """Audit snapshot coverage for a dataset/type/date."""
        return self._repo.audit_dataset(dataset_id, snapshot_type, trading_date)

    def compare(
        self,
        dataset_id_a: str,
        dataset_id_b: str,
        snapshot_type: str,
        trading_date: str | None = None,
    ) -> dict[str, Any]:
        """Compare snapshot data between two datasets.

        Returns a structured diff including slot completeness, row counts,
        and field-level missing rates for each trading date and slot.
        """
        return self._repo.compare_datasets(
            dataset_id_a, dataset_id_b, snapshot_type, trading_date
        )

    # ── internal helpers ──────────────────────────────────────────────────

    def _create_providers(self) -> list[Any]:
        """Create data-source providers from settings."""
        from .providers import ProxyHotlistProvider, ProxyQuoteProvider

        proxy_url = self._proxy_base_url()
        return [
            ProxyHotlistProvider(base_url=proxy_url),
            ProxyQuoteProvider(base_url=proxy_url),
        ]

    def _proxy_base_url(self) -> str:
        if self._settings and hasattr(self._settings, "snapshot_collector_proxy_base_url"):
            return self._settings.snapshot_collector_proxy_base_url
        return "http://127.0.0.1:3000"

    def _bridge_base_url(self) -> str:
        if self._settings and hasattr(self._settings, "snapshot_collector_bridge_base_url"):
            return self._settings.snapshot_collector_bridge_base_url
        return "http://127.0.0.1:8765"

    def _provider_timeout_ms(self) -> int:
        if self._settings and hasattr(self._settings, "snapshot_collector_provider_timeout_ms"):
            return self._settings.snapshot_collector_provider_timeout_ms
        return 5000

    def _close_grace_minutes(self) -> int:
        if self._settings and hasattr(self._settings, "snapshot_collector_close_grace_minutes"):
            return self._settings.snapshot_collector_close_grace_minutes
        return 5

    def _allow_live_dataset(self) -> bool:
        if self._settings and hasattr(self._settings, "snapshot_collector_allow_live_dataset"):
            return self._settings.snapshot_collector_allow_live_dataset
        return False
