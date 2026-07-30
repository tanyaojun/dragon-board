"""Tests for snapshot_collector providers — Task 7: Providers unit tests.

All external HTTP/Mongo calls are mocked so tests run offline.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.snapshot_collector.models import MarketDataContext, SourceHealth
from backend.snapshot_collector.providers import (
    BridgeQuoteProvider,
    MarketFundCacheProvider,
    ProxyHotlistProvider,
    ProxyLimitUpProvider,
    ProxyMergedHotlistProvider,
    StartupBundleStockProvider,
    TencentBasicQuoteProvider,
    ThemeMappingProvider,
    collect_market_context,
)
from backend.theme_fund_cache import ThemeFundCache


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


def test_market_fund_cache_provider_preserves_last_good_and_missing_values() -> None:
    cache = ThemeFundCache(None, prefix="test")
    cache.put({
        "code": "000001",
        "zlje": 88_000_000,
        "sessionDate": "2026-07-30",
        "moneyFlowSource": "ths_main_monitor",
        "sourceTs": 1,
    })
    provider = MarketFundCacheProvider(cache)

    rows, health = provider.collect(["000001", "000002"])

    assert rows == [{
        "code": "000001",
        "mainNetInflow": 88_000_000.0,
        "moneyFlowSource": "ths_main_monitor",
        "moneyFlowEstimated": False,
        "capitalFlowSource": "ths_main_monitor",
        "capitalFlowConfidence": "high",
    }]
    assert health.ok is False
    assert health.returned_count == 1
    assert health.coverage_ratio == 0.5


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
        "snapshotContext": {
            "breathData": {"overall": 72},
            "marketData": {"upCount": 3200, "downCount": 1800},
        },
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

THS_LIMIT_UP_POOLS_RESPONSE = {
    "ok": True,
    "source": "limitup-ths-pools",
    "date": "20260623",
    "pools": {
        "one": {
            "ok": True,
            "items": [
                {
                    "stock_code": "000001",
                    "stock_name": "平安银行",
                    "limit_up_reason": "金融科技",
                    "limit_up_time": "09:45:00",
                    "last_limit_up_time": "14:20:00",
                    "continue_day": 1,
                    "volume_money": 68000000,
                    "turnover_rate": 5.6,
                }
            ],
        },
        "failed": {
            "ok": True,
            "items": [
                {
                    "stock_code": "600000",
                    "stock_name": "浦发银行",
                    "reason_type": "银行",
                    "first_limit_up_time": "10:05:00",
                    "high_days": "2天2板",
                    "order_amount": 12000000,
                }
            ],
        },
    },
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
# TencentBasicQuoteProvider
# ═════════════════════════════════════════════════════════════════════════════


class TestTencentBasicQuoteProvider:
    @pytest.mark.parametrize("raw_value", [None, "", 0, "0", "nan"])
    def test_omits_unavailable_or_nonpositive_volume_ratio(self, raw_value: Any) -> None:
        provider = TencentBasicQuoteProvider(base_url=PROXY_BASE_URL)

        row = provider._normalize_row({"f12": "000001", "f14": "平安银行", "f10": raw_value})

        assert row is not None
        assert "volumeRatio" not in row

    def test_preserves_positive_volume_ratio(self) -> None:
        provider = TencentBasicQuoteProvider(base_url=PROXY_BASE_URL)

        row = provider._normalize_row({"f12": "000001", "f14": "平安银行", "f10": "1.88"})

        assert row is not None
        assert row["volumeRatio"] == 1.88

    def test_empty_codes_report_no_data_without_requesting_upstream(self) -> None:
        provider = TencentBasicQuoteProvider(base_url=PROXY_BASE_URL)

        with patch.object(urllib.request, "urlopen") as urlopen:
            rows, health = provider.collect([], timeout_ms=5000)

        urlopen.assert_not_called()
        assert rows == {}
        assert health.ok is False
        assert health.requested_count == 0
        assert health.coverage_ratio == 0.0
        assert health.error == "no requested codes"


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

    def test_collect_preserves_rank_formula_inputs_from_platform_data(self) -> None:
        provider = StartupBundleStockProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        mock_resp = _fake_urlopen_response(STARTUP_BUNDLE_RESPONSE)

        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            stocks, health = provider.collect(timeout_ms=5000)

        assert health.details["rankProvenance"]["platformTotals"] == {
            "eastmoney": 1,
            "ths": 1,
            "kpl": 0,
            "tdx": 0,
            "xueqiu": 0,
            "cls": 0,
            "tgb": 0,
            "dzh": 0,
        }
        assert health.details["rankProvenance"]["formulaVersion"] == "weighted_platform_percentile_v1"
        ping_an = next(stock for stock in stocks if stock["code"] == "000001")
        assert ping_an["emRank"] == 1
        assert ping_an["thsRank"] == 999
        assert ping_an["platforms"] == 1
        assert ping_an["avgRankNum"] == pytest.approx(100.0)
        assert ping_an["avgRank"] == "100.0"

    def test_collect_discards_stale_raw_ranks_not_present_in_platform_data(self) -> None:
        body = deepcopy(STARTUP_BUNDLE_RESPONSE)
        body["data"]["stocks"][2]["emRank"] = 5
        provider = StartupBundleStockProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")

        with patch.object(urllib.request, "urlopen", return_value=_fake_urlopen_response(body)):
            stocks, _ = provider.collect(timeout_ms=5000)

        absent = next(stock for stock in stocks if stock["code"] == "300001")
        assert absent["emRank"] == 999

    def test_collect_reads_normalized_cls_and_dzh_rows_from_platform_data(self) -> None:
        body = deepcopy(STARTUP_BUNDLE_RESPONSE)
        body["data"]["platformData"].update({
            "cls": [{"rank": 3, "code": "000001", "name": "平安银行", "rawData": {}}],
            "dzh": [{"rank": 4, "code": "600000", "name": "浦发银行", "rawData": {}}],
        })
        provider = StartupBundleStockProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")

        with patch.object(urllib.request, "urlopen", return_value=_fake_urlopen_response(body)):
            stocks, _ = provider.collect(timeout_ms=5000)

        ping_an = next(stock for stock in stocks if stock["code"] == "000001")
        pudong = next(stock for stock in stocks if stock["code"] == "600000")
        assert ping_an["clsRank"] == 3
        assert pudong["dzhRank"] == 4

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

    def test_missing_snapshot_context_preserves_stocks_but_reports_degraded_health(self) -> None:
        body = deepcopy(STARTUP_BUNDLE_RESPONSE)
        body["data"].pop("snapshotContext")
        provider = StartupBundleStockProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")

        with patch.object(urllib.request, "urlopen", return_value=_fake_urlopen_response(body)):
            stocks, health = provider.collect(timeout_ms=5000)

        assert len(stocks) == 3
        assert health.ok is False
        assert health.coverage_ratio == 1.0
        assert "snapshotContext" in health.error


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


class TestProxyMergedHotlistProviderRankProvenance:
    def test_collect_preserves_raw_platform_ranks_and_formula_inputs(self) -> None:
        provider = ProxyMergedHotlistProvider(base_url=PROXY_BASE_URL)

        def respond(req: urllib.request.Request, timeout: float = 0) -> MagicMock:
            del timeout
            return _fake_urlopen_response(_hotlist_response_for_url(req.full_url))

        with patch.object(urllib.request, "urlopen", side_effect=respond):
            stocks, health = provider.collect(timeout_ms=5000)

        ping_an = next(stock for stock in stocks if stock["code"] == "000001")
        assert ping_an["emRank"] == 1
        assert ping_an["thsRank"] == 1
        assert ping_an["kplRank"] == 1
        assert ping_an["xqRank"] == 1
        assert health.details["rankProvenance"]["platformTotals"] == {
            "eastmoney": 3,
            "ths": 3,
            "kpl": 2,
            "tdx": 1,
            "xueqiu": 1,
            "cls": 1,
            "tgb": 1,
            "dzh": 1,
        }
        assert health.details["rankProvenance"]["defaultRank"] == 999

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

    def test_ignores_bridge_http_money_flow(self) -> None:
        provider = BridgeQuoteProvider(base_url=BRIDGE_BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_SNAPSHOT_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert data["money_flow"] == []

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

    def test_merges_bounded_tencent_quotes_after_stock_codes_are_known(self) -> None:
        startup = StartupBundleStockProvider(base_url=PROXY_BASE_URL)
        tencent = TencentBasicQuoteProvider(base_url=PROXY_BASE_URL)
        startup_rows = [
            {"code": "000001", "name": "平安银行", "rank": 1},
            {"code": "600000", "name": "浦发银行", "rank": 2},
        ]
        with (
            patch.object(startup, "collect", return_value=(startup_rows, SourceHealth("startup_bundle", True))),
            patch.object(
                tencent,
                "collect",
                return_value=(
                    {"000001": {"code": "000001", "volumeRatio": 1.8}},
                    SourceHealth("theme_quote_tencent", True, row_count=1),
                ),
            ) as collect_quotes,
        ):
            ctx = collect_market_context([startup, tencent], [], timeout_ms=5000)

        collect_quotes.assert_called_once_with(["000001", "600000"], timeout_ms=5000)
        assert ctx.quotes == [{"code": "000001", "volumeRatio": 1.8}]

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
# ProxyLimitUpProvider
# ═════════════════════════════════════════════════════════════════════════════


class TestProxyLimitUpProvider:
    """ProxyLimitUpProvider maps THS pool data to stock enrichment fields."""

    def test_collect_maps_limitup_pool_fields_by_code(self) -> None:
        provider = ProxyLimitUpProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        mock_resp = _fake_urlopen_response(THS_LIMIT_UP_POOLS_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            rows, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is True
        assert health.source == "limitup_proxy"
        assert health.row_count == 2

        by_code = {row["code"]: row for row in rows}
        assert by_code["000001"]["limitUpPool"] == "one"
        assert by_code["000001"]["reason"] == "金融科技"
        assert by_code["000001"]["firstZtTime"] == "09:45:00"
        assert by_code["000001"]["lastZtTime"] == "14:20:00"
        assert by_code["000001"]["boardHeight"] == 1
        assert by_code["000001"]["highDays"] == 1
        assert by_code["000001"]["fengdan"] == 68000000.0
        assert by_code["000001"]["turnoverRate"] == 5.6

        assert by_code["600000"]["limitUpPool"] == "failed"
        assert by_code["600000"]["boardHeight"] == 2

    def test_collect_filters_to_requested_codes(self) -> None:
        provider = ProxyLimitUpProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        mock_resp = _fake_urlopen_response(THS_LIMIT_UP_POOLS_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            rows, health = provider.collect(["000001"], timeout_ms=5000)

        assert health.ok is True
        assert [row["code"] for row in rows] == ["000001"]

    def test_degraded_proxy_envelope_returns_failing_health(self) -> None:
        provider = ProxyLimitUpProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        degraded = {
            "ok": False,
            "degraded": True,
            "source": "limitup-ths-pools",
            "message": "fallback",
            "error": "upstream unavailable",
            "pools": {},
        }
        mock_resp = _fake_urlopen_response(degraded)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            rows, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert rows == []
        assert health.ok is False
        assert "upstream unavailable" in health.error

    def test_degraded_proxy_envelope_preserves_available_pool_items(self) -> None:
        provider = ProxyLimitUpProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        degraded = {
            "ok": False,
            "degraded": True,
            "error": "one pool failed",
            "pools": THS_LIMIT_UP_POOLS_RESPONSE["pools"],
        }
        mock_resp = _fake_urlopen_response(degraded)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            rows, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert "one pool failed" in health.error
        assert {row["code"] for row in rows} == {"000001", "600000"}

    def test_collect_decodes_frontend_limitup_field_shapes(self) -> None:
        provider = ProxyLimitUpProvider(base_url=PROXY_BASE_URL, trading_date="2026-06-23")
        response = {
            "ok": True,
            "pools": {
                "high": {
                    "items": [
                        {
                            "stock_code": "000001",
                            "first_limit_up_time": 1778827443,
                            "last_limit_up_time": 1778827443,
                            "high_days": "5天3板",
                            "high_days_value": 196613,
                        }
                    ],
                },
                "one": {
                    "items": [
                        {
                            "stock_code": "600000",
                            "limit_up_time": "09:45",
                            "high_days_value": 196613,
                        }
                    ],
                },
            },
        }
        mock_resp = _fake_urlopen_response(response)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            rows, health = provider.collect(TEST_CODES, timeout_ms=5000)

        by_code = {row["code"]: row for row in rows}
        assert health.ok is True
        assert by_code["000001"]["firstZtTime"] == "14:44:03"
        assert by_code["000001"]["lastZtTime"] == "14:44:03"
        assert by_code["000001"]["boardHeight"] == 3
        assert by_code["600000"]["firstZtTime"] == "09:45:00"
        assert by_code["600000"]["boardHeight"] == 3
