"""Snapshot ingest / outbox / repository fault-tolerance tests, plus the
Supabase homomorphic backup client unit tests that share the same backup
pipeline concerns.

Extracted from tests/test_quant_board.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.data.backup.backup_sync import BackupSyncService
from backend.data.backup.supabase_homomorphic import SupabaseBackupClient, _chunk_rows_by_payload_size
from backend.data.models.database import SessionLocal, init_db
from backend.data.models.models import (
    BacktestRun,
    Dataset,
    GoldenRankTrendCase,
    OptimizationRun,
    SyncOutboxModel,
)
from backend.data.repositories.repository import Repository
from backend.main import app
from backend.services import BacktestService

from tests.fixtures.helpers import MemoryBackup


def test_supabase_upsert_chunks_are_limited_by_payload_size() -> None:
    rows = [
        {"id": "a", "code": "600001", "name": "x" * 40},
        {"id": "b", "code": "600002", "name": "y" * 40},
        {"id": "c", "code": "600003", "name": "z" * 40},
    ]

    chunks = _chunk_rows_by_payload_size(rows, max_rows=100, max_payload_bytes=90)

    assert [len(chunk) for chunk in chunks] == [1, 1, 1]
    assert [chunk[0]["id"] for chunk in chunks] == ["a", "b", "c"]


def test_supabase_theme_string_fields_preserve_explicit_empty_values() -> None:
    stock_row = SupabaseBackupClient._stock_to_row(
        "ds_1",
        {
            "snapshotId": "snap_1",
            "code": "000001",
            "themeRole": "",
            "theme_role": "leader",
        },
    )
    sector_row = SupabaseBackupClient._sector_to_row(
        "ds_1",
        {
            "snapshotId": "snap_1",
            "entityType": "hot_theme",
            "entityKey": "AI",
            "rotationState": "",
            "rotation_state": "mainline",
        },
    )

    assert stock_row["theme_role"] == ""
    assert sector_row["rotation_state"] == ""


def test_snapshot_ingest_is_idempotent_and_queues_outbox() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_test_{suffix}"
    idempotency_key = f"ingest-test-key-{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            {
                "id": "half_hour:2026-04-21:10:00",
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": "10:00",
                "timestamp": 1776746400000,
                "displayKey": "[半小时快照] 2026-04-21 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-21",
                    "slotTime": "10:00",
                    "timestamp": 1776746400000,
                    "hotlist": [{"code": "600001", "name": "样本A", "rank": 1, "price": 10}],
                },
            }
        ],
    }

    first = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "tradingDate": "2026-04-21",
            "bundle": bundle,
        },
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["ok"] is True
    assert first_body["deduped"] is False
    assert first_body["outbox"]["status"] == "pending"
    assert first_body["dataset"]["id"] == dataset_id
    assert first_body["dataset"]["frame_count"] == 1
    assert first_body["dataset"]["stock_row_count"] == 1

    second = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "tradingDate": "2026-04-21",
            "bundle": bundle,
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["deduped"] is True

    datasets = client.get("/api/datasets")
    assert any(item["id"] == dataset_id and item["frame_count"] == 1 for item in datasets.json())


def test_snapshot_ingest_dedupes_existing_snapshot_id_without_replacing_rows() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_existing_{suffix}"
    snapshot_id = "half_hour:2026-04-21:10:00"
    base_bundle = {
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
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-21",
                    "slotTime": "10:00",
                    "timestamp": 1776746400000,
                    "hotlist": [{"code": "600001", "name": "样本A", "rank": 1, "price": 10}],
                },
            }
        ],
    }
    changed_bundle = {
        **base_bundle,
        "items": [
            {
                **base_bundle["items"][0],
                "payload": {
                    **base_bundle["items"][0]["payload"],
                    "hotlist": [{"code": "600999", "name": "不应覆盖", "rank": 1, "price": 99}],
                },
            }
        ],
    }

    first = client.post(
        "/api/snapshots/ingest",
        json={"datasetId": dataset_id, "idempotencyKey": f"first-{suffix}", "bundle": base_bundle},
    )
    assert first.status_code == 200, first.text
    assert first.json()["deduped"] is False

    second = client.post(
        "/api/snapshots/ingest",
        json={"datasetId": dataset_id, "idempotencyKey": f"second-{suffix}", "bundle": changed_bundle},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["deduped"] is True
    assert second_body["outbox"]["status"] == "pending"

    stocks = client.get("/api/snapshots/stock-rows", params={"dataset_id": dataset_id, "snapshot_id": snapshot_id})
    assert stocks.status_code == 200, stocks.text
    assert [row["code"] for row in stocks.json()["rows"]] == ["600001"]


def test_snapshot_ingest_filters_existing_snapshot_ids_from_mixed_bundle() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_mixed_{suffix}"
    existing_snapshot_id = "half_hour:2026-04-21:10:00"
    new_snapshot_id = "half_hour:2026-04-21:10:30"

    def item(snapshot_id: str, slot_time: str, code: str) -> dict[str, Any]:
        return {
            "id": snapshot_id,
            "type": "half_hour",
            "tradingDate": "2026-04-21",
            "slotTime": slot_time,
            "timestamp": 1776746400000,
            "displayKey": f"[半小时快照] 2026-04-21 {slot_time}",
            "captureMode": "real_time",
            "source": "browser_runtime",
            "payload": {
                "type": "half_hour",
                "tradingDate": "2026-04-21",
                "slotTime": slot_time,
                "timestamp": 1776746400000,
                "hotlist": [{"code": code, "name": code, "rank": 1, "price": 10}],
            },
        }

    first_bundle = {"version": "v4", "tradingDate": "2026-04-21", "items": [item(existing_snapshot_id, "10:00", "600001")]}
    mixed_bundle = {
        "version": "v4",
        "tradingDate": "2026-04-21",
        "items": [
            item(existing_snapshot_id, "10:00", "600999"),
            item(new_snapshot_id, "10:30", "600002"),
        ],
    }

    first = client.post(
        "/api/snapshots/ingest",
        json={"datasetId": dataset_id, "idempotencyKey": f"first-mixed-{suffix}", "bundle": first_bundle},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        "/api/snapshots/ingest",
        json={"datasetId": dataset_id, "idempotencyKey": f"second-mixed-{suffix}", "bundle": mixed_bundle},
    )
    assert second.status_code == 200, second.text
    assert second.json()["deduped"] is False

    counts = client.get("/api/snapshots/counts", params={"dataset_id": dataset_id})
    assert counts.status_code == 200, counts.text
    assert counts.json()["counts"]["snapshot_frames"] == 2
    assert counts.json()["counts"]["snapshot_stock_rows"] == 2

    existing_rows = client.get(
        "/api/snapshots/stock-rows",
        params={"dataset_id": dataset_id, "snapshot_id": existing_snapshot_id},
    )
    assert existing_rows.status_code == 200, existing_rows.text
    assert [row["code"] for row in existing_rows.json()["rows"]] == ["600001"]

    new_rows = client.get(
        "/api/snapshots/stock-rows",
        params={"dataset_id": dataset_id, "snapshot_id": new_snapshot_id},
    )
    assert new_rows.status_code == 200, new_rows.text
    assert [row["code"] for row in new_rows.json()["rows"]] == ["600002"]


def test_snapshot_ingest_summary_is_persisted_and_outbox_retry_is_due_gated() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_live_summary_{suffix}"
    idempotency_key = f"ingest-summary-key-{suffix}"
    bundle = {
        "version": "v4",
        "tradingDate": "2026-04-22",
        "items": [
            {
                "id": "half_hour:2026-04-22:10:00",
                "type": "half_hour",
                "tradingDate": "2026-04-22",
                "slotTime": "10:00",
                "timestamp": 1776832800000,
                "displayKey": "[半小时快照] 2026-04-22 10:00",
                "captureMode": "real_time",
                "source": "browser_runtime",
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-22",
                    "slotTime": "10:00",
                    "timestamp": 1776832800000,
                    "hotlist": [
                        {"code": "600001", "name": "样本A", "rank": 1, "price": 10},
                        {"code": "600002", "name": "样本B", "rank": 2, "price": 11},
                    ],
                },
            }
        ],
    }
    response = client.post(
        "/api/snapshots/ingest",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "tradingDate": "2026-04-22",
            "bundle": bundle,
        },
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as session:
        saved = session.get(Dataset, dataset_id)
        assert saved is not None
        assert saved.snapshot_count == 1
        assert saved.frame_count == 1
        assert saved.stock_row_count == 2
        assert saved.start_date == "2026-04-22"
        assert saved.end_date == "2026-04-22"

        repo = Repository(session, enable_backup=False)
        row = repo.mark_outbox_failed(idempotency_key, "temporary outage", delay_seconds=3600, max_retries=3)
        assert row is not None
        assert row.status == "retry"
        assert row.next_retry_at is not None and row.next_retry_at > datetime.utcnow()
        pending_keys = {item.idempotency_key for item in repo.list_pending_outbox(limit=100)}
        assert idempotency_key not in pending_keys

        row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()
        pending_keys = {item.idempotency_key for item in repo.list_pending_outbox(limit=100)}
        assert idempotency_key in pending_keys

        repo.mark_outbox_failed(idempotency_key, "still down", delay_seconds=0, max_retries=3)
        failed = repo.mark_outbox_failed(idempotency_key, "still down", delay_seconds=0, max_retries=3)
        assert failed is not None
        assert failed.status == "failed"
        assert failed.next_retry_at is None
        pending_keys = {item.idempotency_key for item in repo.list_pending_outbox(limit=100)}
        assert idempotency_key not in pending_keys


def test_push_outbox_api_reports_due_items() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    with SessionLocal() as session:
        row = Repository(session, enable_backup=False).enqueue_outbox(
            "unsupported_test",
            {"value": suffix},
            idempotency_key=f"unsupported-test-{suffix}",
            dataset_id=f"ds_unsupported_{suffix}",
            next_retry_at=datetime.utcnow() - timedelta(seconds=1),
        )
        row.updated_at = datetime(1970, 1, 1)
        session.commit()

    response = client.post("/api/sync/push-outbox", params={"limit": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scanned"] == 1
    assert body["skipped"] == 1
    assert body["items"][0]["op_type"] == "unsupported_test"

    with SessionLocal() as session:
        row = Repository(session, enable_backup=False).get_outbox_by_idempotency_key(f"unsupported-test-{suffix}")
        if row:
            row.status = "done"
            session.commit()


def test_snapshot_json_migration_dry_run_and_idempotent_import(tmp_path: Path) -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_history_{suffix}"
    bundle = {
        "version": "v4",
        "items": [
            {
                "id": "half_hour:2026-04-23:10:00",
                "type": "half_hour",
                "tradingDate": "2026-04-23",
                "slotTime": "10:00",
                "timestamp": 1776919200000,
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-23",
                    "slotTime": "10:00",
                    "timestamp": 1776919200000,
                    "hotlist": [
                        {"code": "600001", "name": "样本A", "rank": 1, "price": 10},
                        {"code": "600002", "name": "样本B", "rank": 2, "price": 11},
                    ],
                    "sectors": [{"name": "样本行业", "rank": 1}],
                },
            },
            {
                "id": "half_hour:2026-04-23:10:30",
                "type": "half_hour",
                "tradingDate": "2026-04-23",
                "slotTime": "10:30",
                "timestamp": 1776921000000,
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-23",
                    "slotTime": "10:30",
                    "timestamp": 1776921000000,
                    "hotlist": [{"code": "600001", "name": "样本A", "rank": 1, "price": 10.2}],
                },
            },
        ],
    }
    path = tmp_path / "dragonboard-v4.json"
    path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")

    dry_run = client.post(
        "/api/migrations/snapshots/import-json",
        json={"datasetId": dataset_id, "sourcePath": str(path), "dryRun": True},
    )
    assert dry_run.status_code == 200, dry_run.text
    dry_report = dry_run.json()["report"]
    assert dry_report == {
        "scanned": 2,
        "imported": 0,
        "skipped": 0,
        "errors": [],
        "dry_run": True,
        "record_count": 2,
        "frame_count": 2,
        "stock_row_count": 3,
        "sector_row_count": 1,
        "start_date": "2026-04-23",
        "end_date": "2026-04-23",
        "snapshot_types": ["half_hour"],
    }
    assert client.get(f"/api/datasets/{dataset_id}").status_code == 404

    first = client.post(
        "/api/migrations/snapshots/import-json",
        json={"datasetId": dataset_id, "sourcePath": str(path), "name": "history import"},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first_body["ok"] is True
    assert first_body["deduped"] is False
    assert first_body["idempotencyKey"]
    assert first_body["report"] == {
        "scanned": 2,
        "imported": 2,
        "skipped": 0,
        "errors": [],
        "dry_run": False,
        "record_count": 2,
        "frame_count": 2,
        "stock_row_count": 3,
        "sector_row_count": 1,
        "start_date": "2026-04-23",
        "end_date": "2026-04-23",
        "snapshot_types": ["half_hour"],
    }
    assert first_body["dataset"]["id"] == dataset_id
    assert first_body["dataset"]["frame_count"] == 2
    assert first_body["dataset"]["stock_row_count"] == 3
    assert first_body["dataset"]["sector_row_count"] == 1

    second = client.post(
        "/api/migrations/snapshots/import-json",
        json={"datasetId": dataset_id, "sourcePath": str(path), "name": "history import"},
    )
    assert second.status_code == 200, second.text
    second_body = second.json()
    assert second_body["ok"] is True
    assert second_body["deduped"] is True
    assert second_body["report"]["scanned"] == 2
    assert second_body["report"]["imported"] == 0
    assert second_body["report"]["skipped"] == 2
    assert second_body["report"]["stock_row_count"] == 3

    dataset = client.get(f"/api/datasets/{dataset_id}")
    assert dataset.status_code == 200
    assert dataset.json()["frame_count"] == 2
    assert dataset.json()["stock_row_count"] == 3
    assert dataset.json()["sector_row_count"] == 1


def test_snapshot_json_migration_retries_missing_rows_with_existing_outbox() -> None:
    client = TestClient(app)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"dragonboard_history_retry_{suffix}"
    idempotency_key = f"migration-retry-key-{suffix}"
    first_bundle = {
        "version": "v4",
        "items": [
            {
                "id": "half_hour:2026-04-24:10:00",
                "type": "half_hour",
                "tradingDate": "2026-04-24",
                "slotTime": "10:00",
                "timestamp": 1777005600000,
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-24",
                    "slotTime": "10:00",
                    "timestamp": 1777005600000,
                    "hotlist": [{"code": "600001", "name": "样本A", "rank": 1}],
                },
            }
        ],
    }
    retry_bundle = {
        "version": "v4",
        "items": [
            *first_bundle["items"],
            {
                "id": "half_hour:2026-04-24:10:30",
                "type": "half_hour",
                "tradingDate": "2026-04-24",
                "slotTime": "10:30",
                "timestamp": 1777007400000,
                "payload": {
                    "type": "half_hour",
                    "tradingDate": "2026-04-24",
                    "slotTime": "10:30",
                    "timestamp": 1777007400000,
                    "hotlist": [{"code": "600002", "name": "样本B", "rank": 1}],
                },
            },
        ],
    }

    first = client.post(
        "/api/migrations/snapshots/import-json",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "content": first_bundle,
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["report"]["imported"] == 1

    retry = client.post(
        "/api/migrations/snapshots/import-json",
        json={
            "datasetId": dataset_id,
            "idempotencyKey": idempotency_key,
            "content": retry_bundle,
        },
    )
    assert retry.status_code == 200, retry.text
    retry_body = retry.json()
    assert retry_body["deduped"] is False
    assert retry_body["report"]["imported"] == 1
    assert retry_body["report"]["skipped"] == 1

    counts = client.get("/api/snapshots/counts", params={"dataset_id": dataset_id})
    assert counts.status_code == 200, counts.text
    assert counts.json()["counts"] == {
        "snapshots": 2,
        "snapshot_frames": 2,
        "snapshot_stock_rows": 2,
        "snapshot_sector_rows": 0,
    }


def test_snapshot_ingest_outbox_pushes_only_target_snapshot() -> None:
    init_db()
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"outbox_slice_{suffix}"
    backup = MemoryBackup()

    with SessionLocal() as session:
        repo = Repository(session, backup, enable_backup=False)
        dataset = Dataset(
            id=dataset_id,
            name="Outbox Slice",
            source_type="test",
            snapshot_count=2,
            frame_count=2,
            stock_row_count=2,
            sector_row_count=0,
            start_date="2026-05-08",
            end_date="2026-05-08",
            snapshot_types_json='["half_hour"]',
        )
        records = []
        frames = []
        stock_rows = []
        for slot, code in [("09:30", "600001"), ("10:00", "600002")]:
            snapshot_id = f"half_hour:2026-05-08:{slot}"
            records.append(
                {
                    "id": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-05-08",
                    "slotTime": slot,
                    "timestamp": 1778203800000,
                }
            )
            frames.append(
                {
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-05-08",
                    "slotTime": slot,
                    "timestamp": 1778203800000,
                    "rows": [{"code": code, "name": code, "rank": 1}],
                }
            )
            stock_rows.append(
                {
                    "snapshotId": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": "2026-05-08",
                    "timestamp": 1778203800000,
                    "code": code,
                    "name": code,
                    "rank": 1,
                }
        )
        repo.save_dataset_bundle(dataset, records, frames, stock_rows, [])
        saved_dataset = session.get(Dataset, dataset_id)
        assert saved_dataset is not None
        row = repo.enqueue_outbox(
            "snapshot_ingest",
            {"dataset": Repository.dataset_to_dict(saved_dataset)},
            idempotency_key=f"snapshot_ingest:{dataset_id}:target",
            dataset_id=dataset_id,
            snapshot_id="half_hour:2026-05-08:10:00",
            next_retry_at=datetime.utcnow() - timedelta(seconds=1),
        )
        session.commit()

        service = BackupSyncService(session, backup)
        success, error = service._push_dataset_outbox_row(repo, row)

        assert success is True
        assert error is None
        assert len(backup.frames[dataset_id]) == 1
        assert backup.frames[dataset_id][0]["payload"]["frame"]["snapshotId"] == "half_hour:2026-05-08:10:00"

    def frames_from_rows(self, rows, snapshot_type="half_hour", start_date=None, end_date=None, include_payload=True):
        frames = []
        for row in rows:
            frame = row["payload"]["frame"]
            if frame.get("type") != snapshot_type:
                continue
            item = {
                "snapshotId": frame["snapshotId"],
                "timestamp": frame["timestamp"],
                "tradingDate": frame["tradingDate"],
                "slotTime": frame["slotTime"],
                "type": frame["type"],
                "captureMode": frame.get("captureMode", "real_time"),
                "source": frame.get("source", "browser_runtime"),
                "marketContext": {},
                "stocks": row["payload"]["stocks"],
            }
            frames.append(item)
        return frames


def test_snapshot_ingest_outbox_fails_when_target_snapshot_is_missing() -> None:
    init_db()
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    dataset_id = f"outbox_missing_{suffix}"
    backup = MemoryBackup()

    with SessionLocal() as session:
        repo = Repository(session, backup, enable_backup=False)
        dataset = Dataset(
            id=dataset_id,
            name="Outbox Missing",
            source_type="test",
            snapshot_count=0,
            frame_count=0,
            stock_row_count=0,
            sector_row_count=0,
            start_date="2026-05-08",
            end_date="2026-05-08",
            snapshot_types_json='["half_hour"]',
        )
        repo.save_dataset_bundle(dataset, [], [], [], [])
        saved_dataset = session.get(Dataset, dataset_id)
        assert saved_dataset is not None
        row = repo.enqueue_outbox(
            "snapshot_ingest",
            {"dataset": Repository.dataset_to_dict(saved_dataset)},
            idempotency_key=f"snapshot_ingest:{dataset_id}:missing",
            dataset_id=dataset_id,
            snapshot_id="half_hour:2026-05-08:10:00",
            next_retry_at=datetime.utcnow() - timedelta(seconds=1),
        )
        session.commit()

        service = BackupSyncService(session, backup)
        success, error = service._push_dataset_outbox_row(repo, row)

        assert success is False
        assert error == "snapshot not found for outbox replay"
        assert dataset_id not in backup.frames


def test_repository_reports_primary_unavailable_without_backup_read_fallback() -> None:
    backup = MemoryBackup()
    repo = Repository(None, backup)
    dataset = Dataset(
        id="ds_backup",
        name="backup",
        source_type="json_bundle",
        source_path="",
        frame_count=1,
        stock_row_count=1,
        snapshot_count=1,
        sector_row_count=0,
        start_date="2026-04-01",
        end_date="2026-04-01",
        snapshot_types_json='["half_hour"]',
        metadata_json="{}",
        created_at=datetime.utcnow(),
    )
    frame = {
        "snapshotId": "s1",
        "type": "half_hour",
        "tradingDate": "2026-04-01",
        "slotTime": "10:00",
        "timestamp": 1,
    }
    stock = {"snapshotId": "s1", "code": "600001", "rank": 1}

    writer = Repository(SessionLocal(), backup)
    try:
        writer.save_dataset_bundle(dataset, [], [frame], [stock], [])
    finally:
        writer.close()

    fallback_repo = Repository(None, backup)
    assert fallback_repo.list_datasets() == []
    assert fallback_repo.get_dataset("ds_backup") is None
    with pytest.raises(RuntimeError, match="primary database is unavailable"):
        fallback_repo.load_frames("ds_backup", "half_hour")


def test_repository_dataset_reads_raise_when_primary_query_fails() -> None:
    class FailingSession:
        def scalars(self, *_args, **_kwargs):
            raise SQLAlchemyError("database offline")

        def get(self, *_args, **_kwargs):
            raise SQLAlchemyError("database offline")

    repo = Repository(FailingSession())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="primary database read failed"):
        repo.list_datasets()

    with pytest.raises(RuntimeError, match="primary database read failed"):
        repo.get_dataset("ds_missing")


def test_snapshot_ingest_fails_when_primary_session_is_unavailable() -> None:
    backup = MemoryBackup()
    repo = Repository(None, backup)
    dataset = Dataset(
        id="ds_ingest_failover",
        name="ingest failover",
        source_type="dragon_board_runtime",
        source_path="",
        frame_count=1,
        stock_row_count=1,
        snapshot_count=1,
        sector_row_count=0,
        start_date="2026-04-01",
        end_date="2026-04-01",
        snapshot_types_json='["half_hour"]',
        metadata_json="{}",
        created_at=datetime.utcnow(),
    )
    record = {
        "id": "half_hour:2026-04-01:10:00",
        "type": "half_hour",
        "tradingDate": "2026-04-01",
        "slotTime": "10:00",
        "timestamp": 1,
    }
    frame = {"snapshotId": record["id"], **record}
    stock = {"snapshotId": record["id"], "code": "600001", "rank": 1}

    with pytest.raises(RuntimeError, match="primary database is unavailable"):
        repo.save_snapshot_ingest(
            dataset,
            [record],
            [frame],
            [stock],
            [],
            idempotency_key="snapshot-ingest-failover-key",
            trading_date="2026-04-01",
        )

    assert dataset.id not in backup.datasets


def test_snapshot_ingest_primary_unavailable_does_not_try_backup_write() -> None:
    backup = MemoryBackup()
    backup.fail_writes = True
    repo = Repository(None, backup)
    dataset = Dataset(
        id="ds_ingest_failover_failed",
        name="ingest failover failed",
        source_type="dragon_board_runtime",
        source_path="",
        frame_count=1,
        stock_row_count=0,
        snapshot_count=1,
        sector_row_count=0,
        start_date="2026-04-01",
        end_date="2026-04-01",
        snapshot_types_json='["half_hour"]',
        metadata_json="{}",
        created_at=datetime.utcnow(),
    )
    record = {"id": "half_hour:2026-04-01:10:00", "type": "half_hour", "tradingDate": "2026-04-01"}

    with pytest.raises(RuntimeError, match="primary database is unavailable"):
        repo.save_snapshot_ingest(
            dataset,
            [record],
            [{"snapshotId": record["id"], **record}],
            [],
            [],
            idempotency_key="snapshot-ingest-failover-failed-key",
        )


def test_outbox_push_replays_snapshot_mirrors_and_keeps_research_local() -> None:
    backup = MemoryBackup()
    backup.fail_writes = True
    with SessionLocal() as session:
        suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        dataset = Dataset(
            id=f"ds_outbox_{suffix}",
            name="outbox",
            source_type="json_bundle",
            source_path="",
            frame_count=1,
            stock_row_count=1,
            snapshot_count=1,
            sector_row_count=0,
            start_date="2026-04-24",
            end_date="2026-04-24",
            snapshot_types_json='["half_hour"]',
            metadata_json="{}",
            created_at=datetime.utcnow(),
        )
        frame = {
            "snapshotId": f"half_hour:2026-04-24:{suffix}",
            "type": "half_hour",
            "tradingDate": "2026-04-24",
            "slotTime": "10:00",
            "timestamp": 1777005600000,
        }
        stock = {"snapshotId": frame["snapshotId"], "code": "600001", "rank": 1}
        repo = Repository(session, backup)
        repo.save_dataset_bundle(dataset, [], [frame], [stock], [])
        repo.save_backtest_run(
            BacktestRun(
                id=f"bt_{suffix}",
                dataset_id=dataset.id,
                strategy_name="rank_trend_candidate",
                snapshot_type="half_hour",
                config_hash="cfg",
                random_seed=20260430,
                request_json="{}",
                result_json="{}",
            )
        )
        repo.save_optimization_run(
            OptimizationRun(
                id=f"opt_{suffix}",
                dataset_id=dataset.id,
                strategy_name="rank_trend_candidate",
                method="grid",
                config_hash="cfg",
                random_seed=20260430,
                request_json="{}",
                result_json="{}",
            )
        )
        repo.save_golden_case(
            GoldenRankTrendCase(
                id=f"golden_{suffix}",
                name="golden",
                dataset_id=dataset.id,
                input_json="{}",
                expected_json="[]",
            )
        )

        queued = list(
            session.scalars(
                select(SyncOutboxModel).where(
                    SyncOutboxModel.dataset_id == dataset.id,
                )
            )
        )
        assert {row.op_type for row in queued} == {"dataset_bundle"}
        assert all(not hasattr(row, "payload_json") for row in queued)
        for row in queued:
            row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
        session.commit()

        backup.fail_writes = False
        service = BackupSyncService(session, backup)
        result = service.push_outbox_to_backup(repo, limit=200)
        for _ in range(3):
            unfinished = list(
                session.scalars(
                    select(SyncOutboxModel).where(
                        SyncOutboxModel.dataset_id == dataset.id,
                        SyncOutboxModel.status.in_(["pending", "retry"]),
                    )
                )
            )
            if not unfinished:
                break
            for row in unfinished:
                row.next_retry_at = datetime.utcnow() - timedelta(seconds=1)
            session.commit()
            result = service.push_outbox_to_backup(repo, limit=200)

        target_items = [item for item in result["items"] if item["dataset_id"] == dataset.id]
        assert target_items
        assert all(item["status"] == "done" for item in target_items)
        assert dataset.id in backup.datasets
        finished = list(
            session.scalars(
                select(SyncOutboxModel).where(
                    SyncOutboxModel.dataset_id == dataset.id,
                )
            )
        )
        assert {row.status for row in finished} == {"done"}


def test_delete_dataset_api_is_disabled_outside_mongodb_mode() -> None:
    client = TestClient(app)
    response = client.delete("/api/datasets/ds_legacy")
    assert response.status_code == 410, response.text
    assert response.json()["detail"] == "dataset deletion is only available in MongoDB mode"


def test_research_vacuum_runs_outside_session_transaction() -> None:
    init_db()
    with SessionLocal() as session:
        result = BacktestService(session).vacuum_research_sqlite()

    assert result == {"ok": True, "vacuum": True}
