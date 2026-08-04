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


async def _acquire_lock_with_retry(
    lock: Any,
    *,
    tries: int = 10,
    interval_seconds: float = 5.0,
) -> bool:
    """锁冲突退避重试：上一进程残留锁会随 TTL 过期或 PID 存活检测回收。"""
    for attempt in range(tries):
        if await asyncio.to_thread(lock.acquire):
            return True
        logger.warning(
            "collector lock held elsewhere (attempt %d/%d); retrying in %.0fs",
            attempt + 1,
            tries,
            interval_seconds,
        )
        await asyncio.sleep(interval_seconds)
    return False


async def _catchup_missing_slots(settings: Any) -> None:
    """当日缺槽自动补采：错过 grace 窗口且尚未入库的槽位用当日数据补上。"""
    from backend.snapshot_collector.models import CollectorRunRequest
    from backend.snapshot_collector.service_factory import (
        create_snapshot_collector_repository,
        create_snapshot_collector_service,
    )
    from backend.snapshot_collector.slots import generate_slots
    from backend.snapshot_collector.trading_calendar import trading_date_from_ts

    attempted: set[str] = set()
    last_date: str | None = None
    while True:
        await asyncio.sleep(900)  # 每 15 分钟检查一次
        try:
            now_ts = int(time.time() * 1000)
            trading_date = await asyncio.to_thread(trading_date_from_ts, now_ts)
            if not trading_date:
                continue
            if last_date != trading_date:
                last_date = trading_date
                attempted.clear()
            grace_ms = settings.snapshot_collector_close_grace_minutes * 60 * 1000
            types = [
                t.strip()
                for t in settings.snapshot_collector_types.split(",")
                if t.strip()
            ]
            repo = await asyncio.to_thread(create_snapshot_collector_repository)
            missing: list[Any] = []
            for slot in generate_slots(trading_date, types):
                if slot.snapshot_id in attempted:
                    continue
                if slot.timestamp_ms + grace_ms >= now_ts:
                    continue  # 调度器仍在处理或未到期，不抢
                exists = await asyncio.to_thread(
                    repo.snapshot_exists,
                    settings.snapshot_collector_dataset_id,
                    slot.snapshot_id,
                )
                if not exists:
                    missing.append(slot)
            if not missing:
                continue
            service = await asyncio.to_thread(create_snapshot_collector_service, repo)
            for slot in missing:
                attempted.add(slot.snapshot_id)
                try:
                    result = await service.arun_once(
                        CollectorRunRequest(
                            dataset_id=settings.snapshot_collector_dataset_id,
                            snapshot_type=slot.snapshot_type,
                            trading_date=slot.trading_date,
                            slot_time=slot.slot_time,
                            dry_run=False,
                            force=False,
                        )
                    )
                    logger.warning(
                        "catch-up: %s -> %s (%s)",
                        slot.snapshot_id,
                        result.status,
                        result.message,
                    )
                except Exception:
                    logger.exception("catch-up failed: %s", slot.snapshot_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("catch-up cycle failed")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.market_fund_scheduler import market_fund_scheduler
    from backend.market_proxy.hotlists import (
        close_hotlist_client,
        start_hotlist_refresh,
        stop_hotlist_refresh,
    )
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
    if not await _acquire_lock_with_retry(lock):
        remaining = lock.remaining_ttl()
        raise RuntimeError(
            "another snapshot collector instance holds the lock for dataset "
            f"{settings.snapshot_collector_dataset_id}"
            + (f" (remaining TTL {remaining}s)" if remaining is not None else "")
        )

    renew_task: asyncio.Task[Any] | None = None
    catchup_task: asyncio.Task[Any] | None = None
    set_default_gateway(InProcessMarketDataGateway())

    try:
        await start_market_quotes_refresh()
        await start_hotlist_refresh()
        market_fund_scheduler.start()
        snapshot_collector_scheduler.start()

        async def _renew_lock() -> None:
            failures = 0
            while True:
                await asyncio.sleep(lock.ttl_seconds / 2)
                if await asyncio.to_thread(lock.renew):
                    failures = 0
                    continue
                failures += 1
                logger.error("collector lock renew failed (%d); retrying", failures)
                if failures >= 3:
                    logger.error(
                        "collector lock lost after %d renew failures; stopping scheduler",
                        failures,
                    )
                    await snapshot_collector_scheduler.stop()
                    return

        renew_task = asyncio.create_task(_renew_lock())
        catchup_task = asyncio.create_task(_catchup_missing_slots(settings))
        yield
    finally:
        for task in (renew_task, catchup_task):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
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
    status["background"] = _background_task_status()
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


def _background_task_status() -> dict[str, Any]:
    """各后台刷新任务健康：供 launcher/人工判断是"进程死"还是"任务停"。"""
    result: dict[str, Any] = {}
    try:
        from backend.market_proxy.hotlists import get_hotlist_service

        result["hotlist"] = get_hotlist_service().status()
    except Exception as exc:
        result["hotlist"] = {"ok": False, "error": str(exc)[:200]}
    try:
        from backend.market_proxy.quotes import get_market_quotes_cache

        result["quotes"] = get_market_quotes_cache().status()
    except Exception as exc:
        result["quotes"] = {"ok": False, "error": str(exc)[:200]}
    try:
        from backend.market_fund_scheduler import market_fund_scheduler

        fund = market_fund_scheduler.status()
        result["fund"] = fund if isinstance(fund, dict) else {"ok": True}
    except Exception as exc:
        result["fund"] = {"ok": False, "error": str(exc)[:200]}
    try:
        from backend.market_proxy.limitup import get_limitup_service

        service = get_limitup_service()
        cache = getattr(service, "_cache", {})
        result["limitup"] = {
            "ok": True,
            "cachedKeys": sorted(str(k) for k in cache.keys()),
        }
    except Exception as exc:
        result["limitup"] = {"ok": False, "error": str(exc)[:200]}
    return result
