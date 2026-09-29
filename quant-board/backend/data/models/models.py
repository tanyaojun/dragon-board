"""领域模型 —— 纯 dataclass（2026-09-29 深度解绑）。

历史上这是 SQLAlchemy ORM 声明（sqlite 主链时代）；sqlite 链退役后转换为
dataclass，仅作为 mongo 仓库与服务层的内存领域对象 + 字段 schema 文档：

- 构造合同与原 ORM 完全等价：所有字段均可省略（省略 = None，或取声明默认值），
  ``created_at`` 等时间戳字段省略时取 ``datetime.utcnow``；
- 全部 ``kw_only=True``：构造必须用关键字参数；
- ``*_json`` 文本字段的压缩/解压由 ``backend/data/ingest/json_codec`` 在仓库层处理；
- mongo 集合的索引/唯一键定义见 ``mongodb_migration.py`` 与生产库实际索引，
  不再由 ORM ``__table_args__`` 声明。

禁止重新引入 SQLAlchemy/ORM 声明。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(kw_only=True)
class Dataset:
    id: str | None = None
    name: str | None = None
    source_type: str | None = None
    source_path: str = ""
    db_name: str = "DragonBoardData"
    schema_fingerprint: str = ""
    snapshot_count: int = 0
    frame_count: int = 0
    stock_row_count: int = 0
    sector_row_count: int = 0
    start_date: str | None = None
    end_date: str | None = None
    snapshot_types_json: str = "[]"
    metadata_json: str = "{}"
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(kw_only=True)
class SnapshotStockRowModel:
    id: int | None = None
    dataset_id: str | None = None
    row_id: str | None = None
    snapshot_id: str | None = None
    type: str | None = None
    trading_date: str | None = None
    slot_time: str = ""
    timestamp: int | None = None
    capture_mode: str = "real_time"
    source: str = "browser_runtime"
    code: str | None = None
    name: str = ""
    rank: int = 0
    comp_rank: int = 0
    platforms: int = 0
    avg_rank: str | None = None
    avg_rank_num: float | None = None
    price: float | None = None
    change: float | None = None
    volume: float | None = None
    turnover: float | None = None
    turnover_rate: float | None = None
    total_mv: float | None = None
    cir_mv: float | None = None
    volume_ratio: float | None = None
    zlje: float | None = None
    zljzb: float | None = None
    cddje: float | None = None
    cddjzb: float | None = None
    pe: float | None = None
    pb: float | None = None
    depth10_json: str = "{}"
    bid1_price: float | None = None
    bid1_volume: float | None = None
    ask1_price: float | None = None
    ask1_volume: float | None = None
    spread: float | None = None
    bid10_total: float | None = None
    ask10_total: float | None = None
    depth_imbalance: float | None = None
    tick_buy_volume: float | None = None
    tick_sell_volume: float | None = None
    tick_buy_count: int | None = None
    tick_sell_count: int | None = None
    last_trade_price: float | None = None
    last_trade_volume: float | None = None
    speed: float | None = None
    lead_status: str | None = None
    lead_times: int | None = None
    lianban_str: str | None = None
    fengdan: float | None = None
    max_fengdan: float | None = None
    popularity: float | None = None
    popularity_change: float | None = None
    institution_buy: float | None = None
    big_money300: float | None = None
    themes_json: str = "[]"
    theme_contribution: float | None = None
    theme_role: str | None = None
    theme_exposure_weight: float | None = None
    theme_risk_flags_json: str = "[]"
    is_new: bool = False
    reason: str | None = None
    first_zt_time: str | None = None
    last_zt_time: str | None = None
    board_height: int | None = None
    high_days: int | None = None
    hotness: float | None = None
    main_theme: str | None = None
    theme_heat: float | None = None
    theme_level: str | None = None
    rank_change: float | None = None
    direction_signal: str | None = None
    direction_confidence: float | None = None
    acceleration_signal: str | None = None
    acceleration_confidence: float | None = None
    cross_signal: str | None = None
    cross_confidence: float | None = None
    final_signal: str | None = None
    final_confidence: float | None = None
    jump_direction: str | None = None
    jump_confidence: float | None = None
    macd_cross: str | None = None
    resonance_intensity: float | None = None


@dataclass(kw_only=True)
class SnapshotSectorRowModel:
    id: int | None = None
    dataset_id: str | None = None
    row_id: str | None = None
    snapshot_id: str | None = None
    type: str | None = None
    trading_date: str | None = None
    slot_time: str = ""
    timestamp: int | None = None
    capture_mode: str = "real_time"
    source: str = "browser_runtime"
    entity_type: str = ""
    entity_key: str = ""
    entity_code: str | None = None
    entity_name: str = ""
    rank: int = 0
    strength: float | None = None
    heat_score: float | None = None
    heat_level: str | None = None
    change: float | None = None
    main_net_inflow: float | None = None
    big_money300: float | None = None
    institution_buy: float | None = None
    volume_ratio: float | None = None
    zt_count: int | None = None
    leader_count: int | None = None
    persistent_days: int | None = None
    net_inflow: float | None = None
    momentum_score: float | None = None
    breadth_score: float | None = None
    fund_score: float | None = None
    leadership_score: float | None = None
    correlation_score: float | None = None
    crowding_risk: float | None = None
    persistence_score: float | None = None
    rotation_state: str | None = None
    theme_quality_flags_json: str = "[]"
    metadata_json: str = "{}"


@dataclass(kw_only=True)
class GoldenRankTrendCase:
    id: str | None = None
    name: str | None = None
    dataset_id: str | None = None
    input_json: str = "{}"
    expected_json: str = "{}"
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(kw_only=True)
class BacktestRun:
    id: str | None = None
    dataset_id: str | None = None
    strategy_name: str = "rank_trend_candidate"
    strategy_version: str = "0.1.0"
    snapshot_type: str = "half_hour"
    config_hash: str = ""
    random_seed: int = 0
    status: str = "completed"
    date_start: str | None = None
    date_end: str | None = None
    error_reason: str | None = None
    request_json: str = "{}"
    result_json: str = "{}"
    created_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None


@dataclass(kw_only=True)
class BacktestTrade:
    id: int | None = None
    backtest_run_id: str | None = None
    code: str | None = None
    name: str = ""
    side: str = "buy"
    entry_snapshot_id: str | None = None
    exit_snapshot_id: str | None = None
    entry_time: int | None = None
    exit_time: int | None = None
    entry_trading_date: str | None = None
    exit_trading_date: str | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    quantity: int = 0
    gross_return: float | None = None
    net_return: float | None = None
    profit: float | None = None
    holding_bars: int = 0
    reason: str | None = None
    candidate_tier: str | None = None
    stage: str | None = None
    regime: str | None = None
    explanation: str | None = None
    fill_detail_json: str = "{}"


@dataclass(kw_only=True)
class BacktestEquityCurve:
    id: int | None = None
    backtest_run_id: str | None = None
    snapshot_id: str | None = None
    timestamp: int | None = None
    trading_date: str | None = None
    equity: float | None = None
    cash: float | None = None
    market_value: float | None = None
    position_count: int = 0


@dataclass(kw_only=True)
class BacktestSignal:
    id: int | None = None
    backtest_run_id: str | None = None
    snapshot_id: str | None = None
    trading_date: str | None = None
    code: str | None = None
    name: str = ""
    candidate_tier: str | None = None
    signal: str | None = None
    confidence: float | None = None
    rank: int | None = None
    stage: str | None = None
    regime: str | None = None
    reasons_json: str = "[]"
    risk_flags_json: str = "[]"
    main_theme: str | None = None
    theme_heat: float | None = None
    theme_contribution: float | None = None
    theme_role: str | None = None
    theme_support_score: float | None = None
    theme_risk_flags_json: str = "[]"
    theme_reasons_json: str = "[]"


@dataclass(kw_only=True)
class BacktestQualityReport:
    id: int | None = None
    backtest_run_id: str | None = None
    passed: bool = False
    severity: str = "pass"
    research_grade: str = "research_ready"
    frame_count: int = 0
    stock_count: int = 0
    sector_count: int = 0
    missing_fields_json: str = "{}"
    nan_counts_json: str = "{}"
    inf_counts_json: str = "{}"
    negative_price_count: int = 0
    non_positive_price_count: int = 0
    negative_volume_count: int = 0
    coverage_ratio: float | None = None
    time_order_fixed: bool = False
    time_order_fix_count: int = 0
    warnings_json: str = "[]"


@dataclass(kw_only=True)
class OptimizationRun:
    id: str | None = None
    dataset_id: str | None = None
    strategy_name: str = "rank_trend_candidate"
    method: str = "grid"
    config_hash: str = ""
    random_seed: int = 0
    status: str = "completed"
    request_json: str = "{}"
    result_json: str = "{}"
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(kw_only=True)
class ThemeFactorFrameModel:
    id: int | None = None
    dataset_id: str | None = None
    snapshot_id: str | None = None
    snapshot_type: str = "half_hour"
    trading_date: str | None = None
    slot_time: str = ""
    strategy_version: str = "theme-trend-v12"
    config_hash: str = ""
    random_seed: int = 0
    theme_id: str | None = None
    theme_name: str = ""
    heat_score: float = 0.0
    momentum_score: float = 0.0
    breadth_score: float = 0.0
    fund_score: float = 0.0
    leadership_score: float = 0.0
    correlation_score: float = 0.0
    crowding_risk: float = 0.0
    persistence_score: float = 0.0
    rotation_state: str = "neutral"
    rank: int = 0
    quality_flags_json: str = "[]"
    lifecycle: str = "neutral"


@dataclass(kw_only=True)
class ThemeStockExposureModel:
    id: int | None = None
    dataset_id: str | None = None
    snapshot_id: str | None = None
    snapshot_type: str = "half_hour"
    trading_date: str | None = None
    slot_time: str = ""
    strategy_version: str = "theme-trend-v12"
    config_hash: str = ""
    random_seed: int = 0
    code: str | None = None
    theme_id: str | None = None
    theme_name: str = ""
    role: str = "unknown"
    role_score: float = 0.0
    exposure_weight: float = 0.0
    theme_contribution: float = 0.0
    risk_penalty: float = 0.0
    reasons_json: str = "[]"


@dataclass(kw_only=True)
class ThemeSignalModel:
    id: int | None = None
    dataset_id: str | None = None
    snapshot_id: str | None = None
    snapshot_type: str = "half_hour"
    trading_date: str | None = None
    slot_time: str = ""
    strategy_version: str = "theme-trend-v12"
    config_hash: str = ""
    random_seed: int = 0
    theme_id: str | None = None
    theme_name: str = ""
    signal: str = "watch"
    risk: str = "none"
    lifecycle: str = "neutral"
    score: float = 0.0


@dataclass(kw_only=True)
class ThemeQualityReportModel:
    id: int | None = None
    dataset_id: str | None = None
    snapshot_type: str = "half_hour"
    strategy_version: str = "theme-trend-v12"
    config_hash: str = ""
    random_seed: int = 0
    passed: bool = False
    severity: str = "pass"
    research_grade: str = "research_ready"
    issues_json: str = "[]"
    warnings_json: str = "[]"
    stats_json: str = "{}"
    theme_coverage: float = 0.0
    frame_count: int = 0
    stock_count: int = 0
    theme_count: int = 0


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
    candidate_entry_id: str | None = None
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
    # ---- Layer 3 execution fields (V2 long-test plan) ----
    entry_price: float | None = None
    entry_time: str | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    position_pct: float | None = None
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
            "candidateEntryId": self.candidate_entry_id,
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
            "entryPrice": self.entry_price,
            "entryTime": self.entry_time,
            "exitPrice": self.exit_price,
            "exitTime": self.exit_time,
            "stopLossPrice": self.stop_loss_price,
            "takeProfitPrice": self.take_profit_price,
            "positionPct": self.position_pct,
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
            candidate_entry_id=data.get("candidateEntryId"),
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
