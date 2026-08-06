r"""fetch_ticks 非交易时段源头跳过测试。

背景（2026-08-06）：tdxpy 非交易时段调用分笔接口（get_transaction_data）会打
DeprecationWarning「目前不是交易时间段...」并返回 None。fetch_ticks 从源头跳过
非交易时段的调用（与 tdxpy time_frame 同一判断），行为与 tdxpy 返回 None 等价，
同时消除警告刷屏与无意义请求。

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_tick_fetch -v
"""

import asyncio
import unittest
from collections import defaultdict, deque
from unittest import mock

import pandas as pd

import main as main_mod
from main import TdxL2Bridge


def make_bridge() -> TdxL2Bridge:
    bridge = TdxL2Bridge.__new__(TdxL2Bridge)
    bridge.tick_fetch_supported = True
    bridge.tick_fetch_warning_emitted = False
    bridge.fetch_lock = asyncio.Lock()
    bridge.tick_cursor = 0
    bridge.tick_seen_keys = defaultdict(set)
    bridge.tick_seen_queues = defaultdict(deque)
    bridge.config = mock.Mock()
    bridge.config.tick_fetch_concurrency = 4
    bridge.config.tick_window = 60
    return bridge


class TickFetchTest(unittest.TestCase):
    def test_skips_transaction_outside_trading_frame(self):
        # 非交易时段：不调用 quote_client.transaction，直接返回空结果
        bridge = make_bridge()
        bridge.quote_client = mock.Mock()
        with mock.patch.object(main_mod, "tdx_is_trading_frame", return_value=False), mock.patch.object(
            bridge, "current_tick_codes", return_value=["000001"]
        ), mock.patch.object(bridge, "ensure_client", new_callable=mock.AsyncMock):
            result = asyncio.run(bridge.fetch_ticks(["000001"]))
        self.assertEqual(result, [])
        bridge.quote_client.transaction.assert_not_called()

    def test_calls_transaction_in_trading_frame(self):
        # 交易时段：正常调用 transaction（行为不变）
        bridge = make_bridge()
        bridge.quote_client = mock.Mock()
        frame = pd.DataFrame(
            {"code": ["000001"], "time": ["09:31"], "price": [10.0], "vol": [100], "side": [0]}
        )
        bridge.quote_client.transaction.return_value = frame
        with mock.patch.object(main_mod, "tdx_is_trading_frame", return_value=True), mock.patch.object(
            bridge, "current_tick_codes", return_value=["000001"]
        ), mock.patch.object(bridge, "ensure_client", new_callable=mock.AsyncMock), mock.patch.object(
            main_mod, "frame_to_records", return_value=[]
        ):
            result = asyncio.run(bridge.fetch_ticks(["000001"]))
        bridge.quote_client.transaction.assert_called_once()
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
