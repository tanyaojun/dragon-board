from __future__ import annotations

from typing import Any


def _maybe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _maybe_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _compute_archive_source(has_sqlite: bool, has_archive: bool) -> str:
    if has_sqlite and has_archive:
        return "mixed"
    if has_archive:
        return "parquet_archive"
    return "sqlite"


def _frames_from_backup_rows(
    rows: list[dict[str, Any]],
    snapshot_type: str,
    start_date: str | None,
    end_date: str | None,
    include_payload: bool,
) -> list[dict[str, Any]]:
    frames = []
    for row in rows:
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
        frame = payload.get("frame") if isinstance(payload.get("frame"), dict) else None
        if not frame or frame.get("type") != snapshot_type:
            continue
        trading_date = str(frame.get("tradingDate") or "")
        if start_date and trading_date < start_date:
            continue
        if end_date and trading_date > end_date:
            continue
        item = {
            "snapshotId": frame.get("snapshotId"),
            "timestamp": frame.get("timestamp"),
            "tradingDate": frame.get("tradingDate"),
            "slotTime": frame.get("slotTime"),
            "type": frame.get("type"),
            "captureMode": frame.get("captureMode") or "real_time",
            "source": frame.get("source") or "supabase_backup",
            "marketContext": {},
            "stocks": payload.get("stocks") if isinstance(payload.get("stocks"), list) else [],
        }
        if include_payload:
            item["payload"] = frame.get("payload") or {}
        frames.append(item)
    return sorted(frames, key=lambda item: int(item.get("timestamp") or 0))
