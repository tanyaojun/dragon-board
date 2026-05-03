from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.data.importers import ImporterError, read_snapshot_bundle
from backend.data.models import Dataset
from backend.data.quality_gate import evaluate_snapshot_quality
from backend.data.repository import Repository
from backend.data.schemas import ImportDatasetRequest
from backend.utils import json_dumps, new_id, stable_hash


class DatasetService:
    def __init__(self, session: Session | None):
        self.repo = Repository(session)

    def list_datasets(self) -> list[dict[str, Any]]:
        return [self.repo.dataset_to_dict(model) for model in self.repo.list_datasets()]

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        model = self.repo.get_dataset(dataset_id)
        return self.repo.dataset_to_dict(model) if model else None

    def import_dataset(self, request: ImportDatasetRequest) -> dict[str, Any]:
        if request.source_type == "sqlite_snapshots":
            return self._import_from_sqlite_snapshots(request)

        bundle = read_snapshot_bundle(request.source_type, request.source_path)
        if not bundle.frames and bundle.records:
            raise ImporterError("importer returned records without frames")

        frames = self._filter_by_request(bundle.frames, request)
        if not frames:
            source_hint = request.source_path or request.source_type
            raise ImporterError(f"no snapshot frames found from {source_hint}; check source path, origin, and snapshot type")
        snapshot_ids = {str(frame.get("snapshotId") or frame.get("id")) for frame in frames}
        stock_rows = [row for row in bundle.stock_rows if str(row.get("snapshotId")) in snapshot_ids]
        sector_rows = [row for row in bundle.sector_rows if str(row.get("snapshotId")) in snapshot_ids]
        records = [
            record
            for record in bundle.records
            if str(record.get("id") or record.get("snapshotId")) in snapshot_ids
        ]

        if not records and frames:
            records = [
                {
                    "id": frame.get("snapshotId"),
                    "type": frame.get("type"),
                    "tradingDate": frame.get("tradingDate"),
                    "slotTime": frame.get("slotTime"),
                    "timestamp": frame.get("timestamp"),
                    "displayKey": frame.get("displayKey") or frame.get("snapshotId"),
                    "captureMode": frame.get("captureMode") or "real_time",
                    "source": frame.get("source") or "browser_runtime",
                    "payload": frame.get("payload") or {},
                }
                for frame in frames
            ]

        quality = evaluate_snapshot_quality(
            frames,
            stock_rows,
            snapshot_type=request.snapshot_types[0] if request.snapshot_types else "half_hour",
            min_snapshot_count=2,
            min_hotlist_size=1,
        )

        dates = sorted({str(frame.get("tradingDate")) for frame in frames if frame.get("tradingDate")})
        types = sorted({str(frame.get("type")) for frame in frames if frame.get("type")})
        dataset = Dataset(
            id=new_id("ds"),
            name=request.name or f"QuantBoard Dataset {datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            source_type=request.source_type,
            source_path=request.source_path or "",
            db_name=str(bundle.metadata.get("db_name") or "DragonBoardData"),
            schema_fingerprint=bundle.fingerprint(),
            snapshot_count=len(records),
            frame_count=len(frames),
            stock_row_count=len(stock_rows),
            sector_row_count=len(sector_rows),
            start_date=dates[0] if dates else None,
            end_date=dates[-1] if dates else None,
            snapshot_types_json=json_dumps(types),
            metadata_json=json_dumps({**bundle.metadata, "qualityGate": quality.to_dict()}),
            created_at=datetime.utcnow(),
        )
        if request.dry_run:
            result = self.repo.dataset_to_dict(dataset)
            result["qualityGate"] = quality.to_dict()
            result["dryRun"] = True
            return result
        self.repo.save_dataset_bundle(dataset, records, frames, stock_rows, sector_rows)
        result = self.repo.dataset_to_dict(dataset)
        result["qualityGate"] = quality.to_dict()
        return result

    @staticmethod
    def _filter_by_request(frames: list[dict[str, Any]], request: ImportDatasetRequest) -> list[dict[str, Any]]:
        output = []
        requested_types = set(request.snapshot_types or [])
        for frame in frames:
            if requested_types and frame.get("type") not in requested_types:
                continue
            date = str(frame.get("tradingDate") or "")
            if request.start_date and date < request.start_date:
                continue
            if request.end_date and date > request.end_date:
                continue
            output.append(frame)
        return sorted(output, key=lambda item: int(item.get("timestamp") or 0))

    def _import_from_sqlite_snapshots(self, request: ImportDatasetRequest) -> dict[str, Any]:
        source_dataset_id = request.source_dataset_id or request.source_path or "dragonboard_live"
        source = self.repo.get_dataset(source_dataset_id)
        if not source:
            fallback = self._latest_snapshot_source()
            if source_dataset_id == "dragonboard_live" and fallback:
                source = fallback
                source_dataset_id = fallback.id
            else:
                raise ImporterError(f"SQLite snapshot source dataset not found: {source_dataset_id}")

        requested_types = list(dict.fromkeys(request.snapshot_types or ["half_hour"]))
        records, frames, stock_rows, sector_rows = self.repo.load_dataset_bundle_slice(
            source_dataset_id,
            snapshot_types=requested_types,
            start_date=request.start_date,
            end_date=request.end_date,
            max_snapshots=request.max_snapshots,
        )
        if not frames:
            raise ImporterError(
                "no SQLite snapshot frames found; check sourceDatasetId, date range, and snapshot type"
            )

        snapshot_ids = {str(frame.get("snapshotId") or frame.get("id")) for frame in frames}
        if not records:
            records = [
                {
                    "id": frame.get("snapshotId"),
                    "type": frame.get("type"),
                    "tradingDate": frame.get("tradingDate"),
                    "slotTime": frame.get("slotTime"),
                    "timestamp": frame.get("timestamp"),
                    "displayKey": frame.get("displayKey") or frame.get("snapshotId"),
                    "captureMode": frame.get("captureMode") or "real_time",
                    "source": frame.get("source") or "sqlite_snapshots",
                    "payload": frame.get("payload") or {},
                }
                for frame in frames
            ]

        quality = evaluate_snapshot_quality(
            frames,
            stock_rows,
            snapshot_type=requested_types[0],
            min_snapshot_count=2,
            min_hotlist_size=1,
        )
        dates = sorted({str(frame.get("tradingDate")) for frame in frames if frame.get("tradingDate")})
        types = sorted({str(frame.get("type")) for frame in frames if frame.get("type")})
        fingerprint_payload = {
            "sourceDatasetId": source_dataset_id,
            "snapshotIds": sorted(snapshot_ids),
            "snapshotTypes": types,
            "startDate": request.start_date,
            "endDate": request.end_date,
            "maxSnapshots": request.max_snapshots,
        }
        dataset = Dataset(
            id=new_id("ds"),
            name=request.name or self._derived_dataset_name(source, dates, types),
            source_type="sqlite_snapshots",
            source_path=source_dataset_id,
            db_name=source.db_name or "DragonBoardData",
            schema_fingerprint=stable_hash(fingerprint_payload),
            snapshot_count=len(records),
            frame_count=len(frames),
            stock_row_count=len(stock_rows),
            sector_row_count=len(sector_rows),
            start_date=dates[0] if dates else None,
            end_date=dates[-1] if dates else None,
            snapshot_types_json=json_dumps(types),
            metadata_json=json_dumps(
                {
                    "sourceDatasetId": source_dataset_id,
                    "sourceDatasetName": source.name,
                    "source": "sqlite_snapshots",
                    "qualityGate": quality.to_dict(),
                    "filters": {
                        "snapshotTypes": requested_types,
                        "startDate": request.start_date,
                        "endDate": request.end_date,
                        "maxSnapshots": request.max_snapshots,
                    },
                }
            ),
            created_at=datetime.utcnow(),
        )
        if request.dry_run:
            result = self.repo.dataset_to_dict(dataset)
            result["qualityGate"] = quality.to_dict()
            result["dryRun"] = True
            return result

        self.repo.save_dataset_bundle(dataset, records, frames, stock_rows, sector_rows)
        result = self.repo.dataset_to_dict(dataset)
        result["qualityGate"] = quality.to_dict()
        return result

    @staticmethod
    def _derived_dataset_name(source: Dataset, dates: list[str], snapshot_types: list[str]) -> str:
        type_label = ",".join(snapshot_types) or "snapshots"
        if dates:
            return f"{source.name or source.id} · {dates[0]}~{dates[-1]} · {type_label}"
        return f"{source.name or source.id} · {type_label}"

    def _latest_snapshot_source(self) -> Dataset | None:
        for dataset in self.repo.list_datasets():
            if any(
                int(value or 0) > 0
                for value in (
                    dataset.frame_count,
                    dataset.snapshot_count,
                    dataset.stock_row_count,
                    dataset.sector_row_count,
                )
            ):
                return dataset
        return None
