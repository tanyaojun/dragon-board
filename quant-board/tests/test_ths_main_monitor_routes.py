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


# —— 查看即刷新：ths-detail / ths-fund-batch 成功时同步更新资金列（theme-fund），
#    避免非订阅池个股资金列停留在历史旧值（2026-08-11 实盘复盘修复）——

class FakeCache:
    def __init__(self) -> None:
        self.puts: list[dict] = []
        self.put_many_rows: list[dict] = []

    def put(self, row: dict) -> dict:
        self.puts.append(row)
        return row

    def put_many(self, rows: list[dict]) -> tuple[list[dict], list[dict]]:
        self.put_many_rows.extend(rows)
        return rows, []


def _client_with_cache(monkeypatch, cache: FakeCache) -> TestClient:
    monkeypatch.setattr(ths_main_monitor_routes, "get_theme_fund_cache", lambda: cache)
    return _client()


def test_ths_detail_refreshes_theme_fund_cache_when_raw_valid(monkeypatch) -> None:
    cache = FakeCache()
    response = _client_with_cache(monkeypatch, cache).get(
        "/api/big-order/ths-detail?stockCode=002297"
    )

    assert response.status_code == 200
    assert len(cache.puts) == 1
    row = cache.puts[0]
    assert row["code"] == "002297"
    assert row["zlje"] == -10_000  # mainbuy 1万 − mainsell 2万
    assert row["sessionDate"] == "2026-07-24"
    assert row["moneyFlowSource"] == "ths_main_monitor"


def test_ths_fund_batch_refreshes_theme_fund_cache_with_rows(monkeypatch) -> None:
    cache = FakeCache()
    response = _client_with_cache(monkeypatch, cache).get(
        "/api/big-order/ths-fund-batch?codes=002297,600000"
    )

    assert response.status_code == 200
    assert len(cache.put_many_rows) == 1
    assert cache.put_many_rows[0]["code"] == "002297"
    assert cache.put_many_rows[0]["zlje"] == -10_000


def test_ths_detail_failure_keeps_cache_untouched(monkeypatch) -> None:
    class BrokenService(FakeService):
        async def load_raw(self, code: str, *, force: bool = False) -> dict:
            raise ths_main_monitor_routes.ThsMainMonitorError("ths_rate_limited")

    app = FastAPI()
    app.include_router(ths_main_monitor_routes.router)
    app.dependency_overrides[ths_main_monitor_routes.get_ths_main_monitor_service] = BrokenService
    cache = FakeCache()
    monkeypatch.setattr(ths_main_monitor_routes, "get_theme_fund_cache", lambda: cache)

    response = TestClient(app).get("/api/big-order/ths-detail?stockCode=002297")

    assert response.status_code == 503
    assert cache.puts == []
