from __future__ import annotations

import argparse
import json
import sys
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from backend.data.archive.object_store import get_object_backup_store
from backend.data.ingest.dataset_service import DatasetService
from backend.data.migrations.mongodb_migration import (
    MongoMigrationPlan,
    apply_mongodb_migration,
    get_mongodb_database,
    inspect_mongodb_database,
    plan_mongodb_migration,
    verify_mongodb_migration,
)
from backend.data.migrations.mongodb_cleanup import plan_mongodb_dataset_cleanup
from backend.operations.mongodb_dead_data_cleanup import plan_dead_data_cleanup
from backend.data.migrations.mongodb_snapshot_repair import (
    backfill_empty_snapshot_rows,
    copy_missing_snapshot_slots_from_dataset,
)
from backend.data.backup.mongodb_backup import get_mongodb_backup_service
from backend.data.migrations.mongodb_research_repair import repair_mongodb_research_metadata
from backend.data.migrations.jump_backfill import backfill_jump_fields
from backend.data.repositories.repository_factory import create_repository
from backend.data.models.schemas import ImportDatasetRequest
from backend.data.migrations.theme_migration import ThemeMigrationService
from backend.services.theme.mapping_refresh import refresh_theme_stock_mappings
from backend.analysis.ranktrend.live_gate_shadow_audit import load_hotlist_anchor_samples
from backend.operations.schedule import run_after_market_once
from backend.operations.snapshot_field_backfill import SnapshotFieldBackfillService
from backend.core.settings import get_settings
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
from backend.core.utils import json_loads
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


def runtime_session():
    """mongodb 单链：会话恒为 None（create_repository 内部走 MongoResearchRepository）。"""
    return nullcontext(None)


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


def cmd_jev_low_confidence(args: argparse.Namespace) -> None:
    """判答质量观测（2026-11-18 C1 裁决）：低置信判答清单，零 jev 调用，按代际分段。"""
    from backend.operations.jev_answer_quality import low_confidence_report
    db = _runtime_mongodb_database()
    print_json(low_confidence_report(
        db, date_start=args.start, date_end=args.end, threshold=args.threshold))


