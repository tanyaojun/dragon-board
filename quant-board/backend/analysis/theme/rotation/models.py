"""题材轮动输出合同。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThemeFactorScores:
    """单个题材在当前槽的五组因子得分（0-100，缺失为 None）。"""

    theme_id: str
    theme_name: str
    strength: float | None = None
    flow: float | None = None
    breadth: float | None = None
    crowding: float | None = None
    lifecycle: float | None = None
    missing: list[str] = field(default_factory=list)

    def available(self) -> list[str]:
        """返回非缺失因子名，用于权重归一化。"""
        return [
            key
            for key in ("strength", "flow", "breadth", "crowding", "lifecycle")
            if getattr(self, key) is not None
        ]


@dataclass
class ThemeRotationStatus:
    """单个题材的轮动输出（写入 sector row）。"""

    theme_id: str
    theme_name: str
    rotation_state: str | None = None
    lifecycle: str | None = None
    rotation_score: float | None = None
    rank: int = 0
    rank_change: int = 0
    heat_trend: float | None = None
    flow_trend: float | None = None
    breadth_trend: float | None = None
    crowding_trend: float | None = None
    mainline_concentration_rank: int | None = None
    reasons: list[str] = field(default_factory=list)
    factor_breakdown: dict[str, float | None] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)


@dataclass
class MarketRotationSummary:
    """市场级轮动摘要（写入 frame.rotationSummary）。"""

    market_phase: str = "unknown"
    rotation_speed: float | None = None
    mainline_concentration: float | None = None
    max_board_height: int | None = None
    main_lines: list[dict[str, Any]] = field(default_factory=list)
    inflow_themes: list[dict[str, Any]] = field(default_factory=list)
    outflow_themes: list[dict[str, Any]] = field(default_factory=list)
    suggestion: str = ""
    computed_at: int = 0
    algorithm_version: str = "theme_rotation_v2"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_camel_dict(self) -> dict[str, Any]:
        """序列化为消费端统一的 camelCase 合同（审计 C1：禁止 snake_case 落库）。"""
        return {
            "marketPhase": self.market_phase,
            "rotationSpeed": self.rotation_speed,
            "mainlineConcentration": self.mainline_concentration,
            "maxBoardHeight": self.max_board_height,
            "mainLines": self.main_lines,
            "inflowThemes": self.inflow_themes,
            "outflowThemes": self.outflow_themes,
            "suggestion": self.suggestion,
            "computedAt": self.computed_at,
            "algorithmVersion": self.algorithm_version,
            "evidence": self.evidence,
        }


@dataclass
class ThemeRotationResult:
    """引擎一次计算的完整输出。"""

    statuses: list[ThemeRotationStatus] = field(default_factory=list)
    market: MarketRotationSummary = field(default_factory=MarketRotationSummary)
    quality_issues: list[str] = field(default_factory=list)
    frames_used: int = 0


@dataclass
class HistorySlot:
    """一个历史槽位（来自 MongoDB，供引擎消费）。"""

    timestamp_ms: int
    trading_date: str
    sector_rows: list[dict[str, Any]] = field(default_factory=list)
    stock_rows: list[dict[str, Any]] | None = None


@dataclass
class RotationHistory:
    """历史读取结果。"""

    slots: list[HistorySlot] = field(default_factory=list)
    source: str = "mongodb"
