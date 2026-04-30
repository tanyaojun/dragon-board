from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.data.database import Base


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, default="")
    db_name: Mapped[str] = mapped_column(String(80), default="DragonBoardData")
    schema_fingerprint: Mapped[str] = mapped_column(String(96), default="")
    snapshot_count: Mapped[int] = mapped_column(Integer, default=0)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    stock_row_count: Mapped[int] = mapped_column(Integer, default=0)
    sector_row_count: Mapped[int] = mapped_column(Integer, default=0)
    start_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    snapshot_types_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SnapshotRecordModel(Base):
    __tablename__ = "snapshot_records"
    __table_args__ = (UniqueConstraint("dataset_id", "snapshot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(160), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    trading_date: Mapped[str] = mapped_column(String(16), index=True)
    slot_time: Mapped[str] = mapped_column(String(16), default="")
    timestamp: Mapped[int] = mapped_column(Integer, index=True)
    display_key: Mapped[str] = mapped_column(String(160), default="")
    capture_mode: Mapped[str] = mapped_column(String(32), default="real_time")
    source: Mapped[str] = mapped_column(String(32), default="browser_runtime")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class SnapshotFrameModel(Base):
    __tablename__ = "snapshot_frames"
    __table_args__ = (UniqueConstraint("dataset_id", "snapshot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(160), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    trading_date: Mapped[str] = mapped_column(String(16), index=True)
    slot_time: Mapped[str] = mapped_column(String(16), default="")
    timestamp: Mapped[int] = mapped_column(Integer, index=True)
    capture_mode: Mapped[str] = mapped_column(String(32), default="real_time")
    source: Mapped[str] = mapped_column(String(32), default="browser_runtime")
    market_context_json: Mapped[str] = mapped_column(Text, default="{}")
    stock_row_count: Mapped[int] = mapped_column(Integer, default=0)
    sector_row_count: Mapped[int] = mapped_column(Integer, default=0)


class SnapshotStockRowModel(Base):
    __tablename__ = "snapshot_stock_rows"
    __table_args__ = (UniqueConstraint("dataset_id", "row_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    row_id: Mapped[str] = mapped_column(String(220), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(160), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    trading_date: Mapped[str] = mapped_column(String(16), index=True)
    slot_time: Mapped[str] = mapped_column(String(16), default="")
    timestamp: Mapped[int] = mapped_column(Integer, index=True)
    capture_mode: Mapped[str] = mapped_column(String(32), default="real_time")
    code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    rank: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    zlje: Mapped[float | None] = mapped_column(Float, nullable=True)
    zljzb: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class SnapshotSectorRowModel(Base):
    __tablename__ = "snapshot_sector_rows"
    __table_args__ = (UniqueConstraint("dataset_id", "row_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    row_id: Mapped[str] = mapped_column(String(240), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(160), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    trading_date: Mapped[str] = mapped_column(String(16), index=True)
    slot_time: Mapped[str] = mapped_column(String(16), default="")
    timestamp: Mapped[int] = mapped_column(Integer, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_key: Mapped[str] = mapped_column(String(160), default="")
    entity_name: Mapped[str] = mapped_column(String(160), default="")
    rank: Mapped[int] = mapped_column(Integer, default=0)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class GoldenRankTrendCase(Base):
    __tablename__ = "golden_ranktrend_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    expected_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    strategy_name: Mapped[str] = mapped_column(String(80), default="rank_trend_candidate")
    strategy_version: Mapped[str] = mapped_column(String(40), default="0.1.0")
    snapshot_type: Mapped[str] = mapped_column(String(32), default="half_hour")
    config_hash: Mapped[str] = mapped_column(String(96), default="")
    random_seed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OptimizationRun(Base):
    __tablename__ = "optimization_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    strategy_name: Mapped[str] = mapped_column(String(80), default="rank_trend_candidate")
    method: Mapped[str] = mapped_column(String(40), default="grid")
    config_hash: Mapped[str] = mapped_column(String(96), default="")
    random_seed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