def cmd_verify_themes(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    print_json(ThemeMigrationService(None).verify_mapping(payload))


def cmd_refresh_theme_mappings(_args: argparse.Namespace) -> None:
    """从 longhuvip 题材 API 刷新 MongoDB theme_stock_mappings。"""
    if get_settings().storage_backend != "mongodb":
        print_json({"ok": False, "error": "theme mapping refresh requires MongoDB storage backend"})
        return
    print_json(refresh_theme_stock_mappings())


def cmd_smoke_object_backup(_: argparse.Namespace) -> None:
    store = get_object_backup_store()
    if not store:
        print_json({"ok": False, "configured": False, "error": "object backup bucket is not configured"})
        return
    print_json(store.smoke_test())




def cmd_rewrap_pool_backfill(args: argparse.Namespace) -> None:
    from backend.data.repositories import repository_factory
    from backend.operations.rewrap_pool import backfill_rewrap_pool
    db = repository_factory.get_runtime_mongodb_database()
    slots = (("final", "midday") if args.slot == "both" else (args.slot,))
    result = backfill_rewrap_pool(db, args.start, args.end, slots=slots,
                                  dry_run=bool(args.dry_run))
    print_json(result)
    if not result.get("ok"):
        raise SystemExit(1)


def cmd_wzs_settle_backfill(args: argparse.Namespace) -> None:
    """弱转强节点历史回填定档（2026-10-22 §6.3 节点定格；幂等 first-write-wins）。

    --idx-override 日期=指数（可重复）：仅限引用研究档案存档定档值（如 2026-10-20=50.1，
    记录于 jev-weak-to-strong-day-study.md §1），使用须在档案登记依据。
    """
    from backend.analysis.hotlist import weak_to_strong as W
    from backend.data.repositories import repository_factory
    db = repository_factory.get_runtime_mongodb_database()
    overrides = {}
    for item in (args.idx_override or []):
        if "=" not in item:
            raise SystemExit(f"--idx-override 格式应为 日期=指数，得到: {item}")
        d, v = item.split("=", 1)
        overrides[d.strip()] = float(v)
    dates = [str(x["_id"]).split(":")[0]
             for x in db["hotlist_jev_relay_index"].find({"status": "ok"}, {"_id": 1})
             if args.start <= str(x["_id"]).split(":")[0] <= args.end]
    reset = bool(args.reset)
    archive_path = None
    if reset and not args.dry_run:
        # 升代重定档：旧代定格先归档（§6.4；data/backups 为 gitignore 归档区）
        import json as _json
        import time as _time
        stamps = {}
        for doc in db["hotlist_jev_relay_index"].find({}, {"wzs": 1, "tradingDate": 1}):
            w = doc.get("wzs")
            if isinstance(w, dict) and "state" in w:
                stamps[str(doc.get("tradingDate") or doc["_id"]).split(":")[0]] = w
        from pathlib import Path as _Path
        backup_dir = _Path("data/backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        archive_path = str(backup_dir / f"wzs_settlements_{_time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(archive_path, "w", encoding="utf-8") as f:
            _json.dump({"archivedAt": _time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "count": len(stamps), "settlements": stamps}, f, ensure_ascii=False, indent=1)
    stamped = skipped = missing = 0
    details = []
    for d in sorted(dates):
        doc = db["hotlist_jev_relay_index"].find_one({"_id": f"{d}:RELAY"}) or {}
        already = isinstance(doc.get("wzs"), dict) and "state" in doc["wzs"]
        if already and not reset:
            skipped += 1
            continue
        entry = W.write_settlement(db, d, idx_override=overrides.get(d),
                                   dry_run=bool(args.dry_run), reset=reset)
        if entry is None:
            missing += 1
            details.append({"date": d, "result": "missing_doc"})
        else:
            stamped += 1
            details.append({"date": d, "result": "dry-run" if args.dry_run else "stamped",
                            "hit": entry.get("hit"), "state": entry.get("state"),
                            "idx": entry.get("idx"),
                            "override": overrides.get(d) is not None})
    result = {"ok": True, "range": [args.start, args.end],
              "stamped": stamped, "skippedAlreadySettled": skipped,
              "missingDoc": missing, "dryRun": bool(args.dry_run), "reset": reset,
              "archivedTo": archive_path,
              "overrides": overrides, "details": details}
    print_json(result)
    if missing and not args.dry_run:
        raise SystemExit(1)


def cmd_after_market_once(args: argparse.Namespace) -> None:
    try:
        result = run_after_market_once(
            archive_limit=args.archive_limit,
            backup_limit=args.backup_limit,
            dry_run=bool(args.dry_run),
        )
    except Exception:
        # 2026-10-23 加固：链内未捕获异常（如日历不可用）曾绕过 _write_after_market_log，
        # 只留任务计划裸退出码 1、无日志无失败 JSON（fail-visible 缺口）。兜底落盘后退出。
        import traceback

        traceback.print_exc()
        _write_after_market_log({
            "ok": False,
            "finishedAt": datetime.now(timezone.utc).isoformat(),
            "stoppedAt": "unhandled_exception",
            "results": {},
            "error": {
                "code": "after_market_unhandled_exception",
                "message": traceback.format_exc(),
            },
        })
        raise SystemExit(1)
    print_json(result)
    _write_after_market_log(result)
    if not result.get("ok"):
        raise SystemExit(1)


_AFTER_MARKET_LOG_NAME = "after_market.log"


def _after_market_log_summary(result: dict[str, Any]) -> dict[str, Any]:
    """盘后链结果摘要（任务计划历史只有退出码，摘要行必须可追溯）。"""
    steps = result.get("results") or {}
    backup = steps.get("mongodbBackup") or {}
    archive = steps.get("snapshotArchiveR2") or {}
    hotlist = steps.get("hotlistSentiment") or {}
    types: dict[str, Any] = {}
    for name, item in (archive.get("snapshotTypes") or {}).items():
        files = item.get("files") or []
        types[name] = {
            "ok": bool(item.get("ok")),
            "tradingDate": item.get("tradingDate"),
            "reason": item.get("reason") or "",
            "uploadedFiles": len(files),
            "uploadedBytes": sum(int(f.get("bytes") or 0) for f in files),
        }
    summary: dict[str, Any] = {
        "logAt": datetime.now(timezone.utc).isoformat(),
        "startedAt": result.get("startedAt"),
        "finishedAt": result.get("finishedAt"),
        "ok": bool(result.get("ok")),
        "hotlistSentimentOk": bool(hotlist.get("ok")),
        "mongodbBackup": {
            "ok": bool(backup.get("ok")),
            "strategy": backup.get("strategy"),
            "backupId": backup.get("backupId"),
            "pushOk": bool((backup.get("push") or {}).get("ok")),
            **({"fullCatchUpReason": (backup.get("lastFullBackup") or {}).get("fullCatchUp", {}).get("reason")}
               if (backup.get("lastFullBackup") or {}).get("fullCatchUp") else {}),
        },
        "snapshotArchiveR2": {"ok": bool(archive.get("ok")), "types": types},
    }
    if result.get("stoppedAt"):
        summary["stoppedAt"] = result.get("stoppedAt")
    if steps.get("jiuyanPreflight"):
        pf = steps["jiuyanPreflight"]
        summary["jiuyanPreflight"] = {
            "ok": bool(pf.get("ok")), "checked": bool(pf.get("checked")),
            "remoteCountsAll": pf.get("remoteCountsAll"),
            "storedCountsAll": pf.get("storedCountsAll"),
            "repairs": len(pf.get("repairs") or []),
            **({"warning": pf["warning"]} if pf.get("warning") else {}),
            **({"error": pf["error"]} if pf.get("error") else {}),
        }
    return summary


def _write_after_market_log(result: dict[str, Any]) -> None:
    """盘后链结果落盘：ok 时追加一行摘要，失败时另存完整 JSON 便于诊断。

    落盘本身失败只打警告，不影响盘后链退出码。
    """
    try:
        log_dir = get_settings().mongodb_backup_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / _AFTER_MARKET_LOG_NAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_after_market_log_summary(result), ensure_ascii=False, sort_keys=True) + "\n")
        if not result.get("ok"):
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            (log_dir / f"after_market-failure-{ts}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=1, default=str),
                encoding="utf-8",
            )
    except Exception as exc:
        print(f"after-market 日志落盘失败（不影响退出码）: {exc}", file=sys.stderr)


def cmd_snapshot_archive_backfill(args: argparse.Namespace) -> None:
    """MongoDB 快照历史日归档到 R2（mongodb 后端，补历史；盘后任务只归档 T-1）。

    逐交易日幂等补归档：manifest 已 uploaded 的日期自动跳过，可安全重跑。
    """
    from backend.data.repositories import repository_factory

    if args.start_date > args.end_date:
        raise SystemExit("--start-date must be <= --end-date")
    db = repository_factory.get_runtime_mongodb_database()
    summary: dict[str, Any] = {
        "datasetId": args.dataset_id,
        "snapshotType": args.snapshot_type,
        "startDate": args.start_date,
        "endDate": args.end_date,
        "dryRun": bool(args.dry_run),
        "days": [],
        "archived": 0,
        "skipped": 0,
        "failed": 0,
    }
    service = ArchiveService(db)
    cursor = (
        db["snapshot_frames"]
        .find(
            {
                "datasetId": args.dataset_id,
                "type": args.snapshot_type,
                "tradingDate": {"$gte": args.start_date, "$lte": args.end_date},
            },
            {"tradingDate": 1, "_id": 0},
        )
        .sort("tradingDate", 1)
    )
    dates = sorted({str(row.get("tradingDate") or "") for row in cursor} - {""})
    for trading_date in dates:
        try:
            result = service.backup_mongodb_snapshot_day_to_object(
                db,
                dataset_id=args.dataset_id,
                snapshot_type=args.snapshot_type,
                trading_date=trading_date,
                dry_run=bool(args.dry_run),
            )
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        status = (
            "failed" if not result.get("ok") and not result.get("skipped")
            else "skipped" if result.get("skipped")
            else "archived"
        )
        summary[status] = int(summary.get(status, 0)) + 1
        summary["days"].append(
            {
                "tradingDate": trading_date,
                "status": status,
                "reason": result.get("reason") or result.get("error") or "",
                "rowCounts": result.get("rowCounts") or {},
            }
        )
    print_json(summary)
    if summary["failed"]:
        raise SystemExit(1)


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


def cmd_cleanup_mongodb_dead_data(args: argparse.Namespace) -> None:
    purge_before = None
    if args.purge_result_chunks_before:
        try:
            purge_before = datetime.strptime(args.purge_result_chunks_before, "%Y-%m-%d")
        except ValueError as exc:
            raise SystemExit(f"--purge-result-chunks-before 需为 YYYY-MM-DD：{exc}")
    result = plan_dead_data_cleanup(
        _runtime_mongodb_database(),
        drop_dead_collections=bool(args.drop_dead_collections),
        cleanup_datasets=bool(args.cleanup_datasets),
        purge_result_chunks=bool(args.purge_result_chunks),
        purge_result_chunks_before=purge_before,
        compact=bool(args.compact),
        apply=bool(args.apply),
    )
    print_json(result)
    if not result.get("ok"):
        raise SystemExit(1)


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


def cmd_snapshot_field_backfill(args: argparse.Namespace) -> None:
    service = SnapshotFieldBackfillService(_runtime_mongodb_database())
    print_json(
        service.backfill(
            dataset_id=args.dataset_id,
            start_date=args.start_date or None,
            end_date=args.end_date or None,
            snapshot_types=args.snapshot_type or None,
            dry_run=not bool(args.apply),
            backup=not bool(args.no_backup),
            limit=int(args.limit or 0),
        )
    )


def cmd_backup_mongodb(args: argparse.Namespace) -> None:
    service = get_mongodb_backup_service()
    if args.light:
        result = service.create_light_backup()
    elif args.full:
        result = service.create_full_backup()
    else:
        raise SystemExit("use --full or --light")
    if result.get("ok"):
        result["verify"] = service.verify_backup(result["backupId"])
    print_json(result)


def cmd_restore_mongodb_backup(args: argparse.Namespace) -> None:
    result = get_mongodb_backup_service().restore_backup(
        args.backup_id,
        target_database=args.target_db,
        drop=bool(args.drop),
    )
    print_json(result)
    if not result.get("ok"):
        raise SystemExit(1)


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

    from backend.operations.jev_answer_quality import LOW_CONFIDENCE_THRESHOLD
    jev_lc_cmd = sub.add_parser(
        "jev-low-confidence",
        help="判答质量观测：低置信判答清单（零 jev 调用，按题集代际分段，C1 替代审计）")
    jev_lc_cmd.add_argument("--start", default=None, help="起始日 YYYY-MM-DD（含）")
    jev_lc_cmd.add_argument("--end", default=None, help="结束日 YYYY-MM-DD（含）")
    jev_lc_cmd.add_argument("--threshold", type=float, default=LOW_CONFIDENCE_THRESHOLD,
                            help="max_prob 观察阈值（默认取模块常量，仅人工抽检分流非判据）")
    jev_lc_cmd.set_defaults(func=cmd_jev_low_confidence)

    verify_themes_cmd = sub.add_parser("verify-themes", help="Verify historical DragonBoard theme mapping JSON payload (mongodb 链)")
    verify_themes_cmd.add_argument("--path", required=True)
    verify_themes_cmd.set_defaults(func=cmd_verify_themes)

    refresh_theme_mappings_cmd = sub.add_parser(
        "refresh-theme-mappings",
        help="Refresh MongoDB theme_stock_mappings from longhuvip theme API",
    )
    refresh_theme_mappings_cmd.set_defaults(func=cmd_refresh_theme_mappings)

    smoke_object_cmd = sub.add_parser("smoke-object-backup", help="Run R2/S3 object backup smoke test")
    smoke_object_cmd.set_defaults(func=cmd_smoke_object_backup)

    after_market_cmd = sub.add_parser("after-market-once", help="Run after-market MongoDB backup, R2 snapshot archive, and hotlist sentiment pipeline")
    after_market_cmd.add_argument("--archive-limit", type=int, default=None)
    after_market_cmd.add_argument("--backup-limit", type=int, default=None)
    after_market_cmd.add_argument("--dry-run", action="store_true")
    after_market_cmd.set_defaults(func=cmd_after_market_once)

    rewrap_backfill_cmd = sub.add_parser(
        "rewrap-pool-backfill",
        help="Backfill rewrap pool snapshots (idempotent; midday only for genuine noon lists)")
    rewrap_backfill_cmd.add_argument("--start", required=True)
    rewrap_backfill_cmd.add_argument("--end", required=True)
    rewrap_backfill_cmd.add_argument("--slot", choices=("final", "midday", "both"), default="final")
    rewrap_backfill_cmd.add_argument("--dry-run", action="store_true")
    rewrap_backfill_cmd.set_defaults(func=cmd_rewrap_pool_backfill)

    wzs_backfill_cmd = sub.add_parser(
        "wzs-settle-backfill",
        help="Backfill weak-to-strong node settlements (idempotent; first-write-wins)")
    wzs_backfill_cmd.add_argument("--start", required=True)
    wzs_backfill_cmd.add_argument("--end", required=True)
    wzs_backfill_cmd.add_argument("--idx-override", action="append", default=[],
                                   metavar="DATE=IDX",
                                   help="archived settlement idx (e.g. 2026-10-20=50.1)")
    wzs_backfill_cmd.add_argument("--reset", action="store_true",
                                   help="generation upgrade only: re-settle (archive old stamps first)")
    wzs_backfill_cmd.add_argument("--dry-run", action="store_true")
    wzs_backfill_cmd.set_defaults(func=cmd_wzs_settle_backfill)

    archive_backfill_cmd = sub.add_parser(
        "snapshot-archive-backfill",
        help="Backfill MongoDB snapshot days to R2 archives (idempotent per trading date)",
    )
    archive_backfill_cmd.add_argument("--dataset-id", default="dragonboard_live")
    archive_backfill_cmd.add_argument("--snapshot-type", choices=["five_minutes", "quarter_hour", "half_hour", "hourly", "daily"], required=True)
    archive_backfill_cmd.add_argument("--start-date", required=True)
    archive_backfill_cmd.add_argument("--end-date", required=True)
    archive_backfill_cmd.add_argument("--dry-run", action="store_true")
    archive_backfill_cmd.set_defaults(func=cmd_snapshot_archive_backfill)

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

    cleanup_dead_data_cmd = sub.add_parser(
        "cleanup-mongodb-dead-data",
        help="Preview or delete dead MongoDB collections / dataset residue / old research result chunks (default dry-run)",
    )
    cleanup_dead_data_cmd.add_argument("--drop-dead-collections", action="store_true")
    cleanup_dead_data_cmd.add_argument("--cleanup-datasets", action="store_true")
    cleanup_dead_data_cmd.add_argument("--purge-result-chunks", action="store_true")
    cleanup_dead_data_cmd.add_argument(
        "--purge-result-chunks-before",
        default=None,
        help="Override the result-chunks purge cutoff (YYYY-MM-DD, default 2026-09-01)",
    )
    cleanup_dead_data_cmd.add_argument(
        "--compact",
        action="store_true",
        help="After deletion, run compact on affected collections to reclaim disk space",
    )
    cleanup_dead_data_cmd.add_argument("--apply", action="store_true")
    cleanup_dead_data_cmd.set_defaults(func=cmd_cleanup_mongodb_dead_data)

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

    restore_mongodb_backup_cmd = sub.add_parser(
        "restore-mongodb-backup",
        help="Restore a verified local MongoDB backup via mongorestore into a staging database",
    )
    restore_mongodb_backup_cmd.add_argument("--backup-id", required=True)
    restore_mongodb_backup_cmd.add_argument(
        "--target-db",
        default="dragon_board_quant_restore_staging",
        help="Target database name (must not be the primary database)",
    )
    restore_mongodb_backup_cmd.add_argument("--drop", action="store_true")
    restore_mongodb_backup_cmd.set_defaults(func=cmd_restore_mongodb_backup)

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
    collector_run_cmd.add_argument("--snapshot-type", choices=["five_minutes", "quarter_hour", "half_hour", "hourly", "daily"], required=True)
    collector_run_cmd.add_argument("--trading-date", required=True)
    collector_run_cmd.add_argument("--slot-time", required=True)
    collector_run_cmd.add_argument("--dry-run", action="store_true")
    collector_run_cmd.add_argument("--force", action="store_true")
    collector_run_cmd.set_defaults(func=cmd_snapshot_collector_run_once)

    collector_backfill_cmd = sub.add_parser("snapshot-collector-backfill", help="Run collection for all slots across a date range")
    collector_backfill_cmd.add_argument("--dataset-id", required=True)
    collector_backfill_cmd.add_argument("--snapshot-type", choices=["five_minutes", "quarter_hour", "half_hour", "hourly", "daily"], required=True)
    collector_backfill_cmd.add_argument("--start-date", required=True)
    collector_backfill_cmd.add_argument("--end-date", required=True)
    collector_backfill_cmd.add_argument("--dry-run", dest="dry_run", action="store_true")
    collector_backfill_cmd.add_argument("--apply", dest="dry_run", action="store_false")
    collector_backfill_cmd.add_argument("--force", action="store_true")
    collector_backfill_cmd.set_defaults(func=cmd_snapshot_collector_backfill, dry_run=True)

    collector_audit_cmd = sub.add_parser("snapshot-collector-audit", help="Audit snapshot coverage for a dataset/type")
    collector_audit_cmd.add_argument("--dataset-id", required=True)
    collector_audit_cmd.add_argument("--snapshot-type", choices=["five_minutes", "quarter_hour", "half_hour", "hourly", "daily"], required=True)
    collector_audit_cmd.add_argument("--trading-date", default=None)
    collector_audit_cmd.set_defaults(func=cmd_snapshot_collector_audit)

    collector_compare_cmd = sub.add_parser(
        "snapshot-collector-compare",
        help="Compare snapshot data between two datasets (e.g. shadow vs live)",
    )
    collector_compare_cmd.add_argument("--dataset-id-a", required=True, help="First dataset ID (e.g. dragonboard_live)")
    collector_compare_cmd.add_argument("--dataset-id-b", required=True, help="Second dataset ID (e.g. another_dataset)")
    collector_compare_cmd.add_argument("--snapshot-type", choices=["five_minutes", "quarter_hour", "half_hour", "hourly", "daily"], required=True)
    collector_compare_cmd.add_argument("--trading-date", default=None, help="Optional single date to compare")
    collector_compare_cmd.set_defaults(func=cmd_snapshot_collector_compare)

    scheduler_status_cmd = sub.add_parser(
        "snapshot-collector-scheduler-status",
        help="Show snapshot collector scheduler operational state",
    )
    scheduler_status_cmd.set_defaults(func=cmd_snapshot_collector_scheduler_status)

    field_backfill_cmd = sub.add_parser(
        "snapshot-backfill-fields",
        help="Backfill derived fields in snapshot_stock_rows from per-row evidence "
        "(limit prices, lastTrade, amplitude, zljzb, totalMV); default dry-run",
    )
    field_backfill_cmd.add_argument("--dataset-id", default="dragonboard_live")
    field_backfill_cmd.add_argument("--start-date", default="")
    field_backfill_cmd.add_argument("--end-date", default="")
    field_backfill_cmd.add_argument("--snapshot-type", action="append", default=None)
    field_backfill_cmd.add_argument("--apply", dest="apply", action="store_true")
    field_backfill_cmd.add_argument("--no-backup", dest="no_backup", action="store_true")
    field_backfill_cmd.add_argument("--limit", default="0")
    field_backfill_cmd.set_defaults(func=cmd_snapshot_field_backfill)

    analysis_backfill_cmd = sub.add_parser(
        "snapshot-analysis-backfill",
        help="Backfill snapshot_analysis (analyze 全字段) for frames; default dry-run",
    )
    analysis_backfill_cmd.add_argument("--dataset-id", default="dragonboard_live")
    analysis_backfill_cmd.add_argument("--snapshot-type", action="append", default=None)
    analysis_backfill_cmd.add_argument("--limit", type=int, default=1, help="recent frames to backfill (newest first); 0 = unlimited when --start-date is given")
    analysis_backfill_cmd.add_argument("--start-date", default=None, help="YYYY-MM-DD lower bound (inclusive) for date-range backfill")
    analysis_backfill_cmd.add_argument(
        "--workers",
        type=int,
        default=1,
        help="parallel worker processes (default 1 = serial). 单帧约 20~40s CPU；全量历史回填请用 6~8",
    )
    analysis_backfill_cmd.add_argument("--apply", dest="apply", action="store_true")
    analysis_backfill_cmd.set_defaults(func=cmd_snapshot_analysis_backfill, apply=False)

    sentiment_recompute_cmd = sub.add_parser(
        "hotlist-sentiment-recompute",
        help="Force recompute (overwrite) hotlist_sentiment EOD documents; default dry-run",
    )
    sentiment_recompute_cmd.add_argument("--dataset-id", default="dragonboard_live")
    sentiment_recompute_cmd.add_argument("--snapshot-type", default="half_hour")
    sentiment_recompute_cmd.add_argument("--trading-date", default=None, help="YYYY-MM-DD; overrides --days when given")
    sentiment_recompute_cmd.add_argument(
        "--days",
        type=int,
        default=1,
        help="recompute the latest N trading days; 0 = ALL trading days (全量历史重算)",
    )
    sentiment_recompute_cmd.add_argument("--apply", dest="apply", action="store_true")
    sentiment_recompute_cmd.set_defaults(func=cmd_hotlist_sentiment_recompute, apply=False)

    return parser


def cmd_snapshot_analysis_backfill(args: argparse.Namespace) -> None:
    """补跑 snapshot_analysis（analyze 顶层字段全集）；默认 dry-run，--apply 才写库。

    背景：analyze 持久化只挂 ingest 路由，而日常采集由 collector 直写库 → 集合长期为空。
    ``--workers > 1`` 时按帧并行（进程池），用于全量历史回填。
    """
    from backend.data.repositories import repository_factory
    from backend.services.snapshot_analysis_backfill import (
        backfill_frames,
        normalize_snapshot_types,
        select_recent_frames,
    )

    try:
        snapshot_types = normalize_snapshot_types(args.snapshot_type)
    except ValueError as error:
        print_json({"ok": False, "error": str(error)})
        return
    db = repository_factory.get_runtime_mongodb_database()
    frames = select_recent_frames(
        db,
        args.dataset_id,
        snapshot_types,
        args.limit,
        start_date=args.start_date or None,
    )
    if not frames:
        print_json(
            {
                "ok": False,
                "reason": "no_frames_matched",
                "dataset_id": args.dataset_id,
                "snapshotTypes": snapshot_types,
            }
        )
        return
    print_json(
        backfill_frames(
            db,
            args.dataset_id,
            frames,
            apply=bool(args.apply),
            workers=max(1, int(args.workers or 1)),
        )
    )


def cmd_hotlist_sentiment_recompute(args: argparse.Namespace) -> None:
    """强制重算指定交易日（默认最新一天）的 hotlist_sentiment EOD 文档；默认 dry-run。

    ``--days 0`` = 该 dataset/snapshot_type 的**全部**交易日（全量历史重算，
    用于消除历史 fallback 兜底口径）。重算可复现（纯函数+库内帧），落库后立即失效读口缓存；
    回滚安全网=git 历史与 data/backups 文件归档（2026-10-13 红线 4，业务库不留 backup 集合）。
    """
    from backend.data.repositories import repository_factory
    from backend.operations.hotlist_sentiment import HotListSentimentBackfillService
    from backend.services.theme.hotlist_sentiment_compute import HotListSentimentComputeService

    db = repository_factory.get_runtime_mongodb_database()
    service = HotListSentimentComputeService(db)
    if args.trading_date:
        targets = [args.trading_date]
    else:
        dates = HotListSentimentBackfillService(db).trading_dates(
            dataset_id=args.dataset_id, snapshot_type=args.snapshot_type
        )
        if not dates:
            print_json({"ok": False, "reason": "no_snapshot_trading_date", "dataset_id": args.dataset_id})
            return
        days = int(args.days or 0)
        targets = dates if days <= 0 else dates[-days:]
    results = [
        service.recompute(
            args.dataset_id,
            args.snapshot_type,
            trading_date,
            persist=bool(args.apply),
        )
        for trading_date in targets
    ]
    print_json(
        results[0]
        if len(results) == 1
        else {"ok": True, "applied": bool(args.apply), "days": len(results), "results": results}
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
