from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import Session as ORMSession

from backend.data.database import Base, ResearchBase
from backend.data.json_codec import dumps_json_field


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
    captured_at: Mapped[int] = mapped_column(Integer, default=0)
    data_timestamp: Mapped[int] = mapped_column(Integer, default=0)
    delay_ms: Mapped[int] = mapped_column(Integer, default=0)
    quality_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    source: Mapped[str] = mapped_column(String(32), default="browser_runtime")


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
    display_key: Mapped[str] = mapped_column(String(160), default="")
    capture_mode: Mapped[str] = mapped_column(String(32), default="real_time")
    quality_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    delay_ms: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(32), default="browser_runtime")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    market_stats_json: Mapped[str] = mapped_column(Text, default="{}")
    sentiment_json: Mapped[str] = mapped_column(Text, default="{}")
    money_flow_json: Mapped[str] = mapped_column(Text, default="{}")
    indices_json: Mapped[str] = mapped_column(Text, default="{}")
    limit_summary_json: Mapped[str] = mapped_column(Text, default="{}")
    rotation_summary_json: Mapped[str] = mapped_column(Text, default="{}")
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
    source: Mapped[str] = mapped_column(String(32), default="browser_runtime")
    code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    rank: Mapped[int] = mapped_column(Integer, default=0)
    comp_rank: Mapped[int] = mapped_column(Integer, default=0)
    platforms: Mapped[int] = mapped_column(Integer, default=0)
    avg_rank: Mapped[str | None] = mapped_column(String(32), nullable=True)
    avg_rank_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    cir_mv: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    zlje: Mapped[float | None] = mapped_column(Float, nullable=True)
    zljzb: Mapped[float | None] = mapped_column(Float, nullable=True)
    cddje: Mapped[float | None] = mapped_column(Float, nullable=True)
    cddjzb: Mapped[float | None] = mapped_column(Float, nullable=True)
    pe: Mapped[float | None] = mapped_column(Float, nullable=True)
    pb: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth10_json: Mapped[str] = mapped_column(Text, default="{}")
    bid1_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid1_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask1_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask1_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid10_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask10_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    depth_imbalance: Mapped[float | None] = mapped_column(Float, nullable=True)
    tick_buy_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    tick_sell_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    tick_buy_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tick_sell_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_trade_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_trade_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    lead_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lead_times: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lianban_str: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fengdan: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_fengdan: Mapped[float | None] = mapped_column(Float, nullable=True)
    popularity: Mapped[float | None] = mapped_column(Float, nullable=True)
    popularity_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    institution_buy: Mapped[float | None] = mapped_column(Float, nullable=True)
    big_money300: Mapped[float | None] = mapped_column(Float, nullable=True)
    themes_json: Mapped[str] = mapped_column(Text, default="[]")
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    first_zt_time: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_zt_time: Mapped[str | None] = mapped_column(String(32), nullable=True)
    board_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    high_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hotness: Mapped[float | None] = mapped_column(Float, nullable=True)
    main_theme: Mapped[str | None] = mapped_column(String(160), nullable=True)
    theme_heat: Mapped[float | None] = mapped_column(Float, nullable=True)
    theme_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rank_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    direction_signal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    direction_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    acceleration_signal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    acceleration_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    cross_signal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cross_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_signal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    final_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)


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
    capture_mode: Mapped[str] = mapped_column(String(32), default="real_time")
    source: Mapped[str] = mapped_column(String(32), default="browser_runtime")
    entity_type: Mapped[str] = mapped_column(String(40), default="")
    entity_key: Mapped[str] = mapped_column(String(160), default="")
    entity_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_name: Mapped[str] = mapped_column(String(160), default="")
    rank: Mapped[int] = mapped_column(Integer, default=0)
    strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    heat_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    heat_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    main_net_inflow: Mapped[float | None] = mapped_column(Float, nullable=True)
    big_money300: Mapped[float | None] = mapped_column(Float, nullable=True)
    institution_buy: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    zt_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    leader_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    persistent_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    net_inflow: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")


