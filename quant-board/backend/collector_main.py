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
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI


logger = logging.getLogger(__name__)


def _startup_failure_file() -> Path:
    """锁冲突等启动失败原因落盘，供 launcher 探针在 8001 不可达时读取。

    路径固定在仓库根 logs 下（与 launcher 日志同目录），C# 探针用
    ProjectRootLocator.Find() 定位同一路径。
    """
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "logs" / "collector-startup-failure.json"


def _write_startup_failure(reason: str, *, recommended_action: str = "wait") -> None:
    """启动失败时写入结构化原因；launcher 探针据此不杀不重启。"""
    try:
        payload = {
            "status": "error",
            "restartable": False,
            "recommendedAction": recommended_action,
            "reason": reason,
            "writtenAt": datetime.now(timezone.utc).isoformat(),
        }
        _startup_failure_file().write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        logger.exception("failed to write startup failure file")


def _clear_startup_failure() -> None:
    try:
        _startup_failure_file().unlink(missing_ok=True)
    except Exception:
        pass


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


_LOCK_STATE: dict[str, str] = {"mode": "unknown", "error": ""}
"""单实例协调状态（fail-visible）：mode ∈ {unknown, redis, degraded}。

2026-10-19 复盘新增：Redis 不可达时 acquire() 是 fail-open（可用性优先，采集
不能因为缓存/协调层挂了就起不来），但“无 Redis 协调”必须能在 /api/health 里
看见，否则运维只能看到“一切 ok”而双采风险已经在场上。

注意：它是**启动快照**，只作为拿不到活锁对象时的兜底；健康输出优先读当前锁
对象的 ``degraded_reason``（见 ``_live_lock_state``），否则一次瞬时抖动会把
health 永久钉在 degraded。
"""

# 当前活着的实例锁对象（供 /api/health 读“当下”的协调状态）。
_ACTIVE_LOCK: Any | None = None


def _live_lock_state() -> tuple[str, str]:
    """``(mode, error)``：优先用活锁对象的当下状态，没有则回退启动快照。"""
    lock = _ACTIVE_LOCK
    if lock is not None:
        reason = getattr(lock, "degraded_reason", None)
        return ("degraded" if reason else "redis", reason or "")
    return (_LOCK_STATE.get("mode") or "unknown", _LOCK_STATE.get("error") or "")


def _lock_wait_tries(ttl_seconds: int, interval_seconds: float) -> int:
    """等锁预算次数：总等待必须覆盖残留锁的最长寿命（TTL）。

    launcher 停止服务是 taskkill 强杀，collector 来不及走 lifespan finally 的
    lock.release()，锁必然残留 0~TTL 秒；旧预算 10×5s=50s < TTL 120s，等锁实例
    必然 RuntimeError 自杀，喂大 launcher 连续失败计数直至熔断，形成重启风暴
    （2026-10-12 复盘：11:34:52 杀掉持有者后新实例仍干等到 11:36:53 TTL 自然过期）。
    预算 = TTL/interval + 8 次余量。

    2026-10-19 复盘后 acquire() 的残留锁判定改为「退出码 + 创建时间」双重身份
    （见 instance_lock._process_identity），强杀后通常首次尝试即可清锁重抢；本预算
    仍必须覆盖 TTL 全长——判活不可判定时按存活处理，那时只能等 TTL 自然过期。
    """
    return int(ttl_seconds / interval_seconds) + 8


