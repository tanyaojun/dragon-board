from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backend.market_proxy.akshare_fund_provider import (
    SYSTEMIC_ERRORS as AKSHARE_SYSTEMIC_ERRORS,
)
from backend.market_proxy.akshare_fund_provider import get_akshare_fund_provider
from backend.market_proxy.eastmoney_fund_provider import (
    SYSTEMIC_ERRORS as EASTMONEY_SYSTEMIC_ERRORS,
)
from backend.market_proxy.eastmoney_fund_provider import get_eastmoney_fund_provider
from backend.services.market.fund_stream import MarketFundStream, get_market_fund_stream
from backend.core.settings import get_settings
from backend.snapshot_collector.trading_calendar import is_trading_day
from backend.services.theme.fund_cache import ThemeFundCache, get_theme_fund_cache


logger = logging.getLogger(__name__)
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketFundScheduler:
    """theme_fund 题材主力资金全市场刷新调度器。

    上游可插拔（2026-XX 用户确认题材主力资金切换东财口径）：
    - 默认 ``EastmoneyFundProvider``：东财 push2 ulist.np 批量（httpx 独立
      URL 直连，不走 akshare），universe 用腾讯全市场行情缓存；风控纪律
      （串行 + 请求间隔 + 命中 429 立即中止）由 provider 内部保证，调度器
      收到系统性错误/截断标记即熔断冷却，不会短时间连续打东财 API；
    - 回退 ``AkshareFundProvider``（QUANT_BOARD_THEME_FUND_SOURCE=akshare）：
      akshare 同花顺网页个股资金流，一次调用返回全市场。

    行写入 Redis theme-fund 题材 hash（TTL，跨进程/重启共享）+ 进程内
    last-good。启动预热在无订阅者时也抓一轮，题材聚合首屏可直接命中。
    上游失败从不清空已有行；打开冷却并暴露结构化 status，消费方 keep last-good。
    """

    def __init__(
        self,
        *,
        cache: ThemeFundCache,
        stream: MarketFundStream,
        provider: Any,
        is_trading_day: Callable = is_trading_day,
        now: Callable[[], datetime] | None = None,
        min_refresh_interval_seconds: float = 60.0,
        refresh_interval_seconds: float = 300.0,
        systemic_cooldown_seconds: float = 300.0,
        fetch_timeout_seconds: float = 60.0,
        save_timeout_seconds: float = 90.0,
        max_pending_save_rows: int = 30000,
        enabled: bool = True,
        systemic_error_codes: frozenset[str] | None = None,
    ) -> None:
        self.cache = cache
        self.stream = stream
        # provider 鸭子类型：fetch_all(*, session_date, codes=None) →
        # batch(rows/failures/fetched_at_ms/session_date/source[/truncated_by])；
        # 失败异常带 .code 结构化错误码（Akshare/Eastmoney provider 均满足）。
        self.provider = provider
        # 系统性错误码合并两源命名空间（ems/ths 前缀不同，合并不会误伤），
        # 显式传参仍可覆盖（测试用）。
        self._systemic_error_codes = systemic_error_codes or (
            AKSHARE_SYSTEMIC_ERRORS | EASTMONEY_SYSTEMIC_ERRORS
        )
        self._is_trading_day = is_trading_day
        self._now = now or (lambda: datetime.now(TZ_SHANGHAI))
        self.min_refresh_interval_seconds = max(30.0, float(min_refresh_interval_seconds))
        self.refresh_interval_seconds = max(
            self.min_refresh_interval_seconds,
            float(refresh_interval_seconds),
        )
        self.systemic_cooldown_seconds = max(30.0, float(systemic_cooldown_seconds))
        self.fetch_timeout_seconds = max(10.0, float(fetch_timeout_seconds))
        self.save_timeout_seconds = max(5.0, float(save_timeout_seconds))
        self.max_pending_save_rows = max(1000, int(max_pending_save_rows))
        self.enabled = enabled
        self._next_refresh_at = 0.0
        self._circuit_open_until = 0.0
        self._current_session_date: str | None = None
        self._primed = False
        self._finalized = False
        self._final_session_date: str | None = None
        self._last_error: str | None = None
        self._last_saved_at: float | None = None
        self._last_session_date: str | None = None
        self._last_row_count = 0
        self._last_code: str | None = None
        self._parse_failure_count = 0
        self._parse_failure_samples: list[dict[str, object]] = []
        self._request_times: list[float] = []
        self._pending_save_rows: list[dict[str, object]] = []
        self._pending_save_dropped = 0
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.enabled or (self._task and not self._task.done()):
            return
        if not get_settings().theme_fund_seed_enabled:
            # 题材主力资金全市场源开关（东财默认 / akshare 回退）；关闭时跳过刷新，
            # 冷启动改从 Redis dump.rdb 恢复 L2 数据（见 docs/theme-module 资金源口径文档）。
            logger.info(
                "theme_fund source disabled (QUANT_BOARD_THEME_FUND_SEED_ENABLED=false); skip %s refresh",
                self.provider_source(),
            )
            return
        self._task = asyncio.create_task(
            self._warmup_then_run(),
            name="market-fund-scheduler",
        )

    def provider_source(self) -> str:
        """当前 provider 的数据源标识（无 source 属性的 stub 返回 unknown）。"""
        return str(getattr(self.provider, "source", "") or "unknown")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None
        # provider 自有资源（如东财 provider 的 owned httpx.Client）随停释放；
        # 无 close 的 provider（akshare/stub）静默跳过
        close = getattr(self.provider, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                logger.warning("fund provider close failed", exc_info=True)

    async def run_once(self, *, ignore_subscribers: bool = False) -> bool:
        codes = self.stream.market_codes()
        if not codes and not ignore_subscribers:
            return False
        current = self._now()
        now_ts = current.timestamp()
        if now_ts < max(self._next_refresh_at, self._circuit_open_until):
            return False

        try:
            trading_day = await asyncio.to_thread(self._is_trading_day, current.date())
        except Exception:
            # Calendar unavailable: keep last-good rows and surface the reason.
            self._last_error = "trading_calendar_unavailable"
            self._next_refresh_at = now_ts + self.min_refresh_interval_seconds
            return True

        session_date = self._resolve_session_date(current.date(), trading_day)
        if session_date != self._current_session_date:
            self._current_session_date = session_date
            self._primed = False
            self._finalized = False
            self._final_session_date = None

        minute = current.hour * 60 + current.minute
        intraday = trading_day and (570 <= minute <= 690 or 780 <= minute < 900)
        after_close = trading_day and 900 <= minute <= 930

        if intraday and self._primed:
            if now_ts < self._next_refresh_at:
                return False
        elif after_close and self._finalized:
            return False
        elif not intraday and not after_close and self._primed:
            # 盘后暂停——但题材估算源缓存缺失（重启后 RDB 无此 key/被误清）时
            # 冷启动拉一次填充（2026-08-12 修复：否则题材资金空直到下个交易日）
            if self.cache.has_akshare_redis_data():
                return False
            logger.info(
                "theme-fund %s cache missing; cold-start refresh outside trading hours",
                self.provider_source(),
            )
            self._primed = False

        self._next_refresh_at = now_ts + self.min_refresh_interval_seconds
        self._record_request(now_ts)
        try:
            batch = await asyncio.wait_for(
                self.provider.fetch_all(session_date=session_date),
                timeout=self.fetch_timeout_seconds,
            )
        except asyncio.TimeoutError:
            # 上游挂起不能拖死调度器：超时熔断 + 冷却，状态结构化可见
            self._last_error = "fund_fetch_timeout"
            self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
            return True
        except Exception as error:
            code = getattr(error, "code", None)
            if isinstance(code, str) and code:
                # provider 结构化错误（akshare ths_* / 东财 em_*）：
                # 系统性错误（限流/风控/上游故障）打开熔断冷却，不短时间重打 API
                self._last_error = code
                if code in self._systemic_error_codes:
                    self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
                return True
            logger.exception("market fund refresh failed unexpectedly")
            self._last_error = "unexpected_fetch_error"
            self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
            return True

        truncated_by = str(getattr(batch, "truncated_by", "") or "")
        if truncated_by:
            # provider 中止剩余批次：系统性错误（限流/风控/上游故障）另加熔断冷却；
            # 非系统性截断（连续超时/坏负载，典型为东财拦截页）同样必须暴露原因，
            # 不能因为 status 尾部“成功清理”而被冲掉（fail-visible）。
            self._last_error = truncated_by
            if truncated_by in self._systemic_error_codes:
                self._circuit_open_until = now_ts + self.systemic_cooldown_seconds

        if not batch.rows:
            # 空批次视为质量问题而非成功：保留 last-good、状态暴露原因与批级失败，
            # min 间隔后重试。早退前同步 parse failure 计数，避免截断轮失败完全不可见。
            if not truncated_by:
                self._last_error = "empty_batch"
            self._parse_failure_count = len(batch.failures)
            self._parse_failure_samples = list(batch.failures)[:10]
            return True

        saved_rows: list[dict[str, object]] = []
        validation_failures: list[dict[str, object]] = []

        # 1) 先重试上次保存超时的原始行：不丢弃、先落地（fail-visible）
        if self._pending_save_rows:
            pending = self._pending_save_rows
            self._pending_save_rows = []
            try:
                pending_saved, pending_failures = await asyncio.wait_for(
                    self._save_rows(pending),
                    timeout=self.save_timeout_seconds,
                )
            except asyncio.TimeoutError:
                self._pending_save_rows = self._retain_pending(pending)
                self._last_error = "save_retry_timeout"
                self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
                return True
            saved_rows.extend(pending_saved)
            validation_failures.extend(pending_failures)

        # 2) 保存本轮新数据：超时进入待重试缓冲，不清空 last-good，下个周期重试
        try:
            new_saved, new_failures = await asyncio.wait_for(
                self._save_batch(batch),
                timeout=self.save_timeout_seconds,
            )
        except asyncio.TimeoutError:
            self._pending_save_rows = self._retain_pending(batch.rows)
            self._last_error = "save_timeout"
            self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
            return True
        saved_rows.extend(new_saved)
        validation_failures.extend(new_failures)

        if saved_rows:
            self.stream.publish(saved_rows)

        self._primed = True
        self._final_session_date = session_date
        if after_close:
            self._finalized = True
        if intraday:
            self._next_refresh_at = now_ts + self.refresh_interval_seconds
        # truncated（provider 中止）：保留中止原因，不得被成功状态冲掉。
        # 另：行源与 provider 不一致（如当日盘中从东财切回 akshare 时，同日旧
        # eastmoney 行因 rank 高者权威仍被原样返回/推送）必须结构化暴露——
        # rank 语义决定切源回退需跨交易日生效，运维需从 status 看到陈旧信号。
        if truncated_by:
            pass  # last_error 已在上面设置，不得清空
        else:
            stale_source = str(getattr(self.provider, "source", "") or "")
            if stale_source and any(
                str(row.get("moneyFlowSource") or "") != stale_source for row in saved_rows
            ):
                self._last_error = "provider_source_stale_rows"
            else:
                self._last_error = None
        self._last_saved_at = now_ts
        self._last_session_date = session_date
        self._last_row_count = len(saved_rows)
        self._last_code = str(saved_rows[-1].get("code") or "") if saved_rows else None
        self._parse_failure_count = len(batch.failures) + len(validation_failures)
        self._parse_failure_samples = (batch.failures + validation_failures)[:10]
        return True

    async def _warmup_then_run(self) -> None:
        """启动预热：立即抓取一轮全市场资金流写入 Redis，首屏可直接命中；随后进入正常周期。"""
        try:
            await self.run_once(ignore_subscribers=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("market fund warmup cycle failed")
        await self._run()

    async def _save_batch(
        self,
        batch: Any,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        return await self._save_rows(batch.rows)

    async def _save_rows(
        self,
        rows: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        # 批量 pipeline 写入：单次 to_thread + 单次锁 + 单次 hmget/pipeline/incrby，
        # 替代逐行 3 次 Redis 往返；非法行由 put_many 以 failures 返回，不阻断其余行。
        return await asyncio.to_thread(
            self.cache.put_many,
            [dict(row) for row in rows],
        )

    def _retain_pending(
        self,
        rows: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        """保留待重试行：超上限时丢弃最旧行并计数（全市场刷新成功后会被新数据覆盖）。"""
        merged = self._pending_save_rows + rows
        overflow = max(0, len(merged) - self.max_pending_save_rows)
        if overflow:
            self._pending_save_dropped += overflow
            merged = merged[-self.max_pending_save_rows :]
        return merged

    def _resolve_session_date(self, today: date, trading_day: bool) -> str:
        if trading_day:
            return today.isoformat()
        if self._last_session_date:
            return self._last_session_date
        # First run on a non-trading day: walk back to the latest trading day.
        candidate = today
        for _ in range(10):
            candidate = candidate - timedelta(days=1)
            try:
                if self._is_trading_day(candidate):
                    return candidate.isoformat()
            except Exception:
                break
        return today.isoformat()

    def _record_request(self, now_ts: float) -> None:
        self._request_times.append(now_ts)
        self._request_times = [ts for ts in self._request_times if now_ts - ts < 60]

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "seedEnabled": get_settings().theme_fund_seed_enabled,
            "running": self._task is not None,
            # 数据源诚实标识：东财默认源 / akshare 回退源按实际 provider 暴露；
            # configuredSource 便于核对 env 覆盖是否生效
            "source": self.provider_source(),
            "configuredSource": get_settings().theme_fund_source,
            "queueLength": len(self.stream.market_codes()),
            "currentCode": self._last_code,
            "requestsLastMinute": len(self._request_times),
            "circuitOpenUntil": self._circuit_open_until,
            "lastError": self._last_error,
            "refreshIntervalSeconds": self.refresh_interval_seconds,
            "lastSavedAt": self._last_saved_at,
            "lastSessionDate": self._last_session_date,
            "primedCodes": self._last_row_count,
            "lastRowCount": self._last_row_count,
            "parseFailureCount": self._parse_failure_count,
            "parseFailureSamples": self._parse_failure_samples,
            "pendingSaveCount": len(self._pending_save_rows),
            "pendingSaveDropped": self._pending_save_dropped,
        }

    async def _ensure_redis_cache_alive(self) -> None:
        """theme-fund:akshare key 缺失时用内存 akshare last-good 写回 Redis（零上游请求）。

        2026-08-12：Redis 资金缓存 key 曾被误清/丢失导致资金列空；盘后
        调度器暂停不写，key 缺失时这里从进程内 akshare last-good 恢复，保证题材可读。
        2026-08-14：akshare 题材源独立 hash，恢复逻辑改针对 akshare；
        L2 latest 由 ThsFundRefreshScheduler._ensure_latest_cache_alive
        （内存 last-good 写回 Redis latest，run_once 每次调用）负责。
        """
        try:
            if not self.cache.has_akshare_redis_data():
                rows = self.cache.akshare_memory_rows()
                if rows:
                    saved, _failures = self.cache.put_many(rows)
                    if saved:
                        self.stream.publish(saved)
                        logger.info("restored theme-fund akshare cache from last-good: %s rows", len(saved))
        except Exception:
            logger.exception("ensure theme-fund akshare cache alive failed")

    async def _run(self) -> None:
        while True:
            try:
                has_work = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market fund scheduler cycle failed")
                has_work = False
            if has_work:
                await asyncio.sleep(self.min_refresh_interval_seconds)
            else:
                self.stream.codes_changed.clear()
                wait_for = min(120.0, self.refresh_interval_seconds)
                try:
                    await asyncio.wait_for(self.stream.codes_changed.wait(), timeout=wait_for)
                except asyncio.TimeoutError:
                    pass
            # Redis 资金缓存存活检查（key 被误清/丢失时用内存 last-good 写回）
            await self._ensure_redis_cache_alive()


def _build_default_provider() -> Any:
    """按 QUANT_BOARD_THEME_FUND_SOURCE 选择题材主力资金上游。

    默认 eastmoney（东财 push2 独立 URL 直连）；akshare 保留为显式回退。
    """
    settings = get_settings()
    if settings.theme_fund_source == "eastmoney":
        return get_eastmoney_fund_provider()
    return get_akshare_fund_provider()


def _build_market_fund_scheduler() -> MarketFundScheduler:
    settings = get_settings()
    # 东财风控专用参数（2026-09-30 二次论断）:
    # - 刷新周期 1800s（30 分钟一轮，轮内约 6 分钟完成、其余静默），
    #   独立于 akshare 模式的 theme_fund_refresh_interval_seconds（300s）；
    # - 断连/限流冷却 1800s：push2 断连即已被风控，半小时内不再碰
    #   （2026-09-30 盘中实透：短冷却重试反复刺激 WAF，IP 被临时拉黑）；
    # - fetch 预算 600s：覆盖最坏 6×60s 批间距 + 7×15s 响应超时 ≈ 465s，
    #   避免正常慢轮被半路抬新断（to_thread 僵尸线程跑完但结果被丢）。
    eastmoney_mode = settings.theme_fund_source == "eastmoney"
    return MarketFundScheduler(
        cache=get_theme_fund_cache(),
        stream=get_market_fund_stream(),
        provider=_build_default_provider(),
        refresh_interval_seconds=(
            settings.theme_fund_em_refresh_interval_seconds
            if eastmoney_mode
            else settings.theme_fund_refresh_interval_seconds
        ),
        fetch_timeout_seconds=(
            max(600.0, settings.market_fund_fetch_timeout_seconds)
            if eastmoney_mode
            else settings.market_fund_fetch_timeout_seconds
        ),
        systemic_cooldown_seconds=1800.0 if eastmoney_mode else 300.0,
    )


market_fund_scheduler = _build_market_fund_scheduler()
