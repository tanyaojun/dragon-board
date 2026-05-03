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
    frontend_dir: Path = BASE_DIR / "frontend"
    database_url: str = Field(default="")
    snapshot_database_url: str = Field(default="")
    research_database_url: str = Field(default="")
    supabase_url: str = Field(default="")
    supabase_secret_key: str = Field(default="")
    backup_mirror_enabled: bool = Field(default=True)
    backup_read_fallback: bool = Field(default=True)
    backup_timeout_seconds: float = Field(default=10.0)
    backup_auto_sync_enabled: bool = Field(default=False)
    backup_auto_sync_interval_seconds: float = Field(default=60.0)
    backup_auto_sync_initial_delay_seconds: float = Field(default=10.0)
    backup_auto_sync_batch_size: int = Field(default=50)
    data_source: DataSourceConfig = Field(default_factory=DataSourceConfig)

    def model_post_init(self, __context: Any) -> None:
        old_db_url = os.environ.get("QUANT_BOARD_DATABASE_URL")
        if old_db_url and not os.environ.get("QUANT_BOARD_SNAPSHOT_DATABASE_URL"):
            warnings.warn(
                "QUANT_BOARD_DATABASE_URL is deprecated, use QUANT_BOARD_SNAPSHOT_DATABASE_URL instead. "
                "Falling back to the old value for now, but this will be removed in a future version.",
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

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.warehouse_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)


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
