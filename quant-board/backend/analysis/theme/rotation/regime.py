"""rotation_regime 轮动状态（设计文档 §5.3，2026-09-26 用户裁决重构为引擎权威口径）。

**生产消费口径（Phase R3 起）**：不自算第三套状态体系（single-source-of-truth）——
轮动状态 = 引擎 `rotationSummary.rotationState` 六值原值（half_hour 15:00 槽）
+ Top1 稳定性辅助维度（rank Top1 连续保持天数，阈值参数化）；market_phase
同取引擎 half_hour 15:00 帧，两轴独立采集互不推导（Phase R2 实证两者低相关）。
`rotation_state_context` 组装逐日状态上下文，任一输入缺失打 qualityFlags 不伪造。

**诊断对照口径（Phase R2，不进生产消费）**：classify_regime / regime_sequence /
transition_counts 为 rot×entropy 双轴三态纯函数。Phase R2 实证 rank Top10 口径下
两轴正相关（快换手⇔熵高），rotating 态 9 组阈值全 0 天、rot_hi 不敏感——双轴
设计前提（两轴独立刻画轮动）不成立，仅保留供 runner 对照复现，勿接入信号消费。
R1 实证锚点：7-8 月 rot 0.89-0.93/entropy 0.96（chaotic 形态）；9 月 rot 0.45/
entropy 0.84（concentrated 形态）。
"""

from __future__ import annotations

from typing import Any

REGIME_CHAOTIC = "chaotic"
REGIME_CONCENTRATED = "concentrated"
REGIME_ROTATING = "rotating"

DEFAULT_ROT_HI = 0.70
DEFAULT_ENTROPY_HI = 0.90

DEFAULT_HEAD_STABLE_MIN_DAYS = 3


def top1_streaks(top1_by_day: dict[str, str | None]) -> dict[str, int | None]:
    """逐日 rank Top1 主题 {date: theme|None} → {date: 连续保持天数|None}。

    同主题连续保持 +1，切换重置 1；None 日（无数据/无 rank）计数中断并如实输出
    None（不可知 ≠ 1），下一个已知日从 1 重算，不跨缺口接段。日期按字典序累计，
    与插入顺序无关。
    """
    streaks: dict[str, int | None] = {}
    prev_theme: str | None = None
    prev_streak: int | None = None
    for d in sorted(top1_by_day):
        theme = top1_by_day[d]
        if theme is None:
            streaks[d] = None
            prev_theme = None
            prev_streak = None
            continue
        streaks[d] = prev_streak + 1 if theme == prev_theme and prev_streak is not None else 1
        prev_theme = theme
        prev_streak = streaks[d]
    return streaks


def rotation_state_context(
    engine_rotation_state: str | None,
    market_phase: str | None,
    top1_streak: int | None,
    *,
    head_stable_min_days: int = DEFAULT_HEAD_STABLE_MIN_DAYS,
) -> dict[str, Any]:
    """单日轮动状态上下文：引擎 rotationState/market_phase 原值 + Top1 稳定性标签。

    fail-visible：任一输入缺失（None 或空串）在 qualityFlags 打结构化标记，
    对应字段如实为 None，不伪造中性值；headStable 仅在 streak 可知时有定义
    （streak >= head_stable_min_days，含边界）。
    """
    if head_stable_min_days < 1:
        raise ValueError(f"head_stable_min_days must be >= 1, got {head_stable_min_days}")
    state = engine_rotation_state or None
    phase = market_phase or None
    flags: list[str] = []
    if state is None:
        flags.append("missing_rotation_state")
    if phase is None:
        flags.append("missing_market_phase")
    if top1_streak is None:
        flags.append("missing_top1_streak")
    return {
        "rotationState": state,
        "marketPhase": phase,
        "top1Streak": top1_streak,
        "headStable": None if top1_streak is None else top1_streak >= head_stable_min_days,
        "qualityFlags": flags,
    }


def classify_regime(
    rot_speed: float | None,
    entropy: float | None,
    *,
    rot_hi: float = DEFAULT_ROT_HI,
    entropy_hi: float = DEFAULT_ENTROPY_HI,
) -> str | None:
    """[仅诊断对照] 单日两轴指标 → 三态标签；任一缺失返回 None（不伪造）。"""
    if rot_speed is None or entropy is None:
        return None
    fast = rot_speed >= rot_hi
    scattered = entropy >= entropy_hi
    if fast and scattered:
        return REGIME_CHAOTIC
    if not fast and not scattered:
        return REGIME_CONCENTRATED
    if fast:
        return REGIME_ROTATING
    return REGIME_CHAOTIC


def regime_sequence(
    daily_metrics: dict[str, dict[str, Any]],
    *,
    rot_hi: float = DEFAULT_ROT_HI,
    entropy_hi: float = DEFAULT_ENTROPY_HI,
) -> dict[str, str | None]:
    """[仅诊断对照] 逐日两指标（rot_speed、entropy）{date: {rot_speed, entropy}} → {date: regime|None}。"""
    return {
        d: classify_regime(m.get("rot_speed"), m.get("entropy"), rot_hi=rot_hi, entropy_hi=entropy_hi)
        for d, m in daily_metrics.items()
    }


def transition_counts(seq: dict[str, str | None]) -> dict[tuple[str, str], int]:
    """[仅诊断对照] 相邻可计算日的态切换计数（相同态不计；None 日断开不计）。键按字典序输出。返回 tuple 键，不可直接 json 序列化；落 JSON 报告时需转为 'chaotic->concentrated' 形式字符串键（R2 runner 已处理）。"""
    days = sorted(seq)
    counts: dict[tuple[str, str], int] = {}
    prev: str | None = None
    for d in days:
        cur = seq[d]
        if cur is None:
            prev = None
            continue
        if prev is not None and prev != cur:
            counts[(prev, cur)] = counts.get((prev, cur), 0) + 1
        prev = cur
    return dict(sorted(counts.items()))