async def _acquire_lock_with_retry(
    lock: Any,
    *,
    tries: int | None = None,
    interval_seconds: float = 5.0,
) -> bool:
    """锁冲突退避重试：上一进程残留锁会随 TTL 过期或 PID 存活检测回收。"""
    if tries is None:
        ttl_seconds = int(getattr(lock, "ttl_seconds", 0) or 120)
        tries = _lock_wait_tries(ttl_seconds, interval_seconds)
    for attempt in range(tries):
        if await asyncio.to_thread(lock.acquire):
            return True
        logger.warning(
            "collector lock held elsewhere (attempt %d/%d); retrying in %.0fs",
            attempt + 1,
            tries,
            interval_seconds,
        )
        if attempt == 0:
            # 首次失败即落盘启动失败标记：进程可能已绑定 8001 端口但 lifespan
            # 尚未完成（正在等锁），launcher 探针读到 restartable=false/wait 后
            # 不会"杀正在等锁的进程"打断重试（2026-08-05 重启风暴根因之一）。
            _write_startup_failure(
                "collector lock held elsewhere; waiting for lock TTL expiry",
                recommended_action="wait",
            )
        await asyncio.sleep(interval_seconds)
    return False


_CLOSE_BACKFILL_MIN_SLOT_TIME = "15:00"


def _degraded_lock_peer_running(lock: Any, *, port: int = 8001) -> bool:
    """锁后端不可用（fail-open 抢锁）+ 8001 已被别的实例服务 = 本进程必须退出。

    fail-open 的代价是"无 Redis 协调"：若此时已有活实例在采（8001 自报健康契约），
    再起一个就是双采（项目红线）。所以降级抢锁后必须再查一次对端；
    查不到对端才允许单实例继续跑（并在 /api/health 暴露 lockBackend=degraded）。
    """
    if not getattr(lock, "degraded_reason", None):
        return False
    return _collector_serving_elsewhere(port=port)


def _collector_serving_elsewhere(port: int = 8001, timeout: float = 3.0) -> bool:
    """8001 是否已由另一个采集实例提供健康契约（冗余实例判定）。

    等锁预算耗尽时用：若 8001 已被活实例 serve，本进程是多余的那一个。
    2026-10-19 复盘：输家实例自杀时写下 restartable=false 标记，launcher 据此
    10 分钟内不再拉起采集；但标记对“8001 已被另一个实例正常服务”是错的消息。
    锁后端降级（无 Redis 协调）时也用它做防双采复查。
    """
    import json as _json
    import urllib.request as _urllib_request

    try:
        with _urllib_request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=timeout
        ) as response:
            if getattr(response, "status", 200) != 200:
                return False
            payload = _json.loads(response.read().decode("utf-8", "replace"))
    except Exception:
        return False
    return isinstance(payload, dict) and isinstance(payload.get("snapshotCollector"), dict)


class _CatchupState:
    """缺失补采循环的跨轮状态：已成功补采的槽位与当前交易日。"""

    def __init__(self) -> None:
        self.attempted: set[str] = set()
        self.last_date: str | None = None


