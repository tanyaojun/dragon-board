from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.data.importers import frame_from_record, sector_rows_from_record, stock_rows_from_record
from backend.data.models import Dataset
from backend.data.schemas import SnapshotIngestRequest
from backend.utils import json_dumps, stable_hash


def normalize_snapshot_ingest(
    request: SnapshotIngestRequest,
) -> tuple[Dataset, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], str]:
    bundle = request.bundle
    if not isinstance(bundle, dict):
        raise ValueError("bundle is required")

    records = [item for item in bundle.get("items") or bundle.get("records") or [] if isinstance(item, dict)]
    if not records:
        raise ValueError("bundle.items is required")
    frames = [item for item in bundle.get("frames") or [] if isinstance(item, dict)]
    stock_rows = [item for item in bundle.get("stockRows") or bundle.get("stock_rows") or [] if isinstance(item, dict)]
    sector_rows = [item for item in bundle.get("sectorRows") or bundle.get("sector_rows") or [] if isinstance(item, dict)]

    if not frames:
        frames = [frame_from_record(record) for record in records if str(record.get("type") or "") != "five_minute"]
    if not stock_rows:
        for record in records:
            stock_rows.extend(stock_rows_from_record(record))
    if not sector_rows:
        for record in records:
            sector_rows.extend(sector_rows_from_record(record))

    def row_snapshot_id(item: dict[str, Any]) -> str:
        return str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or "")

    stock_row_count_by_snapshot: dict[str, int] = {}
    for row in stock_rows:
        snapshot_id = row_snapshot_id(row)
        if snapshot_id:
            stock_row_count_by_snapshot[snapshot_id] = stock_row_count_by_snapshot.get(snapshot_id, 0) + 1
    empty_formal_snapshot_ids = [
        snapshot_id
        for frame in frames
        for snapshot_id in [row_snapshot_id(frame)]
        if str(frame.get("type") or "") != "five_minute"
        and snapshot_id
        and str(frame.get("captureMode") or "real_time") != "restored"
        and stock_row_count_by_snapshot.get(snapshot_id, 0) == 0
    ]
    if empty_formal_snapshot_ids:
        raise ValueError(f"formal snapshot hotlist is empty: {empty_formal_snapshot_ids[0]}")

    snapshot_ids = {str(record.get("id") or record.get("snapshotId") or "") for record in records}
    snapshot_ids.update(str(frame.get("snapshotId") or frame.get("id") or "") for frame in frames)
    snapshot_ids.discard("")
    if not snapshot_ids:
        raise ValueError("snapshot id is required")

    trading_dates = sorted(
        {
            str(item.get("tradingDate") or "")
            for item in [*records, *frames]
            if isinstance(item, dict) and item.get("tradingDate")
        }
    )
    snapshot_types = sorted(
        {
            str(item.get("type") or "")
            for item in [*records, *frames]
            if isinstance(item, dict) and item.get("type")
        }
    )
    dataset_id = request.dataset_id or "dragonboard_live"
    dataset = Dataset(
        id=dataset_id,
        name="DragonBoard Live Snapshots" if dataset_id == "dragonboard_live" else dataset_id,
        source_type="dragon_board_runtime",
        source_path="",
        db_name="DragonBoardData",
        schema_fingerprint=stable_hash({"snapshotIds": sorted(snapshot_ids), "source": request.source}),
        snapshot_count=len(records),
        frame_count=len(frames),
        stock_row_count=len(stock_rows),
        sector_row_count=len(sector_rows),
        start_date=trading_dates[0] if trading_dates else request.trading_date,
        end_date=trading_dates[-1] if trading_dates else request.trading_date,
        snapshot_types_json=json_dumps(snapshot_types),
        metadata_json=json_dumps({"source": request.source, "ingest": "snapshots_ingest"}),
        created_at=datetime.utcnow(),
    )
    idempotency_key = request.idempotency_key or stable_hash(
        {
            "datasetId": dataset_id,
            "records": records,
            "frames": frames,
            "stockRows": stock_rows,
            "sectorRows": sector_rows,
        }
    )
    return dataset, records, frames, stock_rows, sector_rows, idempotency_key
