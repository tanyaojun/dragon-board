"""主题生命周期、轮动方向与市场阶段状态机（纯函数，阈值来自 ThemeRotationConfig）。"""

from __future__ import annotations

import math
from typing import Any

from backend.analysis.theme_rotation.config import ThemeRotationConfig


def _num(value: Any, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def lifecycle_for(
    row: dict[str, Any],
    prev_lifecycle: str | None,
    cfg: ThemeRotationConfig,
) -> tuple[str, list[str]]:
    """按设计 §5.1 判定主题生命周期，返回 (state, reasons)。"""
    heat = _num(row.get("heatScore"))
    momentum = _num(row.get("momentumScore"))
    crowding = _num(row.get("crowdingRisk"))
    inflow = row.get("mainNetInflow")
    positive_streak = int(_num(row.get("positiveInflowStreak"), 0))
    negative_streak = int(_num(row.get("negativeInflowStreak"), 0))
    max_board = int(_num(row.get("maxBoardHeight"), 0))
    reasons: list[str] = []

    if heat >= cfg.climax_heat and (
        crowding >= cfg.climax_crowding or max_board >= cfg.climax_max_board
    ):
        reasons.append(
            f"heat={heat:.0f}≥{cfg.climax_heat:.0f}且拥挤≥{cfg.climax_crowding:.0f}或最高连板≥{cfg.climax_max_board}"
        )
        state = "climax"
    elif heat < cfg.ice_heat and momentum < cfg.ice_momentum:
        # 设计 §5.1：ice = heat<ice_heat 且 momentum<ice_momentum（AND，先于 cooling）
        reasons.append(
            f"heat={heat:.0f}<{cfg.ice_heat:.0f}且momentum={momentum:.0f}<{cfg.ice_momentum:.0f}"
        )
        state = "ice"
    elif momentum < cfg.cooling_momentum or (
        inflow is not None and negative_streak >= cfg.cooling_negative_inflow_streak
    ):
        reasons.append(
            f"momentum={momentum:.0f}<{cfg.cooling_momentum:.0f}或连续{cfg.cooling_negative_inflow_streak}槽资金流出"
        )
        state = "cooling"
    elif heat >= cfg.expanding_heat and crowding < cfg.climax_crowding:
        reasons.append(f"heat={heat:.0f}≥{cfg.expanding_heat:.0f}且拥挤<{cfg.climax_crowding:.0f}")
        state = "expanding"
    elif heat >= cfg.emerging_heat_min and momentum >= cfg.ice_momentum:
        reasons.append("资金由负转正，动量回暖" if positive_streak >= 1 else "heat 回到观察区间")
        state = "emerging"
    else:
        reasons.append("数据不足，中性观察")
        state = "neutral"

    # 转移约束（M2/设计 §5.1）：非相邻跳变钳制到相邻中间态。
    if prev_lifecycle and state != prev_lifecycle:
        adjacency = {
            "ice": {"emerging"},
            "emerging": {"ice", "expanding", "cooling"},
            "expanding": {"emerging", "climax", "cooling"},
            "climax": {"expanding", "cooling"},
            "cooling": {"expanding", "emerging", "ice"},
            "neutral": {"ice", "emerging", "expanding"},
        }
        if prev_lifecycle not in adjacency or state not in adjacency[prev_lifecycle]:
            if state == "climax" and prev_lifecycle in {"ice", "emerging", "neutral"}:
                state, reasons = "expanding", [
                    *reasons,
                    "transition_clamped: ice/emerging→climax 非相邻，钳制到 expanding",
                ]
            elif state == "ice" and prev_lifecycle in {"climax", "expanding"}:
                state, reasons = "cooling", [
                    *reasons,
                    "transition_clamped: climax/expanding→ice 非相邻，钳制到 cooling",
                ]
            else:
                reasons = [
                    *reasons,
                    f"transition_clamped: {prev_lifecycle}→{state} 非相邻，钳制到 neutral",
                ]
                state = "neutral"
    return state, reasons


def rotation_state_for(
    lifecycle: str,
    momentum: float,
    is_mainline: bool,
    inflow_positive: bool,
) -> str:
    """在设计 §5.2 的 lifecycle 之上叠加方向与主线性。"""
    if lifecycle == "cooling":
        return "cooling"
    if lifecycle == "emerging":
        return "emerging"
    if lifecycle == "ice":
        return "neutral"
    if lifecycle in ("expanding", "climax"):
        return "mainline" if is_mainline else "inflow"
    if momentum < 50.0:
        return "outflow"
    if inflow_positive:
        return "inflow"
    return "neutral"


def market_phase_for(
    *,
    max_board_height: int,
    rotation_speed: float | None,
    mainline_count: int,
    mainline_concentration: float | None,
    total_zt_count: int,
    cooling_theme_ratio: float | None = None,
    negative_inflow_theme_ratio: float | None = None,
    cfg: ThemeRotationConfig,
) -> str:
    """按设计 §5.3 判定市场阶段（含 cooling/neutral 兜底，审计 C4/M3）。"""
    if (
        mainline_concentration is not None
        and mainline_concentration >= cfg.market_climax_min_concentration
        and max_board_height >= cfg.market_rising_min_board
    ):
        return "climax"
    if max_board_height >= cfg.market_climax_max_board:
        return "climax"
    if (
        (cooling_theme_ratio is not None and cooling_theme_ratio >= cfg.market_cooling_theme_ratio)
        or (
            negative_inflow_theme_ratio is not None
            and negative_inflow_theme_ratio >= cfg.market_cooling_negative_inflow_ratio
        )
    ):
        return "cooling"
    if max_board_height <= cfg.market_ice_max_board and total_zt_count < cfg.market_ice_min_zt_count:
        return "ice"
    if (
        cfg.market_rising_min_board <= max_board_height <= cfg.market_climax_max_board - 1
        and mainline_count >= 1
    ):
        return "rising"
    if (
        rotation_speed is not None
        and rotation_speed >= cfg.market_chaos_min_rotation_speed
        and mainline_count == 0
    ):
        return "chaos"
    if (
        rotation_speed is not None
        and rotation_speed < cfg.market_neutral_max_rotation_speed
        and mainline_count == 0
    ):
        return "neutral"
    return "chaos"


def rotation_speed_score(rank_changes: list[int]) -> float | None:
    """全市场 rank turnover 映射 0-100。"""
    if not rank_changes:
        return None
    mean_abs = sum(abs(r) for r in rank_changes) / len(rank_changes)
    return _clamp(mean_abs * 8.0)


def mainline_concentration(heats: list[float], top_n: int = 3) -> float | None:
    """Top-N heat 占比，区分抱团（高）与发散（低）。"""
    if not heats or sum(heats) <= 0:
        return None
    top = sorted(heats, reverse=True)[:top_n]
    return round(sum(top) / sum(heats), 4)
