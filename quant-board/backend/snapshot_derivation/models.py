"""快照派生层模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarketFactBundle:
    """一次采集得到的原始事实（派生层只读，不发起 I/O）。

    同刻多个快照类型共享同一份 fact，按类型各自派生 record/frame/stockRows/sectorRows。
    """

    snapshot_type: str = ""
    trading_date: str = ""
    slot_time: str = ""
    timestamp_ms: int = 0
    dataset_id: str = "dragonboard_live"
    source: str = "quantboard_backend_collector"
    capture_mode: str = "real_time"

    stocks: list[dict[str, Any]] = field(default_factory=list)
    quotes: list[dict[str, Any]] = field(default_factory=list)
    depth: list[dict[str, Any]] = field(default_factory=list)
    money_flow: list[dict[str, Any]] = field(default_factory=list)
    themes: dict[str, list[str]] = field(default_factory=dict)
    limit_up: dict[str, dict[str, Any]] = field(default_factory=dict)
    sectors: list[dict[str, Any]] = field(default_factory=list)
    # 采集层 SourceHealth 对象（含 details/coverage 等审计字段）
    source_health: list[Any] = field(default_factory=list)
    snapshot_context: dict[str, Any] = field(default_factory=dict)
    market_meta: dict[str, Any] = field(default_factory=dict)
    quality_issues: list[dict[str, Any]] = field(default_factory=list)

    algorithm_version: str = "snapshot_derivation_v1"
    config_hash: str = "snapshot_derivation_v1_default"


@dataclass
class SnapshotBundle:
    """派生结果：与 MongoDB 四类事实一一对应。"""

    records: list[dict[str, Any]] = field(default_factory=list)
    frames: list[dict[str, Any]] = field(default_factory=list)
    stock_rows: list[dict[str, Any]] = field(default_factory=list)
    sector_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_ingest_bundle(self) -> dict[str, Any]:
        """转成 ingest normalizer 接受的 bundle dict。"""
        return {
            "items": self.records,
            "frames": self.frames,
            "stockRows": self.stock_rows,
            "sectorRows": self.sector_rows,
        }
