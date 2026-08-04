import pytest

from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.engine import ThemeRotationEngine
from backend.analysis.theme_rotation.service import ThemeRotationService
from backend.snapshot_derivation.models import SnapshotBundle


class FakeRepo:
    def list_snapshot_sector_rows(self, dataset_id=None, **kwargs):
        return {
            "rows": [
                {"timestamp": 1000, "tradingDate": "2026-08-04", "entityKey": "BKAI", "themeId": "BKAI",
                 "themeName": "人工智能", "heatScore": 60.0, "momentumScore": 55.0, "crowdingRisk": 40.0,
                 "mainNetInflow": 1.0, "rank": 1},
                {"timestamp": 2000, "tradingDate": "2026-08-04", "entityKey": "BKAI", "themeId": "BKAI",
                 "themeName": "人工智能", "heatScore": 65.0, "momentumScore": 60.0, "crowdingRisk": 45.0,
                 "mainNetInflow": 1.5, "rank": 1},
            ],
            "source": "fake",
        }

    def list_snapshot_stock_rows(self, dataset_id=None, **kwargs):
        return {"rows": [], "source": "fake"}


@pytest.mark.asyncio
async def test_enrich_writes_rotation_fields():
    bundle = SnapshotBundle(
        frames=[{"snapshotId": "half_hour:2026-08-04:15:00", "indices": {}, "metadata": {}}],
        sector_rows=[{"themeId": "BKAI", "entityKey": "BKAI", "themeName": "人工智能", "rank": 1,
                      "heatScore": 80.0, "momentumScore": 70.0, "crowdingRisk": 50.0,
                      "mainNetInflow": 2.0, "positiveInflowStreak": 2, "negativeInflowStreak": 0,
                      "ztCount": 5, "change": 3.0, "breadthScore": 60.0}],
        stock_rows=[],
    )
    svc = ThemeRotationService(FakeRepo(), previous_trading_day_fn=lambda date: "2026-08-03")
    await svc.enrich_bundle(
        bundle,
        dataset_id="dragonboard_live",
        snapshot_type="half_hour",
        trading_date="2026-08-04",
        slot_timestamp_ms=3000,
        computed_at=3000,
    )
    row = bundle.sector_rows[0]
    assert row.get("rotationState") is not None  # 3 槽历史足够，输出真实状态
    assert "rotation_history_insufficient" not in (row.get("qualityFlags") or [])
    assert "reasons" in row
    assert bundle.frames[0]["rotationSummary"]["algorithmVersion"] == "theme_rotation_v2"


@pytest.mark.asyncio
async def test_enrich_engine_failure_does_not_block_save():
    class BoomEngine(ThemeRotationEngine):
        def compute(self, *args, **kwargs):
            raise RuntimeError("boom")

    bundle = SnapshotBundle(
        frames=[{"snapshotId": "half_hour:2026-08-04:15:00", "metadata": {}}],
        sector_rows=[{"themeId": "BKAI", "entityKey": "BKAI", "heatScore": 70.0}],
        stock_rows=[],
    )
    svc = ThemeRotationService(
        FakeRepo(),
        engine=BoomEngine(),
        previous_trading_day_fn=lambda date: "2026-08-03",
    )
    await svc.enrich_bundle(
        bundle, dataset_id="dragonboard_live", snapshot_type="half_hour",
        trading_date="2026-08-04", slot_timestamp_ms=3000, computed_at=3000,
    )
    issues = bundle.frames[0]["metadata"]["derivation"]["qualityIssues"]
    assert any("theme_rotation_failed" in issue for issue in issues)
    assert bundle.sector_rows[0]["themeId"] == "BKAI"  # 原始数据保留
