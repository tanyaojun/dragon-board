from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, text

from backend.data.json_codec import COMPRESSED_TEXT_PREFIX, DEFAULT_COMPRESSION_THRESHOLD, dumps_json_field


DEFAULT_JSON_TABLES = {
    "datasets": ["snapshot_types_json", "metadata_json"],
    "snapshot_records": ["quality_flags_json"],
    "snapshot_frames": [
        "quality_flags_json",
        "metadata_json",
        "market_stats_json",
        "sentiment_json",
        "money_flow_json",
        "indices_json",
        "limit_summary_json",
        "rotation_summary_json",
    ],
    "snapshot_stock_rows": ["depth10_json", "themes_json"],
    "snapshot_sector_rows": ["metadata_json"],
    "golden_ranktrend_cases": ["input_json", "expected_json"],
    "backtest_runs": ["request_json", "result_json"],
    "backtest_trades": ["fill_detail_json"],
    "backtest_signals": ["reasons_json", "risk_flags_json"],
    "backtest_quality_reports": ["missing_fields_json", "nan_counts_json", "inf_counts_json", "warnings_json"],
    "optimization_runs": ["request_json", "result_json"],
}


def compact_json_fields(
    database_url: str,
    *,
    apply: bool = False,
    threshold: int = DEFAULT_COMPRESSION_THRESHOLD,
    batch_size: int = 500,
    vacuum: bool = False,
) -> dict[str, Any]:
    engine = create_engine(database_url, connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {})
    fields: list[dict[str, Any]] = []
    updated_rows = 0
    try:
        with engine.begin() as conn:
            tables = _table_names(conn)
            for table, columns in DEFAULT_JSON_TABLES.items():
                if table not in tables:
                    continue
                actual_columns = _column_names(conn, table)
                for column in columns:
                    if column not in actual_columns:
                        continue
                    stats = _field_stats(conn, table, column, threshold, apply=apply, batch_size=batch_size)
                    fields.append(stats)
                    updated_rows += int(stats["updatedRows"])
        if apply and vacuum:
            with engine.connect() as conn:
                conn.execute(text("VACUUM"))
    finally:
        engine.dispose()
    return {
        "ok": True,
        "applied": bool(apply),
        "vacuumed": bool(apply and vacuum),
        "threshold": threshold,
        "updatedRows": updated_rows,
        "fields": fields,
    }


def _field_stats(conn, table: str, column: str, threshold: int, *, apply: bool, batch_size: int) -> dict[str, Any]:
    rows = conn.execute(
        text(f'select rowid as rowid, "{column}" as value from "{table}" where "{column}" is not null')
    ).mappings()
    before = 0
    after = 0
    candidates: list[tuple[int, str]] = []
    updated = 0
    for row in rows:
        value = str(row["value"] or "")
        before += len(value.encode("utf-8"))
        encoded = dumps_json_field(value, threshold=threshold)
        after += len(encoded.encode("utf-8"))
        if encoded != value and encoded.startswith(COMPRESSED_TEXT_PREFIX):
            candidates.append((int(row["rowid"]), encoded))
        if apply and len(candidates) >= batch_size:
            updated += _update_batch(conn, table, column, candidates)
            candidates = []
    if apply and candidates:
        updated += _update_batch(conn, table, column, candidates)
    return {
        "field": f"{table}.{column}",
        "bytesBefore": before,
        "estimatedBytesAfter": after,
        "candidateRows": len(candidates) if not apply else updated,
        "updatedRows": updated,
    }


def _update_batch(conn, table: str, column: str, rows: list[tuple[int, str]]) -> int:
    for rowid, value in rows:
        conn.execute(
            text(f'update "{table}" set "{column}" = :value where rowid = :rowid'),
            {"value": value, "rowid": rowid},
        )
    return len(rows)


def _table_names(conn) -> set[str]:
    return {str(row[0]) for row in conn.execute(text("select name from sqlite_master where type='table'")).fetchall()}


def _column_names(conn, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(text(f'pragma table_info("{table}")')).fetchall()}
