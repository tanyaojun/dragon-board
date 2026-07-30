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
from typing import Any

from backend.settings import get_settings as _get_settings
from backend.theme_heat_service import ThemeHeatUnavailable

from . import builder as builder_module
from . import providers as providers_module
from . import quality_gate as quality_gate_module
from .models import (
    CollectorRunRequest,
    CollectorRunResult,
    MarketDataContext,
    SnapshotSlot,
    SourceHealth,
)
from .state import record_run as _record_run

# ── helpers ───────────────────────────────────────────────────────────────────


def _slot_timestamp_ms(snapshot_type: str, trading_date: str, slot_time: str) -> int:
    from .slots import _make_timestamp_ms
    return _make_timestamp_ms(trading_date, slot_time)


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
            "requested_count": sh.requested_count,
            "returned_count": sh.returned_count,
            "coverage_ratio": sh.coverage_ratio,
            "started_at": sh.started_at,
            "completed_at": sh.completed_at,
            "failed_batches": sh.failed_batches,
            "stale": sh.stale,
            "details": sh.details,
        }
        for sh in market_context.source_health
    ]


def factor_to_sector(
    factor: dict[str, Any],
    theme_snapshot: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(factor.get("metadata") or {})
    metadata.update(
        {
            "factorVersion": theme_snapshot.get("factorVersion"),
            "mappingVersion": theme_snapshot.get("mappingVersion"),
            "computedAt": theme_snapshot.get("computedAt"),
            "rankEligible": factor.get("rankEligible", True),
            "degraded": factor.get("degraded", False),
            "quoteSource": "tencent",
            "fundSource": None,
        }
    )
    return {
        "code": str(factor.get("themeId") or ""),
        "name": str(factor.get("themeName") or factor.get("themeId") or ""),
        "entityType": "hot_theme",
        "rank": factor.get("rank", 0),
        "heatScore": factor.get("heatScore"),
        "momentumScore": factor.get("momentumScore"),
        "breadthScore": factor.get("breadthScore"),
        "fundScore": factor.get("fundScore"),
        "leadershipScore": factor.get("leadershipScore"),
        "correlationScore": factor.get("correlationScore"),
        "crowdingRisk": factor.get("crowdingRisk"),
        "persistenceScore": factor.get("persistenceScore"),
        "change": factor.get("change", metadata.get("trimmedMeanChange")),
        "mainNetInflow": factor.get("mainNetInflow"),
        "volumeRatio": factor.get("volumeRatio"),
        "ztCount": factor.get("ztCount", 0),
        "leaderCount": factor.get("leaderCount", 0),
        "themeQualityFlags": list(factor.get("qualityFlags") or []),
        "metadata": metadata,
    }


def theme_snapshot_source_health(theme_snapshot: dict[str, Any]) -> list[SourceHealth]:
    health_rows: list[SourceHealth] = []
    sources = theme_snapshot.get("sources")
    if not isinstance(sources, dict):
        return health_rows
    for value in sources.values():
        if not isinstance(value, dict):
            continue
        health_rows.append(
            SourceHealth(
                source=str(value.get("source") or "theme_heat"),
                ok=bool(value.get("ok")),
                latency_ms=int(value.get("latency_ms") or 0),
                row_count=int(value.get("row_count") or value.get("returned_count") or 0),
                error=str(value.get("error") or ""),
                captured_at=str(value.get("captured_at") or ""),
                requested_count=int(value.get("requested_count") or 0),
                returned_count=int(value.get("returned_count") or 0),
                coverage_ratio=float(value.get("coverage_ratio") or 0),
                started_at=str(value.get("started_at") or ""),
                completed_at=str(value.get("completed_at") or ""),
                failed_batches=list(value.get("failed_batches") or []),
                stale=bool(value.get("stale")),
            )
        )
    quality = theme_snapshot.get("quality")
    quote_coverage = (
        float(quality.get("quoteCoverage") or 0)
        if isinstance(quality, dict)
        else 0.0
    )
    health_rows.append(
        SourceHealth(
            source="theme_heat",
            ok=True,
            row_count=len(theme_snapshot.get("factors") or []),
            coverage_ratio=quote_coverage,
        )
    )
    return health_rows


def _theme_audit_fields(theme_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not theme_snapshot:
        return {}
    quality = theme_snapshot.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    sources = theme_snapshot.get("sources")
    sources = sources if isinstance(sources, dict) else {}
    fund_health = sources.get("funds")
    fund_health = fund_health if isinstance(fund_health, dict) else {}
    return {
        "themeFactorVersion": theme_snapshot.get("factorVersion"),
        "themeComputedAt": theme_snapshot.get("computedAt"),
        "themeQuoteCoverage": quality.get("quoteCoverage"),
        "themeFundCoverage": fund_health.get("coverage_ratio"),
    }


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


def _default_normalize(norm_request: Any) -> tuple:
    """Default normalizer using the extracted ingest normalizer."""
    from backend.data.snapshot_ingest_normalizer import normalize_snapshot_ingest
    return normalize_snapshot_ingest(norm_request)


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
        collect_fn: Any = None,
        normalize_fn: Any = None,
        quality_fn: Any = None,
        cache_invalidate_fn: Any = None,
        theme_heat_service: Any = None,
    ) -> None:
        from backend.data.schemas import SnapshotIngestRequest

        self._repo = repo
        self._settings = settings
        self._collect_fn = collect_fn or providers_module.collect_market_context
        self._normalize_fn = normalize_fn or _default_normalize
        self._quality_fn = quality_fn or quality_gate_module.evaluate_quality
        self._cache_invalidate_fn = cache_invalidate_fn
        self._theme_heat_service = theme_heat_service
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
        providers_list = self._create_providers(trading_date=trading_date)
        codes: list[str] = []
        timeout_ms = self._provider_timeout_ms()
        market_context = self._collect_fn(providers_list, codes, timeout_ms=timeout_ms)
        theme_snapshot: dict[str, Any] | None = None
        if self._theme_heat_service is not None:
            try:
                theme_snapshot = self._theme_heat_service.get_snapshot(
                    include_runtime_funds=False
                )
                market_context.sectors = [
                    factor_to_sector(factor, theme_snapshot)
                    for factor in theme_snapshot.get("factors", [])
                    if isinstance(factor, dict)
                ]
                market_context.source_health.extend(theme_snapshot_source_health(theme_snapshot))
            except ThemeHeatUnavailable as error:
                market_context.sectors = []
                market_context.source_health.append(
                    SourceHealth(source="theme_heat", ok=False, error=error.code)
                )
        source_health = _source_health_dicts(market_context)
        theme_audit = _theme_audit_fields(theme_snapshot)
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
                **theme_audit,
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
            sector_rows=sector_rows,
            dataset_id=dataset_id,
            allow_live_dataset=allow_live,
            snapshot_type=snapshot_type,
            trading_date=trading_date,
            slot_time=slot_time,
            slot_timestamp_ms=slot_timestamp,
            actual_timestamp_ms=actual_ts,
            grace_minutes=grace_minutes,
        )
        diagnostic_flags = [*quality.warnings, *quality.blocking_issues]
        if diagnostic_flags:
            for item in [*records, *frames]:
                existing_flags = item.get("qualityFlags")
                flags = list(existing_flags) if isinstance(existing_flags, list) else []
                item["qualityFlags"] = list(dict.fromkeys([*flags, *diagnostic_flags]))

        # 7 — No raw record exists only when every hotlist source failed.
        # Other quality findings are persisted above for later diagnosis.
        all_hotlist_sources_failed = not source_health or all(
            not source.get("ok") for source in source_health
        )
        if not stock_rows and all_hotlist_sources_failed:
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
                **theme_audit,
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
                **theme_audit,
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
        save_method = (
            self._repo.replace_snapshot_ingest
            if request.force
            else self._repo.save_snapshot_ingest
        )
        if request.force:
            idempotency_key = f"{idempotency_key}:force:{run_id}"
        save_result = save_method(
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
            if self._cache_invalidate_fn is not None:
                self._cache_invalidate_fn(
                    dataset_id=dataset_id,
                    records=records,
                    frames=frames,
                    stock_rows=stock_rows,
                    sector_rows=sector_rows,
                )

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
            **theme_audit,
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

    def _create_providers(self, *, trading_date: str | None = None) -> list[Any]:
        """Create data-source providers from settings."""
        from .providers import (
            BridgeQuoteProvider,
            MarketFundCacheProvider,
            ProxyLimitUpProvider,
            ProxyMergedHotlistProvider,
            StartupBundleStockProvider,
            TencentBasicQuoteProvider,
            ThemeMappingProvider,
        )

        proxy_url = self._proxy_base_url()
        providers: list[Any] = [
            StartupBundleStockProvider(base_url=proxy_url, trading_date=trading_date),
            ProxyMergedHotlistProvider(base_url=proxy_url),
            TencentBasicQuoteProvider(base_url=proxy_url),
            BridgeQuoteProvider(base_url=self._bridge_base_url()),
            MarketFundCacheProvider(self._create_market_fund_cache()),
            ProxyLimitUpProvider(base_url=proxy_url, trading_date=trading_date),
        ]
        theme_repo = self._create_theme_repository()
        if theme_repo is not None:
            providers.append(ThemeMappingProvider(theme_repo))
        return providers

    @staticmethod
    def _create_market_fund_cache() -> Any:
        from backend.theme_fund_cache import get_theme_fund_cache

        return get_theme_fund_cache()

    def _create_theme_repository(self) -> Any | None:
        try:
            from backend.data.mongo_theme_repository import MongoThemeRepository
            from backend.data.repository_factory import get_runtime_mongodb_database

            return MongoThemeRepository(get_runtime_mongodb_database())
        except Exception:
            return None

    def _settings_or_default(self) -> Any:
        return self._settings if self._settings else _get_settings()

    def _proxy_base_url(self) -> str:
        return self._settings_or_default().snapshot_collector_proxy_base_url

    def _bridge_base_url(self) -> str:
        return self._settings_or_default().snapshot_collector_bridge_base_url

    def _provider_timeout_ms(self) -> int:
        return self._settings_or_default().snapshot_collector_provider_timeout_ms

    def _close_grace_minutes(self) -> int:
        return self._settings_or_default().snapshot_collector_close_grace_minutes

    def _allow_live_dataset(self) -> bool:
        return self._settings_or_default().snapshot_collector_allow_live_dataset
