import logging
import os
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


# backend/core/settings.py：位于 backend/core/ 下，parents[2] 指向 quant-board 根
BASE_DIR = Path(__file__).resolve().parents[2]


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
    # Supabase 备份链已于 2026-09-29 随 supabase_homomorphic.py 删除，相关字段/解析一并移除
    archive_retention_trading_days: int = Field(default=90)
    archive_parquet_compression: str = Field(default="zstd")
    archive_auto_enabled: bool = Field(default=False)
    archive_auto_interval_seconds: float = Field(default=3600.0)
    archive_auto_initial_delay_seconds: float = Field(default=30.0)
    archive_auto_max_partitions: int = Field(default=5)
    # 2026-09-28：R2 快照日归档类型扩到全类型（half_hour 必须首位：盘后链
    # _first_snapshot_type 用首类型取最新帧算当日情绪）
    archive_auto_snapshot_types: str = Field(default="half_hour,quarter_hour,five_minutes,daily")
    archive_auto_dataset_id: str = Field(default="dragonboard_live")
    archive_auto_research_enabled: bool = Field(default=False)
    object_backup_enabled: bool = Field(default=False)
    object_backup_bucket: str = Field(default="")
    object_backup_prefix: str = Field(default="quant-board")
    object_backup_endpoint_url: str = Field(default="")
    object_backup_access_key_id: str = Field(default="")
    object_backup_secret_access_key: str = Field(default="")
    object_backup_region: str = Field(default="auto")
    mongodb_uri: str = Field(default="")
    mongodb_database: str = Field(default="dragon_board_quant")
    mongodb_connect_timeout_ms: int = Field(default=10000)
    mongodb_server_selection_timeout_ms: int = Field(default=15000)
    # 单次 Mongo 读写的 socket 超时：不能设太小——RankTrend analyze 等重读
    # 一次要跨集合拉 200 帧 + 数十万行，3s 会被 NetworkTimeout 掐断导致 500。
    # 60s 既能兜住死连接挂起，也容得下本地大查询。
    mongodb_socket_timeout_ms: int = Field(default=60000)
    mongodb_max_pool_size: int = Field(default=20)
    mongodb_backup_dir: Path = BASE_DIR / "data" / "backups" / "mongodb"
    mongodb_backup_retention_days: int = Field(default=30)
    # 远端对象存储（R2）保留的全量备份份数，push 成功后清理更早备份
    mongodb_remote_backup_keep: int = Field(default=4)
    # MongoDB Database Tools（mongodump/mongorestore）所在 bin 目录，备份引擎用绝对路径调用
    mongodb_tools_bin: Path = Path(r"D:\APP_SOFT\MongoDB\tools\bin")
    # 2026-09-29 隔离裁决：sqlite 链退役，mongodb 是唯一默认后端；裸环境不再静默落 sqlite。
    storage_backend: str = Field(default="mongodb")
    # sqlite 仅剩一次性本地诊断用途，必须显式 opt-in（QUANT_BOARD_ALLOW_SQLITE_BACKEND=1）
    allow_sqlite_backend: bool = Field(default=False)
    redis_url: str = Field(default="redis://127.0.0.1:6379/0")
    redis_key_prefix: str = Field(default="hellobiga:dragon-board:local")
    snapshot_cache_enabled: bool = Field(default=True)
    snapshot_cache_ttl_seconds: int = Field(default=7200)
    snapshot_empty_cache_ttl_seconds: int = Field(default=10)
    theme_rotation_cache_ttl_seconds: int = Field(default=60)
    # hotlist EOD 情绪序列读口缓存 TTL（2026-09-10 新增）：盘中短 TTL；写口重算与
    # 快照写入（数据层 after-save 钩子）都会即时失效该缓存，TTL 只是兜底。
    hotlist_sentiment_cache_ttl_seconds: int = Field(default=60)
    # ThemeTrend 研究摘要读口缓存 TTL（2026-09-12 新增）：该读口每次重算需全量
    # load_frame_bundles(200) + 引擎重放（实测 8~18s），TTL 取长（10 分钟）兜底；
    # 快照写入（数据层 after-save 钩子经依赖 index）会即时失效该缓存。
    theme_research_summary_cache_ttl_seconds: int = Field(default=600)
    # 题材日频因子（theme_daily_factors，2026-09-27 Task1 接线）最近一日横截面
    # 读口缓存 TTL：盘后每日计算一次，读口消费在 Phase 4 接线，TTL 仅兜底。
    theme_daily_factors_cache_ttl_seconds: int = Field(default=3600)
    snapshot_cache_connect_timeout_seconds: float = Field(default=0.2)
    snapshot_cache_socket_timeout_seconds: float = Field(default=0.2)
    snapshot_collector_enabled: bool = Field(default=False)
    snapshot_collector_dataset_id: str = Field(default="dragonboard_backend_shadow")
    # 2026-09-28：quarter_hour / five_minutes 重新入采（默认含全部五类；
    # 生产实际类型由 quant-board/.env.local 的同名环境变量覆盖）
    snapshot_collector_types: str = Field(default="five_minutes,quarter_hour,half_hour,daily")
    snapshot_collector_poll_ms: int = Field(default=30000)
    snapshot_collector_close_grace_minutes: int = Field(default=5)
    snapshot_collector_proxy_base_url: str = Field(default="http://127.0.0.1:3000")
    snapshot_collector_bridge_base_url: str = Field(default="http://127.0.0.1:8765")
    snapshot_collector_provider_timeout_ms: int = Field(default=30000)
    # 采集池来源模式（2026-09-20 spec：docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md）
    # autonomous = 八平台热榜实时合并池为主池（bundle 只供 snapshotContext）；
    # bundle_first = 旧行为（bundle 为主池，merged 仅 fallback）。改后重启采集进程生效。
    snapshot_collector_pool_source_mode: str = Field(default="autonomous")
    snapshot_collector_allow_live_dataset: bool = Field(default=False)
    # 韭研 final 入库后自动同步板块名到通达信 mark.dat：由采集进程内 after-collect 钩子
    # 触发（无独立定时脚本）；默认开，mark 文件缺失则跳过（fail-visible，不影响采集主链）。
    jiuyan_mark_sync_enabled: bool = Field(default=True)
    jiuyan_mark_path: str = Field(default=r"D:\APP_SOFT\TDX\T0002\mark.dat")
    jiuyan_mark_mark_color: str = Field(default="7")
    jiuyan_mark_tip_color: str = Field(default="65535")
    theme_heat_batch_size: int = Field(default=50)
    theme_heat_max_concurrency: int = Field(default=3)
    theme_heat_cache_ttl_seconds: int = Field(default=300)
    theme_heat_failed_batch_retries: int = Field(default=1)
    theme_heat_quote_timeout_ms: int = Field(default=10000)
    theme_heat_fund_timeout_ms: int = Field(default=30000)
    theme_heat_quote_collection_timeout_ms: int = Field(default=90000)
    theme_heat_fund_collection_timeout_ms: int = Field(default=180000)
    # THS L2 单票并发（2026-08-14 实测：并发 4 为甜点，30s 压测 18.7 rps 全程 0 429）
    theme_fund_concurrency: int = Field(default=4)
    theme_fund_upstream_timeout_seconds: float = Field(default=15.0)
    # analyze 路由并发闸门：同一时刻最多 N 个 golden 计算并发，防止并发请求拖死 8000
    quant_board_analyze_max_concurrency: int = Field(default=2)
    theme_fund_ths_upstream_url: str = Field(
        default="https://vaserviece.10jqka.com.cn/Level2/index.php"
    )
    theme_fund_refresh_interval_seconds: int = Field(default=300)
    theme_fund_cache_ttl_seconds: int = Field(default=259200)  # 3 天（容灾 1 交易日 + 跨周末）
    # akshare 同花顺网页全市场资金源开关（2026-08-14：默认启用，专供 theme_fund
    # 题材资金聚合；原“种子首屏占位”方案废弃，冷启动改由 Redis dump.rdb 恢复 L2）
    theme_fund_seed_enabled: bool = Field(default=True)
    # 题材主力资金上游（2026-09-29 用户确认切换）：默认 eastmoney（push2 ulist.np
    # 独立 URL 直连，不走 akshare——东财接口风控限流严重，必须精确控制请求节奏）；
    # akshare 同花顺网页口径保留为回退（QUANT_BOARD_THEME_FUND_SOURCE=akshare）。
    # 注意：同 sessionDate 下 rank 高者权威（eastmoney > akshare），当日盘中
    # 切回 akshare 不会覆盖当日已写入的东财行——切源需跨交易日生效，
    # 调度器 status 以 provider_source_stale_rows 暴露行源不一致（fail-visible）。
    theme_fund_source: str = Field(default="eastmoney")
    # 题材主力资金东财批量参数（风控纪律，2026-09-30 二次论断定稿）。
    # 核心原则：东财压力 ∝ 请求次数，绝不短间距频繁请求。
    # - batch 800：URL≈6.9KB 贴近 nginx 8KB 上限，全市场压到约 7 批（一次
    #   全市场 50KB 超限，分批仅过 URL 上限，减压靠批间距）；
    # - interval 60s：批间距分钟级，任意 1 分钟窗口最多 1 个请求
    #   （2026-09-30 盘中实透：300 只×18 批×1.5s 连发被 push2 断连封 IP）。
    theme_fund_em_batch_size: int = Field(default=800)
    theme_fund_em_request_interval_seconds: float = Field(default=60.0)
    theme_fund_em_request_timeout_seconds: float = Field(default=15.0)
    # 东财模式刷新周期：30 分钟一轮（轮内约 6 分钟完成、其余静默），
    # 独立于 akshare 模式的 theme_fund_refresh_interval_seconds（300s）
    theme_fund_em_refresh_interval_seconds: int = Field(default=1800)
    # KPL 题材个股人气后台刷新周期（2026-09：热度口径切换为 KPL 人气总和，
    # 对齐 tck2.js 的 10 分钟全量刷新节奏；下限 60s 由 KplHotnessCache 兜底）
    theme_kpl_hotness_refresh_seconds: int = Field(default=600)
    # 题材主力资金 fetch 预算：
    # - akshare 单请求模式：本默认值直接生效（默认 150s，单请求自身有 30s 上限）；
    # - 东财批量模式：实际预算由 fund_scheduler._build_market_fund_scheduler
    #   钳制为 max(600, 本值)——轮内 6×60~69s 批间距 + 7×15s 超时上限 ≈ 465-519s，
    #   600s 保证最坏情况不中途抬新断（避免 to_thread 僵尸线程跑完剩余批次却结果
    #   被丢）；调大 EM 批间距/批大小时需同步评估该下限。
    market_fund_fetch_timeout_seconds: float = Field(default=150.0)
    market_quotes_refresh_interval_seconds: int = Field(default=300)
    hotlist_refresh_interval_seconds: int = Field(default=600)
    xueqiu_cookie: str = Field(default="")
    data_source: DataSourceConfig = Field(default_factory=DataSourceConfig)

    def model_post_init(self, __context: Any) -> None:
        # allow_sqlite_backend 必须先于下方 sqlite URL 兜底解析（A1：兜底仅 opt-in 后填充）
        self.allow_sqlite_backend = _env_bool("QUANT_BOARD_ALLOW_SQLITE_BACKEND", self.allow_sqlite_backend)
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
        # 2026-09-29 隔离裁决（A1）：sqlite URL 兜底仅在显式 opt-in 后填充，否则留空串。
        # sqlite 引擎已随链退役删除，空值即 fail-visible，不再静默指向 warehouse .db；
        # 显式 env（SNAPSHOT/RESEARCH/THEME_DATABASE_URL、deprecated DATABASE_URL）仍照常生效。
        if not self.snapshot_database_url:
            self.snapshot_database_url = (
                os.environ.get("QUANT_BOARD_SNAPSHOT_DATABASE_URL")
                or old_db_url
                or (
                    f"sqlite:///{self.warehouse_dir / 'quant_board_snapshots.db'}"
                    if self.allow_sqlite_backend
                    else ""
                )
            )
        if not self.research_database_url:
            self.research_database_url = (
                os.environ.get("QUANT_BOARD_RESEARCH_DATABASE_URL")
                or (
                    f"sqlite:///{self.warehouse_dir / 'quant_board_research.db'}"
                    if self.allow_sqlite_backend
                    else ""
                )
            )
        if not self.theme_database_url:
            self.theme_database_url = (
                os.environ.get("QUANT_BOARD_THEME_DATABASE_URL")
                or (
                    f"sqlite:///{self.warehouse_dir / 'themeDATA.db'}"
                    if self.allow_sqlite_backend
                    else ""
                )
            )
        self.database_url = self.snapshot_database_url
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
        self.mongodb_uri = os.environ.get("QUANT_BOARD_MONGODB_URI", self.mongodb_uri)
        self.mongodb_database = os.environ.get("QUANT_BOARD_MONGODB_DATABASE", self.mongodb_database)
        self.mongodb_connect_timeout_ms = max(
            100,
            _env_int("QUANT_BOARD_MONGODB_CONNECT_TIMEOUT_MS", self.mongodb_connect_timeout_ms),
        )
        self.mongodb_server_selection_timeout_ms = max(
            100,
            _env_int(
                "QUANT_BOARD_MONGODB_SERVER_SELECTION_TIMEOUT_MS",
                self.mongodb_server_selection_timeout_ms,
            ),
        )
        self.mongodb_socket_timeout_ms = max(
            100,
            _env_int(
                "QUANT_BOARD_MONGODB_SOCKET_TIMEOUT_MS",
                self.mongodb_socket_timeout_ms,
            ),
        )
        self.mongodb_max_pool_size = max(
            1,
            _env_int("QUANT_BOARD_MONGODB_MAX_POOL_SIZE", self.mongodb_max_pool_size),
        )
        mongodb_backup_dir = os.environ.get("QUANT_BOARD_MONGODB_BACKUP_DIR")
        if mongodb_backup_dir:
            self.mongodb_backup_dir = Path(mongodb_backup_dir)
        self.mongodb_backup_retention_days = max(
            1,
            _env_int("QUANT_BOARD_MONGODB_BACKUP_RETENTION_DAYS", self.mongodb_backup_retention_days),
        )
        self.mongodb_remote_backup_keep = max(
            1,
            _env_int("QUANT_BOARD_MONGODB_REMOTE_BACKUP_KEEP", self.mongodb_remote_backup_keep),
        )
        mongodb_tools_bin = os.environ.get("QUANT_BOARD_MONGODB_TOOLS_BIN")
        if mongodb_tools_bin:
            self.mongodb_tools_bin = Path(mongodb_tools_bin)
        self.storage_backend = os.environ.get("QUANT_BOARD_STORAGE_BACKEND", self.storage_backend).strip().lower()
        if self.storage_backend not in {"sqlite", "mongodb"}:
            raise ValueError(f"unsupported QUANT_BOARD_STORAGE_BACKEND: {self.storage_backend}")
        # allow_sqlite_backend 已在 model_post_init 顶部解析（先于 sqlite URL 兜底）
        if self.storage_backend == "sqlite" and not self.allow_sqlite_backend:
            raise RuntimeError(
                "生产禁止 sqlite 存储链：默认后端为 mongodb/dragon_board_quant；"
                "如确需 sqlite（仅限一次性本地诊断），显式设置 QUANT_BOARD_ALLOW_SQLITE_BACKEND=1"
            )
        self.redis_url = os.environ.get("QUANT_BOARD_REDIS_URL", self.redis_url)
        self.redis_key_prefix = os.environ.get("QUANT_BOARD_REDIS_KEY_PREFIX", self.redis_key_prefix).strip(":")
        self.snapshot_cache_enabled = _env_bool(
            "QUANT_BOARD_SNAPSHOT_CACHE_ENABLED",
            self.snapshot_cache_enabled,
        )
        self.jiuyan_mark_sync_enabled = _env_bool(
            "QUANT_BOARD_JIUYAN_MARK_SYNC",
            self.jiuyan_mark_sync_enabled,
        )
        self.jiuyan_mark_path = os.environ.get(
            "QUANT_BOARD_JIUYAN_MARK_PATH", self.jiuyan_mark_path)
        self.jiuyan_mark_mark_color = os.environ.get(
            "QUANT_BOARD_JIUYAN_MARK_MARK_COLOR", self.jiuyan_mark_mark_color)
        self.jiuyan_mark_tip_color = os.environ.get(
            "QUANT_BOARD_JIUYAN_MARK_TIP_COLOR", self.jiuyan_mark_tip_color)
        self.snapshot_cache_ttl_seconds = max(
            1,
            _env_int("QUANT_BOARD_SNAPSHOT_CACHE_TTL_SECONDS", self.snapshot_cache_ttl_seconds),
        )
        self.snapshot_empty_cache_ttl_seconds = max(
            1,
            _env_int(
                "QUANT_BOARD_SNAPSHOT_EMPTY_CACHE_TTL_SECONDS",
                self.snapshot_empty_cache_ttl_seconds,
            ),
        )
        self.theme_rotation_cache_ttl_seconds = max(
            1,
            _env_int(
                "QUANT_BOARD_THEME_ROTATION_CACHE_TTL_SECONDS",
                self.theme_rotation_cache_ttl_seconds,
            ),
        )
        self.hotlist_sentiment_cache_ttl_seconds = max(
            1,
            _env_int(
                "QUANT_BOARD_HOTLIST_SENTIMENT_CACHE_TTL_SECONDS",
                self.hotlist_sentiment_cache_ttl_seconds,
            ),
        )
        self.theme_research_summary_cache_ttl_seconds = max(
            1,
            _env_int(
                "QUANT_BOARD_THEME_RESEARCH_SUMMARY_CACHE_TTL_SECONDS",
                self.theme_research_summary_cache_ttl_seconds,
            ),
        )
        self.snapshot_cache_connect_timeout_seconds = max(
            0.05,
            _env_float(
                "QUANT_BOARD_SNAPSHOT_CACHE_CONNECT_TIMEOUT_SECONDS",
                self.snapshot_cache_connect_timeout_seconds,
            ),
        )
        self.snapshot_cache_socket_timeout_seconds = max(
            0.05,
            _env_float(
                "QUANT_BOARD_SNAPSHOT_CACHE_SOCKET_TIMEOUT_SECONDS",
                self.snapshot_cache_socket_timeout_seconds,
            ),
        )
        self.quant_board_analyze_max_concurrency = max(
            1,
            _env_int(
                "QUANT_BOARD_ANALYZE_MAX_CONCURRENCY",
                self.quant_board_analyze_max_concurrency,
            ),
        )
        self.snapshot_collector_enabled = _env_bool(
            "QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED",
            self.snapshot_collector_enabled,
        )
        self.snapshot_collector_dataset_id = os.environ.get(
            "QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID",
            self.snapshot_collector_dataset_id,
        )
        self.snapshot_collector_types = os.environ.get(
            "QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES",
            self.snapshot_collector_types,
        )
        self.snapshot_collector_poll_ms = max(
            100,
            _env_int("QUANT_BOARD_SNAPSHOT_COLLECTOR_POLL_MS", self.snapshot_collector_poll_ms),
        )
        self.snapshot_collector_close_grace_minutes = min(
            29,  # 上限 29 分钟：最后槽位 15:30 + grace = 15:59，落在 [09:00,16:00) 窗口内
            max(
                1,
                _env_int(
                    "QUANT_BOARD_SNAPSHOT_COLLECTOR_CLOSE_GRACE_MINUTES",
                    self.snapshot_collector_close_grace_minutes,
                ),
            ),
        )
        self.snapshot_collector_proxy_base_url = os.environ.get(
            "QUANT_BOARD_SNAPSHOT_COLLECTOR_PROXY_BASE_URL",
            self.snapshot_collector_proxy_base_url,
        )
        self.snapshot_collector_bridge_base_url = os.environ.get(
            "QUANT_BOARD_SNAPSHOT_COLLECTOR_BRIDGE_BASE_URL",
            self.snapshot_collector_bridge_base_url,
        )
        self.snapshot_collector_provider_timeout_ms = max(
            100,
            _env_int(
                "QUANT_BOARD_SNAPSHOT_COLLECTOR_PROVIDER_TIMEOUT_MS",
                self.snapshot_collector_provider_timeout_ms,
            ),
        )
        self.snapshot_collector_pool_source_mode = os.environ.get(
            "QUANT_BOARD_SNAPSHOT_COLLECTOR_POOL_SOURCE_MODE",
            self.snapshot_collector_pool_source_mode,
        )
        self.snapshot_collector_allow_live_dataset = _env_bool(
            "QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET",
            self.snapshot_collector_allow_live_dataset,
        )
        self.theme_heat_batch_size = max(
            1,
            _env_int("QUANT_BOARD_THEME_HEAT_BATCH_SIZE", self.theme_heat_batch_size),
        )
        self.theme_heat_max_concurrency = max(
            1,
            _env_int("QUANT_BOARD_THEME_HEAT_MAX_CONCURRENCY", self.theme_heat_max_concurrency),
        )
        self.theme_heat_cache_ttl_seconds = max(
            1,
            _env_int("QUANT_BOARD_THEME_HEAT_CACHE_TTL_SECONDS", self.theme_heat_cache_ttl_seconds),
        )
        self.theme_heat_failed_batch_retries = max(
            1,
            _env_int(
                "QUANT_BOARD_THEME_HEAT_FAILED_BATCH_RETRIES",
                self.theme_heat_failed_batch_retries,
            ),
        )
        self.theme_fund_concurrency = max(
            1,
            min(4, _env_int("QUANT_BOARD_THEME_FUND_CONCURRENCY", self.theme_fund_concurrency)),
        )
        self.theme_fund_upstream_timeout_seconds = max(
            0.1,
            _env_float(
                "QUANT_BOARD_THEME_FUND_UPSTREAM_TIMEOUT_SECONDS",
                self.theme_fund_upstream_timeout_seconds,
            ),
        )
        self.theme_fund_ths_upstream_url = os.environ.get(
            "QUANT_BOARD_THEME_FUND_THS_UPSTREAM_URL",
            self.theme_fund_ths_upstream_url,
        ).strip()
        self.theme_fund_refresh_interval_seconds = max(
            60,
            _env_int(
                "QUANT_BOARD_THEME_FUND_REFRESH_INTERVAL_SECONDS",
                self.theme_fund_refresh_interval_seconds,
            ),
        )
        self.theme_fund_cache_ttl_seconds = max(
            60,
            _env_int(
                "QUANT_BOARD_THEME_FUND_CACHE_TTL_SECONDS",
                self.theme_fund_cache_ttl_seconds,
            ),
        )
        seed_flag = os.environ.get("QUANT_BOARD_THEME_FUND_SEED_ENABLED")
        if seed_flag is not None:
            self.theme_fund_seed_enabled = seed_flag.strip().lower() in {"1", "true", "yes", "on"}
        fund_source = os.environ.get("QUANT_BOARD_THEME_FUND_SOURCE", "").strip().lower()
        if fund_source in {"eastmoney", "akshare"}:
            self.theme_fund_source = fund_source
        elif fund_source:
            # 拼错源名（如 em/east）静默回落默认会误导排障：显式告警（m5）
            logging.getLogger(__name__).warning(
                "QUANT_BOARD_THEME_FUND_SOURCE=%r not in {eastmoney, akshare}; keep default %s",
                fund_source,
                self.theme_fund_source,
            )
        # 风控安全下限：interval 0 等于关闭节流（封 IP 风险），batch 过小（如 1）
        # 会把全市场拆成 5000+ 请求（结合超时僵尸线程边界放大风险），均设下限
        self.theme_fund_em_batch_size = max(
            50,
            _env_int("QUANT_BOARD_THEME_FUND_EM_BATCH_SIZE", self.theme_fund_em_batch_size),
        )
        self.theme_fund_em_request_interval_seconds = max(
            30.0,
            _env_float(
                "QUANT_BOARD_THEME_FUND_EM_REQUEST_INTERVAL_SECONDS",
                self.theme_fund_em_request_interval_seconds,
            ),
        )
        self.theme_fund_em_refresh_interval_seconds = max(
            600,
            _env_int(
                "QUANT_BOARD_THEME_FUND_EM_REFRESH_INTERVAL_SECONDS",
                self.theme_fund_em_refresh_interval_seconds,
            ),
        )
        self.theme_fund_em_request_timeout_seconds = max(
            5.0,
            _env_float(
                "QUANT_BOARD_THEME_FUND_EM_REQUEST_TIMEOUT_SECONDS",
                self.theme_fund_em_request_timeout_seconds,
            ),
        )
        self.theme_kpl_hotness_refresh_seconds = max(
            60,
            _env_int(
                "QUANT_BOARD_THEME_KPL_HOTNESS_REFRESH_SECONDS",
                self.theme_kpl_hotness_refresh_seconds,
            ),
        )
        self.market_fund_fetch_timeout_seconds = max(
            10.0,
            _env_float(
                "QUANT_BOARD_MARKET_FUND_FETCH_TIMEOUT_SECONDS",
                self.market_fund_fetch_timeout_seconds,
            ),
        )
        self.market_quotes_refresh_interval_seconds = max(
            60,
            _env_int(
                "QUANT_BOARD_MARKET_QUOTES_REFRESH_INTERVAL_SECONDS",
                self.market_quotes_refresh_interval_seconds,
            ),
        )
        self.hotlist_refresh_interval_seconds = max(
            60,
            _env_int(
                "QUANT_BOARD_HOTLIST_REFRESH_INTERVAL_SECONDS",
                self.hotlist_refresh_interval_seconds,
            ),
        )
        self.xueqiu_cookie = os.environ.get(
            "QUANT_BOARD_XUEQIU_COOKIE",
            os.environ.get("XUEQIU_COOKIE", self.xueqiu_cookie),
        ).strip()
        self.theme_heat_quote_timeout_ms = max(
            100,
            _env_int("QUANT_BOARD_THEME_HEAT_QUOTE_TIMEOUT_MS", self.theme_heat_quote_timeout_ms),
        )
        self.theme_heat_fund_timeout_ms = max(
            100,
            _env_int("QUANT_BOARD_THEME_HEAT_FUND_TIMEOUT_MS", self.theme_heat_fund_timeout_ms),
        )
        self.theme_heat_quote_collection_timeout_ms = max(
            1000,
            _env_int(
                "QUANT_BOARD_THEME_HEAT_QUOTE_COLLECTION_TIMEOUT_MS",
                self.theme_heat_quote_collection_timeout_ms,
            ),
        )
        self.theme_heat_fund_collection_timeout_ms = max(
            1000,
            _env_int(
                "QUANT_BOARD_THEME_HEAT_FUND_COLLECTION_TIMEOUT_MS",
                self.theme_heat_fund_collection_timeout_ms,
            ),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.warehouse_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.mongodb_backup_dir.mkdir(parents=True, exist_ok=True)


def assert_production_storage_backend(settings: "Settings | None" = None) -> None:
    """生产入口 fail-fast（8000 API / 8001 采集器 startup 调用）：
    sqlite 后端未显式 opt-in 即拒绝启动，防止裸环境静默写 warehouse sqlite。"""
    resolved = settings if settings is not None else get_settings()
    if resolved.storage_backend != "mongodb" and not getattr(resolved, "allow_sqlite_backend", False):
        raise RuntimeError(
            "生产入口禁止 sqlite 存储链：请使用 mongodb/dragon_board_quant，"
            "或显式设置 QUANT_BOARD_ALLOW_SQLITE_BACKEND=1（仅限一次性本地诊断）"
        )
    return None


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
