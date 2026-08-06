r"""tdx_bj_compat 单元测试：北交所（920 号段）兼容 patch 行为。

覆盖：
- mootdx.get_stock_market / get_stock_markets：920 识别为北交所（市场 2），沪深逻辑保留
- tdxpy.get_security_type：市场 2 + 92 → BJ_A_STOCK，沪深逻辑保留
- tdxpy SECURITY_COEFFICIENT：含 BJ_A_STOCK（0.01 元）
- tdxpy.get_security_quotes：含北交所的请求（list 与单值形式）不再被拒绝
- 幂等安装 / 卸载还原

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_bj_compat -v
"""

import unittest
from unittest import mock

import mootdx.quotes
import mootdx.utils
import tdx_bj_compat
import tdxpy.helper
import tdxpy.hq
from mootdx.utils import get_stock_markets
from tdxpy.constants import SECURITY_COEFFICIENT, TDXParams


def _make_api():
    api = object.__new__(tdxpy.hq.TdxHq_API)
    api.client = mock.Mock()
    api.lock = None
    api.auto_retry = False
    api.raise_exception = False
    api.last_ack_time = 0.0
    return api


class BjCompatTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(tdx_bj_compat.install_bj_compat())

    def tearDown(self):
        tdx_bj_compat.uninstall_bj_compat()

    def test_install_idempotent(self):
        self.assertTrue(tdx_bj_compat.install_bj_compat())  # 重复调用仍成功

    def test_uninstall_restores_originals(self):
        import tdxpy.helper

        self.assertEqual(tdxpy.helper.get_security_type(2, "920299"), "BJ_A_STOCK")
        tdx_bj_compat.uninstall_bj_compat()
        # 卸载后恢复上游行为
        self.assertEqual(mootdx.utils.get_stock_market("920299"), 1)
        with self.assertRaises(NotImplementedError):
            tdxpy.helper.get_security_type(2, "920299")
        self.assertNotIn("BJ_A_STOCK", SECURITY_COEFFICIENT)

    def test_mootdx_market_mapping_920(self):
        self.assertEqual(mootdx.utils.get_stock_market("920299"), 2)  # 北交所
        self.assertEqual(mootdx.utils.get_stock_market("920275"), 2)
        self.assertEqual(mootdx.utils.get_stock_market("920299", string=True), "bj")
        self.assertEqual(get_stock_markets(["920299", "000001"]), [[2, "920299"], [0, "000001"]])
        # mootdx.quotes 绑定导入的引用也已替换
        self.assertEqual(mootdx.quotes.get_stock_market("920299"), 2)

    def test_mootdx_market_mapping_legacy_unchanged(self):
        # 沪深等原逻辑完全保留
        self.assertEqual(mootdx.utils.get_stock_market("000001"), 0)
        self.assertEqual(mootdx.utils.get_stock_market("600000"), 1)
        self.assertEqual(mootdx.utils.get_stock_market("300001"), 0)
        self.assertEqual(mootdx.utils.get_stock_market("688001"), 1)

    def test_tdxpy_security_type_920(self):
        self.assertEqual(tdxpy.helper.get_security_type(2, "920299"), "BJ_A_STOCK")
        self.assertEqual(tdxpy.helper.get_security_type("bj", "920299"), "BJ_A_STOCK")

    def test_tdxpy_security_type_legacy_unchanged(self):
        self.assertEqual(tdxpy.helper.get_security_type(0, "000001"), "SZ_A_STOCK")
        self.assertEqual(tdxpy.helper.get_security_type(1, "600000"), "SH_A_STOCK")
        # 沪深逻辑保留：沪市 92 仍不识别（抛 NotImplementedError，与上游一致）
        with self.assertRaises(NotImplementedError):
            tdxpy.helper.get_security_type(1, "920299")

    def test_tdxpy_coefficient_has_bj(self):
        self.assertEqual(SECURITY_COEFFICIENT["BJ_A_STOCK"], [0.01, 0.01])

    def test_get_security_quotes_bj_list_not_rejected(self):
        # list 形式含北交所：走底层 cmd 同路径（不返回 None）
        api = _make_api()
        fake_cmd = mock.Mock()
        fake_cmd.call_api.return_value = [{"market": 2, "code": "920299", "price": 16.53}]
        with mock.patch("tdxpy.parser.std.get_security_quotes.GetSecurityQuotesCmd", return_value=fake_cmd) as cmd_cls:
            result = tdxpy.hq.TdxHq_API.get_security_quotes(api, [(2, "920299")])
        cmd_cls.assert_called_once()
        fake_cmd.setParams.assert_called_once_with([(2, "920299")])
        self.assertEqual(result[0]["code"], "920299")

    def test_get_security_quotes_bj_single_form(self):
        # 单值形式 get_security_quotes(2, code)：同样走北交所路径
        api = _make_api()
        fake_cmd = mock.Mock()
        fake_cmd.call_api.return_value = [{"market": 2, "code": "920299", "price": 16.53}]
        with mock.patch("tdxpy.parser.std.get_security_quotes.GetSecurityQuotesCmd", return_value=fake_cmd) as cmd_cls:
            result = tdxpy.hq.TdxHq_API.get_security_quotes(api, 2, "920299")
        fake_cmd.setParams.assert_called_once_with([(2, "920299")])
        self.assertEqual(result[0]["code"], "920299")

    def test_get_security_quotes_legacy_passthrough(self):
        # 不含北交所的请求透传给原函数（原函数内部使用 hq.py 绑定的 cmd 类）
        api = _make_api()
        fake_cmd = mock.Mock()
        fake_cmd.call_api.return_value = [{"market": 0, "code": "000001"}]
        with mock.patch("tdxpy.hq.GetSecurityQuotesCmd", return_value=fake_cmd):
            result = tdxpy.hq.TdxHq_API.get_security_quotes(api, [(0, "000001")])
        self.assertEqual(result[0]["code"], "000001")

    def test_tdxparams_market_bj_is_2(self):
        self.assertEqual(TDXParams.MARKET_BJ, 2)


if __name__ == "__main__":
    unittest.main()
