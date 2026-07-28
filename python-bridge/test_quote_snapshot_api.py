import asyncio
import os
import sys
import threading
import time
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(__file__))

from main import (
    BridgeConfig,
    QuoteFetchStats,
    TdxL2Bridge,
    is_trading_session_now,
    latest_completed_trading_date,
    normalize_code,
    resolve_requested_session_date,
    resolve_minute_session_date,
)
from fastapi.testclient import TestClient


class QuoteSnapshotApiTest(unittest.TestCase):
    def setUp(self):
        self.bridge = TdxL2Bridge(BridgeConfig())
        self.app = self.bridge.create_app()
        self.client = TestClient(self.app)

    def test_bridge_has_no_dashboard_money_flow_runtime(self):
        self.assertFalse(hasattr(self.bridge, "set_money_flow_pool"))
        self.assertFalse(hasattr(self.bridge, "aggregate_money_flow_pool"))
        self.assertFalse(hasattr(self.bridge, "get_accumulated_money_flow"))
        self.assertFalse(hasattr(self.bridge, "big_order"))

    def test_calendar_reports_unavailable_without_guessing(self):
        with patch("main._is_trading_day_cached", return_value=None):
            response = self.client.get("/api/calendar?date=2026-07-25")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["errorCode"], "tdx_calendar_unavailable")
        self.assertIsNone(response.json()["isTradingDay"])

    def test_minute_session_date_uses_today_during_session_and_completed_date_off_session(self):
        session = __import__("datetime").datetime(2026, 7, 24, 10, 0).astimezone()
        before_open = __import__("datetime").datetime(2026, 7, 24, 9, 0).astimezone()
        weekend = __import__("datetime").datetime(2026, 7, 25, 10, 0).astimezone()

        with patch("main._is_trading_day_cached", side_effect=lambda value: value.date().isoformat() == "2026-07-24"), patch(
            "main.latest_completed_trading_date",
            return_value=__import__("datetime").datetime(2026, 7, 23).astimezone(),
        ):
            self.assertEqual(resolve_minute_session_date(session), ("20260724", False))
            self.assertEqual(resolve_minute_session_date(before_open), ("20260723", True))
            self.assertEqual(resolve_minute_session_date(weekend), ("20260723", True))

    def test_post_close_session_ends_at_1530_and_only_completes_afterwards(self):
        session_end = __import__("datetime").datetime(2026, 7, 24, 15, 30)
        after_close = __import__("datetime").datetime(2026, 7, 24, 15, 31)

        with patch("main._is_trading_day_cached", return_value=True):
            self.assertTrue(is_trading_session_now(session_end))
            self.assertEqual(latest_completed_trading_date(session_end).date().isoformat(), "2026-07-23")
            self.assertEqual(latest_completed_trading_date(after_close), after_close)

    def test_requested_non_trading_day_resolves_to_previous_sse_session(self):
        with patch(
            "main._is_trading_day_cached",
            side_effect=lambda value: value.date().isoformat() == "2026-07-24",
        ):
            self.assertEqual(resolve_requested_session_date("20260725"), "20260724")

    def test_requested_session_fails_when_calendar_is_unavailable(self):
        with patch("main._is_trading_day_cached", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "TDX trading calendar unavailable"):
                resolve_requested_session_date("20260724")

    def test_minute_endpoint_uses_realtime_mootdx_api_during_session(self):
        class TrackingLock:
            entered = False

            async def __aenter__(self):
                self.entered = True

            async def __aexit__(self, exc_type, exc, tb):
                self.entered = False

        lock = TrackingLock()

        class FakeQuoteClient:
            def minute(self, *, symbol):
                self.symbol = symbol
                assert lock.entered
                return [
                    {"price": 10.0, "vol": 2},
                    {"price": 10.5, "vol": 3},
                ]

        quote_client = FakeQuoteClient()
        self.bridge.quote_client = quote_client
        self.bridge.fetch_lock = lock

        with patch("main.resolve_minute_session_date", return_value=("20260724", False)):
            response = self.client.get("/api/quotes/minute?code=002297")

        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(quote_client.symbol, "002297")
        self.assertEqual(data["date"], "20260724")
        self.assertFalse(data["complete"])
        self.assertFalse(data["expectedComplete"])
        self.assertEqual(data["points"][0]["cumulativeVolume"], 2)
        self.assertEqual(data["points"][0]["cumulativeAmount"], 2000)
        self.assertEqual(data["points"][1]["cumulativeAmount"], 5150)

    def test_minute_endpoint_uses_requested_session_date_for_historical_data(self):
        class FakeQuoteClient:
            def minutes(self, *, symbol, date):
                self.symbol = symbol
                self.date = date
                return [{"price": 10.0, "vol": 2}]

        quote_client = FakeQuoteClient()
        self.bridge.quote_client = quote_client
        with patch("main.resolve_requested_session_date", return_value="20260724"):
            response = self.client.get("/api/quotes/minute?code=002297&date=20260725")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(quote_client.symbol, "002297")
        self.assertEqual(quote_client.date, "20260724")
        self.assertEqual(response.json()["data"]["date"], "20260724")

    def test_minute_endpoint_uses_realtime_api_for_explicit_current_session(self):
        class FakeQuoteClient:
            def minute(self, *, symbol):
                self.symbol = symbol
                return [{"price": 10.0, "vol": 2}]

            def minutes(self, *, symbol, date):
                raise AssertionError("historical API must not be used during the current session")

        quote_client = FakeQuoteClient()
        self.bridge.quote_client = quote_client
        with patch("main.resolve_requested_session_date", return_value="20260727"), patch(
            "main.resolve_minute_session_date", return_value=("20260727", False)
        ):
            response = self.client.get("/api/quotes/minute?code=002297&date=20260727")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(quote_client.symbol, "002297")
        self.assertFalse(response.json()["data"]["expectedComplete"])

    def test_minute_endpoint_uses_history_api_when_explicit_today_resolves_back(self):
        class FakeQuoteClient:
            def minute(self, *, symbol):
                raise AssertionError("realtime API must not be used for a completed session")

            def minutes(self, *, symbol, date):
                self.symbol = symbol
                self.date = date
                return [{"price": 10.0, "vol": 2}]

        quote_client = FakeQuoteClient()
        self.bridge.quote_client = quote_client
        with patch("main.resolve_requested_session_date", return_value="20260724"), patch(
            "main.resolve_minute_session_date", return_value=("20260724", True)
        ):
            response = self.client.get("/api/quotes/minute?code=002297&date=20260727")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(quote_client.symbol, "002297")
        self.assertEqual(quote_client.date, "20260724")
        self.assertTrue(response.json()["data"]["expectedComplete"])

    def test_minute_endpoint_uses_previous_session_for_explicit_today_before_open(self):
        today = __import__("datetime").datetime.now().astimezone().strftime("%Y%m%d")

        class FakeQuoteClient:
            def minute(self, *, symbol):
                raise AssertionError("realtime API must not be used before open")

            def minutes(self, *, symbol, date):
                self.symbol = symbol
                self.date = date
                return [{"price": 10.0, "vol": 2}]

        quote_client = FakeQuoteClient()
        self.bridge.quote_client = quote_client
        with patch("main.resolve_requested_session_date", return_value=today), patch(
            "main.resolve_minute_session_date", return_value=("20260724", True)
        ):
            response = self.client.get(
                "/api/quotes/minute?code=002297&date=" + today
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(quote_client.symbol, "002297")
        self.assertEqual(quote_client.date, "20260724")
        self.assertEqual(response.json()["data"]["date"], "20260724")

    def test_minute_endpoint_marks_incomplete_completed_session_without_padding(self):
        class FakeQuoteClient:
            def minutes(self, *, symbol, date):
                del symbol, date
                return [{"price": 10.0, "vol": 2}]

        self.bridge.quote_client = FakeQuoteClient()
        with patch("main.resolve_minute_session_date", return_value=("20260724", True)):
            response = self.client.get("/api/quotes/minute?code=002297")

        data = response.json()["data"]
        self.assertTrue(data["expectedComplete"])
        self.assertFalse(data["complete"])
        self.assertEqual(len(data["points"]), 1)

    def test_minute_endpoint_marks_240_point_completed_session_complete(self):
        class FakeQuoteClient:
            def minutes(self, *, symbol, date):
                del symbol, date
                return [{"price": 10.0, "vol": 2} for _ in range(240)]

        self.bridge.quote_client = FakeQuoteClient()
        with patch("main.resolve_minute_session_date", return_value=("20260724", True)):
            response = self.client.get("/api/quotes/minute?code=002297")

        data = response.json()["data"]
        self.assertTrue(data["expectedComplete"])
        self.assertTrue(data["complete"])
        self.assertEqual(len(data["points"]), 240)

    def test_minute_endpoint_rejects_negative_volume(self):
        class FakeQuoteClient:
            def minute(self, *, symbol):
                del symbol
                return [{"price": 10.0, "vol": -1}]

        self.bridge.quote_client = FakeQuoteClient()
        with patch("main.resolve_minute_session_date", return_value=("20260724", False)):
            response = self.client.get("/api/quotes/minute?code=002297")

        self.assertEqual(response.status_code, 500)
        self.assertFalse(response.json()["ok"])
        self.assertIn("invalid minute row", response.json()["error"])

    def test_minute_and_quote_fetches_do_not_enter_tdx_client_together(self):
        guard = threading.Lock()
        active = 0
        peak = 0

        class FakeQuoteClient:
            @staticmethod
            def _track():
                nonlocal active, peak
                with guard:
                    active += 1
                    peak = max(peak, active)
                time.sleep(0.03)
                with guard:
                    active -= 1

            def minute(self, *, symbol):
                del symbol
                self._track()
                return [{"price": 10.0, "vol": 1}]

            def quotes(self, *, symbol):
                self._track()
                return [
                    {"code": code, "price": 10.0, "last_close": 9.5, "amount": 1000, "volume": 1}
                    for code in symbol
                ]

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True
        minute_endpoint = next(
            route.endpoint for route in self.app.routes if route.path == "/api/quotes/minute"
        )

        async def fetch_both():
            return await asyncio.gather(
                minute_endpoint(code="002297"),
                self.bridge.fetch_quotes_and_depth(["002297"]),
            )

        with patch("main.resolve_minute_session_date", return_value=("20260724", False)):
            minute_response, _ = asyncio.run(fetch_both())
            self.assertEqual(minute_response.status_code, 200)

        self.assertEqual(peak, 1)

    # ── positive cases ────────────────────────────────────────────────

    def test_snapshot_returns_structured_payload_for_valid_codes(self):
        """GET /api/quotes/snapshot?codes=000001,600000 returns ok=true with quotes and depth."""

        class FakeQuoteClient:
            def quotes(self, symbol):
                results = []
                for code in symbol:
                    results.append(
                        {
                            "code": code,
                            "price": 10.0 + (int(code) % 100),
                            "last_close": 9.5,
                            "amount": 1000000,
                            "volume": 100000,
                            "open": 9.6,
                            "high": 10.2,
                            "low": 9.4,
                        }
                    )
                return results

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True

        response = self.client.get("/api/quotes/snapshot?codes=000001,600000")
        self.assertEqual(response.status_code, 200)

        payload = response.json()
        self.assertTrue(payload["ok"], f"Expected ok=true, got {payload}")
        self.assertEqual(payload["source"], "python_bridge")
        self.assertIsInstance(payload["serverTs"], int)
        self.assertGreater(payload["serverTs"], 0)
        self.assertEqual(payload["subscribedCount"], 2)
        self.assertIsInstance(payload["quotes"], list)
        self.assertGreater(len(payload["quotes"]), 0, "Should return at least one quote")
        self.assertIsInstance(payload["depth"], list)
        self.assertIsInstance(payload["ticks"], list)
        self.assertNotIn("moneyFlow", payload)
        self.assertIsInstance(payload["quoteStats"], dict)
        self.assertIsInstance(payload["l2"], dict)

        # Verify quote shape
        first_quote = payload["quotes"][0]
        self.assertIn("code", first_quote)
        self.assertIn("lastPrice", first_quote)
        self.assertIn("changePct", first_quote)
        self.assertIn("volume", first_quote)

    def test_snapshot_does_not_require_websocket_subscription(self):
        """The HTTP endpoint works without any browser WebSocket clients."""

        class FakeQuoteClient:
            def quotes(self, symbol):
                return [
                    {
                        "code": code,
                        "price": 12.5,
                        "last_close": 12.0,
                        "amount": 500000,
                        "volume": 40000,
                    }
                    for code in symbol
                ]

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True
        # Verify no clients are connected
        self.assertEqual(len(self.bridge.clients), 0)

        response = self.client.get("/api/quotes/snapshot?codes=000001")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        # WebSocket client count should remain 0
        self.assertEqual(len(self.bridge.clients), 0)

    def test_snapshot_handles_single_code(self):
        """Single code query works identically."""

        class FakeQuoteClient:
            def quotes(self, symbol):
                return [
                    {
                        "code": symbol[0],
                        "price": 22.3,
                        "last_close": 22.0,
                        "amount": 300000,
                        "volume": 13500,
                    }
                ]

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True

        response = self.client.get("/api/quotes/snapshot?codes=000001")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["subscribedCount"], 1)
        self.assertEqual(len(payload["quotes"]), 1)

    def test_snapshot_normalizes_mixed_format_codes(self):
        """Codes like 000001.SZ or sh000001 are normalized to 6-digit."""

        class FakeQuoteClient:
            def quotes(self, symbol):
                return [
                    {
                        "code": normalize_code(s),
                        "price": 8.0,
                        "last_close": 7.8,
                        "amount": 0,
                        "volume": 0,
                    }
                    for s in symbol
                ]

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True

        response = self.client.get("/api/quotes/snapshot?codes=000001.SZ,sh600000")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["subscribedCount"], 2)

    # ── error / offline cases ─────────────────────────────────────────

    def test_missing_codes_parameter_returns_ok_false(self):
        """Missing codes parameter returns ok=false with error message."""
        response = self.client.get("/api/quotes/snapshot")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)
        self.assertIn("missing", payload.get("error", "").lower())
        self.assertEqual(payload["source"], "python_bridge")

    def test_empty_codes_parameter_returns_ok_false(self):
        """Empty codes string returns ok=false."""
        response = self.client.get("/api/quotes/snapshot?codes=")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)

    def test_bridge_offline_returns_ok_false_with_error(self):
        """When bridge cannot fetch quotes, return ok=false with error field."""

        class FailingQuoteClient:
            def quotes(self, symbol):
                raise RuntimeError("TDX server unreachable")

        self.bridge.quote_client = FailingQuoteClient()
        self.bridge.tdx_connected = False

        response = self.client.get("/api/quotes/snapshot?codes=000001")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("error", payload)
        self.assertIn("batches failed", payload["error"])
        self.assertEqual(payload["source"], "python_bridge")
        self.assertEqual(payload["quotes"], [])
        self.assertEqual(payload["depth"], [])

    def test_bridge_quote_returns_all_top_level_keys_even_on_error(self):
        """Error response still includes the full payload shape."""
        response = self.client.get("/api/quotes/snapshot?codes=")
        payload = response.json()
        expected_keys = {
            "ok",
            "source",
            "serverTs",
            "subscribedCount",
            "quotes",
            "depth",
            "ticks",
            "quoteStats",
            "l2",
        }
        self.assertTrue(
            expected_keys.issubset(set(payload.keys())),
            f"Missing keys: {expected_keys - set(payload.keys())}",
        )

    # ── existing websocket route untouched ────────────────────────────

    def test_existing_routes_remain_accessible(self):
        """The existing health, status, metrics, and monitor routes still work."""
        for path, expected_text in (
            ("/health", "tdx-quote-bridge"),
            ("/status", "tdx-quote-bridge"),
            ("/metrics", "service=tdx-quote-bridge"),
            ("/monitor", "TDX Bridge Monitor"),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(
                    response.status_code,
                    200,
                    f"Route {path} should return 200",
                )
                # /health and /status return JSON
                if path in ("/health", "/status"):
                    self.assertEqual(response.json()["service"], "tdx-quote-bridge")
                else:
                    self.assertIn(expected_text, response.text)

    def test_websocket_route_exists_in_app(self):
        """The /ws/quotes WebSocket route is still defined."""
        route_paths = [route.path for route in self.app.routes]
        self.assertIn("/ws/quotes", route_paths)

    # ── l2 field reflects actual bridge state ─────────────────────────

    def test_l2_field_reflects_actual_l2_state(self):
        """The l2 field in snapshot response reflects bridge l2_state, not labeled as official L2."""

        class FakeQuoteClient:
            def quotes(self, symbol):
                return [
                    {
                        "code": "000001",
                        "price": 10.0,
                        "last_close": 9.5,
                        "amount": 100000,
                        "volume": 10000,
                    }
                ]

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True
        # L2 is disabled by default
        self.assertFalse(self.bridge.config.l2_enabled)

        response = self.client.get("/api/quotes/snapshot?codes=000001")
        payload = response.json()
        self.assertTrue(payload["ok"])
        l2 = payload["l2"]
        self.assertIsInstance(l2, dict)
        self.assertEqual(l2.get("enabled"), False)
        # The l2 status should reflect disabled/not-official-L2
        self.assertIn(l2.get("status", ""), ("disabled", "pending"))

    # ── quoteStats reflects fetch metrics ────────────────────────────

    def test_quote_stats_reflects_fetch_metrics(self):
        """quoteStats includes requestedCount, receivedCount, elapsedMs etc."""

        class FakeQuoteClient:
            def quotes(self, symbol):
                return [
                    {
                        "code": code,
                        "price": 15.0,
                        "last_close": 14.5,
                        "amount": 200000,
                        "volume": 13333,
                    }
                    for code in symbol
                ]

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True

        response = self.client.get("/api/quotes/snapshot?codes=000001,600000")
        payload = response.json()
        self.assertTrue(payload["ok"])
        stats = payload["quoteStats"]
        self.assertIsInstance(stats, dict)
        self.assertIn("requestedCount", stats)
        self.assertEqual(stats["requestedCount"], 2)
        self.assertIn("receivedCount", stats)
        self.assertGreaterEqual(stats["receivedCount"], 1)
        self.assertIn("elapsedMs", stats)


    # ── Phase 2: backend subscription pool ──────────────────────────────

    def test_set_subscriptions_pool_returns_ok(self):
        """POST /api/quotes/subscriptions sets pool and returns ok=true with codes."""
        self.bridge.fetch_quotes_and_depth = AsyncMock(
            return_value=([], [], QuoteFetchStats())
        )
        response = self.client.post(
            "/api/quotes/subscriptions",
            json={"codes": ["000001", "600000", "300001"]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 3)
        self.assertEqual(payload["codes"], ["000001", "600000", "300001"])
        self.assertGreater(payload["setAt"], 0)

    def test_set_subscriptions_pool_normalizes_codes(self):
        """POST /api/quotes/subscriptions normalizes malformed codes."""
        self.bridge.fetch_quotes_and_depth = AsyncMock(
            return_value=([], [], QuoteFetchStats())
        )
        response = self.client.post(
            "/api/quotes/subscriptions",
            json={"codes": ["000001.SZ", "sh600000", "", "  "]},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["codes"], ["000001", "600000"])

    def test_set_subscriptions_pool_empty_clears_pool(self):
        """POST /api/quotes/subscriptions with empty codes clears the pool."""
        self.bridge.fetch_quotes_and_depth = AsyncMock(
            return_value=([], [], QuoteFetchStats())
        )
        # First set a pool
        self.client.post(
            "/api/quotes/subscriptions",
            json={"codes": ["000001"]},
        )
        # Then clear it
        response = self.client.post(
            "/api/quotes/subscriptions",
            json={"codes": []},
        )
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["codes"], [])

    def test_snapshot_uses_pool_when_no_codes_param(self):
        """GET /api/quotes/snapshot without codes param returns pooled data."""

        class FakeQuoteClient:
            def quotes(self, symbol):
                return [
                    {
                        "code": code,
                        "price": 10.0,
                        "last_close": 9.5,
                        "amount": 1000000,
                        "volume": 100000,
                    }
                    for code in symbol
                ]

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True

        # Set pool first
        self.client.post(
            "/api/quotes/subscriptions",
            json={"codes": ["000001", "600000"]},
        )

        # Now request snapshot without codes param
        response = self.client.get("/api/quotes/snapshot")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["subscribedCount"], 2)
        self.assertGreater(len(payload["quotes"]), 0)
        # Should have pooled metadata
        self.assertTrue(payload.get("pooled"), "Expected pooled=True")
        self.assertGreater(payload.get("poolRefreshedAt", 0), 0)

    def test_snapshot_without_codes_and_empty_pool_returns_error(self):
        """GET /api/quotes/snapshot without codes and empty pool returns ok=false."""
        # Ensure pool is empty (default state)
        response = self.client.get("/api/quotes/snapshot")
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("pool is empty", payload.get("error", ""))

    def test_pool_codes_survive_multiple_snapshot_requests(self):
        """Pool codes persist across multiple snapshot requests."""

        class FakeQuoteClient:
            def quotes(self, symbol):
                return [
                    {
                        "code": code,
                        "price": 10.0 + len(symbol),
                        "last_close": 9.5,
                        "amount": 1000000,
                        "volume": 100000,
                    }
                    for code in symbol
                ]

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True

        # Set pool
        self.client.post(
            "/api/quotes/subscriptions",
            json={"codes": ["000001", "600000"]},
        )

        # First snapshot
        r1 = self.client.get("/api/quotes/snapshot")
        p1 = r1.json()
        self.assertTrue(p1["ok"])
        self.assertEqual(p1["subscribedCount"], 2)

        # Second snapshot — pool should still be active
        r2 = self.client.get("/api/quotes/snapshot")
        p2 = r2.json()
        self.assertTrue(p2["ok"])
        self.assertEqual(p2["subscribedCount"], 2)

    def test_snapshot_with_explicit_codes_ignores_pool(self):
        """When codes param is provided, pool is not used."""
        self.bridge.fetch_quotes_and_depth = AsyncMock(
            return_value=([], [], QuoteFetchStats())
        )
        # Set pool first
        self.client.post(
            "/api/quotes/subscriptions",
            json={"codes": ["000001", "600000"]},
        )

        # Request with explicit codes parameter
        response = self.client.get("/api/quotes/snapshot?codes=300001")
        payload = response.json()
        # If this returns ok=false it's because there's no quote_client,
        # but the key point is that the subscribedCount should be 1 (from
        # the explicit codes), not 2 (from the pool).
        self.assertEqual(
            payload["subscribedCount"],
            1,
            f"Expected subscribedCount=1 (explicit codes), got {payload['subscribedCount']}",
        )
        # pooled should NOT appear when explicit codes are provided
        self.assertNotIn("pooled", payload)

    def test_subscription_endpoint_missing_codes_key(self):
        """POST /api/quotes/subscriptions with missing codes key treats as empty."""
        response = self.client.post(
            "/api/quotes/subscriptions",
            json={"other": "data"},
        )
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["codes"], [])

    def test_pool_snapshot_refreshes_pool_timestamp(self):
        """A fresh pool fetch must not be reported with the pool creation timestamp."""

        class FakeQuoteClient:
            def quotes(self, symbol):
                return [
                    {
                        "code": code,
                        "price": 10.0,
                        "last_close": 9.5,
                        "amount": 1000000,
                        "volume": 100000,
                    }
                    for code in symbol
                ]

        self.bridge.quote_client = FakeQuoteClient()
        self.bridge.tdx_connected = True
        created = self.client.post(
            "/api/quotes/subscriptions", json={"codes": ["000001"]}
        ).json()["setAt"]
        time.sleep(0.01)

        payload = self.client.get("/api/quotes/snapshot").json()

        self.assertGreater(payload["poolRefreshedAt"], created)


if __name__ == "__main__":
    unittest.main()
