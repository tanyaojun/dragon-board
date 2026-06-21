from __future__ import annotations

from fastapi.testclient import TestClient

import backend.api.theme_heat_routes as theme_heat_routes
from backend.main import app
from backend.theme_heat_service import ThemeHeatUnavailable


class FakeThemeHeatService:
    def __init__(self, *, failure: ThemeHeatUnavailable | None = None) -> None:
        self.failure = failure

    def get_snapshot(self, *, force: bool = False) -> dict:
        assert isinstance(force, bool)
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
    monkeypatch.setattr(theme_heat_routes, "get_theme_heat_service", lambda: FakeThemeHeatService())
    client = TestClient(app)
    response = client.get("/api/themes/heat")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["factors"][0]["themeId"] == "AI"
    assert "quoteRowsByCode" not in body["data"]
    assert "fundRowsByCode" not in body["data"]
    assert "themeStocks" not in body["data"]


def test_theme_heat_unavailable_returns_503_with_stale_data(monkeypatch) -> None:
    stale = FakeThemeHeatService().get_snapshot()
    service = FakeThemeHeatService(
        failure=ThemeHeatUnavailable(
            code="quote_coverage_blocked",
            message="coverage low",
            stale_data=stale,
        )
    )
    monkeypatch.setattr(theme_heat_routes, "get_theme_heat_service", lambda: service)
    client = TestClient(app)
    response = client.get("/api/themes/heat")

    assert response.status_code == 503
    assert response.json()["errorCode"] == "quote_coverage_blocked"
    assert response.json()["staleData"]["computedAt"] > 0
    assert "quoteRowsByCode" not in response.json()["staleData"]


def test_theme_heat_stocks_rejects_unknown_sort_field(monkeypatch) -> None:
    monkeypatch.setattr(theme_heat_routes, "get_theme_heat_service", lambda: FakeThemeHeatService())
    client = TestClient(app)
    response = client.get("/api/themes/heat/AI/stocks?sort_by=unsupported")

    assert response.status_code == 400
