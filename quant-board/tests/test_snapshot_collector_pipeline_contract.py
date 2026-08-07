"""契约测试：provider → MarketDataContext → projection → normalizer 全链路（mock 外部 I/O）。

覆盖：
- BridgeQuoteProvider 在 httpx 网关（注入 gateway）下的 set_pool/collect
  （直连模式、pool 模式、陈旧标记、失败降级）；
- 全链路产出非空 records/frames/stockRows/sectorRows，不写 MongoDB；
- 部分来源失败仍产出有效 payload（fail-visible），全源离线时上下文显式反映失败。
"""

from __future__ import annotations

import datetime
import time
from typing import Any
from zoneinfo import ZoneInfo

from backend.data.models.schemas import SnapshotIngestRequest
from backend.data.ingest.snapshot_ingest_normalizer import normalize_snapshot_ingest
from backend.snapshot_collector.builder import build_ingest_payload
from backend.snapshot_collector.models import SnapshotSlot
from backend.snapshot_collector.providers import (
    BridgeQuoteProvider,
    ProxyHotlistProvider,
    ThemeMappingProvider,
    collect_market_context,
)

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class FakeGateway:
    """Minimal in-memory HttpMarketDataGateway substitute (httpx 层 mock)。"""

    def __init__(
        self,
        *,
        get_result: Any = None,
        post_result: Any = None,
        get_error: Exception | None = None,
        post_error: Exception | None = None,
    ) -> None:
        self.get_result = get_result
        self.post_result = post_result
        self.get_error = get_error
        self.post_error = post_error
        self.get_urls: list[str] = []
        self.post_urls: list[str] = []
        self.post_payloads: list[Any] = []

    def get_json(self, url: str, timeout_s: float) -> Any:
        self.get_urls.append(url)
        if self.get_error:
            raise self.get_error
        return self.get_result() if callable(self.get_result) else (self.get_result or {})

    def post_json(self, url: str, timeout_s: float, payload: Any | None = None) -> Any:
        self.post_urls.append(url)
        self.post_payloads.append(payload)
        if self.post_error:
            raise self.post_error
        return self.post_result() if callable(self.post_result) else (self.post_result or {})


class FakeThemeRepo:
    def __init__(self, theme_map: dict[str, list[str]] | None = None) -> None:
        self._map = theme_map or {}

    def get_stock_themes(self, code: str) -> dict[str, Any]:
        themes = self._map.get(code, [])
        return {
            "code": code,
            "themes": [{"id": theme, "name": theme} for theme in themes],
            "tags": [],
            "reason": "",
            "source": "mongodb",
        }


BRIDGE_OK = {
    "ok": True,
    "source": "python_bridge",
    "serverTs": 1781170800000,
    "subscribedCount": 2,
    "quotes": [
        {"code": "000001", "price": 12.50, "pctChange": 2.35, "volume": 150000, "amount": 1800000.0},
        {"code": "600000", "price": 9.80, "pctChange": -0.51, "volume": 80000, "amount": 784000.0},
    ],
    "depth": [],
    "quoteStats": {"totalVolume": 100, "totalAmount": 2000, "upCount": 10, "downCount": 2, "flatCount": 1},
}

HOTLIST_ROWS = [
    {"code": "000001", "name": "平安银行", "rank": 1, "price": 12.5, "pctChange": 2.35,
     "volume": 150000, "amount": 1800000.0, "turnover": 5.5, "heat": 92.0},
    {"code": "600000", "name": "浦发银行", "rank": 2, "price": 9.8, "pctChange": -0.51,
     "volume": 80000, "amount": 784000.0, "turnover": 2.1, "heat": 75.0},
]


# ── BridgeQuoteProvider（httpx 网关） ───────────────────────────────────────


def test_bridge_set_pool_posts_subscriptions() -> None:
    gateway = FakeGateway(post_result={"ok": True, "count": 2, "codes": ["000001", "600000"], "setAt": 1})
    provider = BridgeQuoteProvider(base_url="http://127.0.0.1:8765", gateway=gateway)
    result = provider.set_pool(["000001", "600000"], timeout_ms=5000)
    assert result["ok"] is True
    assert result["count"] == 2
    assert gateway.post_urls == ["http://127.0.0.1:8765/api/quotes/subscriptions"]
    assert gateway.post_payloads == [{"codes": ["000001", "600000"]}]


def test_bridge_collect_direct_normalizes_quotes() -> None:
    gateway = FakeGateway(get_result=BRIDGE_OK)
    provider = BridgeQuoteProvider(base_url="http://127.0.0.1:8765", gateway=gateway)
    data, health = provider.collect(["000001", "600000"], timeout_ms=5000)
    assert health.ok is True
    assert len(data["quotes"]) == 2
    assert data["market_meta"]  # 归一化后的 quoteStats
    assert "codes=000001" in gateway.get_urls[0]