async def _catchup_cycle(settings: Any, state: _CatchupState) -> None:
    """单轮缺失补采（由 _catchup_missing_slots 每 15 分钟驱动一次）。

    - 采集窗口内（09:00-16:00）：所有过期未入库槽位均可补采。
    - 收盘后（16:00 至次日 09:00）：行情已定格，仅补 15:00 及之后的收盘类
      槽位（half_hour 15:00 / daily 15:30，回填不失真）；盘中槽不补——用收盘价
      伪造盘中数据会失真（2026-09-11 复盘：机器待机 7 小时，唤醒后旧实现
      对缺失槽位完全不作为）。
    - attempted 仅在成功（completed/deduped）后登记：blocked/failed 的
      槽位下一轮重试（blocked 已由 service 写入 run 记录，缺失保持可见）。
    """
    from backend.snapshot_collector.models import CollectorRunRequest
    from backend.snapshot_collector.service_factory import (
        create_snapshot_collector_repository,
        create_snapshot_collector_service,
    )
    from backend.snapshot_collector.slots import generate_slots
    from backend.snapshot_collector.trading_calendar import (
        TZ_SHANGHAI,
        is_in_collect_window,
        trading_date_from_ts,
    )

    now_ts = int(time.time() * 1000)
    in_window = is_in_collect_window(
        datetime.fromtimestamp(now_ts / 1000, TZ_SHANGHAI)
    )
    trading_date = await asyncio.to_thread(trading_date_from_ts, now_ts)
    if not trading_date:
        return
    if state.last_date != trading_date:
        state.last_date = trading_date
        state.attempted.clear()
    grace_ms = settings.snapshot_collector_close_grace_minutes * 60 * 1000
    types = [
        t.strip()
        for t in settings.snapshot_collector_types.split(",")
        if t.strip()
    ]
    repo = await asyncio.to_thread(create_snapshot_collector_repository)
    missing: list[Any] = []
    for slot in generate_slots(trading_date, types):
        if slot.snapshot_id in state.attempted:
            continue
        if slot.timestamp_ms + grace_ms >= now_ts:
            continue  # 调度器仍在处理或未到期，不抢
        # 收盘后只补收盘定格槽位；盘中槽交给人工决策（失真数据不入库）。
        if not in_window and slot.slot_time < _CLOSE_BACKFILL_MIN_SLOT_TIME:
            continue
        exists = await asyncio.to_thread(
            repo.snapshot_exists,
            settings.snapshot_collector_dataset_id,
            slot.snapshot_id,
        )
        if not exists:
            missing.append(slot)
    if not missing:
        return
    service = await asyncio.to_thread(create_snapshot_collector_service, repo)
    for slot in missing:
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
            if result.status in ("completed", "deduped"):
                state.attempted.add(slot.snapshot_id)
                logger.warning(
                    "catch-up: %s -> %s (%s)",
                    slot.snapshot_id,
                    result.status,
                    result.message,
                )
            else:
                # 失败不登记 attempted：下一轮重试；blocked 的 run 记录由
                # service 落库，缺失与原因保持可见（fail-visible）。
                logger.warning(
                    "catch-up: %s -> %s (%s); will retry next cycle",
                    slot.snapshot_id,
                    result.status,
                    result.message,
                )
        except Exception:
            logger.exception("catch-up failed: %s", slot.snapshot_id)


