import os
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
    supabase_url: str = Field(default="")
    supabase_secret_key: str = Field(default="")
    backup_mirror_enabled: bool = Field(default=True)
    backup_read_fallback: bool = Field(default=True)
    backup_timeout_seconds: float = Field(default=10.0)
    data_source: DataSourceConfig = Field(default_factory=DataSourceConfig)

    def model_post_init(self, __context: Any) -> None:
        if not self.database_url:
            self.database_url = os.environ.get("QUANT_BOARD_DATABASE_URL") or f"sqlite:///{self.warehouse_dir / 'quant_board.db'}"
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
        try:
            self.backup_timeout_seconds = float(os.environ.get("QUANT_BOARD_BACKUP_TIMEOUT_SECONDS", self.backup_timeout_seconds))
        except (TypeError, ValueError):
            self.backup_timeout_seconds = 10.0

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
