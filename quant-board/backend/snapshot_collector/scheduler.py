"""Automatic background scheduler for snapshot collection.

Uses a next-slot timer: calculates the upcoming snapshot time, sleeps until
then, and collects all slots that become due at that instant.  Falls back to
idle recheck on non-trading days.

The scheduler auto-disables itself when the storage backend is not MongoDB
or when ``snapshot_collector_enabled`` is False.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import logging
import time
from typing import Any

from backend.core.settings import get_settings
from backend.snapshot_collector.trading_calendar import TZ_SHANGHAI


logger = logging.getLogger(__name__)

# Wake exactly at slot time — no advance (avoids busy-loop when slot isn't eligible yet)
_ADVANCE_SECONDS = 0
# Max idle sleep on a non-trading day before re-checking (seconds)
_IDLE_RECHECK_SECONDS = 1800


class SnapshotCollectorScheduler:
    """Background async runner driven by the next-snapshot-slot timer.

    Instead of polling, the scheduler computes the next due slot, sleeps
    precisely until that moment, then fires a collection.  Multiple types
    that share the same ``HH:MM`` are collected in the same wake-up.
    """

    def __init__(self) -> None:
        settings = get_settings()
        backend_ok = settings.storage_backend == "mongodb"
        self.enabled = backend_ok and settings.snapshot_collector_enabled
        self.dataset_id = settings.snapshot_collector_dataset_id
        self.snapshot_types = [
            t.strip() for t in settings.snapshot_collector_types.split(",") if t.strip()
        ]
        self.grace_minutes = settings.snapshot_collector_close_grace_minutes
        # 单槽位采集整体超时：provider 串行（6 个）× 单个 provider 预算 + 落库缓冲。
        # 超时后槽位不标 completed，下一轮定时器在 grace 窗口内自动重试。
        self.collect_timeout_seconds = max(
            60.0,
            float(settings.snapshot_collector_provider_timeout_ms) / 1000.0 * 6 + 60.0,
        )
        self._task: asyncio.Task[None] | None = None
        self._in_flight_slots: set[str] = set()
        self._last_run_at: str | None = None
        self._last_slot_collected: str | None = None
        self._last_error: str | None = None
        self._last_error_at: str | None = None
        self._last_error_slot: str | None = None
        self._collection_count: int = 0
        self._error_count: int = 0
        # 同刻多类型共享一次采集；全局信号量保证不同时刻的槽位不并发（防进程风暴）。
        self._collect_sem = asyncio.Semaphore(1)
        # Tracks collected snapshot_ids for the current trading date so the
        # timer can skip already-persisted slots without a round-trip to Mongo.
        self._completed_today: set[str] = set()
        self._completed_date: str | None = None
        # 微信「个股信息差」支线（16:30/17:00/17:30，每日≤3 次）
        self._info_diff_task: asyncio.Task[None] | None = None
        self._info_diff_last: dict[str, Any] | None = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.enabled or (self._task is not None and not self._task.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop())
        if self._info_diff_task is None or self._info_diff_task.done():
            self._info_diff_task = loop.create_task(run_info_diff_loop(self))

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        info_task = self._info_diff_task
        self._info_diff_task = None
        if info_task is not None:
            info_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await info_task

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def status(self) -> dict[str, Any]:
        from backend.snapshot_collector.slots import generate_slots
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        now_ts = int(time.time() * 1000)
        trading_date = trading_date_from_ts(now_ts)
        is_trading_day = trading_date is not None
        now_dt = datetime.datetime.fromtimestamp(now_ts / 1000, TZ_SHANGHAI)
        minute = now_dt.hour * 60 + now_dt.minute
        in_session = 570 <= minute < 900  # 09:30-15:00
        upcoming_slot = None
        if is_trading_day and trading_date:
            all_slots = generate_slots(trading_date, self.snapshot_types)
            for slot in all_slots:
                if slot.timestamp_ms > now_ts and slot.snapshot_id not in self._completed_today:
                    upcoming_slot = slot.snapshot_id
                    break

        return {
            "enabled": self.enabled,
            "running": self.running,
            "dataset_id": self.dataset_id,
            "snapshot_types": self.snapshot_types,
            "grace_minutes": self.grace_minutes,
            "is_trading_day": is_trading_day,
            "trading_date": trading_date,
            "in_session": in_session,
            "upcoming_slot": upcoming_slot,
            "last_run_at": self._last_run_at,
            "last_slot_collected": self._last_slot_collected,
            "last_error": self._last_error,
            "last_error_at": self._last_error_at,
            "last_error_slot": self._last_error_slot,
            "collection_count": self._collection_count,
            "error_count": self._error_count,
            "in_flight_slots": sorted(self._in_flight_slots),
            "info_diff": self._info_diff_last,
        }

    # ── timer loop ──────────────────────────────────────────────────────────

    async def _run_loop(self) -> None:
        while True:
            try:
                until_next = await self._seconds_until_next_slot()
                await asyncio.sleep(until_next)
                # 唤醒后先做缺失自检再触发采集：机器睡眠/事件循环冻结跨过槽位时，
                # 过期未入库的槽位在此写 blocked run 记录并置 last_error（fail-visible）。
                # 顺序不能反——_collect_due_slots 会把过期槽位静默标记完成，先跑会
                # 掩盖缺失（2026-09-11 复盘：12:00-19:02 待机导致下午 6 槽无痕丢失）。
                await self._record_missed_slots_now()
                await self._collect_due_slots()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                self._last_error_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
                self._last_error_slot = "scheduler_cycle"
                self._error_count += 1
                logger.exception("snapshot collector scheduler cycle failed")
                await asyncio.sleep(30)

    # ── missed-slot visibility ──────────────────────────────────────────────

    async def _record_missed_slots_now(self) -> None:
        """唤醒后自检：当日已过 grace 且未入库的槽位写 blocked run 记录。

        调度器按 next-slot 定时休眠，机器睡眠或进程冻结跨过槽位后不会有任何
        采集动作；此前过期槽位被静默标记完成，数据无痕丢失。此处保证缺失以
        run 记录 + last_error（/api/health degraded 契约）暴露，供 launcher 与
        人工发现、backfill。不做补采决策——补采由 catch-up（收盘定格槽）或
        人工 backfill 承担（盘中槽用收盘数据回填会失真，见 _catchup_cycle）。
        """
        from backend.snapshot_collector.service_factory import (
            create_snapshot_collector_repository,
        )
        from backend.snapshot_collector.slots import generate_slots
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        now_ts = int(time.time() * 1000)
        trading_date = await asyncio.to_thread(trading_date_from_ts, now_ts)
        if trading_date is None:
            return
        if trading_date != self._completed_date:
            self._completed_date = trading_date
            self._completed_today.clear()

        grace_ms = self.grace_minutes * 60 * 1000
        repo = await asyncio.to_thread(create_snapshot_collector_repository)
        for slot in generate_slots(trading_date, self.snapshot_types):
            sid = slot.snapshot_id
            if sid in self._completed_today or sid in self._in_flight_slots:
                continue
            if now_ts < slot.timestamp_ms + grace_ms:
                continue  # 未过期：调度器仍在处理或尚未到期
            if await asyncio.to_thread(repo.snapshot_exists, self.dataset_id, sid):
                self._completed_today.add(sid)
                continue
            self._record_missed_slot(repo, slot)
            self._completed_today.add(sid)

    def _record_missed_slot(self, repo: Any, slot: Any) -> None:
        """写单条缺失记录并置 last_error；记录失败不阻断自检循环。"""
        from backend.snapshot_collector.state import record_run as _record_run

        reason = (
            f"slot missed: {self.grace_minutes}m grace window expired with no run "
            f"(scheduler freeze or machine sleep); backfill manually if needed"
        )
        try:
            _record_run(
                repo,
                {
                    "runId": f"missed-{slot.snapshot_id}-{int(time.time() * 1000)}",
                    "datasetId": self.dataset_id,
                    "snapshotId": slot.snapshot_id,
                    "snapshotType": slot.snapshot_type,
                    "tradingDate": slot.trading_date,
                    "slotTime": slot.slot_time,
                    "status": "blocked",
                    "deduped": False,
                    "dryRun": False,
                    "blockingIssues": ["slot_missed_grace_window"],
                    "error": reason,
                },
            )
        except Exception:
            logger.exception("failed to record missed slot %s", slot.snapshot_id)
        self._last_error = reason
        self._last_error_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
        self._last_error_slot = slot.snapshot_id
        self._error_count += 1

    # ── next-slot calculation ───────────────────────────────────────────────

    async def _seconds_until_next_slot(self) -> float:
        """Return seconds to sleep before the next snapshot slot becomes due.

        On a trading day returns the precise interval; on a non-trading day
        sleeps for ``_IDLE_RECHECK_SECONDS``.  Outside the collection window
        (16:00-09:00 next day) sleeps until the window opens again — no
        pointless polling after close.
        """
        from backend.snapshot_collector.slots import generate_slots
        from backend.snapshot_collector.trading_calendar import (
            TZ_SHANGHAI,
            is_in_collect_window,
            seconds_until_collect_window,
            trading_date_from_ts,
        )

        now_ts = int(time.time() * 1000)
        now_dt = datetime.datetime.fromtimestamp(now_ts / 1000, TZ_SHANGHAI)

        trading_date = await asyncio.to_thread(trading_date_from_ts, now_ts)
        if trading_date is None:
            return float(_IDLE_RECHECK_SECONDS)

        # 非采集窗口（收盘后至次日 09:00）：当日槽位已全部完成，深度休眠到窗口再开，
        # 避免每 30 分钟空转轮询/补采。
        if not is_in_collect_window(now_dt):
            return seconds_until_collect_window(now_dt)

        if trading_date != self._completed_date:
            self._completed_date = trading_date
            self._completed_today.clear()

        all_slots = generate_slots(trading_date, self.snapshot_types)

        for slot in all_slots:
            sid = slot.snapshot_id
            if sid in self._in_flight_slots or sid in self._completed_today:
                continue
            # Target the slot's scheduled time (not the end of grace window)
            wait_ms = slot.timestamp_ms - now_ts
            if wait_ms > -_ADVANCE_SECONDS * 1000:
                return max(0.0, wait_ms / 1000.0 - _ADVANCE_SECONDS)

        # All today's slots are either done or expired — re-check later
        return float(_IDLE_RECHECK_SECONDS)

    # ── collection ──────────────────────────────────────────────────────────

    async def _collect_due_slots(self) -> None:
        """Collect every slot whose timestamp has arrived and whose grace
        window has not yet expired.  Multiple types at the same ``HH:MM``
        are collected together.
        """
        from backend.snapshot_collector.slots import generate_slots
        from backend.snapshot_collector.service_factory import create_snapshot_collector_repository
        from backend.snapshot_collector.trading_calendar import trading_date_from_ts

        now_ts = int(time.time() * 1000)
        trading_date = await asyncio.to_thread(trading_date_from_ts, now_ts)
        if trading_date is None:
            return

        grace_ms = self.grace_minutes * 60 * 1000
        all_slots = generate_slots(trading_date, self.snapshot_types)
        repo = await asyncio.to_thread(create_snapshot_collector_repository)

        groups: dict[int, list[Any]] = {}
        for slot in all_slots:
            sid = slot.snapshot_id
            # Not yet due
            if now_ts < slot.timestamp_ms:
                continue
            # Expired
            if now_ts > slot.timestamp_ms + grace_ms:
                self._completed_today.add(sid)
                continue
            # Already handled
            if sid in self._in_flight_slots or sid in self._completed_today:
                continue
            # Already persisted
            if await asyncio.to_thread(repo.snapshot_exists, self.dataset_id, sid):
                self._completed_today.add(sid)
                continue

            groups.setdefault(slot.timestamp_ms, []).append(slot)

        for group in groups.values():
            for slot in group:
                self._in_flight_slots.add(slot.snapshot_id)
            asyncio.create_task(self._tracked_collect_multi(group))

    # ── per-slot collection ────────────────────────────────────────────────

    async def _tracked_collect(self, slot: Any) -> None:
        await self._tracked_collect_multi([slot])

    async def _tracked_collect_multi(self, group: list[Any]) -> None:
        """同刻一组槽位：全局串行执行，一次采集、按类型派生。"""
        from backend.snapshot_collector.models import CollectorRunRequest
        from backend.snapshot_collector.service_factory import (
            create_snapshot_collector_repository,
            create_snapshot_collector_service,
        )

        try:
            async with self._collect_sem:
                repo = await asyncio.to_thread(create_snapshot_collector_repository)
                pending: list[Any] = []
                for slot in group:
                    exists = await asyncio.to_thread(
                        repo.snapshot_exists, self.dataset_id, slot.snapshot_id
                    )
                    if exists:
                        self._completed_today.add(slot.snapshot_id)
                    else:
                        pending.append(slot)
                if not pending:
                    return
                service = await asyncio.to_thread(create_snapshot_collector_service, repo)
                requests = [
                    CollectorRunRequest(
                        dataset_id=self.dataset_id,
                        snapshot_type=slot.snapshot_type,
                        trading_date=slot.trading_date,
                        slot_time=slot.slot_time,
                        dry_run=False,
                        force=False,
                    )
                    for slot in pending
                ]
                group = pending
                if hasattr(service, "arun_once_multi"):
                    try:
                        results = await asyncio.wait_for(
                            service.arun_once_multi(requests),
                            timeout=self.collect_timeout_seconds * len(requests),
                        )
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            f"collector group of {len(group)} slots timed out after "
                            f"{self.collect_timeout_seconds * len(group)}s"
                        ) from None
                elif hasattr(service, "arun_once"):
                    results = []
                    for slot, request in zip(group, requests):
                        try:
                            results.append(
                                await asyncio.wait_for(
                                    service.arun_once(request),
                                    timeout=self.collect_timeout_seconds,
                                )
                            )
                        except asyncio.TimeoutError:
                            raise RuntimeError(
                                f"collector slot {slot.snapshot_id} timed out after "
                                f"{self.collect_timeout_seconds}s"
                            ) from None
                else:
                    results = []
                    for slot, request in zip(group, requests):
                        try:
                            results.append(
                                await asyncio.wait_for(
                                    asyncio.to_thread(service.run_once, request),
                                    timeout=self.collect_timeout_seconds,
                                )
                            )
                        except asyncio.TimeoutError:
                            raise RuntimeError(
                                f"collector slot {slot.snapshot_id} timed out after "
                                f"{self.collect_timeout_seconds}s"
                            ) from None
            for slot, result in zip(group, results):
                try:
                    self._apply_slot_result(slot, result)
                except Exception as exc:
                    self._mark_slot_error(slot, exc)
        except Exception as exc:
            for slot in group:
                self._mark_slot_error(slot, exc)
        finally:
            for slot in group:
                self._in_flight_slots.discard(slot.snapshot_id)

    def _apply_slot_result(self, slot: Any, result: Any) -> None:
        self._last_run_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
        if result.status in ("completed", "deduped"):
            if result.status == "completed":
                self._collection_count += 1
            self._completed_today.add(slot.snapshot_id)
        else:
            raise RuntimeError(
                f"collector slot {slot.snapshot_id} returned {result.status}: "
                f"{result.message or 'no message'}"
            )
        self._last_slot_collected = slot.snapshot_id
        if self._last_error_slot == slot.snapshot_id:
            self._last_error = None
            self._last_error_at = None
            self._last_error_slot = None

    def _mark_slot_error(self, slot: Any, exc: Exception) -> None:
        self._last_error = str(exc)
        self._last_error_at = datetime.datetime.now(TZ_SHANGHAI).isoformat()
        self._last_error_slot = slot.snapshot_id
        self._error_count += 1
        logger.exception("snapshot collector slot failed: %s", slot.snapshot_id)


# Module-level singleton — start/stop via the FastAPI lifespan or CLI.
snapshot_collector_scheduler = SnapshotCollectorScheduler()


# ── 微信「个股信息差」每日抓取（N：飞火挖掘社，16:30 主爬 + 17:00/17:30 补爬） ──────────

_INFODIFF_ATTEMPT_TIMES = (
    datetime.time(16, 30),
    datetime.time(17, 0),
    datetime.time(17, 30),
)
_INFODIFF_MAX_ATTEMPTS = 3


def next_info_diff_attempt(now: datetime.datetime) -> datetime.datetime:
    """下一个抓取时点：今日 16:30/17:00/17:30 中未到的最早一个，否则明日 16:30。"""
    naive = now.replace(tzinfo=None)
    for t in _INFODIFF_ATTEMPT_TIMES:
        candidate = datetime.datetime.combine(now.date(), t)
        if candidate > naive:
            return candidate.replace(tzinfo=now.tzinfo)
    return datetime.datetime.combine(now.date() + datetime.timedelta(days=1),
                                     _INFODIFF_ATTEMPT_TIMES[0]).replace(tzinfo=now.tzinfo)


async def run_info_diff_attempt() -> dict:
    """单次抓取尝试（供调度循环与测试调用）：发现→日期守卫→入库。"""
    from backend.operations.wechat_info_diff_ingest import ingest_today_if_published

    return await asyncio.to_thread(ingest_today_if_published)


_INFO_DIFF_META_OK = "ok"


async def run_info_diff_loop(sched: "SnapshotCollectorScheduler") -> None:
    """每日 16:30/17:00/17:30 抓「个股信息差」，每日≤3 次；失败/未发布按计划补爬。

    与主采集循环互不阻塞：抓取走 asyncio.to_thread（同步网络 IO）。attempts 计数
    仅存进程内存（服务长驻；重启后当日重新计数，代价只是最多 3 次额外抓取）。
    非交易日由 trading calendar 直接跳过。
    """
    from backend.snapshot_collector.trading_calendar import trading_date_from_ts

    state = {"date": None, "attempts": 0}
    while True:
        try:
            now = datetime.datetime.now(TZ_SHANGHAI)
            trading_date = trading_date_from_ts(int(now.timestamp() * 1000))
            due = (now.hour, now.minute) >= (16, 30)
            if trading_date and due:
                if state["date"] != trading_date:
                    state = {"date": trading_date, "attempts": 0}
                if state["attempts"] < _INFODIFF_MAX_ATTEMPTS:
                    result = await run_info_diff_attempt()
                    state["attempts"] += 1
                    sched._info_diff_last = {**result, "attempts": state["attempts"],
                                             "tradingDate": trading_date,
                                             "at": now.isoformat(timespec="seconds")}
                    logger.info("info-diff attempt %s/%s: %s", state["attempts"],
                                _INFODIFF_MAX_ATTEMPTS, result.get("status"))
            until_next = (next_info_diff_attempt(now) - now).total_seconds()
            await asyncio.sleep(max(30.0, until_next))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("info-diff scheduler cycle failed")
            sched._info_diff_last = {"status": "loop_error", "at": datetime.datetime.now(TZ_SHANGHAI).isoformat()}
            await asyncio.sleep(60)
