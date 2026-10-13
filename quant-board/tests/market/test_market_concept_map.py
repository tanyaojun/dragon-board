from __future__ import annotations

import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import backend.api.market_data_routes as market_data_routes
from backend.market_proxy.concepts import ConceptMapService


def _now_ms() -> int:
    return int(time.time() * 1000)


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _clist_response(total: int, rows: list[dict]) -> httpx.Response:
    return httpx.Response(200, json={"data": {"total": total, "diff": rows}})


def _board_row(code: str, name: str, pct: str | float) -> dict:
    return {"f12": code, "f14": name, "f3": pct}


def _cons_row(code: str, name: str) -> dict:
    return {"f12": code, "f14": name}


def _happy_handler(request: httpx.Request) -> httpx.Response:
    fs = request.url.params.get("fs", "")
    if fs == "m:90+t:3":
        return _clist_response(
            2,
            [
                _board_row("BK0655", "算力", 2.35),
                _board_row("BK9999", "测试板块", "-"),
            ],
        )
    if fs == "b:BK0655":
        return _clist_response(
            3,
            [
                _cons_row("600000", "浦发银行"),
                _cons_row("sh600519", "贵州茅台"),
                _cons_row("AAPL", "非A股"),
            ],
        )
    if fs == "b:BK9999":
        raise httpx.ConnectError("blocked")
    return _clist_response(0, [])


@pytest.mark.asyncio
async def test_concept_map_filters_and_partial_errors(tmp_path) -> None:
    client = _mock_client(_happy_handler)
    service = ConceptMapService(client=client, cache_dir=tmp_path / "cache")
    payload = await service.get_map(wait=True)

    assert payload["ok"] is True
    assert payload["source"] == "concept-map-em"
    assert payload["stale"] is False
    assert payload["conceptCount"] == 1  # BK9999 成分失败 → 不产出板块，计入 errors
    assert payload["stockCount"] == 2  # sh 前缀归一 + 非 A 股剔除
    board = payload["data"][0]
    assert board["code"] == "BK0655"
    assert board["name"] == "算力"
    assert board["changePct"] == 2.35
    assert board["stocks"] == [("600000", "浦发银行"), ("600519", "贵州茅台")]
    assert any("BK9999" in item for item in payload["errors"])


@pytest.mark.asyncio
async def test_concept_map_background_refresh_returns_snapshot_then_fills(tmp_path) -> None:
    """首刷走后台任务：首次调用立即返回 refreshing 快照，任务完成后数据可用。"""
    service = ConceptMapService(
        client=_mock_client(_happy_handler),
        cache_dir=tmp_path / "cache",
    )

    first = await service.get_map()
    assert first.get("refreshing") is True
    assert first["data"] == []
    assert "initial_refresh_in_progress" in first["errors"]

    # 后台任务真实完成（不受快照返回影响，服务级 task 存活于请求之外）
    task = service._refresh_task
    assert task is not None
    await task

    second = await service.get_map()
    assert second.get("refreshing", False) is False
    assert second["conceptCount"] == 1
    assert second["data"][0]["name"] == "算力"


@pytest.mark.asyncio
async def test_concept_map_serves_stale_disk_cache_on_refresh_failure(tmp_path) -> None:
    cache_dir = tmp_path / "cache"

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _happy_handler(request)

    client = _mock_client(handler)
    service = ConceptMapService(client=client, cache_dir=cache_dir, ttl_seconds=0)
    first = await service.get_map(wait=True)
    assert first["ok"] is True
    cache_file = cache_dir / "concept-map-em.json"
    assert cache_file.exists()

    def broken_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    service2 = ConceptMapService(
        client=_mock_client(broken_handler),
        cache_dir=cache_dir,
        ttl_seconds=0,
        stale_ttl_seconds=72 * 3600,
        now_ms=lambda: _now_ms() + 10_000,  # 推进时钟越过 TTL，逼出刷新路径
    )
    stale = await service2.get_map(wait=True)
    assert stale["stale"] is True
    assert stale["conceptCount"] == 1
    assert any("refresh_failed_serving_disk_cache" in item for item in stale["errors"])


@pytest.mark.asyncio
async def test_concept_map_raises_without_any_data(tmp_path) -> None:
    def broken_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    service = ConceptMapService(
        client=_mock_client(broken_handler),
        cache_dir=tmp_path / "empty",
    )
    with pytest.raises(Exception):
        await service.get_map(wait=True)


@pytest.mark.asyncio
async def test_concept_map_corrupt_disk_cache_does_not_crash(tmp_path) -> None:
    """损坏的磁盘缓存按无缓存处理：上游可用时正常重建并覆写。"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    (cache_dir / "concept-map-em.json").write_text("{corrupt!!", encoding="utf-8")

    service = ConceptMapService(client=_mock_client(_happy_handler), cache_dir=cache_dir)
    payload = await service.get_map(wait=True)

    assert payload["ok"] is True
    assert payload["conceptCount"] == 1


@pytest.mark.asyncio
async def test_concept_map_truncation_flagged_when_pages_capped(tmp_path) -> None:
    """页数封顶导致未拉满 total 时必须产出 truncated 告警（fail-visible）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        fs = request.url.params.get("fs", "")
        pn = int(request.url.params.get("pn", "1"))
        if fs == "m:90+t:3":
            # total=250 需要 3 页，但服务被封顶为 1 页 → 必然截断
            if pn == 1:
                return _clist_response(
                    250,
                    [_board_row(f"BK00{i}", f"板块{i}", 1.0) for i in range(100)],
                )
            return _clist_response(
                250,
                [_board_row(f"BK90{i}", f"尾板块{i}", 1.0) for i in range(50)],
            )
        if fs.startswith("b:BK"):
            return _clist_response(1, [_cons_row("600000", "浦发银行")])
        return _clist_response(0, [])

    service = ConceptMapService(
        client=_mock_client(handler),
        cache_dir=tmp_path / "cache",
        max_board_pages=1,
        max_constituent_pages=1,
    )
    payload = await service.get_map(wait=True)

    assert payload["ok"] is True
    assert any("board_list_truncated: 100/250" in item for item in payload["errors"])


def _build_app(monkeypatch: pytest.MonkeyPatch, payload: dict | Exception) -> FastAPI:
    app = FastAPI()
    app.include_router(market_data_routes.router)

    class FakeService:
        async def get_map(self, force_refresh: bool = False, wait: bool = False) -> dict:
            if isinstance(payload, Exception):
                raise payload
            return payload

    monkeypatch.setattr(
        market_data_routes,
        "get_concept_map_service",
        lambda: FakeService(),
    )
    return app


def test_concepts_map_route_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app(
        monkeypatch,
        {
            "ok": True,
            "source": "concept-map-em",
            "stale": False,
            "data": [{"code": "BK0655", "name": "算力", "stocks": []}],
            "errors": [],
        },
    )
    client = TestClient(app)
    response = client.get("/api/concepts/map")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"][0]["name"] == "算力"


def test_concepts_map_route_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app(monkeypatch, RuntimeError("all hosts failed"))
    client = TestClient(app)
    response = client.get("/api/concepts/map")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["degraded"] is True
    assert body["errorCode"] == "upstream_unavailable"
    assert body["data"] == []
