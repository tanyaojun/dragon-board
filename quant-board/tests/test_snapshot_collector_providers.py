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
    ProxyMergedHotlistProvider,
    ProxyQuoteProvider,
    StartupBundleStockProvider,
    ThemeMappingProvider,
    _eastmoney_rows_to_money_flow,
    _eastmoney_rows_to_quotes,
    _extract_eastmoney_diff,
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

STARTUP_BUNDLE_RESPONSE = {
    "ok": True,
    "data": {
        "schemaVersion": 1,
        "tradingDate": "2026-06-23",
        "createdAt": 1782207600000,
        "platformData": {
            "eastmoney": [{"code": "000001", "rank": 1}],
            "ths": [{"code": "600000", "rank": 1}],
        },
        "stocks": [
            {
                "code": "000001",
                "name": "平安银行",
                "rank": 1,
                "compRank": 1,
                "price": 12.5,
                "change": 2.35,
                "volume": 150000000,
                "turnover": 1875000000.0,
                "turnoverRate": 5.5,
                "hotness": 92,
            },
            {
                "code": "600000",
                "name": "浦发银行",
                "rank": 2,
                "compRank": 2,
                "price": 9.8,
                "change": -0.51,
                "volume": 80000000,
                "turnover": 784000000.0,
                "turnoverRate": 2.1,
                "hotness": 75,
            },
            {
                "code": "300001",
                "name": "特锐德",
                "rank": 3,
                "compRank": 3,
                "price": 25.3,
                "change": 5.2,
                "volume": 12000000,
                "turnover": 320000000.0,
                "turnoverRate": 8.3,
                "hotness": 88,
            },
        ],
    },
    "dragonMeta": {"cache": {"hit": True, "stale": False}},
}


def _hotlist_response_for_url(url: str) -> dict[str, Any]:
    if "/api/eastmoney/hot" in url:
        return {
            "data": [
                {"sc": "SZ000001", "sn": "平安银行"},
                {"sc": "SH600000", "sn": "浦发银行"},
                {"sc": "SZ300001", "sn": "特锐德"},
            ]
        }
    if "/api/ths/hot" in url:
        return {
            "data": {
                "stock_list": [
                    {"code": "000001", "name": "平安银行", "order": 1},
                    {"code": "600000", "name": "浦发银行", "order": 2},
                    {"code": "300002", "name": "神州泰岳", "order": 3},
                ]
            }
        }
    if "/api/kpl/hot" in url:
        return {
            "List": [
                ["000001", "平安银行", "1.2", "", "1"],
                ["300003", "乐普医疗", "3.4", "", "2"],
            ]
        }
    if "/api/tdx/hot" in url:
        return [
            ["meta"],
            ["meta"],
            ["meta"],
            ["", "600004", "白云机场", "0.5", "", "", "", "", "", "", "1"],
        ]
    if "/api/xueqiu/hot" in url:
        return {"data": {"items": [{"code": "SZ000001", "name": "平安银行"}]}}
    if "/api/cls/hot" in url:
        return {"errno": 0, "data": [{"stock": {"StockID": "600005", "name": "武钢股份"}}]}
    if "/api/tgb/hot" in url:
        return {"dto": [{"fullCode": "600006", "stockName": "东风汽车", "ranking": 1}]}
    if "/api/dzh/hot" in url:
        return {"result": [{"SH600007": 99}]}
    return {}


# ═════════════════════════════════════════════════════════════════════════════
# StartupBundleStockProvider
# ═════════════════════════════════════════════════════════════════════════════


