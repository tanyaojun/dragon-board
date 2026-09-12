"""Catch-up 补采循环测试（2026-09-11 机器睡眠丢数据复盘）。

覆盖契约：
- 采集窗口内（09:00-16:00）：所有过期未入库槽位均可补采（现状行为）。
- 收盘后（16:00 至次日 09:00）：行情已定格，仅补 15:00 及之后的收盘类槽位
  （half_hour 15:00 / daily 15:30 回填不失真）；盘中槽不补，避免用收盘价
  伪造盘中数据。
- ``attempted`` 仅在成功（completed/deduped）后登记，失败槽位下一轮重试
  （旧实现在执行前登记，blocked 后当天永不重试）。
- 跨交易日 ``attempted`` 重置。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import pytest

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _ts_ms(dt: datetime.datetime) -> int:
    return int(dt.timestamp() * 1000)


def _slot(
    snapshot_type: str = "half_hour",
    trading_date: str = "2026-06-15",
    slot_time: str = "10:00",
):
    from backend.snapshot_collector.models import SnapshotSlot

    dt = datetime.datetime.strptime(
        f"{trading_date} {slot_time}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=TZ_SHANGHAI)
    return SnapshotSlot(
        snapshot_type, trading_date, slot_time, int(dt.timestamp() * 1000)
    )


@dataclass
class FakeCatchupRepo:
    existing: set[str] = field(default_factory=set)

    def snapshot_exists(self, dataset_id: str, snapshot_id: str) -> bool:
        del dataset_id
        return snapshot_id in self.existing


@dataclass
class FakeCatchupService:
    calls: list = field(default_factory=list)
    status: str = "completed"

    async def arun_once(self, request: Any):
        self.calls.append(request)
        from backend.snapshot_collector.models import CollectorRunResult

        return CollectorRunResult(
            status=self.status,
            snapshot_id=(
                f"{request.snapshot_type}:{request.trading_date}:{request.slot_time}"
            ),
        )


class FakeCatchupSettings:
    snapshot_collector_dataset_id = "test_dataset"
    snapshot_collector_types = "half_hour,daily"
    snapshot_collector_close_grace_minutes = 5


async def _run_cycle(
    monkeypatch: pytest.MonkeyPatch,
    *,
    now: datetime.datetime,
    trading_date: str | None,
    in_window: bool,
    slots: list,
    repo: FakeCatchupRepo,
    service: FakeCatchupService,
    state: Any = None,
):
    """Patch time/calendar/slots/factory，跑一轮 _catchup_cycle 并返回 state。"""
    from backend import collector_main

    now_ms = _ts_ms(now)

    monkeypatch.setattr(
        "backend.collector_main.time.time", lambda: now_ms / 1000.0
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.trading_calendar.trading_date_from_ts",
        lambda ts: trading_date,
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.trading_calendar.is_in_collect_window",
        lambda value: in_window,
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.slots.generate_slots",
        lambda date, types: slots,
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.service_factory.create_snapshot_collector_repository",
        lambda: repo,
    )
    monkeypatch.setattr(
        "backend.snapshot_collector.service_factory.create_snapshot_collector_service",
        lambda repo_: service,
    )

    if state is None:
        state = collector_main._CatchupState()
    await collector_main._catchup_cycle(FakeCatchupSettings(), state)
    return state


def _request_slot_times(service: FakeCatchupService) -> set[tuple[str, str]]:
    return {(r.snapshot_type, r.slot_time) for r in service.calls}


class TestCatchupCycle:
    @pytest.mark.asyncio
    async def test_within_window_backfills_all_missing_slots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 窗口内 15:10：13:00/14:30/15:00 均已过期且未入库 → 全部补采。
        now = datetime.datetime(2026, 6, 15, 15, 10, 0, tzinfo=TZ_SHANGHAI)
        slots = [_slot(slot_time=t) for t in ("13:00", "14:30", "15:00")]
        service = FakeCatchupService()

        await _run_cycle(
            monkeypatch,
            now=now,
            trading_date="2026-06-15",
            in_window=True,
            slots=slots,
            repo=FakeCatchupRepo(),
            service=service,
        )

        assert _request_slot_times(service) == {
            ("half_hour", "13:00"),
            ("half_hour", "14:30"),
            ("half_hour", "15:00"),
        }

    @pytest.mark.asyncio
    async def test_after_close_backfills_only_close_slots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 19:02 唤醒（窗口外）：只有 15:00 及之后的收盘定格槽位可补；
        # 13:00/14:00/14:30 盘中槽不得用收盘数据回填。15:30 收盘值由 daily
        # 独占（half_hour 已止于 15:00，2026-09-11 口径）。
        now = datetime.datetime(2026, 6, 15, 19, 2, 0, tzinfo=TZ_SHANGHAI)
        slots = [
            _slot(slot_time="13:00"),
            _slot(slot_time="14:00"),
            _slot(slot_time="14:30"),
            _slot(slot_time="15:00"),
            _slot(snapshot_type="daily", slot_time="15:30"),
        ]
        service = FakeCatchupService()

        await _run_cycle(
            monkeypatch,
            now=now,
            trading_date="2026-06-15",
            in_window=False,
            slots=slots,
            repo=FakeCatchupRepo(),
            service=service,
        )

        assert _request_slot_times(service) == {
            ("half_hour", "15:00"),
            ("daily", "15:30"),
        }

    @pytest.mark.asyncio
    async def test_after_close_backfills_daily_slot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # daily 槽位时间 15:30，收盘后可补。
        now = datetime.datetime(2026, 6, 15, 20, 0, 0, tzinfo=TZ_SHANGHAI)
        slots = [_slot(snapshot_type="daily", slot_time="15:30")]
        service = FakeCatchupService()

        await _run_cycle(
            monkeypatch,
            now=now,
            trading_date="2026-06-15",
            in_window=False,
            slots=slots,
            repo=FakeCatchupRepo(),
            service=service,
        )

        assert _request_slot_times(service) == {("daily", "15:30")}

    @pytest.mark.asyncio
    async def test_skips_existing_and_not_yet_expired_slots(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 已入库（10:00）与未过期（15:04，grace 内）槽位不补。
        now = datetime.datetime(2026, 6, 15, 15, 4, 0, tzinfo=TZ_SHANGHAI)
        existing_slot = _slot(slot_time="10:00")
        fresh_slot = _slot(slot_time="15:00")
        service = FakeCatchupService()

        await _run_cycle(
            monkeypatch,
            now=now,
            trading_date="2026-06-15",
            in_window=True,
            slots=[existing_slot, fresh_slot],
            repo=FakeCatchupRepo(existing={existing_slot.snapshot_id}),
            service=service,
        )

        assert service.calls == []

    @pytest.mark.asyncio
    async def test_attempted_marked_only_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # blocked 槽位不登记 attempted：下一轮必须重试；成功槽位不再重试。
        now = datetime.datetime(2026, 6, 15, 15, 10, 0, tzinfo=TZ_SHANGHAI)
        slots = [_slot(slot_time="13:00"), _slot(slot_time="15:00")]
        service = FakeCatchupService(status="blocked")
        state = None

        state = await _run_cycle(
            monkeypatch,
            now=now,
            trading_date="2026-06-15",
            in_window=True,
            slots=slots,
            repo=FakeCatchupRepo(),
            service=service,
            state=state,
        )

        assert len(service.calls) == 2
        assert state.attempted == set()

        service.status = "completed"
        await _run_cycle(
            monkeypatch,
            now=now,
            trading_date="2026-06-15",
            in_window=True,
            slots=slots,
            repo=FakeCatchupRepo(),
            service=service,
            state=state,
        )

        assert len(service.calls) == 4  # 两个槽位各重试一次
        assert state.attempted == {s.snapshot_id for s in slots}

    @pytest.mark.asyncio
    async def test_attempted_resets_on_new_trading_day(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime.datetime(2026, 6, 15, 15, 10, 0, tzinfo=TZ_SHANGHAI)
        slots = [_slot(slot_time="13:00")]
        service = FakeCatchupService()

        state = await _run_cycle(
            monkeypatch,
            now=now,
            trading_date="2026-06-15",
            in_window=True,
            slots=slots,
            repo=FakeCatchupRepo(),
            service=service,
        )
        assert state.attempted == {slots[0].snapshot_id}

        # 次日：attempted 必须清空，次日槽位可正常补采。
        next_day_slots = [_slot(trading_date="2026-06-16", slot_time="13:00")]
        service.calls.clear()
        await _run_cycle(
            monkeypatch,
            now=datetime.datetime(2026, 6, 16, 15, 10, 0, tzinfo=TZ_SHANGHAI),
            trading_date="2026-06-16",
            in_window=True,
            slots=next_day_slots,
            repo=FakeCatchupRepo(),
            service=service,
            state=state,
        )

        assert len(service.calls) == 1
        assert service.calls[0].trading_date == "2026-06-16"

    @pytest.mark.asyncio
    async def test_non_trading_day_is_noop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        now = datetime.datetime(2026, 6, 14, 15, 10, 0, tzinfo=TZ_SHANGHAI)
        service = FakeCatchupService()

        await _run_cycle(
            monkeypatch,
            now=now,
            trading_date=None,
            in_window=True,
            slots=[],
            repo=FakeCatchupRepo(),
            service=service,
        )

        assert service.calls == []
