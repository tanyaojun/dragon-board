from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BacktestDataQuality:
    """回测级数据质量报告，整合 quality_gate + NaN/Inf/覆盖率检查。"""

    passed: bool
    reasons: list[dict[str, Any]] = field(default_factory=list)
    frame_count: int = 0
    stock_count: int = 0
    sector_count: int = 0
    missing_fields: dict[str, int] = field(default_factory=dict)
    nan_counts: dict[str, int] = field(default_factory=dict)
    inf_counts: dict[str, int] = field(default_factory=dict)
    negative_price_count: int = 0
    non_positive_price_count: int = 0
    negative_volume_count: int = 0
    coverage_ratio: float = 0.0
    time_order_fixed: bool = False
    time_order_fix_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": self.reasons,
            "frameCount": self.frame_count,
            "stockCount": self.stock_count,
            "sectorCount": self.sector_count,
            "missingFields": self.missing_fields,
            "nanCounts": self.nan_counts,
            "infCounts": self.inf_counts,
            "negativePriceCount": self.negative_price_count,
            "nonPositivePriceCount": self.non_positive_price_count,
            "negativeVolumeCount": self.negative_volume_count,
            "coverageRatio": self.coverage_ratio,
            "timeOrderFixed": self.time_order_fixed,
            "timeOrderFixCount": self.time_order_fix_count,
            "warnings": self.warnings,
        }
