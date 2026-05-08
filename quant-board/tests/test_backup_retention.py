from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from backend.data.backup_retention import BackupRetentionService
from backend.data.backup_sync import BackupSyncService
from backend.main import app
from fastapi.testclient import TestClient


@dataclass
class FakeBackupClient:
    dates_by_dataset: dict[str, list[str]]
    deleted: list[dict[str, Any]] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    mirrored: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None

    def list_snapshot_trading_dates(self, dataset_id: str) -> list[str]:
        return list(self.dates_by_dataset.get(dataset_id, []))

    def prune_snapshot_facts_before(self, dataset_id: str, cutoff_trading_date: str, *, dry_run: bool = False) -> dict[str, Any]:
        if dry_run:
            return {
                "ok": True,
                "dryRun": True,
                "deletedRows": {"records": 0, "frames": 0, "stockRows": 0, "sectorRows": 0, "outbox": 0},
            }
        self.deleted.append({"datasetId": dataset_id, "cutoffTradingDate": cutoff_trading_date})
        return {
            "ok": True,
            "dryRun": False,
            "deletedRows": {"records": 2, "frames": 2, "stockRows": 20, "sectorRows": 4, "outbox": 2},
        }

    def refresh_dataset_summary(self, dataset_id: str) -> dict[str, Any]:
        self.summaries.append(dataset_id)
        return {"ok": True, "datasetId": dataset_id}

    def mirror_dataset_bundle(
        self,
        dataset: Any,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
    ) -> bool:
        self.mirrored.append(
            {
                "datasetId": dataset.id,
                "records": len(records),
                "frames": len(frames),
                "stockRows": len(stock_rows),
                "sectorRows": len(sector_rows),
            }
        )
        return True


def test_prune_backup_skips_when_history_does_not_exceed_retention() -> None:
    backup = FakeBackupClient({"dragonboard_live": ["2026-05-01", "2026-05-04"]})
    service = BackupRetentionService(backup)

    result = service.prune(dataset_ids=["dragonboard_live"], keep_trading_days=10)

    assert result["ok"] is True
    assert result["results"][0]["skipped"] is True
    assert result["results"][0]["reason"] == "not_enough_history"
    assert backup.deleted == []
    assert backup.summaries == []


def test_prune_backup_deletes_only_rows_before_tenth_latest_trading_day() -> None:
    dates = [f"2026-04-{day:02d}" for day in range(1, 13)]
    backup = FakeBackupClient({"dragonboard_live": dates})
    service = BackupRetentionService(backup)

    result = service.prune(dataset_ids=["dragonboard_live"], keep_trading_days=10)

    assert result["ok"] is True
    assert result["results"][0]["cutoffTradingDate"] == "2026-04-03"
    assert result["results"][0]["keptTradingDays"] == dates[-10:]
    assert result["results"][0]["deletedRows"]["stockRows"] == 20
    assert backup.deleted == [{"datasetId": "dragonboard_live", "cutoffTradingDate": "2026-04-03"}]
    assert backup.summaries == ["dragonboard_live"]


def test_prune_backup_dry_run_reports_cutoff_without_deleting_or_refreshing() -> None:
    dates = [f"2026-04-{day:02d}" for day in range(1, 13)]
    backup = FakeBackupClient({"dragonboard_live": dates})
    service = BackupRetentionService(backup)

    result = service.prune(dataset_ids=["dragonboard_live"], keep_trading_days=10, dry_run=True)

    assert result["ok"] is True
    assert result["dryRun"] is True
    assert result["results"][0]["cutoffTradingDate"] == "2026-04-03"
    assert result["results"][0]["deletedRows"] == {
        "records": 0,
        "frames": 0,
        "stockRows": 0,
        "sectorRows": 0,
        "outbox": 0,
    }
    assert backup.deleted == []
    assert backup.summaries == []


class FakeSession:
    def __init__(self, datasets: list[Any]) -> None:
        self.datasets = datasets

    def scalars(self, _query: Any) -> list[Any]:
        return self.datasets


