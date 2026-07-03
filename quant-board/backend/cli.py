from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.data.database import ResearchSessionLocal, SessionLocal, init_db
from backend.data.backup_sync import BackupSyncService
from backend.data.backup_retention import run_backup_retention_once
from backend.data.archive.auto_archive import run_archive_auto_once
from backend.data.archive.object_store import get_object_backup_store
from backend.data.archive.service import ArchiveService
from backend.data.dataset_service import DatasetService
from backend.data.json_compaction import compact_json_fields
from backend.data.legacy_split_migration import migrate_legacy_db
from backend.data.migration import SnapshotMigrationService
from backend.data.mongodb_migration import (
    MongoMigrationPlan,
    apply_mongodb_migration,
    get_mongodb_database,
    inspect_mongodb_database,
    plan_mongodb_migration,
    verify_mongodb_migration,
)
from backend.data.mongodb_cleanup import plan_mongodb_dataset_cleanup
from backend.data.mongodb_snapshot_repair import (
    backfill_empty_snapshot_rows,
    copy_missing_snapshot_slots_from_dataset,
)
from backend.data.mongodb_backup import get_mongodb_backup_service
from backend.data.mongodb_research_repair import repair_mongodb_research_metadata
from backend.data.jump_backfill import backfill_jump_fields
from backend.data.repository import Repository
from backend.data.repository_factory import create_repository
from backend.data.schemas import ImportDatasetRequest
from backend.data.storage_inspector import inspect_storage
from backend.data.supabase_backup import get_backup_client
from backend.data.theme_database import ThemeSessionLocal, init_theme_db
from backend.data.theme_service import ThemeMigrationService
from backend.analysis.ranktrend_live_gate_shadow_audit import load_hotlist_anchor_samples
from backend.operations.schedule import run_after_market_once
from backend.settings import get_settings
from backend.services import (
    BacktestService,
    GoldenService,
    OptimizationService,
    RankTrendLiveGateAuditService,
    check_layer1_meltdown,
    check_layer3_trend,
    compute_alignment,
    compute_checkpoint_layer2,
    read_checkpoint_history,
)
from backend.utils import json_loads
from backend.snapshot_collector.models import CollectorRunRequest
from backend.snapshot_collector.quality_gate import SHADOW_DATASET_ID
from backend.snapshot_collector.service import SnapshotCollectorService
from backend.snapshot_collector.service_factory import (
    create_snapshot_collector_repository,
    create_snapshot_collector_service,
)
from backend.snapshot_collector.slots import generate_slots
from backend.snapshot_collector.trading_calendar import is_trading_day

