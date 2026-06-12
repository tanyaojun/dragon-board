"""Tests for snapshot_collector providers — Task 7: Providers unit tests.

All external HTTP/Mongo calls are mocked so tests run offline.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.snapshot_collector.models import MarketDataContext, SourceHealth
from backend.snapshot_collector.providers import (
    BridgeQuoteProvider,
    ProxyHotlistProvider,
    ThemeMappingProvider,
    collect_market_context,
)


# ── Fake HTTP response builder ──────────────────────────────────────────────


def _fake_urlopen_response(data: dict[str, Any], status: int = 200) -> MagicMock:
    """Build a MagicMock that behaves like urlopen context manager."""
    body_bytes = json.dumps(data).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = body_bytes
    mock_resp.status = status
    return mock_resp


def _fake_urlopen_raise(exception: Exception) -> MagicMock:
    """Build a MagicMock whose __enter__ raises the given exception."""
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(side_effect=exception)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ── Fake theme repository ───────────────────────────────────────────────────


class FakeThemeRepo:
    """In-memory theme repository for testing ThemeMappingProvider."""

    def __init__(self, theme_map: dict[str, list[str]] | None = None) -> None:
        self._map: dict[str, list[str]] = {}
        if theme_map:
            for code, themes in theme_map.items():
                self._map[code] = list(themes)

    def get_stock_themes(self, code: str) -> dict[str, Any]:
        themes = self._map.get(code, [])
        theme_dicts = [{"id": t, "name": t} for t in themes]
        return {
            "code": code,
            "themes": theme_dicts,
            "tags": [],
            "reason": "",
            "source": "mongodb",
        }


# ── Sample data ─────────────────────────────────────────────────────────────

EASTMONEY_HOTLIST_RESPONSE = {
    "data": [
        {
            "c": "000001",
            "n": "平安银行",
            "r": 1,
            "p": 12.50,
            "zdf": 2.35,
            "cje": 1875000000.0,
            "cjl": 150000000,
            "hsl": 5.5,
            "hot": 92.0,
        },
        {
            "c": "600000",
            "n": "浦发银行",
            "r": 2,
            "p": 9.80,
            "zdf": -0.51,
            "cje": 784000000.0,
            "cjl": 80000000,
            "hsl": 2.1,
            "hot": 75.0,
        },
        {
            "c": "300001",
            "n": "特锐德",
            "r": 3,
            "p": 25.30,
            "zdf": 5.20,
            "cje": 320000000.0,
            "cjl": 12000000,
            "hsl": 8.3,
            "hot": 88.0,
        },
    ]
}

BRIDGE_SNAPSHOT_RESPONSE = {
    "ok": True,
    "source": "python_bridge",
    "serverTs": 1781170800000,
    "subscribedCount": 3,
    "quotes": [
        {
            "code": "000001",
            "price": 12.50,
            "pctChange": 2.35,
            "volume": 150000000,
            "amount": 1875000000.0,
            "turnover": 5.5,
        },
        {
            "code": "600000",
            "price": 9.80,
            "pctChange": -0.51,
            "volume": 80000000,
            "amount": 784000000.0,
            "turnover": 2.1,
        },
        {
            "code": "300001",
            "price": 25.30,
            "pctChange": 5.20,
            "volume": 12000000,
            "amount": 320000000.0,
            "turnover": 8.3,
        },
    ],
    "depth": [
        {"code": "000001", "bidPrice1": 12.49, "askPrice1": 12.51, "bidVol1": 10000, "askVol1": 8000},
        {"code": "600000", "bidPrice1": 9.79, "askPrice1": 9.81, "bidVol1": 5000, "askVol1": 3000},
        {"code": "300001", "bidPrice1": 25.29, "askPrice1": 25.31, "bidVol1": 2000, "askVol1": 1500},
    ],
    "ticks": [],
    "moneyFlow": [
        {"code": "000001", "mainNetInflow": 50000000.0, "superLargeNetInflow": 20000000.0},
        {"code": "600000", "mainNetInflow": -10000000.0, "superLargeNetInflow": -5000000.0},
        {"code": "300001", "mainNetInflow": 30000000.0, "superLargeNetInflow": 15000000.0},
    ],
    "quoteStats": {"totalVolume": 500000000000, "upCount": 2500, "downCount": 1800},
    "l2": {},
}

BRIDGE_OFFLINE_RESPONSE = {
    "ok": False,
    "source": "python_bridge",
    "serverTs": 0,
    "subscribedCount": 0,
    "quotes": [],
    "depth": [],
    "ticks": [],
    "moneyFlow": [],
    "quoteStats": {},
    "l2": {},
}

THEME_MAP = {
    "000001": ["银行", "深圳"],
    "600000": ["银行", "上海"],
    "300001": ["充电桩", "新基建"],
}

TEST_CODES = ["000001", "600000", "300001"]

PROXY_BASE_URL = "http://127.0.0.1:3000"
BRIDGE_BASE_URL = "http://127.0.0.1:8765"


# ═════════════════════════════════════════════════════════════════════════════
# ProxyHotlistProvider
# ═════════════════════════════════════════════════════════════════════════════


class TestProxyHotlistProviderNormalization:
    """proxy hotlist response maps to normalized provider rows."""

    def test_normalizes_stock_codes(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert health.ok is True
        assert health.source == "hotlist_proxy"
        assert health.row_count == 3
        assert len(stocks) == 3

    def test_normalized_fields_match_expected(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        row0 = stocks[0]
        assert row0["code"] == "000001"
        assert row0["name"] == "平安银行"
        assert row0["rank"] == 1
        assert row0["price"] == 12.50
        assert row0["pctChange"] == 2.35
        assert row0["amount"] == 1875000000.0
        assert row0["volume"] == 150000000
        assert row0["turnover"] == 5.5
        assert row0["heat"] == 92.0

    def test_all_stocks_have_required_fields(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        required = {"code", "name", "rank", "price", "pctChange", "volume", "amount", "turnover", "heat"}
        for row in stocks:
            missing = required - set(row.keys())
            assert not missing, f"stock {row.get('code')} missing fields: {missing}"

    def test_empty_data_returns_empty_list(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response({"data": []})
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert health.ok is True
        assert health.row_count == 0
        assert stocks == []

    def test_missing_data_key_returns_empty(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response({"other": [{"c": "000001"}]})
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert health.ok is True
        assert stocks == []

    def test_stock_without_code_is_skipped(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        body = {
            "data": [
                {"n": "NoCode", "r": 1},
                {"c": "000001", "n": "平安银行", "r": 2},
            ]
        }
        mock_resp = _fake_urlopen_response(body)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert len(stocks) == 1
        assert stocks[0]["code"] == "000001"

    def test_stock_with_empty_code_is_skipped(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        body = {
            "data": [
                {"c": "", "n": "EmptyCode", "r": 1},
                {"c": "600000", "n": "浦发银行", "r": 2},
            ]
        }
        mock_resp = _fake_urlopen_response(body)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert len(stocks) == 1
        assert stocks[0]["code"] == "600000"

    def test_health_contains_latency(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            _, health = provider.collect(timeout_ms=5000)

        assert health.latency_ms >= 0
        assert health.captured_at != ""


class TestProxyHotlistProviderErrors:
    """Provider error handling tests."""

    def test_http_error_returns_failing_health(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_raise(urllib.error.URLError("connection refused"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert health.ok is False
        assert health.source == "hotlist_proxy"
        assert "connection refused" in health.error.lower()
        assert stocks == []

    def test_timeout_returns_failing_health(self) -> None:
        """Provider timeout returns structured health and does not raise."""
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_raise(TimeoutError("timed out"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert health.ok is False
        assert "timed out" in health.error.lower()
        assert stocks == []

    def test_timeout_does_not_raise_out_of_collect(self) -> None:
        """Provider timeout must NOT propagate exception to caller."""
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_raise(TimeoutError("timed out"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            # Must not raise
            stocks, health = provider.collect(timeout_ms=5000)

        assert health.ok is False

    def test_invalid_json_returns_failing_health(self) -> None:
        provider = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"not json"
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert health.ok is False
        assert stocks == []


# ═════════════════════════════════════════════════════════════════════════════
# BridgeQuoteProvider
# ═════════════════════════════════════════════════════════════════════════════


class TestBridgeQuoteProviderNormalization:
    """bridge snapshot response maps to quote/depth/money-flow rows."""

    def test_normalizes_quotes(self) -> None:
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is True
        assert health.source == "quote_bridge"
        assert health.row_count == 3
        quotes = data["quotes"]
        assert len(quotes) == 3
        assert quotes[0]["code"] == "000001"
        assert quotes[0]["price"] == 12.50

    def test_normalizes_depth(self) -> None:
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        depth = data["depth"]
        assert len(depth) == 3
        assert depth[0]["code"] == "000001"
        assert depth[0]["bidPrice1"] == 12.49
        assert depth[0]["askPrice1"] == 12.51

    def test_normalizes_money_flow(self) -> None:
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        mf = data["money_flow"]
        assert len(mf) == 3
        assert mf[0]["code"] == "000001"
        assert mf[0]["mainNetInflow"] == 50000000.0

    def test_normalizes_market_meta(self) -> None:
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        meta = data["market_meta"]
        assert meta["totalVolume"] == 500000000000
        assert meta["upCount"] == 2500
        assert meta["downCount"] == 1800

    def test_empty_codes_returns_empty(self) -> None:
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect([], timeout_ms=5000)

        assert health.ok is True
        assert data["quotes"] == []

    def test_codes_passed_in_query_string(self) -> None:
        """Verify codes are passed as comma-separated query parameter."""
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        captured_urls: list[str] = []

        def record_urlopen(req: urllib.request.Request, timeout: float = 0) -> MagicMock:
            captured_urls.append(req.full_url if hasattr(req, "full_url") else str(req))
            return _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE)

        with patch.object(urllib.request, "urlopen", side_effect=record_urlopen):
            provider.collect(["000001", "600000"], timeout_ms=5000)

        assert len(captured_urls) == 1
        url = captured_urls[0]
        assert "codes=000001%2C600000" in url or "codes=000001,600000" in url


class TestBridgeQuoteProviderErrors:
    """Bridge error handling."""

    def test_bridge_offline_returns_failing_health(self) -> None:
        """bridge offline returns SourceHealth(ok=False, error=...)."""
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_OFFLINE_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert health.source == "quote_bridge"
        assert health.error != ""
        assert data["quotes"] == []

    def test_bridge_http_error_returns_failing_health(self) -> None:
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        mock_resp = _fake_urlopen_raise(urllib.error.URLError("connection refused"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert "connection refused" in health.error.lower()

    def test_bridge_timeout_does_not_raise(self) -> None:
        """Provider timeout must NOT propagate exception."""
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        mock_resp = _fake_urlopen_raise(TimeoutError("timed out"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert "timed out" in health.error.lower()

    def test_bridge_ok_false_in_response_body(self) -> None:
        """When response body has ok=False, provider reports failing health."""
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        offline_body = {
            "ok": False,
            "source": "python_bridge",
            "error": "no subscriptions",
            "quotes": [],
            "depth": [],
            "moneyFlow": [],
            "quoteStats": {},
        }
        mock_resp = _fake_urlopen_response(offline_body)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False

    def test_bridge_missing_ok_field_assumes_ok(self) -> None:
        """When response body has no 'ok' field, provider assumes ok=True."""
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        body_without_ok = {
            "quotes": [{"code": "000001", "price": 12.50}],
            "depth": [],
            "moneyFlow": [],
            "quoteStats": {},
        }
        mock_resp = _fake_urlopen_response(body_without_ok)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is True


# ═════════════════════════════════════════════════════════════════════════════
# ThemeMappingProvider
# ═════════════════════════════════════════════════════════════════════════════


class TestThemeMappingProvider:
    """Mongo theme provider maps code to theme list."""

    def test_maps_known_codes_to_theme_lists(self) -> None:
        repo = FakeThemeRepo(THEME_MAP)
        provider = ThemeMappingProvider(repo)
        themes, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is True
        assert health.source == "theme_mapping"
        assert health.row_count == 3
        assert themes["000001"] == ["银行", "深圳"]
        assert themes["600000"] == ["银行", "上海"]
        assert themes["300001"] == ["充电桩", "新基建"]

    def test_unknown_code_returns_empty_list(self) -> None:
        repo = FakeThemeRepo(THEME_MAP)
        provider = ThemeMappingProvider(repo)
        themes, health = provider.collect(["999999"], timeout_ms=5000)

        assert health.ok is True
        assert health.row_count == 1
        assert themes["999999"] == []

    def test_empty_codes_returns_empty_dict(self) -> None:
        repo = FakeThemeRepo(THEME_MAP)
        provider = ThemeMappingProvider(repo)
        themes, health = provider.collect([], timeout_ms=5000)

        assert health.ok is True
        assert health.row_count == 0
        assert themes == {}

    def test_mixed_known_and_unknown_codes(self) -> None:
        repo = FakeThemeRepo(THEME_MAP)
        provider = ThemeMappingProvider(repo)
        themes, health = provider.collect(["000001", "999999"], timeout_ms=5000)

        assert themes["000001"] == ["银行", "深圳"]
        assert themes["999999"] == []

    def test_repo_exception_returns_failing_health(self) -> None:
        """Theme provider gracefully handles repository errors."""
        bad_repo = MagicMock()
        bad_repo.get_stock_themes.side_effect = RuntimeError("MongoDB down")

        provider = ThemeMappingProvider(bad_repo)
        themes, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert health.source == "theme_mapping"
        assert "MongoDB down" in health.error
        # All codes returned empty theme lists — the provider still reports
        # which codes were requested but found nothing
        for code in TEST_CODES:
            assert code in themes
            assert themes[code] == []

    def test_health_contains_latency(self) -> None:
        repo = FakeThemeRepo(THEME_MAP)
        provider = ThemeMappingProvider(repo)
        _, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.latency_ms >= 0


# ═════════════════════════════════════════════════════════════════════════════
# collect_market_context
# ═════════════════════════════════════════════════════════════════════════════


class TestCollectMarketContext:
    """The collect_market_context function assembles all providers into MarketDataContext."""

    def test_assembles_stocks_from_hotlist_provider(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        bridge = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, bridge, theme], TEST_CODES, timeout_ms=5000
            )

        assert len(ctx.stocks) == 3
        assert ctx.stocks[0]["code"] == "000001"

    def test_assembles_quotes_from_bridge_provider(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        bridge = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, bridge, theme], TEST_CODES, timeout_ms=5000
            )

        assert len(ctx.quotes) == 3
        assert ctx.quotes[0]["code"] == "000001"

    def test_assembles_depth_from_bridge_provider(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        bridge = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, bridge, theme], TEST_CODES, timeout_ms=5000
            )

        assert len(ctx.depth) == 3

    def test_assembles_themes_from_theme_provider(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        bridge = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, bridge, theme], TEST_CODES, timeout_ms=5000
            )

        assert ctx.themes["000001"] == ["银行", "深圳"]
        assert ctx.themes["600000"] == ["银行", "上海"]

    def test_aggregates_source_health(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        bridge = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, bridge, theme], TEST_CODES, timeout_ms=5000
            )

        assert len(ctx.source_health) == 3
        sources = {h.source for h in ctx.source_health}
        assert sources == {"hotlist_proxy", "quote_bridge", "theme_mapping"}

    def test_market_meta_from_bridge(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        bridge = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, bridge, theme], TEST_CODES, timeout_ms=5000
            )

        assert ctx.market_meta["totalVolume"] == 500000000000
        assert ctx.market_meta["upCount"] == 2500

    def test_partial_provider_failure_still_assembles_healthy_data(self) -> None:
        """When one provider fails, healthy providers still contribute."""
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        bridge = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        # Bridge fails, hotlist succeeds
        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_raise(urllib.error.URLError("offline")),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, bridge, theme], TEST_CODES, timeout_ms=5000
            )

        # Hotlist still contributed
        assert len(ctx.stocks) == 3
        # Theme still contributed
        assert ctx.themes["000001"] == ["银行", "深圳"]
        # Bridge failed
        assert ctx.quotes == []
        assert ctx.depth == []
        # All health entries present
        assert len(ctx.source_health) == 3
        health_sources = {h.source: h.ok for h in ctx.source_health}
        assert health_sources["hotlist_proxy"] is True
        assert health_sources["quote_bridge"] is False
        assert health_sources["theme_mapping"] is True

    def test_provider_order_does_not_affect_result(self) -> None:
        """Collect market context works regardless of provider order."""
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        bridge = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE),
            ],
        ):
            ctx_ordered = collect_market_context(
                [hotlist, bridge, theme], TEST_CODES, timeout_ms=5000
            )

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE),
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
            ],
        ):
            ctx_reversed = collect_market_context(
                [bridge, theme, hotlist], TEST_CODES, timeout_ms=5000
            )

        assert len(ctx_ordered.stocks) == len(ctx_reversed.stocks)
        assert len(ctx_ordered.quotes) == len(ctx_reversed.quotes)
        assert len(ctx_ordered.depth) == len(ctx_reversed.depth)

    def test_default_timeout_is_used(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            _, health = hotlist.collect()

        assert health.ok is True
