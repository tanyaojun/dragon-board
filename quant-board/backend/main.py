from __future__ import annotations

import asyncio
import logging
import warnings
from time import perf_counter
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from backend.api.fusion_strategy_projection_routes import router as fusion_strategy_projection_router
from backend.api.big_order_history_routes import router as big_order_history_router
from backend.api.hotlist_routes import router as hotlist_router
from backend.api.journal_routes import router as journal_router
from backend.api.market_fund_routes import router as market_fund_router
from backend.api.market_data_routes import router as market_data_router
from backend.api.ranktrend_routes import router as ranktrend_router
from backend.api.snapshot_collector_routes import router as snapshot_collector_router
from backend.api.theme_heat_routes import router as theme_heat_router
from backend.api.theme_history_routes import router as theme_history_router
from backend.api.theme_momentum_routes import router as theme_momentum_router
from backend.api.theme_rotation_routes import router as theme_rotation_router
from backend.api.ths_main_monitor_routes import router as ths_main_monitor_router
from backend.data.backup.auto_sync import auto_sync_runner, run_outbox_auto_sync_once
from backend.data.archive.auto_archive import archive_auto_runner, run_archive_auto_once
from backend.data.archive.object_store import get_object_backup_store
from backend.data.archive.service import ArchiveService
from backend.data.backup.backup_retention import backup_retention_runner, run_backup_retention_once
from backend.snapshot_collector.scheduler import snapshot_collector_scheduler
from backend.data.backup.backup_sync import BackupSyncService
from backend.data.models.database import ResearchSessionLocal, get_db, init_db, primary_status
from backend.data.ingest.dataset_service import DatasetService
from backend.data.ingest.importers import ImporterError
from backend.data.ingest.snapshot_ingest_normalizer import normalize_snapshot_ingest
from backend.data.migrations.migration import SnapshotMigrationService
from backend.data.models.models import Dataset
from backend.data.ingest.json_codec import loads_json_field
from backend.data.repositories.repository import Repository
from backend.data.repositories.repository_factory import create_repository, get_runtime_mongodb_database, storage_source_label
from backend.data.models.schemas import (
    GoldenImportRequest,
    GoldenValidateRequest,
    ImportDatasetRequest,
    SnapshotIngestRequest,
    SnapshotJsonMigrationRequest,
)
from backend.data.repositories.stock_name_repository import STOCK_NAMES_VERSION, StockNameRepository
from backend.services.market.stock_name_refresh_scheduler import stock_name_refresh_scheduler
from backend.services.snapshot_analysis_service import analyze_snapshot_and_persist
from backend.data.cache import snapshot_cache
from backend.data.backup.supabase_backup import get_backup_client
from backend.data.models.theme_database import get_theme_db, init_theme_db, theme_status
from backend.data.repositories.mongo_theme_repository import MongoThemeRepository
from backend.data.repositories.theme_repository import ThemeRepository
from backend.data.migrations.theme_migration import ThemeMigrationError, ThemeMigrationService
from backend.services.theme.mapping_refresh import refresh_theme_stock_mappings
from backend.services.theme.mapping_scheduler import theme_mapping_refresh_scheduler
from backend.services.market.ths_main_monitor_service import close_ths_main_monitor_service
from backend.services.market.fund_scheduler import market_fund_scheduler
from backend.services.market.ths_fund_refresh_scheduler import (
    close_ths_fund_refresh_scheduler,
    get_ths_fund_refresh_scheduler,
)
from backend.operations.schedule import run_after_market_once
from backend.services import (
    BacktestService,
    GoldenService,
    OptimizationService,
    compute_alignment,
    compute_checkpoint_layer2,
    select_longtest_baseline_slots,
    summarize_longtest_slot_label,
)
from backend.core.settings import get_settings
from backend.core.utils import json_loads


logger = logging.getLogger(__name__)


# akshare stock_fund_flow 内部 pd.concat 与新版 pandas 存在已知弃用警告
# （第三方库内部实现，无法在调用方修复）。全市场资金流刷新每次都会触发并刷屏日志，
# 这里按模块精确静默该类 FutureWarning，不影响其它警告的可见性。
warnings.filterwarnings(
    "ignore",
    category=FutureWarning,
    module=r"akshare\.stock_feature\.stock_fund_flow",
)


