"""Snapshot ingest payload builder.

Converts a ``SnapshotSlot`` and ``MarketDataContext`` into a bundle dict
accepted by ``backend.data.snapshot_ingest_normalizer.normalize_snapshot_ingest()``.
"""

from __future__ import annotations

from typing import Any

from .models import MarketDataContext, SnapshotSlot


def build_ingest_payload(
    slot: SnapshotSlot,
    market_context: MarketDataContext,
    *,
    dataset_id: str = "dragonboard_backend_shadow",
    source: str = "quantboard_backend_collector",
    capture_mode: str = "real_time",
    quality_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal ingest payload dict from a slot and market context.

    The returned dict is designed to be used as the ``bundle`` field of
    ``backend.data.schemas.SnapshotIngestRequest``.  It contains ``items``
    (records), ``frames``, ``stockRows``, ``sectorRows``, and collector
    metadata.

    Parameters
    ----------
    slot:
        The target snapshot slot (snapshot_type, trading_date, slot_time, timestamp_ms).
    market_context:
        Raw material collected from providers (stocks, sectors, quotes, depth,
        themes, source_health, market_meta).
    dataset_id:
        Target dataset identifier.  Defaults to the shadow dataset so the
        collector does not accidentally write production data.
    source:
        Value written into every ``source`` field.  Distinguishes backend
        collector snapshots from browser-produced ones.
    capture_mode:
        ``"real_time"`` when captured within the slot window, ``"delayed"``
        otherwise.
    quality_flags:
        Optional list of quality-warning tags recorded alongside the payload.
    """
    snapshot_id = slot.snapshot_id

    # ── Record (item) ─────────────────────────────────────────────────────
    record = {
        "id": snapshot_id,
        "snapshotId": snapshot_id,
        "type": slot.snapshot_type,
        "tradingDate": slot.trading_date,
        "slotTime": slot.slot_time,
        "timestamp": slot.timestamp_ms,
        "displayKey": snapshot_id,
        "captureMode": capture_mode,
        "source": source,
        "payload": {
            "hotlist": market_context.stocks,
            "sectors": market_context.sectors,
            "marketStats": market_context.market_meta,
        },
    }

    # ── Frame ──────────────────────────────────────────────────────────────
    frame = {
        "id": snapshot_id,
        "snapshotId": snapshot_id,
        "type": slot.snapshot_type,
        "tradingDate": slot.trading_date,
        "slotTime": slot.slot_time,
        "timestamp": slot.timestamp_ms,
        "displayKey": snapshot_id,
        "captureMode": capture_mode,
        "source": source,
        "marketStats": market_context.market_meta,
        "stockRowCount": len(market_context.stocks),
        "sectorRowCount": len(market_context.sectors),
    }

    # ── Stock rows ─────────────────────────────────────────────────────────
    stock_rows: list[dict[str, Any]] = []
    for stock in market_context.stocks:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "").strip()
        if not code:
            continue

        row: dict[str, Any] = {
            "id": f"{snapshot_id}:{code}",
            "snapshotId": snapshot_id,
            "type": slot.snapshot_type,
            "tradingDate": slot.trading_date,
            "slotTime": slot.slot_time,
            "timestamp": slot.timestamp_ms,
            "captureMode": capture_mode,
            "source": source,
            "code": code,
            "name": stock.get("name", code),
            "rank": int(float(stock.get("rank") or 0)),
        }

        # Optional camelCase fields carried through when present
        for field in ("price", "pctChange", "volume", "amount", "turnover", "heat"):
            if field in stock:
                row[field] = stock[field]

        # Themes from the market_context.themes dict keyed by code
        themes = market_context.themes.get(code)
        if themes is not None:
            row["themes"] = themes
        elif "themes" in stock:
            row["themes"] = stock["themes"]

        stock_rows.append(row)

    stock_rows.sort(key=lambda r: int(r.get("rank") or 999999))

    # ── Sector rows ────────────────────────────────────────────────────────
    sector_rows: list[dict[str, Any]] = []
    for sector in market_context.sectors:
        if not isinstance(sector, dict):
            continue
        key = (
            str(sector.get("code") or sector.get("name") or "").strip()
            or f"sector_{len(sector_rows)}"
        )
        entity_type = str(sector.get("entityType") or "sector")

        sector_rows.append(
            {
                "id": f"{snapshot_id}:{entity_type}:{key}",
                "snapshotId": snapshot_id,
                "type": slot.snapshot_type,
                "tradingDate": slot.trading_date,
                "slotTime": slot.slot_time,
                "timestamp": slot.timestamp_ms,
                "captureMode": capture_mode,
                "source": source,
                "entityType": entity_type,
                "entityKey": str(key),
                "entityName": sector.get("name", str(key)),
                "rank": int(float(sector.get("rank") or len(sector_rows) + 1)),
            }
        )

    # ── Bundle ─────────────────────────────────────────────────────────────
    result: dict[str, Any] = {
        "items": [record],
        "frames": [frame],
        "stockRows": stock_rows,
        "sectorRows": sector_rows,
        "datasetId": dataset_id,
        "snapshotId": snapshot_id,
        "captureMode": capture_mode,
        "source": source,
    }

    if quality_flags:
        result["qualityFlags"] = quality_flags

    return result
