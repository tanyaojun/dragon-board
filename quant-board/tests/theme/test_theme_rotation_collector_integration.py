import pytest

from backend.snapshot_collector.models import CollectorRunRequest
from backend.snapshot_collector.quality_gate import QualityResult
from backend.snapshot_collector.service import SnapshotCollectorService
from backend.snapshot_derivation.models import SnapshotBundle
from backend.snapshot_derivation.service import SnapshotDerivationService
from backend.snapshot_collector.models import MarketDataContext


class FakeRepo:
    def snapshot_exists(self, dataset_id, snapshot_id):
        return False

    def save_snapshot_ingest(self, dataset, records, frames, stock_rows, sector_rows, idempotency_key=None):
        return {"status": "ok", "deduped": False}

    def replace_snapshot_ingest(self, dataset, records, frames, stock_rows, sector_rows, idempotency_key=None):
        return {"status": "ok", "deduped": False}

    def insert_run(self, run):
        pass


class FakeRotationService:
    def __init__(self):
        self.calls = []

    async def enrich_bundle(self, bundle, **kwargs):
        self.calls.append(kwargs)
        bundle.frames[0]["rotationSummary"] = {"marketPhase": "rising"}


def _normalized(req):
    frame = req.bundle["frames"][0]
    return (
        {"id": req.dataset_id},
        [],
        [frame],
        [{"code": "600001", "name": "测试"}],
        req.bundle["sectorRows"],
        "idem-key-1",
    )


def _ok_quality(**kwargs):
    return QualityResult(ok=True, blocking_issues=[], warnings=[], source_counts={"ok": 1, "failed": 0})


@pytest.mark.asyncio
async def test_persist_one_invokes_rotation_service(monkeypatch):
    rotation = FakeRotationService()

    def fake_derive(self, fact, *, theme_governance=None):
        return SnapshotBundle(
            frames=[{"snapshotId": "half_hour:2026-08-04:15:00", "metadata": {}, "indices": {}}],
            sector_rows=[{"themeId": "BKAI", "entityKey": "BKAI", "rank": 1, "heatScore": 80.0}],
            stock_rows=[{"code": "600001", "name": "测试"}],
        )

    monkeypatch.setattr(SnapshotDerivationService, "derive", fake_derive)

    service = SnapshotCollectorService(
        repo=FakeRepo(),
        collect_fn=lambda *a, **k: (MarketDataContext(), None),
        normalize_fn=_normalized,
        quality_fn=_ok_quality,
        theme_rotation_service=rotation,
    )
    request = CollectorRunRequest(
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-08-04",
        slot_time="15:00",
    )
    result = await service._persist_one(request, MarketDataContext(), None)
    assert result.status == "completed"
    assert len(rotation.calls) == 1
    assert rotation.calls[0]["dataset_id"] == "dragonboard_live"
    assert rotation.calls[0]["snapshot_type"] == "half_hour"