app = FastAPI(
    title="QuantBoard",
    version="0.1.0",
    description="Python RankTrend 回测平台",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(journal_router)
app.include_router(market_fund_router)
app.include_router(market_data_router)
app.include_router(ranktrend_router)
app.include_router(big_order_history_router)
app.include_router(hotlist_router)
app.include_router(fusion_strategy_projection_router)
app.include_router(snapshot_collector_router)
app.include_router(theme_heat_router)
app.include_router(theme_history_router)
app.include_router(theme_momentum_router)
app.include_router(theme_rotation_router)
app.include_router(ths_main_monitor_router)


def prune_legacy_redis_ttl(redis_client: Any, prefix: str) -> dict[str, int]:
    """启动时一次性清理存量永久 Redis key（2026-08-11 用户确认"只管杀不管埋"修复）。

    给历史无 TTL 的缓存 key 补 TTL：
    - ``ths-main-monitor:raw:*`` → 3 天（容灾 1 交易日 + 跨周末，此前 628 个永久）
    - ``snapshot:generation:*`` → 7 天（缓存失效标记，过期后重新计算一次）
    - ``theme-fund:v3:version`` → 3 天（与 latest 同生命周期）
    best-effort：Redis 不可用/单个 key 失败不阻塞启动。
    """
    patterns = {
        f"{prefix}:ths-main-monitor:raw*": 259200,
        f"{prefix}:snapshot:generation*": 604800,
        f"{prefix}:theme-fund:v3:version": 259200,
    }
    counts: dict[str, int] = {}
    for pattern, ttl_seconds in patterns.items():
        pruned = 0
        try:
            for key in redis_client.scan_iter(match=pattern, count=500):
                try:
                    if redis_client.ttl(key) < 0:
                        redis_client.expire(key, ttl_seconds)
                        pruned += 1
                except Exception:
                    continue
        except Exception:
            logger.warning("prune legacy redis ttl scan failed for %s", pattern, exc_info=True)
        counts[pattern] = pruned
        if pruned:
            logger.info("prune legacy redis ttl: %s -> %d keys", pattern, pruned)
    return counts


async def restore_fund_flow_from_mongodb() -> None:
    """冷启动资金恢复：MongoDB fund_flow_l2 最近交易日 L2 行 → ThemeFundCache。

    零第三方请求；失败不阻塞启动（回退为仅盘中校准）。完整 7 档 buckets
    保留在 MongoDB，恢复只投影 total.zlje 摘要进 Redis/内存。

    2026-08-14 修复：恢复行 source=ths_main_monitor（L2 主源），必须走
    ``put`` 写 latest hash——不能走 ``put_many``（已改为写 akshare 题材源
    独立 hash，会导致 L2 串线到题材源，实盘已出现 akshare hash 混入
    ths_main_monitor 行）。
    """
    from backend.data.repositories.fund_flow_repository import (
        FundFlowRepository,
        project_cache_rows,
    )
    from backend.data.repositories.repository_factory import get_runtime_mongodb_database
    from backend.services.theme.fund_cache import get_theme_fund_cache

    repo = FundFlowRepository(get_runtime_mongodb_database())
    session_date, docs = await asyncio.to_thread(repo.load_latest_session)
    if not docs:
        return
    rows = project_cache_rows(docs)
    if not rows:
        return

    def _restore() -> int:
        cache = get_theme_fund_cache()
        saved = 0
        for row in rows:
            try:
                cache.put(dict(row))
                saved += 1
            except ValueError:
                continue
        return saved

    saved = await asyncio.to_thread(_restore)
    logger.info("fund_flow_l2 cold restore: %d rows from %s", saved, session_date)

@app.on_event("startup")
async def on_startup() -> None:
    # 清理策略（2026-08-12）：启动时给存量永久 Redis key 补 TTL
    # （ths-main-monitor:raw / snapshot:generation / theme-fund version）——
    # 修复"只管杀不管埋"：历史无 TTL 缓存补过期时间，best-effort 不阻塞启动
    try:
        from backend.core.settings import get_settings as _get_settings
        from backend.market_proxy.redis_client import get_hotlist_redis_client

        _redis = get_hotlist_redis_client(_get_settings())
        if _redis is not None:
            _prefix = _get_settings().redis_key_prefix
            _patterns = {
                f"{_prefix}:ths-main-monitor:raw*": 259200,
                f"{_prefix}:snapshot:generation*": 604800,
                f"{_prefix}:theme-fund:v3:version": 259200,
            }
            for _pattern, _ttl in _patterns.items():
                try:
                    for _key in _redis.scan_iter(match=_pattern, count=500):
                        try:
                            if _redis.ttl(_key) < 0:
                                _redis.expire(_key, _ttl)
                        except Exception:
                            continue
                except Exception:
                    continue
    except Exception:
        pass
    if get_settings().storage_backend != "mongodb":
        init_db()
        init_theme_db()
        auto_sync_runner.start()
        archive_auto_runner.start()
        backup_retention_runner.start()
    # 快照采集已迁移到独立进程 backend.collector_main（8001，由 launcher 管理），
    # 本 API 进程不再启动采集 scheduler，避免双进程争锁/双采。
    stock_name_refresh_scheduler.start()
    theme_mapping_refresh_scheduler.start()
    # KPL 题材个股人气缓存（2026-09 热度口径 = KPL 人气总和，tck2.js）：后台线程
    # 每 10 分钟全量刷新，启动即预热一轮。best-effort：失败不阻断启动，
    # 题材热度缺失会以 kpl_hotness_unavailable 标记暴露在前端。
    if get_settings().storage_backend == "mongodb":
        try:
            from backend.services.theme.heat_service import get_kpl_hotness_cache

            kpl_hotness_cache = get_kpl_hotness_cache()
            if kpl_hotness_cache is not None:
                kpl_hotness_cache.start()
        except Exception:
            logger.exception("kpl hotness cache startup failed; continue startup")
    # MongoDB L2 资金冷启动恢复（零第三方）：最近交易日 L2 行 → ThemeFundCache
    # （Redis + 进程内 last-good），首屏资金列直接命中；失败不阻塞启动。
    if get_settings().storage_backend == "mongodb":
        try:
            await restore_fund_flow_from_mongodb()
        except Exception:
            logger.exception("fund_flow_l2 cold restore failed; continue startup")
    # 量比历史缓存预热（2026-08-13）：预装全市场 daily 历史成交量到 Redis，
    # 避免首次量比请求冷启动串行查 Mongo 造成量价字段长时间 --。
    # best-effort：后台线程执行，失败不阻断启动。
    if get_settings().storage_backend == "mongodb":
        from backend.services.market.volume_ratio_service import warmup_volume_ratio_daily

        def _warmup_volume_ratio() -> None:
            try:
                warmup_volume_ratio_daily()
            except Exception:
                logger.exception("volume_ratio daily warmup failed; continue startup")

        asyncio.get_running_loop().run_in_executor(None, _warmup_volume_ratio)
    # RankTrend frame_bundles 缓存预热（2026-08-13，2026-08-23 对齐 C'）：预装最近
    # ANALYZE_FULL_MARKET_LOAD_LIMIT=280 帧 ranktrend+themes bundle 到 Redis，消除 analyze
    # 四信号（共振/趋势/周期/量价）冷启动的 Mongo 重查询。帧数必须与全市场 analyze 的
    # load_limit 一致（frame_bundles 缓存 key 含 snapshot_ids，200 帧与 280 帧 key 不同，
    # 预热才会被 analyze 命中；否则预热白做、首开仍冷算 280 帧）。best-effort，失败不阻断启动。
    if get_settings().storage_backend == "mongodb":
        from backend.data.repositories import repository_factory as _repo_factory

        def _warmup_ranktrend_bundles() -> None:
            try:
                from backend.api.ranktrend_routes import ANALYZE_FULL_MARKET_LOAD_LIMIT as _ANALYZE_LIMIT
                _db = _repo_factory.get_runtime_mongodb_database()
                _repo = _repo_factory.create_repository(_db, enable_backup=False)
                _repo.load_frame_bundles(
                    "dragonboard_live",
                    snapshot_type="half_hour",
                    sort="desc",
                    projection="ranktrend+themes",
                    limit=_ANALYZE_LIMIT,
                )
            except Exception:
                logger.exception("ranktrend frame_bundles warmup failed; continue startup")

        asyncio.get_running_loop().run_in_executor(None, _warmup_ranktrend_bundles)
    # RankTrend analyze 响应预热（2026-08-13）：预计算最近一帧全市场四信号并写 Redis 缓存，
    # 冷启动（startup bundle / analyze 缓存失效）时前端请求命中，避免引擎 30 帧 × 全市场
    # 逐股重算造成四信号 5-10 秒 "--"。
    # 2026-08-25（P2 复盘）：预热用**最新快照帧**构造 currentFrame（rank=快照 compRank、
    # avgRankNum=快照均榜），而前端请求用**实时值**（compRank/avgRankNum 为前端本地实时计算，
    # 见 ComprehensiveRankEngine.rankMergedStocks）→ 两者缓存键**天然不同**，预热键命中率有限
    # （主要覆盖历史帧请求 / slotTime 规范化后同 tradingDate 的窗口）。这是预期限制，
    # 不宣称"必须对齐"；best-effort：后台异步任务，失败不阻断启动。
    if get_settings().storage_backend == "mongodb":
        from backend.api.ranktrend_routes import analyze_ranktrend

        def _warmup_num(value: Any) -> int | float:
            """模拟前端 Number(x) || 0：非数字/NaN → 0；整数 → int，其余 → float。"""
            try:
                f = float(value)
            except (TypeError, ValueError):
                return 0
            if f != f:  # NaN
                return 0
            if f.is_integer():
                return int(f)
            return f

        async def _warmup_ranktrend_analyze() -> None:
            try:
                _db = get_runtime_mongodb_database()
                _repo = create_repository(_db, enable_backup=False)
                bundles = _repo.load_frame_bundles(
                    "dragonboard_live",
                    snapshot_type="half_hour",
                    sort="desc",
                    projection="ranktrend+themes",
                    limit=1,
                )
                if not bundles:
                    logger.info("[warmup] ranktrend analyze 预热跳过：无快照帧")
                    return
                latest = bundles[0]
                stocks = latest.get("rows") or latest.get("stocks") or []
                current_stocks: list[dict[str, Any]] = []
                codes: list[str] = []
                for stock in stocks:
                    if not isinstance(stock, dict):
                        continue
                    code = str(stock.get("code") or "").strip()
                    if not code:
                        continue
                    avg_rank_num = _warmup_num(stock.get("avgRankNum"))
                    if avg_rank_num <= 0:
                        continue
                    rank_raw = stock.get("compRank")
                    if not rank_raw:  # 对齐前端 compRank || rank
                        rank_raw = stock.get("rank")
                    current_stocks.append(
                        {
                            "code": code,
                            "rank": _warmup_num(rank_raw),
                            "avgRankNum": avg_rank_num,
                        }
                    )
                    codes.append(code)
                if not codes:
                    return
                payload = {
                    "snapshotType": "half_hour",
                    "datasetId": "dragonboard_live",
                    "codes": codes,
                    "currentFrame": {
                        "tradingDate": latest.get("tradingDate"),
                        "slotTime": "current",
                        "stocks": current_stocks,
                    },
                }
                await analyze_ranktrend(payload, _db)
                logger.info("[warmup] ranktrend analyze 预热完成，codes=%d", len(codes))
            except Exception:
                logger.exception("ranktrend analyze warmup failed; continue startup")

        asyncio.create_task(_warmup_ranktrend_analyze())
    market_fund_scheduler.start()
    # mainMonitorDetail 展示池资金校准（L2 主源，覆盖 akshare 种子）
    get_ths_fund_refresh_scheduler().start()
    from backend.market_proxy.quotes import start_market_quotes_refresh
    from backend.market_proxy.hotlists import start_hotlist_refresh

    await start_market_quotes_refresh()
    await start_hotlist_refresh()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if get_settings().storage_backend != "mongodb":
        await auto_sync_runner.stop()
        await archive_auto_runner.stop()
        await backup_retention_runner.stop()
    await snapshot_collector_scheduler.stop()
    await stock_name_refresh_scheduler.stop()
    await theme_mapping_refresh_scheduler.stop()
    # KPL 缓存只在 mongodb 模式启动（与 startup 对称）：非 mongo 部署不尝试
    # 停止，避免每次关闭都打印 "kpl hotness shutdown failed" 异常栈（审计 L4）。
    if get_settings().storage_backend == "mongodb":
        try:
            from backend.services.theme.heat_service import get_kpl_hotness_cache

            kpl_hotness_cache = get_kpl_hotness_cache()
            if kpl_hotness_cache is not None:
                kpl_hotness_cache.stop()
        except Exception:
            logger.exception("kpl hotness cache shutdown failed; continue shutdown")
    await market_fund_scheduler.stop()
    await close_ths_fund_refresh_scheduler()
    from backend.market_proxy.quotes import stop_market_quotes_refresh

    await stop_market_quotes_refresh()
    from backend.market_proxy.hotlists import close_hotlist_client, stop_hotlist_refresh
    from backend.market_proxy.limitup import close_limitup_client
    from backend.market_proxy.longhu import close_longhu_client
    from backend.market_proxy.sentiment import close_sentiment_client
    from backend.market_proxy.surge import close_surge_client
    from backend.market_proxy.xuangubao import close_xuangubao_client

    await stop_hotlist_refresh()
    await close_hotlist_client()
    await close_limitup_client()
    await close_longhu_client()
    await close_sentiment_client()
    await close_surge_client()
    await close_xuangubao_client()
    from backend.snapshot_collector.providers import close_collector_http

    close_collector_http()
    await close_ths_main_monitor_service()


def _kpl_hotness_health() -> dict[str, Any]:
    """KPL 人气缓存健康（best-effort：未配置/异常时返回结构化占位，不崩 health）。"""
    try:
        from backend.services.theme.heat_service import get_kpl_hotness_cache

        cache = get_kpl_hotness_cache()
        if cache is None:
            return {"available": False, "reason": "kpl_cache_not_configured"}
        return cache.get_health()
    except Exception as exc:
        return {"available": False, "reason": str(exc)}


@app.get("/api/health")
def health_check(deep: bool = False, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    backup_status = {"configured": False, "connected": False, "last_error": None}
    backup = None if storage_source_label() == "mongodb" else get_backup_client()
    if backup:
        backup_status = backup.deep_health() if deep else backup.health()
    return {
        # launcher 健康契约：8000 进程存活即 ok/none，采集器状态见 collector_main。
        "status": "ok",
        "restartable": True,
        "recommendedAction": "none",
        "reason": "量化后端 API 运行正常",
        "version": "0.1.0",
        "engine": "QuantBoard",
        "default_snapshot_type": "half_hour",
        "database": {
            "primary": primary_status(),
            "theme": theme_status(),
            "backup": backup_status,
            "mode": "mongodb_primary" if storage_source_label() == "mongodb" else "sqlite_primary_supabase_backup",
            "outbox": None if storage_source_label() == "mongodb" else (Repository(db, enable_backup=False).outbox_status() if db is not None else None),
            "autoSync": auto_sync_runner.status(),
            "backupRetention": backup_retention_runner.status(),
        },
        "archive": {
            "dir": str(get_settings().archive_dir),
            "retentionTradingDays": get_settings().archive_retention_trading_days,
            "parquetCompression": get_settings().archive_parquet_compression,
            "autoArchive": archive_auto_runner.status(),
            "objectBackup": {
                "enabled": get_settings().object_backup_enabled,
                "bucketConfigured": bool(get_settings().object_backup_bucket),
                "provider": "r2",
            },
        },
        "snapshotCollector": snapshot_collector_scheduler.status(),
        "stockNameRefresh": stock_name_refresh_scheduler.status(),
        "themeMappingRefresh": theme_mapping_refresh_scheduler.status(),
        "marketFundRefresh": market_fund_scheduler.status(),
        "thsFundRefresh": get_ths_fund_refresh_scheduler().status(),
        "kplHotness": _kpl_hotness_health(),
    }


def get_stock_name_repository() -> StockNameRepository:
    return StockNameRepository(get_runtime_mongodb_database())


def get_theme_repository(db: Session | None = None) -> ThemeRepository | MongoThemeRepository:
    if storage_source_label() == "mongodb":
        return MongoThemeRepository(get_runtime_mongodb_database())
    if db is None:
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    return ThemeRepository(db)


@app.get("/api/stocks/names")
def list_stock_names(
    market: str | None = None,
    type: str | None = None,
    active: bool | None = True,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    try:
        stocks = get_stock_name_repository().list_names(
            market=market, type=type, active=active, limit=limit, offset=offset,
        )
        return {
            "ok": True,
            "source": "mongodb",
            "version": STOCK_NAMES_VERSION,
            "stocks": stocks,
            "count": len(stocks),
            "limit": limit,
            "offset": offset,
        }
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/api/stocks/names/{code}")
def get_stock_name(code: str, active: bool | None = True) -> dict[str, Any]:
    try:
        stock = get_stock_name_repository().get_by_code(code, active=active)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if not stock:
        raise HTTPException(status_code=404, detail=f"stock not found: {code}")
    return {
        "ok": True,
        "source": "mongodb",
        "version": STOCK_NAMES_VERSION,
        "stock": stock,
    }


@app.get("/api/stocks/search")
def search_stock_names(
    q: str,
    market: str | None = None,
    type: str | None = None,
    active: bool | None = True,
    limit: int = 50,
) -> dict[str, Any]:
    try:
        stocks = get_stock_name_repository().search(q, market=market, type=type, active=active, limit=limit)
        return {
            "ok": True,
            "source": "mongodb",
            "version": STOCK_NAMES_VERSION,
            "stocks": stocks,
            "count": len(stocks),
        }
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.post("/api/sync/push-backup")
def push_backup(full_history: bool = False, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="Supabase backup is disabled after MongoDB migration")
    return BackupSyncService(db).push_all_to_backup(full_history=full_history)


@app.post("/api/sync/pull-backup")
def pull_backup(db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="Supabase backup is disabled after MongoDB migration")
    return BackupSyncService(db).pull_backup_to_primary()


@app.post("/api/sync/push-outbox")
def push_outbox(limit: int | None = None, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="sync_outbox is disabled after MongoDB migration")
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    repo = Repository(db, enable_backup=False)
    return BackupSyncService(db).push_outbox_to_backup(repo, limit=limit or get_settings().backup_auto_sync_batch_size)


@app.post("/api/sync/auto-once")
def run_auto_sync_once(limit: int | None = None) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="sync_outbox auto sync is disabled after MongoDB migration")
    return run_outbox_auto_sync_once(limit)


@app.post("/api/sync/prune-backup")
def prune_backup(dry_run: bool = False) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="Supabase retention is disabled after MongoDB migration")
    return run_backup_retention_once(dry_run=dry_run)


@app.post("/api/storage/archive/auto-once")
def run_archive_auto_once_api(limit: int | None = None) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="SQLite archive auto cleanup is disabled after MongoDB migration")
    return run_archive_auto_once(limit)


