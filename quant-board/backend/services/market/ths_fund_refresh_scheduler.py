from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from backend.core.settings import get_settings
from backend.data.repositories.fund_flow_repository import FundFlowRepository
from backend.services.market.fund_stream import MarketFundStream, get_market_fund_stream
from backend.services.market.ths_fund_flow_buckets import (
    aggregate_l2_buckets,
    build_l2_persist_doc,
    parse_l2_summary,
)
from backend.services.market.ths_main_monitor_service import (
    ThsMainMonitorError,
    ThsMainMonitorService,
    get_ths_main_monitor_service,
)
from backend.services.theme.fund_cache import ThemeFundCache, get_theme_fund_cache

logger = logging.getLogger(__name__)
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# 系统性上游故障：进入全局冷却 + 并发降 1（与 2026-07-25 设计一致）
SYSTEMIC_THS_ERRORS = frozenset(
    {"ths_rate_limited", "ths_captcha_required", "ths_upstream_unavailable"}
)
# THS 单票约 30 req/min 限流：展示池 200 只全刷一轮约 6-7 分钟
DEFAULT_REFRESH_INTERVAL_SECONDS = 180.0
DEFAULT_RETRY_BACKOFF_SECONDS = (30, 60, 120, 300)


class ThsFundRefreshScheduler:
    """mainMonitorDetail 展示池资金刷新调度器（L2 主源）。

    链路：浏览器 fund-stream 订阅 codes → ``MarketFundStream.market_codes()``
    → 本调度器按到期队列分批（每批 ≤5、并发 ≤2）进程内直调
    ``ThsMainMonitorService``（不经 HTTP 回环）→ 写 ``ThemeFundCache``
    （source=ths_main_monitor，L2 口径），覆盖 akshare 网页口径种子
    （ths_web_seed）。

    限流与失败（沿用 2026-07-25 设计参数）：
    - 每批成功后按 ``batch_interval_seconds`` 摊薄请求节奏，贴合 30 req/min；
    - 单票失败退避 30→60→120→300 秒，只影响该股票；
    - 系统性限流/验证码/上游不可用 → 全局冷却 + 并发降 1，
      连续 3 批成功自动恢复并发 2；
    - 任何失败都不清空 last-good，写缓存被拒时保留既有行（fail-visible）。
    """

    def __init__(
        self,
        *,
        service: ThsMainMonitorService,
        cache: ThemeFundCache,
        stream: MarketFundStream,
        now: Callable[[], datetime] | None = None,
        batch_size: int = 5,
        base_concurrency: int = 2,
        refresh_interval_seconds: float = DEFAULT_REFRESH_INTERVAL_SECONDS,
        batch_timeout_seconds: float = 15.0,
        systemic_cooldown_seconds: float = 30.0,
        retry_backoff_seconds: tuple[float, ...] = DEFAULT_RETRY_BACKOFF_SECONDS,
        enabled: bool = True,
        fund_repo: FundFlowRepository | None = None,
        mongo_write_timeout_seconds: float = 5.0,
    ) -> None:
        self._service = service
        self._cache = cache
        self._stream = stream
        # 刷新范围 = 前端 fund-stream 订阅池（2026-08-11 用户确认：取消热度池，
        # 只刷行情列表股票——订阅池即行情列表全部，全量轮转覆盖）。
        # 2026-08-14 用户确认：取消 P0/P1 分级与前 100 白名单，全列表统一刷新。
        self._now = now or (lambda: datetime.now(TZ_SHANGHAI))
        self._batch_size = max(1, min(5, int(batch_size)))
        self._base_concurrency = max(1, min(2, int(base_concurrency)))
        self._refresh_interval_seconds = max(30.0, float(refresh_interval_seconds))
        self._batch_timeout_seconds = max(1.0, float(batch_timeout_seconds))
        self._systemic_cooldown_seconds = max(10.0, float(systemic_cooldown_seconds))
        self._retry_backoff_seconds = tuple(float(v) for v in (retry_backoff_seconds or (30,)))
        # 批间间隔：让每批请求节奏贴合 30 req/min 限流预算
        self._batch_interval_seconds = max(
            1.0,
            self._batch_size / 30.0 * 60.0,
        )
        self.enabled = enabled
        self._fund_repo = fund_repo
        # MongoDB upsert 超时：MongoDB 挂起（TCP 不响应）时不拖慢刷新节奏
        self._mongo_write_timeout_seconds = max(0.5, float(mongo_write_timeout_seconds))

        self._next_refresh_at: dict[str, float] = {}
        self._retry_at: dict[str, float] = {}
        self._fail_count: dict[str, int] = {}
        self._effective_concurrency = self._base_concurrency
        self._consecutive_batch_success = 0
        self._circuit_open_until = 0.0
        self._last_error: str | None = None
        self._last_row_count = 0
        self._last_session_date: str | None = None
        self._task: asyncio.Task[None] | None = None
        # L8（2026-08-11 审计）：MongoDB 唯一索引在首次 run_once 异步 ensure（带超时），
        # 避免单例创建时同步阻塞启动
        self._indexes_ensured = False

    def start(self) -> None:
        if not self.enabled or (self._task and not self._task.done()):
            return
        self._task = asyncio.create_task(
            self._run(),
            name="ths-fund-refresh-scheduler",
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

    async def run_once(self) -> bool:
        now_dt = self._now()
        if not self._indexes_ensured and self._fund_repo is not None:
            self._indexes_ensured = True
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._fund_repo.ensure_indexes),
                    timeout=5.0,
                )
            except Exception:
                self._indexes_ensured = False  # 失败下次重试；缺唯一索引不影响本轮刷新
                logger.exception("fund_flow_l2 ensure_indexes failed; continue without unique index")
        if not self._is_trading_time(now_dt) and not self._needs_cold_init():
            # 非交易时段（周末/午休/盘前盘后）且已初始化：暂停请求，保留 last-good。
            # 冷启动例外：非交易时段允许刷一轮——THS 接口返回最近交易日完整 L2，
            # 用于 MongoDB 空库时首屏不空（见 test_outside_trading_hours_cold_start_initializes）。
            self._last_error = "outside_trading_hours"
            return False
        now_ts = now_dt.timestamp()
        if now_ts < self._circuit_open_until:
            return False
        codes = self._pool_codes()
        if not codes:
            return False
        due = [
            code
            for code in codes
            if now_ts >= max(self._next_refresh_at.get(code, 0.0), self._retry_at.get(code, 0.0))
        ]
        if not due:
            return False
        # 均匀轮转（2026-08-11 方案 A，用户确认）：去 P0/P1 分级，全列表统一
        # 周期——列表内数据时效一致，避免综合排名对比时新旧混杂。
        # 从未刷过的股票优先（首次补齐）。
        due.sort(key=lambda code: 0 if code not in self._next_refresh_at else 1)
        batch = due[: self._batch_size]

        raw_map = await self._load_raw_batch(batch, now_ts)
        cache_rows: list[dict[str, object]] = []
        mongo_docs: list[dict[str, object]] = []
        # 非交易时段冷启动刷的那轮只进 Redis 热缓存（首屏有值），
        # 不写 MongoDB——避免依赖 THS 非交易时段行为产生垃圾文档；
        # MongoDB 只固化交易时段的盘中校准数据。
        persist_to_mongo = self._is_trading_time(now_dt) and self._fund_repo is not None
        for code, raw in raw_map.items():
            summary = parse_l2_summary(code, raw)
            if summary is None:
                # title 摘要缺失/无法解析：保留 last-good，走单票退避
                self._record_failure(code, now_ts)
                continue
            cache_rows.append(summary)
            if persist_to_mongo and not raw.get("stale"):
                # M2（2026-08-11 审计）：stale raw（上游失败回退的旧缓存）不写 MongoDB——
                # MongoDB 只固化真实拉取的数据；Redis 侧有 _is_older 保护，Mongo 侧没有，
                # stale 可能跨日，旧值不得入库。
                buckets = aggregate_l2_buckets((raw.get("data") or {}).get("list") or [])
                # M3（2026-08-11 审计）：THS list 为空或全部 <30 万时 buckets 全 0，
                # 跳过 Mongo 写入——防止全 0 覆盖历史 7 档（MongoDB 侧无 _is_older 保护），
                # Redis total 摘要照常落库（fail-visible：total 有值不空白）。
                has_bucket_activity = any(
                    (b.get("buyAmount") or 0)
                    or (b.get("sellAmount") or 0)
                    or (b.get("buyCount") or 0)
                    or (b.get("sellCount") or 0)
                    for b in buckets
                )
                if has_bucket_activity:
                    mongo_docs.append(
                        build_l2_persist_doc(
                            code,
                            raw,
                            summary,
                            buckets,
                            now_ms=int(now_ts * 1000),
                        )
                    )
        batch_ok = bool(cache_rows)
        self._consecutive_batch_success = (
            self._consecutive_batch_success + 1 if batch_ok else 0
        )

        published_rows: list[dict[str, object]] = []
        for row in cache_rows:
            code = str(row.get("code") or "")
            if not code:
                continue
            # 均匀轮转（2026-08-11 方案 A）：全列表统一 refresh_interval_seconds，
            # 到期时间按批次自然错峰（每批 5 只、批间 batch_interval_seconds），
            # 不再用随机抖动（批次错峰已足够均匀，抖动反而破坏一致性）。
            self._next_refresh_at[code] = now_ts + self._refresh_interval_seconds
            self._retry_at.pop(code, None)
            self._fail_count[code] = 0
            try:
                stored = self._cache.put(dict(row))
                published_rows.append(stored)
            except ValueError:
                # 非法行不落库：保留 last-good（fail-visible），由 fail_count 走退避。
                # M4（2026-08-11 审计）：回滚常规周期，让 retry_at(30s 起) 真正生效，
                # 否则 180s 的 _next_refresh_at 会掩盖 30s 退避。
                self._next_refresh_at.pop(code, None)
                logger.warning("THS 资金行落库被拒 code=%s，保留 last-good", code)
                self._record_failure(code, now_ts)

        if published_rows:
            # H1（2026-08-11 实盘复盘）：每批校准写入后必须 publish 到 fund-stream，
            # 前端才能实时收到 P0/P1 增量（此前只靠 300s idle 断线重连拿快照，滞后 ≤5 分钟）。
            # 推送行带单调 version（来自 ThemeFundCache.put 返回值），前端据此去重。
            self._stream.publish(published_rows)

        if mongo_docs and self._fund_repo is not None:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._fund_repo.upsert_many, mongo_docs),
                    timeout=self._mongo_write_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # MongoDB 挂起：不阻塞刷新（Redis/内存 last-good 继续更新）；
                # 后台线程幂等 upsert 完成后写入，无需额外处理
                logger.warning("fund_flow_l2 upsert timed out; keep last-good in cache/redis")
            except Exception:
                # MongoDB 写失败不阻塞刷新：缓存/Redis last-good 继续可用
                logger.exception("fund_flow_l2 upsert failed; keep last-good in cache/redis")

        if self._consecutive_batch_success >= 3 and self._effective_concurrency < self._base_concurrency:
            self._effective_concurrency = self._base_concurrency
            await self._service.set_effective_concurrency(self._base_concurrency)

        self._last_error = None if batch_ok else self._last_error
        self._last_row_count = len(cache_rows)
        if cache_rows:
            self._last_session_date = str(cache_rows[0].get("sessionDate") or self._last_session_date or "")
        return True

    def _pool_codes(self) -> list[str]:
        """刷新范围 = 前端 fund-stream 订阅池（行情列表全部，2026-08-11 用户确认
        取消热度池——只刷行情列表股票，全量轮转覆盖）。"""
        return sorted(set(self._stream.market_codes()))


    async def _load_raw_batch(self, codes: list[str], now_ts: float) -> dict[str, dict]:
        """并发 load_raw（每只独立超时），返回成功 raw 的 code→raw 映射。

        单票失败/超时记录退避；系统性错误（限流/验证码/上游不可用）进入全局冷却。
        并发任务各自返回错误码，汇总时取最严重错误（systemic > timeout），
        避免共享 ``_last_error`` 被并发覆盖导致限流被 timeout 掩盖（2026-08-08 review）。
        """
        semaphore = asyncio.Semaphore(self._effective_concurrency)

        async def one(code: str) -> tuple[str, dict | None, str | None]:
            async with semaphore:
                try:
                    raw = await asyncio.wait_for(
                        self._service.load_raw(code),
                        timeout=self._batch_timeout_seconds,
                    )
                    return code, raw, None
                except asyncio.TimeoutError:
                    return code, None, "ths_timeout"
                except ThsMainMonitorError as error:
                    return code, None, error.code
                except Exception:
                    logger.exception("ths load_raw failed for %s", code)
                    return code, None, "unexpected_fetch_error"

        outcomes = await asyncio.gather(*(one(code) for code in codes))
        raw_map: dict[str, dict] = {}
        systemic = False
        last_error: str | None = None
        for code, raw, error_code in outcomes:
            if error_code is None:
                raw_map[code] = raw
                continue
            self._record_failure(code, now_ts)
            if error_code in SYSTEMIC_THS_ERRORS:
                systemic = True
                # systemic 错误码优先级最高：后续 timeout/unexpected 不再覆盖
                last_error = error_code
            elif last_error is None or last_error not in SYSTEMIC_THS_ERRORS:
                last_error = error_code
        if systemic:
            self._last_error = last_error
            await self._enter_systemic_cooldown(now_ts)
        elif last_error is not None:
            self._last_error = last_error
        return raw_map

    def _record_failure(self, code: str, now_ts: float) -> None:
        count = self._fail_count.get(code, 0) + 1
        self._fail_count[code] = count
        backoff = self._retry_backoff_seconds[min(count - 1, len(self._retry_backoff_seconds) - 1)]
        self._retry_at[code] = now_ts + backoff

    async def _enter_systemic_cooldown(self, now_ts: float) -> None:
        self._circuit_open_until = now_ts + self._systemic_cooldown_seconds
        self._effective_concurrency = 1
        self._service.enter_cooldown(self._systemic_cooldown_seconds)
        await self._service.set_effective_concurrency(1)

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "running": self._task is not None,
            "source": "ths_main_monitor",
            "mongoPersistEnabled": self._fund_repo is not None,
            "universeCount": len(self._pool_codes()),
            "ownerState": self._owner_state(),
            "cachedCount": len(self._next_refresh_at),
            "effectiveConcurrency": self._effective_concurrency,
            "circuitOpenUntil": self._circuit_open_until,
            "lastError": self._last_error,
            "refreshIntervalSeconds": self._refresh_interval_seconds,
            "batchSize": self._batch_size,
            "lastRowCount": self._last_row_count,
            "lastSessionDate": self._last_session_date,
        }

    def _owner_state(self) -> str:
        """active=有活跃订阅者；persisted=订阅者已断开但按最后池继续刷；none=从未有 owner。"""
        if self._stream.has_active_owner():
            return "active"
        if self._stream.market_codes():
            return "persisted"
        return "none"

    def _needs_cold_init(self) -> bool:
        """非交易时段冷启动例外：展示池还有未刷过的码时允许继续刷，
        直到全池都有最近交易日 L2（首屏资金列不空），然后暂停。

        修复 2026-08-08 首屏只有数笔：原实现"从未刷过才刷一轮"（batch=5），
        233 只展示池只刷 5 只就暂停；现改为按展示池未刷新码持续补齐。
        M1（2026-08-11 审计）：仅当缓存已有**最近交易日**行（MongoDB 冷启动
        restore 或上次冷刷已补齐）时才视为已初始化——**TTL 内未失效的旧交易日
        缓存不算**，否则盘后重启会一直显示旧数据直到下一交易时段（实盘验证
        2026-08-11：Redis 有 08-10 缓存，08-11 盘后重启后 cachedCount=0 且
        调度器暂停，页面显示旧值）。
        """
        codes = self._pool_codes()
        if not codes:
            return False
        if not any(code not in self._next_refresh_at for code in codes):
            return False
        try:
            cached = self._cache.get_latest(codes)
            if cached:
                latest_session = max(
                    (str(row.get("sessionDate") or "") for row in cached.values()),
                    default="",
                )
                if latest_session == self._latest_trading_day(self._now()):
                    return False
        except Exception:
            pass
        return True

    @staticmethod
    def _latest_trading_day(now: datetime) -> str:
        """最近一个工作日（忽略节假日近似）：周末/盘后回退到最近周五/当天。"""
        day = now.date()
        while day.weekday() >= 5:
            day -= timedelta(days=1)
        return day.isoformat()

    @staticmethod
    def _is_trading_time(now: datetime) -> bool:
        """A 股交易时段：周一至周五 09:30-11:30、13:00-15:00（分钟级）。"""
        if now.weekday() >= 5:
            return False
        minutes = now.hour * 60 + now.minute
        return (9 * 60 + 30) <= minutes <= (11 * 60 + 30) or (13 * 60) <= minutes <= (15 * 60)

    @staticmethod
    def _seconds_until_next_trading_time(now: datetime) -> float:
        """距下一个交易时段开始（含跨午休/跨日/跨周末）的秒数，最多覆盖 7 天。"""
        candidate = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(7 * 24 * 60):
            if ThsFundRefreshScheduler._is_trading_time(candidate):
                return max(1.0, (candidate - now).total_seconds())
            candidate += timedelta(minutes=1)
        return 3600.0  # 兜底（正常情况下不会到达）

    async def _run(self) -> None:
        while True:
            try:
                has_work = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("ths fund refresh scheduler cycle failed")
                has_work = False
            if has_work:
                await asyncio.sleep(self._batch_interval_seconds)
            else:
                await self._wait_for_work()

    async def _wait_for_work(self) -> None:
        wait_seconds = self._compute_wait_seconds()
        # wait 前清除，避免上次事件未消费导致忙循环；新订阅/更新会再次 set 提前唤醒
        self._stream.codes_changed.clear()
        try:
            await asyncio.wait_for(self._stream.codes_changed.wait(), timeout=wait_seconds)
        except asyncio.TimeoutError:
            pass

    def _compute_wait_seconds(self) -> float:
        now_dt = self._now()
        if not self._is_trading_time(now_dt):
            # 非交易时段：L5（2026-08-11 审计）一觉睡到下一个交易时段开始
            # （跨午休/跨日/跨周末），不再每小时空转一次
            return max(1.0, self._seconds_until_next_trading_time(now_dt))
        now_ts = now_dt.timestamp()
        horizon = self._refresh_interval_seconds
        for code in self._pool_codes():
            due = max(self._next_refresh_at.get(code, 0.0), self._retry_at.get(code, 0.0))
            if due > 0:
                horizon = min(horizon, max(0.0, due - now_ts))
        return max(1.0, min(horizon, self._refresh_interval_seconds))


