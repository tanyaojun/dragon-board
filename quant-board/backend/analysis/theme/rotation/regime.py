"""rotation_regime 三态划分（Phase R2 研究纯函数，设计文档 §5.3 轮动维）。

两轴双阈值：rot_speed（轮动速度）× entropy（排名熵，滚动窗口频率熵）。
  chaotic      快+散（rot>=rot_hi 且 entropy>=entropy_hi）；慢+散归并于此（无主线语义）
  concentrated 慢+聚（rot<rot_hi 且 entropy<entropy_hi）
  rotating     快+聚（rot>=rot_hi 且 entropy<entropy_hi，主线内快速轮动）
R1 实证锚点：7-8 月 rot 0.89-0.93/entropy 0.96（chaotic 形态）；9 月 rot 0.45/entropy 0.84
（concentrated 形态）。阈值默认为研究初始值，R2 runner 做 3×3 敏感性。
regime 只描述轮动状态本身，不预设好坏；与 market_phase 的联合分布由 runner 输出。
"""

from __future__ import annotations

from typing import Any

REGIME_CHAOTIC = "chaotic"
REGIME_CONCENTRATED = "concentrated"
REGIME_ROTATING = "rotating"

DEFAULT_ROT_HI = 0.70
DEFAULT_ENTROPY_HI = 0.90


def classify_regime(
    rot_speed: float | None,
    entropy: float | None,
    *,
    rot_hi: float = DEFAULT_ROT_HI,
    entropy_hi: float = DEFAULT_ENTROPY_HI,
) -> str | None:
    """单日两轴指标 → 三态标签；任一缺失返回 None（不伪造）。"""
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
    """逐日两指标（rot_speed、entropy）{date: {rot_speed, entropy}} → {date: regime|None}。"""
    return {
        d: classify_regime(m.get("rot_speed"), m.get("entropy"), rot_hi=rot_hi, entropy_hi=entropy_hi)
        for d, m in daily_metrics.items()
    }


def transition_counts(seq: dict[str, str | None]) -> dict[tuple[str, str], int]:
    """相邻可计算日的态切换计数（相同态不计；None 日断开不计）。键按字典序输出。返回 tuple 键，不可直接 json 序列化；落 JSON 报告时需转为 'chaotic->concentrated' 形式字符串键（R2 runner 已处理）。"""
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
