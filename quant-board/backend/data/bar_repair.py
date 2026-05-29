"""Repair missing half_hour / quarter_hour bars by interpolating from adjacent bars."""
from __future__ import annotations

from typing import Any

from backend.data.repository_factory import get_runtime_mongodb_database

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


def _time_minutes(slot: str) -> int:
    h, m = slot.split(":")
    return int(h) * 60 + int(m)


def _snapshot_id(stype: str, date: str, slot: str) -> str:
    return f"{stype}:{date}:{slot}"


def _display_key(stype: str, date: str, slot: str) -> str:
    prefix = {"half_hour": "[半小时开盘]", "quarter_hour": "[一刻开盘]"}.get(stype, "[快照]")
    return f"{prefix} {date} {slot}"


def _find_neighbors(target_slot: str, existing_slots: list[str]) -> tuple[str | None, str | None]:
    """Find nearest existing slots before and after the target slot on the same date."""
    target = _time_minutes(target_slot)
    prev_slot: str | None = None
    next_slot: str | None = None
    for s in sorted(existing_slots):
        t = _time_minutes(s)
        if t < target:
            prev_slot = s
        elif t > target and next_slot is None:
            next_slot = s
    return prev_slot, next_slot


def _interpolate(value_before: float, value_after: float, ratio: float) -> float:
    return round(value_before + (value_after - value_before) * ratio, 4)


def _delete_bar(db: Any, snapshot_id: str) -> int:
    """Delete a synthesized bar and all its associated rows."""
    n = 0
    n += db["snapshot_frames"].delete_many({"snapshotId": snapshot_id}).deleted_count
    n += db["snapshot_stock_rows"].delete_many({"snapshotId": snapshot_id}).deleted_count
    n += db["snapshot_sector_rows"].delete_many({"snapshotId": snapshot_id}).deleted_count
    return n


