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


def test_write_table_encodes_nested_datetime_instead_of_raising(tmp_path: Path) -> None:
    """嵌套结构含 datetime 时降级为 isoformat 字符串，不炸 json.dumps（2026-07-29 实测回归）。"""
    from datetime import datetime

    from backend.data.archive.parquet_store import ParquetStore

    store = ParquetStore(tmp_path, compression="zstd")
    rows = [
        {
            "id": "r1",
            "nested": {"slotTime": datetime(2026, 7, 29, 15, 0, 0), "note": "x"},
            "items": [datetime(2026, 7, 29, 9, 30, 0), {"k": 1}],
        }
    ]
    written = store.write_table("records", rows)
    assert written["rows"] == 1

    decoded = store.read_table("records")
    assert decoded[0]["nested"]["slotTime"] == "2026-07-29T15:00:00"
    assert decoded[0]["items"] == ["2026-07-29T09:30:00", {"k": 1}]