@app.post("/api/storage/archive/backup-snapshot-day")
def backup_snapshot_day(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    trading_date: str | None = None,
    dry_run: bool = False,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="SQLite snapshot-day backup endpoint is disabled after MongoDB migration")
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    service = ArchiveService(db)
    target_date = trading_date or service.latest_snapshot_trading_date(
        dataset_id=dataset_id,
        snapshot_type=snapshot_type,
    )
    if not target_date:
        return {
            "ok": False,
            "error": {
                "code": "no_snapshot_trading_date",
                "datasetId": dataset_id,
                "snapshotType": snapshot_type,
            },
        }
    return service.backup_snapshot_day_to_object(
        dataset_id=dataset_id,
        snapshot_type=snapshot_type,
        trading_date=target_date,
        dry_run=dry_run,
    )


def _reject_sqlite_archive_for_mongodb() -> None:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="SQLite archive endpoints are disabled after MongoDB migration")


@app.post("/api/operations/after-market-once")
def run_after_market_once_api(
    archive_limit: int | None = None,
    backup_limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    return run_after_market_once(archive_limit=archive_limit, backup_limit=backup_limit, dry_run=dry_run)


@app.post("/api/sync/smoke-backup")
def smoke_backup() -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="Supabase backup is disabled after MongoDB migration")
    backup = get_backup_client()
    if not backup:
        return {"ok": False, "configured": False, "error": "supabase backup is not configured"}
    return backup.smoke_test()


@app.post("/api/snapshots/ingest")
def ingest_snapshot(
    request: SnapshotIngestRequest,
    db: Session | None = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
) -> dict[str, Any]:
    try:
        dataset, records, frames, stock_rows, sector_rows, idempotency_key = normalize_snapshot_ingest(request)
        result = create_repository(db).save_snapshot_ingest(
            dataset,
            records,
            frames,
            stock_rows,
            sector_rows,
            idempotency_key=idempotency_key,
            trading_date=request.trading_date,
            source=request.source,
        )
        _invalidate_snapshot_cache_after_ingest(
            dataset_id=dataset.id,
            records=records,
            frames=frames,
            stock_rows=stock_rows,
            sector_rows=sector_rows,
        )
        # G4-3（2026-08-23 前后端分离，用户授权追加）：ingest 后后台对快照帧全量 analyze 并
        # 持久化 observation/displayStatus（稳定回放口径，不阻塞 ingest 响应）。仅 MongoDB 生产态。
        _schedule_snapshot_analysis(background_tasks, dataset.id, frames, db)
        return {"ok": True, **result}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _schedule_snapshot_analysis(
    background_tasks: BackgroundTasks,
    dataset_id: str,
    frames: list[dict[str, Any]],
    db: Session | None,
) -> None:
    """G4-3：ingest 后后台触发 analyze 入库。仅 MongoDB 生产态；失败静默（不吞数据/不阻塞 ingest）。"""
    try:
        if storage_source_label() != "mongodb":
            return
        if not frames:
            return
        task_repo = create_repository(db)
    except Exception:
        return
    for frame in frames:
        snapshot_id = str(frame.get("snapshotId") or frame.get("id") or "")
        if not snapshot_id:
            continue
        # 每帧用自身 snapshot_type（同批混型时不共用 frames[0] 口径）
        snapshot_type = str(frame.get("type") or "half_hour")
        try:
            background_tasks.add_task(
                analyze_snapshot_and_persist,
                task_repo,
                dataset_id,
                snapshot_id,
                snapshot_type,
                frame,
            )
        except Exception:
            continue


