r"""端到端验证 _is_trading_day_cached 的自愈逻辑（损坏缓存 → 删除重试 → 恢复）。

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_calendar_selfheal -v
"""

import os
import unittest
from unittest import mock
from datetime import datetime

from main import _is_trading_day_cached


class CalendarSelfHealTest(unittest.TestCase):
    def test_returns_result_when_holiday_ok(self):
        # 正常路径：holiday 可用时直接返回交易日判定（周六 → 非交易日 False）
        with mock.patch("main._clear_stale_mootdx_holiday_cache", return_value=False), mock.patch(
            "mootdx.utils.holiday.holiday", return_value=True  # 周六 → 假期 True
        ):
            result = _is_trading_day_cached(datetime(2026, 7, 25, 10, 0))
        self.assertIs(result, False)

    def test_clears_cache_and_retries_on_failure(self):
        # 损坏缓存路径：首次调用抛异常 → 清理缓存 → 重试成功
        from main import _is_trading_day_cached as fn
        calls = {"n": 0}

        def fake_holiday(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("issubclass() arg 1 must be a class")
            return True  # 重试成功（周六返回 True=假期）

        cleared = {"n": 0}

        def fake_clear():
            cleared["n"] += 1
            return True

        with mock.patch("main._is_trading_day_cached", side_effect=fn) as _:
            pass  # 不直接 patch 自身；用底层依赖替换

        # 替换 main 模块中的 holiday 与清理函数
        import main as main_mod
        with mock.patch.object(main_mod, "_clear_stale_mootdx_holiday_cache", side_effect=fake_clear):
            with mock.patch("mootdx.utils.holiday.holiday", side_effect=fake_holiday):
                result = _is_trading_day_cached(datetime(2026, 7, 25, 10, 0))
        self.assertIs(result, False)  # not holiday(True) = False（非交易日，周六）
        self.assertEqual(calls["n"], 2)  # 首次失败 + 重试成功
        self.assertEqual(cleared["n"], 1)  # 恰好清理一次

    def test_returns_none_when_retry_also_fails(self):
        # 重试也失败（如网络不可用）：返回 None，不猜测交易日
        def fake_holiday(*args, **kwargs):
            raise RuntimeError("network down")

        def fake_clear():
            return True

        import main as main_mod
        with mock.patch.object(main_mod, "_clear_stale_mootdx_holiday_cache", side_effect=fake_clear):
            with mock.patch("mootdx.utils.holiday.holiday", side_effect=fake_holiday):
                result = _is_trading_day_cached(datetime(2026, 7, 25, 10, 0))
        self.assertIsNone(result)

    def test_no_retry_when_no_cache_to_clear(self):
        # 无缓存可清理：只记一条 warning，不重试
        def fake_holiday(*args, **kwargs):
            raise RuntimeError("boom")

        def fake_clear():
            return False

        import main as main_mod
        with mock.patch.object(main_mod, "_clear_stale_mootdx_holiday_cache", side_effect=fake_clear):
            with mock.patch("mootdx.utils.holiday.holiday", side_effect=fake_holiday):
                result = _is_trading_day_cached(datetime(2026, 7, 25, 10, 0))
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
