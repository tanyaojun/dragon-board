r"""tdx_calendar 单元测试：自实现 tdx.com.cn 交易日历的解析、缓存与 fail-visible 语义。

覆盖：
- tdx 页面文本解析（textarea 提取、中国节假日过滤、与 mootdx 行为等价）
- 内存缓存 / JSON 文件缓存 / 网络拉取三级策略
- 拉取失败返回 None（不猜测交易日）、失败冷却避免高频重试
- 不读写 mootdx 共享 pickle 缓存（~/.mootdx/caches/holiday.plk），跨 pandas 版本不再互相影响
- main._is_trading_day_cached 委托语义

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_tdx_calendar -v

mock 缝隙（2026-10-23）：拉取统一 mock `tdx_calendar._fetch_tdx_holidays`，
不再绑定具体 HTTP 客户端（httpx → urllib 换源后测试仍有效）。
"""

import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import tdx_calendar
from main import _is_trading_day_cached

# 模拟 tdx.com.cn 页面：行格式 YYYYMMDD|节日|国家|交易所。
# 注意与 mootdx 等价：只精确匹配国家「中国」，「中国香港」等行被过滤。
FIXTURE_TEXT = """<html><body>
<textarea id="data" style="display:none;">20260101|元旦|中国|上交所
20260102|元旦|中国|深交所
20260101|New Year|美国|NYSE
20260215|春节|中国香港|港交所
20261001|国庆节|中国|上交所
</textarea>
</body></html>"""

CHINA_HOLIDAYS = {date(2026, 1, 1), date(2026, 1, 2), date(2026, 10, 1)}

T0 = 1_800_000_000.0  # 固定基准时间戳（2027 年初附近，仅用于相对时间控制）


class TdxCalendarTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        cache_path = Path(self.tmpdir.name) / "holiday_bridge.json"
        patcher = mock.patch.object(tdx_calendar, "_CACHE_PATH", cache_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmpdir.cleanup)
        tdx_calendar._reset_cache()
        self.addCleanup(tdx_calendar._reset_cache)

    def _fake_holidays(self, text: str = FIXTURE_TEXT) -> set:
        return tdx_calendar.parse_tdx_holiday_text(text)

    # ---------- 解析 ----------

    def test_parse_extracts_china_holidays(self):
        parsed = tdx_calendar.parse_tdx_holiday_text(FIXTURE_TEXT)
        self.assertEqual(parsed, CHINA_HOLIDAYS)

    def test_parse_raises_when_textarea_missing(self):
        with self.assertRaises(ValueError):
            tdx_calendar.parse_tdx_holiday_text("<html>no textarea</html>")

    def test_parse_raises_when_body_empty(self):
        text = '<textarea id="data" style="display:none;">\n\n</textarea>'
        with self.assertRaises(ValueError):
            tdx_calendar.parse_tdx_holiday_text(text)

    def test_parse_raises_when_no_china_rows(self):
        text = '<textarea id="data" style="display:none;">20260101|元旦|美国|NYSE\n</textarea>'
        with self.assertRaises(ValueError):
            tdx_calendar.parse_tdx_holiday_text(text)

    # ---------- 交易日语义（等价 mootdx：周末与节假日非交易日） ----------

    def test_is_trading_day_weekday_holiday_weekend(self):
        with mock.patch("tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()):
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)  # 周一
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 25)), False)  # 周六
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 1, 1)), False)  # 元旦
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 2, 16)), True)  # 中国香港春节不作用于 A 股（与 mootdx 等价）

    # ---------- fail-visible：不可用返回 None，不猜测 ----------

    def test_fetch_failure_returns_none(self):
        with mock.patch(
            "tdx_calendar._fetch_tdx_holidays", side_effect=ConnectionError("SSL handshake timeout")
        ):
            result = tdx_calendar.is_trading_day(date(2026, 7, 27))
        self.assertIsNone(result)

    def test_parse_failure_returns_none(self):
        # 页面结构变化（textarea 缺失）→ 解析异常 → None，不误判为交易日
        with mock.patch(
            "tdx_calendar._fetch_tdx_holidays",
            side_effect=ValueError("tdx holiday page: textarea block not found"),
        ):
            result = tdx_calendar.is_trading_day(date(2026, 7, 27))
        self.assertIsNone(result)

    def test_failure_cooldown_prevents_repeated_fetch(self):
        ts = {"v": T0}

        def fake_now():
            return ts["v"]

        with mock.patch("tdx_calendar._now_ts", side_effect=fake_now), mock.patch(
            "tdx_calendar._fetch_tdx_holidays", side_effect=ConnectionError("down")
        ) as fetch_mock:
            self.assertIsNone(tdx_calendar.is_trading_day(date(2026, 7, 27)))
            ts["v"] += 30  # 冷却期内（60s）
            self.assertIsNone(tdx_calendar.is_trading_day(date(2026, 7, 27)))
            self.assertEqual(fetch_mock.call_count, 1)
            ts["v"] += 60  # 超过冷却 → 重试
            self.assertIsNone(tdx_calendar.is_trading_day(date(2026, 7, 27)))
            self.assertEqual(fetch_mock.call_count, 2)

    def test_cooldown_recovers_after_refetch_success(self):
        ts = {"v": T0}
        calls = {"n": 0}

        def fake_fetch():
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("down")
            return self._fake_holidays()

        with mock.patch("tdx_calendar._now_ts", side_effect=lambda: ts["v"]), mock.patch(
            "tdx_calendar._fetch_tdx_holidays", side_effect=fake_fetch
        ):
            self.assertIsNone(tdx_calendar.is_trading_day(date(2026, 7, 27)))
            ts["v"] += 120
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)  # 恢复后正常判定

    # ---------- 缓存策略 ----------

    def test_memory_cache_avoids_network(self):
        with mock.patch(
            "tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()
        ) as fetch_mock:
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 28)), True)
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 1, 1)), False)
        self.assertEqual(fetch_mock.call_count, 1)

    def test_json_cache_written_after_fetch(self):
        with mock.patch(
            "tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()
        ), mock.patch("tdx_calendar._now_ts", return_value=T0):
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
        payload = json.loads(tdx_calendar._CACHE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["fetchedAt"], T0)
        self.assertEqual(set(payload["holidays"]), {d.isoformat() for d in CHINA_HOLIDAYS})

    def test_json_cache_reused_on_restart(self):
        # 预写一份新鲜（1 小时前）的缓存文件，模拟进程重启：不再请求网络
        payload = {"fetchedAt": T0 - 3600, "holidays": [d.isoformat() for d in CHINA_HOLIDAYS]}
        tdx_calendar._CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch("tdx_calendar._now_ts", return_value=T0), mock.patch(
            "tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()
        ) as fetch_mock:
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 1, 1)), False)
        fetch_mock.assert_not_called()

    def test_expired_json_cache_refetches(self):
        # 缓存文件已过期（超过 24h TTL）→ 触发网络拉取
        payload = {"fetchedAt": T0 - 3 * tdx_calendar._FETCH_TTL_SECONDS, "holidays": []}
        tdx_calendar._CACHE_PATH.write_text(json.dumps(payload), encoding="utf-8")
        with mock.patch("tdx_calendar._now_ts", return_value=T0), mock.patch(
            "tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()
        ) as fetch_mock:
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
        fetch_mock.assert_called_once()

    def test_corrupt_json_cache_ignored(self):
        tdx_calendar._CACHE_PATH.write_text("{not json", encoding="utf-8")
        with mock.patch(
            "tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()
        ) as fetch_mock:
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
        fetch_mock.assert_called_once()

    def test_memory_ttl_expiry_refetches(self):
        ts = {"v": T0}

        def fake_fetch():
            return self._fake_holidays()

        with mock.patch("tdx_calendar._now_ts", side_effect=lambda: ts["v"]), mock.patch(
            "tdx_calendar._fetch_tdx_holidays", side_effect=fake_fetch
        ) as fetch_mock:
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
            ts["v"] += tdx_calendar._FETCH_TTL_SECONDS + 1  # 超过 TTL
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
        self.assertEqual(fetch_mock.call_count, 2)

    def test_http_error_status_returns_none(self):
        # 非 200（如 500）→ HTTPError → None，不抛异常
        import urllib.error

        with mock.patch(
            "tdx_calendar._fetch_tdx_holidays",
            side_effect=urllib.error.HTTPError(
                tdx_calendar._TDX_CALENDAR_URL, 500, "boom", {}, None
            ),
        ):
            self.assertIsNone(tdx_calendar.is_trading_day(date(2026, 7, 27)))

    def test_cache_write_failure_does_not_block(self):
        # 缓存写失败（磁盘满等）不影响判定：内存缓存仍可用，不抛异常
        with mock.patch(
            "tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()
        ), mock.patch("tdx_calendar.os.replace", side_effect=OSError("disk full")):
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)

    def test_memory_fresh_ignores_corrupt_file(self):
        # 内存缓存新鲜时直接命中，不读取（已损坏的）磁盘缓存
        with mock.patch("tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()):
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
        tdx_calendar._CACHE_PATH.write_text("{corrupt", encoding="utf-8")
        with mock.patch(
            "tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()
        ) as fetch_mock:
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
        fetch_mock.assert_not_called()

    def test_ttl_boundary_expired_refetches(self):
        # TTL 边界：now 恰好等于 fetchedAt + TTL 时判定过期并重拉
        ts = {"v": T0}

        def fake_fetch():
            return self._fake_holidays()

        with mock.patch("tdx_calendar._now_ts", side_effect=lambda: ts["v"]), mock.patch(
            "tdx_calendar._fetch_tdx_holidays", side_effect=fake_fetch
        ) as fetch_mock:
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
            ts["v"] += tdx_calendar._FETCH_TTL_SECONDS
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
        self.assertEqual(fetch_mock.call_count, 2)

    def test_concurrent_expired_fetch_single_network_call(self):
        # 多线程同时触发过期拉取：只发生一次网络请求（_FETCH_IN_PROGRESS 去重）
        import threading

        ts = {"v": T0}

        def fake_fetch():
            return self._fake_holidays()

        with mock.patch("tdx_calendar._now_ts", side_effect=lambda: ts["v"]), mock.patch(
            "tdx_calendar._fetch_tdx_holidays", side_effect=fake_fetch
        ) as fetch_mock:
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
            ts["v"] += tdx_calendar._FETCH_TTL_SECONDS + 1  # 过期
            results = []

            def worker():
                results.append(tdx_calendar.is_trading_day(date(2026, 7, 27)))

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(fetch_mock.call_count, 2)  # 首次 + 过期后仅一次
        self.assertTrue(any(result is True for result in results))  # 至少一个线程拿到结果

    # ---------- 与 mootdx 共享 pickle 缓存彻底隔离 ----------

    def test_does_not_touch_mootdx_plk_cache(self):
        from mootdx import get_config_path

        # 结构保证：独立文件名，绝不对齐 mootdx 的 holiday.plk
        self.assertNotEqual(tdx_calendar._CACHE_PATH.name, "holiday.plk")
        plk = Path(get_config_path("caches/holiday.plk"))
        before = plk.stat().st_mtime_ns if plk.exists() else None
        with mock.patch("tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()):
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 7, 27)), True)
            self.assertIs(tdx_calendar.is_trading_day(date(2026, 1, 1)), False)
        after = plk.stat().st_mtime_ns if plk.exists() else None
        self.assertEqual(before, after)  # bridge 不再读写 mootdx holiday.plk

    # ---------- main 委托 ----------

    def test_main_is_trading_day_cached_semantics(self):
        with mock.patch(
            "tdx_calendar._fetch_tdx_holidays", side_effect=ConnectionError("down")
        ):
            self.assertIsNone(_is_trading_day_cached(datetime(2026, 7, 27, 10, 0)))
        tdx_calendar._reset_cache()
        with mock.patch("tdx_calendar._fetch_tdx_holidays", return_value=self._fake_holidays()):
            self.assertIs(_is_trading_day_cached(datetime(2026, 7, 27, 10, 0)), True)
            self.assertIs(_is_trading_day_cached(datetime(2026, 7, 25, 10, 0)), False)
            self.assertIs(_is_trading_day_cached(datetime(2026, 1, 1, 10, 0)), False)


if __name__ == "__main__":
    unittest.main()