async def _catchup_missing_slots(settings: Any) -> None:
    """当日缺槽自动补采循环：每 15 分钟执行一轮 _catchup_cycle。"""
    state = _CatchupState()
    while True:
        await asyncio.sleep(900)  # 每 15 分钟检查一次
        try:
            await _catchup_cycle(settings, state)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("catch-up cycle failed")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.core.settings import assert_production_storage_backend

    # 2026-09-29 隔离裁决：生产入口 fail-fast——sqlite 后端未显式 opt-in 即拒绝启动
    assert_production_storage_backend()
    from backend.services.market.fund_scheduler import market_fund_scheduler
    from backend.market_proxy.hotlists import (
        close_hotlist_client,
        start_hotlist_refresh,
        stop_hotlist_refresh,
    )
    from backend.market_proxy.quotes import (
        start_market_quotes_refresh,
        stop_market_quotes_refresh,
    )
    from backend.core.settings import get_settings
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
    global _ACTIVE_LOCK
    _ACTIVE_LOCK = lock  # /api/health 据此读“当下”的协调状态
    if not await _acquire_lock_with_retry(lock):
        remaining = lock.remaining_ttl()
        reason = (
            "another snapshot collector instance holds the lock for dataset "
            f"{settings.snapshot_collector_dataset_id}"
            + (f" (remaining TTL {remaining}s)" if remaining is not None else "")
        )
        # 冗余实例判定（2026-10-19 复盘）：8001 已被另一实例正常服务时，本进程
        # 退出前清掉等待标记——那个标记只用于“确实没人在采集”时防重启风暴，
        # 留着会让 launcher 把“不可重启”状态拖满 10 分钟窗口。
        if await asyncio.to_thread(_collector_serving_elsewhere):
            _clear_startup_failure()
            logger.warning(
                "another collector instance is already serving 8001; "
                "exiting this redundant instance"
            )
            raise RuntimeError(
                "another snapshot collector instance is already serving port 8001; "
                "this redundant instance exits (8001 采集正常，无需处理)"
            )
        # 启动失败原因落盘，launcher 探针在 8001 不可达时读取后按 wait 处理，
        # 不再"先杀再启"触发锁竞争重启风暴（2026-08-05 复盘）。
        _write_startup_failure(reason, recommended_action="wait")
        raise RuntimeError(reason)

    # 锁后端降级（Redis 不可达，fail-open）时的防双采复查（2026-10-19 复盘）：
    # Redis 挂了不能让采集起不来，但也不能在“别的实例已在采”时盲起——那样是双采。
    lock_state = getattr(lock, "degraded_reason", None)
    if await asyncio.to_thread(_degraded_lock_peer_running, lock):
        _clear_startup_failure()
        logger.error(
            "lock backend degraded (%s) and 8001 is already served by another "
            "instance; exiting this instance to avoid double collection",
            lock_state,
        )
        raise RuntimeError(
            "lock backend unavailable and 8001 already served by another instance; "
            "exiting to avoid double collection (单实例协调降级，防双采退出)"
        )
    if lock_state:
        logger.warning(
            "single-instance coordination degraded: %s; continuing as sole instance",
            lock_state,
        )
    _LOCK_STATE["mode"] = "degraded" if lock_state else "redis"
    _LOCK_STATE["error"] = lock_state or ""

    # 成功拿到锁后清除历史失败标记，探针回到正常契约判定。
    _clear_startup_failure()

    renew_task: asyncio.Task[Any] | None = None
    catchup_task: asyncio.Task[Any] | None = None
    set_default_gateway(InProcessMarketDataGateway())

    try:
        await start_market_quotes_refresh()
        await start_hotlist_refresh()
        # 资金数据（theme-fund）由 8000 的 fund_scheduler 维护（东财全量 +
        # THS L2 补充）；8001 只通过 MarketFundCacheProvider 读 Redis theme-fund
        # 做快照资金列，不再自己启动 fund_scheduler——否则 8000/8001 双进程并发
        # put_many 会互相触发旧行清理，导致 theme-fund:latest key 反复消失
        # （2026-08-12 排查修复）。
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
        # 2026-09-15 重构：analyze 落库已内联为采集主链的同步后处理链
        # （service._run_post_persist_chain，落帧 → analyze → 槽位情绪 → EOD），
        # 后台 analysis_worker 退役，进程退出无需再排空分析队列。
        await snapshot_collector_scheduler.stop()
        await market_fund_scheduler.stop()
        await stop_hotlist_refresh()
        await close_hotlist_client()
        await stop_market_quotes_refresh()
        close_collector_http()
        lock.release()


app = FastAPI(
    title="QuantBoard Snapshot Collector",
    lifespan=lifespan,
    docs_url=None,  # /docs 由 offline_docs 接管（本地 swagger 资源，CDN 8s+ 延迟致空白）
    redoc_url=None,  # 同根因：redoc 默认走 CDN（reDoc standalone js），本链路无消费者
)

from backend.api.offline_docs import install_offline_docs

install_offline_docs(app)

# after-save 钩子注册（2026-09-10）：8001 进程同样注册，保证 collector 直写库路径与 ingest
# 路由的快照后处理（缓存失效 + analyze 产物落库）由同一处（数据层 `save_snapshot_ingest`）触发。
# 在**模块导入时**注册（而非 lifespan）：不依赖 startup/lifespan 是否被执行。
try:
    from backend.services.snapshot_post_save_hooks import (
        register_default_snapshot_post_save_hooks,
    )

    register_default_snapshot_post_save_hooks()
except Exception:
    logger.exception("snapshot post-save hooks registration failed; continue startup")

from backend.api.snapshot_collector_routes import router as snapshot_collector_router

app.include_router(snapshot_collector_router)