@app.get("/api/snapshots/analysis")
def get_snapshot_analysis(
    dataset_id: str = Query(...),
    snapshot_id: str = Query(...),
    codes: str | None = Query(None),
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    """G4-4（2026-08-23）：读快照的 analyze 持久化结果（observation/displayStatus/meta/resonance）。
    仅 MongoDB 生产态有效；代码列表按逗号分隔，缺省返回该快照全部。"""
    try:
        if storage_source_label() != "mongodb":
            return {"ok": False, "degraded": True, "errorCode": "mongodb_required", "analysis": {}}
        repo = create_repository(db)
        code_list = _parse_csv(codes) or None
        result = repo.load_snapshot_analysis(dataset_id, snapshot_id, code_list)
        return {"ok": True, "dataset_id": dataset_id, "snapshot_id": snapshot_id, "analysis": result}
    except Exception as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def _parse_csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _assert_snapshot_sort(sort: str) -> None:
    if sort not in {"asc", "desc"}:
        raise HTTPException(status_code=400, detail=f"unsupported sort: {sort}")


DEFAULT_SNAPSHOT_DATASET_ID = "dragonboard_live"


def _dataset_has_snapshot_facts(dataset: Dataset | None) -> bool:
    if not dataset:
        return False
    return any(
        int(value or 0) > 0
        for value in (
            dataset.frame_count,
            dataset.snapshot_count,
            dataset.stock_row_count,
            dataset.sector_row_count,
        )
    )


def _latest_snapshot_dataset(repo: Repository) -> Dataset | None:
    candidates = [item for item in repo.list_datasets() if _dataset_has_snapshot_facts(item)]
    return candidates[0] if candidates else None


def _resolve_snapshot_dataset(
    repo: Repository,
    dataset_id: str | None,
    *,
    allow_default_fallback: bool = False,
) -> tuple[str, Dataset]:
    requested_dataset_id = dataset_id.strip() if isinstance(dataset_id, str) and dataset_id.strip() else None
    resolved_dataset_id = requested_dataset_id or DEFAULT_SNAPSHOT_DATASET_ID
    dataset = repo.get_dataset(resolved_dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail=f"dataset not found: {resolved_dataset_id}")
    if not _dataset_has_snapshot_facts(dataset):
        raise HTTPException(status_code=404, detail=f"dataset has no snapshot facts: {resolved_dataset_id}")
    return resolved_dataset_id, dataset


def _snapshot_cache_builder() -> snapshot_cache.SnapshotCacheKeyBuilder:
    return snapshot_cache.SnapshotCacheKeyBuilder(prefix=get_settings().redis_key_prefix)


def _invalidate_theme_caches() -> None:
    """刷新题材映射/热度后清除对应的 Redis 缓存索引键。"""
    cache = snapshot_cache.get_snapshot_redis_cache()
    prefix = get_settings().redis_key_prefix
    index_keys = snapshot_cache.build_snapshot_cache_index_keys(
        prefix=prefix,
        dataset_id="themes",
    )
    cache.invalidate_indexes(index_keys)


def _cached_snapshot_response(
    resource: str,
    *,
    resolved_dataset_id: str,
    params: dict[str, Any],
    snapshot_type: str | None = None,
    trading_date: str | None = None,
    snapshot_ids: list[str] | None = None,
    loader,
) -> dict[str, Any]:
    started_at = perf_counter()
    cache = snapshot_cache.get_snapshot_redis_cache()
    generation_key = snapshot_cache.build_snapshot_cache_generation_key(
        prefix=get_settings().redis_key_prefix,
        dataset_id=resolved_dataset_id,
    )
    generation = cache.get_generation(generation_key)
    cache_key = _snapshot_cache_builder().response_key(
        resource,
        resolved_dataset_id=resolved_dataset_id,
        params={**params, "_generation": generation},
    )
    cached = cache.get_response(cache_key)
    if cached is not None:
        logger.info(
            "snapshot_response resource=%s cache_hit=true elapsed_ms=%d",
            resource,
            round((perf_counter() - started_at) * 1000),
        )
        return cached

    response = loader()
    response = {**response, "cache": {"hit": False, "store": storage_source_label()}}
    if cache.get_generation(generation_key) == generation:
        cache.set_response(cache_key, response)
        cache.register_dependencies(
            cache_key,
            snapshot_cache.build_snapshot_cache_index_keys(
                prefix=get_settings().redis_key_prefix,
                dataset_id=resolved_dataset_id,
                snapshot_type=snapshot_type,
                trading_date=trading_date,
                snapshot_ids=snapshot_ids or [],
            ),
        )
    logger.info(
        "snapshot_response resource=%s cache_hit=false elapsed_ms=%d",
        resource,
        round((perf_counter() - started_at) * 1000),
    )
    return response


def _invalidate_snapshot_cache_after_ingest(
    *,
    dataset_id: str,
    records: list[Any],
    frames: list[Any],
    stock_rows: list[Any],
    sector_rows: list[Any],
) -> None:
    snapshot_cache.invalidate_snapshot_cache_after_ingest(
        dataset_id=dataset_id,
        records=records,
        frames=frames,
        stock_rows=stock_rows,
        sector_rows=sector_rows,
    )


@app.get("/api/snapshots/frames")
def list_snapshot_frames(
    dataset_id: str | None = None,
    snapshot_type: str = "half_hour",
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    sort: str = "asc",
    limit: int | None = 100,
    projection: str = "full",
    fields: str | None = None,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    if snapshot_type not in {"quarter_hour", "half_hour", "hourly", "daily"}:
        raise HTTPException(status_code=400, detail=f"unsupported snapshot_type: {snapshot_type}")
    if limit is not None and limit <= 0:
        limit = None
    if projection not in {"full", "ranktrend"}:
        raise HTTPException(status_code=400, detail=f"unsupported projection: {projection}")
    _assert_snapshot_sort(sort)
    start = trading_date or start_date
    end = trading_date or end_date
    capture_modes = _parse_csv(allowed_capture_modes)
    field_list = _parse_csv(fields)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
        frames = repo.load_frame_bundles(
            resolved_dataset_id,
            snapshot_type=snapshot_type,
            start_date=start,
            end_date=end,
            before_trading_date=before_trading_date,
            allowed_capture_modes=capture_modes,
            exclude_restored=exclude_restored,
            limit=limit,
            sort=sort,
            projection=projection,
            fields=field_list or None,
        )
        from backend.analysis.ranktrend.engine import market_regime

        for frame in frames:
            frame["regime"] = market_regime({
                "stocks": frame.get("rows") or frame.get("stocks") or [],
                "marketContext": {
                    "sentiment": frame.get("sentiment"),
                    "marketStats": frame.get("marketStats"),
                },
            })
        snapshot_ids.extend(str(frame.get("snapshotId") or "") for frame in frames if frame.get("snapshotId"))
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "snapshotType": snapshot_type,
            "frames": frames,
            "count": len(frames),
            "source": storage_source_label(),
        }

    return _cached_snapshot_response(
        "frames",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_type": snapshot_type,
            "start_date": start,
            "end_date": end,
            "before_trading_date": before_trading_date,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "sort": sort,
            "limit": limit,
            "projection": projection,
            "fields": fields,
        },
        snapshot_type=snapshot_type,
        trading_date=start if start == end else None,
        snapshot_ids=snapshot_ids,
        loader=load_response,
    )


@app.get("/api/ranktrend/rank-series")
def get_ranktrend_rank_series(
    dataset_id: str | None = None,
    snapshot_type: str = "half_hour",
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    codes: str | None = None,
    sort: str = "asc",
    limit: int | None = 50,
    window_bars: int | None = None,
    rank_basis: str = "composite",
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    if snapshot_type not in {"quarter_hour", "half_hour", "hourly", "daily"}:
        raise HTTPException(status_code=400, detail=f"unsupported snapshot_type: {snapshot_type}")
    if rank_basis not in {"composite", "attention"}:
        raise HTTPException(status_code=400, detail=f"unsupported rank_basis: {rank_basis}")
    if rank_basis == "attention" and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="attention rank series requires mongodb")
    code_list = list(dict.fromkeys(_parse_csv(codes)))
    if not code_list:
        raise HTTPException(status_code=400, detail="codes is required for rank-series queries")
    _assert_snapshot_sort(sort)
    start = trading_date or start_date
    end = trading_date or end_date
    capture_modes = _parse_csv(allowed_capture_modes)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
        result = repo.load_rank_series(
            resolved_dataset_id,
            snapshot_type=snapshot_type,
            start_date=start,
            end_date=end,
            before_trading_date=before_trading_date,
            allowed_capture_modes=capture_modes,
            exclude_restored=exclude_restored,
            codes=code_list,
            limit=limit,
            sort=sort,
            window_bars=window_bars,
            rank_basis=rank_basis,
        )
        frames = result["frames"]
        market_frames = result.get("marketFrames", [])
        series = result["series"]
        snapshot_ids.extend(
            str(frame.get("snapshotId") or "")
            for frame in [*frames, *market_frames]
            if frame.get("snapshotId")
        )
        public_frames = [
            {key: value for key, value in frame.items() if key != "bars"}
            for frame in frames
        ]
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "snapshotType": snapshot_type,
            "rankBasis": rank_basis,
            "frames": public_frames,
            "marketFrames": market_frames,
            "series": series,
            "count": len(public_frames),
            "source": storage_source_label(),
        }

    return _cached_snapshot_response(
        "ranktrend:rank-series",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_type": snapshot_type,
            "start_date": start,
            "end_date": end,
            "before_trading_date": before_trading_date,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "codes": ",".join(code_list),
            "sort": sort,
            "limit": limit,
            "window_bars": window_bars,
            "rank_basis": rank_basis,
        },
        snapshot_type=snapshot_type,
        trading_date=start if start == end else None,
        snapshot_ids=snapshot_ids,
        loader=load_response,
    )


@app.get("/api/snapshots/records")
def list_snapshot_records(
    dataset_id: str | None = None,
    snapshot_type: str | None = None,
    types: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    sort: str = "desc",
    limit: int | None = 500,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    _assert_snapshot_sort(sort)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
        records = repo.list_snapshot_records(
            resolved_dataset_id,
            snapshot_type=snapshot_type,
            snapshot_types=_parse_csv(types),
            trading_date=trading_date,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            allowed_capture_modes=_parse_csv(allowed_capture_modes),
            exclude_restored=exclude_restored,
            limit=limit,
            sort=sort,
        )
        snapshot_ids.extend(str(record.get("id") or "") for record in records if record.get("id"))
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "records": records,
            "count": len(records),
            "source": storage_source_label(),
        }

    return _cached_snapshot_response(
        "records",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_type": snapshot_type,
            "types": types,
            "trading_date": trading_date,
            "start_date": start_date,
            "end_date": end_date,
            "before_trading_date": before_trading_date,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "sort": sort,
            "limit": limit,
        },
        snapshot_type=snapshot_type,
        trading_date=trading_date,
        snapshot_ids=snapshot_ids,
        loader=load_response,
    )


