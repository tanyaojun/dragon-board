from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def build_comp_rank_backfill_plan(rows: list[dict[str, Any]]) -> dict[str, Any]:
    snapshot_ids = {str(row.get("snapshotId") or "") for row in rows}
    snapshot_ids.discard("")
    snapshot_id = next(iter(snapshot_ids), "")
    result = {
        "snapshotId": snapshot_id,
        "eligible": False,
        "rowCount": len(rows),
        "reason": None,
    }
    if len(snapshot_ids) != 1 or not rows:
        result["reason"] = "invalid_snapshot_identity"
        return result

    codes = [str(row.get("code") or "") for row in rows]
    if not all(codes):
        result["reason"] = "missing_stock_code"
        return result
    if len(set(codes)) != len(codes):
        result["reason"] = "duplicate_stock_code"
        return result

    try:
        ranks = [int(row["rank"]) for row in rows]
    except (KeyError, TypeError, ValueError):
        result["reason"] = "invalid_rank"
        return result
    if sorted(ranks) != list(range(1, len(rows) + 1)):
        result["reason"] = "rank_not_contiguous_1_to_n"
        return result
    if any(
        row.get("compRank") is not None and int(row["compRank"]) != int(row["rank"])
        for row in rows
    ):
        result["reason"] = "existing_comp_rank_conflicts"
        return result

    result["eligible"] = True
    return result


class RankFieldBackfillService:
    VERSION = "comp_rank_from_rank_v1"

    def __init__(self, mongo_db: Any) -> None:
        self._db = mongo_db

    def backfill_comp_rank(
        self,
        *,
        dataset_id: str = "dragonboard_live",
        start_date: str | None = None,
        end_date: str | None = None,
        snapshot_types: list[str] | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        rows_collection = self._db["snapshot_stock_rows"]
        candidate_query: dict[str, Any] = {
            "datasetId": dataset_id,
            "source": "quantboard_backend_collector",
            "$or": [{"compRank": {"$exists": False}}, {"compRank": None}],
        }
        if start_date or end_date:
            date_query: dict[str, str] = {}
            if start_date:
                date_query["$gte"] = start_date
            if end_date:
                date_query["$lte"] = end_date
            candidate_query["tradingDate"] = date_query
        if snapshot_types:
            candidate_query["type"] = {"$in": snapshot_types}

        candidate_snapshot_ids = sorted(
            str(value)
            for value in rows_collection.distinct("snapshotId", candidate_query)
            if value
        )
        plans: list[dict[str, Any]] = []
        for snapshot_id in candidate_snapshot_ids:
            rows = list(rows_collection.find(
                {"datasetId": dataset_id, "snapshotId": snapshot_id},
                {"_id": 0, "snapshotId": 1, "code": 1, "rank": 1, "compRank": 1},
            ))
            plans.append(build_comp_rank_backfill_plan(rows))

        eligible = [plan for plan in plans if plan["eligible"]]
        result = {
            "ok": True,
            "dryRun": dry_run,
            "datasetId": dataset_id,
            "version": self.VERSION,
            "candidateSlots": len(plans),
            "eligibleSlots": len(eligible),
            "eligibleRows": sum(int(plan["rowCount"]) for plan in eligible),
            "skippedSlots": [plan for plan in plans if not plan["eligible"]],
            "updatedRows": 0,
        }
        if dry_run or not eligible:
            return result

        repaired_at = datetime.now(timezone.utc).isoformat()
        updated_rows = 0
        for plan in eligible:
            update_result = rows_collection.update_many(
                {
                    "datasetId": dataset_id,
                    "snapshotId": plan["snapshotId"],
                    "$or": [{"compRank": {"$exists": False}}, {"compRank": None}],
                },
                [{
                    "$set": {
                        "compRank": "$rank",
                        "repairMetadata.compRank": {
                            "version": self.VERSION,
                            "repairedAt": repaired_at,
                            "sourceField": "rank",
                        },
                    }
                }],
            )
            updated_rows += int(update_result.modified_count)
            self._db["snapshot_frames"].update_one(
                {"datasetId": dataset_id, "snapshotId": plan["snapshotId"]},
                {"$set": {
                    "metadata.rankRepair.compRank": {
                        "version": self.VERSION,
                        "repairedAt": repaired_at,
                        "updatedRows": int(update_result.modified_count),
                    }
                }},
            )

        audit_id = f"rank-field-backfill-{uuid4().hex}"
        self._db["migration_audit"].insert_one({
            "auditId": audit_id,
            "opType": "snapshot_rank_field_backfill",
            "datasetId": dataset_id,
            "version": self.VERSION,
            "createdAt": repaired_at,
            "eligibleSlots": len(eligible),
            "updatedRows": updated_rows,
            "fields": ["compRank"],
        })
        result["updatedRows"] = updated_rows
        result["auditId"] = audit_id
        return result
