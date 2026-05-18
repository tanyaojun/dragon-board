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
    theme_contribution: Mapped[float | None] = mapped_column(Float, nullable=True)
    theme_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    theme_exposure_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    theme_risk_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    momentum_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    breadth_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fund_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    leadership_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    correlation_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    crowding_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    persistence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rotation_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    theme_quality_flags_json: Mapped[str] = mapped_column(Text, default="[]")
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
    main_theme: Mapped[str | None] = mapped_column(String(160), nullable=True)
    theme_heat: Mapped[float | None] = mapped_column(Float, nullable=True)
    theme_contribution: Mapped[float | None] = mapped_column(Float, nullable=True)
    theme_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    theme_support_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    theme_risk_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    theme_reasons_json: Mapped[str] = mapped_column(Text, default="[]")


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


class ThemeFactorFrameModel(ResearchBase):
    __tablename__ = "theme_factor_frames"
    __table_args__ = (Index("ix_tf_dataset_snapshot", "dataset_id", "snapshot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(160), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(32), default="half_hour")
    trading_date: Mapped[str] = mapped_column(String(16), index=True)
    slot_time: Mapped[str] = mapped_column(String(16), default="")
    strategy_version: Mapped[str] = mapped_column(String(40), default="theme-trend-v12")
    config_hash: Mapped[str] = mapped_column(String(96), default="")
    random_seed: Mapped[int] = mapped_column(Integer, default=0)
    theme_id: Mapped[str] = mapped_column(String(160))
    theme_name: Mapped[str] = mapped_column(String(160), default="")
    heat_score: Mapped[float] = mapped_column(Float, default=0.0)
    momentum_score: Mapped[float] = mapped_column(Float, default=0.0)
    breadth_score: Mapped[float] = mapped_column(Float, default=0.0)
    fund_score: Mapped[float] = mapped_column(Float, default=0.0)
    leadership_score: Mapped[float] = mapped_column(Float, default=0.0)
    correlation_score: Mapped[float] = mapped_column(Float, default=0.0)
    crowding_risk: Mapped[float] = mapped_column(Float, default=0.0)
    persistence_score: Mapped[float] = mapped_column(Float, default=0.0)
    rotation_state: Mapped[str] = mapped_column(String(32), default="neutral")
    rank: Mapped[int] = mapped_column(Integer, default=0)
    quality_flags_json: Mapped[str] = mapped_column(Text, default="[]")
    lifecycle: Mapped[str] = mapped_column(String(32), default="neutral")


class ThemeStockExposureModel(ResearchBase):
    __tablename__ = "theme_stock_exposures"
    __table_args__ = (Index("ix_tse_dataset_snapshot", "dataset_id", "snapshot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(160), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(32), default="half_hour")
    trading_date: Mapped[str] = mapped_column(String(16), index=True)
    slot_time: Mapped[str] = mapped_column(String(16), default="")
    strategy_version: Mapped[str] = mapped_column(String(40), default="theme-trend-v12")
    config_hash: Mapped[str] = mapped_column(String(96), default="")
    random_seed: Mapped[int] = mapped_column(Integer, default=0)
    code: Mapped[str] = mapped_column(String(16), index=True)
    theme_id: Mapped[str] = mapped_column(String(160))
    theme_name: Mapped[str] = mapped_column(String(160), default="")
    role: Mapped[str] = mapped_column(String(32), default="unknown")
    role_score: Mapped[float] = mapped_column(Float, default=0.0)
    exposure_weight: Mapped[float] = mapped_column(Float, default=0.0)
    theme_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    risk_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    reasons_json: Mapped[str] = mapped_column(Text, default="[]")


class ThemeSignalModel(ResearchBase):
    __tablename__ = "theme_signals"
    __table_args__ = (Index("ix_ts_dataset_snapshot", "dataset_id", "snapshot_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_id: Mapped[str] = mapped_column(String(160), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(32), default="half_hour")
    trading_date: Mapped[str] = mapped_column(String(16), index=True)
    slot_time: Mapped[str] = mapped_column(String(16), default="")
    strategy_version: Mapped[str] = mapped_column(String(40), default="theme-trend-v12")
    config_hash: Mapped[str] = mapped_column(String(96), default="")
    random_seed: Mapped[int] = mapped_column(Integer, default=0)
    theme_id: Mapped[str] = mapped_column(String(160))
    theme_name: Mapped[str] = mapped_column(String(160), default="")
    signal: Mapped[str] = mapped_column(String(32), default="watch")
    risk: Mapped[str] = mapped_column(String(32), default="none")
    lifecycle: Mapped[str] = mapped_column(String(32), default="neutral")
    score: Mapped[float] = mapped_column(Float, default=0.0)


class ThemeQualityReportModel(ResearchBase):
    __tablename__ = "theme_quality_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    snapshot_type: Mapped[str] = mapped_column(String(32), default="half_hour")
    strategy_version: Mapped[str] = mapped_column(String(40), default="theme-trend-v12")
    config_hash: Mapped[str] = mapped_column(String(96), default="")
    random_seed: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    severity: Mapped[str] = mapped_column(String(32), default="pass")
    research_grade: Mapped[str] = mapped_column(String(32), default="research_ready")
    issues_json: Mapped[str] = mapped_column(Text, default="[]")
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    theme_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    stock_count: Mapped[int] = mapped_column(Integer, default=0)
    theme_count: Mapped[int] = mapped_column(Integer, default=0)


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
    BacktestSignal: ("reasons_json", "risk_flags_json", "theme_risk_flags_json", "theme_reasons_json"),
    BacktestQualityReport: ("missing_fields_json", "nan_counts_json", "inf_counts_json", "warnings_json"),
    OptimizationRun: ("request_json", "result_json"),
    ThemeFactorFrameModel: ("quality_flags_json",),
    ThemeStockExposureModel: ("reasons_json",),
    ThemeSignalModel: (),  # 信号表无 JSON 列，所有字段均为标量
    ThemeQualityReportModel: ("issues_json", "warnings_json", "stats_json"),
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


from dataclasses import dataclass, field
from typing import Any


@dataclass
class TradeJournal:
    id: str
    stock_code: str
    stock_name: str
    direction: str = "buy"  # "buy" | "sell"
    trade_type: str = "thesis"  # "thesis" | "entry" | "exit"
    price: float = 0
    volume: int = 0
    trade_time: str = ""  # ISO 8601
    linked_entry_id: str | None = None
    signals_snapshot: dict[str, Any] | None = field(default_factory=dict)
    notes: str = ""
    screenshot_paths: list[str] = field(default_factory=list)
    review_tags: list[str] = field(default_factory=list)
    pnl: float | None = None
    pnl_pct: float | None = None
    status: str = "observe"
    market_phase: str = ""
    theme_role: str = ""
    stock_role: str = ""
    entry_reason: str = ""
    trade_hypothesis: str = ""
    entry_prerequisites: str = ""
    invalidation_rules: str = ""
    expected_holding_days: int = 3
    human_decision: str = "watch"
    skip_reason: str = ""
    review_outcome: str = "pending"
    model_result: str = "unknown"
    execution_result: str = "unknown"
    review_notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "stockCode": self.stock_code,
            "stockName": self.stock_name,
            "direction": self.direction,
            "tradeType": self.trade_type,
            "price": self.price,
            "volume": self.volume,
            "tradeTime": self.trade_time,
            "linkedEntryId": self.linked_entry_id,
            "signalsSnapshot": self.signals_snapshot,
            "notes": self.notes,
            "screenshotPaths": self.screenshot_paths,
            "reviewTags": self.review_tags,
            "pnl": self.pnl,
            "pnlPct": self.pnl_pct,
            "status": self.status,
            "marketPhase": self.market_phase,
            "themeRole": self.theme_role,
            "stockRole": self.stock_role,
            "entryReason": self.entry_reason,
            "tradeHypothesis": self.trade_hypothesis,
            "entryPrerequisites": self.entry_prerequisites,
            "invalidationRules": self.invalidation_rules,
            "expectedHoldingDays": self.expected_holding_days,
            "humanDecision": self.human_decision,
            "skipReason": self.skip_reason,
            "reviewOutcome": self.review_outcome,
            "modelResult": self.model_result,
            "executionResult": self.execution_result,
            "reviewNotes": self.review_notes,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TradeJournal":
        return cls(
            id=str(data.get("id") or ""),
            stock_code=str(data.get("stockCode") or ""),
            stock_name=str(data.get("stockName") or ""),
            direction=str(data.get("direction") or "buy"),
            trade_type=str(data.get("tradeType") or "thesis"),
            price=float(data.get("price") or 0),
            volume=int(data.get("volume") or 0),
            trade_time=str(data.get("tradeTime") or ""),
            linked_entry_id=data.get("linkedEntryId"),
            signals_snapshot=data.get("signalsSnapshot") or {},
            notes=str(data.get("notes") or ""),
            screenshot_paths=list(data.get("screenshotPaths") or []),
            review_tags=list(data.get("reviewTags") or []),
            pnl=float(data["pnl"]) if data.get("pnl") is not None else None,
            pnl_pct=float(data["pnlPct"]) if data.get("pnlPct") is not None else None,
            status=str(data.get("status") or "observe"),
            market_phase=str(data.get("marketPhase") or ""),
            theme_role=str(data.get("themeRole") or ""),
            stock_role=str(data.get("stockRole") or ""),
            entry_reason=str(data.get("entryReason") or ""),
            trade_hypothesis=str(data.get("tradeHypothesis") or ""),
            entry_prerequisites=str(data.get("entryPrerequisites") or ""),
            invalidation_rules=str(data.get("invalidationRules") or ""),
            expected_holding_days=int(data.get("expectedHoldingDays") or 3),
            human_decision=str(data.get("humanDecision") or "watch"),
            skip_reason=str(data.get("skipReason") or ""),
            review_outcome=str(data.get("reviewOutcome") or "pending"),
            model_result=str(data.get("modelResult") or "unknown"),
            execution_result=str(data.get("executionResult") or "unknown"),
            review_notes=str(data.get("reviewNotes") or ""),
            created_at=str(data.get("createdAt") or ""),
            updated_at=str(data.get("updatedAt") or ""),
        )
