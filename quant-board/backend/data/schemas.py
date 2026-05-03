from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


SnapshotType = Literal["quarter_hour", "half_hour", "hourly", "daily"]


class ImportDatasetRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_type: Literal["sqlite_snapshots", "leveldb", "browser_bridge", "json_bundle"] = Field(
        default="sqlite_snapshots",
        alias="sourceType",
    )
    source_path: str | None = Field(default=None, alias="sourcePath")
    source_dataset_id: str | None = Field(default=None, alias="sourceDatasetId")
    name: str | None = None
    start_date: str | None = Field(default=None, alias="startDate")
    end_date: str | None = Field(default=None, alias="endDate")
    snapshot_types: list[SnapshotType] = Field(default_factory=lambda: ["half_hour"], alias="snapshotTypes")
    max_snapshots: int | None = Field(default=None, alias="maxSnapshots")
    dry_run: bool = Field(default=False, alias="dryRun")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def normalize_date(cls, value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        return normalized.replace("/", "-")


class SnapshotIngestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dataset_id: str | None = Field(default=None, alias="datasetId")
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")
    trading_date: str | None = Field(default=None, alias="tradingDate")
    bundle: dict[str, Any]
    source: str = Field(default="dragon_board_runtime", alias="source")


class SnapshotJsonMigrationRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    dataset_id: str | None = Field(default=None, alias="datasetId")
    idempotency_key: str | None = Field(default=None, alias="idempotencyKey")
    source_path: str | None = Field(default=None, alias="sourcePath")
    content: Any | None = None
    bundle: dict[str, Any] | None = None
    payload: Any | None = None
    name: str | None = None
    source: str = "dragon_board_history_migration"
    dry_run: bool = Field(default=False, alias="dryRun")


class DatasetSummary(BaseModel):
    id: str
    name: str
    source_type: str
    snapshot_count: int
    frame_count: int
    stock_row_count: int
    sector_row_count: int
    start_date: str | None
    end_date: str | None
    snapshot_types: list[str]
    created_at: str


class BacktestRequest(BaseModel):
    dataset_id: str
    snapshot_type: SnapshotType = "half_hour"
    start_date: str | None = None
    end_date: str | None = None
    random_seed: int = 20260430
    enable_trade_simulation: bool = True
    horizons: list[int] = Field(default_factory=lambda: [1, 3, 5, 10])
    trade_config: dict[str, Any] = Field(default_factory=dict)
    strategy_config: dict[str, Any] = Field(default_factory=dict)


class OptimizationRequest(BaseModel):
    dataset_id: str
    snapshot_type: SnapshotType = "half_hour"
    method: Literal["grid", "random", "bayesian", "tpe", "optuna_tpe"] = "grid"
    random_seed: int = 20260430
    max_trials: int = 12
    search_space: dict[str, list[Any]] = Field(default_factory=dict)
    backtest: dict[str, Any] = Field(default_factory=dict)


class GoldenImportRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str | None = None
    case_id: str | None = Field(default=None, alias="caseId")
    path: str | None = None
    payload: dict[str, Any] | None = None
    dataset_id: str | None = Field(default=None, alias="datasetId")
    snapshot_type: SnapshotType | None = Field(default=None, alias="snapshotType")
    source: str | None = None


class GoldenValidateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    case_id: str | None = Field(default=None, alias="caseId")
    dataset_id: str | None = Field(default=None, alias="datasetId")
    path: str | None = None
    tolerance: float = 1e-6
    strict: bool = True
    sample_limit: int | None = Field(default=None, alias="sampleLimit")
