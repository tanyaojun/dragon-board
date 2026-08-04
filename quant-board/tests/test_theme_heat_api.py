from __future__ import annotations

from fastapi.testclient import TestClient

import backend.api.theme_heat_routes as theme_heat_routes
from backend.main import app
from backend.theme_heat_service import ThemeHeatUnavailable


class FakeThemeHeatService:
    def __init__(self, *, failure: ThemeHeatUnavailable | None = None) -> None:
        self.failure = failure
        self.last_options: dict = {}

    def get_snapshot(
        self,
        *,
        force: bool = False,
        include_rotation_state: bool = False,
    ) -> dict:
        assert isinstance(force, bool)
        self.last_options = {"force": force, "include_rotation_state": include_rotation_state}
        if self.failure:
            raise self.failure
        return {
            "ok": True,
            "computedAt": 1782018300000,
            "cacheBucket": "2026-06-21T09:05:00+08:00",
            "factorVersion": "theme-market-v1",
            "mappingVersion": "theme-v8-test",
            "factors": [{"themeId": "AI", "heatScore": 88}],
            "quality": {},
            "sources": {},
            "quoteRowsByCode": {"000001": {"change": 2}},
            "fundRowsByCode": {"000001": {"mainNetInflow": 100}},
            "themeStocks": {"AI": ["000001"]},
            "stockThemes": {"000001": ["AI"]},
        }

    def get_theme_stocks(self, theme_id: str, **options) -> dict:
        return {"themeId": theme_id, "stocks": [], "options": options}


def test_theme_heat_summary_excludes_full_quote_maps(monkeypatch) -> None:
    service = FakeThemeHeatService()
    monkeypatch.setattr(theme_heat_routes, "get_theme_heat_service", lambda: service)
    client = TestClient(app)
    response = client.get("/api/themes/heat")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["factors"][0]["themeId"] == "AI"
    assert service.last_options["include_rotation_state"] is True
    assert "quoteRowsByCode" not in body["data"]
    assert "fundRowsByCode" not in body["data"]
    assert "themeStocks" not in body["data"]


def test_theme_heat_factors_enriched_with_rotation_state(monkeypatch) -> None:
    from backend.theme_heat_service import ThemeHeatService

    service = ThemeHeatService.__new__(ThemeHeatService)
    monkeypatch.setattr(
        service,
        "_load_latest_rotation_state",
        lambda: {
            "AI": {"rotationState": "mainline", "lifecycle": "expanding", "rotationScore": 78.0}
        },
    )
    snapshot = {
        "factors": [
            {"themeId": "AI", "heatScore": 88},
            {"themeId": "BKAG", "heatScore": 60},
        ]
    }
    enriched = service._with_rotation_state(snapshot)
    assert enriched["factors"][0]["rotationState"] == "mainline"
    assert enriched["factors"][0]["lifecycle"] == "expanding"
    assert enriched["factors"][0]["rotationScore"] == 78.0
    assert "rotationState" not in enriched["factors"][1]


def test_theme_heat_mapping_empty_returns_503_with_stale_data(monkeypatch) -> None:
    stale = FakeThemeHeatService().get_snapshot()
    service = FakeThemeHeatService(
        failure=ThemeHeatUnavailable(
            code="mapping_empty",
            message="MongoDB theme mapping is empty",
            stale_data=stale,
        )
    )
    monkeypatch.setattr(theme_heat_routes, "get_theme_heat_service", lambda: service)
    client = TestClient(app)
    response = client.get("/api/themes/heat")

    assert response.status_code == 503
    assert response.json()["errorCode"] == "mapping_empty"
    assert response.json()["staleData"]["computedAt"] > 0
    assert "quoteRowsByCode" not in response.json()["staleData"]


def test_theme_heat_low_coverage_returns_degraded_data_with_200(monkeypatch) -> None:
    """覆盖率不足返回降级因子 + 质量原因（200），不再用 503 隐藏已有数据。"""
    service = FakeThemeHeatService()
    monkeypatch.setattr(theme_heat_routes, "get_theme_heat_service", lambda: service)
    monkeypatch.setattr(
        service,
        "get_snapshot",
        lambda *, force, include_rotation_state=False: {
            **FakeThemeHeatService().get_snapshot(),
            "ok": False,
            "degraded": True,
            "quality": {
                "quoteCoverage": 0.5,
                "requestedCount": 2,
                "returnedCount": 1,
                "qualityFlags": [],
                "errorCode": "quote_coverage_blocked",
            },
            "factors": [{"themeId": "AI", "heatScore": 50, "rank": 0, "rankEligible": False}],
        },
    )
    client = TestClient(app)
    response = client.get("/api/themes/heat")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["degraded"] is True
    assert body["data"]["quality"]["errorCode"] == "quote_coverage_blocked"
    assert body["data"]["factors"][0]["rankEligible"] is False
    assert "quoteRowsByCode" not in body["data"]


def test_theme_heat_stocks_rejects_unknown_sort_field(monkeypatch) -> None:
    monkeypatch.setattr(theme_heat_routes, "get_theme_heat_service", lambda: FakeThemeHeatService())
    client = TestClient(app)
    response = client.get("/api/themes/heat/AI/stocks?sort_by=unsupported")

    assert response.status_code == 400
