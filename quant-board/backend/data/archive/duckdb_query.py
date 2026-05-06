from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.data.archive.parquet_store import ParquetStore


class ArchiveQueryError(RuntimeError):
    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details

    def to_error(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), **self.details}


ALLOWED_FILTERS = {
    "stock_rows": {"datasetId", "snapshotId", "type", "tradingDate", "code", "slotTime", "__startDate", "__endDate", "__beforeTradingDate"},
    "sector_rows": {"datasetId", "snapshotId", "type", "tradingDate", "entityType", "entityKey", "__startDate", "__endDate", "__beforeTradingDate"},
    "trades": {"backtestRunId", "backtest_run_id", "code", "side"},
    "equity_curve": {"backtestRunId", "backtest_run_id"},
    "signals": {"backtestRunId", "backtest_run_id", "code", "signal"},
}


class DuckDBArchiveQuery:
    def read_table(
        self,
        parquet_path: Path,
        *,
        table: str | None = None,
        filters: dict[str, Any] | None = None,
        sort: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if not parquet_path.is_file():
            raise ArchiveQueryError("archive_file_missing", "archive parquet file is missing", file=str(parquet_path))
        table_name = table or parquet_path.stem
        self._validate_filters(table_name, filters or {})
        try:
            import duckdb
        except ModuleNotFoundError:
            return self._fallback_read(parquet_path, table=table_name, filters=filters, sort=sort, limit=limit, offset=offset)

        clauses: list[str] = []
        values: list[Any] = []
        for key, value in (filters or {}).items():
            if value is None or value == "":
                continue
            if key == "__startDate":
                clauses.append('"tradingDate" >= ?')
                values.append(value)
            elif key == "__endDate":
                clauses.append('"tradingDate" <= ?')
                values.append(value)
            elif key == "__beforeTradingDate":
                clauses.append('"tradingDate" < ?')
                values.append(value)
            elif isinstance(value, list):
                if not value:
                    continue
                placeholders = ", ".join(["?"] * len(value))
                clauses.append(f'"{key}" in ({placeholders})')
                values.extend(value)
            else:
                clauses.append(f'"{key}" = ?')
                values.append(value)
        where_sql = f" where {' and '.join(clauses)}" if clauses else ""
        order = "asc" if sort == "asc" else "desc"
        limit_sql = " limit ?" if limit is not None and limit > 0 else ""
        offset_sql = " offset ?" if offset else ""
        params = [*values]
        if limit_sql:
            params.append(int(limit or 0))
        if offset_sql:
            params.append(int(offset))
        try:
            query = f"select * from read_parquet(?) {where_sql} order by timestamp {order}, rank asc{limit_sql}{offset_sql}"
            rows = duckdb.execute(query, [str(parquet_path), *params]).fetchdf().to_dict("records")
        except Exception:
            return self._fallback_read(parquet_path, table=table_name, filters=filters, sort=sort, limit=limit, offset=offset)
        return [_clean_nan(row) for row in rows]

    def _fallback_read(
        self,
        parquet_path: Path,
        *,
        table: str,
        filters: dict[str, Any] | None = None,
        sort: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = ParquetStore(parquet_path.parent).read_table(parquet_path.stem)
        for key, value in (filters or {}).items():
            if value is None or value == "":
                continue
            if key == "__startDate":
                rows = [row for row in rows if str(row.get("tradingDate") or "") >= str(value)]
            elif key == "__endDate":
                rows = [row for row in rows if str(row.get("tradingDate") or "") <= str(value)]
            elif key == "__beforeTradingDate":
                rows = [row for row in rows if str(row.get("tradingDate") or "") < str(value)]
            elif isinstance(value, list):
                allowed = set(value)
                rows = [row for row in rows if row.get(key) in allowed]
            else:
                rows = [row for row in rows if row.get(key) == value]
        rows = sorted(rows, key=lambda row: (row.get("timestamp") or 0, row.get("rank") or 0), reverse=sort != "asc")
        if offset:
            rows = rows[offset:]
        if limit is not None and limit > 0:
            rows = rows[:limit]
        return rows

    def _validate_filters(self, table: str, filters: dict[str, Any]) -> None:
        allowed = ALLOWED_FILTERS.get(table)
        if allowed is None:
            raise ArchiveQueryError("archive_query_table_unsupported", "archive query table is unsupported", table=table)
        unsupported = sorted(key for key, value in filters.items() if value not in (None, "") and key not in allowed)
        if unsupported:
            raise ArchiveQueryError(
                "archive_query_filter_unsupported",
                "archive query filter is unsupported",
                table=table,
                filters=unsupported,
            )


def _clean_nan(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        try:
            if value != value:
                cleaned[key] = None
                continue
        except TypeError:
            pass
        cleaned[key] = value
    return cleaned