class TestStartupBundleStockProvider:
    """startup bundle provider reuses live's merged stock pool."""

    def test_collect_reads_complete_merged_stocks_from_startup_bundle(self) -> None:
        provider = StartupBundleStockProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        mock_resp = _fake_urlopen_response(STARTUP_BUNDLE_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert health.ok is True
        assert health.source == "startup_bundle"
        assert health.row_count == 3
        assert health.coverage_ratio == 1.0
        assert len(stocks) == 3
        assert stocks[0]["code"] == "000001"
        assert stocks[0]["rank"] == 1
        assert stocks[0]["pctChange"] == 2.35
        assert stocks[0]["amount"] == 1875000000.0
        assert stocks[0]["turnover"] == 1875000000.0
        assert stocks[0]["turnoverRate"] == 5.5

    def test_collect_uses_default_today_key_when_trading_date_missing(self) -> None:
        provider = StartupBundleStockProvider(base_url=PROXY_BASE_URL)
        captured_urls: list[str] = []

        def record_urlopen(req: urllib.request.Request, timeout: float = 0) -> MagicMock:
            captured_urls.append(req.full_url if hasattr(req, "full_url") else str(req))
            return _fake_urlopen_response(STARTUP_BUNDLE_RESPONSE)

        with patch.object(urllib.request, "urlopen", side_effect=record_urlopen):
            provider.collect(timeout_ms=5000)

        assert len(captured_urls) == 1
        assert "/api/cache/startup-bundle" in captured_urls[0]
        assert "key=default%3A" in captured_urls[0]

    def test_missing_bundle_returns_failing_health(self) -> None:
        provider = StartupBundleStockProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        mock_resp = _fake_urlopen_response({"ok": True, "data": None})
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert stocks == []
        assert health.ok is False
        assert health.source == "startup_bundle"
        assert "missing" in health.error


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

    def test_derives_bridge_and_theme_codes_from_hotlist_when_codes_empty(self) -> None:
        """Service wiring passes no initial codes; providers must use hotlist codes."""
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        bridge = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))
        captured_urls: list[str] = []

        def record_urlopen(req: urllib.request.Request, timeout: float = 0) -> MagicMock:
            captured_urls.append(req.full_url if hasattr(req, "full_url") else str(req))
            if len(captured_urls) == 1:
                return _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE)
            return _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE)

        with patch.object(urllib.request, "urlopen", side_effect=record_urlopen):
            ctx = collect_market_context([hotlist, bridge, theme], [], timeout_ms=5000)

        assert len(ctx.stocks) == 3
        assert len(ctx.quotes) == 3
        assert ctx.themes["000001"] == ["银行", "深圳"]
        assert any("codes=000001%2C600000%2C300001" in url for url in captured_urls)

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


# ═════════════════════════════════════════════════════════════════════════════
# ProxyQuoteProvider
# ═════════════════════════════════════════════════════════════════════════════

EASTMONEY_QUOTE_RESPONSE = {
    "rc": 0,
    "data": {
        "diff": [
            {
                "f12": "000001",
                "f14": "平安银行",
                "f2": 12.50,
                "f3": 2.35,
                "f5": 150000000,
                "f6": 1875000000.0,
                "f8": 5.5,
                "f9": 8.5,
                "f10": 12.22,
                "f20": 350000000000.0,
                "f21": 345000000000.0,
                "f23": 0.85,
                "f62": 50000000.0,
                "f66": 20000000.0,
                "f69": 15000000.0,
                "f184": 10000000.0,
            },
            {
                "f12": "600000",
                "f14": "浦发银行",
                "f2": 9.80,
                "f3": -0.51,
                "f5": 80000000,
                "f6": 784000000.0,
                "f8": 2.1,
                "f9": 5.2,
                "f10": 9.85,
                "f20": 180000000000.0,
                "f21": 178000000000.0,
                "f23": 0.72,
                "f62": -10000000.0,
                "f66": -5000000.0,
                "f69": -3000000.0,
                "f184": -2000000.0,
            },
            {
                "f12": "300001",
                "f14": "特锐德",
                "f2": 25.30,
                "f3": 5.20,
                "f5": 12000000,
                "f6": 320000000.0,
                "f8": 8.3,
                "f9": 35.0,
                "f10": 24.05,
                "f20": 80000000000.0,
                "f21": 78000000000.0,
                "f23": 1.15,
                "f62": 30000000.0,
                "f66": 15000000.0,
                "f69": 10000000.0,
                "f184": 3000000.0,
            },
        ]
    },
}


class TestEastmoneyExtractDiff:
    """Unit tests for _extract_eastmoney_diff helper."""

    def test_extracts_diff_from_valid_body(self) -> None:
        result = _extract_eastmoney_diff(EASTMONEY_QUOTE_RESPONSE)
        assert len(result) == 3

    def test_returns_empty_when_body_is_none(self) -> None:
        assert _extract_eastmoney_diff(None) == []

    def test_returns_empty_when_body_is_list(self) -> None:
        assert _extract_eastmoney_diff([{"f12": "000001"}]) == []

    def test_returns_empty_when_no_data_key(self) -> None:
        assert _extract_eastmoney_diff({"rc": 0}) == []

    def test_returns_empty_when_data_is_not_dict(self) -> None:
        assert _extract_eastmoney_diff({"data": []}) == []

    def test_returns_empty_when_diff_is_not_list(self) -> None:
        assert _extract_eastmoney_diff({"data": {"diff": "not_list"}}) == []


