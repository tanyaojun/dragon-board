"""Repair missing half_hour / quarter_hour bars by copying from nearest adjacent bar."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from backend.data.repository_factory import get_runtime_mongodb_database

# Expected bar slots for each snapshot type (China market hours, time-only)
HALF_HOUR_SLOTS = [
    "09:30", "10:00", "10:30", "11:00", "11:30",
    "13:00", "13:30", "14:00", "14:30", "15:00",
]

QUARTER_HOUR_SLOTS = [
    "09:30", "09:45", "10:00", "10:15", "10:30", "10:45",
    "11:00", "11:15", "11:30",
    "13:00", "13:15", "13:30", "13:45", "14:00", "14:15",
    "14:30", "14:45", "15:00",
]

EXPECTED_SLOTS: dict[str, list[str]] = {
    "half_hour": HALF_HOUR_SLOTS,
    "quarter_hour": QUARTER_HOUR_SLOTS,
}

CHINA_TZ = timezone(timedelta(hours=8))


def _time_minutes(slot: str) -> int:
    h, m = slot.split(":")
    return int(h) * 60 + int(m)


def _find_nearest_source(missing: str, existing: list[str]) -> str:
    """Find the nearest existing slot to the missing one (prefer earlier)."""
    target = _time_minutes(missing)
    best = existing[0]
    best_dist = abs(_time_minutes(best) - target)
    for s in existing[1:]:
        dist = abs(_time_minutes(s) - target)
        # Prefer earlier bar at same distance
        if dist < best_dist or (dist == best_dist and _time_minutes(s) < _time_minutes(best)):
            best = s
            best_dist = dist
    return best


def _build_snapshot_id(stype: str, date: str, slot: str) -> str:
    return f"{stype}:{date}:{slot}"


def _build_display_key(stype: str, date: str, slot: str) -> str:
    # Match existing format: e.g. "[半小时开盘] 2026-04-16 09:30"
    if stype == "half_hour":
        prefix = "[半小时开盘]"
    elif stype == "quarter_hour":
        prefix = "[一刻开盘]"
    else:
        prefix = "[快照]"
    return f"{prefix} {date} {slot}"


def repair_bars(dataset_id: str = "dragonboard_live", stype: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Fill missing bar slots by copying from nearest adjacent bar on the same date.

    Args:
        dataset_id: MongoDB dataset id.
        stype: 'half_hour' or 'quarter_hour'. None = both.
        dry_run: if True, only report what would be done.
    """
    db = get_runtime_mongodb_database()
    types = [stype] if stype else ["half_hour", "quarter_hour"]
    results: dict[str, Any] = {}

    for tp in types:
        expected = EXPECTED_SLOTS[tp]
        # Collect existing slots per date
        dates: dict[str, set[str]] = {}
        for doc in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": tp},
            {"tradingDate": 1, "slotTime": 1},
        ):
            d = doc["tradingDate"]
            if d not in dates:
                dates[d] = set()
            dates[d].add(doc.get("slotTime", ""))

        repairs: list[dict[str, str]] = []
        for date_str in sorted(dates):
            existing = sorted(dates[date_str])
            missing = [s for s in expected if s not in dates[date_str]]
            if not missing:
                continue
            for miss in missing:
                source = _find_nearest_source(miss, existing)
                repairs.append({
                    "date": date_str,
                    "source_slot": source,
                    "target_slot": miss,
                    "source_snapshot_id": _build_snapshot_id(tp, date_str, source),
                    "target_snapshot_id": _build_snapshot_id(tp, date_str, miss),
                })

        if not dry_run:
            collections_copied = 0
            for r in repairs:
                source_sid = r["source_snapshot_id"]
                target_sid = r["target_snapshot_id"]

                # Check if target already exists (idempotent)
                if db["snapshot_frames"].count_documents({"snapshotId": target_sid}) > 0:
                    continue

                # 1. Copy frame
                frame = db["snapshot_frames"].find_one({"snapshotId": source_sid})
                if not frame:
                    continue
                new_frame = dict(frame)
                del new_frame["_id"]
                new_frame["snapshotId"] = target_sid
                new_frame["slotTime"] = r["target_slot"]
                new_frame["displayKey"] = _build_display_key(tp, r["date"], r["target_slot"])
                # Adjust timestamp: add time difference from source to target
                diff_min = _time_minutes(r["target_slot"]) - _time_minutes(r["source_slot"])
                if isinstance(frame.get("timestamp"), (int, float)):
                    new_frame["timestamp"] = int(frame["timestamp"]) + diff_min * 60 * 1000
                db["snapshot_frames"].insert_one(new_frame)

                # 2. Copy stock rows (update rowId to match new snapshotId)
                existing_stock_count = db["snapshot_stock_rows"].count_documents({"snapshotId": target_sid})
                if existing_stock_count == 0:
                    stock_rows = list(db["snapshot_stock_rows"].find({"snapshotId": source_sid}))
                    if stock_rows:
                        new_rows = []
                        for row in stock_rows:
                            nr = dict(row)
                            del nr["_id"]
                            nr["snapshotId"] = target_sid
                            code = str(nr.get("code") or "")
                            nr["rowId"] = f"{target_sid}:{code}" if code else target_sid
                            new_rows.append(nr)
                        db["snapshot_stock_rows"].insert_many(new_rows)

                # 3. Copy sector rows (update rowId to match new snapshotId)
                existing_sector_count = db["snapshot_sector_rows"].count_documents({"snapshotId": target_sid})
                if existing_sector_count == 0:
                    sector_rows = list(db["snapshot_sector_rows"].find({"snapshotId": source_sid}))
                    if sector_rows:
                        new_rows = []
                        for row in sector_rows:
                            nr = dict(row)
                            del nr["_id"]
                            nr["snapshotId"] = target_sid
                            key = str(nr.get("entityKey") or nr.get("entityCode") or nr.get("code") or "")
                            nr["rowId"] = f"{target_sid}:{key}" if key else target_sid
                            new_rows.append(nr)
                        db["snapshot_sector_rows"].insert_many(new_rows, ordered=False)

                collections_copied += 1

            results[tp] = {
                "planned": len(repairs),
                "executed": collections_copied,
                "repairs": repairs if len(repairs) <= 20 else repairs[:10] + [{"...": f"+{len(repairs)-10} more"}],
            }
        else:
            results[tp] = {
                "planned": len(repairs),
                "dry_run": True,
                "repairs": repairs if len(repairs) <= 30 else repairs[:20] + [{"...": f"+{len(repairs)-20} more"}],
            }

    return results


if __name__ == "__main__":
    import json

    print("Dry run first...")
    result = repair_bars(dry_run=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    total = sum(v.get("planned", 0) for v in result.values())
    if total == 0:
        print("\nNo missing bars to repair.")
    else:
        resp = input(f"\nRepair {total} missing bars? [y/N] ")
        if resp.lower() == "y":
            result = repair_bars(dry_run=False)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("Done.")
        else:
            print("Aborted.")
