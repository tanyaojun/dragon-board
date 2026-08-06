"""题材轮动引擎配置：默认参数唯一来源。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ThemeRotationConfig:
    """轮动引擎默认参数。窗口/权重/阈值均可按数据集覆盖。"""

    window_slots: int = 8
    min_slots_for_state: int = 3
    min_factors_for_score: int = 3

    weights: dict[str, float] = field(
        default_factory=lambda: {
            "strength": 0.30,
            "flow": 0.25,
            "breadth": 0.20,
            "crowding": 0.15,
            "lifecycle": 0.10,
        }
    )

    # ── 主题生命周期阈值（lifecycle.py） ──
    ice_heat: float = 40.0
    ice_momentum: float = 40.0
    emerging_heat_min: float = 40.0
    expanding_heat: float = 60.0
    climax_heat: float = 80.0
    climax_crowding: float = 75.0
    climax_max_board: int = 7
    cooling_momentum: float = 35.0
    cooling_negative_inflow_streak: int = 2

    # ── 主线判定 ──
    mainline_top_n: int = 3
    concentration_top_n: int = 3

    # ── 市场阶段（lifecycle.py） ──
    market_ice_max_board: int = 3
    market_ice_min_zt_count: int = 30
    market_rising_min_board: int = 7
    market_climax_max_board: int = 10
    market_climax_min_concentration: float = 0.80
    market_chaos_min_rotation_speed: float = 60.0
    market_neutral_max_rotation_speed: float = 40.0
    market_cooling_theme_ratio: float = 0.35
    market_cooling_negative_inflow_ratio: float = 0.50
    min_mainline_z_rank: int = 3
    min_mainline_concentration_rank: int = 3

    algorithm_version: str = "theme_rotation_v2"
