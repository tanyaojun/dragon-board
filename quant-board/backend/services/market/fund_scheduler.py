from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backend.market_proxy.akshare_fund_provider import (
    SYSTEMIC_ERRORS,
    AkshareFundBatch,
    AkshareFundProvider,
    AkshareFundProviderError,
    get_akshare_fund_provider,
)
from backend.services.market.fund_stream import MarketFundStream, get_market_fund_stream
from backend.services.market.ths_main_monitor_service import get_ths_main_monitor_service
from backend.core.settings import get_settings
from backend.snapshot_collector.trading_calendar import is_trading_day
from backend.services.theme.fund_cache import ThemeFundCache, get_theme_fund_cache


logger = logging.getLogger(__name__)
TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


class MarketFundScheduler:
    """Full-market THS fund flow refresher backed by akshare.

    One akshare call returns the whole market, so the scheduler replaces the
    old per-stock polling with a periodic full refresh. Rows are written to
    Redis with a TTL (shared across processes/restarts) and kept as last-good
    in the in-memory ThemeFundCache. Startup warmup prefetches the whole
    market once without waiting for WebSocket subscribers so the first screen
    can be served from cache immediately. Upstream failures never clear
    existing rows; they open a cooldown and expose a structured status so
    consumers can keep last-good.
    """

    def __init__(
        self,
        *,
        cache: ThemeFundCache,
        stream: MarketFundStream,
        provider: AkshareFundProvider,
        is_trading_day: Callable = is_trading_day,
        now: Callable[[], datetime] | None = None,
        min_refresh_interval_seconds: float = 60.0,
        refresh_interval_seconds: float = 300.0,
        systemic_cooldown_seconds: float = 300.0,
        fetch_timeout_seconds: float = 60.0,
        save_timeout_seconds: float = 30.0,
        max_pending_save_rows: int = 30000,
        enabled: bool = True,
        # THS L2 单票补充服务（2026-08-12 用户确认）：akshare 网页源不全，
        # 订阅池里 akshare 全量结果缺失的票主动用 THS L2 补（不能查看才刷新）
        ths_service: Any | None = None,
        max_ths_backfill_per_cycle: int = 20,
    ) -> None:
        self.cache = cache
        self.stream = stream
        self.provider = provider
        self._ths_service = ths_service
        self.max_ths_backfill_per_cycle = max(1, int(max_ths_backfill_per_cycle))
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
        self._task = asyncio.create_task(
            self._warmup_then_run(),
            name="market-fund-scheduler",
        )

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._task = None

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
            return False

        self._next_refresh_at = now_ts + self.min_refresh_interval_seconds
        self._record_request(now_ts)
        try:
            batch = await asyncio.wait_for(
                self.provider.fetch_all(session_date=session_date),
                timeout=self.fetch_timeout_seconds,
            )
        except asyncio.TimeoutError:
            # 上游挂起不能拖死调度器：超时熔断 + 冷却，状态结构化可见
            self._last_error = "ths_timeout"
            self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
            return True
        except AkshareFundProviderError as error:
            self._last_error = error.code
            if error.code in SYSTEMIC_ERRORS:
                self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
            return True
        except Exception:
            logger.exception("market fund akshare refresh failed unexpectedly")
            self._last_error = "unexpected_fetch_error"
            self._circuit_open_until = now_ts + self.systemic_cooldown_seconds
            return True

        if not batch.rows:
            # 空批次视为质量问题而非成功：保留 last-good、状态暴露原因，min 间隔后重试
            self._last_error = "empty_batch"
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

        # akshare 全量缺失票 THS L2 补充（2026-08-12 用户确认）
        await self._backfill_missing_with_ths(saved_rows, session_date)

        self._primed = True
        self._final_session_date = session_date
        if after_close:
            self._finalized = True
        if intraday:
            self._next_refresh_at = now_ts + self.refresh_interval_seconds
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
        batch: AkshareFundBatch,
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

    async def _backfill_missing_with_ths(
        self,
        saved_rows: list[dict[str, object]],
        session_date: str,
    ) -> None:
        """akshare 全量缺失票 THS L2 补充（2026-08-12 用户确认）。

        判断逻辑：订阅池（行情列表）中 akshare 全量结果缺失、且 Redis 无
        session_date 行的票，主动用 THS L2 单票接口（load_summary_row）补；
        THS 也无数据（新股未上市等）则跳过，下轮再试。单轮上限防批量缺失
        时打爆 THS 30 req/min 预算。
        """
        if not saved_rows or self._ths_service is None:
            return
        saved_codes = {str(row.get("code")) for row in saved_rows}
        pool_codes = set(self.stream.market_codes())
        missing = sorted(code for code in pool_codes if code not in saved_codes)
        if not missing:
            return
        # 排除 Redis 已有 session_date 行的（之前 THS 补过/其它来源已有），不重复补
        cached = self.cache.get_latest(missing)
        missing = [
            code
            for code in missing
            if str((cached.get(code) or {}).get("sessionDate") or "") != session_date
        ]
        if not missing:
            return
        for code in missing[: self.max_ths_backfill_per_cycle]:
            try:
                row = await self._ths_service.load_summary_row(code)
            except Exception:
                continue
            if not row or row.get("zlje") is None:
                continue
            try:
                saved = self.cache.put(dict(row))
                self.stream.publish([saved])
            except ValueError:
                continue

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
            "running": self._task is not None,
            "source": "akshare_ths_individual",
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


market_fund_scheduler = MarketFundScheduler(
    cache=get_theme_fund_cache(),
    stream=get_market_fund_stream(),
    provider=get_akshare_fund_provider(),
    refresh_interval_seconds=get_settings().theme_fund_refresh_interval_seconds,
    fetch_timeout_seconds=get_settings().market_fund_fetch_timeout_seconds,
    # akshare 全量缺失票 THS L2 单票补充（2026-08-12 用户确认）
    ths_service=get_ths_main_monitor_service(),
)
