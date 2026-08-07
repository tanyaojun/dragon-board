# quant-board/backend/analysis/theme/momentum_config.py
"""题材动量 v2 配置：默认参数唯一来源。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ThemeMomentumConfig:
    """题材动量 v2 默认参数。窗口/权重/阈值均可按数据集覆盖。"""

    # ── 日线窗口 ──
    rps_windows: tuple[int, int, int] = (5, 10, 20)
    rps_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)  # 短窗权重大（A 股扩散期短）
    min_history_days: int = 5  # 不足 → 该维度 null + reason
    cross_section_min: int = 20  # 全市场横截面最小板块数
    near_high_full_window_days: int = 250  # 52 周高完整窗口；不足降级为数据窗内高点

    # ── 权重（五正向维度，和 0.95；拥挤惩罚独立扣分） ──
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "rps": 0.25,
            "near_high": 0.15,
            "window_momentum": 0.20,
            "breadth": 0.20,
            "flow_volume": 0.15,
        }
    )

    # ── 动量/方向阈值 ──
    momentum_coefficient: float = 2.0  # 50 + 加权收益率×系数
    direction_up_threshold: float = 55.0  # score ≥ 55 → up
    direction_down_threshold: float = 45.0  # score ≤ 45 → down

    # ── 拥挤惩罚（门禁，0-15 扣分） ──
    crowding_penalty_max: float = 15.0
    crowding_penalty_start: float = 60.0  # crowdingRisk ≥ 60 开始扣分
    crowding_penalty_slope: float = 0.3  # (crowding - start) * slope

    # ── phaseLabel 展示标签（非状态机） ──
    phase_overheated_crowding: float = 75.0
    phase_heat_score: float = 75.0
    phase_cool_score: float = 45.0
    phase_start_score: float = 60.0

    version: str = "theme_momentum_v2"