_ths_fund_refresh_scheduler: ThsFundRefreshScheduler | None = None


def get_ths_fund_refresh_scheduler() -> ThsFundRefreshScheduler:
    global _ths_fund_refresh_scheduler
    if _ths_fund_refresh_scheduler is None:
        fund_repo = None
        if get_settings().storage_backend == "mongodb":
            from backend.data.repositories.fund_flow_repository import FundFlowRepository
            from backend.data.repositories.repository_factory import get_runtime_mongodb_database

            fund_repo = FundFlowRepository(get_runtime_mongodb_database())
            # L8（2026-08-11 审计）：ensure_indexes 移到 run_once 异步执行（带超时），
            # 不在单例创建时同步阻塞启动；MongoDB 故障仅告警（Redis/内存 last-good 继续工作）
        _ths_fund_refresh_scheduler = ThsFundRefreshScheduler(
            service=get_ths_main_monitor_service(),
            cache=get_theme_fund_cache(),
            stream=get_market_fund_stream(),
            fund_repo=fund_repo,
        )
    return _ths_fund_refresh_scheduler


async def close_ths_fund_refresh_scheduler() -> None:
    global _ths_fund_refresh_scheduler
    scheduler = _ths_fund_refresh_scheduler
    _ths_fund_refresh_scheduler = None
    if scheduler is not None:
        await scheduler.stop()
