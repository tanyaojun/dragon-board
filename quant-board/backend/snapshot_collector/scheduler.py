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
import json
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
        # 韭研公社异动支线（交易日 12:05 midday / 15:35 final，每日各 ≤1 次；
        # 2026-11-03 用户裁决：午盘只采名单，不投喂不打标，盘后链全量投喂；
        # 2026-11-04 用户裁决：15:35 版可能不完整（韭研盘后补名单），完整性由
        # 17:00 盘后链预检 run_jiuyan_preflight 保障：远端探针 vs 落库，不一致先补齐）
        self._jiuyan_task: asyncio.Task[None] | None = None
        self._jiuyan_last: dict[str, Any] | None = None
        self._jiuyan_theme_last: dict[str, Any] | None = None
        # 题材层龙头投喂（17:30，2026-10-30 用户裁决改时；每日 ≈112k tokens 包络
        # （2026-11-11 实测 22 doc，旧 ≈29k 为 13 龙头旧口径），幂等；龙虎榜主榜晚于
        # 挂链生成，由 C 席位兜底 + B 补齐链保障，见 _THEME_LEADER_LHB_BACKFILL_SLOTS）
        self._theme_leader_last: dict[str, Any] | None = None
        # 龙虎榜补齐（B，2026-11-11 用户裁决：00:30 凌晨/07:10 次晨两时点，零 token 探针+定向重跑）
        self._theme_leader_lhb_backfill_last: dict[str, Any] | None = None
        # 竞价龙头晨间链（vA1，2026-11-13 预登记：09:26 投喂 + 16:10 结局回填）
        self._auction_leader_last: dict[str, Any] | None = None
        self._auction_leader_settle_last: dict[str, Any] | None = None

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
            "jiuyanTheme": self._jiuyan_theme_last,
            "themeLeader": self._theme_leader_last,
            "themeLeaderLhbBackfill": self._theme_leader_lhb_backfill_last,
            "auctionLeader": self._auction_leader_last,
            "auctionLeaderSettle": self._auction_leader_settle_last,
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
    # 15:35 版可能不完整（韭研盘后补名单，2026-11-04 实测 44 只/晚间 136）：
    # 完整性由 17:00 盘后链预检 run_jiuyan_preflight 保障（探针对账，不一致先补齐）。
    (datetime.time(15, 35), "final"),
)

# 题材语料采集时点（2026-10-23 v4 换源）：事件层唯一权威源=开盘啦（韭研 timeline/早报退役，
# 重叠实测见 theme-corpus-extra-sources-survey-20261023.md §8）。
# 盘前 08:45：开盘啦题材事件+新闻流+日历（当日炒事件池 + 前瞻）；
# 盘中 11:45（2026-11-02 用户裁决 B）：KPL 刷新——当日新闻流尽早进语料
#（盘中新出题材新闻如 10:41 研讨会此前要等 16:10 才进语料）；
# 收盘后 16:10：开盘啦刷新（当日新闻流收全）+ 韭研产业树正文（无 KPL 对应物，保留）。
_THEME_CORPUS_ATTEMPTS = (
    (datetime.time(8, 45), "preopen", ("kpl",)),
    (datetime.time(11, 45), "midday", ("kpl",)),
    (datetime.time(16, 10), "postclose", ("kpl", "jiuyan")),
)

# 午盘投喂已于 2026-11-03 用户裁决移除：午盘只采名单不投喂不打标，盘后链全量投喂。
# 题材层龙头投喂时点（2026-10-20 用户裁决「每日自动投喂、累积到 20 交易日」；
# **2026-10-30 用户裁决改 17:30**：晚于 16:10 题材语料刷新 + 15:35 收盘名单（名单完整性
# 由 17:00 盘后链预检补齐保障，2026-11-04）。**2026-11-11 推翻注**：原改时动机「龙虎榜榜
# 约 17:00 盘后生成、当日事实行当日可得」对主榜 HisBeOnTheLHB 不成立（17:30~21:37 实证仍空，
# 约 17:00 生成的是席位榜）；主榜事实由 C 席位兜底 + B 补齐链（00:30/07:10）保障，见 §5.4。
# 每日 1 call/龙头（2026-11-11 实测 22 doc ≈112k tokens/日，旧 13 只 ≈29k 为旧口径），
# 子进程幂等（同股同日不重复投喂）。
_THEME_LEADER_LABEL_AT = datetime.time(17, 30)
# 失败重试：每日最多 3 次，间隔 ≥10 分钟（防一次通道抖动吃掉整天 pilot 样本）
_THEME_LEADER_MAX_ATTEMPTS = 3
_THEME_LEADER_RETRY_AFTER = datetime.timedelta(minutes=10)
# 龙虎榜补齐时点（B，2026-11-11 用户裁决；时点经 11-11 夜实测钉死）：HisBeOnTheLHB
# 主榜凌晨批处理生成——11-11 23:42 仍结构化空态，00:08 实测到达（探针 00:12 捕获
# groups=18/stocks=123），生成窗口 (23:42, 00:12]。故 00:30 凌晨时点同夜补齐（主榜
# 到达后、次日竞价前）+ 07:10 次晨保险（生成延迟时承接）；旧 21:30 晚间时点实证必空跑
# 已废。函数内 lookback=5 自愈，任一时点可补历史 pending 日；零 token 探针，有新数据
# 才定向重跑；每时点每日一次尝试，失败由下一时点/次日自愈（进程重启后当前时点自动补）。
_THEME_LEADER_LHB_BACKFILL_SLOTS = (
    (datetime.time(0, 30), "night"),
    (datetime.time(7, 10), "morning"),
)

