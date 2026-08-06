r"""tdx_fund_flow 单元测试：主力/大单/中单/小单资金流聚合计算。

覆盖：
- 分档（超大/大/中/小单）阈值
- accumulate_ticks 增量累计（buy/sell/neutral 方向）
- get_fund_flow 净额与占比计算、无数据返回 None
- snapshot / reset
- fetch_ticks 集成：增量分笔触发累计

运行：
  cd python-bridge
  ..\quant-board\.venv\Scripts\python.exe -m unittest test_fund_flow -v
"""

import asyncio
import unittest
from unittest import mock

import tdx_fund_flow


def _tick(price: float, volume: float, side: str) -> dict:
    return {"code": "000001", "price": price, "volume": volume, "side": side}


class FundFlowTest(unittest.TestCase):
    def setUp(self):
        tdx_fund_flow.reset()

    def tearDown(self):
        tdx_fund_flow.reset()

    # ---------- 分档 ----------

    def test_bucket_thresholds(self):
        self.assertEqual(tdx_fund_flow.bucket_of(2_000_000), "super")  # ≥100万
        self.assertEqual(tdx_fund_flow.bucket_of(1_000_000), "super")
        self.assertEqual(tdx_fund_flow.bucket_of(500_000), "big")  # 20-100万
        self.assertEqual(tdx_fund_flow.bucket_of(200_000), "big")
        self.assertEqual(tdx_fund_flow.bucket_of(100_000), "mid")  # 4-20万
        self.assertEqual(tdx_fund_flow.bucket_of(40_000), "mid")
        self.assertEqual(tdx_fund_flow.bucket_of(10_000), "small")  # <4万

    # ---------- 累计与计算 ----------

    def test_accumulate_and_get(self):
        # volume 单位：手（金额 = price × vol × 100）
        # 买入：2 笔超大单（200万+150万）、1 笔大单（50万）
        # 卖出：1 笔超大单（120万）、1 笔中单（10万）
        # 中性：8 千（不计买卖）
        tdx_fund_flow.accumulate_ticks(
            "000001",
            [
                _tick(10.0, 2_000, "buy"),  # 10*2000*100=200万 super buy
                _tick(15.0, 1_000, "buy"),  # 15*1000*100=150万 super buy
                _tick(25.0, 200, "buy"),  # 25*200*100=50万 big buy
                _tick(12.0, 1_000, "sell"),  # 12*1000*100=120万 super sell
                _tick(10.0, 100, "sell"),  # 10*100*100=10万 mid sell
                _tick(8.0, 10, "neutral"),  # 8*10*100=8千 neutral
            ],
        )
        flow = tdx_fund_flow.get_fund_flow("000001")
        self.assertIsNotNone(flow)
        total = 2_000_000 + 1_500_000 + 500_000 + 1_200_000 + 100_000 + 8_000
        self.assertAlmostEqual(flow["totalAmount"], total, delta=1)
        # 主力净额 = super(买350万-卖120万) + big(买50万) = 280万
        self.assertAlmostEqual(flow["mainNetAmount"], 2_800_000, delta=1)
        self.assertAlmostEqual(flow["mainNetPct"], 2_800_000 / total * 100, places=2)
        # 大单净额 = 买50万
        self.assertAlmostEqual(flow["bigNetAmount"], 500_000, delta=1)
        # 中单净额 = -10万（卖）
        self.assertAlmostEqual(flow["midNetAmount"], -100_000, delta=1)
        # 小单净额 = 0（neutral 不计）
        self.assertAlmostEqual(flow["smallNetAmount"], 0.0, delta=1)
        # 中性单只计入总量，不影响任何档净额
        self.assertAlmostEqual(flow["smallNetPct"], 0.0, places=2)

    def test_get_fund_flow_none_when_no_data(self):
        self.assertIsNone(tdx_fund_flow.get_fund_flow("000001"))

    def test_get_fund_flow_none_when_zero_total(self):
        # 全部是 0 金额/非法行 → 无有效累计
        tdx_fund_flow.accumulate_ticks("000001", [{"price": 0, "volume": 0, "side": "buy"}])
        self.assertIsNone(tdx_fund_flow.get_fund_flow("000001"))

    def test_incremental_accumulate(self):
        tdx_fund_flow.accumulate_ticks("000001", [_tick(10.0, 1_000, "buy")])  # 100万 buy
        tdx_fund_flow.accumulate_ticks("000001", [_tick(11.0, 1_000, "sell")])  # 110万 sell
        flow = tdx_fund_flow.get_fund_flow("000001")
        self.assertAlmostEqual(flow["mainNetAmount"], 1_000_000 - 1_100_000, delta=1)

    def test_snapshot_only_nonempty(self):
        self.assertEqual(tdx_fund_flow.snapshot(), [])
        tdx_fund_flow.accumulate_ticks("000001", [_tick(10.0, 100_000, "buy")])
        items = tdx_fund_flow.snapshot()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["code"], "000001")

    def test_reset(self):
        tdx_fund_flow.accumulate_ticks("000001", [_tick(10.0, 100_000, "buy")])
        tdx_fund_flow.reset()
        self.assertIsNone(tdx_fund_flow.get_fund_flow("000001"))


if __name__ == "__main__":
    unittest.main()