DEFAULT_MOMENTUM_PERIODS = [3, 5, 8, 13, 21]
DEFAULT_HORIZONS = [1, 3, 5, 10]
DEFAULT_LIVE_GATE_AUDIT_FOCUS_CODES = ["600186", "002156"]
DEFAULT_LIVE_GATE_AUDIT_CONFIDENCE_THRESHOLDS = [70, 75, 80, 85, 90, 95]
DEFAULT_LONGTEST_BASELINE_SET = "early_big_move_v5"
LIVE_DATASET_ID = "dragonboard_live"


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def parse_int_list(value: str) -> list[int]:
    raw_items = value.replace(";", ",").replace("-", ",").split(",")
    items = [item.strip() for item in raw_items if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("expected at least one positive integer")
    periods: list[int] = []
    for item in items:
        try:
            period = int(item)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid integer value: {item}") from exc
        if period <= 0:
            raise argparse.ArgumentTypeError(f"period must be positive: {item}")
        periods.append(period)
    return periods


def parse_csv_list(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def parse_float_list(value: str) -> list[float]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        raise argparse.ArgumentTypeError("expected at least one number")
    try:
        return [float(item) for item in items]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid number list: {value}") from exc


def reject_legacy_storage_command_in_mongodb(command: str) -> None:
    if get_settings().storage_backend == "mongodb":
        raise SystemExit(f"{command} is disabled after MongoDB migration; use MongoDB backup/migration commands instead")


def runtime_session():
    init_db()
    if get_settings().storage_backend == "mongodb":
        return nullcontext(None)
    return SessionLocal()


def cmd_import_idb(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        request = ImportDatasetRequest(
            source_type=args.source,
            source_path=args.path,
            name=args.name,
            snapshot_types=args.snapshot_type,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        print_json(DatasetService(session).import_dataset(request))


def cmd_build_dataset(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        request = ImportDatasetRequest(
            source_type="sqlite_snapshots",
            source_dataset_id=args.source_dataset_id,
            name=args.name,
            snapshot_types=args.snapshot_type or ["half_hour"],
            start_date=args.start_date,
            end_date=args.end_date,
            max_snapshots=args.max_snapshots,
            dry_run=args.dry_run,
        )
        print_json(DatasetService(session).import_dataset(request))


def cmd_list_datasets(_: argparse.Namespace) -> None:
    with runtime_session() as session:
        print_json(DatasetService(session).list_datasets())


def cmd_push_backup(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("push-backup")
    init_db()
    with SessionLocal() as session:
        print_json(BackupSyncService(session).push_all_to_backup(full_history=args.full_history))


def cmd_push_outbox(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("push-outbox")
    init_db()
    with SessionLocal() as session:
        repo = Repository(session, enable_backup=False)
        print_json(BackupSyncService(session).push_outbox_to_backup(repo, limit=args.limit))


def cmd_pull_backup(_: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("pull-backup")
    init_db()
    with SessionLocal() as session:
        print_json(BackupSyncService(session).pull_backup_to_primary())


def cmd_smoke_backup(_: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("smoke-backup")
    backup = get_backup_client()
    if not backup:
        print_json({"ok": False, "configured": False, "error": "supabase backup is not configured"})
        return
    print_json(backup.smoke_test())


def cmd_prune_backup(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("prune-backup")
    print_json(run_backup_retention_once(dry_run=args.dry_run))


def cmd_migrate_snapshots(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("migrate-snapshots")
    init_db()
    with SessionLocal() as session:
        request = {
            "datasetId": args.dataset_id,
            "sourcePath": args.path,
            "sourceType": args.source_type,
            "name": args.name,
            "idempotencyKey": args.idempotency_key,
            "source": args.source,
            "dryRun": args.dry_run,
        }
        print_json(SnapshotMigrationService(session).import_json(request))


def cmd_verify_themes(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    if get_settings().storage_backend == "mongodb":
        print_json(ThemeMigrationService(None).verify_mapping(payload))
        return
    init_theme_db()
    with ThemeSessionLocal() as session:
        print_json(ThemeMigrationService(session).verify_mapping(payload))


def cmd_inspect_storage(args: argparse.Namespace) -> None:
    settings = get_settings()
    target = Path(args.path or settings.warehouse_dir)
    print_json(inspect_storage(target))


def cmd_migrate_legacy_db(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("migrate-legacy-db")
    settings = get_settings()
    print_json(
        migrate_legacy_db(
            source=args.source,
            snapshot_database_url=args.snapshot_database_url or settings.snapshot_database_url,
            research_database_url=args.research_database_url or settings.research_database_url,
            apply=bool(args.apply),
        )
    )


def cmd_compact_json_fields(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("compact-json-fields")
    settings = get_settings()
    targets = [args.database_url] if args.database_url else [settings.snapshot_database_url, settings.research_database_url]
    results = [
        compact_json_fields(
            target,
            apply=bool(args.apply),
            threshold=args.threshold,
            batch_size=args.batch_size,
            vacuum=bool(args.vacuum),
        )
        for target in targets
    ]
    print_json({"ok": all(item.get("ok") for item in results), "databases": results})


def cmd_archive_snapshots(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("archive-snapshots")
    init_db()
    with SessionLocal() as session:
        print_json(
            ArchiveService(session).archive_snapshots(
                dataset_id=args.dataset_id,
                snapshot_type=args.snapshot_type,
                before_trading_date=args.before_trading_date,
                dry_run=bool(args.dry_run),
                apply=bool(args.apply),
                max_partitions=args.max_partitions,
            )
        )


def cmd_archive_research(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("archive-research")
    init_db()
    with SessionLocal() as session, ResearchSessionLocal() as research_session:
        print_json(
            ArchiveService(session, research_session=research_session).archive_research(
                run_id=args.run_id,
                older_than_days=args.older_than_days,
                keep_latest_per_group=args.keep_latest_per_group,
                dry_run=bool(args.dry_run),
                apply=bool(args.apply),
            )
        )


def cmd_verify_archive(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("verify-archive")
    init_db()
    with SessionLocal() as session:
        print_json(ArchiveService(session).verify_archive(args.archive_id))


def cmd_restore_archive(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("restore-archive")
    init_db()
    with SessionLocal() as session:
        print_json(ArchiveService(session).restore_archive(args.archive_id, dry_run=bool(args.dry_run), apply=bool(args.apply)))


def cmd_archive_auto_once(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("archive-auto-once")
    init_db()
    print_json(run_archive_auto_once(args.limit))


def cmd_smoke_object_backup(_: argparse.Namespace) -> None:
    store = get_object_backup_store()
    if not store:
        print_json({"ok": False, "configured": False, "error": "object backup bucket is not configured"})
        return
    print_json(store.smoke_test())


def cmd_push_archive_backup(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("push-archive-backup")
    init_db()
    with SessionLocal() as session:
        result = ArchiveService(session).push_archive_backup(limit=args.limit)
        print_json(result)


def cmd_backup_snapshot_day(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("backup-snapshot-day")
    init_db()
    with SessionLocal() as session:
        service = ArchiveService(session)
        trading_date = args.trading_date or service.latest_snapshot_trading_date(
            dataset_id=args.dataset_id,
            snapshot_type=args.snapshot_type,
        )
        if not trading_date:
            print_json(
                {
                    "ok": False,
                    "error": {
                        "code": "no_snapshot_trading_date",
                        "datasetId": args.dataset_id,
                        "snapshotType": args.snapshot_type,
                    },
                }
            )
            return
        print_json(
            service.backup_snapshot_day_to_object(
                dataset_id=args.dataset_id,
                snapshot_type=args.snapshot_type,
                trading_date=trading_date,
                dry_run=bool(args.dry_run),
            )
        )


def cmd_after_market_once(args: argparse.Namespace) -> None:
    print_json(
        run_after_market_once(
            archive_limit=args.archive_limit,
            backup_limit=args.backup_limit,
            dry_run=bool(args.dry_run),
        )
    )


def cmd_migrate_mongodb(args: argparse.Namespace) -> None:
    settings = get_settings()
    if args.apply and args.dry_run:
        raise SystemExit("choose either --dry-run or --apply, not both")
    plan = MongoMigrationPlan(
        snapshot_db=Path(args.snapshot_db or settings.warehouse_dir / "quant_board_snapshots.db"),
        research_db=Path(args.research_db or settings.warehouse_dir / "quant_board_research.db"),
        theme_db=Path(args.theme_db or settings.warehouse_dir / "themeDATA.db"),
        stock_json=Path(args.stock_json or settings.project_root.parent / "public" / "data" / "stock_code.json"),
        target_database=args.target_database or settings.mongodb_database,
        include_research=not bool(args.skip_research),
    )
    if args.apply:
        db = get_mongodb_database(
            settings.mongodb_uri,
            plan.target_database,
            connect_timeout_ms=settings.mongodb_connect_timeout_ms,
            server_selection_timeout_ms=settings.mongodb_server_selection_timeout_ms,
        )
        print_json(
            apply_mongodb_migration(
                plan,
                db,
                replace_confirmed=bool(args.replace_confirmed),
                batch_size=args.batch_size,
            )
        )
        return
    print_json(plan_mongodb_migration(plan))


def _runtime_mongodb_database() -> Any:
    settings = get_settings()
    return get_mongodb_database(
        settings.mongodb_uri,
        settings.mongodb_database,
        connect_timeout_ms=settings.mongodb_connect_timeout_ms,
        server_selection_timeout_ms=settings.mongodb_server_selection_timeout_ms,
    )


def cmd_inspect_mongodb(_: argparse.Namespace) -> None:
    print_json(inspect_mongodb_database(_runtime_mongodb_database()))


def cmd_verify_mongodb_migration(args: argparse.Namespace) -> None:
    print_json(
        verify_mongodb_migration(
            _runtime_mongodb_database(),
            dataset_id=args.dataset_id,
            snapshot_type=args.snapshot_type,
            codes=args.code or [],
        )
    )


def cmd_cleanup_mongodb_datasets(args: argparse.Namespace) -> None:
    print_json(
        plan_mongodb_dataset_cleanup(
            _runtime_mongodb_database(),
            keep_dataset_ids=args.keep_dataset_id,
            apply=bool(args.apply),
        )
    )


def cmd_backfill_empty_mongodb_snapshots(args: argparse.Namespace) -> None:
    print_json(
        backfill_empty_snapshot_rows(
            _runtime_mongodb_database(),
            dataset_id=args.dataset_id,
            snapshot_ids=args.snapshot_id,
            apply=bool(args.apply),
        )
    )


def cmd_copy_missing_mongodb_snapshot_slots(args: argparse.Namespace) -> None:
    print_json(
        copy_missing_snapshot_slots_from_dataset(
            _runtime_mongodb_database(),
            target_dataset_id=args.target_dataset_id,
            donor_dataset_id=args.donor_dataset_id,
            snapshot_ids=args.snapshot_id,
            apply=bool(args.apply),
        )
    )


def cmd_repair_mongodb_research_metadata(args: argparse.Namespace) -> None:
    print_json(
        repair_mongodb_research_metadata(
            _runtime_mongodb_database(),
            apply=bool(args.apply),
        )
    )


def cmd_backfill_jump_fields(args: argparse.Namespace) -> None:
    print_json(
        backfill_jump_fields(
            _runtime_mongodb_database(),
            dataset_id=args.dataset_id,
            trading_dates=args.trading_date or None,
            dry_run=not bool(args.apply),
        )
    )


def cmd_backup_mongodb(args: argparse.Namespace) -> None:
    settings = get_settings()
    db = get_mongodb_database(
        settings.mongodb_uri,
        settings.mongodb_database,
        connect_timeout_ms=settings.mongodb_connect_timeout_ms,
        server_selection_timeout_ms=settings.mongodb_server_selection_timeout_ms,
    )
    service = get_mongodb_backup_service()
    if args.light:
        result = service.create_light_backup(db)
    elif args.full:
        result = service.create_full_backup(db)
    else:
        raise SystemExit("use --full or --light")
    if result.get("ok"):
        result["verify"] = service.verify_backup(result["backupId"])
    print_json(result)


def cmd_verify_mongodb_backup(args: argparse.Namespace) -> None:
    print_json(get_mongodb_backup_service().verify_backup(args.backup_id))


def cmd_verify_mongodb_restore_staging(args: argparse.Namespace) -> None:
    print_json(get_mongodb_backup_service().verify_restore_staging_backup(args.backup_id))


def cmd_push_mongodb_backup(args: argparse.Namespace) -> None:
    print_json(get_mongodb_backup_service().push_backup(args.backup_id))


def cmd_pull_mongodb_backup(args: argparse.Namespace) -> None:
    print_json(get_mongodb_backup_service().pull_backup(args.backup_id, dry_run=bool(args.dry_run)))


def cmd_list_mongodb_backups(_: argparse.Namespace) -> None:
    print_json(get_mongodb_backup_service().list_backups())


def cmd_prune_mongodb_backups(args: argparse.Namespace) -> None:
    print_json(get_mongodb_backup_service().prune_local_backups(dry_run=bool(args.dry_run)))


def cmd_pull_archive_backup(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("pull-archive-backup")
    init_db()
    with SessionLocal() as session:
        result = ArchiveService(session).pull_archive_backup(
            args.archive_id,
            dry_run=bool(args.dry_run),
            apply=bool(args.apply),
        )
        print_json(result)


def cmd_verify_snapshot_migration(args: argparse.Namespace) -> None:
    reject_legacy_storage_command_in_mongodb("verify-snapshot-migration")
    init_db()
    source_report = json.loads(Path(args.source_report).read_text(encoding="utf-8"))
    expected = source_report.get("report") if isinstance(source_report.get("report"), dict) else source_report
    with SessionLocal() as session:
        repo = Repository(session, enable_backup=False)
        counts = repo.snapshot_counts(dataset_id=args.dataset_id)
    actual = {
        "records": counts.get("records", 0),
        "frames": counts.get("frames", 0),
        "stock_rows": counts.get("stockRows", 0),
        "sector_rows": counts.get("sectorRows", 0),
    }
    expected_counts = {
        "records": int(expected.get("record_count") or expected.get("records") or expected.get("scanned") or 0),
        "frames": int(expected.get("frame_count") or expected.get("frames") or expected.get("scanned") or 0),
        "stock_rows": int(expected.get("stock_row_count") or expected.get("stock_rows") or 0),
        "sector_rows": int(expected.get("sector_row_count") or expected.get("sector_rows") or 0),
    }
    mismatches = {
        key: {"expected": expected_counts[key], "actual": actual[key]}
        for key in expected_counts
        if expected_counts[key] and expected_counts[key] != actual[key]
    }
    print_json({"ok": not mismatches, "datasetId": args.dataset_id, "expected": expected_counts, "actual": actual, "mismatches": mismatches})


def cmd_inspect_research_storage(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        print_json(BacktestService(session).research_storage_summary())


def cmd_delete_backtest(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        result = BacktestService(session).delete_run(args.run_id)
    if result is None:
        raise SystemExit(f"backtest run not found: {args.run_id}")
    print_json(result)


def cmd_cleanup_research(args: argparse.Namespace) -> None:
    payload = {
        "olderThanDays": args.older_than_days,
        "keepLatestPerGroup": args.keep_latest_per_group,
        "datasetId": args.dataset_id,
        "snapshotType": args.snapshot_type,
        "includeFailed": args.include_failed,
        "confirm": bool(args.apply),
    }
    with runtime_session() as session:
        service = BacktestService(session)
        result = service.cleanup_research(payload, apply=bool(args.apply))
        if args.apply and args.vacuum:
            result["vacuum"] = service.vacuum_research_sqlite()
    print_json(result)


def build_ranktrend_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload = {
        "dataset_id": args.dataset_id,
        "snapshot_type": args.snapshot_type,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "strategy_name": args.strategy_name,
        "random_seed": args.seed,
        "enable_trade_simulation": not args.no_trade_simulation,
        "initialCash": args.initial_cash,
        "maxPositions": args.max_positions,
        "targetHoldingDays": args.target_holding_days,
        "macdFast": args.macd_fast,
        "macdSlow": args.macd_slow,
        "macdSignal": args.macd_signal,
        "momentumPeriods": list(args.momentum_periods),
        "horizons": list(args.horizons),
        "tradeConfig": {
            "positionSize": args.position_size,
            "feeRate": args.fee_rate,
            "stampTaxRate": args.stamp_tax_rate,
            "slippageRate": args.slippage_rate,
            "enforceT1": not args.no_t1,
            "executionMode": args.execution_mode,
            "useOrderBookPrice": not args.no_order_book_price,
            "enforceLimitStatus": not args.no_limit_status,
            "enforceVolumeLimit": not args.no_volume_limit,
            "enforceOrderBookQueue": not args.no_order_book_queue,
            "allowPartialFills": not args.no_partial_fills,
            "orderBookParticipationRate": args.order_book_participation_rate,
            "useIntrabarStops": not args.no_intrabar_stops,
            "intrabarAmbiguity": args.intrabar_ambiguity,
            "useThemeFactorForExecution": args.use_theme_factor_for_execution,
        },
        "excludeNonPositivePriceRows": args.exclude_non_positive_price_rows,
        "excludeCrossMarketZeroPriceRows": args.exclude_cross_market_zero_price_rows,
        "excludeAllZeroPriceFrames": args.exclude_all_zero_price_frames,
    }
    if args.max_holding_bars is not None:
        payload["maxHoldingBars"] = args.max_holding_bars
    if args.take_profit_pct is not None:
        payload["takeProfitPct"] = args.take_profit_pct
    if args.stop_loss_pct is not None:
        payload["stopLossPct"] = args.stop_loss_pct
    if args.volume_participation_rate is not None:
        payload["tradeConfig"]["volumeParticipationRate"] = args.volume_participation_rate
    return payload


LEGACY_LIFECYCLE_BASELINES = (
    {
        "label": "H1_half_hour_current_bar",
        "snapshot_type": "half_hour",
        "execution_mode": "current_bar",
        "max_holding_bars": 40,
        "purpose": "page-compatible optimistic baseline",
    },
    {
        "label": "H2_half_hour_next_bar",
        "snapshot_type": "half_hour",
        "execution_mode": "next_bar",
        "max_holding_bars": 40,
        "purpose": "formal conservative baseline",
    },
    {
        "label": "Q1_quarter_hour_next_bar",
        "snapshot_type": "quarter_hour",
        "execution_mode": "next_bar",
        "max_holding_bars": 80,
        "purpose": "research pressure-test baseline",
    },
)

EARLY_BIG_MOVE_BASELINES = (
    {
        "label": "E1_half_hour_signal_forward40",
        "snapshot_type": "half_hour",
        "execution_mode": "current_bar",
        "max_holding_bars": 40,
        "purpose": "early big-move candidate recall without trade simulation",
        "strategy_name": "ranktrend_early_big_move",
        "enable_trade_simulation": False,
    },
    {
        "label": "E2_half_hour_ranked_current_bar",
        "snapshot_type": "half_hour",
        "execution_mode": "current_bar",
        "max_holding_bars": 40,
        "purpose": "ranked early big-move current-frame execution baseline",
        "strategy_name": "ranktrend_early_big_move",
    },
    {
        "label": "E3_half_hour_ranked_strict_fill",
        "snapshot_type": "half_hour",
        "execution_mode": "next_bar",
        "max_holding_bars": 40,
        "purpose": "ranked early big-move strict executable baseline",
        "strategy_name": "ranktrend_early_big_move",
        "fill_fallback_mode": "strict_fill",
    },
)

EARLY_BIG_MOVE_V2_BASELINES = (
    {
        "label": "V2_E1_half_hour_signal_forward40",
        "snapshot_type": "half_hour",
        "execution_mode": "current_bar",
        "max_holding_bars": 40,
        "purpose": "early big-move V2 candidate recall without trade simulation",
        "strategy_name": "ranktrend_early_big_move_v2",
        "enable_trade_simulation": False,
        "take_profit_pct": 9.99,
        "stop_loss_pct": 0.05,
    },
    {
        "label": "V2_E2_half_hour_ranked_current_bar",
        "snapshot_type": "half_hour",
        "execution_mode": "current_bar",
        "max_holding_bars": 40,
        "purpose": "ranked early big-move V2 current-frame execution baseline",
        "strategy_name": "ranktrend_early_big_move_v2",
        "take_profit_pct": 9.99,
        "stop_loss_pct": 0.05,
    },
    {
        "label": "V2_E3_half_hour_ranked_strict_fill",
        "snapshot_type": "half_hour",
        "execution_mode": "next_bar",
        "max_holding_bars": 40,
        "purpose": "ranked early big-move V2 strict executable baseline",
        "strategy_name": "ranktrend_early_big_move_v2",
        "fill_fallback_mode": "strict_fill",
        "take_profit_pct": 9.99,
        "stop_loss_pct": 0.05,
    },
)

EARLY_BIG_MOVE_V3_BASELINES = (
    {
        "label": "V3_E1_half_hour_signal_forward50",
        "snapshot_type": "half_hour",
        "execution_mode": "current_bar",
        "max_holding_bars": 50,
        "purpose": "early big-move V3 candidate recall without trade simulation",
        "strategy_name": "ranktrend_early_big_move_v3",
        "enable_trade_simulation": False,
        "take_profit_pct": 9.99,
        "stop_loss_pct": 0.05,
    },
    {
        "label": "V3_E2_half_hour_ranked_current_bar",
        "snapshot_type": "half_hour",
        "execution_mode": "current_bar",
        "max_holding_bars": 50,
        "purpose": "ranked early big-move V3 current-frame execution baseline",
        "strategy_name": "ranktrend_early_big_move_v3",
        "take_profit_pct": 9.99,
        "stop_loss_pct": 0.05,
    },
    {
        "label": "V3_E3_half_hour_ranked_strict_fill",
        "snapshot_type": "half_hour",
        "execution_mode": "next_bar",
        "max_holding_bars": 50,
        "purpose": "ranked early big-move V3 strict executable baseline",
        "strategy_name": "ranktrend_early_big_move_v3",
        "fill_fallback_mode": "strict_fill",
        "take_profit_pct": 9.99,
        "stop_loss_pct": 0.05,
    },
)

EARLY_BIG_MOVE_V5_BASELINES = (
    {
        "label": "V5_E1_half_hour_fusion_signal_forward30",
        "snapshot_type": "half_hour",
        "execution_mode": "current_bar",
        "max_holding_bars": 30,
        "purpose": "V5 fusion candidate recall without trade simulation",
        "strategy_name": "ranktrend_early_big_move_v3_lifecycle_fusion",
        "enable_trade_simulation": False,
        "take_profit_pct": 9.99,
        "stop_loss_pct": 0.05,
        "volume_participation_rate": 0.1,
    },
    {
        "label": "V5_E2_half_hour_fusion_current_bar",
        "snapshot_type": "half_hour",
        "execution_mode": "current_bar",
        "max_holding_bars": 30,
        "purpose": "V5 lifecycle-fusion current-frame execution baseline",
        "strategy_name": "ranktrend_early_big_move_v3_lifecycle_fusion",
        "take_profit_pct": 9.99,
        "stop_loss_pct": 0.05,
        "volume_participation_rate": 0.1,
    },
)

LONGTEST_BASELINE_SETS = {
    "early_big_move_v1": EARLY_BIG_MOVE_BASELINES,
    "early_big_move_v2": EARLY_BIG_MOVE_V2_BASELINES,
    "early_big_move_v3": EARLY_BIG_MOVE_V3_BASELINES,
    "early_big_move_v5": EARLY_BIG_MOVE_V5_BASELINES,
    "legacy_lifecycle_v1": LEGACY_LIFECYCLE_BASELINES,
}


def build_longtest_baseline_payloads(args: argparse.Namespace) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    baseline_set = str(getattr(args, "baseline_set", DEFAULT_LONGTEST_BASELINE_SET))
    baselines = LONGTEST_BASELINE_SETS[baseline_set]
    for baseline in baselines:
        ranktrend_args = argparse.Namespace(
            dataset_id=args.dataset_id,
            snapshot_type=baseline["snapshot_type"],
            start_date=args.start_date,
            end_date=args.end_date,
            strategy_name=baseline.get("strategy_name") or args.strategy_name,
            seed=args.seed,
            no_trade_simulation=not bool(baseline.get("enable_trade_simulation", True)),
            initial_cash=args.initial_cash,
            max_positions=args.max_positions,
            position_size=args.position_size,
            target_holding_days=args.target_holding_days,
            max_holding_bars=baseline["max_holding_bars"],
            take_profit_pct=baseline.get("take_profit_pct", args.take_profit_pct),
            stop_loss_pct=baseline.get("stop_loss_pct", args.stop_loss_pct),
            fee_rate=args.fee_rate,
            stamp_tax_rate=args.stamp_tax_rate,
            slippage_rate=args.slippage_rate,
            no_t1=False,
            macd_fast=args.macd_fast,
            macd_slow=args.macd_slow,
            macd_signal=args.macd_signal,
            momentum_periods=args.momentum_periods,
            horizons=args.horizons,
            execution_mode=baseline["execution_mode"],
            no_order_book_price=False,
            no_limit_status=False,
            no_volume_limit=False,
            no_order_book_queue=False,
            no_partial_fills=False,
            volume_participation_rate=baseline.get("volume_participation_rate", args.volume_participation_rate),
            order_book_participation_rate=baseline.get("order_book_participation_rate", args.order_book_participation_rate),
            no_intrabar_stops=False,
            intrabar_ambiguity=args.intrabar_ambiguity,
            use_theme_factor_for_execution=False,
            exclude_non_positive_price_rows=args.exclude_non_positive_price_rows,
            exclude_cross_market_zero_price_rows=args.exclude_cross_market_zero_price_rows,
            exclude_all_zero_price_frames=args.exclude_all_zero_price_frames,
        )
        payload = build_ranktrend_payload(ranktrend_args)
        fill_fallback_mode = baseline.get("fill_fallback_mode")
        if fill_fallback_mode:
            payload["tradeConfig"]["fillFallbackMode"] = fill_fallback_mode
        payloads.append({
            "label": baseline["label"],
            "purpose": baseline["purpose"],
            "payload": payload,
        })
    return payloads


def summarize_longtest_baseline(spec: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    payload = spec.get("payload") if isinstance(spec.get("payload"), dict) else {}
    data_quality = run.get("dataQuality") if isinstance(run.get("dataQuality"), dict) else {}
    quality_gate = data_quality.get("qualityGate") if isinstance(data_quality.get("qualityGate"), dict) else {}
    quality_stats = quality_gate.get("stats") if isinstance(quality_gate.get("stats"), dict) else {}
    report_only_diagnostics = (
        data_quality.get("reportOnlyDiagnostics")
        if isinstance(data_quality.get("reportOnlyDiagnostics"), dict)
        else {}
    )
    simulation = run.get("tradeSimulation") if isinstance(run.get("tradeSimulation"), dict) else {}
    matching = simulation.get("matchingDiagnostics") if isinstance(simulation.get("matchingDiagnostics"), dict) else {}
    trade_config = payload.get("tradeConfig") if isinstance(payload.get("tradeConfig"), dict) else {}
    return {
        "label": spec.get("label"),
        "purpose": spec.get("purpose"),
        "runId": run.get("runId") or run.get("id"),
        "datasetId": run.get("datasetId") or payload.get("dataset_id"),
        "snapshotType": run.get("snapshotType") or payload.get("snapshot_type"),
        "strategyName": run.get("strategyName") or payload.get("strategy_name"),
        "strategyVersion": run.get("strategyVersion") or "0.1.0",
        "configHash": run.get("configHash"),
        "randomSeed": run.get("randomSeed") or payload.get("random_seed"),
        "executionMode": trade_config.get("executionMode"),
        "maxHoldingBars": payload.get("maxHoldingBars"),
        "targetHoldingDays": payload.get("targetHoldingDays"),
        "volumeParticipationRate": trade_config.get("volumeParticipationRate"),
        "totalReturn": run.get("totalReturn"),
        "realizedReturn": run.get("realizedReturn"),
        "maxDrawdown": run.get("maxDrawdown"),
        "sharpe": run.get("sharpe"),
        "winRate": run.get("winRate"),
        "tradeCount": run.get("tradeCount"),
        "openPositionCount": run.get("openPositionCount"),
        "qualitySeverity": data_quality.get("severity"),
        "researchGrade": data_quality.get("researchGrade"),
        "sampleOkShare": data_quality.get("sampleOkShare"),
        "sampleDegradedShare": data_quality.get("sampleDegradedShare"),
        "sampleInsufficientShare": data_quality.get("sampleInsufficientShare"),
        "missingMoneyFlowSourceCount": quality_stats.get("missingMoneyFlowSourceCount"),
        "formalMoneyFlowCount": quality_stats.get("formalMoneyFlowCount"),
        "estimatedL1MoneyFlowCount": quality_stats.get("estimatedL1MoneyFlowCount"),
        "excludeNonPositivePriceRows": bool(payload.get("excludeNonPositivePriceRows")),
        "excludeCrossMarketZeroPriceRows": bool(payload.get("excludeCrossMarketZeroPriceRows")),
        "excludeAllZeroPriceFrames": bool(payload.get("excludeAllZeroPriceFrames")),
        "priceFilter": (data_quality.get("runtimeFilter") or {}).get("priceFilter") if isinstance(data_quality.get("runtimeFilter"), dict) else None,
        "crossMarketPriceFilter": (data_quality.get("runtimeFilter") or {}).get("crossMarketPriceFilter") if isinstance(data_quality.get("runtimeFilter"), dict) else None,
        "allZeroPriceFrameFilter": (data_quality.get("runtimeFilter") or {}).get("allZeroPriceFrameFilter") if isinstance(data_quality.get("runtimeFilter"), dict) else None,
        "priceQualityDiagnostics": report_only_diagnostics.get("priceQuality"),
        "layer1SignalEfficacy": data_quality.get("layer1SignalEfficacy"),
        "executionLayer1Efficacy": data_quality.get("executionLayer1Efficacy"),
        "layer2ExecutionQuality": data_quality.get("layer2ExecutionQuality"),
        "blockedByLimit": matching.get("blockedByLimit"),
        "nextBarEntries": matching.get("nextBarEntries"),
        "nextBarExits": matching.get("nextBarExits"),
        "buyFilled": matching.get("buyFilled"),
        "sellFilled": matching.get("sellFilled"),
    }


def cmd_run_longtest_baselines(args: argparse.Namespace) -> None:
    checkpoint_id = args.checkpoint_id or datetime.now(timezone.utc).strftime("longtest_%Y%m%dT%H%M%SZ")
    specs = build_longtest_baseline_payloads(args)
    created_at = datetime.now(timezone.utc).isoformat()
    baselines: list[dict[str, Any]] = []

    if args.dry_run:
        print_json({
            "ok": True,
            "dryRun": True,
            "checkpointId": checkpoint_id,
            "createdAt": created_at,
            "baselines": specs,
        })
        return

    with runtime_session() as session:
        service = BacktestService(session)
        for spec in specs:
            run = service.run_ranktrend(spec["payload"])
            baselines.append(summarize_longtest_baseline(spec, run))

    # Layer 2: compute execution quality from the active optimistic vs strict-fill execution pair
    layer_2 = compute_checkpoint_layer2(baselines)
    if layer_2 is not None:
        for baseline in baselines:
            label = str(baseline.get("label") or "")
            if label in ("H1_half_hour_current_bar", "H2_half_hour_next_bar") or "E2_" in label or "E3_" in label:
                baseline["layer2ExecutionQuality"] = layer_2

    result = {
        "ok": True,
        "checkpointId": checkpoint_id,
        "createdAt": created_at,
        "datasetId": args.dataset_id,
        "baselineSet": args.baseline_set,
        "strategyName": args.strategy_name,
        "randomSeed": args.seed,
        "baselines": baselines,
    }

    # Layer 3: compute alignment if trade journal data available
    try:
        run_ids = [b.get("runId") or b.get("id", "") for b in baselines]
        alignment = compute_alignment(
            repo=create_repository(None),
            run_ids=[rid for rid in run_ids if rid],
            start_date=getattr(args, "start_date", None),
            end_date=getattr(args, "end_date", None),
        )
        result["layer3Alignment"] = alignment
        if alignment.get("sufficientSample"):
            print(f"  Layer 3 alignment: {alignment['intersectionCount']} overlapping stocks, intersection P&L: {alignment['intersectionPnlPct']:.2%}")
        elif alignment.get("alignmentStatus") == "unavailable":
            print(f"  Layer 3 alignment: {alignment.get('reason', 'unavailable')}")
        else:
            print(f"  Layer 3 alignment: insufficient data ({alignment.get('journalExecutedCount', 0)} executed trades, need >= 10)")
    except Exception as exc:
        print(f"  Layer 3 alignment skipped: {exc}")
        result["layer3Alignment"] = {"status": "skipped", "reason": str(exc)}

    # Cross-period checks
    jsonl_path = get_settings().reports_dir / "long_test_runs.jsonl"
    history = read_checkpoint_history(jsonl_path, limit=6)

    l1_meltdown_signal_pool = check_layer1_meltdown(history, metric_key="layer1SignalEfficacy")
    l1_meltdown_execution_v5 = check_layer1_meltdown(
        history,
        "V5_E2_half_hour_fusion_current_bar",
        metric_key="executionLayer1Efficacy",
    )
    l1_meltdown_h1 = l1_meltdown_signal_pool
    if l1_meltdown_h1.get("meltdown"):
        label = l1_meltdown_h1.get("selectedLabel") or "signal-pool Layer1"
        print(f"  [WARN] L1 meltdown: {l1_meltdown_h1['consecutiveRedPeriods']} consecutive red periods on {label}")
    if l1_meltdown_execution_v5.get("meltdown"):
        print(
            "  [WARN] V5 execution-entry L1 meltdown: "
            f"{l1_meltdown_execution_v5['consecutiveRedPeriods']} consecutive red periods"
        )

    l3_trend = check_layer3_trend(history)
    if l3_trend.get("greenLight"):
        print("  [OK] L3 trend: 2 consecutive sufficient alignments -> green light")

    result["crossPeriod"] = {
        "layer1MeltdownH1": l1_meltdown_h1,
        "layer1MeltdownSignalPool": l1_meltdown_signal_pool,
        "layer1MeltdownV5Execution": l1_meltdown_execution_v5,
        "layer3Trend": l3_trend,
    }

    output = Path(args.output) if args.output else get_settings().reports_dir / "long_test_runs.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8") as file:
        file.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")
    print_json({**result, "output": str(output)})


def cmd_run_ranktrend(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        payload = build_ranktrend_payload(args)
        print_json(BacktestService(session).run_ranktrend(payload))


def cmd_run_theme_trend(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        payload = {
            "dataset_id": args.dataset_id,
            "snapshot_type": args.snapshot_type,
            "strategy_name": args.strategy_name,
            "random_seed": args.seed,
            "crowdingBlockThreshold": args.crowding_block_threshold,
            "lookbackBars": args.lookback_bars,
            "persistenceBars": args.persistence_bars,
            "breadthMinStocks": args.breadth_min_stocks,
            "minThemeCoverage": args.min_theme_coverage,
            "maxThemeExposure": args.max_theme_exposure,
        }
        print_json(BacktestService(session).run_theme_trend(payload))


def cmd_run_theme_confluence(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        payload = {
            "dataset_id": args.dataset_id,
            "snapshot_type": args.snapshot_type,
            "strategy_name": args.strategy_name,
            "random_seed": args.seed,
            "maxThemeCrowding": args.max_theme_crowding,
            "rankTrendWeight": args.rank_trend_weight,
            "themeWeight": args.theme_weight,
            "lookbackBars": args.lookback_bars,
        }
        print_json(BacktestService(session).run_theme_confluence(payload))


def cmd_optimize_theme_trend(args: argparse.Namespace) -> None:
    payload = {
        "dataset_id": args.dataset_id,
        "snapshot_type": args.snapshot_type,
        "strategy_name": args.strategy_name,
        "method": args.method,
        "random_seed": args.seed,
        "trials": args.trials,
        "objective": args.objective,
    }
    with runtime_session() as session:
        print_json(OptimizationService(session).run_theme_trend(payload))


def cmd_optimize_theme_confluence(args: argparse.Namespace) -> None:
    payload = {
        "dataset_id": args.dataset_id,
        "snapshot_type": args.snapshot_type,
        "strategy_name": args.strategy_name,
        "method": args.method,
        "random_seed": args.seed,
        "trials": args.trials,
        "objective": args.objective,
    }
    if args.parameter_grid:
        payload["parameterGrid"] = json_loads(args.parameter_grid, {})
    with runtime_session() as session:
        print_json(OptimizationService(session).run_theme_confluence(payload, wait=not args.no_wait))


def cmd_compare_backtests(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        try:
            print_json(BacktestService(session).compare_runs(args.run_ids, parse_csv_list(args.metrics)))
        except LookupError as error:
            print_json({"ok": False, "error": {"code": "backtest_run_not_found", "runId": str(error.args[0])}})
            sys.exit(1)
        except ValueError as error:
            detail = error.args[0] if error.args and isinstance(error.args[0], dict) else {"code": "backtest_compare_failed", "message": str(error)}
            print_json({"ok": False, "error": detail})
            sys.exit(1)


def cmd_export_report(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        service = BacktestService(session)
        output = Path(args.output)
        if args.format == "jsonl-bundle":
            result = service.export_report_bundle(args.run_id, output)
            print_json({**result, "output": str(output)})
            if not result.get("ok"):
                sys.exit(1)
            return
        if args.format == "json.gz":
            result = service.export_report_gzip(args.run_id, output)
            print_json({**result, "output": str(output)})
            if not result.get("ok"):
                sys.exit(1)
            return

        report = service.export_report(args.run_id)
        if report is None:
            print_json({"ok": False, "error": {"code": "backtest_run_not_found", "runId": args.run_id}})
            sys.exit(1)
        report = {**report, "exportedAt": datetime.now(timezone.utc).isoformat()}
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print_json({"ok": True, "runId": args.run_id, "format": "legacy-json", "output": str(output)})


def cmd_optimize_ranktrend(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        payload = {
            "dataset_id": args.dataset_id,
            "snapshot_type": args.snapshot_type,
            "strategy_name": args.strategy_name,
            "method": args.method,
            "random_seed": args.seed,
            "max_trials": args.trials,
            "objective": args.objective,
            "validation_mode": args.validation_mode,
            "validation_ratio": args.validation_ratio,
            "validation_warmup_bars": args.validation_warmup_bars,
            "train_range": [args.train_start, args.train_end] if args.train_start or args.train_end else None,
            "validation_range": [args.validation_start, args.validation_end] if args.validation_start or args.validation_end else None,
            "walk_forward": {
                "enabled": args.walk_forward,
                "trainWindowDays": args.walk_forward_train_days,
                "validationWindowDays": args.walk_forward_validation_days,
                "stepDays": args.walk_forward_step_days,
                "topTrials": args.walk_forward_top_trials,
            },
        }
        print_json(OptimizationService(session).run_ranktrend(payload, wait=not args.no_wait))


def cmd_research_ranktrend_jump(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        payload = {
            "dataset_id": args.dataset_id,
            "snapshot_type": args.snapshot_type,
            "random_seed": args.seed,
            "trials": args.trials,
            "fillFallbackMode": args.fill_fallback_mode,
            "validationRatio": args.validation_ratio,
            "walkForwardTrainDays": args.walk_forward_train_days,
            "walkForwardValidationDays": args.walk_forward_validation_days,
            "walkForwardStepDays": args.walk_forward_step_days,
        }
        print_json(OptimizationService(session).run_ranktrend_jump_research(payload))


def cmd_validate_golden(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        print_json(GoldenService(session).validate({"caseId": args.case_id, "path": args.path, "tolerance": args.tolerance}))


def cmd_show_report(args: argparse.Namespace) -> None:
    with runtime_session() as session:
        print_json(BacktestService(session).get_run(args.run_id) or {"error": "run not found"})


def cmd_audit_ranktrend_live_gates(args: argparse.Namespace) -> None:
    payload = {
        "dataset_id": args.dataset_id,
        "snapshot_type": args.snapshot_type,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "focus_codes": args.focus_code or DEFAULT_LIVE_GATE_AUDIT_FOCUS_CODES,
        "anchor_samples": load_hotlist_anchor_samples(args.anchor_file) if args.anchor_file else [],
        "confidence_thresholds": args.confidence_thresholds,
        "research_all_frames": args.research_all_frames,
    }
    with runtime_session() as session:
        result = RankTrendLiveGateAuditService(session).run(payload)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print_json(result)


# ── Snapshot Collector CLI handlers ────────────────────────────────────────────


class _BackfillRequest:
    """Simple namespace for the backfill_slots service call."""

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


def _result_to_output(result: Any) -> dict[str, Any]:
    """Convert a CollectorRunResult to a JSON-safe output dict."""
    output: dict[str, Any] = {
        "status": result.status,
        "snapshotId": result.snapshot_id,
        "runId": result.run_id,
        "dryRun": result.dry_run,
        "deduped": result.deduped,
        "message": result.message,
    }
    if result.details:
        output["details"] = result.details
    if result.quality is not None:
        output["quality"] = {
            "ok": result.quality.ok,
            "blockingIssues": result.quality.blocking_issues,
            "warnings": result.quality.warnings,
            "sourceCounts": result.quality.source_counts,
        }
    return output


def _generate_backfill_slots(
    snapshot_type: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, str]]:
    """Generate slot dicts for every trading date in [start_date, end_date]."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if start > end:
        raise ValueError(
            f"startDate ({start_date}) must not be after endDate ({end_date})"
        )

    slot_dicts: list[dict[str, str]] = []
    current = start
    while current <= end:
        if not is_trading_day(current.date()):
            current += timedelta(days=1)
            continue
        date_str = current.strftime("%Y-%m-%d")
        slots = generate_slots(date_str, [snapshot_type])
        for slot in slots:
            slot_dicts.append(
                {"trading_date": slot.trading_date, "slot_time": slot.slot_time}
            )
        current += timedelta(days=1)
    return slot_dicts


def _create_snapshot_collector_service(repo: Any) -> SnapshotCollectorService:
    """Create the collector service through the shared dependency factory."""
    return create_snapshot_collector_service(repo)


def _collector_shadow_dataset_error(dataset_id: str) -> dict[str, Any] | None:
    """Return a JSON error when a write command targets a non-shadow dataset."""
    if dataset_id == SHADOW_DATASET_ID:
        return None
    settings = get_settings()
    allow_live = bool(getattr(settings, "snapshot_collector_allow_live_dataset", False))
    if dataset_id == LIVE_DATASET_ID and allow_live:
        return None
    return {
        "ok": False,
        "status": "error",
        "error": f"snapshot collector only writes {SHADOW_DATASET_ID}",
    }


def cmd_snapshot_collector_status(_: argparse.Namespace) -> None:
    """Print collector operational state as JSON."""
    repo = create_snapshot_collector_repository()
    service = _create_snapshot_collector_service(repo)
    print_json(service.get_status())


def cmd_snapshot_collector_run_once(args: argparse.Namespace) -> None:
    """Execute a single snapshot collection run and print JSON result."""
    if error := _collector_shadow_dataset_error(args.dataset_id):
        print_json(error)
        return

    request = CollectorRunRequest(
        dataset_id=args.dataset_id,
        snapshot_type=args.snapshot_type,
        trading_date=args.trading_date,
        slot_time=args.slot_time,
        dry_run=bool(args.dry_run),
        force=bool(args.force),
    )
    repo = create_snapshot_collector_repository()
    service = _create_snapshot_collector_service(repo)
    result = service.run_once(request)
    print_json(_result_to_output(result))


def cmd_snapshot_collector_backfill(args: argparse.Namespace) -> None:
    """Run collection for multiple slots across a date range and print JSON result."""
    if error := _collector_shadow_dataset_error(args.dataset_id):
        print_json(error)
        return

    # Generate all slots for the date range
    slot_dicts = _generate_backfill_slots(
        args.snapshot_type,
        args.start_date,
        args.end_date,
    )

    if not slot_dicts:
        print_json({
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "blocked": 0,
            "deduped": 0,
            "details": [],
        })
        return

    backfill_request = _BackfillRequest(
        dataset_id=args.dataset_id,
        snapshot_type=args.snapshot_type,
        slots=slot_dicts,
        dry_run=bool(args.dry_run),
        force=bool(args.force),
    )

    repo = create_snapshot_collector_repository()
    service = _create_snapshot_collector_service(repo)
    result = service.backfill_slots(backfill_request)
    print_json(result)


def cmd_snapshot_collector_audit(args: argparse.Namespace) -> None:
    """Audit snapshot coverage and print structured JSON result."""
    repo = create_snapshot_collector_repository()
    service = _create_snapshot_collector_service(repo)
    result = service.audit(
        args.dataset_id,
        args.snapshot_type,
        trading_date=getattr(args, "trading_date", None),
    )
    print_json(result)


def cmd_snapshot_collector_compare(args: argparse.Namespace) -> None:
    """Compare snapshot data between two datasets and print structured diff."""
    repo = create_snapshot_collector_repository()
    service = _create_snapshot_collector_service(repo)
    result = service.compare(
        args.dataset_id_a,
        args.dataset_id_b,
        args.snapshot_type,
        trading_date=getattr(args, "trading_date", None),
    )
    print_json(result)


def cmd_snapshot_collector_scheduler_status(_: argparse.Namespace) -> None:
    """Print scheduler operational state as JSON."""
    from backend.snapshot_collector.scheduler import snapshot_collector_scheduler

    print_json(snapshot_collector_scheduler.status())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quant-board", description="QuantBoard CLI")
    sub = parser.add_subparsers(required=True)

    build_dataset_cmd = sub.add_parser("build-dataset", help="Build a research dataset from SQLite snapshot tables")
    build_dataset_cmd.add_argument("--source-dataset-id", default="dragonboard_live")
    build_dataset_cmd.add_argument("--name", default=None)
    build_dataset_cmd.add_argument("--snapshot-type", action="append", default=None)
    build_dataset_cmd.add_argument("--start-date", default=None)
    build_dataset_cmd.add_argument("--end-date", default=None)
    build_dataset_cmd.add_argument("--max-snapshots", type=int, default=None)
    build_dataset_cmd.add_argument("--dry-run", action="store_true")
    build_dataset_cmd.set_defaults(func=cmd_build_dataset)

    import_cmd = sub.add_parser("import-idb", help="Compatibility import for legacy IndexedDB/JSON snapshot bundles")
    import_cmd.add_argument("--source", choices=["leveldb", "browser_bridge", "json_bundle"], default="leveldb")
    import_cmd.add_argument("--path", default=None)
    import_cmd.add_argument("--name", default=None)
    import_cmd.add_argument("--snapshot-type", action="append", default=["half_hour"])
    import_cmd.add_argument("--start-date", default=None)
    import_cmd.add_argument("--end-date", default=None)
    import_cmd.set_defaults(func=cmd_import_idb)

    list_cmd = sub.add_parser("list-datasets", help="List datasets")
    list_cmd.set_defaults(func=cmd_list_datasets)

    push_backup_cmd = sub.add_parser("push-backup", help="Push SQLite records to Supabase backup")
    push_backup_cmd.add_argument("--full-history", action="store_true")
    push_backup_cmd.set_defaults(func=cmd_push_backup)

    push_outbox_cmd = sub.add_parser("push-outbox", help="Push due sync_outbox rows to Supabase backup")
    push_outbox_cmd.add_argument("--limit", type=int, default=50)
    push_outbox_cmd.set_defaults(func=cmd_push_outbox)

    pull_backup_cmd = sub.add_parser("pull-backup", help="Pull Supabase backup records into SQLite")
    pull_backup_cmd.set_defaults(func=cmd_pull_backup)

    smoke_backup_cmd = sub.add_parser("smoke-backup", help="Run Supabase backup write/read/delete smoke test")
    smoke_backup_cmd.set_defaults(func=cmd_smoke_backup)

    prune_backup_cmd = sub.add_parser("prune-backup", help="Prune Supabase backup to retention window")
    prune_backup_cmd.add_argument("--dry-run", action="store_true")
    prune_backup_cmd.set_defaults(func=cmd_prune_backup)

    migrate_cmd = sub.add_parser("migrate-snapshots", help="Import historical DragonBoard snapshot JSON into SQLite")
    migrate_cmd.add_argument("--path", required=True)
    migrate_cmd.add_argument("--source-type", choices=["json_bundle", "leveldb", "browser_bridge"], default="json_bundle")
    migrate_cmd.add_argument("--dataset-id", default="dragonboard_history")
    migrate_cmd.add_argument("--name", default=None)
    migrate_cmd.add_argument("--idempotency-key", default=None)
    migrate_cmd.add_argument("--source", default="dragon_board_history_migration")
    migrate_cmd.add_argument("--dry-run", action="store_true")
    migrate_cmd.set_defaults(func=cmd_migrate_snapshots)

    verify_themes_cmd = sub.add_parser("verify-themes", help="Verify historical DragonBoard theme JSON against themeDATA.db")
    verify_themes_cmd.add_argument("--path", required=True)
    verify_themes_cmd.set_defaults(func=cmd_verify_themes)

    inspect_cmd = sub.add_parser("inspect-storage", help="Inspect SQLite files and JSON field sizes")
    inspect_cmd.add_argument("--path", default=None)
    inspect_cmd.set_defaults(func=cmd_inspect_storage)

    legacy_cmd = sub.add_parser("migrate-legacy-db", help="Split legacy quant_board.db into snapshot and research DBs")
    legacy_cmd.add_argument("--source", required=True)
    legacy_cmd.add_argument("--snapshot-database-url", default=None)
    legacy_cmd.add_argument("--research-database-url", default=None)
    legacy_cmd.add_argument("--apply", action="store_true")
    legacy_cmd.set_defaults(func=cmd_migrate_legacy_db)

    compact_cmd = sub.add_parser("compact-json-fields", help="Compress large SQLite JSON text fields")
    compact_cmd.add_argument("--database-url", default=None)
    compact_cmd.add_argument("--threshold", type=int, default=4096)
    compact_cmd.add_argument("--batch-size", type=int, default=500)
    compact_cmd.add_argument("--apply", action="store_true")
    compact_cmd.add_argument("--vacuum", action="store_true")
    compact_cmd.set_defaults(func=cmd_compact_json_fields)

    archive_snapshots_cmd = sub.add_parser("archive-snapshots", help="Archive SQLite snapshot detail rows to Parquet")
    archive_snapshots_cmd.add_argument("--dataset-id", default="dragonboard_live")
    archive_snapshots_cmd.add_argument("--snapshot-type", default="half_hour")
    archive_snapshots_cmd.add_argument("--before-trading-date", required=True)
    archive_snapshots_cmd.add_argument("--max-partitions", type=int, default=None)
    archive_snapshots_cmd.add_argument("--dry-run", action="store_true")
    archive_snapshots_cmd.add_argument("--apply", action="store_true")
    archive_snapshots_cmd.set_defaults(func=cmd_archive_snapshots)

    archive_research_cmd = sub.add_parser("archive-research", help="Archive research detail rows to Parquet")
    archive_research_cmd.add_argument("--run-id", default=None)
    archive_research_cmd.add_argument("--older-than-days", type=int, default=30)
    archive_research_cmd.add_argument("--keep-latest-per-group", type=int, default=10)
    archive_research_cmd.add_argument("--dry-run", action="store_true")
    archive_research_cmd.add_argument("--apply", action="store_true")
    archive_research_cmd.set_defaults(func=cmd_archive_research)

    verify_archive_cmd = sub.add_parser("verify-archive", help="Verify a Parquet archive manifest")
    verify_archive_cmd.add_argument("--archive-id", required=True)
    verify_archive_cmd.set_defaults(func=cmd_verify_archive)

    restore_archive_cmd = sub.add_parser("restore-archive", help="Restore a Parquet archive into SQLite")
    restore_archive_cmd.add_argument("--archive-id", required=True)
    restore_archive_cmd.add_argument("--dry-run", action="store_true")
    restore_archive_cmd.add_argument("--apply", action="store_true")
    restore_archive_cmd.set_defaults(func=cmd_restore_archive)

    archive_auto_cmd = sub.add_parser("archive-auto-once", help="Run one automatic archive cycle")
    archive_auto_cmd.add_argument("--limit", type=int, default=None)
    archive_auto_cmd.set_defaults(func=cmd_archive_auto_once)

    smoke_object_cmd = sub.add_parser("smoke-object-backup", help="Run R2/S3 object backup smoke test")
    smoke_object_cmd.set_defaults(func=cmd_smoke_object_backup)

    push_archive_cmd = sub.add_parser("push-archive-backup", help="Push local Parquet archives to R2/S3 object storage")
    push_archive_cmd.add_argument("--limit", type=int, default=None)
    push_archive_cmd.set_defaults(func=cmd_push_archive_backup)

    backup_day_cmd = sub.add_parser("backup-snapshot-day", help="Backup one trading day's SQLite snapshots to R2/S3 without deleting SQLite rows")
    backup_day_cmd.add_argument("--dataset-id", default="dragonboard_live")
    backup_day_cmd.add_argument("--snapshot-type", default="half_hour")
    backup_day_cmd.add_argument("--trading-date", default=None)
    backup_day_cmd.add_argument("--dry-run", action="store_true")
    backup_day_cmd.set_defaults(func=cmd_backup_snapshot_day)

    after_market_cmd = sub.add_parser("after-market-once", help="Run after-market archive, R2 push, and Supabase prune pipeline")
    after_market_cmd.add_argument("--archive-limit", type=int, default=None)
    after_market_cmd.add_argument("--backup-limit", type=int, default=None)
    after_market_cmd.add_argument("--dry-run", action="store_true")
    after_market_cmd.set_defaults(func=cmd_after_market_once)

    migrate_mongodb_cmd = sub.add_parser("migrate-mongodb", help="Inspect SQLite sources for one-shot MongoDB migration")
    migrate_mongodb_cmd.add_argument("--snapshot-db", default=None)
    migrate_mongodb_cmd.add_argument("--research-db", default=None)
    migrate_mongodb_cmd.add_argument("--theme-db", default=None)
    migrate_mongodb_cmd.add_argument("--stock-json", default=None)
    migrate_mongodb_cmd.add_argument("--target-database", default=None)
    migrate_mongodb_cmd.add_argument("--batch-size", type=int, default=1000)
    migrate_mongodb_cmd.add_argument("--dry-run", action="store_true")
    migrate_mongodb_cmd.add_argument("--apply", action="store_true")
    migrate_mongodb_cmd.add_argument("--replace-confirmed", action="store_true")
    migrate_mongodb_cmd.add_argument("--skip-research", action="store_true")
    migrate_mongodb_cmd.set_defaults(func=cmd_migrate_mongodb)

    inspect_mongodb_cmd = sub.add_parser("inspect-mongodb", help="Inspect MongoDB collection counts and indexes")
    inspect_mongodb_cmd.set_defaults(func=cmd_inspect_mongodb)

    verify_mongodb_migration_cmd = sub.add_parser("verify-mongodb-migration", help="Verify MongoDB migration counts, indexes, and snapshot continuity")
    verify_mongodb_migration_cmd.add_argument("--dataset-id", default="dragonboard_live")
    verify_mongodb_migration_cmd.add_argument("--snapshot-type", default="half_hour")
    verify_mongodb_migration_cmd.add_argument("--code", action="append", default=[])
    verify_mongodb_migration_cmd.set_defaults(func=cmd_verify_mongodb_migration)

    cleanup_mongodb_cmd = sub.add_parser("cleanup-mongodb-datasets", help="Preview or delete non-kept MongoDB datasets and derived research rows")
    cleanup_mongodb_cmd.add_argument("--keep-dataset-id", action="append", default=["dragonboard_live"])
    cleanup_mongodb_cmd.add_argument("--apply", action="store_true")
    cleanup_mongodb_cmd.set_defaults(func=cmd_cleanup_mongodb_datasets)

    backfill_mongodb_cmd = sub.add_parser("backfill-empty-mongodb-snapshots", help="Preview or repair MongoDB formal snapshots: empty rows, missing records, count drift, missing slots, and missing indexes")
    backfill_mongodb_cmd.add_argument("--dataset-id", default="dragonboard_live")
    backfill_mongodb_cmd.add_argument("--snapshot-id", action="append", default=None)
    backfill_mongodb_cmd.add_argument("--apply", action="store_true")
    backfill_mongodb_cmd.set_defaults(func=cmd_backfill_empty_mongodb_snapshots)

    backfill_jump_cmd = sub.add_parser("backfill-jump-fields", help="Backfill jumpDirection/jumpConfidence in snapshot_stock_rows from compRank history")
    backfill_jump_cmd.add_argument("--dataset-id", default="dragonboard_live")
    backfill_jump_cmd.add_argument("--trading-date", action="append", default=[])
    backfill_jump_cmd.add_argument("--apply", action="store_true")
    backfill_jump_cmd.set_defaults(func=cmd_backfill_jump_fields)

    copy_missing_mongodb_slot_cmd = sub.add_parser("copy-missing-mongodb-snapshot-slots", help="Preview or copy missing MongoDB snapshot slots from a donor dataset")
    copy_missing_mongodb_slot_cmd.add_argument("--target-dataset-id", required=True)
    copy_missing_mongodb_slot_cmd.add_argument("--donor-dataset-id", required=True)
    copy_missing_mongodb_slot_cmd.add_argument("--snapshot-id", action="append", required=True)
    copy_missing_mongodb_slot_cmd.add_argument("--apply", action="store_true")
    copy_missing_mongodb_slot_cmd.set_defaults(func=cmd_copy_missing_mongodb_snapshot_slots)

    repair_mongodb_research_cmd = sub.add_parser("repair-mongodb-research-metadata", help="Preview or repair MongoDB research metadata and test theme pollution")
    repair_mongodb_research_cmd.add_argument("--apply", action="store_true")
    repair_mongodb_research_cmd.set_defaults(func=cmd_repair_mongodb_research_metadata)

    backup_mongodb_cmd = sub.add_parser("backup-mongodb", help="Create a full or light local MongoDB backup")
    backup_mongodb_cmd.add_argument("--full", action="store_true")
    backup_mongodb_cmd.add_argument("--light", action="store_true")
    backup_mongodb_cmd.set_defaults(func=cmd_backup_mongodb)

    verify_mongodb_backup_cmd = sub.add_parser("verify-mongodb-backup", help="Verify a local MongoDB backup")
    verify_mongodb_backup_cmd.add_argument("--backup-id", required=True)
    verify_mongodb_backup_cmd.set_defaults(func=cmd_verify_mongodb_backup)

    verify_mongodb_restore_cmd = sub.add_parser("verify-mongodb-restore-staging", help="Verify a pulled MongoDB backup under restore-staging")
    verify_mongodb_restore_cmd.add_argument("--backup-id", required=True)
    verify_mongodb_restore_cmd.set_defaults(func=cmd_verify_mongodb_restore_staging)

    push_mongodb_backup_cmd = sub.add_parser("push-mongodb-backup", help="Push a verified MongoDB backup to R2/S3")
    push_mongodb_backup_cmd.add_argument("--backup-id", required=True)
    push_mongodb_backup_cmd.set_defaults(func=cmd_push_mongodb_backup)

    pull_mongodb_backup_cmd = sub.add_parser("pull-mongodb-backup", help="Pull a MongoDB backup into restore-staging")
    pull_mongodb_backup_cmd.add_argument("--backup-id", required=True)
    pull_mongodb_backup_cmd.add_argument("--dry-run", action="store_true")
    pull_mongodb_backup_cmd.set_defaults(func=cmd_pull_mongodb_backup)

    list_mongodb_backups_cmd = sub.add_parser("list-mongodb-backups", help="List local MongoDB backups")
    list_mongodb_backups_cmd.set_defaults(func=cmd_list_mongodb_backups)

    prune_mongodb_backups_cmd = sub.add_parser("prune-mongodb-backups", help="Prune old local MongoDB backup files")
    prune_mongodb_backups_cmd.add_argument("--dry-run", action="store_true")
    prune_mongodb_backups_cmd.set_defaults(func=cmd_prune_mongodb_backups)

    pull_archive_cmd = sub.add_parser("pull-archive-backup", help="Pull Parquet archives from R2/S3 into local storage")
    pull_archive_cmd.add_argument("--archive-id", required=True)
    pull_archive_cmd.add_argument("--dry-run", action="store_true")
    pull_archive_cmd.add_argument("--apply", action="store_true")
    pull_archive_cmd.set_defaults(func=cmd_pull_archive_backup)

    verify_cmd = sub.add_parser("verify-snapshot-migration", help="Verify migrated snapshot row counts")
    verify_cmd.add_argument("--dataset-id", required=True)
    verify_cmd.add_argument("--source-report", required=True)
    verify_cmd.set_defaults(func=cmd_verify_snapshot_migration)

    inspect_research_cmd = sub.add_parser("inspect-research-storage", help="Inspect local research SQLite table counts")
    inspect_research_cmd.set_defaults(func=cmd_inspect_research_storage)

    delete_backtest_cmd = sub.add_parser("delete-backtest", help="Delete one backtest run and normalized result rows")
    delete_backtest_cmd.add_argument("--run-id", required=True)
    delete_backtest_cmd.set_defaults(func=cmd_delete_backtest)

    cleanup_research_cmd = sub.add_parser("cleanup-research", help="Preview or delete old local research backtest runs")
    cleanup_research_cmd.add_argument("--older-than-days", type=int, default=30)
    cleanup_research_cmd.add_argument("--keep-latest-per-group", type=int, default=10)
    cleanup_research_cmd.add_argument("--dataset-id", default=None)
    cleanup_research_cmd.add_argument("--snapshot-type", choices=["quarter_hour", "half_hour"], default=None)
    cleanup_research_cmd.add_argument("--include-failed", action="store_true")
    cleanup_research_cmd.add_argument("--apply", action="store_true")
    cleanup_research_cmd.add_argument("--vacuum", action="store_true")
    cleanup_research_cmd.set_defaults(func=cmd_cleanup_research)

    audit_live_gates_cmd = sub.add_parser("audit-ranktrend-live-gates", help="Audit RankTrend live gate shadow variants")
    audit_live_gates_cmd.add_argument("--dataset-id", required=True)
    audit_live_gates_cmd.add_argument("--snapshot-type", choices=["quarter_hour", "half_hour"], default="half_hour")
    audit_live_gates_cmd.add_argument("--start-date", default=None)
    audit_live_gates_cmd.add_argument("--end-date", default=None)
    audit_live_gates_cmd.add_argument("--focus-code", action="append", default=[])
    audit_live_gates_cmd.add_argument("--anchor-file", default=None)
    audit_live_gates_cmd.add_argument(
        "--confidence-thresholds",
        type=parse_float_list,
        default=DEFAULT_LIVE_GATE_AUDIT_CONFIDENCE_THRESHOLDS,
    )
    audit_live_gates_cmd.add_argument("--research-all-frames", action="store_true")
    audit_live_gates_cmd.add_argument("--output", default=None)
    audit_live_gates_cmd.set_defaults(func=cmd_audit_ranktrend_live_gates)

    run_cmd = sub.add_parser("run-ranktrend", help="Run RankTrend backtest")
    run_cmd.add_argument("--dataset-id", required=True)
    run_cmd.add_argument("--snapshot-type", choices=["quarter_hour", "half_hour"], default="half_hour")
    run_cmd.add_argument("--start-date", default=None)
    run_cmd.add_argument("--end-date", default=None)
    run_cmd.add_argument("--strategy-name", default="rank_trend_candidate")
    run_cmd.add_argument("--seed", type=int, default=20260430)
    run_cmd.add_argument("--no-trade-simulation", action="store_true")
    run_cmd.add_argument("--initial-cash", type=float, default=1000000)
    run_cmd.add_argument("--max-positions", type=int, default=5)
    run_cmd.add_argument("--position-size", type=float, default=0.2)
    run_cmd.add_argument("--target-holding-days", type=float, default=5)
    run_cmd.add_argument("--max-holding-bars", type=int, default=None)
    run_cmd.add_argument("--take-profit-pct", type=float, default=None)
    run_cmd.add_argument("--stop-loss-pct", type=float, default=None)
    run_cmd.add_argument("--fee-rate", type=float, default=0.0003)
    run_cmd.add_argument("--stamp-tax-rate", type=float, default=0.0005)
    run_cmd.add_argument("--slippage-rate", type=float, default=0.001)
    run_cmd.add_argument("--no-t1", action="store_true")
    run_cmd.add_argument("--macd-fast", type=int, default=21)
    run_cmd.add_argument("--macd-slow", type=int, default=34)
    run_cmd.add_argument("--macd-signal", type=int, default=13)
    run_cmd.add_argument("--momentum-periods", type=parse_int_list, default=DEFAULT_MOMENTUM_PERIODS)
    run_cmd.add_argument("--horizons", type=parse_int_list, default=DEFAULT_HORIZONS)
    run_cmd.add_argument("--execution-mode", choices=["current_bar", "next_bar"], default="current_bar")
    run_cmd.add_argument("--no-order-book-price", action="store_true")
    run_cmd.add_argument("--no-limit-status", action="store_true")
    run_cmd.add_argument("--no-volume-limit", action="store_true")
    run_cmd.add_argument("--no-order-book-queue", action="store_true")
    run_cmd.add_argument("--no-partial-fills", action="store_true")
    run_cmd.add_argument("--volume-participation-rate", type=float, default=None)
    run_cmd.add_argument("--order-book-participation-rate", type=float, default=0.3)
    run_cmd.add_argument("--no-intrabar-stops", action="store_true")
    run_cmd.add_argument("--intrabar-ambiguity", choices=["stop_first", "take_first"], default="stop_first")
    run_cmd.add_argument("--use-theme-factor-for-execution", action="store_true")
    run_cmd.add_argument("--exclude-non-positive-price-rows", action="store_true")
    run_cmd.add_argument("--exclude-cross-market-zero-price-rows", action="store_true")
    run_cmd.add_argument("--exclude-all-zero-price-frames", action="store_true")
    run_cmd.set_defaults(func=cmd_run_ranktrend)

    longtest_cmd = sub.add_parser("run-longtest-baselines", help="Run fixed long-test RankTrend baseline set")
    longtest_cmd.add_argument("--dataset-id", default="dragonboard_live")
    longtest_cmd.add_argument("--start-date", default=None)
    longtest_cmd.add_argument("--end-date", default=None)
    longtest_cmd.add_argument("--baseline-set", choices=sorted(LONGTEST_BASELINE_SETS), default=DEFAULT_LONGTEST_BASELINE_SET)
    longtest_cmd.add_argument("--strategy-name", default="rank_trend_candidate")
    longtest_cmd.add_argument("--seed", type=int, default=20260430)
    longtest_cmd.add_argument("--initial-cash", type=float, default=1000000)
    longtest_cmd.add_argument("--max-positions", type=int, default=5)
    longtest_cmd.add_argument("--position-size", type=float, default=0.2)
    longtest_cmd.add_argument("--target-holding-days", type=float, default=5)
    longtest_cmd.add_argument("--take-profit-pct", type=float, default=0.12)
    longtest_cmd.add_argument("--stop-loss-pct", type=float, default=0.06)
    longtest_cmd.add_argument("--fee-rate", type=float, default=0.0003)
    longtest_cmd.add_argument("--stamp-tax-rate", type=float, default=0.0005)
    longtest_cmd.add_argument("--slippage-rate", type=float, default=0.001)
    longtest_cmd.add_argument("--macd-fast", type=int, default=21)
    longtest_cmd.add_argument("--macd-slow", type=int, default=34)
    longtest_cmd.add_argument("--macd-signal", type=int, default=13)
    longtest_cmd.add_argument("--momentum-periods", type=parse_int_list, default=DEFAULT_MOMENTUM_PERIODS)
    longtest_cmd.add_argument("--horizons", type=parse_int_list, default=DEFAULT_HORIZONS)
    longtest_cmd.add_argument("--volume-participation-rate", type=float, default=0.05)
    longtest_cmd.add_argument("--order-book-participation-rate", type=float, default=0.3)
    longtest_cmd.add_argument("--intrabar-ambiguity", choices=["stop_first", "take_first"], default="stop_first")
    longtest_cmd.add_argument("--exclude-non-positive-price-rows", action="store_true")
    longtest_cmd.add_argument("--exclude-cross-market-zero-price-rows", action="store_true")
    longtest_cmd.add_argument("--exclude-all-zero-price-frames", action="store_true")
    longtest_cmd.add_argument("--checkpoint-id", default=None)
    longtest_cmd.add_argument("--output", default=None)
    longtest_cmd.add_argument("--dry-run", action="store_true")
    longtest_cmd.set_defaults(func=cmd_run_longtest_baselines)

    theme_run_cmd = sub.add_parser("run-theme-trend", help="Run ThemeTrend backtest")
    theme_run_cmd.add_argument("--dataset-id", required=True)
    theme_run_cmd.add_argument("--snapshot-type", choices=["quarter_hour", "half_hour"], default="half_hour")
    theme_run_cmd.add_argument("--strategy-name", default="theme_rotation")
    theme_run_cmd.add_argument("--seed", type=int, default=20260430)
    theme_run_cmd.add_argument("--crowding-block-threshold", type=int, default=75)
    theme_run_cmd.add_argument("--lookback-bars", type=int, default=8)
    theme_run_cmd.add_argument("--persistence-bars", type=int, default=3)
    theme_run_cmd.add_argument("--breadth-min-stocks", type=int, default=5)
    theme_run_cmd.add_argument("--min-theme-coverage", type=float, default=0.7)
    theme_run_cmd.add_argument("--max-theme-exposure", type=float, default=0.45)
    theme_run_cmd.set_defaults(func=cmd_run_theme_trend)

    confluence_run_cmd = sub.add_parser("run-theme-confluence", help="Run ThemeConfluence backtest")
    confluence_run_cmd.add_argument("--dataset-id", required=True)
    confluence_run_cmd.add_argument("--snapshot-type", choices=["quarter_hour", "half_hour"], default="half_hour")
    confluence_run_cmd.add_argument("--strategy-name", default="hotlist_theme_confluence")
    confluence_run_cmd.add_argument("--seed", type=int, default=20260430)
    confluence_run_cmd.add_argument("--rank-trend-weight", type=float, default=0.65)
    confluence_run_cmd.add_argument("--theme-weight", type=float, default=0.35)
    confluence_run_cmd.add_argument("--max-theme-crowding", type=int, default=85)
    confluence_run_cmd.add_argument("--lookback-bars", type=int, default=8)
    confluence_run_cmd.set_defaults(func=cmd_run_theme_confluence)

    opt_cmd = sub.add_parser("optimize-ranktrend", help="Run RankTrend optimization")
    opt_cmd.add_argument("--dataset-id", required=True)
    opt_cmd.add_argument("--snapshot-type", default="half_hour")
    opt_cmd.add_argument("--strategy-name", default="rank_trend_candidate")
    opt_cmd.add_argument("--method", choices=["grid", "random", "bayesian", "tpe"], default="grid")
    opt_cmd.add_argument("--seed", type=int, default=20260430)
    opt_cmd.add_argument("--trials", type=int, default=12)
    opt_cmd.add_argument("--objective", choices=["sharpe", "return", "max_drawdown", "win_rate", "risk_adjusted", "stability"], default="sharpe")
    opt_cmd.add_argument("--validation-mode", choices=["none", "auto", "auto_split", "ratio", "chronological"], default="none")
    opt_cmd.add_argument("--validation-ratio", type=float, default=0.3)
    opt_cmd.add_argument("--validation-warmup-bars", type=int, default=40)
    opt_cmd.add_argument("--train-start", default=None)
    opt_cmd.add_argument("--train-end", default=None)
    opt_cmd.add_argument("--validation-start", default=None)
    opt_cmd.add_argument("--validation-end", default=None)
    opt_cmd.add_argument("--walk-forward", action="store_true")
    opt_cmd.add_argument("--walk-forward-train-days", type=int, default=5)
    opt_cmd.add_argument("--walk-forward-validation-days", type=int, default=1)
    opt_cmd.add_argument("--walk-forward-step-days", type=int, default=1)
    opt_cmd.add_argument("--walk-forward-top-trials", type=int, default=5)
    opt_cmd.add_argument("--no-wait", action="store_true")
    opt_cmd.set_defaults(func=cmd_optimize_ranktrend)

    jump_research_cmd = sub.add_parser("research-ranktrend-jump", help="Run RankTrend Jump TPE research")
    jump_research_cmd.add_argument("--dataset-id", required=True)
    jump_research_cmd.add_argument("--snapshot-type", default="half_hour")
    jump_research_cmd.add_argument("--seed", type=int, default=20260430)
    jump_research_cmd.add_argument("--trials", type=int, default=24)
    jump_research_cmd.add_argument("--fill-fallback-mode", choices=["strict_fill", "fallback_penalized", "blocked_fill"], default="fallback_penalized")
    jump_research_cmd.add_argument("--validation-ratio", type=float, default=0.3)
    jump_research_cmd.add_argument("--walk-forward-train-days", type=int, default=8)
    jump_research_cmd.add_argument("--walk-forward-validation-days", type=int, default=2)
    jump_research_cmd.add_argument("--walk-forward-step-days", type=int, default=2)
    jump_research_cmd.set_defaults(func=cmd_research_ranktrend_jump)

    theme_opt_cmd = sub.add_parser("optimize-theme-trend", help="Run ThemeTrend optimization")
    theme_opt_cmd.add_argument("--dataset-id", required=True)
    theme_opt_cmd.add_argument("--snapshot-type", default="half_hour")
    theme_opt_cmd.add_argument("--strategy-name", default="theme_rotation")
    theme_opt_cmd.add_argument("--method", choices=["grid", "random", "bayesian", "tpe"], default="random")
    theme_opt_cmd.add_argument("--seed", type=int, default=20260430)
    theme_opt_cmd.add_argument("--trials", type=int, default=36)
    theme_opt_cmd.add_argument("--objective", default="stability")
    theme_opt_cmd.set_defaults(func=cmd_optimize_theme_trend)

    confluence_opt_cmd = sub.add_parser("optimize-theme-confluence", help="Run ThemeConfluence optimization")
    confluence_opt_cmd.add_argument("--dataset-id", required=True)
    confluence_opt_cmd.add_argument("--snapshot-type", default="half_hour")
    confluence_opt_cmd.add_argument("--strategy-name", default="hotlist_theme_confluence")
    confluence_opt_cmd.add_argument("--method", choices=["grid", "random", "bayesian", "tpe"], default="random")
    confluence_opt_cmd.add_argument("--seed", type=int, default=20260430)
    confluence_opt_cmd.add_argument("--trials", type=int, default=36)
    confluence_opt_cmd.add_argument("--objective", default="stability")
    confluence_opt_cmd.add_argument("--parameter-grid", default=None)
    confluence_opt_cmd.add_argument("--no-wait", action="store_true")
    confluence_opt_cmd.set_defaults(func=cmd_optimize_theme_confluence)

    golden_cmd = sub.add_parser("validate-golden", help="Validate golden case")
    golden_cmd.add_argument("--case-id", default=None)
    golden_cmd.add_argument("--path", default=None)
    golden_cmd.add_argument("--tolerance", type=float, default=1e-6)
    golden_cmd.set_defaults(func=cmd_validate_golden)

    report_cmd = sub.add_parser("show-report", help="Show backtest report")
    report_cmd.add_argument("--run-id", required=True)
    report_cmd.set_defaults(func=cmd_show_report)

    compare_cmd = sub.add_parser("compare-backtests", help="Compare backtest runs")
    compare_cmd.add_argument("--run-ids", nargs="+", required=True)
    compare_cmd.add_argument("--metrics", default="totalReturn,sharpe,maxDrawdown,winRate")
    compare_cmd.set_defaults(func=cmd_compare_backtests)

    export_cmd = sub.add_parser("export-report", help="Export a backtest report")
    export_cmd.add_argument("--run-id", required=True)
    export_cmd.add_argument("--output", required=True)
    export_cmd.add_argument(
        "--format",
        choices=("jsonl-bundle", "json.gz", "legacy-json"),
        default="jsonl-bundle",
        help="Report export format. Defaults to jsonl-bundle for large backtests.",
    )
    export_cmd.set_defaults(func=cmd_export_report)

    # ── Snapshot Collector commands ─────────────────────────────────────────

    collector_status_cmd = sub.add_parser("snapshot-collector-status", help="Show snapshot collector operational state")
    collector_status_cmd.set_defaults(func=cmd_snapshot_collector_status)

    collector_run_cmd = sub.add_parser("snapshot-collector-run-once", help="Execute a single snapshot collection run")
    collector_run_cmd.add_argument("--dataset-id", required=True)
    collector_run_cmd.add_argument("--snapshot-type", choices=["quarter_hour", "half_hour", "hourly", "daily"], required=True)
    collector_run_cmd.add_argument("--trading-date", required=True)
    collector_run_cmd.add_argument("--slot-time", required=True)
    collector_run_cmd.add_argument("--dry-run", action="store_true")
    collector_run_cmd.add_argument("--force", action="store_true")
    collector_run_cmd.set_defaults(func=cmd_snapshot_collector_run_once)

    collector_backfill_cmd = sub.add_parser("snapshot-collector-backfill", help="Run collection for all slots across a date range")
    collector_backfill_cmd.add_argument("--dataset-id", required=True)
    collector_backfill_cmd.add_argument("--snapshot-type", choices=["quarter_hour", "half_hour", "hourly", "daily"], required=True)
    collector_backfill_cmd.add_argument("--start-date", required=True)
    collector_backfill_cmd.add_argument("--end-date", required=True)
    collector_backfill_cmd.add_argument("--dry-run", dest="dry_run", action="store_true")
    collector_backfill_cmd.add_argument("--apply", dest="dry_run", action="store_false")
    collector_backfill_cmd.add_argument("--force", action="store_true")
    collector_backfill_cmd.set_defaults(func=cmd_snapshot_collector_backfill, dry_run=True)

    collector_audit_cmd = sub.add_parser("snapshot-collector-audit", help="Audit snapshot coverage for a dataset/type")
    collector_audit_cmd.add_argument("--dataset-id", required=True)
    collector_audit_cmd.add_argument("--snapshot-type", choices=["quarter_hour", "half_hour", "hourly", "daily"], required=True)
    collector_audit_cmd.add_argument("--trading-date", default=None)
    collector_audit_cmd.set_defaults(func=cmd_snapshot_collector_audit)

    collector_compare_cmd = sub.add_parser(
        "snapshot-collector-compare",
        help="Compare snapshot data between two datasets (e.g. shadow vs live)",
    )
    collector_compare_cmd.add_argument("--dataset-id-a", required=True, help="First dataset ID (e.g. dragonboard_live)")
    collector_compare_cmd.add_argument("--dataset-id-b", required=True, help="Second dataset ID (e.g. dragonboard_backend_shadow)")
    collector_compare_cmd.add_argument("--snapshot-type", choices=["quarter_hour", "half_hour", "hourly", "daily"], required=True)
    collector_compare_cmd.add_argument("--trading-date", default=None, help="Optional single date to compare")
    collector_compare_cmd.set_defaults(func=cmd_snapshot_collector_compare)

    scheduler_status_cmd = sub.add_parser(
        "snapshot-collector-scheduler-status",
        help="Show snapshot collector scheduler operational state",
    )
    scheduler_status_cmd.set_defaults(func=cmd_snapshot_collector_scheduler_status)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
