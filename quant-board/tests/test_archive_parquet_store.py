from __future__ import annotations

from pathlib import Path

import pytest


def test_parquet_store_writes_manifest_and_reads_rows(tmp_path: Path) -> None:
    from backend.data.archive.parquet_store import ParquetStore

    store = ParquetStore(tmp_path)
    rows = [{"code": "000001", "rank": 1, "themes": ["bank"], "value": 1.25}]

    result = store.write_table("stock_rows", rows)

    assert result["name"] == "stock_rows.parquet"
    assert result["rows"] == 1
    assert result["bytes"] > 0
    assert len(result["sha256"]) == 64
    assert store.read_table("stock_rows") == rows


def test_parquet_store_rejects_empty_rows(tmp_path: Path) -> None:
    from backend.data.archive.parquet_store import ParquetStore

    store = ParquetStore(tmp_path)

    with pytest.raises(ValueError, match="archive_empty_table"):
        store.write_table("stock_rows", [])