@app.get("/api/health")
def health() -> dict:
    from backend.snapshot_collector.scheduler import snapshot_collector_scheduler
    from backend.snapshot_collector.trading_calendar import _last_calendar_source

    status = snapshot_collector_scheduler.status()
    status["calendarSource"] = _last_calendar_source
    status["background"] = _background_task_status()
    # 单实例协调状态（2026-10-19 复盘）：Redis 不可达时 acquire 是 fail-open，
    # 必须让 launcher/运维看得见“当前无 Redis 协调”（否则双采风险静默）。
    status["lockBackend"], lock_error = _live_lock_state()
    if lock_error:
        status["lockError"] = lock_error
    if not status.get("last_run_at"):
        # 进程重启后内存态 last_run_at 会清零，导致 launcher 探针在"已收盘但
        # 进程刚启动"时误报。用 MongoDB 里最近且属于当前交易日的 completed
        # 运行记录回填；跨日的旧记录不写入 last_run_at，避免新交易日开盘瞬间
        # 被探针误判为"超过2小时未执行"而杀重启。
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
                latest_trading_date = str(
                    latest.get("tradingDate")
                    or latest.get("trading_date")
                    or ""
                )
                if latest_trading_date == str(status.get("trading_date") or ""):
                    created_at = latest.get("createdAt")
                    if created_at is not None:
                        if hasattr(created_at, "isoformat"):
                            iso = created_at.isoformat()
                            # Mongo 的 datetime.utcnow() 是无时区 UTC，补 Z 让探针按 UTC 解析
                            status["last_run_at"] = (
                                iso if created_at.tzinfo is not None else iso + "Z"
                            )
                        else:
                            status["last_run_at"] = str(created_at)
                    status["last_slot_collected"] = str(
                        latest.get("snapshotId") or ""
                    )
        except Exception:
            pass

    contract = _collector_health_contract(status)
    return {
        # launcher 健康契约：restartable/recommendedAction 由后端判定，
        # 启动器只消费结构，不再解析 snapshotCollector 内部字段猜语义。
        "status": contract["status"],
        "restartable": contract["restartable"],
        "recommendedAction": contract["recommendedAction"],
        "reason": contract["reason"],
        "snapshotCollector": status,
    }


def _collector_health_contract(status: dict[str, Any]) -> dict[str, Any]:
    """把调度器状态映射为 launcher 可消费的健康契约。

    - 调度器未运行（enabled 但 running=false）：硬故障，可重启；
    - 最近有采集异常（last_error）：数据源暂时失败，重启无益，只告警；
    - 其余：ok，不动作。
    """
    if status.get("enabled") and not status.get("running"):
        return {
            "status": "error",
            "restartable": True,
            "recommendedAction": "restart",
            "reason": "调度器未运行",
        }
    last_error = status.get("last_error")
    if status.get("lockBackend") == "degraded":
        return {
            "status": "degraded",
            "restartable": False,
            "recommendedAction": "alert",
            "reason": "单实例协调降级（锁后端不可用）: "
            + str(status.get("lockError") or "unknown"),
        }
    if last_error:
        return {
            "status": "degraded",
            "restartable": False,
            "recommendedAction": "alert",
            "reason": f"最近异常: {last_error}",
        }
    return {
        "status": "ok",
        "restartable": True,
        "recommendedAction": "none",
        "reason": "快照采集运行正常",
    }


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
        from backend.services.market.fund_scheduler import market_fund_scheduler

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
    try:
        # 2026-09-15 重构：analyze 已内联为采集主链同步后处理链（worker 退役）。
        # 可观测口径改为链开关状态；链内每步失败进 run doc warnings（fail-visible）。
        from backend.snapshot_collector.service import _snapshot_analysis_enabled

        result["snapshotAnalysis"] = {
            "ok": True,
            "enabled": _snapshot_analysis_enabled(),
            "mode": "inline_post_persist_chain",
        }
    except Exception as exc:
        result["snapshotAnalysis"] = {"ok": False, "error": str(exc)[:200]}
    return result