# 竞价龙头晨间投喂时点（vA1，2026-11-13 预登记 A1）：09:26 = 9:25 集合竞价冻结
# + :8000 archiver ≤60s 轮询 lag 保障；失败重试每日最多 3 次、间隔 ≥5 分钟。
_AUCTION_LEADER_LABEL_AT = datetime.time(9, 26)
_AUCTION_LEADER_MAX_ATTEMPTS = 3
_AUCTION_LEADER_RETRY_AFTER = datetime.timedelta(minutes=5)
# 当日结局回填时点（16:10 盘后：daban pool 日档已收全；零 token，lookback 自愈）
_AUCTION_LEADER_SETTLE_AT = datetime.time(16, 10)


def _parse_iso(v: Any) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(v)) if v else None
    except (TypeError, ValueError):
        return None


def jiuyan_enabled() -> bool:
    import os

    return os.environ.get("JIUYAN_ENABLED", "1") != "0"


def jiuyan_theme_collect_enabled() -> bool:
    """题材语料采集开关（L3；默认开，`JIUYAN_THEME_COLLECT_ENABLED=0` 关闭）。"""
    import os

    return os.environ.get("JIUYAN_THEME_COLLECT_ENABLED", "1") != "0"


async def run_jiuyan_attempt(date: str, kind: str) -> dict:
    from backend.operations.jiuyan_collect import collect_and_store

    return await asyncio.to_thread(collect_and_store, date, kind)


