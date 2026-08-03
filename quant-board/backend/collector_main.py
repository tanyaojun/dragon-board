"""Standalone snapshot collector process (default port 8001).

Managed as a core startup item by DragonBoardLauncher.  Only mounts the
snapshot-collector routes and a health endpoint, and starts the market-proxy
background refreshers the collector needs.  Provider requests are served
in-process (``InProcessMarketDataGateway``), so snapshot collection no longer
depends on the 8000 API process.

Single-instance coordination: the collector acquires a Redis instance lock
before starting the scheduler.  When the lock is held elsewhere (e.g. the 8000
API process started first), startup fails fast so the launcher shows the
conflict instead of silently double-collecting.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import FastAPI


logger = logging.getLogger(__name__)


def _build_redis_client(redis_url: str) -> Any | None:
    if not redis_url:
        return None
    try:
        import redis as redis_module

        return redis_module.Redis.from_url(
            redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
            decode_responses=True,
        )
    except Exception:
        return None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.market_fund_scheduler import market_fund_scheduler
    from backend.market_proxy.hotlists import (
        close_hotlist_client,
        start_hotlist_refresh,
        stop_hotlist_refresh,
    )
    from backend.market_proxy.limitup import get_limitup_service
    from backend.market_proxy.quotes import (
        start_market_quotes_refresh,
        stop_market_quotes_refresh,
    )
    from backend.settings import get_settings
    from backend.snapshot_collector.instance_lock import RedisInstanceLock
    from backend.snapshot_collector.providers import (
        close_collector_http,
        set_default_gateway,
    )
    from backend.snapshot_collector.gateway import InProcessMarketDataGateway
    from backend.snapshot_collector.scheduler import snapshot_collector_scheduler

    settings = get_settings()
    lock = RedisInstanceLock(
        _build_redis_client(settings.redis_url),
        settings.snapshot_collector_dataset_id,
    )
    if not lock.acquire():
        remaining = lock.remaining_ttl()
        raise RuntimeError(
            "another snapshot collector instance holds the lock for dataset "
            f"{settings.snapshot_collector_dataset_id}"
            + (f" (remaining TTL {remaining}s)" if remaining is not None else "")
        )

    renew_task: asyncio.Task[Any] | None = None
    set_default_gateway(InProcessMarketDataGateway())

    async def _warm_limitup() -> None:
        """预热涨停池缓存：进程内网关冷缓存时显式降级，预热后正常返回。"""
        while True:
            try:
                await get_limitup_service().get_ths_pools()
            except Exception as exc:
                logger.warning("limitup warm refresh failed: %s", exc)
            await asyncio.sleep(300)

    try:
        await start_market_quotes_refresh()
        await start_hotlist_refresh()
        market_fund_scheduler.start()
        snapshot_collector_scheduler.start()
        limitup_task = asyncio.create_task(_warm_limitup())

        async def _renew_lock() -> None:
            while True:
                await asyncio.sleep(lock.ttl_seconds / 2)
                if not lock.renew():
                    logger.error("collector instance lock lost; stopping scheduler")
                    await snapshot_collector_scheduler.stop()
                    return

        renew_task = asyncio.create_task(_renew_lock())
        yield
        limitup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await limitup_task
    finally:
        if renew_task is not None:
            renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renew_task
        await snapshot_collector_scheduler.stop()
        await market_fund_scheduler.stop()
        await stop_hotlist_refresh()
        await close_hotlist_client()
        await stop_market_quotes_refresh()
        close_collector_http()
        lock.release()


app = FastAPI(title="QuantBoard Snapshot Collector", lifespan=lifespan)

from backend.api.snapshot_collector_routes import router as snapshot_collector_router

app.include_router(snapshot_collector_router)


@app.get("/api/health")
def health() -> dict:
    from backend.snapshot_collector.scheduler import snapshot_collector_scheduler
    from backend.snapshot_collector.trading_calendar import _last_calendar_source

    status = snapshot_collector_scheduler.status()
    status["calendarSource"] = _last_calendar_source
    if not status.get("last_run_at"):
        # 进程重启后内存态 last_run_at 会清零，导致 launcher 探针在"已收盘但
        # 进程刚启动"时误报。用 MongoDB 里最近的 completed 运行记录回填。
        try:
            from backend.snapshot_collector.service_factory import (
                create_snapshot_collector_repository,
            )

            runs = create_snapshot_collector_repository().list_runs(
                {
                    "datasetId": status.get("dataset_id", ""),
                    "status": "completed",
                    "limit": 1,
                }
            )
            items = runs.get("items") or []
            if items:
                latest = items[0]
                created_at = latest.get("createdAt")
                if created_at is not None:
                    if hasattr(created_at, "isoformat"):
                        iso = created_at.isoformat()
                        # Mongo 的 datetime.utcnow() 是无时区 UTC，补 Z 让探针按 UTC 解析
                        status["last_run_at"] = iso if created_at.tzinfo is not None else iso + "Z"
                    else:
                        status["last_run_at"] = str(created_at)
                status["last_slot_collected"] = str(latest.get("snapshotId") or "")
        except Exception:
            pass
    return {"status": "ok", "snapshotCollector": status}
