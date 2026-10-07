# -*- coding: utf-8 -*-
"""横截面相对强弱观察因子（2026-08-17 核心算法升级方向 A）。

Dragon Board 核心资产是八平台热榜合并排名（avgRankNum），engine.py 的 frame_cross_section
只用于市场 median 环境门（frame_market_median），个股主信号（动量/MACD/量比）全是纯时序
自回归——热榜横截面信息未进入个股信号。

本模块把个股横截面 percentile 相对强弱做成观察因子（crossSection，第 5 维投票默认打开
tierSynergyCrossSectionVote=1.0，2026-08-17 用户决策；实证 all syn +10%/8月 +237%）：

- percentile：个股当前帧横截面 percentile（0-100，avgRankNum 越小 percentile 越高）
- percentileDelta：个股 percentile 相对上一帧变化（正 = 热度排名上升）
- relativeToMarket：percentile - 市场 median percentile（个股相对全市场强弱）
- signalTier A/B/C/D：参与 _synergy_tier 第 5 维投票（A/B 正、C/D 负 × 权重）

档位规则（config 可调，默认值 = 设计值，golden 不漂移）：
- A 强：percentile >= strongMin(85) 且 delta >= strongDeltaUp(5)（高位 + 上升确认）
- A 强（持续高位替代路径，2026-09-13 方案2，默认关闭）：percentile >= persistMin(90)
  且近 persistFrames 帧均值 >= persistMeanMin(85) 且窗口满帧合法——数学边界
  delta <= 100 - percentile 使 pct > 95 的强势股（榜首）delta 确认永不可达，
  其强势体现在持续停留高位；判定顺序 A-delta > A-persist，开启后纯增量 B 升 A
- B 偏强：percentile >= strongAbsMin(70) 或 (percentile >= 50 且 delta >= 15)
- C 偏弱：percentile <= 30（无效轴，与中位兜底同返回 C，审计 I-1 归档）或
  (percentile <= 50 且 delta <= -15)
- D 弱：percentile <= weakMax(15) 且 delta <= weakDeltaDown(-5)（低位 + 下降确认）
- unknown：percentile 不可得（不在横截面）
- 首帧缺 delta：降级绝对档（不给 A/D，delta 是 A/D 的必要确认；中位无上升证据给 C）
- 市场 median 缺失：relativeToMarket=None，绝对档位照常（fail-visible，不阻断）
"""
from __future__ import annotations

import math
from typing import Any

CROSS_SECTION_DEFAULTS: dict[str, float] = {
    "crossSectionStrongMin": 85.0,
    "crossSectionStrongDeltaUp": 5.0,
    "crossSectionMidMin": 50.0,
    "crossSectionMidDeltaUp": 15.0,
    "crossSectionWeakMax": 15.0,
    "crossSectionWeakDeltaDown": -5.0,
    "crossSectionMidMax": 50.0,
    "crossSectionMidDeltaDown": -15.0,
    # B 档绝对线（P1-0 参数化，默认=原硬编码 70；<=30 低位线为无效轴不参数化，审计 I-1）
    "crossSectionStrongAbsMin": 70.0,
    # 持续高位 A 档替代路径（方案2）：Frames=0 关闭（默认，golden 不漂移）
    "crossSectionPersistFrames": 0.0,
    "crossSectionPersistMin": 90.0,
    "crossSectionPersistMeanMin": 85.0,
}


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _tier_from(
    percentile: float,
    delta: float | None,
    persist: tuple[int, float] | None,
    c: Any,
    persist_independent: bool = False,
) -> tuple[str, list[str]]:
    """档位判定。delta=None（首帧/缺历史）时降级绝对档，A/D 需要 delta 确认。

    persist=(窗口N, 近N帧均值)：持续高位 A 档替代路径（方案2）。放在 A-delta 之后：
    开启后原 A/B/C/D 输出与文案零漂移，变更面 = 纯增量（部分 B 升 A）。
    persist_independent（T4，2026-10-07 预登记合同）：独立档 A_PERSIST——eligible 人群
    （pct≥90 ∧ 近5帧均值≥85）不并入 A（H2 合并稀释前例），delta-A 之后、原 B 之前返回
    "A_PERSIST"，票值由 tierSynergyCsPersistStrength 三态定（默认 0.5=同 B 票零行为）。
    """
    if delta is not None:
        if percentile >= c.crossSectionStrongMin and delta >= c.crossSectionStrongDeltaUp:
            return "A", ["高位 + 热度排名上升（横截面强势确认）"]
        if (
            persist is not None
            and percentile >= c.crossSectionPersistMin
            and persist[1] >= c.crossSectionPersistMeanMin
        ):
            return "A", [f"持续高位（近{persist[0]}帧均值 {persist[1]:.1f}）"]
        if persist_independent:
            return "A_PERSIST", ["持续高位独立档（未达 delta-A 确认，独立计票）"]
        if percentile >= c.crossSectionMidMin and delta >= c.crossSectionMidDeltaUp:
            return "B", ["中位之上 + 热度显著上升"]
        if percentile <= c.crossSectionWeakMax and delta <= c.crossSectionWeakDeltaDown:
            return "D", ["低位 + 热度排名下降（横截面弱势确认）"]
        if percentile <= c.crossSectionMidMax and delta <= c.crossSectionMidDeltaDown:
            return "C", ["热度排名显著下降"]
        if percentile >= c.crossSectionStrongAbsMin:
            return "B", ["横截面高位"]
        if percentile <= 30:
            return "C", ["横截面低位"]
        # 中位区间 + 无明显变化：保守偏弱（无强势证据）
        return "C", ["中位区间无强势证据"]
    # 首帧缺 delta：绝对档降级，不给 A/D
    if percentile >= c.crossSectionStrongMin:
        return "B", ["高位但缺 delta 确认（首帧）"]
    if percentile >= c.crossSectionStrongAbsMin:
        return "B", ["横截面高位（首帧缺 delta）"]
    if percentile <= c.crossSectionWeakMax:
        return "C", ["低位但缺 delta 确认（首帧）"]
    return "C", ["中位区间无强势证据（首帧缺 delta）"]


