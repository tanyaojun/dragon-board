from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.data.archive.manifest import sha256_file


class ParquetStore:
    def __init__(self, base_dir: Path, *, compression: str = "zstd") -> None:
        self.base_dir = Path(base_dir)
        self.compression = compression
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write_table(self, name: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            raise ValueError("archive_empty_table")
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ModuleNotFoundError as exc:
            raise RuntimeError("pyarrow is required for parquet archive; run pip install -r requirements.txt") from exc

        path = self._table_path(name)
        normalized = [_encode_nested_values(row) for row in rows]
        table = pa.Table.from_pylist(normalized)
        pq.write_table(table, path, compression=self.compression)
        return {
            "name": path.name,
            "path": str(path),
            "rows": len(rows),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    def read_table(self, name: str) -> list[dict[str, Any]]:
        path = self._table_path(name)
        if not path.exists():
            return []
        try:
            import pyarrow.parquet as pq
        except ModuleNotFoundError as exc:
            raise RuntimeError("pyarrow is required for parquet archive; run pip install -r requirements.txt") from exc
        rows = pq.read_table(path).to_pylist()
        return [_decode_nested_values(row) for row in rows]

    def _table_path(self, name: str) -> Path:
        table_name = name if name.endswith(".parquet") else f"{name}.parquet"
        return self.base_dir / table_name


def _encode_nested_values(row: dict[str, Any]) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (dict, list)):
            encoded[key] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            encoded[key] = value
    return encoded


def _decode_nested_values(row: dict[str, Any]) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, str) and value and value[0] in "[{":
            try:
                decoded[key] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        decoded[key] = value
    return decoded
