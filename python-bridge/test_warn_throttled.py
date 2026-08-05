r"""_warn_throttled 节流逻辑测试（不依赖 TDX/网络，纯逻辑验证）。

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_warn_throttled -v
"""

import time
import unittest
from unittest import mock

from main import TdxL2Bridge

# 生产缓存上限常量（与 main.py 保持一致；避免魔法数字漂移）
_CACHE_LIMIT = 512


class WarnThrottledTest(unittest.TestCase):
    def setUp(self):
        # 用 __new__ 绕过 __init__（不创建连接/配置）
        self.bridge = TdxL2Bridge.__new__(TdxL2Bridge)
        self.bridge._warn_cooldown_s = 60.0
        self._clock = 1000.0  # mock 时钟基准（monotonic 值任意）

    def _tick(self, seconds: float) -> None:
        """推进 mock 时钟，使冷却窗口测试确定且无需真实 sleep。"""
        self._clock += seconds

    def _patch_clock(self):
        return mock.patch.object(time, "monotonic", side_effect=lambda: self._clock)

    def test_first_call_returns_true(self):
        cache = {}
        with self._patch_clock():
            self.assertTrue(self.bridge._warn_throttled(cache, ("920092",), 60.0))

    def test_same_key_within_cooldown_returns_false(self):
        cache = {}
        key = ("920092", "600000")
        with self._patch_clock():
            self.assertTrue(self.bridge._warn_throttled(cache, key, 60.0))
            # 冷却窗口内同集合不重复记录
            self.assertFalse(self.bridge._warn_throttled(cache, key, 60.0))
            self.assertFalse(self.bridge._warn_throttled(cache, key, 60.0))
            # 即使时钟前进 30s（仍在 60s 窗口内）仍节流
            self._tick(30)
            self.assertFalse(self.bridge._warn_throttled(cache, key, 60.0))

    def test_different_key_not_throttled(self):
        cache = {}
        with self._patch_clock():
            self.assertTrue(self.bridge._warn_throttled(cache, ("920092",), 60.0))
            # 不同缺失集合（不同代码）不互相节流
            self.assertTrue(self.bridge._warn_throttled(cache, ("600000",), 60.0))

    def test_cooldown_elapsed_allows_again(self):
        cache = {}
        key = ("920092",)
        with self._patch_clock():
            self.assertTrue(self.bridge._warn_throttled(cache, key, 60.0))
            self.assertFalse(self.bridge._warn_throttled(cache, key, 60.0))
            self._tick(60.0)
            # 冷却窗口过后再次放行
            self.assertTrue(self.bridge._warn_throttled(cache, key, 60.0))

    def test_refetch_fail_throttle_by_code(self):
        cache = {}
        code = "920092"
        with self._patch_clock():
            self.assertTrue(self.bridge._warn_throttled(cache, code, 60.0))
            self.assertFalse(self.bridge._warn_throttled(cache, code, 60.0))
            self._tick(60.0)
            self.assertTrue(self.bridge._warn_throttled(cache, code, 60.0))

    def test_stale_entries_cleaned_when_over_limit(self):
        """超限清理时，超过 2×冷却窗口的过期条目被优先删除。"""
        cache = {}
        with self._patch_clock():
            # 填满缓存并写入少量过期条目，再超限写入触发清理
            for i in range(_CACHE_LIMIT):
                self.bridge._warn_throttled(cache, ("base%04d" % i,), 60.0)
                self._tick(0.001)
            # 前进 3×cooldown 使全部 base 条目过期，再写入 10 个新 key 触发超限清理
            self._tick(180.0)
            for i in range(10):
                self.bridge._warn_throttled(cache, ("fresh%02d" % i,), 60.0)
            self.assertLessEqual(len(cache), _CACHE_LIMIT)
            # 过期条目（base*）被清掉，新条目保留
            self.assertNotIn(("base0000",), cache)
            self.assertIn(("fresh09",), cache)

    def test_cache_grows_bounded(self):
        """缓存超限后强制回到上限：写入远多于上限的 key，验证 len 不超过上限。"""
        cache = {}
        with self._patch_clock():
            for i in range(_CACHE_LIMIT * 2 + 100):
                # 每个 key 唯一；时钟轻微推进，保证清理路径稳定触发
                self.bridge._warn_throttled(cache, ("code%04d" % i,), 60.0)
                self._tick(0.001)
            self.assertLessEqual(len(cache), _CACHE_LIMIT)
            # 最新的 key 保留（最旧被淘汰）
            self.assertIn(("code%04d" % (_CACHE_LIMIT * 2 + 99),), cache)
            # 最旧的 key 已被淘汰
            self.assertNotIn(("code0000",), cache)

    def test_cache_evicts_oldest_when_all_fresh(self):
        """全部条目都新鲜（<2×cooldown）时，超限仍删除最旧条目保证有界。"""
        cache = {}
        with self._patch_clock():
            for i in range(_CACHE_LIMIT + 50):
                self.bridge._warn_throttled(cache, ("fresh%04d" % i,), 60.0)
                self._tick(0.5)  # 每 key 间隔 0.5s，总跨度 < 2×60s，全部新鲜
            self.assertLessEqual(len(cache), _CACHE_LIMIT)
            # 最旧的（fresh0000）被淘汰，最新保留
            self.assertNotIn(("fresh0000",), cache)
            self.assertIn(("fresh%04d" % (_CACHE_LIMIT + 49),), cache)


if __name__ == "__main__":
    unittest.main()
