from __future__ import annotations

import pytest

from backend.data.schemas import SnapshotIngestRequest
from backend.data.snapshot_ingest_normalizer import normalize_snapshot_ingest


def _bundle_without_stock_rows() -> dict:
    """正式 half_hour 槽位：股票行为空，但 sector 与 payload 有部分数据。"""
    return {
        "items": [
            {
                "id": "half_hour:2026-08-03:15:00",
                "type": "half_hour",
                "tradingDate": "2026-08-03",
                "slotTime": "15:00",
                "timestamp": 1785751200000,
                "payload": {"sectors": [{"themeId": "T1"}]},
            }
        ],
        "frames": [
            {
                "snapshotId": "half_hour:2026-08-03:15:00",
                "type": "half_hour",
                "tradingDate": "2026-08-03",
                "slotTime": "15:00",
                "timestamp": 1785751200000,
                "stockRowCount": 0,
                "sectorRowCount": 5,
            }
        ],
        "stockRows": [],
        "sectorRows": [
            {
                "snapshotId": "half_hour:2026-08-03:15:00",
                "entityType": "hot_theme",
                "entityKey": "T1",
            }
        ],
        "snapshotId": "half_hour:2026-08-03:15:00",
    }


def test_normalizer_keeps_partial_data_when_hotlist_empty() -> None:
    """热榜为空但有 sector/payload 时，必须保存并打标记，而不是整批拒写。"""
    request = SnapshotIngestRequest(
        dataset_id="dragonboard_live",
        bundle=_bundle_without_stock_rows(),
        source="quantboard_backend_collector",
    )
    dataset, records, frames, stock_rows, sector_rows, key = normalize_snapshot_ingest(
        request
    )
    assert len(frames) == 1
    assert len(sector_rows) == 1
    assert len(stock_rows) == 0
    assert "empty_hotlist_with_partial_data" in frames[0].get("qualityFlags", [])
    assert "empty_hotlist_with_partial_data" in records[0].get("qualityFlags", [])


def test_normalizer_still_requires_snapshot_identity() -> None:
    """快照身份缺失仍是硬错误（属于合同校验，不是质量门禁）。"""
    bundle = _bundle_without_stock_rows()
    bundle["frames"][0]["snapshotId"] = ""
    bundle["items"][0]["id"] = ""
    request = SnapshotIngestRequest(
        dataset_id="dragonboard_live",
        bundle=bundle,
        source="quantboard_backend_collector",
    )
    with pytest.raises(ValueError):
        normalize_snapshot_ingest(request)


def test_normalizer_still_requires_records() -> None:
    """records 缺失仍是硬错误（数据完整性，不属于可降级质量项）。"""
    bundle = _bundle_without_stock_rows()
    bundle["items"] = []
    request = SnapshotIngestRequest(
        dataset_id="dragonboard_live",
        bundle=bundle,
        source="quantboard_backend_collector",
    )
    with pytest.raises(ValueError):
        normalize_snapshot_ingest(request)
