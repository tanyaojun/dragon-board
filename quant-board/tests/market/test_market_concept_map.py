"""概念映射（theme_stock_mappings 单一事实源）服务层测试。

2026-10-13 裁决：东财概念含指数成分/人气榜等非题材噪音，弃用东财爬虫；
数据源换自家 Mongo 题材库。测试用内存 fake database，不真实连库（pytest 只入
dragon_board_test 护栏不受影响，本文件根本不触库）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import backend.api.market_data_routes as market_data_routes
from backend.market_proxy.concepts import ConceptMapService, get_concept_map_service


class FakeCursor:
    """链式 find().sort() 形态的最小模拟。"""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = list(docs)

    def sort(self, key: Any = None, **_kwargs: Any) -> "FakeCursor":
        # 生产 pymongo sort 传 [("field", 1), ...]；单键时按字段升序模拟
        if key and isinstance(key, list) and key and isinstance(key[0], (list, tuple)):
            field = str(key[0][0])
            self._docs = sorted(self._docs, key=lambda doc: str(doc.get(field) or ""))
        return self

    def __iter__(self):
        return iter(self._docs)

    def __len__(self) -> int:
        return len(self._docs)


class FakeCollection:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    def find(self, _filter: Any = None, projection: Any = None) -> FakeCursor:
        return FakeCursor(self.docs)


class FakeDatabase:
    def __init__(
        self,
        themes: list[dict[str, Any]],
        mappings: list[dict[str, Any]],
        metadata: list[dict[str, Any]] | None = None,
    ) -> None:
        self._collections = {
            "themes": FakeCollection(themes),
            "theme_stock_mappings": FakeCollection(mappings),
            "theme_metadata": FakeCollection(metadata or []),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections[name]


def make_service(
    database: FakeDatabase | None,
    cache_dir: Path,
    **kwargs: Any,
) -> ConceptMapService:
    return ConceptMapService(database=database, cache_dir=cache_dir, **kwargs)


def sample_database() -> FakeDatabase:
    return FakeDatabase(
        themes=[
            {"id": "117", "name": "固态电池", "zsCode": ""},
            {"id": "118", "name": "AI PC", "zsCode": "BK0001"},
            {"id": "119", "name": "空题材", "zsCode": ""},
        ],
        mappings=[
            {"themeId": "117", "stockCode": "300001"},
            {"themeId": "117", "stockCode": "300002"},
            {"themeId": "118", "stockCode": "600001"},
            {"themeId": "119", "stockCode": ""},  # 空 code：不计 errors
            {"themeId": "118", "stockCode": "abc123"},  # 非 6 位：errors
        ],
        metadata=[
            {"key": "version", "value": "v2026.10.13"},
            {"key": "lastUpdate", "value": "2026-10-13"},
        ],
    )


@pytest.mark.asyncio
async def test_builds_theme_mapping_from_mongo(tmp_path: Path) -> None:
    service = make_service(sample_database(), tmp_path)
    payload = await service.get_map()

    assert payload["ok"] is True
    assert payload["refreshing"] is False
    assert payload["source"] == "concept-map-theme"
    assert payload["version"] == "v2026.10.13"
    assert payload["lastUpdate"] == "2026-10-13"
    # 空题材不进 data（no_valid_members 计入 errors）
    names = {row["name"] for row in payload["data"]}
    assert names == {"固态电池", "AI PC"}
    assert payload["conceptCount"] == 2
    assert payload["stockCount"] == 3
    battery = next(row for row in payload["data"] if row["name"] == "固态电池")
    assert battery["code"] == "117"
    assert battery["stocks"] == ["300001", "300002"]
    # 板块实时涨幅由客户端按成员行情现算，题材库不提供
    assert battery["changePct"] is None
    assert any("invalid_stock_code:abc123" in item for item in payload["errors"])
    assert any("no_valid_members" in item for item in payload["errors"])


@pytest.mark.asyncio
async def test_memory_ttl_cache(tmp_path: Path) -> None:
    ticks = {"now": 1_000_000}
    database = sample_database()
    service = make_service(database, tmp_path, now_ms=lambda: ticks["now"])

    first = await service.get_map()
    database._collections["themes"].docs.append({"id": "999", "name": "新题材", "zsCode": ""})
    database._collections["theme_stock_mappings"].docs.append({"themeId": "999", "stockCode": "000006"})
    second = await service.get_map()
    assert second["conceptCount"] == first["conceptCount"]  # TTL 内不回源

    ticks["now"] += 31 * 60 * 1000  # 越过 30 分钟 TTL
    third = await service.get_map()
    assert third["conceptCount"] == 3


@pytest.mark.asyncio
async def test_force_refresh_bypasses_cache(tmp_path: Path) -> None:
    database = sample_database()
    service = make_service(database, tmp_path)
    await service.get_map()
    database._collections["themes"].docs.append({"id": "999", "name": "新题材", "zsCode": ""})
    database._collections["theme_stock_mappings"].docs.append({"themeId": "999", "stockCode": "000006"})

    payload = await service.get_map(force_refresh=True)
    assert payload["conceptCount"] == 3


@pytest.mark.asyncio
async def test_database_failure_falls_back_to_disk_cache(tmp_path: Path) -> None:
    service = make_service(sample_database(), tmp_path)
    await service.get_map()
    disk = json.loads((tmp_path / "concept-map-theme.json").read_text(encoding="utf-8"))
    assert disk["ok"] is True

    class BrokenDatabase:
        def __getitem__(self, _name: str) -> Any:
            raise RuntimeError("mongo down")

    ticks = {"now": 1_000_000 + 31 * 60 * 1000}
    broken = make_service(BrokenDatabase(), tmp_path, now_ms=lambda: ticks["now"])
    payload = await broken.get_map()

    assert payload["stale"] is True
    assert payload["ok"] is True
    assert any(item.startswith("database_unavailable") for item in payload["errors"])
    assert {row["name"] for row in payload["data"]} == {"固态电池", "AI PC"}


@pytest.mark.asyncio
async def test_database_failure_without_cache_raises(tmp_path: Path) -> None:
    class BrokenDatabase:
        def __getitem__(self, _name: str) -> Any:
            raise RuntimeError("mongo down")

    service = make_service(BrokenDatabase(), tmp_path)
    with pytest.raises(RuntimeError):
        await service.get_map()


@pytest.mark.asyncio
async def test_stale_disk_cache_expired_raises(tmp_path: Path) -> None:
    ticks = {"now": 1_000_000}
    service = make_service(sample_database(), tmp_path, stale_ttl_seconds=1000, now_ms=lambda: ticks["now"])
    await service.get_map()

    class BrokenDatabase:
        def __getitem__(self, _name: str) -> Any:
            raise RuntimeError("mongo down")

    # 与首个 service 同一时钟，推进到超 stale 窗口（1000s）
    ticks["now"] = 1_000_000 + 2000 * 1000
    broken = make_service(BrokenDatabase(), tmp_path, stale_ttl_seconds=1000, now_ms=lambda: ticks["now"])
    with pytest.raises(RuntimeError):
        await broken.get_map()


@pytest.mark.asyncio
async def test_empty_mapping_raises(tmp_path: Path) -> None:
    service = make_service(FakeDatabase(themes=[], mappings=[]), tmp_path)
    with pytest.raises(RuntimeError, match="theme mapping empty"):
        await service.get_map()


@pytest.mark.asyncio
async def test_disk_cache_atomic_write(tmp_path: Path) -> None:
    service = make_service(sample_database(), tmp_path)
    await service.get_map()
    # 原子写：不留 .tmp 残留
    assert not (tmp_path / "concept-map-theme.json.tmp").exists()
    disk = json.loads((tmp_path / "concept-map-theme.json").read_text(encoding="utf-8"))
    assert disk["source"] == "concept-map-theme"


# ---------------------------------------------------------------- 路由级合同


def _route_client(monkeypatch: pytest.MonkeyPatch, service: Any):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(market_data_routes.router)
    monkeypatch.setattr(market_data_routes, "get_concept_map_service", lambda: service)
    return TestClient(app)


def test_route_ok_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _StubService:
        async def get_map(self, force_refresh: bool = False):
            return {
                "ok": True,
                "refreshing": False,
                "stale": False,
                "source": "concept-map-theme",
                "conceptCount": 1,
                "data": [{"code": "117", "name": "固态电池", "changePct": None, "stocks": ["300001"]}],
                "errors": [],
            }

    client = _route_client(monkeypatch, _StubService())
    resp = client.get("/api/concepts/map")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["source"] == "concept-map-theme"
    assert payload["data"][0]["stocks"] == ["300001"]
    assert "_cachedAtMs" not in payload  # 私有键不得漏出


def test_route_degraded_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class _BrokenService:
        async def get_map(self, force_refresh: bool = False):
            raise RuntimeError("mongo down and no cache")

    client = _route_client(monkeypatch, _BrokenService())
    resp = client.get("/api/concepts/map")
    assert resp.status_code == 200  # 失败可见：200 + degraded 结构，不抛 5xx
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["degraded"] is True
    assert payload["errorCode"] == "upstream_unavailable"
    assert payload["source"] == "concept-map-theme"
    assert payload["data"] == []
