import os
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


_load_env_file(BASE_DIR.parent / ".env.local")
_load_env_file(BASE_DIR / ".env.local")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class DataSourceConfig(BaseModel):
    profile_indexeddb_path: str = ""
    origin_hint: str = ""
    db_name: str = "DragonBoardData"
    db_version: int = 9
    page_url: str = "http://localhost:5173"


class Settings(BaseModel):
    project_root: Path = BASE_DIR
    data_dir: Path = BASE_DIR / "data"
    staging_dir: Path = BASE_DIR / "data" / "staging"
    warehouse_dir: Path = BASE_DIR / "data" / "warehouse"
    reports_dir: Path = BASE_DIR / "data" / "reports"
    archive_dir: Path = BASE_DIR / "data" / "archive"
    frontend_dir: Path = BASE_DIR / "frontend"
    database_url: str = Field(default="")
    snapshot_database_url: str = Field(default="")
    research_database_url: str = Field(default="")
    theme_database_url: str = Field(default="")
    supabase_url: str = Field(default="")
    supabase_secret_key: str = Field(default="")
    backup_mirror_enabled: bool = Field(default=True)
    backup_read_fallback: bool = Field(default=True)
    backup_timeout_seconds: float = Field(default=10.0)
    backup_auto_sync_enabled: bool = Field(default=False)
    backup_auto_sync_interval_seconds: float = Field(default=60.0)
    backup_auto_sync_initial_delay_seconds: float = Field(default=10.0)
    backup_auto_sync_batch_size: int = Field(default=50)
    archive_retention_trading_days: int = Field(default=90)
    archive_parquet_compression: str = Field(default="zstd")
    archive_auto_enabled: bool = Field(default=False)
    archive_auto_interval_seconds: float = Field(default=3600.0)
    archive_auto_initial_delay_seconds: float = Field(default=30.0)
    archive_auto_max_partitions: int = Field(default=5)
    archive_auto_snapshot_types: str = Field(default="half_hour")
    archive_auto_dataset_id: str = Field(default="dragonboard_live")
    archive_auto_research_enabled: bool = Field(default=False)
    object_backup_enabled: bool = Field(default=False)
    object_backup_bucket: str = Field(default="")
    object_backup_prefix: str = Field(default="quant-board")
    object_backup_endpoint_url: str = Field(default="")
    object_backup_access_key_id: str = Field(default="")
    object_backup_secret_access_key: str = Field(default="")
    object_backup_region: str = Field(default="auto")
    data_source: DataSourceConfig = Field(default_factory=DataSourceConfig)

    def model_post_init(self, __context: Any) -> None:
        old_db_url = os.environ.get("QUANT_BOARD_DATABASE_URL")
        if old_db_url and not os.environ.get("QUANT_BOARD_SNAPSHOT_DATABASE_URL"):
            if "quant_board.db" in old_db_url.replace("\\", "/"):
                warnings.warn(
                    "QUANT_BOARD_DATABASE_URL points to legacy quant_board.db and is ignored. "
                    "Use QUANT_BOARD_SNAPSHOT_DATABASE_URL and QUANT_BOARD_RESEARCH_DATABASE_URL, "
                    "or migrate the legacy DB with `python -m backend.cli migrate-legacy-db`.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                old_db_url = None
            else:
                warnings.warn(
                    "QUANT_BOARD_DATABASE_URL is deprecated, use QUANT_BOARD_SNAPSHOT_DATABASE_URL instead. "
                    "Falling back to the old value for now.",
                    DeprecationWarning,
                    stacklevel=2,
                )
        if not self.snapshot_database_url:
            self.snapshot_database_url = (
                os.environ.get("QUANT_BOARD_SNAPSHOT_DATABASE_URL")
                or old_db_url
                or f"sqlite:///{self.warehouse_dir / 'quant_board_snapshots.db'}"
            )
        if not self.research_database_url:
            self.research_database_url = (
                os.environ.get("QUANT_BOARD_RESEARCH_DATABASE_URL")
                or f"sqlite:///{self.warehouse_dir / 'quant_board_research.db'}"
            )
        if not self.theme_database_url:
            self.theme_database_url = (
                os.environ.get("QUANT_BOARD_THEME_DATABASE_URL")
                or f"sqlite:///{self.warehouse_dir / 'themeDATA.db'}"
            )
        self.database_url = self.snapshot_database_url
        self.supabase_url = os.environ.get("SUPABASE_URL", self.supabase_url).rstrip("/")
        self.supabase_secret_key = os.environ.get("SUPABASE_SECRET_KEY", self.supabase_secret_key)
        self.backup_mirror_enabled = _env_bool(
            "QUANT_BOARD_ENABLE_SUPABASE_BACKUP",
            bool(self.supabase_url and self.supabase_secret_key),
        )
        self.backup_read_fallback = _env_bool(
            "QUANT_BOARD_ENABLE_BACKUP_READ_FALLBACK",
            self.backup_mirror_enabled,
        )
        self.backup_timeout_seconds = _env_float("QUANT_BOARD_BACKUP_TIMEOUT_SECONDS", self.backup_timeout_seconds)
        self.backup_auto_sync_enabled = _env_bool("QUANT_BOARD_AUTO_SYNC_ENABLED", self.backup_auto_sync_enabled)
        self.backup_auto_sync_interval_seconds = max(
            5.0,
            _env_float("QUANT_BOARD_AUTO_SYNC_INTERVAL_SECONDS", self.backup_auto_sync_interval_seconds),
        )
        self.backup_auto_sync_initial_delay_seconds = max(
            0.0,
            _env_float("QUANT_BOARD_AUTO_SYNC_INITIAL_DELAY_SECONDS", self.backup_auto_sync_initial_delay_seconds),
        )
        self.backup_auto_sync_batch_size = max(
            1,
            _env_int("QUANT_BOARD_AUTO_SYNC_BATCH_SIZE", self.backup_auto_sync_batch_size),
        )
        archive_dir = os.environ.get("QUANT_BOARD_ARCHIVE_DIR")
        if archive_dir:
            self.archive_dir = Path(archive_dir)
        self.archive_retention_trading_days = max(
            1,
            _env_int("QUANT_BOARD_ARCHIVE_RETENTION_TRADING_DAYS", self.archive_retention_trading_days),
        )
        self.archive_parquet_compression = os.environ.get(
            "QUANT_BOARD_ARCHIVE_PARQUET_COMPRESSION",
            self.archive_parquet_compression,
        )
        self.archive_auto_enabled = _env_bool("QUANT_BOARD_ARCHIVE_AUTO_ENABLED", self.archive_auto_enabled)
        self.archive_auto_interval_seconds = max(
            60.0,
            _env_float("QUANT_BOARD_ARCHIVE_AUTO_INTERVAL_SECONDS", self.archive_auto_interval_seconds),
        )
        self.archive_auto_initial_delay_seconds = max(
            0.0,
            _env_float("QUANT_BOARD_ARCHIVE_AUTO_INITIAL_DELAY_SECONDS", self.archive_auto_initial_delay_seconds),
        )
        self.archive_auto_max_partitions = max(
            1,
            _env_int("QUANT_BOARD_ARCHIVE_AUTO_MAX_PARTITIONS", self.archive_auto_max_partitions),
        )
        self.archive_auto_snapshot_types = os.environ.get(
            "QUANT_BOARD_ARCHIVE_AUTO_SNAPSHOT_TYPES",
            self.archive_auto_snapshot_types,
        )
        self.archive_auto_dataset_id = os.environ.get(
            "QUANT_BOARD_ARCHIVE_AUTO_DATASET_ID",
            self.archive_auto_dataset_id,
        )
        self.archive_auto_research_enabled = _env_bool(
            "QUANT_BOARD_ARCHIVE_AUTO_RESEARCH_ENABLED",
            self.archive_auto_research_enabled,
        )
        self.object_backup_enabled = _env_bool("QUANT_BOARD_OBJECT_BACKUP_ENABLED", self.object_backup_enabled)
        self.object_backup_bucket = os.environ.get("QUANT_BOARD_OBJECT_BACKUP_BUCKET", self.object_backup_bucket)
        self.object_backup_prefix = os.environ.get("QUANT_BOARD_OBJECT_BACKUP_PREFIX", self.object_backup_prefix)
        self.object_backup_endpoint_url = os.environ.get(
            "QUANT_BOARD_OBJECT_BACKUP_ENDPOINT_URL",
            self.object_backup_endpoint_url,
        )
        self.object_backup_access_key_id = os.environ.get(
            "QUANT_BOARD_OBJECT_BACKUP_ACCESS_KEY_ID",
            self.object_backup_access_key_id,
        )
        self.object_backup_secret_access_key = os.environ.get(
            "QUANT_BOARD_OBJECT_BACKUP_SECRET_ACCESS_KEY",
            self.object_backup_secret_access_key,
        )
        self.object_backup_region = os.environ.get("QUANT_BOARD_OBJECT_BACKUP_REGION", self.object_backup_region)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.warehouse_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)


def _load_yaml_config() -> dict[str, Any]:
    config_path = BASE_DIR / "config" / "data_sources.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return loaded if isinstance(loaded, dict) else {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    loaded = _load_yaml_config()
    data_source = loaded.get("data_source") or loaded
    settings = Settings(data_source=DataSourceConfig(**data_source))
    settings.ensure_dirs()
    return settings