def repair_bars(
    dataset_id: str = "dragonboard_live",
    stype: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Fill missing bar slots by linear interpolation of price/volume from adjacent bars.

    Args:
        dataset_id: MongoDB 数据集 ID
        stype: 'half_hour' / 'quarter_hour'，None 表示两者都处理
        dry_run: True 只报告不写入
        force: True 先删除目标 bar 再重建（用于替换之前无插值的补齐数据）
    """
    db = get_runtime_mongodb_database()
    types = [stype] if stype else ["half_hour", "quarter_hour"]
    results: dict[str, Any] = {}

    for tp in types:
        expected = EXPECTED_SLOTS[tp]

        # 收集每个交易日已有的 slot
        dates: dict[str, set[str]] = {}
        for doc in db["snapshot_frames"].find(
            {"datasetId": dataset_id, "type": tp},
            {"tradingDate": 1, "slotTime": 1},
        ):
            d = doc["tradingDate"]
            if d not in dates:
                dates[d] = set()
            dates[d].add(doc.get("slotTime", ""))

        # 找出每个日期缺失的 slot
        repairs: list[dict[str, Any]] = []
        for date_str in sorted(dates):
            existing = sorted(dates[date_str])
            missing = [s for s in expected if s not in dates[date_str]]
            if not missing:
                continue
            for miss in missing:
                prev_slot, next_slot = _find_neighbors(miss, existing)
                repairs.append({
                    "date": date_str,
                    "target_slot": miss,
                    "prev_slot": prev_slot,
                    "next_slot": next_slot,
                    "target_sid": _snapshot_id(tp, date_str, miss),
                    "prev_sid": _snapshot_id(tp, date_str, prev_slot) if prev_slot else None,
                    "next_sid": _snapshot_id(tp, date_str, next_slot) if next_slot else None,
                })

        if dry_run:
            results[tp] = {
                "planned": len(repairs),
                "dry_run": True,
                "method": "linear_interpolation",
                "samples": repairs[:10] if repairs else [],
            }
            continue

        executed = 0
        for r in repairs:
            target_sid = r["target_sid"]
            prev_sid = r["prev_sid"]
            next_sid = r["next_sid"]

            # force 模式：先删旧的
            if force:
                _delete_bar(db, target_sid)
            elif db["snapshot_frames"].count_documents({"snapshotId": target_sid}) > 0:
                continue  # 已有数据，跳过

            # 至少需要一个相邻 bar 才能补齐
            source_sid = prev_sid or next_sid
            if not source_sid:
                continue
            source_frame = db["snapshot_frames"].find_one({"snapshotId": source_sid})
            if not source_frame:
                continue

            # 计算插值比例
            if prev_sid and next_sid:
                prev_min = _time_minutes(r["prev_slot"] or "09:30")
                next_min = _time_minutes(r["next_slot"] or "15:00")
                target_min = _time_minutes(r["target_slot"])
                denom = next_min - prev_min
                ratio = (target_min - prev_min) / denom if denom > 0 else 0.5
            else:
                ratio = 0.0  # 只有单侧数据，不插值，直接复制

            # 1. 插入 frame（复制 frame 元数据，更新时间字段）
            new_frame = dict(source_frame)
            del new_frame["_id"]
            new_frame["snapshotId"] = target_sid
            new_frame["slotTime"] = r["target_slot"]
            new_frame["displayKey"] = _display_key(tp, r["date"], r["target_slot"])
            new_frame["captureMode"] = "synthesized"
            new_frame["qualityFlags"] = list(source_frame.get("qualityFlags") or []) + ["synthesized"]
            diff_min = _time_minutes(r["target_slot"]) - _time_minutes(source_frame.get("slotTime", "09:30"))
            if isinstance(source_frame.get("timestamp"), (int, float)):
                new_frame["timestamp"] = int(source_frame["timestamp"]) + diff_min * 60 * 1000
            db["snapshot_frames"].insert_one(new_frame)

            # 2. 处理 stock_rows — 线性插值价格和成交量
            if prev_sid and next_sid and ratio > 0:
                prev_rows = {str(r.get("code") or ""): r for r in
                             db["snapshot_stock_rows"].find({"snapshotId": prev_sid})}
                next_rows = {str(r.get("code") or ""): r for r in
                             db["snapshot_stock_rows"].find({"snapshotId": next_sid})}
                all_codes = set(prev_rows) | set(next_rows)
                new_rows = []
                for code in all_codes:
                    prv = prev_rows.get(code)
                    nxt = next_rows.get(code)
                    if prv and nxt:
                        nr = dict(prv)
                        del nr["_id"]
                        nr["snapshotId"] = target_sid
                        nr["rowId"] = f"{target_sid}:{code}"
                        # 插值价格
                        try:
                            p1 = float(prv.get("price") or 0)
                            p2 = float(nxt.get("price") or 0)
                            nr["price"] = _interpolate(p1, p2, ratio)
                            if p1 > 0:
                                nr["change"] = round((nr["price"] - p1) / p1 * 100, 2)
                        except (TypeError, ValueError):
                            pass
                        # 插值成交量
                        try:
                            v1 = float(prv.get("volume") or 0)
                            v2 = float(nxt.get("volume") or 0)
                            nr["volume"] = _interpolate(v1, v2, ratio)
                        except (TypeError, ValueError):
                            pass
                        # 插值成交额
                        try:
                            t1 = float(prv.get("turnover") or 0)
                            t2 = float(nxt.get("turnover") or 0)
                            nr["turnover"] = _interpolate(t1, t2, ratio)
                        except (TypeError, ValueError):
                            pass
                    elif prv:
                        nr = dict(prv)
                        del nr["_id"]
                        nr["snapshotId"] = target_sid
                        nr["rowId"] = f"{target_sid}:{code}"
                    elif nxt:
                        nr = dict(nxt)
                        del nr["_id"]
                        nr["snapshotId"] = target_sid
                        nr["rowId"] = f"{target_sid}:{code}"
                    else:
                        continue
                    new_rows.append(nr)

                if new_rows:
                    db["snapshot_stock_rows"].insert_many(new_rows, ordered=False)
            else:
                # 单侧数据：直接复制
                source_stock_rows = list(db["snapshot_stock_rows"].find({"snapshotId": source_sid}))
                if source_stock_rows:
                    new_rows = []
                    for row in source_stock_rows:
                        nr = dict(row)
                        del nr["_id"]
                        nr["snapshotId"] = target_sid
                        code = str(nr.get("code") or "")
                        nr["rowId"] = f"{target_sid}:{code}" if code else target_sid
                        new_rows.append(nr)
                    db["snapshot_stock_rows"].insert_many(new_rows, ordered=False)

            # 3. 复制 sector_rows（板块数据不插值）
            source_sector_rows = list(db["snapshot_sector_rows"].find({"snapshotId": source_sid}))
            if source_sector_rows:
                new_rows = []
                for row in source_sector_rows:
                    nr = dict(row)
                    del nr["_id"]
                    nr["snapshotId"] = target_sid
                    key = str(nr.get("entityKey") or nr.get("entityCode") or "")
                    nr["rowId"] = f"{target_sid}:{key}" if key else target_sid
                    new_rows.append(nr)
                db["snapshot_sector_rows"].insert_many(new_rows, ordered=False)

            executed += 1

        results[tp] = {
            "planned": len(repairs),
            "executed": executed,
            "method": "linear_interpolation",
        }

    return results


if __name__ == "__main__":
    import json

    print("Dry run...")
    result = repair_bars(dry_run=True)
    total = sum(v.get("planned", 0) for v in result.values())
    print(f"Planned: {total} bars")
    if total == 0:
        print("No gaps to repair.")
    else:
        resp = input(f"\nDelete old copies and re-create with interpolation? [y/N] ")
        if resp.lower() == "y":
            result = repair_bars(force=True)
            total_exec = sum(v.get("executed", 0) for v in result.values())
            print(f"Done: {total_exec} bars repaired with interpolation.")
        else:
            print("Aborted.")
