"""主力资金流聚合计算（基于通达信分笔成交，供 python-bridge 转发）。

背景（2026-08-06）：tdxpy/mootdx 没有现成的资金流向接口，但
``get_transaction_data``（分笔）提供每笔成交的 价格/成交量/买卖方向
（normalize_tick_row 已把 buyorsell 归一为 side: buy/sell/neutral）。
本模块按单笔成交额分档（超大单/大单/中单/小单），增量累计当日资金流：

- 主力 = 超大单 + 大单
- 各档净额 = 买入额 - 卖出额（中性单不计入买卖方向）
- 各档 % = 净额 / 当日总成交额 × 100

口径说明：
- 分档阈值（元）默认：超大单 ≥ 100 万、大单 20-100 万、中单 4-20 万、小单 < 4 万，
  与通达信/东财等常见口径相近但可能不完全一致，前端展示时注意。
- 累计基于 fetch_ticks 去重后的新增分笔（连续轮次增量远小于去重窗口，可靠）。
- 非交易时段无分笔数据，资金流保持当日累计值。

用法：
- ``accumulate_ticks(code, ticks)``：行情路径增量累计（每笔 dict 含 price/volume/side）；
- ``get_fund_flow(code)``：读取累计结果（无数据返回 None）；
- ``reset()``：每日开盘重置（或测试用）。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 分档阈值（元）：超大单 ≥ SUPER_AMOUNT，大单 ≥ BIG_AMOUNT，中单 ≥ MID_AMOUNT，其余小单
SUPER_AMOUNT = 1_000_000.0
BIG_AMOUNT = 200_000.0
MID_AMOUNT = 40_000.0

BUCKET_SUPER = "super"
BUCKET_BIG = "big"
BUCKET_MID = "mid"
BUCKET_SMALL = "small"
BUCKETS = (BUCKET_SUPER, BUCKET_BIG, BUCKET_MID, BUCKET_SMALL)

_flows: dict[str, "_FlowAccumulator"] = {}
_guard = threading.Lock()


@dataclass
class _FlowAccumulator:
    buy: dict[str, float] = field(default_factory=lambda: {b: 0.0 for b in BUCKETS})
    sell: dict[str, float] = field(default_factory=lambda: {b: 0.0 for b in BUCKETS})
    total: float = 0.0


def reset() -> None:
    """清空全部资金流累计（每日开盘/测试用）。"""
    with _guard:
        _flows.clear()


def bucket_of(amount: float) -> str:
    """按单笔金额分档。"""
    if amount >= SUPER_AMOUNT:
        return BUCKET_SUPER
    if amount >= BIG_AMOUNT:
        return BUCKET_BIG
    if amount >= MID_AMOUNT:
        return BUCKET_MID
    return BUCKET_SMALL


def accumulate_ticks(code: str, ticks: list[dict[str, Any]]) -> None:
    """增量累计分笔资金流（每笔需含 price/volume(手)/side）。"""
    with _guard:
        acc = _flows.setdefault(code, _FlowAccumulator())
    for tick in ticks:
        try:
            price = float(tick.get("price") or 0.0)
            vol = float(tick.get("volume") or 0.0)  # 手
            side = str(tick.get("side") or "neutral").lower()
            amount = price * vol * 100
            if amount <= 0:
                continue
            acc.total += amount
            if side == "buy":
                acc.buy[bucket_of(amount)] += amount
            elif side == "sell":
                acc.sell[bucket_of(amount)] += amount
            # neutral（集合竞价等）不计入买卖方向，只计入总量
        except Exception:
            logger.debug("accumulate tick failed for %s", code, exc_info=True)


def get_fund_flow(code: str) -> dict[str, Any] | None:
    """读取某只股票的当日资金流累计；无数据返回 None。"""
    with _guard:
        acc = _flows.get(code)
        if acc is None or acc.total <= 0:
            return None

        def _net(bucket: str) -> float:
            return acc.buy[bucket] - acc.sell[bucket]

        main_net = _net(BUCKET_SUPER) + _net(BUCKET_BIG)

        def _pct(net: float) -> float:
            return round(net / acc.total * 100, 2) if acc.total > 0 else 0.0

        return {
            "code": code,
            "mainNetAmount": round(main_net, 2),
            "mainNetPct": _pct(main_net),
            "bigNetAmount": round(_net(BUCKET_BIG), 2),
            "bigNetPct": _pct(_net(BUCKET_BIG)),
            "midNetAmount": round(_net(BUCKET_MID), 2),
            "midNetPct": _pct(_net(BUCKET_MID)),
            "smallNetAmount": round(_net(BUCKET_SMALL), 2),
            "smallNetPct": _pct(_net(BUCKET_SMALL)),
            "totalAmount": round(acc.total, 2),
        }


def snapshot() -> list[dict[str, Any]]:
    """全部有数据的股票资金流（供广播用）。"""
    with _guard:
        codes = list(_flows.keys())
    items = [item for code in codes if (item := get_fund_flow(code)) is not None]
    return items