@app.get("/api/snapshots/records/{snapshot_id}")
def get_snapshot_record(
    snapshot_id: str,
    dataset_id: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id = dataset_id
    dataset: Dataset | None = None
    if dataset_id:
        resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    record = repo.get_snapshot_record(
        snapshot_id,
        dataset_id=resolved_dataset_id,
        allowed_capture_modes=_parse_csv(allowed_capture_modes),
        exclude_restored=exclude_restored,
    )
    if not record:
        raise HTTPException(status_code=404, detail=f"snapshot not found: {snapshot_id}")
    if dataset is None:
        resolved_dataset_id = "dragonboard_live"
        dataset = repo.get_dataset(resolved_dataset_id)
        if not dataset:
            resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, None)
    return {
        "ok": True,
        "dataset": repo.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "record": record,
        "source": storage_source_label(),
    }


@app.get("/api/snapshots/stock-rows")
def list_snapshot_stock_rows(
    dataset_id: str | None = None,
    snapshot_id: str | None = None,
    snapshot_type: str | None = None,
    types: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    code: str | None = None,
    codes: str | None = None,
    slot_time: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    sort: str = "desc",
    limit: int | None = 500,
    fields: str | None = None,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    _assert_snapshot_sort(sort)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    row_snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
        result = repo.list_snapshot_stock_rows(
            resolved_dataset_id,
            snapshot_id=snapshot_id,
            snapshot_type=snapshot_type,
            snapshot_types=_parse_csv(types),
            trading_date=trading_date,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            code=code,
            codes=_parse_csv(codes),
            slot_time=slot_time,
            allowed_capture_modes=_parse_csv(allowed_capture_modes),
            exclude_restored=exclude_restored,
            limit=limit,
            sort=sort,
            fields=_parse_csv(fields),
        )
        row_snapshot_ids.extend(str(row.get("snapshotId") or "") for row in result["rows"] if row.get("snapshotId"))
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "rows": result["rows"],
            "count": len(result["rows"]),
            "source": result["source"],
        }

    return _cached_snapshot_response(
        "stock_rows",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_id": snapshot_id,
            "snapshot_type": snapshot_type,
            "types": types,
            "trading_date": trading_date,
            "start_date": start_date,
            "end_date": end_date,
            "before_trading_date": before_trading_date,
            "code": code,
            "codes": codes,
            "slot_time": slot_time,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "sort": sort,
            "limit": limit,
            "fields": fields,
        },
        snapshot_type=snapshot_type,
        trading_date=trading_date,
        snapshot_ids=[snapshot_id] if snapshot_id else row_snapshot_ids,
        loader=load_response,
    )


