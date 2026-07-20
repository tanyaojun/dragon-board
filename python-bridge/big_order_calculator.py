"""基于 tdxpy 逐笔成交数据的实时大单资金流向计算。

不依赖外部 API，直接从 TDX 服务器拉取逐笔成交，按东方财富风格分类：
- 超大单 / 大单 / 中单 / 小单
- 主力净额 = 超大单净额 + 大单净额
- 支持 6 档阈值切换（50/100/300/500/700/1000 万）
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from l2.provider import MoneyFlowFrame, now_ms


@dataclass
class BigOrderConfig:
    """大单阈值配置。

    超大单 >= threshold_wan 万元
    大单   >= threshold_wan / 5 万元
    中单   >= threshold_wan / 25 万元
    小单   <  threshold_wan / 25 万元
    """

    threshold_wan: float = 100.0  # 超大单阈值（万元）
    fetch_limit: int = 300  # 每轮拉取逐笔条数上限
    poll_interval_ms: int = 3000  # 轮询间隔 ms
    min_amount_wan: float = 0.0  # 低于此金额不统计（过滤尾盘集合竞价零量单）
    codes_per_cycle: int = 30  # 每轮处理股票数上限

    @property
    def large_threshold_wan(self) -> float:
        return self.threshold_wan / 5.0

    @property
    def medium_threshold_wan(self) -> float:
        return self.threshold_wan / 25.0


@dataclass
class StockFlowAccumulator:
    """单只股票的累积资金流状态。"""

    code: str
    super_large_buy: float = 0.0
    super_large_sell: float = 0.0
    large_buy: float = 0.0
    large_sell: float = 0.0
    medium_buy: float = 0.0
    medium_sell: float = 0.0
    small_buy: float = 0.0
    small_sell: float = 0.0
    total_amount: float = 0.0
    total_volume: float = 0.0
    last_tick_key: str = ""
    last_source_ts: int = 0
    tick_count: int = 0

    @property
    def super_large_net(self) -> float:
        return self.super_large_buy - self.super_large_sell

    @property
    def large_net(self) -> float:
        return self.large_buy - self.large_sell

    @property
    def zlje(self) -> float:  # 主力净额
        return self.super_large_net + self.large_net

    @property
    def zljzb(self) -> float:  # 主力净占比
        if self.total_amount <= 0:
            return 0.0
        return (self.zlje / self.total_amount) * 100.0

    def reset(self) -> None:
        self.super_large_buy = 0.0
        self.super_large_sell = 0.0
        self.large_buy = 0.0
        self.large_sell = 0.0
        self.medium_buy = 0.0
        self.medium_sell = 0.0
        self.small_buy = 0.0
        self.small_sell = 0.0
        self.total_amount = 0.0
        self.total_volume = 0.0
        self.last_tick_key = ""
        self.last_source_ts = 0
        self.tick_count = 0

    def to_money_flow_frame(self, config: BigOrderConfig) -> MoneyFlowFrame:
        return MoneyFlowFrame(
            code=self.code,
            zlje=self.zlje / 10000,  # 转为万元
            zljzb=self.zljzb,
            cddje=self.super_large_net / 10000,
            cddjzb=(self.super_large_net / self.total_amount * 100.0) if self.total_amount > 0 else 0.0,
            moneyFlowSource="tdx_transaction",
            moneyFlowEstimated=False,
            capitalFlowSource="tdx_tick",
            capitalFlowConfidence="high",
            activeAmount=self.total_amount / 10000,
            sourceTs=self.last_source_ts,
            timestamp=now_ms(),
        )


class BigOrderCalculator:
    """实时大单资金流计算器。

    轮询逐笔成交数据，分类统计各类订单的买卖金额，
    生成与 QMT L2 兼容的 MoneyFlowFrame 输出。
    """

    def __init__(self, config: BigOrderConfig | None = None) -> None:
        self.config = config or BigOrderConfig()
        self.accumulators: dict[str, StockFlowAccumulator] = {}
        self._cycle_count = 0

    def ensure_accumulator(self, code: str) -> StockFlowAccumulator:
        if code not in self.accumulators:
            self.accumulators[code] = StockFlowAccumulator(code=code)
        return self.accumulators[code]

    def classify_amount(self, amount_yuan: float) -> str:
        """将成交金额分类为超大大小单品种。"""
        wan = amount_yuan / 10000.0
        if wan >= self.config.threshold_wan:
            return "super_large"
        if wan >= self.config.large_threshold_wan:
            return "large"
        if wan >= self.config.medium_threshold_wan:
            return "medium"
        return "small"

    def process_ticks(
        self,
        code: str,
        ticks: list[dict[str, Any]],
    ) -> StockFlowAccumulator:
        """处理一批逐笔成交，累加到对应股票的 accumulator。

        ticks 格式同 tdxpy get_transaction_data / get_history_transaction_data 返回，
        每条记录包含 time, price, vol, buyorsell 四个字段。
        """
        acc = self.ensure_accumulator(code)
        if not ticks:
            return acc

        min_amount_yuan = self.config.min_amount_wan * 10000.0

        for tick in ticks:
            price = float(tick.get("price", 0))
            vol = int(tick.get("vol", 0))  # 股数
            bs = int(tick.get("buyorsell", -1))
            tick_time = str(tick.get("time", ""))

            if vol <= 0 or price <= 0:
                continue

            amount = price * vol  # 成交金额（元）

            if amount < min_amount_yuan:
                continue

            # 判断买卖方向: 0/1=主动买, 2=主动卖, 其他=中性（不统计方向）
            is_buy = bs in (0, 1)
            is_sell = bs == 2

            category = self.classify_amount(amount)
            field_buy = f"{category}_buy"
            field_sell = f"{category}_sell"

            if is_buy:
                setattr(acc, field_buy, getattr(acc, field_buy) + amount)
                acc.total_amount += amount
                acc.total_volume += vol
            elif is_sell:
                setattr(acc, field_sell, getattr(acc, field_sell) + amount)
                acc.total_amount += amount
                acc.total_volume += vol
            # 中性盘（buyorsell 为 5/8 等）不计方向，但计入总量
            elif bs >= 0:
                acc.total_amount += amount
                acc.total_volume += vol

            acc.tick_count += 1
            acc.last_tick_key = tick_time

        return acc

    def fetch_and_update(
        self,
        api,  # TdxHq_API 实例
        codes: list[str],
        market_map: dict[str, int] | None = None,
    ) -> list[MoneyFlowFrame]:
        """拉取逐笔并更新累加器，返回有更新的股票的 MoneyFlowFrame 列表。

        api: 已连接的 TdxHq_API 实例
        codes: 需要查询的股票代码列表
        market_map: code -> market(0=SZ,1=SH) 映射，自动推导
        """
        frames: list[MoneyFlowFrame] = []
        processed = 0

        for code in codes:
            if processed >= self.config.codes_per_cycle:
                break

            market = 0  # SZ
            if market_map:
                market = market_map.get(code, 0)
            elif code.startswith("6"):
                market = 1  # SH

            try:
                ticks = api.get_transaction_data(
                    market, code, 0, self.config.fetch_limit
                )
            except Exception:
                ticks = None

            # 盘中实时数据不可用时（收盘/非交易时段），回退到历史逐笔查询当天
            if not ticks:
                try:
                    from datetime import datetime

                    today = int(datetime.now().strftime("%Y%m%d"))
                    ticks = api.get_history_transaction_data(
                        market, code, 0, self.config.fetch_limit, today
                    )
                except Exception:
                    ticks = None

            if not ticks:
                continue

            processed += 1
            acc = self.ensure_accumulator(code)
            old_count = acc.tick_count
            self.process_ticks(code, ticks)

            if acc.tick_count > old_count:
                frames.append(acc.to_money_flow_frame(self.config))

        self._cycle_count += 1
        return frames

    def get_frames(self, codes: list[str]) -> list[MoneyFlowFrame]:
        """获取指定代码的当前累积资金流帧（不拉新数据）。"""
        return [
            acc.to_money_flow_frame(self.config)
            for code in codes
            if (acc := self.accumulators.get(code)) and acc.tick_count > 0
        ]

    def reset_all(self) -> None:
        for acc in self.accumulators.values():
            acc.reset()

    def daily_cleanup(self) -> None:
        """交易日切换时清空所有累加器。"""
        self.accumulators.clear()
        self._cycle_count = 0
