from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


TEST_THEME_DATASET_IDS = ("ds_test", "ds_compress", "ds_v12")
THEME_RESEARCH_COLLECTIONS = (
    "theme_factor_frames",
    "theme_stock_exposures",
    "theme_signals",
    "theme_quality_reports",
)


def repair_mongodb_research_metadata(
    database: Any,
    *,
    apply: bool = False,
) -> dict[str, Any]:
    theme_query = {"datasetId": {"$in": list(TEST_THEME_DATASET_IDS)}}
    missing_status_query = {
        "$or": [
            {"status": {"$exists": False}},
            {"status": None},
            {"status": ""},
        ]
    }
    trial_query = {"request.optimization_run_id": {"$exists": True}}

    counts: dict[str, int] = {
        name: int(database[name].count_documents(theme_query))
        for name in THEME_RESEARCH_COLLECTIONS
    }
    counts["missingBacktestStatus"] = int(database["backtest_runs"].count_documents(missing_status_query))
    counts["optimizationTrialBacktests"] = int(database["backtest_runs"].count_documents(trial_query))

    result: dict[str, Any] = {
        "ok": True,
        "apply": apply,
        "testThemeDatasetIds": list(TEST_THEME_DATASET_IDS),
        "counts": counts,
    }
    if not apply:
        return result

    deleted = {
        name: _delete_many(database[name], theme_query)
        for name in THEME_RESEARCH_COLLECTIONS
    }
    status_update = database["backtest_runs"].update_many(
        missing_status_query,
        {"$set": {"status": "completed"}},
    )
    trial_update = database["backtest_runs"].update_many(
        trial_query,
        {
            "$set": {
                "artifactType": "optimization_trial",
                "request.artifact_type": "optimization_trial",
                "request.artifactType": "optimization_trial",
                "status": "completed",
            }
        },
    )

    updated = {
        "backtestStatus": int(getattr(status_update, "modified_count", 0)),
        "optimizationTrialBacktests": int(getattr(trial_update, "modified_count", 0)),
    }
    _write_repair_audit(database, deleted, updated)
    result["deleted"] = deleted
    result["updated"] = updated
    return result


def _delete_many(collection: Any, query: dict[str, Any]) -> int:
    result = collection.delete_many(query)
    return int(getattr(result, "deleted_count", 0))


def _write_repair_audit(database: Any, deleted: dict[str, int], updated: dict[str, int]) -> None:
    now = datetime.now(UTC)
    database["migration_audit"].insert_many(
        [
            {
                "opType": "mongodb_research_metadata_repair",
                "idempotencyKey": f"mongodb_research_metadata_repair:{now.isoformat()}",
                "createdAt": now.replace(tzinfo=None),
                "testThemeDatasetIds": list(TEST_THEME_DATASET_IDS),
                "deleted": deleted,
                "updated": updated,
            }
        ],
        ordered=False,
    )