async def run_jiuyan_loop(sched: "SnapshotCollectorScheduler") -> None:
    """交易日 12:05 采 midday、15:35 采 final（每日各 ≤1 次）；authFailed 自愈重试一次
    （清缓存重新解析，可触发浏览器铸造/登录，见 jiuyan_auth），仍失败如实记状态。

    2026-11-03 用户裁决：午盘只采名单（落 `jiuyan_action` 供盘中读口），不投喂不打标；
    投喂打标统一在 17:00 盘后链 `jiuyanLabel` 步全量执行（单日每股一次幂等保留）。

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
                # 题材/事件语料（L3，2026-10-20）：盘前 08:45 取当日+未来事件日历，
                # 盘中 11:45 KPL 刷新（2026-11-02 用户裁决 B：当日新闻流尽早进语料），
                # 收盘后 16:10 刷新板块催化正文。失败只记状态，不影响异动采集与打标。
                if jiuyan_theme_collect_enabled():
                    for theme_time, theme_kind, theme_collectors in _THEME_CORPUS_ATTEMPTS:
                        key = f"theme:{theme_kind}"
                        if key in state["done"]:
                            continue
                        if (now.hour, now.minute) >= (theme_time.hour, theme_time.minute):
                            state["done"].add(key)
                            from backend.operations.schedule import run_theme_corpus_collect_once
                            theme_result = await asyncio.to_thread(
                                run_theme_corpus_collect_once, trading_date,
                                collectors=theme_collectors)
                            sched._jiuyan_theme_last = {
                                **theme_result, "at": now.isoformat(timespec="seconds")}
                            logger.info("jiuyan theme corpus %s %s: %s", theme_kind, trading_date,
                                        json.dumps(theme_result, ensure_ascii=False,
                                                   default=str)[:200])
                            break
                # 竞价龙头晨间投喂（09:26，vA1 预登记 A1）：独立集合/独立题集代际；
                # 限次退避重试镜像 17:30 链（防一次通道抖动吃掉整天样本）。
                if now.time() >= _AUCTION_LEADER_LABEL_AT:
                    from backend.operations.schedule import (
                        run_auction_leader_label_once, auction_leader_label_enabled)
                    if auction_leader_label_enabled():
                        attempts = int(state.get("auction_leader_attempts") or 0)
                        prev = sched._auction_leader_last or {}
                        prev_at = _parse_iso(prev.get("at"))
                        retry_due = (
                            not prev.get("ok")
                            and attempts < _AUCTION_LEADER_MAX_ATTEMPTS
                            and (prev_at is None
                                 or (now - prev_at).total_seconds() >= _AUCTION_LEADER_RETRY_AFTER.total_seconds()))
                        first_run = "auction_leader_label" not in state["done"]
                        if first_run or retry_due:
                            if first_run:
                                state["done"].add("auction_leader_label")
                            state["auction_leader_attempts"] = attempts + 1
                            if attempts and not first_run:
                                logger.info("auction leader label 重试第 %s 次（%s）",
                                            attempts + 1, trading_date)
                            auction_result = await asyncio.to_thread(
                                run_auction_leader_label_once, trading_date)
                            sched._auction_leader_last = {
                                **auction_result, "attempt": attempts + 1,
                                "at": now.isoformat(timespec="seconds")}
                            logger.info("auction leader label %s: %s", trading_date,
                                        json.dumps(auction_result, ensure_ascii=False,
                                                   default=str)[:200])
                # 题材层龙头投喂（17:30，2026-10-30 用户裁决改时）：独立集合/独立题集代际。
                # **限次退避重试**：失败（通道/取数/子进程）不一次判死——否则 8001 重启撞上
                # 通道短暂不可用就会让那一天永远补不上（2026-10-20 实测：代理挂 → 9/9 degraded）。
                # 规则：每日最多 `_THEME_LEADER_MAX_ATTEMPTS` 次，两次间隔 ≥ `_THEME_LEADER_RETRY_AFTER`。
                if now.time() >= _THEME_LEADER_LABEL_AT:
                    from backend.operations.schedule import (
                        run_theme_leader_label_once, theme_leader_label_enabled)
                    if theme_leader_label_enabled():
                        attempts = int(state.get("theme_leader_attempts") or 0)
                        prev = sched._theme_leader_last or {}
                        prev_at = _parse_iso(prev.get("at"))
                        retry_due = (
                            not prev.get("ok")
                            and attempts < _THEME_LEADER_MAX_ATTEMPTS
                            and (prev_at is None
                                 or (now - prev_at).total_seconds() >= _THEME_LEADER_RETRY_AFTER.total_seconds())
                        )
                        first_run = "theme_leader_label" not in state["done"]
                        if first_run or retry_due:
                            if first_run:
                                state["done"].add("theme_leader_label")
                            state["theme_leader_attempts"] = attempts + 1
                            if attempts and not first_run:
                                logger.info("theme leader label 重试第 %s 次（%s）",
                                            attempts + 1, trading_date)
                            leader_result = await asyncio.to_thread(
                                run_theme_leader_label_once, trading_date)
                            sched._theme_leader_last = {
                                **leader_result, "attempt": attempts + 1,
                                "at": now.isoformat(timespec="seconds")}
                            logger.info("theme leader label %s: %s", trading_date,
                                        json.dumps(leader_result, ensure_ascii=False,
                                                   default=str)[:200])
                # 龙虎榜补齐（B，2026-11-11 用户裁决）：00:30 凌晨 / 07:10 次晨，
                # 零 token 探针 + 有新数据才定向重跑（lookback 自愈在函数内）。
                for bf_time, bf_slot in _THEME_LEADER_LHB_BACKFILL_SLOTS:
                    bf_key = f"theme_leader_lhb_backfill:{bf_slot}"
                    if bf_key in state["done"] or now.time() < bf_time:
                        continue
                    state["done"].add(bf_key)
                    from backend.operations.schedule import (
                        run_theme_leader_lhb_backfill_once, theme_leader_label_enabled)
                    if not theme_leader_label_enabled():
                        break
                    bf_result = await asyncio.to_thread(
                        run_theme_leader_lhb_backfill_once, trading_date)
                    sched._theme_leader_lhb_backfill_last = {
                        **bf_result, "slot": bf_slot,
                        "at": now.isoformat(timespec="seconds")}
                    logger.info("theme leader lhb backfill %s %s: %s", bf_slot, trading_date,
                                json.dumps(bf_result, ensure_ascii=False, default=str)[:300])
                    break
                # 竞价龙头当日结局回填（16:10，零 token；lookback 5 日自愈）
                if now.time() >= _AUCTION_LEADER_SETTLE_AT:
                    st_key = "auction_leader_settle"
                    if st_key not in state["done"]:
                        state["done"].add(st_key)
                        from backend.operations.schedule import (
                            run_auction_leader_settle_once, auction_leader_label_enabled)
                        if auction_leader_label_enabled():
                            st_result = await asyncio.to_thread(
                                run_auction_leader_settle_once, trading_date)
                            sched._auction_leader_settle_last = {
                                **st_result, "at": now.isoformat(timespec="seconds")}
                            logger.info("auction leader settle %s: %s", trading_date,
                                        json.dumps(st_result, ensure_ascii=False,
                                                   default=str)[:300])
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("jiuyan scheduler cycle failed")
            sched._jiuyan_last = {"status": "loop_error", "at": datetime.datetime.now(TZ_SHANGHAI).isoformat()}
            await asyncio.sleep(60)
