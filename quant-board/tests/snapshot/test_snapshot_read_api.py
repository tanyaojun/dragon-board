"""Snapshot read API tests: frames, records, rank-series, stock-rows,
sector-rows, and snapshot-cache behaviour.

Extracted from tests/test_quant_board.py.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.main import app


def test_snapshot_stock_rows_api_supports_field_projection() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_projection_{suffix}"
    snapshot_id = f"half_hour:2026-04-21:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": f"[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-21",
                    "slotTime": "10:00",
                    "timestamp": 1776746400000,
                    "hotlist": [
                        {"code": "600001", "name": "样本A", "rank": 1, "price": 10, "avgRankNum": 3.5},
                        {"code": "600002", "name": "样本B", "rank": 2, "price": 11, "avgRankNum": 8.2},
                    ],
                },
            }
        ],
    }
    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"projection-{suffix}",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    full = client.get(
        "/api/snapshots/stock-rows",
        params={"dataset_id": dataset_id, "snapshot_id": snapshot_id},
    )
    assert full.status_code == 200, full.text
    full_row = full.json()["rows"][0]
    assert "name" in full_row
    assert "avgRankNum" in full_row

    projected = client.get(
        "/api/snapshots/stock-rows",
        params={
            "dataset_id": dataset_id,
            "snapshot_id": snapshot_id,
            "fields": "code,tradingDate,slotTime,avgRankNum",
        },
    )
    assert projected.status_code == 200, projected.text
    assert projected.json()["rows"] == [
        {"code": "600001", "tradingDate": "2026-04-21", "slotTime": "10:00", "avgRankNum": 3.5},
        {"code": "600002", "tradingDate": "2026-04-21", "slotTime": "10:00", "avgRankNum": 8.2},
    ]


def test_snapshot_stock_rows_include_analysis_attaches_persisted_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """include_analysis=true 把 snapshot_analysis 落库产物按 code 注入行（2026-09-21）。

    行情列表观察六列首屏同步投影的读口：帧池种子行带上帧内 analyze 产物后，
    前端不必等异步增强即可显示。fail-visible 合同：无落库产物的行不加 analysis 键
    （不伪造空产物）；仓库无 load_snapshot_analysis（SQLite 本地/测试态）时
    analysisAttached=0 且不报错。
    """
    rows = [
        {"code": "600001", "snapshotId": "half_hour:2026-04-21:10:00", "name": "样本A", "rank": 1},
        {"code": "600002", "snapshotId": "half_hour:2026-04-21:10:00", "name": "样本B", "rank": 2},
    ]
    persisted = {"600001": {"observation": {"lifecycle": {"stage": "crowded"}}}}
    load_calls: list[tuple[str, str]] = []
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_analysis_attach_{suffix}"

    class FakeDataset:
        id = dataset_id
        frame_count = 1
        snapshot_count = 1
        stock_row_count = len(rows)
        sector_row_count = 0

    class FakeRepo:
        def get_dataset(self, dataset_id):
            return FakeDataset()

        def dataset_to_dict(self, dataset):
            return {"id": dataset.id}

        def list_snapshot_stock_rows(self, dataset_id, **kwargs):
            return {"rows": [dict(row) for row in rows], "source": "mongodb"}

        def load_snapshot_analysis(self, dataset_id, snapshot_id, codes=None):
            load_calls.append((dataset_id, snapshot_id))
            return dict(persisted)

    class RepoWithoutAnalysis:
        """模拟 SQLite 本地/测试态仓库：不实现 snapshot_analysis 读方法。"""

        def get_dataset(self, dataset_id):
            return FakeDataset()

        def dataset_to_dict(self, dataset):
            return {"id": dataset.id}

        def list_snapshot_stock_rows(self, dataset_id, **kwargs):
            return {"rows": [dict(row) for row in rows], "source": "sqlite"}

    monkeypatch.setattr(
        "backend.main.create_repository", lambda db, enable_backup=True: FakeRepo()
    )
    client = TestClient(app)

    attached = client.get(
        "/api/snapshots/stock-rows",
        params={
            "dataset_id": dataset_id,
            "snapshot_id": "half_hour:2026-04-21:10:00",
            "include_analysis": True,
        },
    )
    assert attached.status_code == 200, attached.text
    body = attached.json()
    assert load_calls == [(dataset_id, "half_hour:2026-04-21:10:00")]
    assert body["analysisAttached"] == 1
    assert body["rows"][0]["analysis"] == persisted["600001"]
    assert "analysis" not in body["rows"][1]

    bare = client.get(
        "/api/snapshots/stock-rows",
        params={
            "dataset_id": dataset_id,
            "snapshot_id": "half_hour:2026-04-21:10:00",
        },
    )
    assert bare.status_code == 200, bare.text
    assert bare.json()["analysisAttached"] == 0
    assert all("analysis" not in row for row in bare.json()["rows"])

    monkeypatch.setattr(
        "backend.main.create_repository",
        lambda db, enable_backup=True: RepoWithoutAnalysis(),
    )
    without_loader = client.get(
        "/api/snapshots/stock-rows",
        params={
            "dataset_id": dataset_id,
            # 与 attached 请求区分缓存 key：本机 Redis 存活时同 key 会命中上一响应
            "snapshot_id": "half_hour:2026-04-21:10:30",
            "include_analysis": True,
        },
    )
    assert without_loader.status_code == 200, without_loader.text
    assert without_loader.json()["analysisAttached"] == 0
    assert all("analysis" not in row for row in without_loader.json()["rows"])


def test_snapshot_frames_api_reads_sqlite_frame_bundles() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_sqlite_read_{suffix}"
    snapshot_id = f"half_hour:2026-04-21:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": "[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {"hotlist": [{"code": "600001", "name": "样本A", "rank": 1}]},
            }
        ],
        "frames": [
            {
                "id": snapshot_id,
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "stockRowCount": 1,
                "sectorRowCount": 1,
                "rotationSummary": {"stage": "start"},
            }
        ],
        "stockRows": [
            {
                "id": f"{snapshot_id}:600001",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "code": "600001",
                "name": "样本A",
                "rank": 1,
                "price": 10,
            }
        ],
        "sectorRows": [
            {
                "id": f"{snapshot_id}:sector:AI",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "entityType": "sector",
                "entityKey": "AI",
                "entityName": "人工智能",
                "rank": 1,
                "strength": 90,
            }
        ],
    }

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"sqlite-read-key-{suffix}",
            "tradingDate": "2026-04-21",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    response = client.get(
        "/api/snapshots/frames",
        params={
            "dataset_id": dataset_id,
            "snapshot_type": "half_hour",
            "trading_date": "2026-04-21",
            "allowed_capture_modes": "real_time",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "sqlite"
    assert body["count"] == 1
    frame = body["frames"][0]
    assert frame["snapshotId"] == snapshot_id
    assert frame["hotlist"][0]["code"] == "600001"
    assert frame["stocks"] == frame["hotlist"]
    assert frame["sectors"][0]["name"] == "人工智能"


def test_snapshot_frames_api_ranktrend_projection_returns_lightweight_hotlist() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_ranktrend_projection_{suffix}"
    snapshot_id = f"half_hour:2026-04-21:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": "[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {"hotlist": [{"code": "600001", "name": "样本A", "rank": 1}]},
            }
        ],
        "frames": [
            {
                "id": snapshot_id,
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "stockRowCount": 1,
                "sectorRowCount": 1,
            }
        ],
        "stockRows": [
            {
                "id": f"{snapshot_id}:600001",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "code": "600001",
                "name": "样本A",
                "rank": 1,
                "price": 10,
                "zlje": 1234,
            }
        ],
        "sectorRows": [
            {
                "id": f"{snapshot_id}:sector:AI",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "entityType": "sector",
                "entityKey": "AI",
                "entityName": "人工智能",
                "rank": 1,
            }
        ],
    }

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"ranktrend-projection-key-{suffix}",
            "tradingDate": "2026-04-21",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    response = client.get(
        "/api/snapshots/frames",
        params={
            "dataset_id": dataset_id,
            "snapshot_type": "half_hour",
            "trading_date": "2026-04-21",
            "allowed_capture_modes": "real_time",
            "projection": "ranktrend",
        },
    )
    assert response.status_code == 200, response.text
    frame = response.json()["frames"][0]
    assert frame["hotlist"] == [{
        "code": "600001",
        "name": "样本A",
        "rank": 1,
        "avgRankNum": None,
        "change": None,
        "volumeRatio": None,
        "zlje": 1234,
        "zljzb": None,
    }]
    assert frame["rows"] == frame["hotlist"]
    assert frame["sectors"] == []


def test_ranktrend_rank_series_api_returns_compact_rank_history() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_rank_series_{suffix}"
    first_snapshot_id = f"half_hour:2026-04-21:1000:{suffix}"
    second_snapshot_id = f"half_hour:2026-04-21:1030:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            {
                "id": first_snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": "[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {"hotlist": []},
            },
            {
                "id": second_snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:30",
                "timestamp": 1776748200000,
                "displayKey": "[半小时快照] 2026-04-21 10:30",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {"hotlist": []},
            },
        ],
        "frames": [
            {
                "id": first_snapshot_id,
                "snapshotId": first_snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": "[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "stockRowCount": 2,
                "sectorRowCount": 0,
            },
            {
                "id": second_snapshot_id,
                "snapshotId": second_snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:30",
                "timestamp": 1776748200000,
                "displayKey": "[半小时快照] 2026-04-21 10:30",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "stockRowCount": 2,
                "sectorRowCount": 0,
            },
        ],
        "stockRows": [
            {
                "id": f"{first_snapshot_id}:600001",
                "snapshotId": first_snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "code": "600001",
                "name": "样本A",
                "rank": 1,
                "zlje": 1234,
            },
            {
                "id": f"{first_snapshot_id}:600002",
                "snapshotId": first_snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "code": "600002",
                "name": "样本B",
                "rank": 2,
            },
            {
                "id": f"{second_snapshot_id}:600001",
                "snapshotId": second_snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:30",
                "timestamp": 1776748200000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "code": "600001",
                "name": "样本A",
                "rank": 3,
            },
            {
                "id": f"{second_snapshot_id}:600002",
                "snapshotId": second_snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:30",
                "timestamp": 1776748200000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "code": "600002",
                "name": "样本B",
                "rank": 1,
            },
        ],
        "sectorRows": [],
    }

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"rank-series-key-{suffix}",
            "tradingDate": "2026-04-21",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    response = client.get(
        "/api/ranktrend/rank-series",
        params={
            "dataset_id": dataset_id,
            "snapshot_type": "half_hour",
            "trading_date": "2026-04-21",
            "allowed_capture_modes": "real_time",
            "codes": "600001,600002",
            "sort": "asc",
            "limit": 10,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "sqlite"
    assert body["count"] == 2
    assert body["frames"][0]["snapshotId"] == first_snapshot_id
    assert body["frames"][0]["ranks"] == {"600001": 1, "600002": 2}
    assert body["frames"][0]["totalCount"] == 2
    assert "hotlist" not in body["frames"][0]
    assert "rows" not in body["frames"][0]


def test_ranktrend_rank_series_api_requires_codes() -> None:
    response = TestClient(app).get(
        "/api/ranktrend/rank-series",
        params={"dataset_id": "dragonboard_live", "snapshot_type": "half_hour"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "codes is required for rank-series queries"


def test_ranktrend_attention_rank_series_requires_mongodb() -> None:
    response = TestClient(app).get(
        "/api/ranktrend/rank-series",
        params={
            "dataset_id": "dragonboard_live",
            "snapshot_type": "half_hour",
            "codes": "600001",
            "rank_basis": "attention",
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "attention rank series requires mongodb"


def test_ranktrend_rank_series_api_filters_codes() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_rank_series_codes_{suffix}"
    snapshot_id = f"half_hour:2026-04-21:1000:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": "[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {"hotlist": []},
            }
        ],
        "frames": [
            {
                "id": snapshot_id,
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "stockRowCount": 3,
            }
        ],
        "stockRows": [
            {
                "id": f"{snapshot_id}:600001",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "code": "600001",
                "name": "样本A",
                "rank": 1,
            },
            {
                "id": f"{snapshot_id}:600002",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "code": "600002",
                "name": "样本B",
                "rank": 2,
            },
            {
                "id": f"{snapshot_id}:600003",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "code": "600003",
                "name": "样本C",
                "rank": 3,
            },
        ],
        "sectorRows": [],
    }

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"rank-series-codes-key-{suffix}",
            "tradingDate": "2026-04-21",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    response = client.get(
        "/api/ranktrend/rank-series",
        params={
            "dataset_id": dataset_id,
            "snapshot_type": "half_hour",
            "trading_date": "2026-04-21",
            "codes": "600001,600003",
        },
    )

    assert response.status_code == 200, response.text
    frame = response.json()["frames"][0]
    assert frame["ranks"] == {"600001": 1, "600003": 3}
    assert frame["totalCount"] == 3


def test_ranktrend_rank_series_api_uses_per_code_window_not_global_frame_window() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_rank_series_code_window_{suffix}"
    frames = []
    items = []
    stock_rows = []

    for index in range(8):
        slot = f"10:{index:02d}"
        snapshot_id = f"half_hour:2026-04-21:{slot}:{suffix}"
        timestamp = 1776746400000 + index * 30 * 60 * 1000
        items.append(
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": slot,
                "timestamp": timestamp,
                "displayKey": f"[半小时快照] 2026-04-21 {slot}",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {"hotlist": []},
            }
        )
        frames.append(
            {
                "id": snapshot_id,
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": slot,
                "timestamp": timestamp,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "stockRowCount": 200,
            }
        )
        stock_rows.append(
            {
                "id": f"{snapshot_id}:600001",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": slot,
                "timestamp": timestamp,
                "captureMode": "real_time",
                "code": "600001",
                "name": "连续样本",
                "rank": 100 - index,
            }
        )
        if index >= 5:
            stock_rows.append(
                {
                    "id": f"{snapshot_id}:600601",
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-04-21",
                    "slotTime": slot,
                    "timestamp": timestamp,
                    "captureMode": "real_time",
                    "code": "600601",
                    "name": "方正科技",
                    "rank": 80 - index,
                }
            )

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"rank-series-code-window-key-{suffix}",
            "tradingDate": "2026-04-21",
            "bundle": {
                "version": "v4",
                "tradingDate": "2026-04-21",
                "items": items,
                "frames": frames,
                "stockRows": stock_rows,
                "sectorRows": [],
            },
        },
    )
    assert ingest.status_code == 200, ingest.text

    response = client.get(
        "/api/ranktrend/rank-series",
        params={
            "dataset_id": dataset_id,
            "snapshot_type": "half_hour",
            "trading_date": "2026-04-21",
            "codes": "600001,600601",
            "sort": "asc",
            "limit": 5,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    frames_by_code = body["series"]
    assert [bar["rank"] for bar in frames_by_code["600001"]["bars"]] == [97, 96, 95, 94, 93]
    assert [bar["rank"] for bar in frames_by_code["600601"]["bars"]] == [75, 74, 73]
    assert frames_by_code["600001"]["totalCount"] == 8
    assert frames_by_code["600601"]["totalCount"] == 3
    assert body["frames"][-1]["ranks"]["600001"] == 93
    assert body["frames"][-1]["ranks"]["600601"] == 73
    # per-code bars carry totalCount from the frame
    for bar in frames_by_code["600001"]["bars"]:
        assert bar.get("totalCount") == 200

    desc_response = client.get(
        "/api/ranktrend/rank-series",
        params={
            "dataset_id": dataset_id,
            "snapshot_type": "half_hour",
            "trading_date": "2026-04-21",
            "codes": "600001",
            "sort": "desc",
            "limit": 5,
        },
    )

    assert desc_response.status_code == 200, desc_response.text
    desc_series = desc_response.json()["series"]
    assert [bar["rank"] for bar in desc_series["600001"]["bars"]] == [97, 96, 95, 94, 93]
    assert desc_series["600001"]["totalCount"] == 8


def test_snapshot_frames_api_uses_snapshot_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.data.cache import snapshot_cache

    class FakeCache:
        def __init__(self) -> None:
            self.values: dict[str, dict] = {}
            self.get_count = 0
            self.set_count = 0
            self.registered: list[tuple[str, list[str]]] = []
            self.generations: dict[str, int] = {}

        def get_response(self, key: str):
            self.get_count += 1
            return self.values.get(key)

        def set_response(self, key: str, response: dict) -> None:
            self.set_count += 1
            self.values[key] = {**response, "cache": {"hit": True, "store": "redis"}}

        def register_dependencies(self, response_key: str, index_keys: list[str]) -> None:
            self.registered.append((response_key, index_keys))

        def get_generation(self, key: str) -> int:
            return self.generations.get(key, 0)

        def bump_generation(self, key: str) -> int:
            self.generations[key] = self.get_generation(key) + 1
            return self.generations[key]

    fake_cache = FakeCache()
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: fake_cache)

    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_cache_read_{suffix}"
    snapshot_id = f"half_hour:2026-04-21:{suffix}"
    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"cache-read-key-{suffix}",
            "tradingDate": "2026-04-21",
            "bundle": {
                "version": "v4",
                "tradingDate": "2026-04-21",
                "items": [
                    {
                        "id": snapshot_id,
                        "type": "half_hour",
                        "tradingDate": "2026-04-21",
                        "slotTime": "10:00",
                        "timestamp": 1776746400000,
                        "displayKey": "[半小时快照] 2026-04-21 10:00",
                        "captureMode": "real_time",
                        "source": "browser_runtime",
                        "payload": {"hotlist": [{"code": "600001", "name": "样本A", "rank": 1}]},
                    }
                ],
                "frames": [
                    {
                        "id": snapshot_id,
                        "snapshotId": snapshot_id,
                        "type": "half_hour",
                        "tradingDate": "2026-04-21",
                        "slotTime": "10:00",
                        "timestamp": 1776746400000,
                        "captureMode": "real_time",
                        "source": "browser_runtime",
                    }
                ],
                "stockRows": [],
                "sectorRows": [],
            },
        },
    )
    assert ingest.status_code == 200, ingest.text

    params = {
        "dataset_id": dataset_id,
        "snapshot_type": "half_hour",
        "trading_date": "2026-04-21",
        "allowed_capture_modes": "real_time",
    }
    first = client.get("/api/snapshots/frames", params=params)
    second = client.get("/api/snapshots/frames", params=params)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["cache"]["hit"] is False
    assert second.json()["cache"]["hit"] is True
    assert fake_cache.set_count == 1
    assert fake_cache.registered


def test_snapshot_detail_read_apis_use_sqlite() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_sqlite_detail_{suffix}"
    snapshot_id = f"half_hour:2026-04-22:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-22",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:30",
                "timestamp": 1776834600000,
                "displayKey": "[半小时快照] 2026-04-22 10:30",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {"hotlist": [{"code": "600010", "name": "样本C", "rank": 1}]},
            }
        ],
        "frames": [
            {
                "id": snapshot_id,
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:30",
                "timestamp": 1776834600000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "stockRowCount": 1,
                "sectorRowCount": 1,
            }
        ],
        "stockRows": [
            {
                "id": f"{snapshot_id}:600010",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:30",
                "timestamp": 1776834600000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "code": "600010",
                "name": "样本C",
                "rank": 1,
                "volumeRatio": 2.5,
                "themeContribution": 15.5,
                "themeRole": "leader",
                "themeExposureWeight": 1,
                "themeRiskFlags": ["riskPenalty:2"],
            }
        ],
        "sectorRows": [
            {
                "id": f"{snapshot_id}:hot_theme:robot",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:30",
                "timestamp": 1776834600000,
                "captureMode": "real_time",
                "source": "browser_runtime",
                "entityType": "hot_theme",
                "entityKey": "robot",
                "entityName": "机器人",
                "rank": 1,
                "momentumScore": 77,
                "crowdingRisk": 18,
                "rotationState": "mainline",
                "themeQualityFlags": [{"code": "low_sample"}],
            }
        ],
    }

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"sqlite-detail-key-{suffix}",
            "tradingDate": "2026-04-22",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    records = client.get(
        "/api/snapshots/records",
        params={"dataset_id": dataset_id, "snapshot_type": "half_hour", "trading_date": "2026-04-22"},
    )
    assert records.status_code == 200, records.text
    assert records.json()["records"][0]["id"] == snapshot_id

    record = client.get(f"/api/snapshots/records/{snapshot_id}", params={"dataset_id": dataset_id})
    assert record.status_code == 200, record.text
    assert record.json()["record"]["payload"] == {}
    assert record.json()["record"]["source"] == "browser_runtime"

    stocks = client.get("/api/snapshots/stock-rows", params={"dataset_id": dataset_id, "snapshot_id": snapshot_id})
    assert stocks.status_code == 200, stocks.text
    assert stocks.json()["rows"][0]["code"] == "600010"
    assert stocks.json()["rows"][0]["volumeRatio"] == 2.5
    assert stocks.json()["rows"][0]["themeContribution"] == 15.5
    assert stocks.json()["rows"][0]["themeRole"] == "leader"
    assert stocks.json()["rows"][0]["themeRiskFlags"] == ["riskPenalty:2"]

    sectors = client.get("/api/snapshots/sector-rows", params={"dataset_id": dataset_id, "snapshot_id": snapshot_id})
    assert sectors.status_code == 200, sectors.text
    assert sectors.json()["rows"][0]["captureMode"] == "real_time"
    assert sectors.json()["rows"][0]["entityName"] == "机器人"
    assert sectors.json()["rows"][0]["momentumScore"] == 77
    assert sectors.json()["rows"][0]["rotationState"] == "mainline"
    assert sectors.json()["rows"][0]["themeQualityFlags"] == [{"code": "low_sample"}]

    counts = client.get("/api/snapshots/counts", params={"dataset_id": dataset_id})
    assert counts.status_code == 200, counts.text
    assert counts.json()["counts"] == {
        "snapshots": 1,
        "snapshot_frames": 1,
        "snapshot_stock_rows": 1,
        "snapshot_sector_rows": 1,
    }


def test_snapshot_detail_list_apis_use_snapshot_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.data.cache import snapshot_cache

    class FakeCache:
        def __init__(self) -> None:
            self.values: dict[str, dict] = {}
            self.set_count = 0
            self.generations: dict[str, int] = {}

        def get_response(self, key: str):
            return self.values.get(key)

        def set_response(self, key: str, response: dict) -> None:
            self.set_count += 1
            self.values[key] = {**response, "cache": {"hit": True, "store": "redis"}}

        def register_dependencies(self, response_key: str, index_keys: list[str]) -> None:
            return None

        def get_generation(self, key: str) -> int:
            return self.generations.get(key, 0)

        def bump_generation(self, key: str) -> int:
            self.generations[key] = self.get_generation(key) + 1
            return self.generations[key]

    fake_cache = FakeCache()
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: fake_cache)

    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_cache_detail_{suffix}"
    snapshot_id = f"half_hour:2026-04-23:{suffix}"
    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"cache-detail-key-{suffix}",
            "tradingDate": "2026-04-23",
            "bundle": {
                "version": "v4",
                "tradingDate": "2026-04-23",
                "items": [{"id": snapshot_id, "type": "half_hour", "tradingDate": "2026-04-23"}],
                "frames": [{"id": snapshot_id, "snapshotId": snapshot_id, "type": "half_hour", "tradingDate": "2026-04-23"}],
                "stockRows": [{"id": f"{snapshot_id}:600010", "snapshotId": snapshot_id, "type": "half_hour", "tradingDate": "2026-04-23", "code": "600010", "volume": 123}],
                "sectorRows": [{"id": f"{snapshot_id}:sector:AI", "snapshotId": snapshot_id, "type": "half_hour", "tradingDate": "2026-04-23", "entityType": "sector", "entityKey": "AI"}],
            },
        },
    )
    assert ingest.status_code == 200, ingest.text

    checks = [
        ("/api/snapshots/records", {"dataset_id": dataset_id, "snapshot_type": "half_hour", "trading_date": "2026-04-23"}),
        ("/api/snapshots/stock-rows", {"dataset_id": dataset_id, "snapshot_id": snapshot_id}),
        ("/api/snapshots/sector-rows", {"dataset_id": dataset_id, "snapshot_id": snapshot_id}),
    ]
    for path, params in checks:
        first = client.get(path, params=params)
        second = client.get(path, params=params)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["cache"]["hit"] is False
        assert second.json()["cache"]["hit"] is True


def test_snapshot_ingest_invalidates_snapshot_cache_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.data.cache import snapshot_cache

    class FakeCache:
        def __init__(self) -> None:
            self.invalidated: list[list[str]] = []
            self.generations: dict[str, int] = {}

        def get_response(self, key: str):
            return None

        def set_response(self, key: str, response: dict) -> None:
            return None

        def register_dependencies(self, response_key: str, index_keys: list[str]) -> None:
            return None

        def invalidate_indexes(self, index_keys: list[str]) -> None:
            self.invalidated.append(index_keys)

        def get_generation(self, key: str) -> int:
            return self.generations.get(key, 0)

        def bump_generation(self, key: str) -> int:
            self.generations[key] = self.get_generation(key) + 1
            return self.generations[key]

    fake_cache = FakeCache()
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: fake_cache)

    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_cache_invalidate_{suffix}"
    snapshot_id = f"half_hour:2026-04-24:{suffix}"
    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"cache-invalidate-key-{suffix}",
            "tradingDate": "2026-04-24",
            "bundle": {
                "version": "v4",
                "tradingDate": "2026-04-24",
                "items": [{"id": snapshot_id, "type": "half_hour", "tradingDate": "2026-04-24"}],
                "frames": [{"id": snapshot_id, "snapshotId": snapshot_id, "type": "half_hour", "tradingDate": "2026-04-24"}],
                "stockRows": [{"id": f"{snapshot_id}:600010", "snapshotId": snapshot_id, "type": "half_hour", "tradingDate": "2026-04-24", "code": "600010"}],
                "sectorRows": [{"id": f"{snapshot_id}:sector:AI", "snapshotId": snapshot_id, "type": "half_hour", "tradingDate": "2026-04-24", "entityType": "sector", "entityKey": "AI"}],
            },
        },
    )

    assert ingest.status_code == 200, ingest.text
    assert fake_cache.generations[
        f"hellobiga:dragon-board:local:snapshot:generation:{dataset_id}"
    ] == 1
    flattened = [key for group in fake_cache.invalidated for key in group]
    assert f"hellobiga:dragon-board:local:snapshot:index:dataset:{dataset_id}" in flattened
    assert f"hellobiga:dragon-board:local:snapshot:index:date:{dataset_id}:half_hour:2026-04-24" in flattened
    assert f"hellobiga:dragon-board:local:snapshot:index:snapshot:{dataset_id}:{snapshot_id}" in flattened


def test_snapshot_detail_read_api_applies_capture_mode_filters() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_sqlite_detail_filter_{suffix}"
    snapshot_id = f"half_hour:2026-04-23:{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-23",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-04-23",
                "slotTime": "10:30",
                "timestamp": 1776921000000,
                "displayKey": "[半小时快照] 2026-04-23 10:30",
                "captureMode": "restored",
                "source": "cloud_restore",
                "payload": {},
            }
        ],
    }

    ingest = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"sqlite-detail-filter-key-{suffix}",
            "tradingDate": "2026-04-23",
            "bundle": bundle,
        },
    )
    assert ingest.status_code == 200, ingest.text

    excluded = client.get(
        f"/api/snapshots/records/{snapshot_id}",
        params={"dataset_id": dataset_id, "exclude_restored": True},
    )
    assert excluded.status_code == 404, excluded.text

    real_time_only = client.get(
        f"/api/snapshots/records/{snapshot_id}",
        params={"dataset_id": dataset_id, "allowed_capture_modes": "real_time"},
    )
    assert real_time_only.status_code == 404, real_time_only.text

    restored = client.get(
        f"/api/snapshots/records/{snapshot_id}",
        params={"dataset_id": dataset_id, "allowed_capture_modes": "restored"},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["record"]["captureMode"] == "restored"