class TestEastmoneyRowsToQuotes:
    """Unit tests for _eastmoney_rows_to_quotes field mapping."""

    def test_maps_all_expected_fields(self) -> None:
        rows = EASTMONEY_QUOTE_RESPONSE["data"]["diff"]
        quotes = _eastmoney_rows_to_quotes(rows)
        assert len(quotes) == 3

        q0 = quotes[0]
        assert q0["code"] == "000001"
        assert q0["name"] == "平安银行"
        assert q0["price"] == 12.50
        assert q0["pctChange"] == 2.35
        assert q0["volume"] == 150000000
        assert q0["amount"] == 1875000000.0
        assert q0["turnover"] == 5.5
        assert q0["pe"] == 8.5
        assert q0["totalMarketValue"] == 350000000000.0

    def test_skips_rows_with_missing_code(self) -> None:
        quotes = _eastmoney_rows_to_quotes([{"f2": 12.50, "f14": "NoCode"}])
        assert quotes == []

    def test_skips_rows_with_blank_code(self) -> None:
        quotes = _eastmoney_rows_to_quotes([{"f12": "", "f2": 12.50}])
        assert quotes == []

    def test_handles_empty_list(self) -> None:
        assert _eastmoney_rows_to_quotes([]) == []

    def test_handles_non_dict_items(self) -> None:
        quotes = _eastmoney_rows_to_quotes(["not_a_dict", {"f12": "000001", "f2": 10.0}])
        assert len(quotes) == 1
        assert quotes[0]["code"] == "000001"

    def test_missing_numeric_fields_default_to_zero(self) -> None:
        quotes = _eastmoney_rows_to_quotes([{"f12": "000001"}])
        q = quotes[0]
        assert q["price"] == 0.0
        assert q["pctChange"] == 0.0
        assert q["volume"] == 0
        assert q["amount"] == 0.0
        assert q["turnover"] == 0.0
        assert q["pe"] == 0.0
        assert q["totalMarketValue"] == 0.0


class TestEastmoneyRowsToMoneyFlow:
    """Unit tests for _eastmoney_rows_to_money_flow derivation."""

    def test_maps_all_money_flow_fields(self) -> None:
        rows = EASTMONEY_QUOTE_RESPONSE["data"]["diff"]
        flows = _eastmoney_rows_to_money_flow(rows)
        assert len(flows) == 3

        f0 = flows[0]
        assert f0["code"] == "000001"
        assert f0["mainNetInflow"] == 50000000.0
        assert f0["superLargeNetInflow"] == 20000000.0
        assert f0["largeNetInflow"] == 15000000.0
        assert f0["smallNetInflow"] == 10000000.0

    def test_medium_net_inflow_is_derived(self) -> None:
        """mediumNetInflow = main - superLarge - large - small"""
        rows = EASTMONEY_QUOTE_RESPONSE["data"]["diff"]
        flows = _eastmoney_rows_to_money_flow(rows)

        # 000001: 50000000 - 20000000 - 15000000 - 10000000 = 5000000
        assert flows[0]["mediumNetInflow"] == 5000000.0

        # 600000: -10000000 - (-5000000) - (-3000000) - (-2000000) = 0
        assert flows[1]["mediumNetInflow"] == 0.0

        # 300001: 30000000 - 15000000 - 10000000 - 3000000 = 2000000
        assert flows[2]["mediumNetInflow"] == 2000000.0

    def test_skips_rows_with_missing_code(self) -> None:
        flows = _eastmoney_rows_to_money_flow([{"f62": 100.0}])
        assert flows == []

    def test_handles_empty_list(self) -> None:
        assert _eastmoney_rows_to_money_flow([]) == []

    def test_missing_fields_default_to_zero(self) -> None:
        flows = _eastmoney_rows_to_money_flow([{"f12": "000001"}])
        f = flows[0]
        assert f["mainNetInflow"] == 0.0
        assert f["superLargeNetInflow"] == 0.0
        assert f["largeNetInflow"] == 0.0
        assert f["mediumNetInflow"] == 0.0
        assert f["smallNetInflow"] == 0.0


