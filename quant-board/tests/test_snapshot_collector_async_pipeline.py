from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.snapshot_collector.gateway import InProcessMarketDataGateway
from backend.snapshot_collector.providers import (
    ProxyLimitUpProvider,
    ProxyMergedHotlistProvider,
    collect_market_context_async,
)


class FakeHotlistService:
    _ttl_ms = 60000

    def __init__(self, payloads: dict[str, Any]) -> None:
        self._payloads = payloads
        self.called: list[str] = []

    async def get(self, platform: str) -> Any:
        self.called.append(platform)
        return self._payloads.get(platform, {"ok": False, "degraded": True})


def _merged_provider(service: FakeHotlistService) -> ProxyMergedHotlistProvider:
    return ProxyMergedHotlistProvider(gateway=InProcessMarketDataGateway())


def test_merged_hotlist_acollect_calls_real_service(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [{"c": "000001", "n": "平安银行", "r": 1}]}
    service = FakeHotlistService({"eastmoney": payload})
    monkeypatch.setattr("backend.market_proxy.hotlists.get_hotlist_service", lambda: service)
    provider = _merged_provider(service)

    rows, health = asyncio.run(provider.acollect(timeout_ms=5000))

    assert health.ok is True
    assert len(rows) == 1
    assert rows[0]["code"] == "000001"
    assert "eastmoney" in service.called


def test_merged_hotlist_acollect_partial_failure_keeps_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"data": [{"c": "000001", "n": "平安银行", "r": 1}]}
    service = FakeHotlistService({"eastmoney": payload, "xueqiu": None})
    monkeypatch.setattr("backend.market_proxy.hotlists.get_hotlist_service", lambda: service)
    provider = _merged_provider(service)

    rows, health = asyncio.run(provider.acollect(timeout_ms=5000))

    assert health.ok is True  # 部分失败不阻断
    assert len(rows) == 1
    assert "xueqiu" in health.failed_batches


def test_limitup_acollect_calls_real_service(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLimitUp:
        async def get_ths_pools(self, date: str | None = None) -> dict[str, Any]:
            return {
                "ok": True,
                "pools": {"one": {"items": [{"stock_code": "000001"}]}},
                "errors": [],
            }

    monkeypatch.setattr("backend.market_proxy.limitup.get_limitup_service", lambda: FakeLimitUp())
    provider = ProxyLimitUpProvider(gateway=InProcessMarketDataGateway())

    rows, health = asyncio.run(provider.acollect(["000001"], timeout_ms=5000))

    assert health.ok is True
    assert [row["code"] for row in rows] == ["000001"]


def test_collect_market_context_async_orchestrates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"data": [{"c": "000001", "n": "平安银行", "r": 1}]}
    service = FakeHotlistService({"eastmoney": payload})
    monkeypatch.setattr("backend.market_proxy.hotlists.get_hotlist_service", lambda: service)

    ctx = asyncio.run(
        collect_market_context_async(
            [_merged_provider(service)],
            [],
            timeout_ms=5000,
        )
    )

    assert len(ctx.stocks) == 1
    assert ctx.stocks[0]["code"] == "000001"


def test_arun_once_multi_collects_once_derives_per_type() -> None:
    from backend.data.snapshot_ingest_normalizer import normalize_snapshot_ingest
    from backend.snapshot_collector.models import (
        CollectorRunRequest,
        MarketDataContext,
        SourceHealth,
    )
    from backend.snapshot_collector.quality_gate import evaluate_quality
    from backend.snapshot_collector.service import SnapshotCollectorService

    class FakeRepo:
        def __init__(self) -> None:
            self.runs: list[dict[str, Any]] = []

        def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
            return False

        def save_snapshot_ingest(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            return {"status": "done", "deduped": False}

        def insert_run(self, run: dict[str, Any]) -> None:
            self.runs.append(run)

    ctx = MarketDataContext(
        stocks=[
            {
                "code": "000001",
                "name": "平安银行",
                "rank": 1,
                "preClose": 10.0,
                "price": 10.5,
                "volume": 1000,
            }
        ],
        source_health=[SourceHealth(source="startup_bundle", ok=True, row_count=1)],
    )
    collect_calls = {"n": 0}

    async def fake_collect(
        providers: list[Any], codes: list[str], timeout_ms: int | None = None
    ) -> MarketDataContext:
        collect_calls["n"] += 1
        return ctx

    service = SnapshotCollectorService(
        FakeRepo(),
        collect_fn=fake_collect,
        normalize_fn=normalize_snapshot_ingest,
        quality_fn=evaluate_quality,
        theme_heat_service=None,
    )
    requests = [
        CollectorRunRequest(
            dataset_id="test",
            snapshot_type="half_hour",
            trading_date="2026-08-04",
            slot_time="15:30",
            dry_run=True,
        ),
        CollectorRunRequest(
            dataset_id="test",
            snapshot_type="daily",
            trading_date="2026-08-04",
            slot_time="15:30",
            dry_run=True,
        ),
    ]

    results = asyncio.run(service.arun_once_multi(requests))

    assert collect_calls["n"] == 1  # 只采集一次
    assert len(results) == 2
    assert all(result.status == "dry_run" for result in results)
    assert results[0].snapshot_id == "half_hour:2026-08-04:15:30"
    assert results[1].snapshot_id == "daily:2026-08-04:15:30"
