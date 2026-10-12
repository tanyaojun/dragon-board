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
from pathlib import Path
import json
import os
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
        # 韭研公社异动支线（交易日 12:05 midday / 15:35 final，每日各 ≤1 次）
        self._jiuyan_task: asyncio.Task[None] | None = None
        self._jiuyan_last: dict[str, Any] | None = None
        self._direction_last: dict[str, Any] | None = None
        self._direction_task: asyncio.Task | None = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.enabled or (self._task is not None and not self._task.done()):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._task = loop.create_task(self._run_loop())
        if self._jiuyan_task is None or self._jiuyan_task.done():
            self._jiuyan_task = loop.create_task(run_jiuyan_loop(self))
        if self._direction_task is None or self._direction_task.done():
            self._direction_task = loop.create_task(run_direction_loop(self))

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        jiuyan_task = self._jiuyan_task
        self._jiuyan_task = None
        if jiuyan_task is not None:
            jiuyan_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await jiuyan_task
        direction_task = getattr(self, "_direction_task", None)
        if direction_task is not None:
            direction_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await direction_task

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
            "jiuyan": self._jiuyan_last,
            "direction": self._direction_last,
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
        self._record_failed_slot(slot, exc)

    def _record_failed_slot(self, slot: Any, exc: Exception) -> None:
        """超时/异常槽位落一条 failed 运行记录（2026-10-09 审计 P2-D）。

        此前超时只更新内存 last_error（进程重启即消失），MongoDB runs 集合无痕——
        09-21 10:30 槽超时后查不到任何记录，违背 fail-visible 的持久可追溯要求。
        写失败不阻断调度循环（MongoDB 不可用时只留日志；此时 run 记录本就无处可写）。
        """
        from backend.snapshot_collector.state import record_run as _record_run

        try:
            from backend.snapshot_collector.service_factory import (
                create_snapshot_collector_repository,
            )

            _record_run(
                create_snapshot_collector_repository(),
                {
                    "runId": f"failed-{slot.snapshot_id}-{int(time.time() * 1000)}",
                    "datasetId": self.dataset_id,
                    "snapshotId": slot.snapshot_id,
                    "snapshotType": slot.snapshot_type,
                    "tradingDate": slot.trading_date,
                    "slotTime": slot.slot_time,
                    "status": "failed",
                    "deduped": False,
                    "dryRun": False,
                    "blockingIssues": ["slot_error"],
                    "error": str(exc)[:500],
                },
            )
        except Exception:
            logger.exception(
                "failed to record failed-slot run record %s", slot.snapshot_id
            )


# Module-level singleton — start/stop via the FastAPI lifespan or CLI.
snapshot_collector_scheduler = SnapshotCollectorScheduler()




# ── 韭研公社异动每日采集（交易日 12:05 midday / 15:35 final，每日各 ≤1 次） ──────────

_JIUYAN_ATTEMPTS = (
    (datetime.time(12, 5), "midday"),
    (datetime.time(15, 35), "final"),
)


def jiuyan_enabled() -> bool:
    import os

    return os.environ.get("JIUYAN_ENABLED", "1") != "0"


async def run_jiuyan_attempt(date: str, kind: str) -> dict:
    from backend.operations.jiuyan_collect import collect_and_store

    return await asyncio.to_thread(collect_and_store, date, kind)


async def run_jiuyan_loop(sched: "SnapshotCollectorScheduler") -> None:
    """交易日 12:05 采 midday、15:35 采 final（每日各 ≤1 次）；authFailed 自愈重试一次
    （清缓存重新解析，可触发浏览器铸造/登录，见 jiuyan_auth），仍失败如实记状态。

    与主采集循环互不阻塞（collect 走 asyncio.to_thread）。60s 轮询足够（时点粒度=分钟）。
    """
    from backend.snapshot_collector.trading_calendar import trading_date_from_ts

    state: dict[str, Any] = {"date": None, "done": set()}
    while True:
        try:
            if not jiuyan_enabled():
                await asyncio.sleep(300)
                continue
            now = datetime.datetime.now(TZ_SHANGHAI)
            trading_date = trading_date_from_ts(int(now.timestamp() * 1000))
            if trading_date:
                if state["date"] != trading_date:
                    state = {"date": trading_date, "done": set()}
                for attempt_time, kind in _JIUYAN_ATTEMPTS:
                    if kind in state["done"]:
                        continue
                    if (now.hour, now.minute) >= (attempt_time.hour, attempt_time.minute):
                        state["done"].add(kind)
                        result = await run_jiuyan_attempt(trading_date, kind)
                        sched._jiuyan_last = {**result, "at": now.isoformat(timespec="seconds")}
                        logger.info("jiuyan collect %s %s: %s", kind, trading_date,
                                    json.dumps(result, ensure_ascii=False, default=str)[:200])
                        break
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("jiuyan scheduler cycle failed")
            sched._jiuyan_last = {"status": "loop_error", "at": datetime.datetime.now(TZ_SHANGHAI).isoformat()}
            await asyncio.sleep(60)

def direction_command(date: str) -> list[str]:
    """direction runner 子进程命令（runner 参数部分须 ⊆ jev_direction_gate.build_arg_parser）。"""
    venv_py = Path(__file__).resolve().parents[2] / ".venv" / "Scripts" / "python.exe"
    return [str(venv_py), "-X", "utf8", "-m", "backend.operations.jev_direction_gate",
            "--day", date, "--fire"]


async def run_direction_attempt(date: str) -> dict:
    """11:00 判读（advisory）：子进程隔离跑 runner（单题集 A 全池，1 调用/股）。"""
    cmd = direction_command(date)
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        cwd=str(Path(__file__).resolve().parents[2]),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])})
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=3600)
    tail = (out or b"").decode("utf-8", "replace")[-500:]
    return {"status": "ok" if proc.returncode == 0 else "failed",
            "returncode": proc.returncode, "tail": tail}


async def run_direction_loop(sched: "SnapshotCollectorScheduler") -> None:
    """交易日 11:08 触发 v3-gate 方向判读（每日一次；11:00 帧已落盘，advisory 语义）。

    预登记：docs/hotlist-jev/jev-direction-standalone-preregistration.md；
    快照 11:00 帧落盘后直挂 jev 调用链（无 token 安静跳过）；失败不翻主采集链。
    """
    from backend.snapshot_collector.trading_calendar import trading_date_from_ts

    state: dict[str, Any] = {"date": None, "done": False}
    while True:
        try:
            now = datetime.datetime.now(TZ_SHANGHAI)
            trading_date = trading_date_from_ts(int(now.timestamp() * 1000))
            if trading_date:
                if state["date"] != trading_date:
                    state = {"date": trading_date, "done": False}
                if not state["done"] and (now.hour, now.minute) >= (11, 8):
                    state["done"] = True
                    if not ((os.environ.get("JEV_CF_TOKEN") or "").strip()
                            or (os.environ.get("JEV_TYPESAFE_KEY") or "").strip()):
                        result = {"status": "no_token"}
                    else:
                        result = await run_direction_attempt(trading_date)
                    sched._direction_last = {**result, "date": trading_date,
                                             "at": now.isoformat(timespec="seconds")}
                    logger.info("direction gate %s: %s", trading_date,
                                json.dumps(result, ensure_ascii=False, default=str)[:200])
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("direction scheduler cycle failed")
            sched._direction_last = {"status": "loop_error", "at": datetime.datetime.now(TZ_SHANGHAI).isoformat()}
            await asyncio.sleep(60)
