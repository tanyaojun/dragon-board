from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


SNAPSHOT_CHILD_COLLECTIONS = (
    "snapshot_records",
    "snapshot_frames",
    "snapshot_stock_rows",
    "snapshot_sector_rows",
)

DATASET_RESEARCH_COLLECTIONS = (
    "golden_ranktrend_cases",
    "optimization_runs",
    "theme_factor_frames",
    "theme_stock_exposures",
    "theme_signals",
    "theme_quality_reports",
)

BACKTEST_CHILD_COLLECTIONS = (
    "backtest_trades",
    "backtest_equity_curve",
    "backtest_signals",
    "backtest_quality_reports",
)


def plan_mongodb_dataset_cleanup(
    database: Any,
    *,
    keep_dataset_ids: list[str] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    keep_ids = {item for item in (["dragonboard_live"] if keep_dataset_ids is None else keep_dataset_ids) if item}
    if not keep_ids:
        return {
            "ok": False,
            "apply": apply,
            "error": {"code": "missing_keep_dataset_ids"},
        }

    dataset_rows = list(database["datasets"].find({}))
    delete_dataset_ids = sorted(
        str(row.get("id") or "")
        for row in dataset_rows
        if str(row.get("id") or "") and str(row.get("id") or "") not in keep_ids
    )
    delete_backtest_ids = sorted(
        str(row.get("id") or "")
        for row in database["backtest_runs"].find({"datasetId": {"$in": delete_dataset_ids}})
        if row.get("id")
    )

    counts = _preview_counts(database, delete_dataset_ids, delete_backtest_ids)
    result: dict[str, Any] = {
        "ok": True,
        "apply": apply,
        "keepDatasetIds": sorted(keep_ids),
        "deleteDatasetIds": delete_dataset_ids,
        "deleteBacktestRunIds": delete_backtest_ids,
        "counts": counts,
        "protectedCollections": [
            "stock_names",
            "themes",
            "theme_stock_mappings",
            "theme_metadata",
            "migration_audit",
        ],
    }
    if not apply:
        return result

    deleted: dict[str, int] = {}
    for name in SNAPSHOT_CHILD_COLLECTIONS:
        deleted[name] = _delete_many(database[name], {"datasetId": {"$in": delete_dataset_ids}})
    deleted["archive_manifests"] = _delete_many(database["archive_manifests"], {"datasetId": {"$in": delete_dataset_ids}})
    deleted["datasets"] = _delete_many(database["datasets"], {"id": {"$in": delete_dataset_ids}})

    deleted["backtest_runs"] = _delete_many(database["backtest_runs"], {"id": {"$in": delete_backtest_ids}})
    for name in BACKTEST_CHILD_COLLECTIONS:
        deleted[name] = _delete_many(database[name], {"backtestRunId": {"$in": delete_backtest_ids}})
    for name in DATASET_RESEARCH_COLLECTIONS:
        deleted[name] = _delete_many(database[name], {"datasetId": {"$in": delete_dataset_ids}})

    deleted["orphanBacktestChildren"] = _delete_orphan_backtest_children(database)
    _write_cleanup_audit(database, keep_ids, delete_dataset_ids, deleted)
    result["deleted"] = deleted
    return result


def _preview_counts(
    database: Any,
    dataset_ids: list[str],
    backtest_run_ids: list[str],
) -> dict[str, int]:
    counts: dict[str, int] = {
        "datasets": int(database["datasets"].count_documents({"id": {"$in": dataset_ids}})),
        "archive_manifests": int(database["archive_manifests"].count_documents({"datasetId": {"$in": dataset_ids}})),
        "backtest_runs": int(database["backtest_runs"].count_documents({"id": {"$in": backtest_run_ids}})),
    }
    for name in SNAPSHOT_CHILD_COLLECTIONS:
        counts[name] = int(database[name].count_documents({"datasetId": {"$in": dataset_ids}}))
    for name in BACKTEST_CHILD_COLLECTIONS:
        counts[name] = int(database[name].count_documents({"backtestRunId": {"$in": backtest_run_ids}}))
    for name in DATASET_RESEARCH_COLLECTIONS:
        counts[name] = int(database[name].count_documents({"datasetId": {"$in": dataset_ids}}))
    return counts


def _delete_many(collection: Any, query: dict[str, Any]) -> int:
    result = collection.delete_many(query)
    return int(getattr(result, "deleted_count", 0))


def _delete_orphan_backtest_children(database: Any) -> int:
    existing_run_ids = {
        str(row.get("id") or "")
        for row in database["backtest_runs"].find({})
        if row.get("id")
    }
    deleted = 0
    for name in BACKTEST_CHILD_COLLECTIONS:
        orphan_ids = sorted(
            {
                str(row.get("backtestRunId") or "")
                for row in database[name].find({})
                if row.get("backtestRunId") and str(row.get("backtestRunId")) not in existing_run_ids
            }
        )
        deleted += _delete_many(database[name], {"backtestRunId": {"$in": orphan_ids}})
    return deleted


def _write_cleanup_audit(
    database: Any,
    keep_ids: set[str],
    delete_dataset_ids: list[str],
    deleted: dict[str, int],
) -> None:
    database["migration_audit"].insert_many(
        [
            {
                "opType": "mongodb_dataset_cleanup",
                "idempotencyKey": f"mongodb_dataset_cleanup:{datetime.now(UTC).isoformat()}",
                "createdAt": datetime.now(UTC).replace(tzinfo=None),
                "keepDatasetIds": sorted(keep_ids),
                "deleteDatasetIds": delete_dataset_ids,
                "deleted": deleted,
            }
        ],
        ordered=False,
    )
