import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from main import BridgeConfig, QuoteFetchStats, TdxL2Bridge
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


if __name__ == "__main__":
    unittest.main()