class TestProxyQuoteProviderNormalization:
    """ProxyQuoteProvider happy-path tests."""

    def test_collect_returns_quotes_and_money_flow(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response(EASTMONEY_QUOTE_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is True
        assert health.source == "quote_proxy"
        assert health.row_count == 3

        quotes = data["quotes"]
        assert len(quotes) == 3
        assert quotes[0]["code"] == "000001"
        assert quotes[0]["price"] == 12.50

        money_flow = data["money_flow"]
        assert len(money_flow) == 3
        assert money_flow[0]["code"] == "000001"
        assert money_flow[0]["mainNetInflow"] == 50000000.0

        assert data["depth"] == []
        assert data["market_meta"] == {}

    def test_empty_codes_returns_empty_success(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        data, health = provider.collect([], timeout_ms=5000)

        assert health.ok is True
        assert health.row_count == 0
        assert data["quotes"] == []
        assert data["money_flow"] == []

    def test_none_codes_returns_empty_success(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        data, health = provider.collect(None, timeout_ms=5000)

        assert health.ok is True
        assert data["quotes"] == []

    def test_empty_diff_returns_empty_lists(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response({"rc": 0, "data": {"diff": []}})
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is True
        assert data["quotes"] == []
        assert data["money_flow"] == []

    def test_health_contains_latency(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_response(EASTMONEY_QUOTE_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            _, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.latency_ms >= 0
        assert health.captured_at != ""


class TestProxyQuoteProviderErrors:
    """ProxyQuoteProvider error handling."""

    def test_degraded_proxy_envelope_returns_failing_health(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        degraded_body = {
            "ok": False,
            "degraded": True,
            "source": "quotes-eastmoney",
            "message": "fallback",
            "error": "upstream unavailable",
            "data": {"diff": []},
        }
        mock_resp = _fake_urlopen_response(degraded_body)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert health.source == "quote_proxy"
        assert "upstream unavailable" in health.error
        assert data["quotes"] == []
        assert data["money_flow"] == []

    def test_http_error_returns_failing_health(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_raise(urllib.error.URLError("connection refused"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert health.source == "quote_proxy"
        assert "connection refused" in health.error.lower()
        assert data["quotes"] == []

    def test_timeout_returns_failing_health(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_raise(TimeoutError("timed out"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert "timed out" in health.error.lower()

    def test_timeout_does_not_raise(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        mock_resp = _fake_urlopen_raise(TimeoutError("timed out"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False

    def test_invalid_json_returns_failing_health(self) -> None:
        provider = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"not json"
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False


# ═════════════════════════════════════════════════════════════════════════════
# collect_market_context with ProxyQuoteProvider
# ═════════════════════════════════════════════════════════════════════════════


class TestCollectMarketContextWithProxyQuoteProvider:
    """collect_market_context routes ProxyQuoteProvider identically to BridgeQuoteProvider."""

    def test_proxy_quote_provider_populates_quotes(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        quote = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(EASTMONEY_QUOTE_RESPONSE),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, quote, theme], TEST_CODES, timeout_ms=5000
            )

        assert len(ctx.quotes) == 3
        assert ctx.quotes[0]["code"] == "000001"
        assert ctx.money_flow[0]["code"] == "000001"
        assert ctx.depth == []
        assert ctx.market_meta == {}

    def test_proxy_quote_provider_populates_money_flow(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        quote = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(EASTMONEY_QUOTE_RESPONSE),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, quote, theme], TEST_CODES, timeout_ms=5000
            )

        assert len(ctx.money_flow) == 3
        assert ctx.money_flow[0]["mainNetInflow"] == 50000000.0
        assert ctx.money_flow[0]["mediumNetInflow"] == 5000000.0
        assert ctx.money_flow[1]["mainNetInflow"] == -10000000.0

    def test_derives_quote_codes_from_hotlist_when_codes_empty(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        quote = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))
        captured_urls: list[str] = []

        def record_urlopen(req: urllib.request.Request, timeout: float = 0) -> MagicMock:
            captured_urls.append(req.full_url if hasattr(req, "full_url") else str(req))
            if len(captured_urls) == 1:
                return _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE)
            return _fake_urlopen_response(EASTMONEY_QUOTE_RESPONSE)

        with patch.object(urllib.request, "urlopen", side_effect=record_urlopen):
            ctx = collect_market_context([hotlist, quote, theme], [], timeout_ms=5000)

        assert len(ctx.stocks) == 3
        assert len(ctx.quotes) == 3
        assert len(ctx.money_flow) == 3

    def test_quote_failure_still_assembles_healthy_data(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        quote = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_raise(urllib.error.URLError("offline")),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, quote, theme], TEST_CODES, timeout_ms=5000
            )

        assert len(ctx.stocks) == 3
        assert ctx.quotes == []
        assert ctx.money_flow == []
        assert ctx.themes["000001"] == ["银行", "深圳"]

        health_sources = {h.source: h.ok for h in ctx.source_health}
        assert health_sources["hotlist_proxy"] is True
        assert health_sources["quote_proxy"] is False
        assert health_sources["theme_mapping"] is True

    def test_aggregates_source_health_with_proxy_quote(self) -> None:
        hotlist = ProxyHotlistProvider(base_url=PROXY_BASE_URL)
        quote = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        theme = ThemeMappingProvider(FakeThemeRepo(THEME_MAP))

        with patch.object(
            urllib.request, "urlopen",
            side_effect=[
                _fake_urlopen_response(EASTMONEY_HOTLIST_RESPONSE),
                _fake_urlopen_response(EASTMONEY_QUOTE_RESPONSE),
            ],
        ):
            ctx = collect_market_context(
                [hotlist, quote, theme], TEST_CODES, timeout_ms=5000
            )

        assert len(ctx.source_health) == 3
        sources = {h.source for h in ctx.source_health}
        assert sources == {"hotlist_proxy", "quote_proxy", "theme_mapping"}

    def test_startup_bundle_is_primary_stock_pool_and_hotlist_is_fallback(self) -> None:
        startup = StartupBundleStockProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        hotlist = ProxyMergedHotlistProvider(base_url=PROXY_BASE_URL)
        quote = ProxyQuoteProvider(base_url=PROXY_BASE_URL)
        captured_urls: list[str] = []

        def record_urlopen(req: urllib.request.Request, timeout: float = 0) -> MagicMock:
            captured_urls.append(req.full_url if hasattr(req, "full_url") else str(req))
            if len(captured_urls) == 1:
                return _fake_urlopen_response(STARTUP_BUNDLE_RESPONSE)
            return _fake_urlopen_response(EASTMONEY_QUOTE_RESPONSE)

        with patch.object(urllib.request, "urlopen", side_effect=record_urlopen):
            ctx = collect_market_context([startup, hotlist, quote], [], timeout_ms=5000)

        assert len(ctx.stocks) == 3
        assert [row["code"] for row in ctx.stocks] == ["000001", "600000", "300001"]
        assert all("eastmoney/hot" not in url for url in captured_urls)
        assert any("quotes/eastmoney" in url for url in captured_urls)
        assert any(h.source == "startup_bundle" and h.ok for h in ctx.source_health)

    def test_merged_hotlist_fallback_runs_when_startup_bundle_missing(self) -> None:
        startup = StartupBundleStockProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        hotlist = ProxyMergedHotlistProvider(base_url=PROXY_BASE_URL)
        captured_urls: list[str] = []

        def record_urlopen(req: urllib.request.Request, timeout: float = 0) -> MagicMock:
            captured_urls.append(req.full_url if hasattr(req, "full_url") else str(req))
            if len(captured_urls) == 1:
                return _fake_urlopen_response({"ok": True, "data": None})
            return _fake_urlopen_response(_hotlist_response_for_url(captured_urls[-1]))

        with patch.object(urllib.request, "urlopen", side_effect=record_urlopen):
            ctx = collect_market_context([startup, hotlist], [], timeout_ms=5000)

        assert len(ctx.stocks) == 9
        assert {row["code"] for row in ctx.stocks} == {
            "000001",
            "600000",
            "300001",
            "300002",
            "300003",
            "600004",
            "600005",
            "600006",
            "600007",
        }
        assert ctx.stocks[0]["emRank"] == 1
        assert ctx.stocks[0]["thsRank"] == 1
        assert ctx.stocks[0]["kplRank"] == 1
        assert ctx.stocks[0]["platforms"] == 4
        assert ctx.stocks[0]["avgRank"] != "999"
        assert any("cache/startup-bundle" in url for url in captured_urls)
        assert any("eastmoney/hot" in url for url in captured_urls)
        assert any("ths/hot" in url for url in captured_urls)
        assert any("kpl/hot" in url for url in captured_urls)
        health_sources = {h.source: h.ok for h in ctx.source_health}
        assert health_sources["startup_bundle"] is False
        assert health_sources["merged_hotlist_proxy"] is True
