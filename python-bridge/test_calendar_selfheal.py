r"""验证 main._is_trading_day_cached 的可用性与自愈语义（日历故障恢复后自动可用）。

背景：旧实现依赖 mootdx 共享 pickle 缓存，损坏时「删缓存重试」自愈；
新实现（tdx_calendar 自拉 tdx.com.cn + 内存/JSON 缓存）彻底绕开 mootdx 缓存，
自愈语义保留为：拉取失败返回 None（不猜测交易日）→ 冷却后重试 → 恢复判定。

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_calendar_selfheal -v
"""

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import httpx

import tdx_calendar
from main import _is_trading_day_cached, is_trading_session_now

FIXTURE_TEXT = """<html><body>
<textarea id="data" style="display:none;">20260101|元旦|中国|上交所
20261001|国庆节|中国|上交所
</textarea>
</body></html>"""

T0 = 1_800_000_000.0


class CalendarSelfHealTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(tdx_calendar, "_CACHE_PATH", Path(self.tmpdir.name) / "holiday_bridge.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmpdir.cleanup)
        tdx_calendar._reset_cache()
        self.addCleanup(tdx_calendar._reset_cache)

    def _fake_response(self):
        request = httpx.Request("GET", tdx_calendar._TDX_CALENDAR_URL)
        return httpx.Response(200, content=FIXTURE_TEXT.encode("gbk"), request=request)

    def test_returns_result_when_calendar_ok(self):
        # 正常路径：工作日 → True，周末/节假日 → False
        with mock.patch("tdx_calendar.httpx.get", return_value=self._fake_response()):
            self.assertIs(_is_trading_day_cached(datetime(2026, 7, 27, 10, 0)), True)
            self.assertIs(_is_trading_day_cached(datetime(2026, 7, 25, 10, 0)), False)
            self.assertIs(_is_trading_day_cached(datetime(2026, 1, 1, 10, 0)), False)

    def test_returns_none_when_calendar_unavailable(self):
        # 拉取失败：返回 None（不猜测交易日），调用方按降级处理
        with mock.patch(
            "tdx_calendar.httpx.get", side_effect=httpx.ConnectError("SSL handshake timeout")
        ):
            self.assertIsNone(_is_trading_day_cached(datetime(2026, 7, 27, 10, 0)))
        # 调用方降级：is_trading_session_now 不抛异常、直接判非交易时段
        self.assertFalse(is_trading_session_now(datetime(2026, 7, 27, 10, 0)))

    def test_recovers_after_failure(self):
        # 自愈：首次失败 → 冷却后重试成功 → 恢复交易日判定
        ts = {"v": T0}
        calls = {"n": 0}

        def fake_get(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise httpx.ConnectError("down")
            return self._fake_response()

        with mock.patch("tdx_calendar._now_ts", side_effect=lambda: ts["v"]), mock.patch(
            "tdx_calendar.httpx.get", side_effect=fake_get
        ):
            self.assertIsNone(_is_trading_day_cached(datetime(2026, 7, 27, 10, 0)))
            ts["v"] += 120  # 超过失败冷却
            self.assertIs(_is_trading_day_cached(datetime(2026, 7, 27, 10, 0)), True)
        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