class GoldenRankTrendCase(ResearchBase):
    __tablename__ = "golden_ranktrend_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    expected_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BacktestRun(ResearchBase):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    strategy_name: Mapped[str] = mapped_column(String(80), default="rank_trend_candidate")
    strategy_version: Mapped[str] = mapped_column(String(40), default="0.1.0")
    snapshot_type: Mapped[str] = mapped_column(String(32), default="half_hour")
    config_hash: Mapped[str] = mapped_column(String(96), default="")
    random_seed: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    date_start: Mapped[str | None] = mapped_column(String(16), nullable=True)
    date_end: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BacktestTrade(ResearchBase):
    __tablename__ = "backtest_trades"
    __table_args__ = (Index("ix_bt_trades_run_id", "backtest_run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[str] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    side: Mapped[str] = mapped_column(String(8), default="buy")
    entry_snapshot_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    exit_snapshot_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    entry_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_trading_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    exit_trading_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    gross_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit: Mapped[float | None] = mapped_column(Float, nullable=True)
    holding_bars: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    candidate_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    fill_detail_json: Mapped[str] = mapped_column(Text, default="{}")


class BacktestEquityCurve(ResearchBase):
    __tablename__ = "backtest_equity_curve"
    __table_args__ = (Index("ix_bt_equity_run_id", "backtest_run_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[str] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    timestamp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trading_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    position_count: Mapped[int] = mapped_column(Integer, default=0)


class BacktestSignal(ResearchBase):
    __tablename__ = "backtest_signals"
    __table_args__ = (Index("ix_bt_signals_run_id_snapshot", "backtest_run_id", "snapshot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[str] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True)
    snapshot_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    trading_date: Mapped[str | None] = mapped_column(String(16), nullable=True)
    code: Mapped[str] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    candidate_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)
    signal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    risk_flags_json: Mapped[str] = mapped_column(Text, default="[]")


class BacktestQualityReport(ResearchBase):
    __tablename__ = "backtest_quality_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[str] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"), index=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    severity: Mapped[str] = mapped_column(String(32), default="pass")
    research_grade: Mapped[str] = mapped_column(String(32), default="research_ready")
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    stock_count: Mapped[int] = mapped_column(Integer, default=0)
    sector_count: Mapped[int] = mapped_column(Integer, default=0)
    missing_fields_json: Mapped[str] = mapped_column(Text, default="{}")
    nan_counts_json: Mapped[str] = mapped_column(Text, default="{}")
    inf_counts_json: Mapped[str] = mapped_column(Text, default="{}")
    negative_price_count: Mapped[int] = mapped_column(Integer, default=0)
    non_positive_price_count: Mapped[int] = mapped_column(Integer, default=0)
    negative_volume_count: Mapped[int] = mapped_column(Integer, default=0)
    coverage_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_order_fixed: Mapped[bool] = mapped_column(Boolean, default=False)
    time_order_fix_count: Mapped[int] = mapped_column(Integer, default=0)
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")


class OptimizationRun(ResearchBase):
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


class ArchiveManifestModel(Base):
    __tablename__ = "archive_manifests"
    __table_args__ = (
        UniqueConstraint("archive_id"),
        Index("ix_archive_manifests_scope_status", "scope", "status"),
        Index("ix_archive_manifests_dataset_type_date", "dataset_id", "snapshot_type", "trading_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    archive_id: Mapped[str] = mapped_column(String(240), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), index=True)
    dataset_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    snapshot_type: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    trading_date: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    local_path: Mapped[str] = mapped_column(Text, default="")
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True, default="local_written")
    row_counts_json: Mapped[str] = mapped_column(Text, default="{}")
    file_hashes_json: Mapped[str] = mapped_column(Text, default="{}")
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    schema_version: Mapped[str] = mapped_column(String(32), default="archive.v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


RESEARCH_JSON_FIELD_MAP = {
    GoldenRankTrendCase: ("input_json", "expected_json"),
    BacktestRun: ("request_json", "result_json"),
    BacktestTrade: ("fill_detail_json",),
    BacktestSignal: ("reasons_json", "risk_flags_json"),
    BacktestQualityReport: ("missing_fields_json", "nan_counts_json", "inf_counts_json", "warnings_json"),
    OptimizationRun: ("request_json", "result_json"),
}


def _compress_research_json_fields(session: ORMSession) -> None:
    for instance in session.new.union(session.dirty):
        fields = RESEARCH_JSON_FIELD_MAP.get(type(instance))
        if not fields:
            continue
        for field in fields:
            setattr(instance, field, dumps_json_field(getattr(instance, field) or "{}"))


@event.listens_for(ORMSession, "before_flush")
def _compress_research_json_fields_before_flush(session: ORMSession, *_args: object) -> None:
    _compress_research_json_fields(session)


class SyncOutboxModel(Base):
    __tablename__ = "sync_outbox"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        Index("ix_sync_outbox_status_next_retry_at", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    op_type: Mapped[str] = mapped_column(String(80), index=True)
    dataset_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, default=None)
    snapshot_id: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True, default=None)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(24), index=True, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