class FakeRepository:
    pending_outbox: list[Any] = []

    def __init__(self, _session: Any, _backup: Any, enable_backup: bool = False) -> None:
        self.enable_backup = enable_backup

    def dump_dataset_bundle(
        self,
        dataset_id: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
        frames = [
            {"snapshotId": f"{dataset_id}:old", "tradingDate": "2026-04-01"},
            {"snapshotId": f"{dataset_id}:new", "tradingDate": "2026-04-12"},
        ]
        if start_date:
            frames = [frame for frame in frames if frame["tradingDate"] >= start_date]
        return SimpleNamespace(id=dataset_id), [], frames, [], []

    def dump_snapshot_bundle(
        self,
        dataset_id: str,
        snapshot_id: str,
    ) -> tuple[Any, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
        bundle = self.dump_dataset_bundle(dataset_id)
        if not bundle:
            return None
        dataset, records, frames, stock_rows, sector_rows = bundle
        return (
            dataset,
            [record for record in records if record.get("snapshotId") == snapshot_id],
            [frame for frame in frames if frame.get("snapshotId") == snapshot_id],
            [row for row in stock_rows if row.get("snapshotId") == snapshot_id],
            [row for row in sector_rows if row.get("snapshotId") == snapshot_id],
        )

    def list_pending_outbox(self, limit: int = 50) -> list[Any]:
        return self.pending_outbox[:limit]

    def mark_outbox_succeeded(self, _idempotency_key: str) -> Any:
        return None

    def mark_outbox_failed(self, _idempotency_key: str, _error: str) -> Any:
        return SimpleNamespace(status="retry")


def test_push_backup_defaults_to_retention_window(monkeypatch: Any) -> None:
    FakeRepository.pending_outbox = []
    backup = FakeBackupClient({})
    session = FakeSession([SimpleNamespace(id="dragonboard_live", created_at="2026-04-01")])
    monkeypatch.setattr("backend.data.backup_sync.Repository", FakeRepository)
    monkeypatch.setattr(
        "backend.data.backup_sync._local_retention_start_date",
        lambda _session, _dataset_id, _keep_trading_days: "2026-04-03",
    )

    result = BackupSyncService(session, backup).push_all_to_backup()

    assert result["ok"] is True
    assert result["retention"]["enabled"] is True
    assert backup.mirrored == [
        {"datasetId": "dragonboard_live", "records": 0, "frames": 1, "stockRows": 0, "sectorRows": 0}
    ]


def test_push_backup_skips_non_retention_datasets_by_default(monkeypatch: Any) -> None:
    FakeRepository.pending_outbox = []
    backup = FakeBackupClient({})
    session = FakeSession(
        [
            SimpleNamespace(id="dragonboard_live", created_at="2026-04-01"),
            SimpleNamespace(id="research_full_history", created_at="2026-04-01"),
        ]
    )
    monkeypatch.setattr("backend.data.backup_sync.Repository", FakeRepository)
    monkeypatch.setattr(
        "backend.data.backup_sync._local_retention_start_date",
        lambda _session, _dataset_id, _keep_trading_days: "2026-04-03",
    )

    result = BackupSyncService(session, backup).push_all_to_backup()

    assert result["ok"] is True
    assert result["datasets"]["scanned"] == 2
    assert result["datasets"]["skipped"] == 1
    assert backup.mirrored == [
        {"datasetId": "dragonboard_live", "records": 0, "frames": 1, "stockRows": 0, "sectorRows": 0}
    ]


def test_push_backup_applies_retention_to_outbox_replay(monkeypatch: Any) -> None:
    FakeRepository.pending_outbox = [
        SimpleNamespace(
            id=1,
            op_type="snapshot_ingest",
            idempotency_key="old-snapshot",
            dataset_id="dragonboard_live",
            snapshot_id="dragonboard_live:old",
        )
    ]
    backup = FakeBackupClient({})
    session = FakeSession([SimpleNamespace(id="dragonboard_live", created_at="2026-04-01")])
    monkeypatch.setattr("backend.data.backup_sync.Repository", FakeRepository)
    monkeypatch.setattr(
        "backend.data.backup_sync._local_retention_start_date",
        lambda _session, _dataset_id, _keep_trading_days: "2026-04-03",
    )

    result = BackupSyncService(session, backup).push_all_to_backup()

    assert result["ok"] is True
    assert result["outbox"]["succeeded"] == 1
    assert backup.mirrored == [
        {"datasetId": "dragonboard_live", "records": 0, "frames": 1, "stockRows": 0, "sectorRows": 0},
        {"datasetId": "dragonboard_live", "records": 0, "frames": 1, "stockRows": 0, "sectorRows": 0},
    ]


def test_prune_backup_api_returns_structured_result(monkeypatch: Any) -> None:
    def fake_once(*, dry_run: bool = False) -> dict[str, Any]:
        return {"ok": True, "dryRun": dry_run, "datasetIds": ["dragonboard_live"], "results": [], "errors": []}

    monkeypatch.setattr("backend.main.run_backup_retention_once", fake_once)
    response = TestClient(app).post("/api/sync/prune-backup?dry_run=true")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["dryRun"] is True
    assert response.json()["datasetIds"] == ["dragonboard_live"]