@app.get("/api/snapshots/sector-rows")
def list_snapshot_sector_rows(
    dataset_id: str | None = None,
    snapshot_id: str | None = None,
    snapshot_type: str | None = None,
    types: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    trading_date: str | None = None,
    before_trading_date: str | None = None,
    entity_type: str | None = None,
    entity_types: str | None = None,
    entity_key: str | None = None,
    entity_keys: str | None = None,
    allowed_capture_modes: str | None = None,
    exclude_restored: bool = False,
    sort: str = "desc",
    limit: int | None = 100,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    _assert_snapshot_sort(sort)
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    row_snapshot_ids: list[str] = []

    def load_response() -> dict[str, Any]:
        result = repo.list_snapshot_sector_rows(
            resolved_dataset_id,
            snapshot_id=snapshot_id,
            snapshot_type=snapshot_type,
            snapshot_types=_parse_csv(types),
            trading_date=trading_date,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            entity_type=entity_type,
            entity_types=_parse_csv(entity_types),
            entity_key=entity_key,
            entity_keys=_parse_csv(entity_keys),
            allowed_capture_modes=_parse_csv(allowed_capture_modes),
            exclude_restored=exclude_restored,
            limit=limit,
            sort=sort,
        )
        row_snapshot_ids.extend(str(row.get("snapshotId") or "") for row in result["rows"] if row.get("snapshotId"))
        return {
            "ok": True,
            "dataset": repo.dataset_to_dict(dataset),
            "datasetId": resolved_dataset_id,
            "rows": result["rows"],
            "count": len(result["rows"]),
            "source": result["source"],
        }

    return _cached_snapshot_response(
        "sector_rows",
        resolved_dataset_id=resolved_dataset_id,
        params={
            "snapshot_id": snapshot_id,
            "snapshot_type": snapshot_type,
            "types": types,
            "trading_date": trading_date,
            "start_date": start_date,
            "end_date": end_date,
            "before_trading_date": before_trading_date,
            "entity_type": entity_type,
            "entity_types": entity_types,
            "entity_key": entity_key,
            "entity_keys": entity_keys,
            "allowed_capture_modes": allowed_capture_modes,
            "exclude_restored": exclude_restored,
            "sort": sort,
            "limit": limit,
        },
        snapshot_type=snapshot_type,
        trading_date=trading_date,
        snapshot_ids=[snapshot_id] if snapshot_id else row_snapshot_ids,
        loader=load_response,
    )


@app.get("/api/snapshots/counts")
def get_snapshot_counts(
    dataset_id: str | None = None,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    repo = create_repository(db, enable_backup=False)
    resolved_dataset_id, dataset = _resolve_snapshot_dataset(repo, dataset_id)
    counts = repo.snapshot_table_counts(resolved_dataset_id)
    return {
        "ok": True,
        "dataset": repo.dataset_to_dict(dataset),
        "datasetId": resolved_dataset_id,
        "counts": counts,
        "source": storage_source_label(),
    }


@app.post("/api/storage/archive/snapshots/preview")
def preview_snapshot_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).archive_snapshots(
        dataset_id=str(payload.get("datasetId") or payload.get("dataset_id") or "dragonboard_live"),
        snapshot_type=str(payload.get("snapshotType") or payload.get("snapshot_type") or "half_hour"),
        before_trading_date=str(payload.get("beforeTradingDate") or payload.get("before_trading_date") or ""),
        dry_run=True,
        max_partitions=payload.get("maxPartitions") or payload.get("max_partitions"),
    )


@app.post("/api/storage/archive/snapshots")
def archive_snapshots(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).archive_snapshots(
        dataset_id=str(payload.get("datasetId") or payload.get("dataset_id") or "dragonboard_live"),
        snapshot_type=str(payload.get("snapshotType") or payload.get("snapshot_type") or "half_hour"),
        before_trading_date=str(payload.get("beforeTradingDate") or payload.get("before_trading_date") or ""),
        apply=True,
        max_partitions=payload.get("maxPartitions") or payload.get("max_partitions"),
    )


@app.post("/api/storage/archive/research/preview")
def preview_research_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    with ResearchSessionLocal() as research_session:
        return ArchiveService(db, research_session=research_session).archive_research(
            run_id=payload.get("runId") or payload.get("run_id"),
            older_than_days=int(payload.get("olderThanDays") or payload.get("older_than_days") or 30),
            keep_latest_per_group=int(payload.get("keepLatestPerGroup") or payload.get("keep_latest_per_group") or 10),
            dry_run=True,
        )


@app.post("/api/storage/archive/research")
def archive_research(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    with ResearchSessionLocal() as research_session:
        return ArchiveService(db, research_session=research_session).archive_research(
            run_id=payload.get("runId") or payload.get("run_id"),
            older_than_days=int(payload.get("olderThanDays") or payload.get("older_than_days") or 30),
            keep_latest_per_group=int(payload.get("keepLatestPerGroup") or payload.get("keep_latest_per_group") or 10),
            apply=True,
        )


@app.get("/api/storage/archive/manifests")
def list_archive_manifests(scope: str | None = None, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    manifests = ArchiveService(db).list_manifests(scope=scope)
    return {"ok": True, "manifests": manifests, "count": len(manifests)}


@app.post("/api/storage/archive/verify")
def verify_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    archive_id = str(payload.get("archiveId") or payload.get("archive_id") or "")
    return ArchiveService(db).verify_archive(archive_id)


@app.post("/api/storage/archive/restore")
def restore_archive(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).restore_archive(
        str(payload.get("archiveId") or payload.get("archive_id") or ""),
        dry_run=bool(payload.get("dryRun") or payload.get("dry_run")),
        apply=bool(payload.get("apply")),
    )


@app.post("/api/storage/archive/smoke-object-backup")
def smoke_object_backup() -> dict[str, Any]:
    store = get_object_backup_store()
    if not store:
        return {"ok": False, "configured": False, "error": "object backup bucket is not configured"}
    return store.smoke_test()


@app.post("/api/storage/archive/push-backup")
def push_archive_backup(limit: int | None = None, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).push_archive_backup(limit=limit)


@app.post("/api/storage/archive/pull-backup")
def pull_archive_backup(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    _reject_sqlite_archive_for_mongodb()
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    return ArchiveService(db).pull_archive_backup(
        str(payload.get("archiveId") or payload.get("archive_id") or ""),
        dry_run=bool(payload.get("dryRun") or payload.get("dry_run")),
        apply=bool(payload.get("apply")),
    )


@app.post("/api/migrations/snapshots/import-json")
def import_snapshot_json_migration(
    request: SnapshotJsonMigrationRequest,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    if storage_source_label() == "mongodb":
        raise HTTPException(status_code=410, detail="SQLite snapshot JSON migration endpoint is disabled after MongoDB migration")
    if db is None:
        raise HTTPException(status_code=503, detail="primary database is unavailable")
    try:
        return SnapshotMigrationService(db).import_json(request.model_dump(by_alias=True))
    except (ImporterError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/migrations/themes/import-json")
def import_theme_json_migration(
    payload: dict[str, Any],
    db: Session | None = Depends(get_theme_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    try:
        return ThemeMigrationService(db).import_mapping(payload)
    except ThemeMigrationError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error


@app.post("/api/migrations/themes/verify-json")
def verify_theme_json_migration(
    payload: dict[str, Any],
    db: Session | None = Depends(get_theme_db),
) -> dict[str, Any]:
    if db is None and storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="theme database is unavailable")
    try:
        return ThemeMigrationService(db).verify_mapping(payload)
    except ThemeMigrationError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error


@app.get("/api/themes/mapping")
def get_theme_mapping(db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    mapping = get_theme_repository(db).get_mapping()
    return {"ok": True, "mapping": mapping, "source": storage_source_label()}


@app.get("/api/themes/stocks/{theme_id}")
def get_theme_stocks(theme_id: str, db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    return get_theme_repository(db).get_theme_stocks(theme_id)


@app.get("/api/themes/stocks/by-code/{code}")
def get_stock_themes(code: str, db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    return get_theme_repository(db).get_stock_themes(code)


@app.get("/api/themes/counts")
def get_theme_counts(db: Session | None = Depends(get_theme_db)) -> dict[str, Any]:
    return {"ok": True, "counts": get_theme_repository(db).counts(), "source": storage_source_label()}


@app.post("/api/themes/refresh-mappings")
def refresh_theme_mappings() -> dict[str, Any]:
    """从 longhuvip 题材 API 刷新 MongoDB theme_stock_mappings 集合。

    数据链：longhuvip.com Theme API → MongoDB themes 表 → theme_stock_mappings。
    仅在 storage_backend=mongodb 时可用。
    """
    if storage_source_label() != "mongodb":
        raise HTTPException(status_code=503, detail="theme mapping refresh requires MongoDB storage backend")
    try:
        result = refresh_theme_stock_mappings()
        if not result.get("ok"):
            raise HTTPException(status_code=500, detail=result)
        # 刷新成功后清除 themes 相关 Redis 缓存，避免 GET 端点返回旧数据
        _invalidate_theme_caches()
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/datasets")
def list_datasets(db: Session | None = Depends(get_db)) -> list[dict[str, Any]]:
    try:
        return DatasetService(db).list_datasets()
    except Exception as error:
        if storage_source_label() == "mongodb":
            raise HTTPException(
                status_code=503,
                detail=f"MongoDB primary is unavailable: {error}",
            ) from error
        raise


@app.get("/api/datasets/{dataset_id}")
def get_dataset(dataset_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        dataset = DatasetService(db).get_dataset(dataset_id)
    except Exception as error:
        if storage_source_label() == "mongodb":
            raise HTTPException(
                status_code=503,
                detail=f"MongoDB primary is unavailable: {error}",
            ) from error
        raise
    if not dataset:
        raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
    return dataset


@app.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    if storage_source_label() != "mongodb":
        raise HTTPException(status_code=410, detail="dataset deletion is only available in MongoDB mode")
    try:
        result = DatasetService(db).delete_dataset(dataset_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        if storage_source_label() == "mongodb":
            raise HTTPException(
                status_code=503,
                detail=f"MongoDB primary is unavailable: {error}",
            ) from error
        raise
    if not result:
        raise HTTPException(status_code=404, detail=f"dataset not found: {dataset_id}")
    return result


@app.post("/api/datasets/upload")
async def upload_dataset(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    content = payload.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    try:
        settings = get_settings()
        safe_name = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in str(payload.get("filename") or "upload.json"))
        path = settings.staging_dir / f"upload_{safe_name}"
        from backend.core.utils import write_json_file

        write_json_file(path, content)
        request = ImportDatasetRequest(
            source_type="json_bundle",
            source_path=str(path),
            name=payload.get("name") or safe_name,
            snapshot_types=payload.get("snapshotTypes") or ["half_hour"],
            dry_run=bool(payload.get("dryRun")),
        )
        return DatasetService(db).import_dataset(request)
    except (ImporterError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def normalize_import_payload(payload: dict[str, Any]) -> ImportDatasetRequest:
    if "sourceType" in payload:
        source_type = payload.get("sourceType")
        if source_type == "sqlite":
            payload = {**payload, "sourceType": "sqlite_snapshots"}
        if payload.get("sourceType") == "indexeddb":
            raise ImporterError(
                "sourceType=indexeddb is removed; use leveldb or json_bundle for explicit historical migration"
            )
        if source_type == "json":
            return ImportDatasetRequest(
                source_type="json_bundle",
                source_path=payload.get("sourcePath") or payload.get("path"),
                name=payload.get("name"),
                snapshot_types=payload.get("snapshotTypes") or ["half_hour"],
                dry_run=bool(payload.get("dryRun")),
            )
    return ImportDatasetRequest(**payload)


def _write_inline_import_bundle(name: str, records: list[Any], preview: dict[str, Any]) -> str:
    from backend.core.utils import write_json_file

    settings = get_settings()
    path = settings.staging_dir / f"inline_{name.replace(' ', '_')}.json"
    normalized = []
    for index, record in enumerate(records):
        if isinstance(record, dict):
            value = record.get("value") if isinstance(record.get("value"), dict) else record
            normalized.append(value)
    write_json_file(path, {"metadata": {"preview": preview, "source": "frontend_inline"}, "records": normalized})
    return str(path)


@app.post("/api/datasets/import")
def import_dataset(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        request = normalize_import_payload(payload)
        dataset = DatasetService(db).import_dataset(request)
        return dataset
    except (ImporterError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/backtests/rank-trend")
def run_ranktrend_backtest(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).run_ranktrend(payload)
    except ValueError as error:
        raise _structured_bad_request(error) from error
    except Exception as error:
        raise _structured_backtest_error("rank_trend_backtest_failed", error) from error


@app.post("/api/backtests/theme-trend")
def run_theme_trend_backtest(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).run_theme_trend(payload)
    except ValueError as error:
        raise _structured_bad_request(error) from error
    except Exception as error:
        raise _structured_backtest_error("theme_trend_backtest_failed", error) from error


@app.post("/api/backtests/theme-confluence")
def run_theme_confluence_backtest(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).run_theme_confluence(payload)
    except ValueError as error:
        raise _structured_bad_request(error) from error
    except Exception as error:
        raise _structured_backtest_error("theme_confluence_backtest_failed", error) from error


def _backtest_not_found(run_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": "backtest_run_not_found", "runId": run_id})


def _structured_bad_request(error: ValueError) -> HTTPException:
    detail = error.args[0] if error.args and isinstance(error.args[0], dict) else str(error)
    return HTTPException(status_code=400, detail=detail)


def _structured_backtest_error(code: str, error: Exception) -> HTTPException:
    return HTTPException(
        status_code=500,
        detail={
            "code": code,
            "message": str(error) or error.__class__.__name__,
            "errorType": error.__class__.__name__,
            "storage": storage_source_label(),
        },
    )


@app.post("/api/backtests/compare")
def compare_backtests(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    run_ids = payload.get("run_ids") or payload.get("runIds") or []
    if not isinstance(run_ids, list) or not run_ids:
        raise HTTPException(status_code=400, detail={"code": "invalid_backtest_compare_request", "field": "run_ids"})
    metrics = payload.get("metrics")
    if metrics is not None and not isinstance(metrics, list):
        raise HTTPException(status_code=400, detail={"code": "invalid_backtest_compare_request", "field": "metrics"})
    try:
        return BacktestService(db).compare_runs([str(item) for item in run_ids], [str(item) for item in metrics] if metrics else None)
    except LookupError as error:
        raise _backtest_not_found(str(error.args[0])) from error
    except ValueError as error:
        raise _structured_bad_request(error) from error


@app.get("/api/backtests/{run_id}/trades")
def get_backtest_trades(
    run_id: str,
    limit: int = 100,
    offset: int = 0,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = BacktestService(db).get_trades(run_id, limit=limit, offset=offset)
    except ValueError as error:
        raise _structured_bad_request(error) from error
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/{run_id}/equity")
def get_backtest_equity(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = BacktestService(db).get_equity(run_id)
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/{run_id}/signals")
def get_backtest_signals(
    run_id: str,
    tier: str | None = None,
    regime: str | None = None,
    limit: int = 200,
    offset: int = 0,
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = BacktestService(db).get_signals(run_id, limit=limit, offset=offset, tier=tier, regime=regime)
    except ValueError as error:
        raise _structured_bad_request(error) from error
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/{run_id}/quality")
def get_backtest_quality(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = BacktestService(db).get_quality(run_id)
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.delete("/api/backtests/{run_id}")
def delete_backtest(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = BacktestService(db).delete_run(run_id)
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/alignment")
def get_alignment(
    checkpoint_id: str | None = Query(None),
    run_ids: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> dict[str, Any]:
    """Cross-reference trade_journal execution records with backtest signals.

    Accepts either checkpoint_id (reads run_ids from JSONL) or run_ids (comma-separated).
    """
    repo = create_repository(None)

    if run_ids:
        checkpoint_run_ids = [rid.strip() for rid in run_ids.split(",") if rid.strip()]
    elif checkpoint_id:
        jsonl_path = get_settings().reports_dir / "long_test_runs.jsonl"
        checkpoint_run_ids: list[str] = []
        if jsonl_path.exists():
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json_loads(line.strip())
                        if record and record.get("checkpointId") == checkpoint_id:
                            for baseline in (record.get("baselines") or []):
                                rid = baseline.get("runId") or baseline.get("id")
                                if rid:
                                    checkpoint_run_ids.append(rid)
                            break
                    except Exception:
                        continue
    else:
        checkpoint_run_ids = []

    alignment = compute_alignment(
        repo=repo,
        run_ids=checkpoint_run_ids,
        start_date=start_date,
        end_date=end_date,
    )
    return {"checkpointId": checkpoint_id, **alignment}


@app.get("/api/backtests/checkpoints")
def get_checkpoints(limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
    """Return recent long-test checkpoint summaries from JSONL."""
    jsonl_path = get_settings().reports_dir / "long_test_runs.jsonl"
    if not jsonl_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json_loads(line.strip())
                if not record or not record.get("checkpointId"):
                    continue
            except Exception:
                continue
            baselines = record.get("baselines") or []
            slots = select_longtest_baseline_slots(baselines)
            h1 = slots.get("h1") or {}
            h2 = slots.get("h2") or {}
            q1 = slots.get("q1") or {}
            l1 = slots.get("l1") or {}
            signal_pool_l1 = l1.get("layer1SignalEfficacy") or {}
            execution_l1 = h1.get("executionLayer1Efficacy") or {}
            layer2 = compute_checkpoint_layer2(baselines) or {}
            cp = record.get("crossPeriod") or {}
            signal_pool_meltdown = cp.get("layer1MeltdownSignalPool") or cp.get("layer1MeltdownH1") or {}
            execution_meltdown = cp.get("layer1MeltdownV5Execution") or {}
            records.append({
                "checkpointId": record.get("checkpointId"),
                "createdAt": record.get("createdAt"),
                "e1Label": summarize_longtest_slot_label(l1),
                "e1SignalCount": signal_pool_l1.get("totalSignals"),
                "e1ABTierCount": signal_pool_l1.get("aPlusBTierCount"),
                "e1TierRatio": signal_pool_l1.get("tierRatio"),
                "h1Label": summarize_longtest_slot_label(h1),
                "h2Label": summarize_longtest_slot_label(h2),
                "q1Label": summarize_longtest_slot_label(q1),
                "h1TotalReturn": h1.get("totalReturn"),
                "h1Sharpe": h1.get("sharpe"),
                "h1Trades": h1.get("tradeCount"),
                "h2TotalReturn": h2.get("totalReturn"),
                "h2Sharpe": h2.get("sharpe"),
                "q1TotalReturn": q1.get("totalReturn"),
                "q1Sharpe": q1.get("sharpe"),
                "h1Layer1Status": signal_pool_l1.get("layer1Status"),
                "h1DirectionAccuracy": signal_pool_l1.get("directionAccuracy"),
                "signalPoolLayer1Label": summarize_longtest_slot_label(l1),
                "signalPoolLayer1Status": signal_pool_l1.get("layer1Status"),
                "signalPoolDirectionAccuracy": signal_pool_l1.get("directionAccuracy"),
                "executionLayer1Label": summarize_longtest_slot_label(h1),
                "executionLayer1Status": execution_l1.get("layer1Status"),
                "executionDirectionAccuracy": execution_l1.get("directionAccuracy"),
                "executionEntryCount": execution_l1.get("entryEventCount") or execution_l1.get("totalSignals"),
                "executionABTierCount": execution_l1.get("aPlusBTierCount"),
                "h1Layer2Status": layer2.get("layer2Status"),
                "h1Layer2Bias": layer2.get("bias"),
                "meltdown": signal_pool_meltdown.get("meltdown"),
                "consecutiveRedPeriods": signal_pool_meltdown.get("consecutiveRedPeriods"),
                "meltdownLabel": signal_pool_meltdown.get("selectedLabel"),
                "meltdownMetricKey": signal_pool_meltdown.get("metricKey"),
                "executionMeltdown": execution_meltdown.get("meltdown"),
                "executionConsecutiveRedPeriods": execution_meltdown.get("consecutiveRedPeriods"),
                "l3GreenLight": (cp.get("layer3Trend") or {}).get("greenLight"),
            })
    return records[-limit:] if len(records) > limit else records


@app.get("/api/backtests")
def list_backtests(limit: int = Query(50, ge=1, le=200), db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return BacktestService(db).list_runs(limit=limit)


@app.get("/api/backtests/{run_id}")
def get_backtest(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = BacktestService(db).get_run(run_id)
    if not result:
        raise _backtest_not_found(run_id)
    return result


@app.get("/api/backtests/{run_id}/report")
def get_backtest_report(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return get_backtest(run_id, db)


@app.get("/api/storage/research-summary")
def get_research_storage_summary(db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return BacktestService(db).research_storage_summary()


@app.post("/api/storage/research-cleanup-preview")
def preview_research_cleanup(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).cleanup_research(payload, apply=False)
    except ValueError as error:
        raise _structured_bad_request(error) from error


@app.post("/api/storage/research-cleanup")
def cleanup_research(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return BacktestService(db).cleanup_research(payload, apply=True)
    except ValueError as error:
        raise _structured_bad_request(error) from error


@app.post("/api/optimizations/rank-trend")
def run_ranktrend_optimization(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return OptimizationService(db).run_ranktrend(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/optimizations/theme-trend")
def run_theme_trend_optimization(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return OptimizationService(db).run_theme_trend(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/optimizations/theme-confluence")
def run_theme_confluence_optimization(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return OptimizationService(db).run_theme_confluence(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/research/ranktrend-jump")
def run_ranktrend_jump_research(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return OptimizationService(db).run_ranktrend_jump_research(payload)
    except ValueError as error:
        raise _structured_bad_request(error) from error


@app.get("/api/optimizations/{run_id}")
def get_optimization(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    result = OptimizationService(db).get_run(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"optimization run not found: {run_id}")
    return result


@app.get("/api/research/theme-summary")
def get_theme_research_summary(
    dataset_id: str = "dragonboard_live",
    snapshot_type: str = "half_hour",
    db: Session | None = Depends(get_db),
) -> dict[str, Any]:
    """Dragon Board 消费的题材研究摘要。QuantBoard 后端不可用时前端显示"不可用"。"""
    try:
        repo = create_repository(db)
        frames = repo.load_frame_bundles(dataset_id, snapshot_type=snapshot_type, limit=200)
        if not frames or len(frames) < 2:
            return {"available": False, "reason": "insufficient_frames", "frameCount": len(frames) if frames else 0}

        # 函数内导入避免与 FastAPI startup 事件中的 DB 初始化形成循环依赖
        from backend.analysis.theme.trend import ThemeTrendPythonEngine
        result = ThemeTrendPythonEngine().replay_sequence(frames)
        factors = result.get("factors") or []
        quality = result.get("qualityReport") or {}

        lifecycle_dist: dict[str, int] = {}
        for f in factors:
            lc = str(f.get("lifecycle") or "neutral")
            lifecycle_dist[lc] = lifecycle_dist.get(lc, 0) + 1

        mainline_themes = [
            {"themeId": f.get("themeId"), "themeName": f.get("themeName"), "heatScore": f.get("heatScore")}
            for f in factors
            if f.get("lifecycle") == "mainline"
        ][:10]

        crowding_themes = [
            {"themeId": f.get("themeId"), "themeName": f.get("themeName"), "crowdingRisk": f.get("crowdingRisk")}
            for f in factors
            if f.get("lifecycle") == "crowded"
        ][:5]

        return {
            "available": True,
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "frameCount": len(frames),
            "lastTradingDate": str(frames[-1].get("tradingDate") or ""),
            "lifecycleDistribution": lifecycle_dist,
            "mainlineThemes": mainline_themes,
            "crowdingAlerts": crowding_themes,
            "qualityPassed": not quality.get("blocked", False),
            "researchGrade": "degraded" if quality.get("warnings") else "research_ready",
            "themeCount": len({f.get("themeId") for f in factors if f.get("themeId")}),
            "signalCount": len(factors),
        }
    except Exception as exc:
        return {"available": False, "reason": f"backend_error: {str(exc)[:200]}"}


@app.get("/api/reports/theme-trend/{run_id}")
def get_theme_trend_report(run_id: str, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    """主题研究报告：同时查询 optimization_runs 和 backtest_runs。

    bt_* 前缀的回测 ID 从 backtest_runs.result_json 提取 themeTrend 段；
    opt_* 前缀的优化 ID 从 optimization_runs.result_json.trialList[0] 提取 engineFactors。
    """
    bt_service = BacktestService(db)
    opt_service = OptimizationService(db)

    factors: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    execution_signals: list[dict[str, Any]] = []
    strategy_name = ""
    dataset_id = ""

    # 优先按 optimization_runs 查询
    opt_run = opt_service.repo.get_optimization_run(run_id)
    if opt_run:
        raw = loads_json_field(opt_run.result_json, {})
        trial_list = raw.get("trialList") or []
        best_trial = trial_list[0] if trial_list else {}
        factors = best_trial.get("engineFactors") or []
        parameter_sensitivity = _build_theme_parameter_sensitivity(trial_list)
        control_attribution = _empty_theme_control_attribution()
        strategy_name = opt_run.strategy_name
        dataset_id = opt_run.dataset_id or ""
    else:
        # 回退到 backtest_runs
        bt_run = bt_service.repo.get_backtest_run(run_id)
        if not bt_run:
            raise HTTPException(status_code=404, detail={"code": "run_not_found", "runId": run_id})
        result = loads_json_field(bt_run.result_json, {})
        tt = result.get("themeTrend") or {}
        factors = tt.get("factors") or tt.get("signals") or result.get("signals") or []
        trades = result.get("trades") or ((result.get("tradeSimulation") or {}).get("trades")) or []
        if not trades:
            trades = bt_service.repo.get_backtest_trades(run_id)
        execution_signals = result.get("executionSignals") or []
        parameter_sensitivity = _build_theme_parameter_sensitivity([])
        control_attribution = _build_theme_control_attribution(result, trades, execution_signals)
        strategy_name = bt_run.strategy_name
        dataset_id = bt_run.dataset_id

    lifecycle_dist: dict[str, int] = {}
    for f in factors:
        lc = str(f.get("lifecycle") or "neutral")
        lifecycle_dist[lc] = lifecycle_dist.get(lc, 0) + 1

    signal_dist: dict[str, int] = {}
    for f in factors:
        sig = str(f.get("signal") or "watch")
        signal_dist[sig] = signal_dist.get(sig, 0) + 1

    crowding_events = [f for f in factors if f.get("lifecycle") == "crowded"]
    transitions = [f for f in factors if f.get("lifecycleTransition")]
    trade_report = _build_theme_trade_report(trades, execution_signals)

    return {
        "runId": run_id,
        "strategyName": strategy_name,
        "datasetId": dataset_id,
        "lifecycleDistribution": lifecycle_dist,
        "signalDistribution": signal_dist,
        "crowdingEventCount": len(crowding_events),
        "lifecycleTransitionCount": len(transitions),
        "recentTransitions": transitions[:20],
        "themeCount": len({f.get("themeId") for f in factors if f.get("themeId")}),
        "totalFactorCount": len(factors),
        "controlGroupAttribution": control_attribution,
        "parameterSensitivity": parameter_sensitivity,
        **trade_report,
    }


def _empty_theme_control_attribution() -> dict[str, Any]:
    base = {"signalCount": 0, "tradeCount": 0, "winRate": 0, "avgNetReturn": 0, "totalProfit": 0}
    return {
        "rankTrendOnly": dict(base),
        "themeOnly": dict(base),
        "themeRankTrendConfluence": dict(base),
        "leaderConfirmation": dict(base),
        "conclusion": "optimization_run_no_trade_control_groups",
    }


def _summarize_theme_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    total_profit = round(sum(float(row.get("profit") or 0) for row in rows), 2)
    total_return = round(sum(float(row.get("netReturn") or 0) for row in rows), 4)
    wins = sum(1 for row in rows if float(row.get("netReturn") or 0) > 0)
    return {
        "tradeCount": count,
        "winRate": round(wins / count, 4) if count else 0,
        "avgNetReturn": round(total_return / count, 4) if count else 0,
        "totalProfit": total_profit,
    }


def _build_theme_control_attribution(
    result: dict[str, Any],
    trades: list[dict[str, Any]],
    execution_signals: list[dict[str, Any]],
) -> dict[str, Any]:
    theme_trend = result.get("themeTrend") if isinstance(result.get("themeTrend"), dict) else {}
    rank_control = theme_trend.get("rankTrendControl") if isinstance(theme_trend.get("rankTrendControl"), dict) else {}
    signals = result.get("signals") if isinstance(result.get("signals"), list) else []
    confluence_count = len(execution_signals)
    leader_signals = [
        signal for signal in execution_signals
        if str(signal.get("themeRole") or "").lower() == "leader"
        or "leader" in str(signal.get("themeReasons") or "").lower()
        or "龙头" in str(signal.get("themeReasons") or "")
    ]
    leader_trades = [
        trade for trade in trades
        if str(trade.get("explanation") or "").find("龙头") >= 0
        or str(trade.get("candidateTier") or "") == "A_MAIN"
    ]
    trade_summary = _summarize_theme_rows(trades)
    leader_trade_summary = _summarize_theme_rows(leader_trades)
    return {
        "rankTrendOnly": {
            "signalCount": int(rank_control.get("signalCount") or 0),
            "tradeCount": int(rank_control.get("tradeCount") or 0),
            "totalReturn": rank_control.get("totalReturn"),
            "maxDrawdown": rank_control.get("maxDrawdown"),
            "winRate": rank_control.get("winRate") or 0,
        },
        "themeOnly": {
            "signalCount": len(signals),
            **trade_summary,
        },
        "themeRankTrendConfluence": {
            "signalCount": confluence_count,
            **trade_summary,
        },
        "leaderConfirmation": {
            "signalCount": len(leader_signals),
            **leader_trade_summary,
        },
        "conclusion": (
            "theme_confluence_available"
            if confluence_count or trades
            else "theme_research_only_no_executable_control_group"
        ),
    }


def _build_theme_parameter_sensitivity(trials: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [trial for trial in trials if isinstance(trial, dict) and isinstance(trial.get("params"), dict)]
    if not completed:
        return {"trialCount": 0, "parameters": [], "topParameterSet": {}, "warnings": ["no_completed_trials"]}
    completed = sorted(completed, key=lambda trial: float(trial.get("score") or 0), reverse=True)
    top_count = max(1, min(5, len(completed)))
    top_trials = completed[:top_count]
    keys = sorted({key for trial in completed for key in (trial.get("params") or {}).keys()})
    rows: list[dict[str, Any]] = []
    for key in keys:
        values = [trial.get("params", {}).get(key) for trial in completed]
        top_values = [trial.get("params", {}).get(key) for trial in top_trials]
        score_by_value: dict[str, list[float]] = {}
        for trial in completed:
            value_key = str((trial.get("params") or {}).get(key))
            score_by_value.setdefault(value_key, []).append(float(trial.get("score") or 0))
        best_value, best_scores = max(
            score_by_value.items(),
            key=lambda item: (sum(item[1]) / len(item[1]) if item[1] else float("-inf")),
        )
        rows.append({
            "parameter": key,
            "bestValue": top_trials[0].get("params", {}).get(key),
            "dominantTopValues": sorted({str(value) for value in top_values}),
            "testedValueCount": len({str(value) for value in values}),
            "bestAverageValue": best_value,
            "bestAverageScore": round(sum(best_scores) / len(best_scores), 4) if best_scores else 0,
        })
    return {
        "trialCount": len(completed),
        "topTrialCount": top_count,
        "topParameterSet": completed[0].get("params") or {},
        "topScore": completed[0].get("score"),
        "parameters": rows,
    }


def _build_theme_trade_report(trades: list[dict[str, Any]], execution_signals: list[dict[str, Any]]) -> dict[str, Any]:
    signal_by_entry = {
        (str(item.get("snapshotId") or ""), str(item.get("code") or "")): item
        for item in execution_signals
        if item.get("code")
    }

    def enrich(trade: dict[str, Any]) -> dict[str, Any]:
        signal = signal_by_entry.get((str(trade.get("entrySnapshotId") or ""), str(trade.get("code") or "")), {})
        return {
            **trade,
            "lifecycle": trade.get("stage") or signal.get("stage") or "neutral",
            "themeName": signal.get("mainTheme") or trade.get("themeName") or "",
            "role": signal.get("themeRole") or trade.get("themeRole") or "",
            "candidateTier": trade.get("candidateTier") or signal.get("candidateTier") or "",
            "crowdingTriggered": (
                trade.get("candidateTier") == "C_CROWDED"
                or signal.get("candidateTier") == "C_CROWDED"
                or str(signal.get("stage") or "") in {"crowded", "divergence"}
                or any(str(flag).startswith("crowding:") for flag in (signal.get("themeRiskFlags") or []))
            ),
        }

    enriched = [enrich(trade) for trade in trades]

    def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(rows)
        total_profit = round(sum(float(row.get("profit") or 0) for row in rows), 2)
        total_return = round(sum(float(row.get("netReturn") or 0) for row in rows), 4)
        wins = sum(1 for row in rows if float(row.get("netReturn") or 0) > 0)
        return {
            "tradeCount": count,
            "winRate": round(wins / count, 4) if count else 0,
            "avgNetReturn": round(total_return / count, 4) if count else 0,
            "totalNetReturn": total_return,
            "totalProfit": total_profit,
        }

    def group_by(field: str) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in enriched:
            key = str(row.get(field) or "unknown")
            grouped.setdefault(key, []).append(row)
        return grouped

    lifecycle_returns = {
        key: summarize(rows)
        for key, rows in sorted(group_by("lifecycle").items())
    }
    theme_diagnostics = [
        {"themeName": key, **summarize(rows)}
        for key, rows in sorted(group_by("themeName").items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    tier_diagnostics = [
        {"candidateTier": key, **summarize(rows)}
        for key, rows in sorted(group_by("candidateTier").items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    role_diagnostics = [
        {"role": key, **summarize(rows)}
        for key, rows in sorted(group_by("role").items(), key=lambda item: (-len(item[1]), item[0]))
    ]
    crowded_rows = [row for row in enriched if row.get("crowdingTriggered")]

    return {
        "lifecycleReturnDistribution": lifecycle_returns,
        "themeTradeDiagnostics": theme_diagnostics,
        "candidateTierDiagnostics": tier_diagnostics,
        "roleDiagnostics": role_diagnostics,
        "crowdingRiskDecay": {
            "triggeredTradeCount": len(crowded_rows),
            **summarize(crowded_rows),
        },
    }


@app.post("/api/golden/import")
def import_golden(request: GoldenImportRequest, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return GoldenService(db).import_case(request.model_dump(by_alias=True))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/golden/baseline")
def create_golden_baseline(payload: dict[str, Any], db: Session | None = Depends(get_db)) -> dict[str, Any]:
    try:
        return GoldenService(db).create_baseline(payload)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/golden/validate")
def validate_golden(request: GoldenValidateRequest, db: Session | None = Depends(get_db)) -> dict[str, Any]:
    return GoldenService(db).validate(request.model_dump(by_alias=True))


settings = get_settings()
frontend_dist = settings.frontend_dir / "dist"
if frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="quant-assets")


@app.get("/", response_model=None)
def index():
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "QuantBoard API is running", "docs": "/docs"}