from __future__ import annotations

from typing import Any

from pymongo import UpdateOne

from backend.operations.snapshot_field_backfill import (
    SnapshotFieldBackfillService,
    backfill_stock_row_fields,
)


# ── pure function ────────────────────────────────────────────────────────────


def test_limit_prices_derived_from_pre_close_main_board() -> None:
    fills = backfill_stock_row_fields({"code": "000001", "name": "平安银行", "preClose": 11.63})
    assert fills["limitUpPrice"] == round(11.63 * 1.1, 2)
    assert fills["limitDownPrice"] == round(11.63 * 0.9, 2)


def test_limit_prices_gem_creates_and_bj() -> None:
    assert backfill_stock_row_fields({"code": "300750", "preClose": 10})["limitUpPrice"] == 12.0
    assert backfill_stock_row_fields({"code": "688001", "preClose": 10})["limitUpPrice"] == 12.0
    assert backfill_stock_row_fields({"code": "830001", "preClose": 10})["limitUpPrice"] == 13.0


def test_limit_prices_st_overrides_board_ratio() -> None:
    fills = backfill_stock_row_fields({"code": "300750", "name": "*ST宁德", "preClose": 10})
    assert fills["limitUpPrice"] == 10.5


def test_existing_limit_price_is_not_overwritten() -> None:
    fills = backfill_stock_row_fields(
        {"code": "000001", "preClose": 11.63, "limitUpPrice": 12.78}
    )
    assert "limitUpPrice" not in fills
    assert fills["limitDownPrice"] == round(11.63 * 0.9, 2)


def test_last_trade_derived_from_price_and_volume() -> None:
    fills = backfill_stock_row_fields({"code": "000001", "price": 11.62, "volume": 1060851})
    assert fills["lastTradePrice"] == 11.62
    assert fills["lastTradeVolume"] == 1060851


def test_placeholder_zeros_are_not_evidence() -> None:
    fills = backfill_stock_row_fields({"code": "000001", "price": 0, "volume": 0})
    assert "lastTradePrice" not in fills
    assert "lastTradeVolume" not in fills


def test_amplitude_derived_from_high_low_pre_close() -> None:
    fills = backfill_stock_row_fields(
        {"code": "000001", "high": 11.66, "low": 11.52, "preClose": 11.63}
    )
    assert fills["amplitude"] == round((11.66 - 11.52) / 11.63 * 100, 4)


def test_zljzb_derived_from_zlje_turnover() -> None:
    fills = backfill_stock_row_fields({"code": "000001", "zlje": 88_000_000, "turnover": 1_000_000_000})
    assert fills["zljzb"] == round(88_000_000 / 1_000_000_000 * 100, 6)


def test_total_mv_from_total_market_value() -> None:
    fills = backfill_stock_row_fields({"code": "000001", "totalMarketValue": 225497000000})
    assert fills["totalMV"] == 225497000000


def test_no_evidence_returns_empty() -> None:
    assert backfill_stock_row_fields({"code": "000001"}) == {}
    assert backfill_stock_row_fields({}) == {}


# ── service（fake db）────────────────────────────────────────────────────────


def _match(doc: dict, query: dict) -> bool:
    for key, cond in query.items():
        if isinstance(cond, dict) and set(cond) & {"$in", "$gte", "$lte"}:
            if "$in" in cond and doc.get(key) not in cond["$in"]:
                return False
            if "$gte" in cond and (doc.get(key) or "") < cond["$gte"]:
                return False
            if "$lte" in cond and (doc.get(key) or "") > cond["$lte"]:
                return False
        elif doc.get(key) != cond:
            return False
    return True


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def limit(self, n: int) -> "_FakeCursor":
        return _FakeCursor(self._docs[:n])

    def __iter__(self):
        return iter(self._docs)


class _FakeColl:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def find(self, query: dict, projection: dict | None = None) -> _FakeCursor:
        return _FakeCursor([dict(d) for d in self._docs if _match(d, query)])

    def bulk_write(self, ops: list[Any], ordered: bool = False) -> Any:
        modified = 0
        for op in ops:
            for doc in self._docs:
                if _match(doc, op._filter):
                    doc.update(op._doc["$set"])
                    modified += 1
                    break
        return type("Bulk", (), {"modified_count": modified})()

    def insert_many(self, docs: list[dict], ordered: bool = False) -> Any:
        self._docs.extend(dict(d) for d in docs)
        return type("Ins", (), {"inserted_ids": [None] * len(docs)})()

    def insert_one(self, doc: dict) -> Any:
        self._docs.append(dict(doc))
        return type("Ins", (), {"inserted_id": None})()


class _FakeDb:
    def __init__(self) -> None:
        self._colls: dict[str, _FakeColl] = {}

    def __getitem__(self, name: str) -> _FakeColl:
        if name not in self._colls:
            self._colls[name] = _FakeColl([])
        return self._colls[name]


def _seed_row(snapshot_id: str, code: str, **extra: Any) -> dict:
    row: dict[str, Any] = {
        "_id": f"{snapshot_id}:{code}",
        "datasetId": "test_backfill",
        "snapshotId": snapshot_id,
        "tradingDate": "2026-07-31",
        "type": "half_hour",
        "code": code,
        "name": "平安银行",
        "price": 11.62,
        "volume": 1060851,
        "preClose": 11.63,
        "high": 11.66,
        "low": 11.52,
        "turnover": 1_000_000_000,
        "zlje": 88_000_000,
    }
    row.update(extra)
    return row


def test_service_dry_run_counts_without_writing() -> None:
    db = _FakeDb()
    db["snapshot_stock_rows"]._docs = [
        _seed_row("half_hour:2026-07-31:15:00", "000001"),
        _seed_row("half_hour:2026-07-31:15:00", "600000", limitUpPrice=12.78),
    ]
    result = SnapshotFieldBackfillService(db).backfill(
        dataset_id="test_backfill", dry_run=True
    )
    assert result["dryRun"] is True
    assert result["scannedRows"] == 2
    assert result["eligibleRows"] == 2
    assert result["updatedRows"] == 0
    assert result["perField"]["limitUpPrice"] == 1
    assert result["perField"]["lastTradePrice"] == 2
    # 未写库
    assert "backfillMeta" not in db["snapshot_stock_rows"]._docs[0]


def test_service_apply_backs_up_updates_and_audits() -> None:
    db = _FakeDb()
    db["snapshot_stock_rows"]._docs = [
        _seed_row("half_hour:2026-07-31:15:00", "000001"),
    ]
    result = SnapshotFieldBackfillService(db).backfill(
        dataset_id="test_backfill", dry_run=False, backup=True
    )
    assert result["updatedRows"] == 1
    assert result["backupCollection"] is not None
    assert len(db[result["backupCollection"]]._docs) == 1
    row = db["snapshot_stock_rows"]._docs[0]
    assert row["limitUpPrice"] == round(11.63 * 1.1, 2)
    assert row["backfillMeta"]["version"] == "snapshot_derived_fields_v1"
    audits = db["migration_audit"]._docs
    assert len(audits) == 1
    assert audits[0]["opType"] == "snapshot_stock_field_backfill"
    assert audits[0]["updatedRows"] == 1
