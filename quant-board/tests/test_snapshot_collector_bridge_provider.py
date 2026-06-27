"""Tests for Phase 2: BridgeQuoteProvider pool-based collection.

All external HTTP calls are mocked so tests run offline.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.snapshot_collector.models import SourceHealth
from backend.snapshot_collector.providers import BridgeQuoteProvider

# ── Helpers ───────────────────────────────────────────────────────────────────


def _fake_urlopen_response(data: dict[str, Any], status: int = 200) -> MagicMock:
    """Build a MagicMock that behaves like urlopen context manager with JSON body."""
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


# ── Sample data ─────────────────────────────────────────────────────────────

BRIDGE_POOL_SNAPSHOT = {
    "ok": True,
    "source": "python_bridge",
    "serverTs": 1781170800000,
    "subscribedCount": 2,
    "pooled": True,
    "poolRefreshedAt": int(time.time() * 1000) - 5000,  # 5 s ago, not stale
    "quotes": [
        {"code": "000001", "price": 12.50, "pctChange": 2.35, "volume": 150000, "amount": 1800000.0, "high": 12.80, "low": 12.20, "preClose": 12.00},
        {"code": "600000", "price": 9.80, "pctChange": -0.51, "volume": 80000, "amount": 784000.0},
    ],
    "depth": [
        {"code": "000001", "bidPrice1": 12.49, "askPrice1": 12.51},
        {"code": "600000", "bidPrice1": 9.79, "askPrice1": 9.81},
    ],
    "moneyFlow": [
        {"code": "000001", "mainNetInflow": 500000.0},
        {"code": "600000", "mainNetInflow": -100000.0},
    ],
    "quoteStats": {"totalVolume": 10000000, "upCount": 1200, "downCount": 900},
    "l2": {},
}

BRIDGE_POOL_DEPTH_BOOK_SNAPSHOT = {
    **BRIDGE_POOL_SNAPSHOT,
    "depth": [
        {
            "code": "000001",
            "bids": [{"price": 12.49, "volume": 10000}],
            "asks": [{"price": 12.51, "volume": 8000}],
            "sourceTs": 1781170800000,
        }
    ],
}

BRIDGE_POOL_REAL_QUOTE_SHAPE_SNAPSHOT = {
    **BRIDGE_POOL_SNAPSHOT,
    "quotes": [
        {
            "code": "000001",
            "lastPrice": 12.50,
            "changePct": 2.35,
            "volume": 150000,
            "amount": 1800000.0,
            "turnoverRate": 5.5,
            "high": 12.80,
            "low": 12.20,
            "preClose": 12.00,
        }
    ],
}

BRIDGE_POOL_STALE_SNAPSHOT = {
    **BRIDGE_POOL_SNAPSHOT,
    "poolRefreshedAt": int(time.time() * 1000) - 60000,  # 60 s ago, stale
}

BRIDGE_SET_POOL_RESPONSE = {
    "ok": True,
    "codes": ["000001", "600000"],
    "count": 2,
    "setAt": int(time.time() * 1000),
}

BRIDGE_SET_POOL_EMPTY = {
    "ok": True,
    "codes": [],
    "count": 0,
    "setAt": int(time.time() * 1000),
}

BRIDGE_POOL_EMPTY_ERROR = {
    "ok": False,
    "error": "missing codes parameter and backend pool is empty",
    "source": "python_bridge",
    "serverTs": int(time.time() * 1000),
    "subscribedCount": 0,
    "quotes": [],
    "depth": [],
    "ticks": [],
    "moneyFlow": [],
    "quoteStats": {},
    "l2": {},
}

BRIDGE_DIRECT_SNAPSHOT = {
    "ok": True,
    "source": "python_bridge",
    "serverTs": 1781170800000,
    "subscribedCount": 2,
    "quotes": [
        {"code": "000001", "price": 12.50, "pctChange": 2.35, "volume": 150000, "amount": 1800000.0},
        {"code": "600000", "price": 9.80, "pctChange": -0.51, "volume": 80000, "amount": 784000.0},
    ],
    "depth": [],
    "moneyFlow": [],
    "quoteStats": {},
    "l2": {},
}

BASE_URL = "http://127.0.0.1:8765"
TEST_CODES = ["000001", "600000"]


# ═════════════════════════════════════════════════════════════════════════════
# set_pool()
# ═════════════════════════════════════════════════════════════════════════════


class TestBridgeQuoteProviderSetPool:
    """set_pool() calls POST /api/quotes/subscriptions."""

    def test_set_pool_calls_subscriptions_endpoint(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_SET_POOL_RESPONSE)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            result = provider.set_pool(TEST_CODES, timeout_ms=5000)

        assert result["ok"] is True
        assert result["count"] == 2
        assert result["codes"] == ["000001", "600000"]

    def test_set_pool_empty_codes(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_SET_POOL_EMPTY)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            result = provider.set_pool([], timeout_ms=5000)

        assert result["ok"] is True
        assert result["count"] == 0
        assert result["codes"] == []

    def test_set_pool_http_error_returns_failing_payload(self) -> None:
        """set_pool never raises — errors are captured in return dict."""
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_raise(urllib.error.URLError("connection refused"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            result = provider.set_pool(TEST_CODES, timeout_ms=5000)

        assert result["ok"] is False
        assert "connection refused" in result.get("error", "").lower()

    def test_set_pool_timeout_does_not_raise(self) -> None:
        """set_pool must not propagate exception."""
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_raise(TimeoutError("timed out"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            result = provider.set_pool(TEST_CODES, timeout_ms=5000)

        assert result["ok"] is False
        assert "timed out" in result.get("error", "").lower()


# ═════════════════════════════════════════════════════════════════════════════
# collect(use_pool=True)
# ═════════════════════════════════════════════════════════════════════════════


class TestBridgeQuoteProviderCollectPool:
    """collect(use_pool=True) fetches from pool without codes param."""

    def test_collect_pool_returns_quotes(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert health.ok is True
        assert health.source == "quote_bridge"
        assert len(data["quotes"]) == 2
        assert data["quotes"][0]["code"] == "000001"
        assert data["quotes"][0]["high"] == 12.80
        assert data["quotes"][0]["low"] == 12.20
        assert data["quotes"][0]["preClose"] == 12.00

    def test_collect_pool_normalizes_real_bridge_quote_shape(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_REAL_QUOTE_SHAPE_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert health.ok is True
        assert data["quotes"][0]["price"] == 12.50
        assert data["quotes"][0]["pctChange"] == 2.35
        assert data["quotes"][0]["turnover"] == 5.5
        assert data["quotes"][0]["high"] == 12.80

    def test_collect_pool_returns_depth(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert len(data["depth"]) == 2
        assert data["depth"][0]["code"] == "000001"

    def test_collect_pool_preserves_depth_book_shape(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_DEPTH_BOOK_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert health.ok is True
        assert data["depth"][0]["bids"][0] == {"price": 12.49, "volume": 10000}
        assert data["depth"][0]["asks"][0] == {"price": 12.51, "volume": 8000}

    def test_collect_pool_returns_money_flow(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert len(data["money_flow"]) == 2

    def test_collect_pool_returns_market_meta(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert data["market_meta"]["totalVolume"] == 10000000
        assert data["market_meta"]["upCount"] == 1200

    def test_collect_pool_empty_pool_returns_failing_health(self) -> None:
        """When bridge returns ok=false for empty pool, provider reports failure."""
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_EMPTY_ERROR)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert health.ok is False
        assert "pool is empty" in health.error.lower()
        assert data["quotes"] == []

    def test_collect_pool_ignores_codes_parameter(self) -> None:
        """When use_pool=True, explicit codes are ignored."""
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_SNAPSHOT)
        captured_urls: list[str] = []

        def record_urlopen(req: urllib.request.Request, timeout: float = 0) -> MagicMock:
            url = req.full_url if hasattr(req, "full_url") else str(req)
            captured_urls.append(url)
            return _fake_urlopen_response(BRIDGE_POOL_SNAPSHOT)

        with patch.object(urllib.request, "urlopen", side_effect=record_urlopen):
            # Pass codes but use_pool=True — codes should be ignored
            provider.collect(["999999"], use_pool=True, timeout_ms=5000)

        assert len(captured_urls) == 1
        url = captured_urls[0]
        # Pool mode should NOT have codes query param
        assert "codes=" not in url

    def test_collect_pool_vs_direct_uses_different_url(self) -> None:
        """Pool mode and direct mode hit different URLs."""
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        captured_urls: list[str] = []

        def record_urlopen(req: urllib.request.Request, timeout: float = 0) -> MagicMock:
            url = req.full_url if hasattr(req, "full_url") else str(req)
            captured_urls.append(url)
            return _fake_urlopen_response(BRIDGE_POOL_SNAPSHOT)

        with patch.object(urllib.request, "urlopen", side_effect=record_urlopen):
            # Pool mode
            provider.collect(use_pool=True, timeout_ms=5000)
            # Direct mode
            provider.collect(["000001"], timeout_ms=5000)

        assert len(captured_urls) == 2
        pool_url = captured_urls[0]
        direct_url = captured_urls[1]
        assert "codes=" not in pool_url
        assert "codes=000001" in direct_url


# ═════════════════════════════════════════════════════════════════════════════
# Staleness detection
# ═════════════════════════════════════════════════════════════════════════════


class TestBridgeQuoteProviderStaleness:
    """Pool staleness detection adds quote_stale warning to SourceHealth."""

    def test_non_stale_pool_has_no_stale_warning(self) -> None:
        """Data refreshed 5 s ago is not stale (default threshold is 30 s)."""
        provider = BridgeQuoteProvider(base_url=BASE_URL, pool_staleness_ms=30000)
        body = dict(BRIDGE_POOL_SNAPSHOT)
        body["poolRefreshedAt"] = int(time.time() * 1000) - 5000
        mock_resp = _fake_urlopen_response(body)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            _, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert health.ok is True
        assert "quote_stale" not in health.error

    def test_stale_pool_adds_warning(self) -> None:
        """Data refreshed 60 s ago exceeds 30 s threshold."""
        provider = BridgeQuoteProvider(base_url=BASE_URL, pool_staleness_ms=30000)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_STALE_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            _, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert health.ok is True  # staleness is a warning, not a failure
        assert "quote_stale" in health.error
        assert "pool data" in health.error.lower()

    def test_direct_mode_never_stale(self) -> None:
        """Direct collection (use_pool=False) never triggers staleness check."""
        provider = BridgeQuoteProvider(base_url=BASE_URL, pool_staleness_ms=30000)
        # Even if the response somehow has pooled=true, direct mode ignores it
        body_with_pooled = {
            "ok": True,
            "quotes": [{"code": "000001", "price": 12.50}],
            "depth": [],
            "moneyFlow": [],
            "quoteStats": {},
            "pooled": True,
            "poolRefreshedAt": int(time.time() * 1000) - 60000,
        }
        mock_resp = _fake_urlopen_response(body_with_pooled)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            _, health = provider.collect(["000001"], timeout_ms=5000)

        assert health.ok is True
        # Even though response has pooled=True, we used explicit codes so no staleness check
        assert "quote_stale" not in health.error

    def test_staleness_respects_custom_threshold(self) -> None:
        """Custom pool_staleness_ms is used."""
        # 5 s old data with 3 s threshold should be stale
        provider = BridgeQuoteProvider(base_url=BASE_URL, pool_staleness_ms=3000)
        mock_resp = _fake_urlopen_response(BRIDGE_POOL_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            _, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert "quote_stale" in health.error

    def test_zero_pool_refreshed_at_no_warning(self) -> None:
        """When poolRefreshedAt is 0, staleness check is skipped."""
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        body = {
            **BRIDGE_POOL_SNAPSHOT,
            "poolRefreshedAt": 0,
        }
        mock_resp = _fake_urlopen_response(body)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            _, health = provider.collect(use_pool=True, timeout_ms=5000)

        assert health.ok is True
        assert "quote_stale" not in health.error


# ═════════════════════════════════════════════════════════════════════════════
# Regression: collect() still works with explicit codes
# ═════════════════════════════════════════════════════════════════════════════


class TestBridgeQuoteProviderDirectCollectionRegression:
    """Phase 1 signature continues to work."""

    def test_collect_with_explicit_codes_still_works(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_DIRECT_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is True
        assert len(data["quotes"]) == 2

    def test_collect_empty_codes_returns_empty(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        data, health = provider.collect([], timeout_ms=5000)

        assert health.ok is True
        assert data["quotes"] == []

    def test_collect_default_timeout(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_response(BRIDGE_DIRECT_SNAPSHOT)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            _, health = provider.collect(TEST_CODES)

        assert health.ok is True

    def test_collect_http_error_still_captured(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        mock_resp = _fake_urlopen_raise(urllib.error.URLError("offline"))
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert "offline" in health.error.lower()
        assert data["quotes"] == []

    def test_collect_bridge_ok_false_still_captured(self) -> None:
        provider = BridgeQuoteProvider(base_url=BASE_URL)
        offline_body = {
            "ok": False,
            "error": "TDX server unreachable",
            "quotes": [],
            "depth": [],
            "moneyFlow": [],
            "quoteStats": {},
        }
        mock_resp = _fake_urlopen_response(offline_body)
        with patch.object(urllib.request, "urlopen", return_value=mock_resp):
            data, health = provider.collect(TEST_CODES, timeout_ms=5000)

        assert health.ok is False
        assert "TDX" in health.error
