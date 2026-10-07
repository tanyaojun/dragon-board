# -*- coding: utf-8 -*-
"""价格-排名背离观察因子（2026-08-18，G1 相位差方案落地）。

背景：价格动能裸投票实证负贡献（G1），根因是价格 vs 排名 Jump 的相位差：
- 排名 Jump = 关注度先行（预期，h1 有预测力）；价格动能 = 实际兑现（热榜股票价格已充分
  反映，h1 均值回归强，无独立预测力）；
- 正确用法是观察**背离**而非并列投票：价升排名跌（出货预警）、排名升价跌（关注度先行）
  均为可观察信号，与 Jump 互补（Jump 看排名跃迁，背离看相位差）。

state 枚举（priceDir × rankDir 交叉）：
- confirm_up：价升 + 排名升 → A 真强势（一致）
- rank_lead：排名升 + 价跌 → B 关注度先行（排名先行，价格未兑现）
- confirm_down：价跌 + 排名跌 → C
- price_lead_warn：价升 + 排名跌 → D 出货预警（价格领先但热度退潮）
- unknown：价格/排名数据不足（fail-visible）

不进 synergy 投票（观察验证区分度后定，同 crossSection 流程）。
"""
from __future__ import annotations

import math
from typing import Any

PRICE_RANK_DIVERGENCE_DEFAULTS: dict[str, float] = {
    "priceRankChangeMin": 0.0,  # 价格方向阈值：change ≥ 此值判涨、≤ -此值判跌
    "priceRankDeltaMin": 0.0,  # 排名方向阈值：percentile delta ≥ 此值判升、≤ -此值判降
}


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def compute_price_rank_divergence(
    price_changes: list[Any],
    percentiles: list[float],
    config: Any,
    *,
    gap_step: bool = False,
) -> dict[str, Any]:
    """计算个股价格-排名背离观察。

    Args:
        price_changes: 个股 change（涨跌幅，%）历史序列（[-1] 为当前帧）。
        percentiles: 个股排名百分位序列（[-1] 当前帧、[-2] 上一帧；同 engine histories item[2]）。
        config: RankTrendConfig（priceRankChangeMin/priceRankDeltaMin）。
        gap_step: 相邻序列元素跨交易日（temporalGap；Q1 合同 C-a1 前置修复）——
            跨日步 rankDir 即隔夜排名跳变（非当日背离证据），归 unknown 不判定（fail-visible）。
            调用方在 lifecycleTimeGapStrictness≠off 且时间键可用时传入；默认 False=旧行为。

    Returns:
        observation.priceRankDivergence：state / signalTier（A/B/C/D/unknown）/
        priceDir / rankDir / tierReasons。
    """
    c = config
    change_min = float(getattr(c, "priceRankChangeMin", 0.0))
    delta_min = float(getattr(c, "priceRankDeltaMin", 0.0))

    cur_change = _finite(price_changes[-1] if price_changes else None)
    cur_pct = _finite(percentiles[-1] if percentiles else None)
    prev_pct = _finite(percentiles[-2] if len(percentiles) >= 2 else None)
    if cur_change is None or cur_pct is None:
        return {
            "state": "unknown",
            "signalTier": "unknown",
            "priceDir": None,
            "rankDir": None,
            "tierReasons": ["价格/排名数据不足（背离不可判定）"],
        }

    # 严格比较（2026-08-19 审计修复）：默认阈值 0.0 时 change=0/delta=0 必须归 flat，
    # 否则 0 变化被标 confirm_up/A 污染档位统计（flat 分支成死代码）。
    price_dir = "up" if cur_change > change_min else "down" if cur_change < -change_min else "flat"
    if gap_step:
        return {
            "state": "unknown",
            "signalTier": "unknown",
            "priceDir": price_dir,
            "rankDir": None,
            "tierReasons": ["跨日缺口步，背离不可判定（temporalGap）"],
        }
    if prev_pct is None:
        return {
            "state": "unknown",
            "signalTier": "unknown",
            "priceDir": price_dir,
            "rankDir": None,
            "tierReasons": ["排名历史不足（缺上一帧，背离不可判定）"],
        }
    delta = cur_pct - prev_pct
    rank_dir = "up" if delta > delta_min else "down" if delta < -delta_min else "flat"

    if price_dir == "up" and rank_dir == "up":
        state, tier, reasons = "confirm_up", "A", ["价升 + 排名升（一致强势，无背离）"]
    elif price_dir == "up" and rank_dir == "down":
        state, tier, reasons = "price_lead_warn", "D", ["价升但排名跌（出货预警：价格领先热度退潮）"]
    elif price_dir == "down" and rank_dir == "up":
        state, tier, reasons = "rank_lead", "B", ["排名升但价跌（关注度先行：排名先于价格兑现）"]
    elif price_dir == "down" and rank_dir == "down":
        state, tier, reasons = "confirm_down", "C", ["价跌 + 排名跌（一致弱势）"]
    else:
        state, tier, reasons = "unknown", "unknown", ["价格/排名方向不明确（flat 态）"]

    return {
        "state": state,
        "signalTier": tier,
        "priceDir": price_dir,
        "rankDir": rank_dir,
        "tierReasons": reasons,
    }
