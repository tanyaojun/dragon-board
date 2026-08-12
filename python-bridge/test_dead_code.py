"""无数据代码挂起机制测试（2026-08-12：688836 新股未上市 TDX 无数据，
含它的批量行情请求整批返回空——连续失败 N 次挂起，避免每轮重复请求 + 拖累同批）。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from main import TdxL2Bridge, BridgeConfig


class DeadCodeHaltTest(unittest.TestCase):
    def setUp(self) -> None:
        config = BridgeConfig()
        config.dead_code_max_failures = 3
        config.dead_code_retry_ms = 60000
        self.bridge = TdxL2Bridge(config=config)

    def test_halt_after_consecutive_failures(self) -> None:
        now = 1_000_000
        self.assertFalse(self.bridge.is_code_halted("688836", now))
        self.bridge.halt_code("688836", now)
        self.bridge.halt_code("688836", now + 1)
        # 2 次未达阈值，仍会请求
        self.assertFalse(self.bridge.is_code_halted("688836", now + 2))
        self.bridge.halt_code("688836", now + 2)
        # 3 次达阈值挂起
        self.assertTrue(self.bridge.is_code_halted("688836", now + 3))
        self.assertIn("688836", self.bridge.halted_codes(now + 3))

    def test_halted_code_expires_for_retry(self) -> None:
        now = 1_000_000
        for _ in range(3):
            self.bridge.halt_code("688836", now)
        # retry 窗口内保持挂起
        self.assertTrue(self.bridge.is_code_halted("688836", now + 1000))
        # 超过 retry 窗口（60000ms）后恢复请求
        self.assertFalse(self.bridge.is_code_halted("688836", now + 60_001))

    def test_unhalt_on_success(self) -> None:
        now = 1_000_000
        for i in range(3):
            self.bridge.halt_code("688836", now + i)
        self.assertTrue(self.bridge.is_code_halted("688836", now + 100))
        self.bridge.unhalt_code("688836")
        self.assertFalse(self.bridge.is_code_halted("688836", now + 101))
        self.assertNotIn("688836", self.bridge.halted_codes(now + 101))


if __name__ == "__main__":
    unittest.main()
