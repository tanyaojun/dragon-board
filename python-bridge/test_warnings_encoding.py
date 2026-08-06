r"""验证 main.py 模块级启动配置：tdxpy 非交易时段警告过滤 + pipe 下 stderr UTF-8。

背景（2026-08-06）：
- tdxpy 非交易时段调用分笔接口输出 DeprecationWarning「目前不是交易时间段...」，
  按消息文本注册 ignore（不依赖 module 解析，比 module 匹配更鲁棒）。
- DragonBoardLauncher 按 UTF-8 解码子进程 stderr，而 Python 在 pipe 重定向下默认
  按系统区域编码（GBK），导致中文日志/警告在 launcher 日志乱码；pipe 下将 stderr
  强制改为 UTF-8 对齐。

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_warnings_encoding -v
"""

import sys
import unittest
import warnings

import main as main_mod  # noqa: F401  触发模块级配置（filterwarnings + stderr reconfigure）


class WarningsEncodingTest(unittest.TestCase):
    def test_non_trading_session_warning_filtered(self):
        # 按消息文本注册的 ignore 过滤器必须存在。
        # 注意：unittest 运行时会注入 simplefilter("default")（filters 头部），会覆盖
        # 该 ignore，因此不能用「warn 不打印」实测；非 unittest 环境（生产/直接运行）
        # 实测过滤生效（见 tdx_calendar 修复记录 2026-08-06）。
        patterns = [f[1].pattern for f in warnings.filters if f[1] is not None]
        self.assertTrue(
            any("目前不是交易时间段" in p for p in patterns),
            "missing message-based ignore filter for tdxpy non-trading DeprecationWarning",
        )

    def test_stderr_utf8_when_piped(self):
        # launcher/CI 等 pipe 重定向场景下 stderr 必须为 UTF-8（对齐 launcher 解码）
        if sys.stderr.isatty():
            self.skipTest("stderr is a tty; reconfigure intentionally skipped")
        self.assertEqual(sys.stderr.encoding, "utf-8")


if __name__ == "__main__":
    unittest.main()
