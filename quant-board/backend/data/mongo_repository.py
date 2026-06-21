from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from backend.data.models import Dataset
from backend.utils import json_dumps, json_loads


class MongoRepository:
    def __init__(self, database: Any) -> None:
        self.db = database

    def list_datasets(self) -> list[Dataset]:
        rows = list(self.db["datasets"].find({}).sort([("createdAt", -1)]))
        return [self._dataset_from_doc(row) for row in rows]

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        row = self.db["datasets"].find_one({"id": dataset_id})
        return self._dataset_from_doc(row) if row else None

    def existing_snapshot_ids(self, dataset_id: str, snapshot_ids: list[str]) -> set[str]:
        if not snapshot_ids:
            return set()
        rows = self.db["snapshot_frames"].find({"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}})
        return {str(row.get("snapshotId")) for row in rows if row.get("snapshotId")}

    def save_dataset_bundle(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
    ) -> Dataset:
        self._delete_dataset_children(dataset.id)
        self.db["datasets"].replace_one({"id": dataset.id}, self._dataset_to_doc(dataset), upsert=True)
        self._insert_many("snapshot_records", [self._record_doc(dataset.id, item) for item in records])
        self._insert_many("snapshot_frames", [self._frame_doc(dataset.id, item) for item in frames])
        self._insert_many("snapshot_stock_rows", [self._stock_doc(dataset.id, item) for item in stock_rows])
        self._insert_many("snapshot_sector_rows", [self._sector_doc(dataset.id, item) for item in sector_rows])
        self._refresh_dataset_summary(dataset.id)
        return self.get_dataset(dataset.id) or dataset

    def delete_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            return None
        if dataset.id == "dragonboard_live" or dataset.source_type == "dragon_board_runtime":
            raise ValueError(f"snapshot primary dataset cannot be deleted from UI/API: {dataset_id}")
        deleted = {
            name: int(self.db[name].delete_many(query).deleted_count)
            for name, query in {
                "snapshot_sector_rows": {"datasetId": dataset_id},
                "snapshot_stock_rows": {"datasetId": dataset_id},
                "snapshot_frames": {"datasetId": dataset_id},
                "snapshot_records": {"datasetId": dataset_id},
                "datasets": {"id": dataset_id},
            }.items()
        }
        return {"ok": True, "datasetId": dataset_id, "deleted": deleted, "source": "mongodb"}

    def close(self) -> None:
        return None

    def save_snapshot_ingest(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
        *,
        idempotency_key: str,
        trading_date: str | None = None,
        source: str = "dragon_board_runtime",
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        existing = self.db["migration_audit"].find_one({"idempotencyKey": idempotency_key, "opType": "snapshot_ingest"})
        if existing and not replace_existing:
            saved_dataset = self.get_dataset(dataset.id) or dataset
            return {
                "dataset": self.dataset_to_dict(saved_dataset),
                "status": "done",
                "outbox": None,
                "deduped": True,
            }

        snapshot_ids = sorted(
            {
                str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or "")
                for item in [*records, *frames, *stock_rows, *sector_rows]
                if isinstance(item, dict)
                and (item.get("snapshotId") or item.get("snapshot_id") or item.get("id"))
            }
        )
        existing_snapshot_ids = self.existing_snapshot_ids(dataset.id, snapshot_ids)
        if (
            existing_snapshot_ids
            and len(existing_snapshot_ids) == len(snapshot_ids)
            and not replace_existing
        ):
            saved_dataset = self.get_dataset(dataset.id) or dataset
            return {
                "dataset": self.dataset_to_dict(saved_dataset),
                "status": "deduped",
                "outbox": None,
                "deduped": True,
            }
        if existing_snapshot_ids and not replace_existing:
            missing_snapshot_ids = set(snapshot_ids) - existing_snapshot_ids
            records = self._filter_snapshot_payloads(records, missing_snapshot_ids)
            frames = self._filter_snapshot_payloads(frames, missing_snapshot_ids)
            stock_rows = self._filter_snapshot_payloads(stock_rows, missing_snapshot_ids)
            sector_rows = self._filter_snapshot_payloads(sector_rows, missing_snapshot_ids)
            snapshot_ids = sorted(missing_snapshot_ids)

        rollback = self._capture_snapshot_replacement(dataset.id, snapshot_ids) if replace_existing else None
        try:
            self._delete_snapshot_children(dataset.id, snapshot_ids)
            self.db["datasets"].replace_one({"id": dataset.id}, self._dataset_to_doc(dataset), upsert=True)
            self._insert_many("snapshot_records", [self._record_doc(dataset.id, item) for item in records])
            self._insert_many("snapshot_frames", [self._frame_doc(dataset.id, item) for item in frames])
            self._insert_many("snapshot_stock_rows", [self._stock_doc(dataset.id, item) for item in stock_rows])
            self._insert_many("snapshot_sector_rows", [self._sector_doc(dataset.id, item) for item in sector_rows])
            self._refresh_dataset_summary(dataset.id)
            self.db["migration_audit"].insert_many(
                [
                    {
                        "opType": "snapshot_ingest",
                        "idempotencyKey": idempotency_key,
                        "datasetId": dataset.id,
                        "snapshotIds": snapshot_ids,
                        "tradingDate": trading_date,
                        "source": source,
                        "status": "done",
                        "createdAt": datetime.utcnow(),
                    }
                ],
                ordered=False,
            )
        except Exception:
            if rollback is not None:
                self._restore_snapshot_replacement(dataset.id, snapshot_ids, rollback)
            raise
        saved_dataset = self.get_dataset(dataset.id) or dataset
        return {
            "dataset": self.dataset_to_dict(saved_dataset),
            "status": "done",
            "outbox": None,
            "deduped": False,
        }

    def load_frame_bundles(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "asc",
        projection: str = "full",
    ) -> list[dict[str, Any]]:
        frame_rows = self._find_frames(
            dataset_id,
            snapshot_type,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            allowed_capture_modes=allowed_capture_modes,
            exclude_restored=exclude_restored,
            limit=limit,
            sort=sort,
        )
        snapshot_ids = [str(row.get("snapshotId")) for row in frame_rows if row.get("snapshotId")]
        stock_rows_by_snapshot = self._stock_rows_by_snapshot(dataset_id, snapshot_ids, projection=projection)
        sector_rows_by_snapshot = {} if projection == "ranktrend" else self._sector_rows_by_snapshot(dataset_id, snapshot_ids)
        bundles: list[dict[str, Any]] = []
        for row in frame_rows:
            item = self.local_frame_to_bundle_dict(row)
            item["rows"] = stock_rows_by_snapshot.get(str(row.get("snapshotId")), [])
            item["hotlist"] = item["rows"]
            item["stocks"] = item["rows"]
            if projection == "ranktrend":
                item["entities"] = []
                item["sectors"] = []
                item["hotThemes"] = []
                bundles.append(item)
                continue
            item["entities"] = sector_rows_by_snapshot.get(str(row.get("snapshotId")), [])
            item["sectors"] = [
                self._sector_entity_to_view(sector)
                for sector in item["entities"]
                if sector.get("entityType") == "sector"
            ]
            item["hotThemes"] = [
                self._sector_entity_to_view(sector)
                for sector in item["entities"]
                if sector.get("entityType") == "hot_theme"
            ]
            bundles.append(item)
        return bundles

    def load_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
    ) -> list[dict[str, Any]]:
        frame_rows = self._find_frames(
            dataset_id,
            snapshot_type,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=None,
            allowed_capture_modes=None,
            exclude_restored=False,
            limit=None,
            sort="asc",
        )
        snapshot_ids = [str(row.get("snapshotId")) for row in frame_rows if row.get("snapshotId")]
        stock_rows_by_snapshot = self._stock_rows_by_snapshot(dataset_id, snapshot_ids, projection="full")
        frames: list[dict[str, Any]] = []
        for row in frame_rows:
            item = self.frame_to_dict(row)
            item["stocks"] = stock_rows_by_snapshot.get(str(row.get("snapshotId")), [])
            frames.append(item)
        return frames

    def load_rank_series(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        codes: list[str] | None = None,
        limit: int | None = 50,
        sort: str = "asc",
    ) -> list[dict[str, Any]]:
        frame_rows = self._find_frames(
            dataset_id,
            snapshot_type,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            allowed_capture_modes=allowed_capture_modes,
            exclude_restored=exclude_restored,
            limit=limit,
            sort=sort,
        )
        snapshot_ids = [str(row.get("snapshotId")) for row in frame_rows if row.get("snapshotId")]
        query: dict[str, Any] = {"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}
        if codes:
            query["code"] = {"$in": codes}
        ranks_by_snapshot: dict[str, dict[str, int]] = defaultdict(dict)
        for row in self.db["snapshot_stock_rows"].find(query).sort([("timestamp", 1), ("rank", 1)]):
            code = str(row.get("code") or "")
            rank = row.get("rank")
            if code and rank:
                ranks_by_snapshot[str(row.get("snapshotId"))][code] = int(rank)
        return [
            {
                "snapshotId": row.get("snapshotId"),
                "displayKey": row.get("displayKey"),
                "timestamp": row.get("timestamp"),
                "type": row.get("type"),
                "tradingDate": row.get("tradingDate"),
                "slotTime": row.get("slotTime"),
                "captureMode": row.get("captureMode"),
                "totalCount": int(row.get("stockRowCount") or len(ranks_by_snapshot.get(str(row.get("snapshotId")), {}))),
                "ranks": ranks_by_snapshot.get(str(row.get("snapshotId")), {}),
            }
            for row in frame_rows
        ]

    def list_snapshot_stock_rows(
        self,
        dataset_id: str,
        snapshot_id: str | None = None,
        snapshot_type: str | None = None,
        snapshot_types: list[str] | None = None,
        trading_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        code: str | None = None,
        codes: list[str] | None = None,
        slot_time: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "desc",
    ) -> dict[str, Any]:
        query = self._snapshot_row_query(
            dataset_id,
            snapshot_id=snapshot_id,
            snapshot_type=snapshot_type,
            snapshot_types=snapshot_types,
            trading_date=trading_date,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            slot_time=slot_time,
            allowed_capture_modes=allowed_capture_modes,
            exclude_restored=exclude_restored,
        )
        stock_codes = self._merge_values(code, codes)
        if stock_codes:
            query["code"] = {"$in": stock_codes}
        direction = 1 if sort == "asc" else -1
        cursor = self.db["snapshot_stock_rows"].find(query).sort([("timestamp", direction), ("rank", 1)])
        if limit and limit > 0:
            cursor = cursor.limit(limit)
        return {"rows": [self.local_stock_to_bundle_dict(row) for row in cursor], "source": "mongodb"}

    def list_snapshot_records(
        self,
        dataset_id: str,
        snapshot_type: str | None = None,
        snapshot_types: list[str] | None = None,
        trading_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "desc",
    ) -> list[dict[str, Any]]:
        query = self._snapshot_row_query(
            dataset_id,
            snapshot_id=None,
            snapshot_type=snapshot_type,
            snapshot_types=snapshot_types,
            trading_date=trading_date,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            slot_time=None,
            allowed_capture_modes=allowed_capture_modes,
            exclude_restored=exclude_restored,
        )
        direction = 1 if sort == "asc" else -1
        cursor = self.db["snapshot_records"].find(query).sort([("timestamp", direction)])
        if limit and limit > 0:
            cursor = cursor.limit(limit)
        return [self.record_to_dict(row) for row in cursor]

    def get_snapshot_record(
        self,
        snapshot_id: str,
        dataset_id: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
    ) -> dict[str, Any] | None:
        query: dict[str, Any] = {"snapshotId": snapshot_id}
        if dataset_id:
            query["datasetId"] = dataset_id
        self._apply_capture_mode_filters(
            query,
            allowed_capture_modes=allowed_capture_modes,
            exclude_restored=exclude_restored,
        )
        row = self.db["snapshot_records"].find_one(query)
        return self.record_to_dict(row) if row else None

    def get_snapshot_frame(
        self,
        snapshot_id: str,
        dataset_id: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
    ) -> dict[str, Any] | None:
        query: dict[str, Any] = {"snapshotId": snapshot_id}
        if dataset_id:
            query["datasetId"] = dataset_id
        self._apply_capture_mode_filters(
            query,
            allowed_capture_modes=allowed_capture_modes,
            exclude_restored=exclude_restored,
        )
        row = self.db["snapshot_frames"].find_one(query)
        return self.frame_to_dict(row) if row else None

    def list_snapshot_sector_rows(
        self,
        dataset_id: str,
        snapshot_id: str | None = None,
        snapshot_type: str | None = None,
        snapshot_types: list[str] | None = None,
        trading_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        entity_type: str | None = None,
        entity_types: list[str] | None = None,
        entity_key: str | None = None,
        entity_keys: list[str] | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "desc",
    ) -> dict[str, Any]:
        query = self._snapshot_row_query(
            dataset_id,
            snapshot_id=snapshot_id,
            snapshot_type=snapshot_type,
            snapshot_types=snapshot_types,
            trading_date=trading_date,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            slot_time=None,
            allowed_capture_modes=allowed_capture_modes,
            exclude_restored=exclude_restored,
        )
        row_entity_types = self._merge_values(entity_type, entity_types)
        row_entity_keys = self._merge_values(entity_key, entity_keys)
        if row_entity_types:
            query["entityType"] = {"$in": row_entity_types}
        if row_entity_keys:
            query["entityKey"] = {"$in": row_entity_keys}
        direction = 1 if sort == "asc" else -1
        cursor = self.db["snapshot_sector_rows"].find(query).sort([("timestamp", direction), ("rank", 1)])
        if limit and limit > 0:
            cursor = cursor.limit(limit)
        return {"rows": [self.local_sector_to_bundle_dict(row) for row in cursor], "source": "mongodb"}

    def snapshot_table_counts(self, dataset_id: str | None = None) -> dict[str, int]:
        query = {"datasetId": dataset_id} if dataset_id else {}
        return {
            "snapshots": int(self.db["snapshot_records"].count_documents(query)),
            "snapshot_frames": int(self.db["snapshot_frames"].count_documents(query)),
            "snapshot_stock_rows": int(self.db["snapshot_stock_rows"].count_documents(query)),
            "snapshot_sector_rows": int(self.db["snapshot_sector_rows"].count_documents(query)),
        }

    def load_dataset_bundle_slice(
        self,
        dataset_id: str,
        *,
        snapshot_types: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        max_snapshots: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        frame_query: dict[str, Any] = {"datasetId": dataset_id}
        if snapshot_types:
            frame_query["type"] = {"$in": snapshot_types}
        self._apply_date_filters(frame_query, start_date, end_date, None)
        cursor = self.db["snapshot_frames"].find(frame_query).sort([("timestamp", 1), ("snapshotId", 1)])
        if max_snapshots and max_snapshots > 0:
            cursor = cursor.limit(max_snapshots)
        frame_rows = list(cursor)
        snapshot_ids = [str(row.get("snapshotId")) for row in frame_rows if row.get("snapshotId")]
        if not snapshot_ids:
            return [], [], [], []
        records = [
            self.record_to_dict(row)
            for row in self.db["snapshot_records"].find({"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}).sort([("timestamp", 1), ("snapshotId", 1)])
        ]
        frames = [self.local_frame_to_bundle_dict(row) for row in frame_rows]
        stock_rows = [
            self.local_stock_to_bundle_dict(row)
            for row in self.db["snapshot_stock_rows"].find({"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}).sort([("timestamp", 1), ("rank", 1), ("code", 1)])
        ]
        sector_rows = [
            self.local_sector_to_bundle_dict(row)
            for row in self.db["snapshot_sector_rows"].find({"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}).sort([("timestamp", 1), ("rank", 1), ("entityType", 1), ("entityKey", 1)])
        ]
        return records, frames, stock_rows, sector_rows

    @staticmethod
    def dataset_to_dict(model: Dataset) -> dict[str, Any]:
        return {
            "id": model.id,
            "name": model.name,
            "source_type": model.source_type,
            "source_path": model.source_path,
            "db_name": model.db_name,
            "schema_fingerprint": model.schema_fingerprint,
            "snapshot_count": model.snapshot_count,
            "frame_count": model.frame_count,
            "stock_row_count": model.stock_row_count,
            "sector_row_count": model.sector_row_count,
            "start_date": model.start_date,
            "end_date": model.end_date,
            "snapshot_types": json_loads(model.snapshot_types_json, []),
            "metadata": json_loads(model.metadata_json, {}),
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }

    @staticmethod
    def local_frame_to_bundle_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("snapshotId"),
            "snapshotId": row.get("snapshotId"),
            "timestamp": row.get("timestamp"),
            "tradingDate": row.get("tradingDate"),
            "slotTime": row.get("slotTime"),
            "type": row.get("type"),
            "displayKey": row.get("displayKey") or row.get("snapshotId"),
            "captureMode": row.get("captureMode"),
            "source": row.get("source"),
            "qualityFlags": row.get("qualityFlags") or [],
            "delayMs": row.get("delayMs") or 0,
            "marketStats": row.get("marketStats") or {},
            "sentiment": row.get("sentiment") or {},
            "moneyFlow": row.get("moneyFlow") or {},
            "indices": row.get("indices") or {},
            "limitSummary": row.get("limitSummary") or {},
            "rotationSummary": row.get("rotationSummary") or {},
            "stockRowCount": row.get("stockRowCount") or 0,
            "sectorRowCount": row.get("sectorRowCount") or 0,
        }

    @staticmethod
    def frame_to_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshotId": row.get("snapshotId"),
            "timestamp": row.get("timestamp"),
            "tradingDate": row.get("tradingDate"),
            "slotTime": row.get("slotTime"),
            "type": row.get("type"),
            "captureMode": row.get("captureMode"),
            "source": row.get("source"),
            "marketContext": {
                "metadata": row.get("metadata") or {},
                "marketStats": row.get("marketStats") or {},
                "sentiment": row.get("sentiment") or {},
                "moneyFlow": row.get("moneyFlow") or {},
                "indices": row.get("indices") or {},
                "limitSummary": row.get("limitSummary") or {},
                "rotationSummary": row.get("rotationSummary") or {},
            },
            "stocks": [],
        }

    @staticmethod
    def record_to_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("snapshotId"),
            "snapshotId": row.get("snapshotId"),
            "type": row.get("type"),
            "tradingDate": row.get("tradingDate"),
            "slotTime": row.get("slotTime"),
            "timestamp": row.get("timestamp"),
            "displayKey": row.get("displayKey"),
            "captureMode": row.get("captureMode"),
            "capturedAt": row.get("capturedAt") or row.get("timestamp"),
            "dataTimestamp": row.get("dataTimestamp") or row.get("timestamp"),
            "delayMs": row.get("delayMs") or 0,
            "qualityFlags": row.get("qualityFlags") or [],
            "source": row.get("source"),
            "payload": {},
        }

    @staticmethod
    def local_stock_to_bundle_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key != "_id" and value is not None}

    @staticmethod
    def local_sector_to_bundle_dict(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key != "_id" and value is not None}

    def _find_frames(
        self,
        dataset_id: str,
        snapshot_type: str,
        *,
        start_date: str | None,
        end_date: str | None,
        before_trading_date: str | None,
        allowed_capture_modes: list[str] | None,
        exclude_restored: bool,
        limit: int | None,
        sort: str,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"datasetId": dataset_id, "type": snapshot_type}
        self._apply_date_filters(query, start_date, end_date, before_trading_date)
        self._apply_capture_mode_filters(
            query,
            allowed_capture_modes=allowed_capture_modes,
            exclude_restored=exclude_restored,
        )
        direction = 1 if sort == "asc" else -1
        cursor = self.db["snapshot_frames"].find(query).sort([("timestamp", direction)])
        if limit and limit > 0:
            cursor = cursor.limit(limit)
        return list(cursor)

    def _stock_rows_by_snapshot(
        self,
        dataset_id: str,
        snapshot_ids: list[str],
        *,
        projection: str,
    ) -> dict[str, list[dict[str, Any]]]:
        rows_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if not snapshot_ids:
            return rows_by_snapshot
        for row in self.db["snapshot_stock_rows"].find({"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}).sort([("timestamp", 1), ("rank", 1)]):
            if projection == "ranktrend":
                item = {"code": row.get("code"), "name": row.get("name"), "rank": row.get("rank")}
            else:
                item = self.local_stock_to_bundle_dict(row)
            rows_by_snapshot[str(row.get("snapshotId"))].append(item)
        return rows_by_snapshot

    def _sector_rows_by_snapshot(self, dataset_id: str, snapshot_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        rows_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if not snapshot_ids:
            return rows_by_snapshot
        for row in self.db["snapshot_sector_rows"].find({"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}).sort([("timestamp", 1), ("rank", 1)]):
            rows_by_snapshot[str(row.get("snapshotId"))].append(self.local_sector_to_bundle_dict(row))
        return rows_by_snapshot

    @staticmethod
    def _snapshot_row_query(
        dataset_id: str,
        *,
        snapshot_id: str | None,
        snapshot_type: str | None,
        snapshot_types: list[str] | None,
        trading_date: str | None,
        start_date: str | None,
        end_date: str | None,
        before_trading_date: str | None,
        slot_time: str | None,
        allowed_capture_modes: list[str] | None,
        exclude_restored: bool,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"datasetId": dataset_id}
        if snapshot_id:
            query["snapshotId"] = snapshot_id
        types = MongoRepository._merge_values(snapshot_type, snapshot_types)
        if types:
            query["type"] = {"$in": types}
        if trading_date:
            query["tradingDate"] = trading_date
        else:
            MongoRepository._apply_date_filters(query, start_date, end_date, before_trading_date)
        if slot_time:
            query["slotTime"] = slot_time
        MongoRepository._apply_capture_mode_filters(
            query,
            allowed_capture_modes=allowed_capture_modes,
            exclude_restored=exclude_restored,
        )
        return query

    @staticmethod
    def _apply_capture_mode_filters(
        query: dict[str, Any],
        *,
        allowed_capture_modes: list[str] | None,
        exclude_restored: bool,
    ) -> None:
        if allowed_capture_modes:
            capture_filter: dict[str, Any] = {"$in": allowed_capture_modes}
            if exclude_restored:
                capture_filter["$ne"] = "restored"
            query["captureMode"] = capture_filter
            return
        if exclude_restored:
            query["captureMode"] = {"$ne": "restored"}

    @staticmethod
    def _apply_date_filters(
        query: dict[str, Any],
        start_date: str | None,
        end_date: str | None,
        before_trading_date: str | None,
    ) -> None:
        trading_date_filter: dict[str, Any] = {}
        if start_date:
            trading_date_filter["$gte"] = start_date
        if end_date:
            trading_date_filter["$lte"] = end_date
        if before_trading_date:
            trading_date_filter["$lt"] = before_trading_date
        if trading_date_filter:
            query["tradingDate"] = trading_date_filter

    def _delete_snapshot_children(self, dataset_id: str, snapshot_ids: list[str]) -> None:
        if not snapshot_ids:
            return
        query = {"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}
        for name in ["snapshot_sector_rows", "snapshot_stock_rows", "snapshot_frames", "snapshot_records"]:
            self.db[name].delete_many(query)

    def _capture_snapshot_replacement(
        self,
        dataset_id: str,
        snapshot_ids: list[str],
    ) -> dict[str, Any]:
        query = {"datasetId": dataset_id, "snapshotId": {"$in": snapshot_ids}}
        return {
            "dataset": self.db["datasets"].find_one({"id": dataset_id}),
            "children": {
                name: list(self.db[name].find(query))
                for name in [
                    "snapshot_records",
                    "snapshot_frames",
                    "snapshot_stock_rows",
                    "snapshot_sector_rows",
                ]
            },
        }

    def _restore_snapshot_replacement(
        self,
        dataset_id: str,
        snapshot_ids: list[str],
        rollback: dict[str, Any],
    ) -> None:
        self._delete_snapshot_children(dataset_id, snapshot_ids)
        for name, rows in rollback["children"].items():
            self._insert_many(name, rows)
        dataset_doc = rollback.get("dataset")
        if dataset_doc is None:
            self.db["datasets"].delete_many({"id": dataset_id})
        else:
            self.db["datasets"].replace_one({"id": dataset_id}, dataset_doc, upsert=True)

    def _delete_dataset_children(self, dataset_id: str) -> None:
        query = {"datasetId": dataset_id}
        for name in ["snapshot_sector_rows", "snapshot_stock_rows", "snapshot_frames", "snapshot_records"]:
            self.db[name].delete_many(query)

    def _refresh_dataset_summary(self, dataset_id: str) -> None:
        dataset = self.get_dataset(dataset_id)
        if not dataset:
            return
        frame_rows = list(self.db["snapshot_frames"].find({"datasetId": dataset_id}))
        trading_dates = sorted({str(row.get("tradingDate")) for row in frame_rows if row.get("tradingDate")})
        snapshot_types = sorted({str(row.get("type")) for row in frame_rows if row.get("type")})
        dataset.snapshot_count = int(self.db["snapshot_records"].count_documents({"datasetId": dataset_id}))
        dataset.frame_count = len(frame_rows)
        dataset.stock_row_count = int(self.db["snapshot_stock_rows"].count_documents({"datasetId": dataset_id}))
        dataset.sector_row_count = int(self.db["snapshot_sector_rows"].count_documents({"datasetId": dataset_id}))
        dataset.start_date = trading_dates[0] if trading_dates else None
        dataset.end_date = trading_dates[-1] if trading_dates else None
        dataset.snapshot_types_json = json_dumps(snapshot_types)
        self.db["datasets"].replace_one({"id": dataset.id}, self._dataset_to_doc(dataset), upsert=True)

    def _insert_many(self, collection: str, rows: list[dict[str, Any]]) -> None:
        if rows:
            self.db[collection].insert_many(rows, ordered=False)

    @staticmethod
    def _dataset_to_doc(dataset: Dataset) -> dict[str, Any]:
        return {
            "id": dataset.id,
            "name": dataset.name,
            "sourceType": dataset.source_type,
            "sourcePath": dataset.source_path,
            "dbName": dataset.db_name,
            "schemaFingerprint": dataset.schema_fingerprint,
            "snapshotCount": dataset.snapshot_count,
            "frameCount": dataset.frame_count,
            "stockRowCount": dataset.stock_row_count,
            "sectorRowCount": dataset.sector_row_count,
            "startDate": dataset.start_date,
            "endDate": dataset.end_date,
            "snapshotTypes": json_loads(dataset.snapshot_types_json, []),
            "metadata": json_loads(dataset.metadata_json, {}),
            "createdAt": dataset.created_at,
        }

    @staticmethod
    def _dataset_from_doc(row: dict[str, Any]) -> Dataset:
        created_at = row.get("createdAt")
        if not isinstance(created_at, datetime):
            created_at = datetime.utcnow()
        return Dataset(
            id=str(row.get("id") or ""),
            name=str(row.get("name") or ""),
            source_type=str(row.get("sourceType") or ""),
            source_path=str(row.get("sourcePath") or ""),
            db_name=str(row.get("dbName") or "DragonBoardData"),
            schema_fingerprint=str(row.get("schemaFingerprint") or ""),
            snapshot_count=int(row.get("snapshotCount") or 0),
            frame_count=int(row.get("frameCount") or 0),
            stock_row_count=int(row.get("stockRowCount") or 0),
            sector_row_count=int(row.get("sectorRowCount") or 0),
            start_date=row.get("startDate"),
            end_date=row.get("endDate"),
            snapshot_types_json=json_dumps(row.get("snapshotTypes") or []),
            metadata_json=json_dumps(row.get("metadata") or {}),
            created_at=created_at,
        )

    @staticmethod
    def _record_doc(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
        timestamp = int(item.get("timestamp") or 0)
        return {
            "datasetId": dataset_id,
            "snapshotId": str(item.get("snapshotId") or item.get("id") or ""),
            "type": str(item.get("type") or ""),
            "tradingDate": str(item.get("tradingDate") or ""),
            "slotTime": str(item.get("slotTime") or ""),
            "timestamp": timestamp,
            "displayKey": str(item.get("displayKey") or item.get("snapshotId") or item.get("id") or ""),
            "captureMode": str(item.get("captureMode") or "real_time"),
            "capturedAt": int(item.get("capturedAt") or timestamp),
            "dataTimestamp": int(item.get("dataTimestamp") or timestamp),
            "delayMs": int(item.get("delayMs") or 0),
            "qualityFlags": item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else [],
            "source": str(item.get("source") or "browser_runtime"),
        }

    @staticmethod
    def _frame_doc(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
        return {
            "datasetId": dataset_id,
            "snapshotId": str(item.get("snapshotId") or item.get("id") or ""),
            "type": str(item.get("type") or ""),
            "tradingDate": str(item.get("tradingDate") or ""),
            "slotTime": str(item.get("slotTime") or ""),
            "timestamp": int(item.get("timestamp") or 0),
            "displayKey": str(item.get("displayKey") or item.get("snapshotId") or item.get("id") or ""),
            "captureMode": str(item.get("captureMode") or "real_time"),
            "qualityFlags": item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else [],
            "delayMs": int(item.get("delayMs") or 0),
            "source": str(item.get("source") or "browser_runtime"),
            "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            "marketStats": item.get("marketStats") if isinstance(item.get("marketStats"), dict) else {},
            "sentiment": item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {},
            "moneyFlow": item.get("moneyFlow") if isinstance(item.get("moneyFlow"), dict) else {},
            "indices": item.get("indices") if isinstance(item.get("indices"), dict) else {},
            "limitSummary": item.get("limitSummary") if isinstance(item.get("limitSummary"), dict) else {},
            "rotationSummary": item.get("rotationSummary") if isinstance(item.get("rotationSummary"), dict) else {},
            "stockRowCount": int(item.get("stockRowCount") or 0),
            "sectorRowCount": int(item.get("sectorRowCount") or 0),
        }

    @staticmethod
    def _stock_doc(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
        row_id = str(item.get("rowId") or item.get("id") or f"{item.get('snapshotId')}:{item.get('code')}")
        return {**item, "datasetId": dataset_id, "rowId": row_id, "id": row_id}

    @staticmethod
    def _sector_doc(dataset_id: str, item: dict[str, Any]) -> dict[str, Any]:
        row_id = str(item.get("rowId") or item.get("id") or f"{item.get('snapshotId')}:{item.get('entityType')}:{item.get('entityKey')}")
        return {**item, "datasetId": dataset_id, "rowId": row_id, "id": row_id}

    @staticmethod
    def _snapshot_id_from_payload(item: dict[str, Any]) -> str:
        return str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or "")

    @classmethod
    def _filter_snapshot_payloads(cls, items: list[dict[str, Any]], snapshot_ids: set[str]) -> list[dict[str, Any]]:
        return [item for item in items if isinstance(item, dict) and cls._snapshot_id_from_payload(item) in snapshot_ids]

    @staticmethod
    def _merge_values(value: str | None, values: list[str] | None) -> list[str]:
        output: list[str] = []
        if value:
            output.append(str(value))
        output.extend(str(item) for item in values or [] if item)
        return list(dict.fromkeys(output))

    @staticmethod
    def _sector_entity_to_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "id": row.get("entityKey") or row.get("rowId") or row.get("id"),
            "code": row.get("entityCode") or row.get("entityKey"),
            "name": row.get("entityName"),
            "themeName": row.get("entityName"),
        }
