from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.data.mongodb_migration import EXPECTED_SNAPSHOT_SLOTS, build_mongodb_indexes


EXPLICIT_DONOR_SNAPSHOT_IDS = {
    "half_hour:2026-05-07:13:00": "quarter_hour:2026-05-07:13:15",
}

SUPPORTED_MISSING_SLOT_RULES = (
    {
        "targetType": "half_hour",
        "slotTime": "15:00",
        "donorType": "daily",
    },
)

def backfill_empty_snapshot_rows(
    database: Any,
    *,
    dataset_id: str = "dragonboard_live",
    snapshot_ids: list[str] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    frame_rows = list(database["snapshot_frames"].find({"datasetId": dataset_id}))
    stock_counts = _row_counts(database, dataset_id, "snapshot_stock_rows")
    sector_counts = _row_counts(database, dataset_id, "snapshot_sector_rows")
    target_snapshot_ids = list(
        snapshot_ids or _default_target_snapshot_ids(database, dataset_id, frame_rows, stock_counts, sector_counts)
    )
    scoped_snapshot_ids = set(target_snapshot_ids)
    plans = [
        _plan_snapshot_repair(
            database,
            dataset_id,
            snapshot_id,
            frame_rows=frame_rows,
            stock_counts=stock_counts,
            sector_counts=sector_counts,
        )
        for snapshot_id in target_snapshot_ids
    ]

    effective_scope = scoped_snapshot_ids or {
        str(row.get("snapshotId") or "") for row in frame_rows if row.get("snapshotId")
    }
    missing_record_repairs = _plan_missing_records(
        database,
        dataset_id,
        frame_rows,
        snapshot_scope=effective_scope,
    )
    count_fixes = _plan_count_fixes(frame_rows, stock_counts, sector_counts, snapshot_scope=effective_scope)
    missing_slots = _find_missing_slots(frame_rows)
    index_repairs = _plan_missing_indexes(database)

    result: dict[str, Any] = {
        "ok": all(plan["ok"] for plan in plans),
        "apply": apply,
        "datasetId": dataset_id,
        "plans": plans,
        "missingRecordRepairs": missing_record_repairs,
        "countFixes": count_fixes,
        "missingSlots": [item for item in missing_slots if item["snapshotId"] in effective_scope],
        "indexRepairs": index_repairs,
    }
    if not result["ok"] or not apply:
        return result

    applied_plans = [
        _apply_snapshot_plan(database, dataset_id, plan)
        for plan in plans
        if plan.get("action") not in {None, "noop"}
    ]

    frame_rows = list(database["snapshot_frames"].find({"datasetId": dataset_id}))
    stock_counts = _row_counts(database, dataset_id, "snapshot_stock_rows")
    sector_counts = _row_counts(database, dataset_id, "snapshot_sector_rows")
    refreshed_scope = set(effective_scope)
    refreshed_scope.update(str(item.get("snapshotId") or "") for item in applied_plans if item.get("snapshotId"))
    applied_count_fixes = _apply_count_fixes(
        database,
        frame_rows,
        stock_counts,
        sector_counts,
        snapshot_scope=refreshed_scope,
    )
    applied_missing_records = _apply_missing_records(
        database,
        dataset_id,
        frame_rows,
        snapshot_scope=refreshed_scope,
    )
    applied_index_repairs = _ensure_missing_indexes(database)
    _refresh_dataset_summary(database, dataset_id)
    _write_audit(
        database,
        dataset_id,
        {
            "snapshotRepairs": applied_plans,
            "countFixes": applied_count_fixes,
            "missingRecords": applied_missing_records,
            "indexRepairs": applied_index_repairs,
        },
    )
    result["applied"] = {
        "snapshotRepairs": applied_plans,
        "countFixes": applied_count_fixes,
        "missingRecords": applied_missing_records,
        "indexRepairs": applied_index_repairs,
    }
    return result


def copy_missing_snapshot_slots_from_dataset(
    database: Any,
    *,
    target_dataset_id: str,
    donor_dataset_id: str,
    snapshot_ids: list[str],
    apply: bool = False,
) -> dict[str, Any]:
    plans = [
        _plan_cross_dataset_slot_copy(
            database,
            target_dataset_id=target_dataset_id,
            donor_dataset_id=donor_dataset_id,
            snapshot_id=snapshot_id,
        )
        for snapshot_id in snapshot_ids
    ]
    result: dict[str, Any] = {
        "ok": all(plan["ok"] for plan in plans),
        "apply": apply,
        "targetDatasetId": target_dataset_id,
        "donorDatasetId": donor_dataset_id,
        "plans": plans,
    }
    if not result["ok"] or not apply:
        return result

    applied = [
        _apply_cross_dataset_slot_copy(
            database,
            target_dataset_id=target_dataset_id,
            donor_dataset_id=donor_dataset_id,
            plan=plan,
        )
        for plan in plans
    ]
    _refresh_dataset_summary(database, target_dataset_id)
    _write_slot_copy_audit(
        database,
        target_dataset_id=target_dataset_id,
        donor_dataset_id=donor_dataset_id,
        applied=applied,
    )
    result["applied"] = applied
    return result


def _default_target_snapshot_ids(
    database: Any,
    dataset_id: str,
    frame_rows: list[dict[str, Any]],
    stock_counts: dict[str, int],
    sector_counts: dict[str, int],
) -> list[str]:
    targets: set[str] = set()
    for frame in frame_rows:
        snapshot_id = str(frame.get("snapshotId") or "")
        if not snapshot_id:
            continue
        if int(frame.get("stockRowCount") or 0) > 0 and stock_counts.get(snapshot_id, 0) == 0:
            targets.add(snapshot_id)
    for plan in _plan_missing_records(database, dataset_id, frame_rows, snapshot_scope=_all_snapshot_ids(frame_rows)):
        targets.add(str(plan["snapshotId"]))
    for plan in _plan_count_fixes(
        frame_rows,
        stock_counts,
        sector_counts,
        snapshot_scope=_all_snapshot_ids(frame_rows),
    ):
        targets.add(str(plan["snapshotId"]))
    for slot in _find_missing_slots(frame_rows):
        targets.add(slot["snapshotId"])
    return sorted(targets)


def _all_snapshot_ids(frame_rows: list[dict[str, Any]]) -> set[str]:
    return {str(row.get("snapshotId") or "") for row in frame_rows if row.get("snapshotId")}


def _plan_snapshot_repair(
    database: Any,
    dataset_id: str,
    snapshot_id: str,
    *,
    frame_rows: list[dict[str, Any]],
    stock_counts: dict[str, int],
    sector_counts: dict[str, int],
) -> dict[str, Any]:
    frame_by_snapshot = {
        str(row.get("snapshotId") or ""): row for row in frame_rows if row.get("snapshotId")
    }
    target = frame_by_snapshot.get(snapshot_id)
    if target:
        existing_stock_rows = int(stock_counts.get(snapshot_id, 0))
        if existing_stock_rows:
            return {
                "ok": True,
                "action": "noop",
                "snapshotId": snapshot_id,
                "status": "target_already_has_stock_rows",
                "stockRows": existing_stock_rows,
            }
        donor = _resolve_donor_frame(
            database,
            dataset_id,
            target,
            frame_rows=frame_rows,
            stock_counts=stock_counts,
        )
        if not donor:
            return {"ok": False, "snapshotId": snapshot_id, "error": "donor_frame_not_found"}
        donor_snapshot_id = str(donor.get("snapshotId") or "")
        donor_stock_rows = int(stock_counts.get(donor_snapshot_id, 0))
        donor_sector_rows = int(sector_counts.get(donor_snapshot_id, 0))
        return {
            "ok": donor_stock_rows > 0,
            "action": "backfill_rows",
            "snapshotId": snapshot_id,
            "type": target.get("type"),
            "tradingDate": target.get("tradingDate"),
            "slotTime": target.get("slotTime"),
            "timestamp": target.get("timestamp"),
            "donorSnapshotId": donor_snapshot_id,
            "donorType": donor.get("type"),
            "donorSlotTime": donor.get("slotTime"),
            "donorTimestamp": donor.get("timestamp"),
            "donorDistanceMs": abs(int(target.get("timestamp") or 0) - int(donor.get("timestamp") or 0)),
            "stockRowsToCopy": donor_stock_rows,
            "sectorRowsToCopy": donor_sector_rows,
            "crossType": str(target.get("type") or "") != str(donor.get("type") or ""),
        }

    slot_plan = _plan_missing_slot_snapshot(
        database,
        dataset_id,
        snapshot_id,
        frame_rows=frame_rows,
        stock_counts=stock_counts,
        sector_counts=sector_counts,
    )
    if slot_plan:
        return slot_plan
    return {"ok": False, "snapshotId": snapshot_id, "error": "target_frame_not_found"}


def _plan_cross_dataset_slot_copy(
    database: Any,
    *,
    target_dataset_id: str,
    donor_dataset_id: str,
    snapshot_id: str,
) -> dict[str, Any]:
    target_frame = database["snapshot_frames"].find_one(
        {"datasetId": target_dataset_id, "snapshotId": snapshot_id}
    )
    if target_frame:
        return {
            "ok": False,
            "snapshotId": snapshot_id,
            "targetDatasetId": target_dataset_id,
            "donorDatasetId": donor_dataset_id,
            "error": "target_frame_already_exists",
        }
    target_record = database["snapshot_records"].find_one(
        {"datasetId": target_dataset_id, "snapshotId": snapshot_id}
    )
    if target_record:
        return {
            "ok": False,
            "snapshotId": snapshot_id,
            "targetDatasetId": target_dataset_id,
            "donorDatasetId": donor_dataset_id,
            "error": "target_record_already_exists",
        }
    donor_record = database["snapshot_records"].find_one(
        {"datasetId": donor_dataset_id, "snapshotId": snapshot_id}
    )
    donor_frame = database["snapshot_frames"].find_one(
        {"datasetId": donor_dataset_id, "snapshotId": snapshot_id}
    )
    if not donor_record or not donor_frame:
        return {
            "ok": False,
            "snapshotId": snapshot_id,
            "targetDatasetId": target_dataset_id,
            "donorDatasetId": donor_dataset_id,
            "error": "donor_snapshot_not_found",
        }
    donor_stock_rows = int(
        database["snapshot_stock_rows"].count_documents(
            {"datasetId": donor_dataset_id, "snapshotId": snapshot_id}
        )
    )
    donor_sector_rows = int(
        database["snapshot_sector_rows"].count_documents(
            {"datasetId": donor_dataset_id, "snapshotId": snapshot_id}
        )
    )
    return {
        "ok": donor_stock_rows > 0,
        "snapshotId": snapshot_id,
        "targetDatasetId": target_dataset_id,
        "donorDatasetId": donor_dataset_id,
        "type": donor_frame.get("type"),
        "tradingDate": donor_frame.get("tradingDate"),
        "slotTime": donor_frame.get("slotTime"),
        "timestamp": donor_frame.get("timestamp"),
        "stockRowsToCopy": donor_stock_rows,
        "sectorRowsToCopy": donor_sector_rows,
        **({} if donor_stock_rows > 0 else {"error": "donor_has_no_stock_rows"}),
    }


def _resolve_donor_frame(
    database: Any,
    dataset_id: str,
    target: dict[str, Any],
    *,
    frame_rows: list[dict[str, Any]],
    stock_counts: dict[str, int],
) -> dict[str, Any] | None:
    target_snapshot_id = str(target.get("snapshotId") or "")
    explicit_snapshot_id = EXPLICIT_DONOR_SNAPSHOT_IDS.get(target_snapshot_id)
    if explicit_snapshot_id:
        donor = database["snapshot_frames"].find_one(
            {"datasetId": dataset_id, "snapshotId": explicit_snapshot_id}
        )
        if donor and stock_counts.get(explicit_snapshot_id, 0) > 0:
            return donor

    target_ts = int(target.get("timestamp") or 0)
    candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    for row in frame_rows:
        if (
            row.get("datasetId") != dataset_id
            or row.get("type") != target.get("type")
            or row.get("tradingDate") != target.get("tradingDate")
            or row.get("snapshotId") == target_snapshot_id
        ):
            continue
        donor_snapshot_id = str(row.get("snapshotId") or "")
        if stock_counts.get(donor_snapshot_id, 0) <= 0:
            continue
        row_ts = int(row.get("timestamp") or 0)
        candidates.append((abs(target_ts - row_ts), 0 if row_ts < target_ts else 1, row_ts, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def _plan_missing_slot_snapshot(
    database: Any,
    dataset_id: str,
    snapshot_id: str,
    *,
    frame_rows: list[dict[str, Any]],
    stock_counts: dict[str, int],
    sector_counts: dict[str, int],
) -> dict[str, Any] | None:
    target_type, trading_date, slot_time = _split_snapshot_id(snapshot_id)
    if not target_type or not trading_date or not slot_time:
        return None
    donor = _resolve_missing_slot_donor(
        database,
        dataset_id,
        target_type,
        trading_date,
        slot_time,
        frame_rows=frame_rows,
        stock_counts=stock_counts,
    )
    if not donor:
        return {
            "ok": False,
            "action": "create_slot",
            "snapshotId": snapshot_id,
            "error": "donor_frame_not_found",
            "targetType": target_type,
            "tradingDate": trading_date,
            "slotTime": slot_time,
        }
    donor_snapshot_id = str(donor.get("snapshotId") or "")
    donor_stock_rows = int(stock_counts.get(donor_snapshot_id, 0))
    donor_sector_rows = int(sector_counts.get(donor_snapshot_id, 0))
    return {
        "ok": donor_stock_rows > 0,
        "action": "create_slot",
        "snapshotId": snapshot_id,
        "type": target_type,
        "tradingDate": trading_date,
        "slotTime": slot_time,
        "timestamp": _slot_timestamp_ms(trading_date, slot_time),
        "donorSnapshotId": donor_snapshot_id,
        "donorType": donor.get("type"),
        "stockRowsToCopy": donor_stock_rows,
        "sectorRowsToCopy": donor_sector_rows,
        "crossType": str(target_type) != str(donor.get("type") or ""),
    }


def _resolve_missing_slot_donor(
    database: Any,
    dataset_id: str,
    target_type: str,
    trading_date: str,
    slot_time: str,
    *,
    frame_rows: list[dict[str, Any]],
    stock_counts: dict[str, int],
) -> dict[str, Any] | None:
    for rule in SUPPORTED_MISSING_SLOT_RULES:
        if rule["targetType"] != target_type or rule["slotTime"] != slot_time:
            continue
        donor_snapshot_id = f"{rule['donorType']}:{trading_date}:{slot_time}"
        donor = database["snapshot_frames"].find_one(
            {"datasetId": dataset_id, "snapshotId": donor_snapshot_id}
        )
        if donor and stock_counts.get(donor_snapshot_id, 0) > 0:
            return donor

    target_ts = _slot_timestamp_ms(trading_date, slot_time)
    candidates: list[tuple[int, int, int, dict[str, Any]]] = []
    for row in frame_rows:
        if row.get("datasetId") != dataset_id or row.get("tradingDate") != trading_date:
            continue
        donor_snapshot_id = str(row.get("snapshotId") or "")
        if stock_counts.get(donor_snapshot_id, 0) <= 0:
            continue
        donor_type = str(row.get("type") or "")
        row_ts = int(row.get("timestamp") or 0)
        candidates.append(
            (
                abs(target_ts - row_ts),
                0 if donor_type == target_type else 1,
                0 if row_ts < target_ts else 1,
                row_ts,
                row,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return candidates[0][4]


def _apply_snapshot_plan(database: Any, dataset_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    if plan["action"] == "create_slot":
        return _apply_missing_slot_plan(database, dataset_id, plan)
    return _apply_backfill_plan(database, dataset_id, plan)


def _apply_backfill_plan(database: Any, dataset_id: str, plan: dict[str, Any]) -> dict[str, Any]:
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
        "sourceType": plan.get("donorType"),
        "reason": "snapshot rows repaired from donor snapshot",
        "createdAt": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }
    quality_flags = list(target.get("qualityFlags") or [])
    quality_flag = "backfilled_from_cross_type_snapshot" if plan.get("crossType") else "backfilled_from_nearest_snapshot"
    if quality_flag not in quality_flags:
        quality_flags.append(quality_flag)
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
        "action": "backfill_rows",
        "snapshotId": plan["snapshotId"],
        "donorSnapshotId": donor_snapshot_id,
        "insertedStockRows": len(stock_rows),
        "insertedSectorRows": len(sector_rows),
    }


def _apply_missing_slot_plan(database: Any, dataset_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    donor_snapshot_id = str(plan["donorSnapshotId"])
    donor = database["snapshot_frames"].find_one({"datasetId": dataset_id, "snapshotId": donor_snapshot_id})
    target = _build_slot_frame_from_donor(donor, plan)
    database["snapshot_frames"].insert_many([target], ordered=False)
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
    target["stockRowCount"] = len(stock_rows)
    target["sectorRowCount"] = len(sector_rows)
    database["snapshot_frames"].update_one(
        {"datasetId": dataset_id, "snapshotId": plan["snapshotId"]},
        {
            "$set": {
                "stockRowCount": len(stock_rows),
                "sectorRowCount": len(sector_rows),
            }
        },
    )
    database["snapshot_records"].insert_many([_record_from_frame(target, dataset_id)], ordered=False)
    return {
        "action": "create_slot",
        "snapshotId": plan["snapshotId"],
        "donorSnapshotId": donor_snapshot_id,
        "insertedStockRows": len(stock_rows),
        "insertedSectorRows": len(sector_rows),
        "insertedRecord": True,
        "insertedFrame": True,
    }


def _build_slot_frame_from_donor(donor: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = str(plan["snapshotId"])
    metadata = dict(donor.get("metadata") or {})
    metadata["backfill"] = {
        "sourceSnapshotId": str(plan["donorSnapshotId"]),
        "sourceType": plan.get("donorType"),
        "reason": "missing formal snapshot slot created from donor snapshot",
        "createdAt": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }
    quality_flags = list(donor.get("qualityFlags") or [])
    quality_flag = "backfilled_from_cross_type_snapshot" if plan.get("crossType") else "backfilled_from_nearest_snapshot"
    if quality_flag not in quality_flags:
        quality_flags.append(quality_flag)
    donor_without_id = {key: value for key, value in donor.items() if key != "_id"}
    synthetic_timestamp = plan["timestamp"]
    return {
        key: value
        for key, value in {
            **donor_without_id,
            "snapshotId": snapshot_id,
            "type": plan["type"],
            "tradingDate": plan["tradingDate"],
            "slotTime": plan["slotTime"],
            "timestamp": synthetic_timestamp,
            "capturedAt": donor_without_id.get("capturedAt") or synthetic_timestamp,
            "dataTimestamp": synthetic_timestamp,
            "displayKey": snapshot_id,
            "captureMode": "synthesized",
            "source": "cross_type_backfill" if plan.get("crossType") else "same_type_backfill",
            "delayMs": 0,
            "qualityFlags": quality_flags,
            "metadata": metadata,
            "stockRowCount": int(plan.get("stockRowsToCopy") or 0),
            "sectorRowCount": int(plan.get("sectorRowsToCopy") or 0),
        }.items()
        if key != "_id"
    }


def _apply_cross_dataset_slot_copy(
    database: Any,
    *,
    target_dataset_id: str,
    donor_dataset_id: str,
    plan: dict[str, Any],
) -> dict[str, Any]:
    snapshot_id = str(plan["snapshotId"])
    donor_record = database["snapshot_records"].find_one(
        {"datasetId": donor_dataset_id, "snapshotId": snapshot_id}
    )
    donor_frame = database["snapshot_frames"].find_one(
        {"datasetId": donor_dataset_id, "snapshotId": snapshot_id}
    )
    if not donor_record or not donor_frame:
        raise ValueError(f"donor snapshot not found: {donor_dataset_id}:{snapshot_id}")

    repair_metadata = {
        "sourceDatasetId": donor_dataset_id,
        "sourceSnapshotId": snapshot_id,
        "reason": "target shadow slot was missing; copied from same-slot live facts",
        "createdAt": datetime.now(UTC).replace(tzinfo=None).isoformat(),
    }
    target_record = _clone_snapshot_doc(
        donor_record,
        target_dataset_id=target_dataset_id,
        repair_metadata=repair_metadata,
        quality_flag="copied_from_donor_dataset",
    )
    target_frame = _clone_snapshot_doc(
        donor_frame,
        target_dataset_id=target_dataset_id,
        repair_metadata=repair_metadata,
        quality_flag="copied_from_donor_dataset",
    )
    stock_rows = [
        _clone_row(row, target_frame, target_dataset_id=target_dataset_id)
        for row in database["snapshot_stock_rows"].find(
            {"datasetId": donor_dataset_id, "snapshotId": snapshot_id}
        )
    ]
    sector_rows = [
        _clone_row(row, target_frame, target_dataset_id=target_dataset_id)
        for row in database["snapshot_sector_rows"].find(
            {"datasetId": donor_dataset_id, "snapshotId": snapshot_id}
        )
    ]
    target_record["stockRowCount"] = len(stock_rows)
    target_record["sectorRowCount"] = len(sector_rows)
    target_frame["stockRowCount"] = len(stock_rows)
    target_frame["sectorRowCount"] = len(sector_rows)

    try:
        database["snapshot_records"].insert_many([target_record], ordered=False)
        database["snapshot_frames"].insert_many([target_frame], ordered=False)
        if stock_rows:
            database["snapshot_stock_rows"].insert_many(stock_rows, ordered=False)
        if sector_rows:
            database["snapshot_sector_rows"].insert_many(sector_rows, ordered=False)
    except Exception:
        _rollback_cross_dataset_slot_copy(database, target_dataset_id, snapshot_id)
        raise
    return {
        "snapshotId": snapshot_id,
        "donorDatasetId": donor_dataset_id,
        "insertedRecords": 1,
        "insertedFrames": 1,
        "insertedStockRows": len(stock_rows),
        "insertedSectorRows": len(sector_rows),
    }


def _rollback_cross_dataset_slot_copy(database: Any, target_dataset_id: str, snapshot_id: str) -> None:
    query = {"datasetId": target_dataset_id, "snapshotId": snapshot_id}
    for collection_name in (
        "snapshot_stock_rows",
        "snapshot_sector_rows",
        "snapshot_frames",
        "snapshot_records",
    ):
        database[collection_name].delete_many(query)


def _clone_snapshot_doc(
    row: dict[str, Any],
    *,
    target_dataset_id: str,
    repair_metadata: dict[str, Any],
    quality_flag: str | None = None,
) -> dict[str, Any]:
    cloned = {key: value for key, value in row.items() if key != "_id"}
    cloned["datasetId"] = target_dataset_id
    metadata = dict(cloned.get("metadata") or {})
    metadata["repair"] = repair_metadata
    cloned["metadata"] = metadata
    if quality_flag:
        quality_flags = list(cloned.get("qualityFlags") or [])
        if quality_flag not in quality_flags:
            quality_flags.append(quality_flag)
        cloned["qualityFlags"] = quality_flags
    return cloned


def _clone_snapshot_doc(
    row: dict[str, Any],
    *,
    target_dataset_id: str,
    repair_metadata: dict[str, Any],
    quality_flag: str | None = None,
) -> dict[str, Any]:
    cloned = {key: value for key, value in row.items() if key != "_id"}
    cloned["datasetId"] = target_dataset_id
    metadata = dict(cloned.get("metadata") or {})
    metadata["repair"] = repair_metadata
    cloned["metadata"] = metadata
    if quality_flag:
        quality_flags = list(cloned.get("qualityFlags") or [])
        if quality_flag not in quality_flags:
            quality_flags.append(quality_flag)
        cloned["qualityFlags"] = quality_flags
    return cloned


def _clone_row(
    row: dict[str, Any],
    target: dict[str, Any],
    *,
    target_dataset_id: str | None = None,
) -> dict[str, Any]:
    cloned = {key: value for key, value in row.items() if key != "_id"}
    snapshot_id = str(target.get("snapshotId") or "")
    if target_dataset_id:
        cloned["datasetId"] = target_dataset_id
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


def _plan_missing_records(
    database: Any,
    dataset_id: str,
    frame_rows: list[dict[str, Any]],
    *,
    snapshot_scope: set[str],
) -> list[dict[str, Any]]:
    record_ids = {
        str(row.get("snapshotId") or "")
        for row in database["snapshot_records"].find({"datasetId": dataset_id})
        if row.get("snapshotId")
    }
    plans: list[dict[str, Any]] = []
    for frame in frame_rows:
        snapshot_id = str(frame.get("snapshotId") or "")
        if not snapshot_id or snapshot_id in record_ids or snapshot_id not in snapshot_scope:
            continue
        plans.append(
            {
                "snapshotId": snapshot_id,
                "type": frame.get("type"),
                "tradingDate": frame.get("tradingDate"),
                "slotTime": frame.get("slotTime"),
            }
        )
    return plans


def _apply_missing_records(
    database: Any,
    dataset_id: str,
    frame_rows: list[dict[str, Any]],
    *,
    snapshot_scope: set[str],
) -> list[dict[str, Any]]:
    plans = _plan_missing_records(database, dataset_id, frame_rows, snapshot_scope=snapshot_scope)
    if not plans:
        return []
    frame_by_snapshot = {
        str(row.get("snapshotId") or ""): row for row in frame_rows if row.get("snapshotId")
    }
    rows = [_record_from_frame(frame_by_snapshot[plan["snapshotId"]], dataset_id) for plan in plans]
    database["snapshot_records"].insert_many(rows, ordered=False)
    return plans


def _record_from_frame(frame: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    timestamp = int(frame.get("timestamp") or 0)
    return {
        "datasetId": dataset_id,
        "snapshotId": str(frame.get("snapshotId") or ""),
        "type": str(frame.get("type") or ""),
        "tradingDate": str(frame.get("tradingDate") or ""),
        "slotTime": str(frame.get("slotTime") or ""),
        "timestamp": timestamp,
        "displayKey": str(frame.get("displayKey") or frame.get("snapshotId") or ""),
        "captureMode": str(frame.get("captureMode") or "real_time"),
        "capturedAt": int(frame.get("capturedAt") or timestamp),
        "dataTimestamp": int(frame.get("dataTimestamp") or timestamp),
        "delayMs": int(frame.get("delayMs") or 0),
        "qualityFlags": frame.get("qualityFlags") if isinstance(frame.get("qualityFlags"), list) else [],
        "source": str(frame.get("source") or "browser_runtime"),
    }


def _plan_count_fixes(
    frame_rows: list[dict[str, Any]],
    stock_counts: dict[str, int],
    sector_counts: dict[str, int],
    *,
    snapshot_scope: set[str],
) -> list[dict[str, Any]]:
    fixes: list[dict[str, Any]] = []
    for frame in frame_rows:
        snapshot_id = str(frame.get("snapshotId") or "")
        if not snapshot_id or snapshot_id not in snapshot_scope:
            continue
        actual_stock = int(stock_counts.get(snapshot_id, 0))
        actual_sector = int(sector_counts.get(snapshot_id, 0))
        declared_stock = int(frame.get("stockRowCount") or 0)
        declared_sector = int(frame.get("sectorRowCount") or 0)
        if declared_stock == actual_stock and declared_sector == actual_sector:
            continue
        fixes.append(
            {
                "snapshotId": snapshot_id,
                "type": frame.get("type"),
                "tradingDate": frame.get("tradingDate"),
                "slotTime": frame.get("slotTime"),
                "declaredStockRowCount": declared_stock,
                "actualStockRowCount": actual_stock,
                "declaredSectorRowCount": declared_sector,
                "actualSectorRowCount": actual_sector,
            }
        )
    return fixes


def _apply_count_fixes(
    database: Any,
    frame_rows: list[dict[str, Any]],
    stock_counts: dict[str, int],
    sector_counts: dict[str, int],
    *,
    snapshot_scope: set[str],
) -> list[dict[str, Any]]:
    fixes = _plan_count_fixes(frame_rows, stock_counts, sector_counts, snapshot_scope=snapshot_scope)
    for item in fixes:
        database["snapshot_frames"].update_one(
            {"snapshotId": item["snapshotId"]},
            {
                "$set": {
                    "stockRowCount": item["actualStockRowCount"],
                    "sectorRowCount": item["actualSectorRowCount"],
                }
            },
        )
    return fixes


def _find_missing_slots(frame_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing_snapshot_ids = {str(row.get("snapshotId") or "") for row in frame_rows if row.get("snapshotId")}
    slots_by_type_date: dict[tuple[str, str], set[str]] = {}
    frames_by_date: dict[str, list[dict[str, Any]]] = {}
    for row in frame_rows:
        snapshot_type = str(row.get("type") or "")
        trading_date = str(row.get("tradingDate") or "")
        slot_time = str(row.get("slotTime") or "")
        if not snapshot_type or not trading_date or not slot_time:
            continue
        slots_by_type_date.setdefault((snapshot_type, trading_date), set()).add(slot_time)
        frames_by_date.setdefault(trading_date, []).append(row)
    missing: list[dict[str, Any]] = []
    for (snapshot_type, trading_date), actual_slots in slots_by_type_date.items():
        expected_slots = EXPECTED_SNAPSHOT_SLOTS.get(snapshot_type)
        if not expected_slots:
            continue
        close_slot = expected_slots[-1]
        snapshot_id = f"{snapshot_type}:{trading_date}:{close_slot}"
        if snapshot_id in existing_snapshot_ids or close_slot in actual_slots:
            continue
        if snapshot_type == "daily":
            intraday_present = any(
                str(row.get("type") or "") in {"quarter_hour", "half_hour", "hourly"}
                for row in frames_by_date.get(trading_date, [])
            )
            if not intraday_present:
                continue
        elif not any(slot in actual_slots for slot in expected_slots[:-1]):
            continue
        missing.append(
            {
                "snapshotId": snapshot_id,
                "type": snapshot_type,
                "tradingDate": trading_date,
                "slotTime": close_slot,
            }
        )
    for trading_date, rows in frames_by_date.items():
        daily_snapshot_id = f"daily:{trading_date}:15:30"
        if daily_snapshot_id in existing_snapshot_ids:
            continue
        intraday_present = any(
            str(row.get("type") or "") in {"quarter_hour", "half_hour", "hourly"}
            for row in rows
        )
        if not intraday_present:
            continue
        missing.append(
            {
                "snapshotId": daily_snapshot_id,
                "type": "daily",
                "tradingDate": trading_date,
                "slotTime": "15:30",
            }
        )
    missing.sort(key=lambda item: (str(item["tradingDate"]), str(item["snapshotId"])))
    return missing


def _slot_timestamp_ms(trading_date: str, slot_time: str) -> int:
    local = datetime.fromisoformat(f"{trading_date}T{slot_time}:00+08:00")
    return int(local.timestamp() * 1000)


def _plan_missing_indexes(database: Any) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for collection_name, expected_indexes in build_mongodb_indexes().items():
        collection = database[collection_name]
        index_info = collection.index_information() if hasattr(collection, "index_information") else {}
        normalized = [_normalize_index_detail(detail) for detail in index_info.values()]
        for expected in expected_indexes:
            expected_key = list(expected["keys"])
            expected_unique = bool(expected.get("unique", False))
            if not any(item["keys"] == expected_key and (not expected_unique or item["unique"]) for item in normalized):
                missing.append(
                    {
                        "collection": collection_name,
                        "keys": expected_key,
                        "unique": expected_unique,
                    }
                )
    return missing


def _ensure_missing_indexes(database: Any) -> list[dict[str, Any]]:
    missing = _plan_missing_indexes(database)
    for item in missing:
        name = "_".join(f"{key}_{direction}" for key, direction in item["keys"])
        database[item["collection"]].create_index(item["keys"], unique=item["unique"], name=name)
    return missing


def _normalize_index_detail(detail: dict[str, Any]) -> dict[str, Any]:
    keys = detail.get("key") or detail.get("keys") or []
    return {
        "keys": [tuple(item) for item in keys],
        "unique": bool(detail.get("unique", False)),
    }


def _row_counts(database: Any, dataset_id: str, collection_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in database[collection_name].find({"datasetId": dataset_id}):
        snapshot_id = str(row.get("snapshotId") or "")
        if not snapshot_id:
            continue
        counts[snapshot_id] = counts.get(snapshot_id, 0) + 1
    return counts


def _split_snapshot_id(snapshot_id: str) -> tuple[str, str, str]:
    parts = snapshot_id.split(":")
    if len(parts) < 3:
        return "", "", ""
    return parts[0], parts[1], ":".join(parts[2:])


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


def _write_audit(database: Any, dataset_id: str, applied: dict[str, Any]) -> None:
    database["migration_audit"].insert_many(
        [
            {
                "opType": "mongodb_snapshot_repair",
                "idempotencyKey": f"mongodb_snapshot_repair:{dataset_id}:{datetime.now(UTC).isoformat()}",
                "createdAt": datetime.now(UTC).replace(tzinfo=None),
                "datasetId": dataset_id,
                "applied": applied,
            }
        ],
        ordered=False,
    )


def _write_slot_copy_audit(
    database: Any,
    *,
    target_dataset_id: str,
    donor_dataset_id: str,
    applied: list[dict[str, Any]],
) -> None:
    now = datetime.now(UTC)
    snapshot_key = ",".join(str(row.get("snapshotId")) for row in applied)
    database["migration_audit"].insert_many(
        [
            {
                "opType": "mongodb_snapshot_slot_copy",
                "idempotencyKey": (
                    f"mongodb_snapshot_slot_copy:{target_dataset_id}:"
                    f"{donor_dataset_id}:{snapshot_key}:{now.isoformat()}"
                ),
                "createdAt": now.replace(tzinfo=None),
                "targetDatasetId": target_dataset_id,
                "donorDatasetId": donor_dataset_id,
                "applied": applied,
            }
        ],
        ordered=False,
    )
