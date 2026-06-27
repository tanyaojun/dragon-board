"""Snapshot ingest payload builder.

Converts a ``SnapshotSlot`` and ``MarketDataContext`` into a bundle dict
accepted by ``backend.data.snapshot_ingest_normalizer.normalize_snapshot_ingest()``.
"""

from __future__ import annotations

from typing import Any

from .models import MarketDataContext, SnapshotSlot


SECTOR_FACTOR_FIELDS = (
    "heatScore",
    "momentumScore",
    "breadthScore",
    "fundScore",
    "leadershipScore",
    "correlationScore",
    "crowdingRisk",
    "persistenceScore",
    "change",
    "mainNetInflow",
    "volumeRatio",
    "ztCount",
    "leaderCount",
    "themeQualityFlags",
    "metadata",
)


def _enrich_stock_rows_from_quotes(
    stock_rows: list[dict[str, Any]],
    quotes: list[dict[str, Any]],
    money_flow: list[dict[str, Any]],
) -> None:
    """Merge quote and money-flow data into stock rows in-place.

    Only fields that are missing or zero in the stock row are filled from
    the quote.  New fields (totalMarketValue, moneyFlow) are always added
    when available.
    """
    if not quotes and not money_flow:
        return

    quote_by_code: dict[str, dict[str, Any]] = {}
    for q in quotes:
        code = str(q.get("code") or "").strip()
        if code:
            quote_by_code[code] = q

    flow_by_code: dict[str, dict[str, Any]] = {}
    for mf in money_flow:
        code = str(mf.get("code") or "").strip()
        if code:
            flow_by_code[code] = mf

    for row in stock_rows:
        code = str(row.get("code") or "").strip()
        if not code:
            continue

        q = quote_by_code.get(code)
        if q:
            quote_name = str(q.get("name") or "").strip()
            current_name = str(row.get("name") or "").strip()
            if quote_name and (not current_name or current_name == code):
                row["name"] = quote_name

            # Override hotlist values with more accurate quote values when
            # the hotlist value is missing or zero.
            for field in ("price", "pctChange", "volume", "amount", "turnover"):
                if not row.get(field):
                    val = q.get(field)
                    if val:
                        row[field] = val
            if row.get("pctChange") is not None:
                row["change"] = row["pctChange"]
            if row.get("amount") is not None:
                row["turnover"] = row["amount"]
            turnover_rate = q.get("turnover")
            if turnover_rate is not None and not row.get("turnoverRate"):
                row["turnoverRate"] = turnover_rate
            volume_ratio = q.get("volumeRatio")
            if volume_ratio is not None and not row.get("volumeRatio"):
                row["volumeRatio"] = volume_ratio

            # Fields not provided by the hotlist at all
            # PE ratio
            pe = q.get("pe")
            if pe is not None:
                row["pe"] = pe
            # Total market value (from EastMoney f20)
            tmv = q.get("totalMarketValue")
            if tmv is not None:
                row["totalMarketValue"] = tmv
                row["totalMV"] = tmv

        mf = flow_by_code.get(code)
        if mf:
            row["moneyFlow"] = {k: v for k, v in mf.items() if k != "code"}
            row["zlje"] = mf.get("mainNetInflow", 0)
            source = str(mf.get("moneyFlowSource") or "unknown")
            estimated = bool(mf.get("moneyFlowEstimated", source == "estimated_l1"))
            row["moneyFlowSource"] = source
            row["moneyFlowEstimated"] = estimated
            row["capitalFlowSource"] = source
            row["capitalFlowConfidence"] = str(
                mf.get("capitalFlowConfidence") or ("low" if estimated else "unknown")
            )


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
        for field in ("price", "pctChange", "volume", "amount", "turnover", "turnoverRate", "heat"):
            if field in stock:
                row[field] = stock[field]

        if "pctChange" in row:
            row["change"] = row["pctChange"]
        if "amount" in row:
            row["turnover"] = row["amount"]
        if "turnoverRate" not in row and "turnover" in stock:
            row["turnoverRate"] = stock["turnover"]
        if "heat" in row:
            row["hotness"] = row["heat"]

        # Themes from the market_context.themes dict keyed by code
        themes = market_context.themes.get(code)
        if themes is not None:
            row["themes"] = themes
        elif "themes" in stock:
            row["themes"] = stock["themes"]

        stock_rows.append(row)

    # Enrich stock rows with quote-derived fields
    _enrich_stock_rows_from_quotes(stock_rows, market_context.quotes, market_context.money_flow)

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

        row = {
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
        for field in SECTOR_FACTOR_FIELDS:
            if field in sector:
                row[field] = sector[field]
        sector_rows.append(row)

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