def compute_cross_section(
    percentiles: list[float],
    market_median: float | None,
    config: Any,
) -> dict[str, Any]:
    """计算个股横截面相对强弱观察。

    Args:
        percentiles: 个股横截面 percentile 序列（含当前帧，[-1] 为当前；同 engine histories item[2]）。
        market_median: 当前帧市场横截面 percentile 中位数（可 None，fail-visible）。
        config: RankTrendConfig（crossSection* 字段）。

    Returns:
        observation.crossSection 结构：percentile / percentileDelta / relativeToMarket /
        signalTier（A/B/C/D/unknown）/ tierReasons（结构化原因）。
    """
    if not percentiles:
        return {
            "percentile": None,
            "percentileDelta": None,
            "relativeToMarket": None,
            "signalTier": "unknown",
            "tierReasons": ["横截面数据不足（无 avgRankNum，不在横截面）"],
        }
    percentile = _finite(percentiles[-1])
    if percentile is None:
        return {
            "percentile": None,
            "percentileDelta": None,
            "relativeToMarket": None,
            "signalTier": "unknown",
            "tierReasons": ["横截面 percentile 非法"],
        }
    delta: float | None = None
    if len(percentiles) >= 2:
        prev = _finite(percentiles[-2])
        if prev is not None:
            delta = percentile - prev
    # 持续高位窗口（方案2）：近 N 帧全部合法才计算均值（证据不足不伪造持续性）。
    # 窗口含 [-2] 项 → persist 非 None 时 delta 必非 None，首帧/单点天然不触发。
    persist: tuple[int, float] | None = None
    persist_frames = int(_finite(getattr(config, "crossSectionPersistFrames", 0)) or 0)
    if persist_frames >= 2:
        window = [_finite(v) for v in percentiles[-persist_frames:]]
        values = [v for v in window if v is not None]
        if len(values) == persist_frames:
            persist = (persist_frames, sum(values) / persist_frames)
    # T4 独立档 eligible 判定（固定 N=5，不消费 crossSectionPersistFrames）：pct≥90 ∧ 近5均值≥85。
    persist_independent = False
    if getattr(config, "crossSectionPersistIndependentTier", False) and len(percentiles) >= 5 and delta is not None:
        vals5 = [_finite(v) for v in percentiles[-5:]]
        if all(v is not None for v in vals5):
            persist_independent = percentile >= 90.0 and sum(vals5) / 5 >= 85.0
    market = _finite(market_median)
    relative = percentile - market if market is not None else None
    tier, reasons = _tier_from(percentile, delta, persist, config, persist_independent=persist_independent)
    if market is None:
        reasons = reasons + ["市场 median 缺失（relativeToMarket 不可算）"]
    return {
        "percentile": percentile,
        "percentileDelta": delta,
        "relativeToMarket": relative,
        "signalTier": tier,
        "tierReasons": reasons,
    }
