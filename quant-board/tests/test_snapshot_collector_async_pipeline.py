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
    from backend.data.ingest.snapshot_ingest_normalizer import normalize_snapshot_ingest
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
    # ctx 无 snapshotContext → fail-visible 打标（不阻断 dry_run 结果）
    assert any(
        "snapshot_context_missing" in warning
        for result in results
        for warning in (result.quality.warnings or [])
    )


def test_collect_context_passes_pool_source_mode_to_real_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真实链路（collect_fn is collect_market_context）必须把 settings 的 mode 传给 async 路由。"""
    from backend.snapshot_collector import providers as providers_module
    from backend.snapshot_collector.models import MarketDataContext
    from backend.snapshot_collector.service import SnapshotCollectorService

    captured: dict[str, Any] = {}

    async def fake_route(
        providers_list: list[Any],
        codes: list[str],
        *,
        timeout_ms: int | None = None,
        pool_source_mode: str = "autonomous",
    ) -> MarketDataContext:
        captured["mode"] = pool_source_mode
        return MarketDataContext()

    # 判断锚点（is 判断）与调用点（async 调用）都指向 fake_route
    monkeypatch.setattr(providers_module, "collect_market_context", fake_route)
    monkeypatch.setattr(providers_module, "collect_market_context_async", fake_route)

    class FakeRepo:
        """_collect_context 不触 repo，仅满足构造器签名。"""

    # 假 settings 需满足 _create_providers 读取的 proxy/bridge/timeout 属性
    settings = type(
        "S",
        (),
        {
            "snapshot_collector_pool_source_mode": "bundle_first",
            "snapshot_collector_proxy_base_url": "http://127.0.0.1:3000",
            "snapshot_collector_bridge_base_url": "http://127.0.0.1:8765",
            "snapshot_collector_provider_timeout_ms": 5000,
        },
    )()

    service = SnapshotCollectorService(
        FakeRepo(),
        settings=settings,
        collect_fn=providers_module.collect_market_context,
        normalize_fn=lambda *a, **k: None,
        quality_fn=lambda **k: None,
        theme_heat_service=None,
    )

    ctx, theme_snapshot = asyncio.run(service._collect_context("2026-09-20"))

    assert captured["mode"] == "bundle_first"
    assert isinstance(ctx, MarketDataContext)
    assert theme_snapshot is None


def _async(value):
    async def _inner():
        return value

    return _inner()


def test_collect_market_context_async_autonomous_merged_is_primary() -> None:
    from backend.snapshot_collector.models import SourceHealth
    from backend.snapshot_collector.providers import (
        ProxyMergedHotlistProvider,
        StartupBundleStockProvider,
    )

    startup = StartupBundleStockProvider(base_url="http://127.0.0.1:3000")
    startup.snapshot_context = {"breathData": {"k": "v"}}
    startup_rows = [{"code": "600000", "name": "浦发银行", "rank": 2}]
    merged_rows = [{"code": "000001", "name": "平安银行", "rank": 1}]
    startup.collect = lambda *args, **kwargs: (
        startup_rows,
        SourceHealth(source="startup_bundle", ok=True, row_count=len(startup_rows)),
    )
    merged = ProxyMergedHotlistProvider(base_url="http://127.0.0.1:3000")
    merged_health = SourceHealth(source="merged_hotlist_proxy", ok=True, row_count=1)
    merged.acollect = lambda **kwargs: _async((merged_rows, merged_health))

    ctx = asyncio.run(
        collect_market_context_async(
            [startup, merged],
            [],
            timeout_ms=5000,
            pool_source_mode="autonomous",
        )
    )

    assert [row["code"] for row in ctx.stocks] == ["000001"]
    assert ctx.stocks[0]["poolSource"] == "autonomous"
    assert ctx.snapshot_context == {"breathData": {"k": "v"}}


def test_collect_market_context_async_merged_failure_falls_back_to_bundle_rows() -> None:
    # 兜底快路径（镜像同步版）：merged 空 rows + ok=False，bundle 行立即兜底入池，
    # 下游 provider 必须按兜底池 codes 补齐（fail-visible：不构成丢帧）。
    from backend.snapshot_collector.models import SourceHealth
    from backend.snapshot_collector.providers import (
        ProxyMergedHotlistProvider,
        StartupBundleStockProvider,
        TencentBasicQuoteProvider,
    )

    startup = StartupBundleStockProvider(base_url="http://127.0.0.1:3000")
    startup.snapshot_context = {"breathData": {"k": "v"}}
    startup_rows = [{"code": "600000", "name": "浦发银行", "rank": 2}]
    startup.collect = lambda *args, **kwargs: (
        startup_rows,
        SourceHealth(source="startup_bundle", ok=True, row_count=len(startup_rows)),
    )
    merged = ProxyMergedHotlistProvider(base_url="http://127.0.0.1:3000")
    failed_health = SourceHealth(
        source="merged_hotlist_proxy",
        ok=False,
        row_count=0,
        error="eastmoney: degraded",
        failed_batches=["eastmoney"],
        details={"rankProvenance": {"platformTotals": {"eastmoney": 0}, "platformWeights": {}}},
    )
    merged.acollect = lambda **kwargs: _async(([], failed_health))

    tencent = TencentBasicQuoteProvider(base_url="http://127.0.0.1:3000")
    captured: dict[str, Any] = {}

    async def fake_tencent_acollect(codes, *, timeout_ms=5000):
        captured["codes"] = list(codes)
        return (
            {"600000": {"code": "600000", "volumeRatio": 1.5}},
            SourceHealth("theme_quote_tencent", True, row_count=1),
        )

    tencent.acollect = fake_tencent_acollect

    ctx = asyncio.run(
        collect_market_context_async(
            [startup, merged, tencent],
            [],
            timeout_ms=5000,
            pool_source_mode="autonomous",
        )
    )

    assert [row["code"] for row in ctx.stocks] == ["600000"]
    assert ctx.stocks[0]["poolSource"] == "bundle_fallback"
    assert captured["codes"] == ["600000"]
    assert ctx.quotes == [{"code": "600000", "volumeRatio": 1.5}]
    composition = failed_health.details["poolComposition"]
    assert composition["failedPlatforms"] == ["eastmoney"]
    assert composition["poolSize"] == 1


def test_collect_market_context_async_bundle_first_keeps_legacy_behavior() -> None:
    # bundle_first 旧行为（镜像同步版）：bundle 在前供池、merged 被 skip、无 poolSource 标记。
    from backend.snapshot_collector.models import SourceHealth
    from backend.snapshot_collector.providers import (
        ProxyMergedHotlistProvider,
        StartupBundleStockProvider,
    )

    startup = StartupBundleStockProvider(base_url="http://127.0.0.1:3000")
    startup.snapshot_context = {"breathData": {"k": "v"}}
    startup_rows = [{"code": "600000", "name": "浦发银行", "rank": 2}]
    startup.collect = lambda *args, **kwargs: (
        startup_rows,
        SourceHealth(source="startup_bundle", ok=True, row_count=len(startup_rows)),
    )
    merged = ProxyMergedHotlistProvider(base_url="http://127.0.0.1:3000")
    merged_calls: list[bool] = []

    async def fake_merged_acollect(**kwargs):
        merged_calls.append(True)
        return ([], SourceHealth(source="merged_hotlist_proxy", ok=True, row_count=0))

    merged.acollect = fake_merged_acollect

    ctx = asyncio.run(
        collect_market_context_async(
            [startup, merged],
            [],
            timeout_ms=5000,
            pool_source_mode="bundle_first",
        )
    )

    assert [row["code"] for row in ctx.stocks] == ["600000"]
    assert "poolSource" not in ctx.stocks[0]
    assert ctx.snapshot_context == {"breathData": {"k": "v"}}
    assert merged_calls == []


def test_collect_market_context_async_fallback_is_order_independent_merged_first() -> None:
    # merged 在前且 raise、bundle 在后：async 路径同样由循环后安全网兜底（不依赖 provider 顺序）
    from backend.snapshot_collector.models import SourceHealth
    from backend.snapshot_collector.providers import (
        ProxyMergedHotlistProvider,
        StartupBundleStockProvider,
    )

    startup = StartupBundleStockProvider(base_url="http://127.0.0.1:3000")
    startup.snapshot_context = {"breathData": {"k": "v"}}
    startup_rows = [{"code": "600000", "name": "浦发银行", "rank": 2}]
    startup.collect = lambda *args, **kwargs: (
        startup_rows,
        SourceHealth(source="startup_bundle", ok=True, row_count=len(startup_rows)),
    )
    merged = ProxyMergedHotlistProvider(base_url="http://127.0.0.1:3000")

    async def raising_acollect(**kwargs):
        raise RuntimeError("all platforms failed")

    merged.acollect = raising_acollect

    ctx = asyncio.run(
        collect_market_context_async(
            [merged, startup],
            [],
            timeout_ms=5000,
            pool_source_mode="autonomous",
        )
    )

    assert [row["code"] for row in ctx.stocks] == ["600000"]
    assert ctx.stocks[0]["poolSource"] == "bundle_fallback"
    # raise 折叠出的 merged health 必须在安全网兜底后被二次修正 poolComposition（poolSize 0 -> 1）
    folded_health = next(h for h in ctx.source_health if h.source == "merged_hotlist_proxy")
    assert folded_health.details["poolComposition"]["poolSize"] == 1


def test_collect_market_context_async_merged_raise_folds_and_fallback_reaches_downstream() -> None:
    # merged.acollect 意外 raise：折叠为失败 health 后继续走兜底快路径（fail-visible），
    # 下游 provider 仍按兜底池 codes 补齐，异常不得阻断兜底。
    from backend.snapshot_collector.models import SourceHealth
    from backend.snapshot_collector.providers import (
        ProxyMergedHotlistProvider,
        StartupBundleStockProvider,
        TencentBasicQuoteProvider,
    )

    startup = StartupBundleStockProvider(base_url="http://127.0.0.1:3000")
    startup.snapshot_context = {"breathData": {"k": "v"}}
    startup_rows = [{"code": "600000", "name": "浦发银行", "rank": 2}]
    startup.collect = lambda *args, **kwargs: (
        startup_rows,
        SourceHealth(source="startup_bundle", ok=True, row_count=len(startup_rows)),
    )
    merged = ProxyMergedHotlistProvider(base_url="http://127.0.0.1:3000")

    async def raising_acollect(**kwargs):
        raise RuntimeError("all platforms failed")

    merged.acollect = raising_acollect

    tencent = TencentBasicQuoteProvider(base_url="http://127.0.0.1:3000")
    captured: dict[str, Any] = {}

    async def fake_tencent_acollect(codes, *, timeout_ms=5000):
        captured["codes"] = list(codes)
        return (
            {"600000": {"code": "600000", "volumeRatio": 1.5}},
            SourceHealth("theme_quote_tencent", True, row_count=1),
        )

    tencent.acollect = fake_tencent_acollect

    ctx = asyncio.run(
        collect_market_context_async(
            [startup, merged, tencent],
            [],
            timeout_ms=5000,
            pool_source_mode="autonomous",
        )
    )

    assert [row["code"] for row in ctx.stocks] == ["600000"]
    assert ctx.stocks[0]["poolSource"] == "bundle_fallback"
    # raise 被折叠为 merged 失败 health（而不是跳到外层 except 阻断兜底）
    folded_health = next(h for h in ctx.source_health if h.source == "merged_hotlist_proxy")
    assert folded_health.ok is False
    assert "all platforms failed" in folded_health.error
    assert captured["codes"] == ["600000"]
    assert ctx.quotes == [{"code": "600000", "volumeRatio": 1.5}]
