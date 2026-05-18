from __future__ import annotations

from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.data.database import SessionLocal
from backend.data.models import SnapshotStockRowModel, SyncOutboxModel
from backend.data.repository import Repository
from backend.main import app


def _snapshot_bundle(snapshot_id: str, code: str) -> dict:
    return {
        "version": "v4",
        "tradingDate": "2026-05-06",
        "items": [
            {
                "id": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-05-06",
                "slotTime": "09:30",
                "timestamp": 1778011800000,
                "displayKey": "[半小时快照] 2026-05-06 09:30",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-05-06",
                    "slotTime": "09:30",
                    "timestamp": 1778011800000,
                    "hotlist": [{"code": code, "name": code, "rank": 1, "price": 10}],
                },
            }
        ],
    }


def test_snapshot_ingest_existing_snapshot_id_does_not_append_outbox_rows() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_outbox_dedupe_{suffix}"
    snapshot_id = "half_hour:2026-05-06:09:30"

    first = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"first-{suffix}",
            "bundle": _snapshot_bundle(snapshot_id, "600001"),
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["deduped"] is False

    second = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"second-{suffix}",
            "bundle": _snapshot_bundle(snapshot_id, "600999"),
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["deduped"] is True

    with SessionLocal() as session:
        outbox_count = session.scalar(
            select(func.count())
            .select_from(SyncOutboxModel)
            .where(
                SyncOutboxModel.op_type == "snapshot_ingest",
                SyncOutboxModel.dataset_id == dataset_id,
                SyncOutboxModel.snapshot_id == snapshot_id,
            )
        )

    assert outbox_count == 1


def test_snapshot_ingest_persists_stock_row_reason() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_reason_{suffix}"
    snapshot_id = "half_hour:2026-05-06:09:30"
    bundle = _snapshot_bundle(snapshot_id, "600001")
    bundle["items"][0]["payload"]["hotlist"][0]["reason"] = "机器人+涨停原因"

    response = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": f"reason-{suffix}",
            "bundle": bundle,
        },
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as session:
        model = session.scalar(
            select(SnapshotStockRowModel).where(
                SnapshotStockRowModel.dataset_id == dataset_id,
                SnapshotStockRowModel.snapshot_id == snapshot_id,
                SnapshotStockRowModel.code == "600001",
            )
        )
        assert model is not None
        assert model.reason == "机器人+涨停原因"

        rows = Repository(session, enable_backup=False).list_snapshot_stock_rows(
            dataset_id,
            snapshot_id=snapshot_id,
        )["rows"]

    assert len(rows) == 1
    assert rows[0]["code"] == "600001"
    assert rows[0]["reason"] == "机器人+涨停原因"
