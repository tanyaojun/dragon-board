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
    # 服务端直连 THS 构建的 limitSummary（2026-09-25 根治浏览器 bundle 断供依赖，
    # 非空时优先于 snapshot_context.marketData / market_meta 原料）
    limit_summary: dict[str, Any] = field(default_factory=dict)
    # 服务端指数证据（sh/hs300/zz500/zz1000 涨跌），题材轮动 _market_change 输入；
    # 2026-10-20 v7 起可含嵌套子键 indexExtra（szcz/cybz/kc50，relay 叙事消费）——
    # additive-only，rotation 引擎对其免疫（值无顶层 change 键，golden 零漂移）
    indices: dict[str, Any] = field(default_factory=dict)

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
