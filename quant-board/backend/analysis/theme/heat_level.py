"""题材热度相对分（heatLevel，0-100 rank 百分位）的生成与统一解释。

2026-09 heatLevel 落库迁移（design:
docs/theme-rotation/2026-09-03-heatlevel-persistence-migration-design.md）：
- heatScore 是 KPL 人气总和（绝对值，热门题材可达数千，theme-market-v2）；
- 0-100 相对分统一由 heatLevel 承载（rank1 → 100）；
- 本模块是口径解释的唯一实现，消费方（trend/momentum/rotation/backtest）
  不得再各自维护 ">100 视为缺失" 的启发式。
"""
from __future__ import annotations

import math
from typing import Any

HEAT_CALIBER_V1 = "theme-market-v1"
HEAT_CALIBER_V2 = "theme-market-v2"


def _num_or_none(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _int_or_zero(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def rank_percentile(rank: int, ranked_total: int) -> float | None:
    """rank 百分位（0-100，rank1 → 100）；rank 或总数无效时 None。"""
    if rank <= 0 or ranked_total <= 0:
        return None
    return round((1 - (rank - 1) / ranked_total) * 100, 1)


def attach_heat_levels(factors: list[dict[str, Any]]) -> None:
    """按 rank 百分位就地附加 heatLevel（rank1 → 100）。

    无热度（heatScore None）或无 rank（rank=0，降级帧）的 factor 显式置 None，
    不回退 heatScore（M3：≤100 绝对值是冷题材人气总和，不是相对分）。"""
    ranked_total = sum(1 for factor in factors if _int_or_zero(factor.get("rank")) > 0)
    for factor in factors:
        if factor.get("heatScore") is None:
            factor["heatLevel"] = None
            continue
        factor["heatLevel"] = rank_percentile(_int_or_zero(factor.get("rank")), ranked_total)


def heat_caliber_of(row: dict[str, Any]) -> str:
    """落库行/因子的热度口径标记：heatFactorVersion 优先，其次 metadata.factorVersion；无标记返回 ""。"""
    version = row.get("heatFactorVersion")
    if isinstance(version, str) and version.strip():
        return version.strip()
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        value = str(metadata.get("factorVersion") or "").strip()
        if value:
            return value
    return ""


def resolve_heat_level(row: dict[str, Any]) -> float | None:
    """heatLevel 统一消费规则（design §4.2 三分支，全部消费点必须走这里）：

    1. heatLevel key 存在 → 数值直接用（0-100，含 SQL varchar 回读的字符串数字）；
       显式 None / 非法值 = 诚实缺失，不回退。
    2. key 不存在（旧落库行）→ 按口径标记回退：theme-market-v1 或未标记 且
       heatScore <= 100 → heatScore 当相对分；theme-market-v2 → 不回退。
    3. heatScore > 100 → 一律缺失（最后兜底）。

    返回值 clamp 到 [0, 100]；缺失返回 None，不伪装 0。"""
    if "heatLevel" in row:
        numeric = _num_or_none(row.get("heatLevel"))
        if numeric is None:
            return None
        return max(0.0, min(100.0, numeric))
    numeric = _num_or_none(row.get("heatScore"))
    if numeric is None or numeric > 100.0:
        return None
    if heat_caliber_of(row) in ("", HEAT_CALIBER_V1):
        return max(0.0, min(100.0, numeric))
    return None
