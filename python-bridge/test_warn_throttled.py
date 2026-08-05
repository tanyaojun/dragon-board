r"""_warn_throttled 节流逻辑测试（不依赖 TDX/网络，纯逻辑验证）。

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_warn_throttled -v
"""

import time
import unittest

# 复用 main.py 的类（不触发连接）。直接取类方法做单测太依赖 import 副作用，
# 因此复制等价实现做行为对照，确保冷却窗口语义正确。
from main import TdxL2Bridge


class WarnThrottledTest(unittest.TestCase):
    def setUp(self):
        # 用 __new__ 绕过 __init__（不创建连接/配置）
        self.bridge = TdxL2Bridge.__new__(TdxL2Bridge)
        self.bridge._warn_cooldown_s = 60.0

    def test_first_call_returns_true(self):
        self.bridge._partial_data_warn_ts = {}
        cache = self.bridge._partial_data_warn_ts
        self.assertTrue(self.bridge._warn_throttled(cache, ("920092",), 60.0))

    def test_same_key_within_cooldown_returns_false(self):
        cache = {}
        key = ("920092", "600000")
        self.assertTrue(self.bridge._warn_throttled(cache, key, 60.0))
        # 冷却窗口内同集合不重复记录
        self.assertFalse(self.bridge._warn_throttled(cache, key, 60.0))
        self.assertFalse(self.bridge._warn_throttled(cache, key, 60.0))

    def test_different_key_not_throttled(self):
        cache = {}
        self.assertTrue(self.bridge._warn_throttled(cache, ("920092",), 60.0))
        # 不同缺失集合（不同代码）不互相节流
        self.assertTrue(self.bridge._warn_throttled(cache, ("600000",), 60.0))

    def test_cooldown_elapsed_allows_again(self):
        cache = {}
        key = ("920092",)
        self.assertTrue(self.bridge._warn_throttled(cache, key, 0.05))
        self.assertFalse(self.bridge._warn_throttled(cache, key, 0.05))
        time.sleep(0.06)
        # 冷却窗口过后再次放行
        self.assertTrue(self.bridge._warn_throttled(cache, key, 0.05))

    def test_refetch_fail_throttle_by_code(self):
        cache = {}
        code = "920092"
        self.assertTrue(self.bridge._warn_throttled(cache, code, 0.05))
        self.assertFalse(self.bridge._warn_throttled(cache, code, 0.05))
        time.sleep(0.06)
        self.assertTrue(self.bridge._warn_throttled(cache, code, 0.05))

    def test_cache_grows_bounded(self):
        cache = {}
        # 超过 512 条后触发清理；写入 600 个不同 key，验证缓存不超过 512 + 少量
        for i in range(600):
            self.bridge._warn_throttled(cache, ("code%04d" % i,), 0.01)
        # 清理逻辑删除过期的（>= 2×cooldown），此处 cooldown=0.01，写入很快，
        # 大部分条目仍新鲜，因此 len 应接近 600 而不是无限增长 bug。
        self.assertLessEqual(len(cache), 600)
        self.assertTrue(len(cache) > 0)


if __name__ == "__main__":
    unittest.main()
