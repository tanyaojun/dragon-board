"""基于 tdxpy 逐笔成交数据的实时大单资金流向计算。

不依赖外部 API，直接从 TDX 服务器拉取逐笔成交，按金额分档：
- 超大单 / 大单 / 中单 / 小单
- 主力净额 = (超大单买入 + 大单买入) - (超大单卖出 + 大单卖出)
- 默认阈值：超大单≥20万, 大单≥4万, 中单≥8千, 小单<8千

注：tdxpy vol 字段单位是「手」，非股数。逐笔成交已拆单，每笔手数通常很小（茅台1-2手）。
因此采用金额分类而非手数分类，与东财/同花顺 L2 口径对齐。
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from l2.provider import MoneyFlowFrame, now_ms


@dataclass
class BigOrderConfig:
    """大单金额阈值配置（万元）。"""

    threshold_wan: float = 100.0  # 超大单阈值（东财标准：≥100万）
    fetch_limit: int = 300
    poll_interval_ms: int = 3000
    min_amount_wan: float = 0.0
    codes_per_cycle: int = 30

    @property
    def large_threshold_wan(self) -> float:
        return self.threshold_wan / 5.0

    @property
    def medium_threshold_wan(self) -> float:
        return self.threshold_wan / 25.0


@dataclass
class StockFlowAccumulator:
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
    processed_keys: set = field(default_factory=set)

    @property
    def super_large_net(self) -> float:
        return self.super_large_buy - self.super_large_sell

    @property
    def large_net(self) -> float:
        return self.large_buy - self.large_sell

    @property
    def zlje(self) -> float:
        return self.super_large_net + self.large_net

    @property
    def zljzb(self) -> float:
        if self.total_amount <= 0:
            return 0.0
        return (self.zlje / self.total_amount) * 100.0

    def reset(self) -> None:
        self.super_large_buy = self.super_large_sell = 0.0
        self.large_buy = self.large_sell = 0.0
        self.medium_buy = self.medium_sell = 0.0
        self.small_buy = self.small_sell = 0.0
        self.total_amount = self.total_volume = 0.0
        self.last_tick_key = ""
        self.last_source_ts = 0
        self.tick_count = 0
        self.processed_keys.clear()

    def to_money_flow_frame(self, config: BigOrderConfig) -> MoneyFlowFrame:
        return MoneyFlowFrame(
            code=self.code,
            zlje=self.zlje / 10000,
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
    def __init__(self, config: BigOrderConfig | None = None) -> None:
        self.config = config or BigOrderConfig()
        self.accumulators: dict[str, StockFlowAccumulator] = {}
        self._cycle_count = 0

    def ensure_accumulator(self, code: str) -> StockFlowAccumulator:
        if code not in self.accumulators:
            self.accumulators[code] = StockFlowAccumulator(code=code)
        return self.accumulators[code]

    def classify_amount(self, amount_yuan: float) -> str:
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
        acc = self.ensure_accumulator(code)
        if not ticks:
            return acc

        min_yuan = self.config.min_amount_wan * 10000.0
        new_ticks = 0

        for tick in ticks:
            price = float(tick.get("price", 0))
            vol = int(tick.get("vol", 0))  # tdxpy vol 单位=手
            bs = int(tick.get("buyorsell", -1))
            tick_time = str(tick.get("time", ""))

            if vol <= 0 or price <= 0:
                continue

            # 跨轮去重：同 time:price:vol:bs 不重复累加
            dedup_key = f"{tick_time}:{price}:{vol}:{bs}"
            if dedup_key in acc.processed_keys:
                continue
            acc.processed_keys.add(dedup_key)

            amount = price * vol * 100

            if amount < min_yuan:
                continue

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
            elif bs >= 0:
                acc.total_amount += amount
                acc.total_volume += vol

            new_ticks += 1
            acc.last_tick_key = tick_time

        acc.tick_count += new_ticks
        return acc

    def fetch_and_update(
        self,
        api,
        codes: list[str],
        market_map: dict[str, int] | None = None,
    ) -> list[MoneyFlowFrame]:
        frames: list[MoneyFlowFrame] = []
        processed = 0

        for code in codes:
            if processed >= self.config.codes_per_cycle:
                break

            market = 0
            if market_map:
                market = market_map.get(code, 0)
            elif code.startswith("6"):
                market = 1

            acc = self.ensure_accumulator(code)
            try:
                ticks = api.get_transaction_data(market, code, 0, self.config.fetch_limit)
            except Exception:
                ticks = None

            if not ticks:
                try:
                    from datetime import datetime

                    today = int(datetime.now().strftime("%Y%m%d"))
                    ticks = api.get_history_transaction_data(market, code, 0, self.config.fetch_limit, today)
                except Exception:
                    ticks = None

            if not ticks:
                continue

            processed += 1
            old_count = acc.tick_count
            self.process_ticks(code, ticks)

            if acc.tick_count > old_count:
                frames.append(acc.to_money_flow_frame(self.config))

        self._cycle_count += 1
        return frames

    def get_frames(self, codes: list[str]) -> list[MoneyFlowFrame]:
        return [
            acc.to_money_flow_frame(self.config)
            for code in codes
            if (acc := self.accumulators.get(code)) and acc.tick_count > 0
        ]

    def reset_all(self) -> None:
        for acc in self.accumulators.values():
            acc.reset()

    def daily_cleanup(self) -> None:
        self.accumulators.clear()
        self._cycle_count = 0
