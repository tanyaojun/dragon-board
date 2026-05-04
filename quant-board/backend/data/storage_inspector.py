from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any


def inspect_storage(path: str | Path) -> dict[str, Any]:
    root = Path(path)
    db_paths = sorted(root.glob("*.db")) if root.is_dir() else [root]
    return {"root": str(root), "databases": [_inspect_database(db_path) for db_path in db_paths if db_path.exists()]}


def _inspect_database(path: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "name": path.name,
        "path": str(path),
        "sizeBytes": path.stat().st_size,
        "tables": {},
        "jsonFields": {},
    }
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        page_count = _pragma_int(conn, "page_count")
        freelist_count = _pragma_int(conn, "freelist_count")
        page_size = _pragma_int(conn, "page_size")
        report["pageCount"] = page_count
        report["freePageCount"] = freelist_count
        report["pageSize"] = page_size
        report["freeBytes"] = freelist_count * page_size
        tables = [
            str(row["name"])
            for row in conn.execute("select name from sqlite_master where type='table' order by name").fetchall()
        ]
        for table in tables:
            count = conn.execute(f'select count(*) as count from "{table}"').fetchone()["count"]
            report["tables"][table] = {"rowCount": int(count)}
            for column in _json_columns(conn, table):
                row = conn.execute(
                    f'select count("{column}") as count, sum(length("{column}")) as total, max(length("{column}")) as max_len from "{table}"'
                ).fetchone()
                total = int(row["total"] or 0)
                if total <= 0:
                    continue
                report["jsonFields"][f"{table}.{column}"] = {
                    "count": int(row["count"] or 0),
                    "totalBytes": total,
                    "maxBytes": int(row["max_len"] or 0),
                }
    return report


def _pragma_int(conn: sqlite3.Connection, name: str) -> int:
    return int(conn.execute(f"pragma {name}").fetchone()[0] or 0)


def _json_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f'pragma table_info("{table}")').fetchall()
    return [
        str(row["name"])
        for row in rows
        if str(row["name"]).endswith("_json") or str(row["name"]) in {"payload", "payload_json"}
    ]
