r"""tdx_fundamental 单元测试：财务缓存与估值指标计算。

覆盖：
- compute_fundamentals：换手率/流通市值/总市值/PE/PB 计算正确（含 peEstimated 标记）
- 财务数据缺失（缓存 miss / 字段缺失）→ None（不阻塞、不猜测）
- refresh_finance：填充缓存、失败冷却、TTL 内不重复拉取、幂等
- normalize_quote_row 集成：估值字段随行情记录输出

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_fundamental -v
"""

import unittest
from unittest import mock

import pandas as pd

import main as main_mod
import tdx_fundamental
from main import normalize_quote_row

# 000001 实测财务数据（2026-08-06 get_finance_info）
FIN_000001 = {
    "market": 0,
    "code": "000001",
    "liutongguben": 19405601250.0,
    "zongguben": 19405918750.0,
    "meigujingzichan": 23.91,
    "jinglirun": 145230000000.0,
}


def _finance_frame(code: str) -> pd.DataFrame:
    row = dict(FIN_000001)
    row["code"] = code
    return pd.DataFrame([row])


class FundamentalTest(unittest.TestCase):
    def setUp(self):
        tdx_fundamental.reset()

    def tearDown(self):
        tdx_fundamental.reset()

    # ---------- 计算 ----------

    def test_compute_fundamentals_values(self):
        tdx_fundamental._cache["000001"] = dict(FIN_000001)
        result = tdx_fundamental.compute_fundamentals("000001", 11.17, 568374)
        self.assertIsNotNone(result)
        # 流通市值 = 19,405,601,250 × 11.17
        self.assertAlmostEqual(result["floatMarketCap"], 19405601250 * 11.17, delta=1)
        # 总市值 = 19,405,918,750 × 11.17
        self.assertAlmostEqual(result["totalMarketCap"], 19405918750 * 11.17, delta=1)
        # 换手率 = 568374手*100 / 流通股本 * 100
        self.assertAlmostEqual(result["turnoverRate"], 568374 * 100 / 19405601250 * 100, places=2)
        # PB = 11.17 / 23.91
        self.assertAlmostEqual(result["pb"], 11.17 / 23.91, places=2)
        # PE 估算（jinglirun 口径，标记 estimated）
        self.assertAlmostEqual(result["pe"], 11.17 / (145230000000 / 19405918750), places=2)
        self.assertTrue(result["peEstimated"])

    def test_compute_fundamentals_missing_cache(self):
        # 缓存 miss → None（不猜测）
        self.assertIsNone(tdx_fundamental.compute_fundamentals("000001", 11.17, 100))

    def test_compute_fundamentals_missing_fields(self):
        # 财务数据缺关键字段 → 只输出可计算项；全缺 → None
        tdx_fundamental._cache["x1"] = {"code": "x1"}  # 无任何财务字段
        self.assertIsNone(tdx_fundamental.compute_fundamentals("x1", 10.0, 100))
        tdx_fundamental._cache["x2"] = {"code": "x2", "liutongguben": 1000000, "zongguben": 2000000}
        result = tdx_fundamental.compute_fundamentals("x2", 10.0, 100)
        self.assertIn("floatMarketCap", result)
        self.assertIn("totalMarketCap", result)
        self.assertNotIn("pe", result)  # 无净利润 → 无 PE
        self.assertNotIn("pb", result)  # 无每股净资产 → 无 PB

    # ---------- 刷新 ----------

    def test_refresh_finance_populates_cache(self):
        client = mock.Mock()
        client.finance.side_effect = lambda symbol: _finance_frame(symbol)
        ok = tdx_fundamental.refresh_finance(["000001", "600000"], client)
        self.assertEqual(ok, 2)
        self.assertIn("000001", tdx_fundamental._cache)
        self.assertEqual(client.finance.call_count, 2)

    def test_refresh_finance_ttl_no_refetch(self):
        client = mock.Mock()
        client.finance.side_effect = lambda symbol: _finance_frame(symbol)
        self.assertEqual(tdx_fundamental.refresh_finance(["000001"], client), 1)
        # TTL 内再次刷新 → 不再拉取
        self.assertEqual(tdx_fundamental.refresh_finance(["000001"], client), 0)
        self.assertEqual(client.finance.call_count, 1)

    def test_refresh_finance_failure_cooldown(self):
        client = mock.Mock()
        client.finance.side_effect = RuntimeError("network down")
        self.assertEqual(tdx_fundamental.refresh_finance(["000001"], client), 0)
        self.assertNotIn("000001", tdx_fundamental._cache)
        # 冷却期内不重试
        self.assertEqual(tdx_fundamental.refresh_finance(["000001"], client), 0)
        self.assertEqual(client.finance.call_count, 1)

    # ---------- normalize_quote_row 集成 ----------

    def test_normalize_quote_row_includes_fundamentals(self):
        tdx_fundamental._cache["000001"] = dict(FIN_000001)
        row = {
            "code": "000001",
            "price": 11.17,
            "last_close": 11.25,
            "vol": 568374,
            "amount": 634374592.0,
        }
        payload = normalize_quote_row(row)
        self.assertIsNotNone(payload)
        self.assertIn("turnoverRate", payload)
        self.assertIn("floatMarketCap", payload)
        self.assertIn("totalMarketCap", payload)
        self.assertIn("pe", payload)
        self.assertIn("pb", payload)
        self.assertEqual(payload["turnoverRate"], 0.29)

    def test_normalize_quote_row_without_fundamentals(self):
        # 无财务缓存 → 无估值字段（不影响基础行情字段）
        row = {"code": "000001", "price": 11.17, "last_close": 11.25, "vol": 100, "amount": 1000}
        payload = normalize_quote_row(row)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["lastPrice"], 11.17)
        for key in ("turnoverRate", "floatMarketCap", "totalMarketCap", "pe", "pb"):
            self.assertNotIn(key, payload)


if __name__ == "__main__":
    unittest.main()