def test_bridge_collect_pool_ignores_codes_and_marks_stale() -> None:
    old = int(time.time() * 1000) - 120000
    gateway = FakeGateway(get_result={**BRIDGE_OK, "pooled": True, "poolRefreshedAt": old})
    provider = BridgeQuoteProvider(
        base_url="http://127.0.0.1:8765",
        pool_staleness_ms=30000,
        gateway=gateway,
    )
    data, health = provider.collect(["ignored"], timeout_ms=5000, use_pool=True)
    assert health.ok is True
    assert "quote_stale" in health.error
    assert "codes=" not in gateway.get_urls[0]


def test_bridge_collect_ok_false_fails_health() -> None:
    gateway = FakeGateway(get_result={"ok": False, "error": "bridge down"})
    provider = BridgeQuoteProvider(base_url="http://127.0.0.1:8765", gateway=gateway)
    data, health = provider.collect(["000001"], timeout_ms=5000)
    assert health.ok is False
    assert data["quotes"] == []


def test_bridge_collect_gateway_error_fails_health() -> None:
    gateway = FakeGateway(get_error=RuntimeError("connection refused"))
    provider = BridgeQuoteProvider(base_url="http://127.0.0.1:8765", gateway=gateway)
    data, health = provider.collect(["000001"], timeout_ms=5000)
    assert health.ok is False
    assert data["quotes"] == []


def test_bridge_collect_without_codes_is_empty_ok() -> None:
    provider = BridgeQuoteProvider(base_url="http://127.0.0.1:8765", gateway=FakeGateway())
    data, health = provider.collect(None, timeout_ms=5000)
    assert health.ok is True
    assert data["quotes"] == []


# ── 全链路契约（provider → projection → normalizer） ───────────────────────


def _slot() -> SnapshotSlot:
    dt = datetime.datetime(2026, 6, 11, 15, 0, tzinfo=TZ_SHANGHAI)
    return SnapshotSlot(
        snapshot_type="half_hour",
        trading_date="2026-06-11",
        slot_time="15:00",
        timestamp_ms=int(dt.timestamp() * 1000),
    )


def _providers(
    *,
    hotlist_gateway: FakeGateway,
    bridge_gateway: FakeGateway,
    theme_map: dict[str, list[str]],
) -> list[Any]:
    return [
        ProxyHotlistProvider(
            base_url="http://127.0.0.1:3000",
            platform="eastmoney",
            gateway=hotlist_gateway,
        ),
        BridgeQuoteProvider(base_url="http://127.0.0.1:8765", gateway=bridge_gateway),
        ThemeMappingProvider(FakeThemeRepo(theme_map)),
    ]


def _normalize_bundle(ctx) -> tuple:
    bundle = build_ingest_payload(
        _slot(),
        ctx,
        dataset_id="dragonboard_backend_shadow",
        source="quantboard_backend_collector",
        capture_mode="real_time",
    )
    return normalize_snapshot_ingest(
        SnapshotIngestRequest(
            dataset_id="dragonboard_backend_shadow",
            bundle=bundle,
            source="quantboard_backend_collector",
        )
    )


def test_pipeline_produces_non_empty_bundle() -> None:
    hotlist_gateway = FakeGateway(post_result={"data": HOTLIST_ROWS})
    bridge_gateway = FakeGateway(get_result=BRIDGE_OK)
    ctx = collect_market_context(
        _providers(
            hotlist_gateway=hotlist_gateway,
            bridge_gateway=bridge_gateway,
            theme_map={"000001": ["人工智能"], "600000": ["银行"]},
        ),
        ["000001", "600000"],
        timeout_ms=5000,
    )
    assert ctx.stocks
    assert all(health.ok for health in ctx.source_health)

    _, records, frames, stock_rows, _, _ = _normalize_bundle(ctx)
    assert records
    assert frames
    assert stock_rows
    assert frames[0]["stockRowCount"] == len(stock_rows)


def test_pipeline_partial_failure_still_produces_payload() -> None:
    # 桥离线：热榜可用，行情失败 → 仍产出可保存 payload（fail-visible）
    hotlist_gateway = FakeGateway(post_result={"data": HOTLIST_ROWS})
    bridge_gateway = FakeGateway(get_error=RuntimeError("bridge offline"))
    ctx = collect_market_context(
        _providers(
            hotlist_gateway=hotlist_gateway,
            bridge_gateway=bridge_gateway,
            theme_map={"000001": ["人工智能"], "600000": ["银行"]},
        ),
        ["000001", "600000"],
        timeout_ms=5000,
    )
    assert ctx.stocks
    assert any(health.ok is False for health in ctx.source_health)

    _, records, frames, stock_rows, _, _ = _normalize_bundle(ctx)
    assert records
    assert frames
    assert stock_rows


def test_pipeline_all_sources_offline_reports_failed_context() -> None:
    hotlist_gateway = FakeGateway(post_error=RuntimeError("hotlist offline"))
    bridge_gateway = FakeGateway(get_error=RuntimeError("bridge offline"))
    ctx = collect_market_context(
        _providers(
            hotlist_gateway=hotlist_gateway,
            bridge_gateway=bridge_gateway,
            theme_map={},
        ),
        ["000001"],
        timeout_ms=5000,
    )
    assert ctx.stocks == []
    assert any(health.ok is False for health in ctx.source_health)
