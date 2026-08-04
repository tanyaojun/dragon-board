from __future__ import annotations

from backend.snapshot_collector.models import SourceHealth
from backend.snapshot_derivation import SnapshotDerivationService
from backend.snapshot_derivation.models import MarketFactBundle


def _fact(snapshot_type: str = "half_hour") -> MarketFactBundle:
    return MarketFactBundle(
        snapshot_type=snapshot_type,
        trading_date="2026-08-04",
        slot_time="15:30",
        timestamp_ms=1785835800000,
        dataset_id="dragonboard_live",
        capture_mode="real_time",
        stocks=[
            {
                "code": "000001",
                "name": "平安银行",
                "rank": 1,
                "preClose": 10.0,
                "price": 10.5,
                "volume": 1000,
                "pctChange": 5.0,
            }
        ],
        source_health=[SourceHealth(source="startup_bundle", ok=True, row_count=1)],
        quality_issues=[{"code": "demo", "detail": "ok"}],
    )


def test_derive_produces_full_bundle() -> None:
    bundle = SnapshotDerivationService().derive(_fact())

    assert len(bundle.records) == 1
    assert len(bundle.frames) == 1
    assert len(bundle.stock_rows) == 1
    assert bundle.stock_rows[0]["code"] == "000001"
    assert bundle.records[0]["snapshotId"] == "half_hour:2026-08-04:15:30"


def test_derive_attaches_derivation_metadata() -> None:
    bundle = SnapshotDerivationService().derive(_fact())
    derivation = bundle.frames[0]["metadata"]["derivation"]

    assert derivation["algorithmVersion"] == "snapshot_derivation_v1"
    assert derivation["configHash"] == "snapshot_derivation_v1_default"
    assert derivation["inputEvidence"]["stocks"] == 1
    assert derivation["inputEvidence"]["sourceHealth"] == 1
    assert derivation["derivedAt"]
    assert derivation["qualityIssues"] == [{"code": "demo", "detail": "ok"}]


def test_same_fact_derives_per_type_without_shared_mutation() -> None:
    service = SnapshotDerivationService()
    half = service.derive(_fact("half_hour"))
    daily = service.derive(_fact("daily"))

    assert half.records[0]["snapshotId"] == "half_hour:2026-08-04:15:30"
    assert daily.records[0]["snapshotId"] == "daily:2026-08-04:15:30"
    assert half.frames[0]["type"] == "half_hour"
    assert daily.frames[0]["type"] == "daily"
