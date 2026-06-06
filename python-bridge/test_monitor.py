import os
import sys
import unittest
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from main import (
    BridgeConfig,
    OpeningRawQuoteFileSink,
    QuoteFetchStats,
    TdxL2Bridge,
    is_opening_sampling_window,
    normalize_quote_row,
)
from fastapi.testclient import TestClient


class BridgeMonitorTest(unittest.TestCase):
    def test_status_snapshot_exposes_runtime_metrics(self):
        bridge = TdxL2Bridge(BridgeConfig())
        bridge.tdx_connected = True
        bridge.active_server = ("218.6.170.47", 7709)
        bridge.latest_quotes = {"000001": "{}", "600000": "{}"}
        bridge.latest_depth = {"000001": "{}"}
        bridge.latest_quote_stats = QuoteFetchStats(
            requested_codes=3,
            batches=2,
            truncated_batches=1,
            slow_batches=1,
            received_quotes=2,
            received_depth=1,
            elapsed_ms=321,
        )
        bridge.last_quote_cycle_ts = 1778752800000
        bridge.last_quote_error = "partial data"

        status = bridge.status_snapshot()

        self.assertTrue(status["ok"])
        self.assertEqual(status["service"], "tdx-quote-bridge")
        self.assertEqual(status["websocket"]["url"], "ws://127.0.0.1:8765/ws/quotes")
        self.assertEqual(status["tdx"]["activeServer"], "218.6.170.47:7709")
        self.assertEqual(status["quotes"]["received"], 2)
        self.assertEqual(status["quotes"]["depth"], 1)
        self.assertEqual(status["quotes"]["lastCycle"]["elapsedMs"], 321)
        self.assertEqual(status["quotes"]["lastError"], "partial data")

    def test_fastapi_app_exposes_docs_monitor_and_status(self):
        bridge = TdxL2Bridge(BridgeConfig())
        app = bridge.create_app()
        client = TestClient(app)

        docs = client.get("/docs")
        self.assertEqual(docs.status_code, 200)
        self.assertIn("swagger-ui", docs.text.lower())

        monitor = client.get("/monitor")
        self.assertEqual(monitor.status_code, 200)
        self.assertIn("TDX Bridge Monitor", monitor.text)

        status = client.get("/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["service"], "tdx-quote-bridge")

    def test_opening_sampling_window_uses_cycle_start_and_end(self):
        start = datetime.fromisoformat("2026-05-22T09:24:49+08:00")
        end = datetime.fromisoformat("2026-05-22T09:25:02+08:00")

        self.assertTrue(is_opening_sampling_window(start, end))

    def test_opening_sampling_window_starts_at_initial_baseline(self):
        start = datetime.fromisoformat("2026-05-22T09:20:00+08:00")
        end = datetime.fromisoformat("2026-05-22T09:20:01+08:00")

        self.assertTrue(is_opening_sampling_window(start, end))

    def test_opening_sampling_window_includes_call_auction_start(self):
        start = datetime.fromisoformat("2026-05-22T09:15:00+08:00")
        end = datetime.fromisoformat("2026-05-22T09:15:01+08:00")

        self.assertTrue(is_opening_sampling_window(start, end))

    def test_opening_raw_quote_sink_writes_jsonl_rows(self):
        with self.subTest("bridge raw quote evidence"):
            import json
            import tempfile

            with tempfile.TemporaryDirectory() as temp_dir:
                sink = OpeningRawQuoteFileSink(temp_dir)
                sink.record_many(
                    [
                        {
                            "code": "002552",
                            "name": "宝鼎科技",
                            "capturedAt": "2026-05-22T09:15:00+08:00",
                            "lastPrice": 9.8,
                            "preClose": 10,
                            "amount": 1000000,
                            "volume": 100000,
                            "openingForcedSample": True,
                            "requestedCount": 1,
                            "receivedCount": 1,
                        }
                    ],
                    source="mootdx-bridge",
                )

                path = os.path.join(temp_dir, "opening-raw-quotes-2026-05-22.jsonl")
                with open(path, encoding="utf-8") as handle:
                    row = json.loads(handle.readline())

                self.assertEqual(row["source"], "mootdx-bridge")
                self.assertEqual(row["code"], "002552")
                self.assertEqual(row["lastPrice"], 9.8)
                self.assertTrue(row["openingForcedSample"])

    def test_quote_capture_timestamp_uses_batch_start_time(self):
        quote = normalize_quote_row(
            {
                "code": "002552",
                "price": 35.68,
                "last_close": 36.2,
                "amount": 6000000,
                "volume": 1680000,
            },
            captured_ms=1779413100000,
        )

        self.assertIsNotNone(quote)
        self.assertEqual(quote["capturedAt"], "2026-05-22T09:25:00+08:00")
        self.assertEqual(quote["sourceTs"], 1779413100000)

    def test_fetch_quotes_refetches_missing_codes_from_truncated_batch(self):
        class FakeQuoteClient:
            def quotes(self, symbol):
                if len(symbol) > 1:
                    return [
                        {"code": code, "price": 10.0, "last_close": 9.5, "amount": 1000, "volume": 100}
                        for code in symbol[:8]
                    ]
                code = symbol[0]
                return [
                    {"code": code, "price": 10.0, "last_close": 9.5, "amount": 1000, "volume": 100}
                ]

        bridge = TdxL2Bridge(BridgeConfig(quote_batch_size=40))
        bridge.quote_client = FakeQuoteClient()
        bridge.tdx_connected = True
        codes = [f"600{i:03d}" for i in range(39)] + ["600360"]

        quotes, _depth, stats = asyncio.run(bridge.fetch_quotes_and_depth(codes))

        self.assertIn("600360", {item["code"] for item in quotes})
        self.assertEqual(40, stats.received_quotes)
        self.assertEqual(1, stats.truncated_batches)


if __name__ == "__main__":
    unittest.main()
