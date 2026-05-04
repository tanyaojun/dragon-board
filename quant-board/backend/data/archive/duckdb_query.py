from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.data.archive.parquet_store import ParquetStore


class DuckDBArchiveQuery:
    def read_table(
        self,
        parquet_path: Path,
        *,
        filters: dict[str, Any] | None = None,
        sort: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        try:
            import duckdb
        except ModuleNotFoundError:
            return self._fallback_read(parquet_path, filters=filters, sort=sort, limit=limit, offset=offset)

        clauses: list[str] = []
        values: list[Any] = []
        for key, value in (filters or {}).items():
            if value is None or value == "":
                continue
            if isinstance(value, list):
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
            return self._fallback_read(parquet_path, filters=filters, sort=sort, limit=limit, offset=offset)
        return [_clean_nan(row) for row in rows]

    def _fallback_read(
        self,
        parquet_path: Path,
        *,
        filters: dict[str, Any] | None = None,
        sort: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        rows = ParquetStore(parquet_path.parent).read_table(parquet_path.stem)
        for key, value in (filters or {}).items():
            if value is None or value == "":
                continue
            if isinstance(value, list):
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
