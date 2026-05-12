from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


EMPTY_STOCK_SNAPSHOT_IDS = (
    "half_hour:2026-05-08:14:00",
    "hourly:2026-05-08:14:00",
    "quarter_hour:2026-05-08:13:45",
    "quarter_hour:2026-05-08:14:00",
    "quarter_hour:2026-05-08:14:15",
)


def backfill_empty_snapshot_rows(
    database: Any,
    *,
    dataset_id: str = "dragonboard_live",
    snapshot_ids: list[str] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    targets = list(snapshot_ids or EMPTY_STOCK_SNAPSHOT_IDS)
    plans = [_plan_one(database, dataset_id, snapshot_id) for snapshot_id in targets]
    result: dict[str, Any] = {
        "ok": all(plan["ok"] for plan in plans),
        "apply": apply,
        "datasetId": dataset_id,
        "plans": plans,
    }
    if not result["ok"] or not apply:
        return result

    applied = [_apply_one(database, dataset_id, plan) for plan in plans]
    _refresh_dataset_summary(database, dataset_id)
    _write_audit(database, dataset_id, applied)
    result["applied"] = applied
    return result


def _plan_one(database: Any, dataset_id: str, snapshot_id: str) -> dict[str, Any]:
    target = database["snapshot_frames"].find_one({"datasetId": dataset_id, "snapshotId": snapshot_id})
    if not target:
        return {"ok": False, "snapshotId": snapshot_id, "error": "target_frame_not_found"}
    existing_stock_rows = int(database["snapshot_stock_rows"].count_documents({"datasetId": dataset_id, "snapshotId": snapshot_id}))
    if existing_stock_rows:
        return {
            "ok": False,
            "snapshotId": snapshot_id,
            "error": "target_already_has_stock_rows",
            "stockRows": existing_stock_rows,
        }
    donor = _nearest_donor_frame(database, dataset_id, target)
    if not donor:
        return {"ok": False, "snapshotId": snapshot_id, "error": "donor_frame_not_found"}
    donor_stock_rows = int(database["snapshot_stock_rows"].count_documents({"datasetId": dataset_id, "snapshotId": donor["snapshotId"]}))
    donor_sector_rows = int(database["snapshot_sector_rows"].count_documents({"datasetId": dataset_id, "snapshotId": donor["snapshotId"]}))
    return {
        "ok": donor_stock_rows > 0,
        "snapshotId": snapshot_id,
        "type": target.get("type"),
        "tradingDate": target.get("tradingDate"),
        "slotTime": target.get("slotTime"),
        "timestamp": target.get("timestamp"),
        "donorSnapshotId": donor.get("snapshotId"),
        "donorSlotTime": donor.get("slotTime"),
        "donorTimestamp": donor.get("timestamp"),
        "donorDistanceMs": abs(int(target.get("timestamp") or 0) - int(donor.get("timestamp") or 0)),
        "stockRowsToCopy": donor_stock_rows,
        "sectorRowsToCopy": donor_sector_rows,
    }


def _nearest_donor_frame(database: Any, dataset_id: str, target: dict[str, Any]) -> dict[str, Any] | None:
    target_ts = int(target.get("timestamp") or 0)
    rows = list(
        database["snapshot_frames"].find(
            {
                "datasetId": dataset_id,
                "type": target.get("type"),
                "tradingDate": target.get("tradingDate"),
                "snapshotId": {"$ne": target.get("snapshotId")},
            }
        )
    )
    candidates = []
    for row in rows:
        stock_count = int(database["snapshot_stock_rows"].count_documents({"datasetId": dataset_id, "snapshotId": row.get("snapshotId")}))
        if stock_count <= 0:
            continue
        row_ts = int(row.get("timestamp") or 0)
        candidates.append((abs(target_ts - row_ts), 0 if row_ts < target_ts else 1, row_ts, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def _apply_one(database: Any, dataset_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    target = database["snapshot_frames"].find_one({"datasetId": dataset_id, "snapshotId": plan["snapshotId"]})
    donor_snapshot_id = str(plan["donorSnapshotId"])
    stock_rows = [
        _clone_row(row, target)
        for row in database["snapshot_stock_rows"].find({"datasetId": dataset_id, "snapshotId": donor_snapshot_id})
    ]
    sector_rows = [
        _clone_row(row, target)
        for row in database["snapshot_sector_rows"].find({"datasetId": dataset_id, "snapshotId": donor_snapshot_id})
    ]
    if stock_rows:
        database["snapshot_stock_rows"].insert_many(stock_rows, ordered=False)
    if sector_rows:
        database["snapshot_sector_rows"].insert_many(sector_rows, ordered=False)
    metadata = dict(target.get("metadata") or {})
    metadata["backfill"] = {
        "sourceSnapshotId": donor_snapshot_id,
        "reason": "source snapshot was empty during historical debugging",
        "createdAt": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }
    quality_flags = list(target.get("qualityFlags") or [])
    if "backfilled_from_nearest_snapshot" not in quality_flags:
        quality_flags.append("backfilled_from_nearest_snapshot")
    database["snapshot_frames"].update_one(
        {"datasetId": dataset_id, "snapshotId": plan["snapshotId"]},
        {
            "$set": {
                "stockRowCount": len(stock_rows),
                "sectorRowCount": len(sector_rows),
                "metadata": metadata,
                "qualityFlags": quality_flags,
            }
        },
    )
    return {
        "snapshotId": plan["snapshotId"],
        "donorSnapshotId": donor_snapshot_id,
        "insertedStockRows": len(stock_rows),
        "insertedSectorRows": len(sector_rows),
    }


def _clone_row(row: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    cloned = {key: value for key, value in row.items() if key != "_id"}
    snapshot_id = str(target.get("snapshotId") or "")
    cloned["snapshotId"] = snapshot_id
    cloned["type"] = target.get("type")
    cloned["tradingDate"] = target.get("tradingDate")
    cloned["slotTime"] = target.get("slotTime")
    cloned["timestamp"] = target.get("timestamp")
    cloned["displayKey"] = target.get("displayKey") or snapshot_id
    if cloned.get("code"):
        row_id = f"{snapshot_id}:{cloned['code']}"
    else:
        row_id = f"{snapshot_id}:{cloned.get('entityType')}:{cloned.get('entityKey')}"
    cloned["rowId"] = row_id
    if "id" in cloned:
        cloned["id"] = row_id
    return cloned


def _refresh_dataset_summary(database: Any, dataset_id: str) -> None:
    frames = list(database["snapshot_frames"].find({"datasetId": dataset_id}))
    trading_dates = sorted({str(row.get("tradingDate")) for row in frames if row.get("tradingDate")})
    snapshot_types = sorted({str(row.get("type")) for row in frames if row.get("type")})
    database["datasets"].update_one(
        {"id": dataset_id},
        {
            "$set": {
                "snapshotCount": int(database["snapshot_records"].count_documents({"datasetId": dataset_id})),
                "frameCount": len(frames),
                "stockRowCount": int(database["snapshot_stock_rows"].count_documents({"datasetId": dataset_id})),
                "sectorRowCount": int(database["snapshot_sector_rows"].count_documents({"datasetId": dataset_id})),
                "startDate": trading_dates[0] if trading_dates else None,
                "endDate": trading_dates[-1] if trading_dates else None,
                "snapshotTypes": snapshot_types,
            }
        },
    )


def _write_audit(database: Any, dataset_id: str, applied: list[dict[str, Any]]) -> None:
    database["migration_audit"].insert_many(
        [
            {
                "opType": "mongodb_snapshot_backfill",
                "idempotencyKey": f"mongodb_snapshot_backfill:{dataset_id}:{datetime.now(UTC).isoformat()}",
                "createdAt": datetime.now(UTC).replace(tzinfo=None),
                "datasetId": dataset_id,
                "applied": applied,
            }
        ],
        ordered=False,
    )
