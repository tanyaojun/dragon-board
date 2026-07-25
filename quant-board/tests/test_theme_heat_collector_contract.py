from __future__ import annotations

from typing import Any

from backend.snapshot_collector.models import (
    CollectorRunRequest,
    MarketDataContext,
    QualityResult,
    SourceHealth,
)
from backend.snapshot_collector.service import SnapshotCollectorService


class FakeRepo:
    def __init__(self) -> None:
        self.runs: list[dict[str, Any]] = []

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
        return False

    def insert_run(self, run: dict[str, Any]) -> None:
        self.runs.append(run)


class FakeThemeHeatService:
    def __init__(self) -> None:
        self.calls = 0
        self.include_runtime_funds: bool | None = None

    def get_snapshot(self, *, include_runtime_funds: bool = True) -> dict[str, Any]:
        self.calls += 1
        self.include_runtime_funds = include_runtime_funds
        return {
            "computedAt": 1782018300000,
            "factorVersion": "theme-market-v1",
            "mappingVersion": "theme-v8-test",
            "quality": {"quoteCoverage": 0.98},
            "factors": [
                {
                    "themeId": "AI", "themeName": "人工智能", "rank": 1,
                    "heatScore": 88, "momentumScore": 90, "breadthScore": 80,
                    "fundScore": 70, "leadershipScore": 75, "correlationScore": 82,
                    "crowdingRisk": 20, "persistenceScore": 60,
                    "mainNetInflow": 1000000, "volumeRatio": 1.8,
                    "ztCount": 2, "leaderCount": 1, "qualityFlags": [],
                    "metadata": {"quoteCoverage": 1},
                },
                {
                    "themeId": "POWER", "themeName": "电力", "rank": 2,
                    "heatScore": 45, "momentumScore": 40, "breadthScore": 55,
                    "fundScore": None, "leadershipScore": 10, "correlationScore": 50,
                    "crowdingRisk": 5, "persistenceScore": 0,
                    "mainNetInflow": None, "volumeRatio": 1.0,
                    "ztCount": 0, "leaderCount": 0,
                    "qualityFlags": ["fund_flow_unavailable"],
                    "metadata": {"quoteCoverage": 1},
                },
            ],
            "sources": {
                "quotes": {"source": "theme_quote_tencent", "ok": True, "row_count": 4000},
                "funds": {
                    "source": "formal_fund_unavailable", "ok": False,
                    "row_count": 0, "coverage_ratio": 0,
                },
            },
        }


def _collect(*args, **kwargs) -> MarketDataContext:
    return MarketDataContext(
        stocks=[{"code": "000001", "name": "样本", "rank": 1, "price": 10}],
        source_health=[SourceHealth(source="hotlist_proxy", ok=True, row_count=1)],
    )


def test_collector_builds_all_theme_sector_rows() -> None:
    captured: dict[str, Any] = {}

    def normalize(request):
        captured.update(request.bundle)
        bundle = request.bundle
        return (
            type("Dataset", (), {"id": request.dataset_id})(),
            bundle["items"], bundle["frames"], bundle["stockRows"], bundle["sectorRows"],
            "test-key",
        )

    repo = FakeRepo()
    theme_service = FakeThemeHeatService()
    service = SnapshotCollectorService(
        repo=repo, collect_fn=_collect, normalize_fn=normalize,
        quality_fn=lambda **kwargs: QualityResult(True, [], [], {"ok": 3, "failed": 0}),
        theme_heat_service=theme_service,
    )
    request = CollectorRunRequest(
        dataset_id="dragonboard_backend_shadow", snapshot_type="half_hour",
        trading_date="2026-06-11", slot_time="10:00", dry_run=True,
    )

    result = service.run_once(request)

    assert result.status == "dry_run"
    assert len(captured["sectorRows"]) == 2
    assert {row["entityType"] for row in captured["sectorRows"]} == {"hot_theme"}
    assert captured["frames"][0]["sectorRowCount"] == 2
    assert captured["sectorRows"][1]["fundScore"] is None
    assert captured["sectorRows"][1]["themeQualityFlags"] == ["fund_flow_unavailable"]
    assert captured["sectorRows"][0]["metadata"]["fundSource"] is None
    assert theme_service.include_runtime_funds is False
    assert repo.runs[0]["themeFactorVersion"] == "theme-market-v1"
    assert repo.runs[0]["themeComputedAt"] == 1782018300000
    assert repo.runs[0]["themeQuoteCoverage"] == 0.98
    assert repo.runs[0]["themeFundCoverage"] == 0


def test_service_factory_injects_shared_theme_heat_service(monkeypatch) -> None:
    import backend.snapshot_collector.service_factory as factory

    fake_theme_service = FakeThemeHeatService()
    monkeypatch.setattr(factory, "get_theme_heat_service", lambda: fake_theme_service, raising=False)
    monkeypatch.setattr(factory, "get_settings", lambda: type("Settings", (), {})())

    service = factory.create_snapshot_collector_service(repo=FakeRepo())

    assert service._theme_heat_service is fake_theme_service
