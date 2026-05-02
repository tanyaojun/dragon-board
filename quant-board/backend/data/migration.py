from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.data.importers import (
    ImporterError,
    JsonBundleImporter,
    SnapshotBundle,
    frame_from_record,
    normalize_record,
    sector_rows_from_record,
    stock_rows_from_record,
)
from backend.data.models import Dataset, SnapshotFrameModel
from backend.data.repository import Repository
from backend.utils import json_dumps, json_loads, read_json_file, stable_hash


class SnapshotMigrationService:
    def __init__(self, session: Session | None):
        self.session = session
        self.repo = Repository(session)

    def import_json(self, request: dict[str, Any]) -> dict[str, Any]:
        dry_run = bool(request.get("dryRun") or request.get("dry_run"))
        dataset_id = str(request.get("datasetId") or request.get("dataset_id") or "dragonboard_history")
        source = str(request.get("source") or "dragon_board_history_migration")
        bundle = self._read_bundle(request)
        normalized = self._normalize_bundle(bundle)

        snapshot_ids = self._snapshot_ids(normalized)
        report = {
            "scanned": len(snapshot_ids),
            "imported": 0,
            "skipped": 0,
            "errors": [],
            "dry_run": dry_run,
            **self._bundle_summary(normalized),
        }
        if not snapshot_ids:
            report["errors"].append("no snapshot frames found in json bundle")
            return {"ok": False, "datasetId": dataset_id, "report": report}

        existing_ids = self._existing_snapshot_ids(dataset_id, snapshot_ids)
        idempotency_key = str(
            request.get("idempotencyKey")
            or request.get("idempotency_key")
            or stable_hash({"migration": "snapshot_json", "datasetId": dataset_id, "snapshotIds": snapshot_ids})
        )
        if self.repo.get_outbox_by_idempotency_key(idempotency_key):
            missing_ids = set(snapshot_ids) - existing_ids
            if not missing_ids:
                report["skipped"] = len(snapshot_ids)
                return {
                    "ok": True,
                    "datasetId": dataset_id,
                    "idempotencyKey": idempotency_key,
                    "deduped": True,
                    "report": report,
                }
            idempotency_key = stable_hash(
                {
                    "migration": "snapshot_json_retry",
                    "datasetId": dataset_id,
                    "snapshotIds": sorted(missing_ids),
                    "sourceKey": idempotency_key,
                }
            )

        report["skipped"] = len(existing_ids)
        report["imported"] = 0 if dry_run else len(snapshot_ids) - len(existing_ids)
        dataset = self._dataset_from_bundle(dataset_id, request, normalized, source)
        if dry_run:
            return {
                "ok": True,
                "dataset": self.repo.dataset_to_dict(dataset),
                "datasetId": dataset_id,
                "idempotencyKey": idempotency_key,
                "deduped": False,
                "report": report,
            }

        to_import = self._filter_bundle_by_snapshot_ids(normalized, set(snapshot_ids) - existing_ids)
        if not to_import.frames:
            saved = self.repo.get_dataset(dataset_id)
            result = {"dataset": self.repo.dataset_to_dict(saved)} if saved else {}
            return {
                "ok": True,
                "datasetId": dataset_id,
                "idempotencyKey": idempotency_key,
                "deduped": False,
                "report": report,
                **result,
            }

        try:
            result = self.repo.save_snapshot_ingest(
                dataset,
                to_import.records,
                to_import.frames,
                to_import.stock_rows,
                to_import.sector_rows,
                idempotency_key=idempotency_key,
                trading_date=dataset.start_date,
                source=source,
            )
        except RuntimeError as error:
            report["errors"].append(str(error))
            return {
                "ok": False,
                "datasetId": dataset_id,
                "idempotencyKey": idempotency_key,
                "deduped": False,
                "report": report,
            }
        return {
            "ok": True,
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "deduped": result.get("deduped", False),
            "report": report,
            **result,
        }

    def _read_bundle(self, request: dict[str, Any]) -> SnapshotBundle:
        content = request.get("content") or request.get("bundle") or request.get("payload")
        if content is not None:
            return self._bundle_from_payload(content)

        source_path = request.get("sourcePath") or request.get("source_path") or request.get("path")
        if not source_path:
            raise ImporterError("sourcePath or content is required")
        path = Path(str(source_path))
        if path.is_file():
            return self._bundle_from_payload(read_json_file(path), {"source_file": str(path)})
        return JsonBundleImporter().read(path)

    def _bundle_from_payload(self, payload: Any, metadata: dict[str, Any] | None = None) -> SnapshotBundle:
        metadata = metadata or {}
        if isinstance(payload, list):
            records = [item for item in (self._normalize_record_row(row) for row in payload if isinstance(row, dict)) if item]
            return self._bundle_from_records(records, metadata)
        if not isinstance(payload, dict):
            raise ImporterError("json bundle root must be object or array")

        raw_records = payload.get("records") or payload.get("snapshots") or payload.get("items") or []
        records = [item for item in (self._normalize_record_row(row) for row in raw_records if isinstance(row, dict)) if item]
        frames = [self._normalize_frame_row(row) for row in payload.get("frames") or [] if isinstance(row, dict)]
        stock_rows = [
            self._normalize_stock_row(row)
            for row in payload.get("stockRows") or payload.get("stock_rows") or []
            if isinstance(row, dict)
        ]
        sector_rows = [
            self._normalize_sector_row(row)
            for row in payload.get("sectorRows") or payload.get("sector_rows") or []
            if isinstance(row, dict)
        ]
        merged_metadata = {**(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}), **metadata}
        if records and (not frames or not stock_rows):
            return self._bundle_from_records(records, merged_metadata)
        if not records and any(key in payload for key in ["type", "tradingDate", "timestamp", "payload"]):
            record = self._normalize_record_row(payload)
            return self._bundle_from_records([record], merged_metadata) if record else SnapshotBundle(metadata=merged_metadata)
        return SnapshotBundle(
            records=records,
            frames=frames,
            stock_rows=stock_rows,
            sector_rows=sector_rows,
            metadata=merged_metadata,
        )

    @staticmethod
    def _bundle_from_records(records: list[dict[str, Any]], metadata: dict[str, Any]) -> SnapshotBundle:
        frames = [frame_from_record(record) for record in records]
        stock_rows: list[dict[str, Any]] = []
        sector_rows: list[dict[str, Any]] = []
        for record in records:
            stock_rows.extend(stock_rows_from_record(record))
            sector_rows.extend(sector_rows_from_record(record))
        return SnapshotBundle(records, frames, stock_rows, sector_rows, metadata)

    @staticmethod
    def _normalize_bundle(bundle: SnapshotBundle) -> SnapshotBundle:
        records = [item for item in (SnapshotMigrationService._normalize_record_row(row) for row in bundle.records) if item]
        frames = [SnapshotMigrationService._normalize_frame_row(row) for row in bundle.frames if isinstance(row, dict)]
        if records and not frames:
            frames = [frame_from_record(record) for record in records]
        if not records and frames:
            records = [
                {
                    "id": frame.get("snapshotId") or frame.get("id"),
                    "type": frame.get("type"),
                    "tradingDate": frame.get("tradingDate"),
                    "slotTime": frame.get("slotTime"),
                    "timestamp": frame.get("timestamp"),
                    "displayKey": frame.get("displayKey") or frame.get("snapshotId") or frame.get("id"),
                    "captureMode": frame.get("captureMode") or "real_time",
                    "source": frame.get("source") or "browser_runtime",
                    "payload": frame.get("payload") or {},
                }
                for frame in frames
                if frame.get("snapshotId") or frame.get("id")
            ]
        snapshot_ids = {str(frame.get("snapshotId") or frame.get("id") or "") for frame in frames}
        snapshot_ids.discard("")
        stock_rows = [
            row
            for row in (SnapshotMigrationService._normalize_stock_row(item) for item in bundle.stock_rows)
            if str(row.get("snapshotId") or "") in snapshot_ids
        ]
        sector_rows = [
            row
            for row in (SnapshotMigrationService._normalize_sector_row(item) for item in bundle.sector_rows)
            if str(row.get("snapshotId") or "") in snapshot_ids
        ]
        return SnapshotBundle(records, frames, stock_rows, sector_rows, bundle.metadata)

    @staticmethod
    def _snapshot_ids(bundle: SnapshotBundle) -> list[str]:
        ids = {str(frame.get("snapshotId") or frame.get("id") or "") for frame in bundle.frames}
        ids.update(str(record.get("id") or record.get("snapshotId") or "") for record in bundle.records)
        ids.discard("")
        return sorted(ids)

    @staticmethod
    def _bundle_summary(bundle: SnapshotBundle) -> dict[str, Any]:
        dates = sorted({str(frame.get("tradingDate")) for frame in bundle.frames if frame.get("tradingDate")})
        types = sorted({str(frame.get("type")) for frame in bundle.frames if frame.get("type")})
        return {
            "record_count": len(bundle.records),
            "frame_count": len(bundle.frames),
            "stock_row_count": len(bundle.stock_rows),
            "sector_row_count": len(bundle.sector_rows),
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if dates else None,
            "snapshot_types": types,
        }

    @staticmethod
    def _normalize_record_row(row: dict[str, Any]) -> dict[str, Any] | None:
        if "trading_date" not in row and "snapshot_id" not in row:
            return normalize_record(row)
        normalized = dict(row)
        normalized.setdefault("id", row.get("snapshotId") or row.get("snapshot_id"))
        normalized.setdefault("snapshotId", normalized.get("id"))
        normalized.setdefault("tradingDate", row.get("trading_date"))
        normalized.setdefault("slotTime", row.get("slot_time"))
        normalized.setdefault("captureMode", row.get("capture_mode"))
        payload = row.get("payload") or row.get("payload_json")
        if isinstance(payload, str):
            payload = json_loads(payload, {})
        if isinstance(payload, dict):
            normalized["payload"] = payload
        return normalize_record(normalized)

    @staticmethod
    def _normalize_frame_row(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item.setdefault("id", row.get("snapshotId") or row.get("snapshot_id"))
        item.setdefault("snapshotId", item.get("id"))
        item.setdefault("tradingDate", row.get("trading_date"))
        item.setdefault("slotTime", row.get("slot_time"))
        item.setdefault("captureMode", row.get("capture_mode"))
        context = row.get("marketContext") or row.get("market_context") or row.get("market_context_json")
        if isinstance(context, str):
            context = json_loads(context, {})
        if isinstance(context, dict):
            item.setdefault("marketStats", context.get("marketStats"))
            item.setdefault("sentiment", context.get("sentiment"))
            item.setdefault("moneyFlow", context.get("moneyFlow"))
            item.setdefault("indices", context.get("indices"))
            item.setdefault("limitSummary", context.get("limitSummary"))
            item.setdefault("rotationSummary", context.get("rotationSummary"))
            item.setdefault("payload", context.get("payload"))
        item.setdefault("stockRowCount", row.get("stock_row_count"))
        item.setdefault("sectorRowCount", row.get("sector_row_count"))
        return item

    @staticmethod
    def _normalize_stock_row(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item.setdefault("id", row.get("rowId") or row.get("row_id"))
        item.setdefault("rowId", item.get("id"))
        item.setdefault("snapshotId", row.get("snapshot_id"))
        item.setdefault("tradingDate", row.get("trading_date"))
        item.setdefault("slotTime", row.get("slot_time"))
        item.setdefault("captureMode", row.get("capture_mode"))
        item.setdefault("volumeRatio", row.get("volume_ratio"))
        item.setdefault("turnoverRate", row.get("turnover_rate"))
        return item

    @staticmethod
    def _normalize_sector_row(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        item.setdefault("id", row.get("rowId") or row.get("row_id"))
        item.setdefault("rowId", item.get("id"))
        item.setdefault("snapshotId", row.get("snapshot_id"))
        item.setdefault("tradingDate", row.get("trading_date"))
        item.setdefault("slotTime", row.get("slot_time"))
        item.setdefault("entityType", row.get("entity_type"))
        item.setdefault("entityKey", row.get("entity_key"))
        item.setdefault("entityName", row.get("entity_name"))
        return item

    def _existing_snapshot_ids(self, dataset_id: str, snapshot_ids: list[str]) -> set[str]:
        if self.session is None or not snapshot_ids:
            return set()
        rows = self.session.scalars(
            select(SnapshotFrameModel.snapshot_id).where(
                SnapshotFrameModel.dataset_id == dataset_id,
                SnapshotFrameModel.snapshot_id.in_(snapshot_ids),
            )
        )
        return {str(row) for row in rows}

    @staticmethod
    def _filter_bundle_by_snapshot_ids(bundle: SnapshotBundle, snapshot_ids: set[str]) -> SnapshotBundle:
        if not snapshot_ids:
            return SnapshotBundle(metadata=bundle.metadata)
        return SnapshotBundle(
            records=[
                row
                for row in bundle.records
                if str(row.get("id") or row.get("snapshotId") or "") in snapshot_ids
            ],
            frames=[
                row
                for row in bundle.frames
                if str(row.get("snapshotId") or row.get("id") or "") in snapshot_ids
            ],
            stock_rows=[row for row in bundle.stock_rows if str(row.get("snapshotId") or "") in snapshot_ids],
            sector_rows=[row for row in bundle.sector_rows if str(row.get("snapshotId") or "") in snapshot_ids],
            metadata=bundle.metadata,
        )

    def _dataset_from_bundle(
        self,
        dataset_id: str,
        request: dict[str, Any],
        bundle: SnapshotBundle,
        source: str,
    ) -> Dataset:
        dates = sorted({str(frame.get("tradingDate")) for frame in bundle.frames if frame.get("tradingDate")})
        types = sorted({str(frame.get("type")) for frame in bundle.frames if frame.get("type")})
        name = str(request.get("name") or f"DragonBoard History {dataset_id}")
        return Dataset(
            id=dataset_id,
            name=name,
            source_type="dragon_board_history_migration",
            source_path=str(request.get("sourcePath") or request.get("source_path") or request.get("path") or ""),
            db_name=str(bundle.metadata.get("db_name") or "DragonBoardData"),
            schema_fingerprint=stable_hash(
                {"snapshotIds": self._snapshot_ids(bundle), "source": source, "metadata": bundle.metadata}
            ),
            snapshot_count=len(bundle.records),
            frame_count=len(bundle.frames),
            stock_row_count=len(bundle.stock_rows),
            sector_row_count=len(bundle.sector_rows),
            start_date=dates[0] if dates else None,
            end_date=dates[-1] if dates else None,
            snapshot_types_json=json_dumps(types),
            metadata_json=json_dumps({"source": source, "migration": "snapshot_json", **bundle.metadata}),
            created_at=datetime.utcnow(),
        )
