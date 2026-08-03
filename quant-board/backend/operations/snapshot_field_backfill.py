"""按证据回填 `snapshot_stock_rows` 的派生字段。

只填充缺失字段，且只使用该行自身已有的证据（preClose/high/low/price/volume/
turnover/zlje/totalMarketValue）。`pe/pb/cirMV/volumeRatio` 等没有历史时点证据
的字段保持缺失，不伪造。

派生规则与 `snapshot_collector/builder.py` 保持一致；应用前默认备份受影响行到
独立集合，并写 `migration_audit` 审计记录。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pymongo import UpdateOne


BACKFILL_VERSION = "snapshot_derived_fields_v1"


def _limit_ratio_for(code: Any, name: Any = "") -> float:
    """A股涨跌停幅度：ST 5%、创业板/科创板 20%、北交所 30%、其余主板 10%。"""
    upper = str(name or "").upper()
    if "ST" in upper:
        return 0.05
    if str(code).startswith(("300", "301", "688", "689")):
        return 0.20
    if str(code).startswith(("4", "8", "9")):
        return 0.30
    return 0.10


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _missing(value: Any) -> bool:
    if value is None or value == "" or value == []:
        return True
    if isinstance(value, float):
        return not math.isfinite(value)
    return False


def backfill_stock_row_fields(row: dict[str, Any]) -> dict[str, Any]:
    """按行内证据计算缺失字段的派生值；返回 {字段: 值}，不修改入参。

    占位零值（price=0 等）不视为证据，避免把缺失伪造成 0。
    """
    fills: dict[str, Any] = {}
    code = str(row.get("code") or "")
    name = row.get("name")

    pre_close = _finite(row.get("preClose"))
    if pre_close is not None and pre_close > 0:
        ratio = _limit_ratio_for(code, name)
        if _missing(row.get("limitUpPrice")):
            fills["limitUpPrice"] = round(pre_close * (1 + ratio), 2)
        if _missing(row.get("limitDownPrice")):
            fills["limitDownPrice"] = round(pre_close * (1 - ratio), 2)

    price = _finite(row.get("price"))
    if _missing(row.get("lastTradePrice")) and price is not None and price > 0:
        fills["lastTradePrice"] = price

    volume = _finite(row.get("volume"))
    if _missing(row.get("lastTradeVolume")) and volume is not None and volume > 0:
        fills["lastTradeVolume"] = volume

    if _missing(row.get("amplitude")):
        high = _finite(row.get("high"))
        low = _finite(row.get("low"))
        pre_close = _finite(row.get("preClose"))
        if (
            high is not None
            and low is not None
            and pre_close is not None
            and high >= low
            and high > 0
            and pre_close > 0
        ):
            fills["amplitude"] = round((high - low) / pre_close * 100, 4)

    if _missing(row.get("zljzb")):
        zlje = _finite(row.get("zlje"))
        turnover = _finite(row.get("turnover"))
        if zlje is not None and zlje > 0 and turnover is not None and turnover > 0:
            derived = round(zlje / turnover * 100, 6)
            # 主力净流入是成交额子集，占比应落在 (0, 100]；超出说明 turnover 单位
            # 不是元（如历史换手率），不视为证据，保持缺失。
            if 0 < derived <= 100:
                fills["zljzb"] = derived

    if _missing(row.get("totalMV")):
        tmv = _finite(row.get("totalMarketValue"))
        if tmv is not None and tmv > 0:
            fills["totalMV"] = tmv

    return fills


class SnapshotFieldBackfillService:
    VERSION = BACKFILL_VERSION

    def __init__(self, mongo_db: Any) -> None:
        self._db = mongo_db

    def backfill(
        self,
        *,
        dataset_id: str = "dragonboard_live",
        start_date: str | None = None,
        end_date: str | None = None,
        snapshot_types: list[str] | None = None,
        dry_run: bool = True,
        backup: bool = True,
        limit: int = 0,
    ) -> dict[str, Any]:
        coll = self._db["snapshot_stock_rows"]
        query: dict[str, Any] = {"datasetId": dataset_id}
        if start_date or end_date:
            date_query: dict[str, str] = {}
            if start_date:
                date_query["$gte"] = start_date
            if end_date:
                date_query["$lte"] = end_date
            query["tradingDate"] = date_query
        if snapshot_types:
            query["type"] = {"$in": snapshot_types}

        projection = {
            "_id": 1,
            "snapshotId": 1,
            "tradingDate": 1,
            "type": 1,
            "code": 1,
            "name": 1,
            "price": 1,
            "volume": 1,
            "preClose": 1,
            "high": 1,
            "low": 1,
            "turnover": 1,
            "zlje": 1,
            "zljzb": 1,
            "totalMarketValue": 1,
            "totalMV": 1,
            "limitUpPrice": 1,
            "limitDownPrice": 1,
            "lastTradePrice": 1,
            "lastTradeVolume": 1,
            "amplitude": 1,
        }
        cursor = coll.find(query, projection)
        if limit and limit > 0:
            cursor = cursor.limit(limit)

        per_field: dict[str, int] = {}
        changed: list[dict[str, Any]] = []
        scanned = 0
        for doc in cursor:
            scanned += 1
            fills = backfill_stock_row_fields(doc)
            if not fills:
                continue
            changed.append({"_id": doc["_id"], "fills": fills})
            for field in fills:
                per_field[field] = per_field.get(field, 0) + 1

        result: dict[str, Any] = {
            "ok": True,
            "dryRun": dry_run,
            "datasetId": dataset_id,
            "version": self.VERSION,
            "scannedRows": scanned,
            "eligibleRows": len(changed),
            "perField": per_field,
            "updatedRows": 0,
            "backupCollection": None,
            "auditId": None,
        }
        if dry_run or not changed:
            return result

        repaired_at = datetime.now(timezone.utc).isoformat()
        backup_name: str | None = None
        if backup:
            backup_name = (
                "snapshot_stock_rows_field_backfill_backup_"
                f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"
            )
            ids = [item["_id"] for item in changed]
            backup_docs = list(coll.find({"_id": {"$in": ids}}))
            if backup_docs:
                self._db[backup_name].insert_many(backup_docs, ordered=False)

        updated = 0
        for start in range(0, len(changed), 1000):
            batch = changed[start : start + 1000]
            ops = [
                UpdateOne(
                    {"_id": item["_id"]},
                    {
                        "$set": {
                            **item["fills"],
                            "backfillMeta": {
                                "version": self.VERSION,
                                "repairedAt": repaired_at,
                                "fields": sorted(item["fills"].keys()),
                            },
                        }
                    },
                )
                for item in batch
            ]
            bulk = coll.bulk_write(ops, ordered=False)
            updated += int(bulk.modified_count)

        audit_id = f"snapshot-field-backfill-{uuid4().hex}"
        self._db["migration_audit"].insert_one(
            {
                "auditId": audit_id,
                "opType": "snapshot_stock_field_backfill",
                "datasetId": dataset_id,
                "version": self.VERSION,
                "createdAt": repaired_at,
                "scannedRows": scanned,
                "updatedRows": updated,
                "perField": per_field,
                "backupCollection": backup_name,
                "startDate": start_date,
                "endDate": end_date,
                "snapshotTypes": snapshot_types,
            }
        )
        result.update(
            {
                "updatedRows": updated,
                "backupCollection": backup_name,
                "auditId": audit_id,
            }
        )
        return result
