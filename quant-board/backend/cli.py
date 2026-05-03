from __future__ import annotations

import argparse
import json
from typing import Any

from backend.data.database import SessionLocal, init_db
from backend.data.backup_sync import BackupSyncService
from backend.data.dataset_service import DatasetService
from backend.data.migration import SnapshotMigrationService
from backend.data.repository import Repository
from backend.data.schemas import ImportDatasetRequest
from backend.data.supabase_backup import get_backup_client
from backend.services import BacktestService, GoldenService, OptimizationService

DEFAULT_MOMENTUM_PERIODS = [3, 5, 8, 13, 21]
DEFAULT_HORIZONS = [1, 3, 5, 10]


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


def cmd_import_idb(args: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as session:
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
    init_db()
    with SessionLocal() as session:
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
    init_db()
    with SessionLocal() as session:
        print_json(DatasetService(session).list_datasets())


def cmd_push_backup(_: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as session:
        print_json(BackupSyncService(session).push_all_to_backup())


def cmd_push_outbox(args: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as session:
        repo = Repository(session, enable_backup=False)
        print_json(BackupSyncService(session).push_outbox_to_backup(repo, limit=args.limit))


def cmd_pull_backup(_: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as session:
        print_json(BackupSyncService(session).pull_backup_to_primary())


def cmd_smoke_backup(_: argparse.Namespace) -> None:
    backup = get_backup_client()
    if not backup:
        print_json({"ok": False, "configured": False, "error": "supabase backup is not configured"})
        return
    print_json(backup.smoke_test())


def cmd_migrate_snapshots(args: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as session:
        request = {
            "datasetId": args.dataset_id,
            "sourcePath": args.path,
            "name": args.name,
            "idempotencyKey": args.idempotency_key,
            "source": args.source,
            "dryRun": args.dry_run,
        }
        print_json(SnapshotMigrationService(session).import_json(request))


def build_ranktrend_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "dataset_id": args.dataset_id,
        "snapshot_type": args.snapshot_type,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "strategy_name": args.strategy_name,
        "random_seed": args.seed,
        "enable_trade_simulation": not args.no_trade_simulation,
        "initialCash": args.initial_cash,
        "maxPositions": args.max_positions,
        "maxHoldingBars": args.max_holding_bars,
        "targetHoldingDays": args.target_holding_days,
        "takeProfitPct": args.take_profit_pct,
        "stopLossPct": args.stop_loss_pct,
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
            "volumeParticipationRate": args.volume_participation_rate,
            "orderBookParticipationRate": args.order_book_participation_rate,
            "useIntrabarStops": not args.no_intrabar_stops,
            "intrabarAmbiguity": args.intrabar_ambiguity,
        },
    }


def cmd_run_ranktrend(args: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as session:
        payload = build_ranktrend_payload(args)
        print_json(BacktestService(session).run_ranktrend(payload))


def cmd_optimize_ranktrend(args: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as session:
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


def cmd_validate_golden(args: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as session:
        print_json(GoldenService(session).validate({"caseId": args.case_id, "path": args.path, "tolerance": args.tolerance}))


def cmd_show_report(args: argparse.Namespace) -> None:
    init_db()
    with SessionLocal() as session:
        print_json(BacktestService(session).get_run(args.run_id) or {"error": "run not found"})


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
    push_backup_cmd.set_defaults(func=cmd_push_backup)

    push_outbox_cmd = sub.add_parser("push-outbox", help="Push due sync_outbox rows to Supabase backup")
    push_outbox_cmd.add_argument("--limit", type=int, default=50)
    push_outbox_cmd.set_defaults(func=cmd_push_outbox)

    pull_backup_cmd = sub.add_parser("pull-backup", help="Pull Supabase backup records into SQLite")
    pull_backup_cmd.set_defaults(func=cmd_pull_backup)

    smoke_backup_cmd = sub.add_parser("smoke-backup", help="Run Supabase backup write/read/delete smoke test")
    smoke_backup_cmd.set_defaults(func=cmd_smoke_backup)

    migrate_cmd = sub.add_parser("migrate-snapshots", help="Import historical DragonBoard snapshot JSON into SQLite")
    migrate_cmd.add_argument("--path", required=True)
    migrate_cmd.add_argument("--dataset-id", default="dragonboard_history")
    migrate_cmd.add_argument("--name", default=None)
    migrate_cmd.add_argument("--idempotency-key", default=None)
    migrate_cmd.add_argument("--source", default="dragon_board_history_migration")
    migrate_cmd.add_argument("--dry-run", action="store_true")
    migrate_cmd.set_defaults(func=cmd_migrate_snapshots)

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
    run_cmd.add_argument("--max-holding-bars", type=int, default=40)
    run_cmd.add_argument("--take-profit-pct", type=float, default=0.12)
    run_cmd.add_argument("--stop-loss-pct", type=float, default=0.06)
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
    run_cmd.add_argument("--volume-participation-rate", type=float, default=0.05)
    run_cmd.add_argument("--order-book-participation-rate", type=float, default=0.3)
    run_cmd.add_argument("--no-intrabar-stops", action="store_true")
    run_cmd.add_argument("--intrabar-ambiguity", choices=["stop_first", "take_first"], default="stop_first")
    run_cmd.set_defaults(func=cmd_run_ranktrend)

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

    golden_cmd = sub.add_parser("validate-golden", help="Validate golden case")
    golden_cmd.add_argument("--case-id", default=None)
    golden_cmd.add_argument("--path", default=None)
    golden_cmd.add_argument("--tolerance", type=float, default=1e-6)
    golden_cmd.set_defaults(func=cmd_validate_golden)

    report_cmd = sub.add_parser("show-report", help="Show backtest report")
    report_cmd.add_argument("--run-id", required=True)
    report_cmd.set_defaults(func=cmd_show_report)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
