from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import ths_main_monitor_routes


class FakeService:
    async def load_raw(self, code: str, *, force: bool = False) -> dict:
        assert code == "002297"
        assert force is False
        return {
            "stockCode": code,
            "sessionDate": "2026-07-24",
            "fetchedAt": 100,
            "servedAt": 110,
            "stale": True,
            "data": {"title": {"mainbuy": "1万", "mainsell": "2万"}, "list": []},
        }

    async def load_batch(self, codes: list[str], *, concurrency: int) -> dict:
        assert codes == ["002297", "600000"]
        assert concurrency == 2
        return {
            "rows": [{"code": "002297", "zlje": -10_000, "sessionDate": "2026-07-24"}],
            "failures": [{"code": "600000", "errorCode": "ths_timeout"}],
        }


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(ths_main_monitor_routes.router)
    app.dependency_overrides[ths_main_monitor_routes.get_ths_main_monitor_service] = FakeService
    return TestClient(app)


def test_single_route_keeps_tool_compatible_envelope() -> None:
    response = _client().get("/api/big-order/ths-detail?stockCode=002297")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["sessionDate"] == "2026-07-24"
    assert body["fetchedAt"] == 100
    assert body["servedAt"] == 110
    assert body["data"]["dragonMeta"]["cache"]["uiStale"] is True
    assert body["data"]["title"]["mainbuy"] == "1万"


def test_batch_route_returns_partial_results() -> None:
    response = _client().get(
        "/api/big-order/ths-fund-batch?codes=002297,600000&concurrency=2"
    )

    assert response.status_code == 200
    assert response.json()["data"]["failures"][0]["errorCode"] == "ths_timeout"


def test_batch_route_rejects_more_than_five_codes() -> None:
    response = _client().get(
        "/api/big-order/ths-fund-batch?codes=000001,000002,000003,000004,000005,000006"
    )

    assert response.status_code == 400
    assert response.json()["errorCode"] == "too_many_codes"
