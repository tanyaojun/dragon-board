# -*- coding: utf-8 -*-
"""开盘槽采集延迟（SLOT_COLLECTION_DELAY_MS）测试。

2026-10-10 用户裁决：09:30 槽延后 10 分钟采集（主力资金等数据源开盘需
5-10 分钟轮询完整）；槽位标识不变，仅「到期时刻」后移。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.snapshot_collector.slots import (
    SLOT_COLLECTION_DELAY_MS,
    SLOT_TIMES,
    _make_timestamp_ms,
    generate_slots,
    is_slot_eligible,
)


def test_delay_table_only_covers_opening_slot():
    """延迟表只登记开盘首槽 09:30，其余槽位零延迟。"""
    assert set(SLOT_COLLECTION_DELAY_MS) == {"09:30"}
    assert SLOT_COLLECTION_DELAY_MS["09:30"] == 10 * 60 * 1000


def test_generate_slots_shifts_opening_slot_only():
    """09:30 槽 timestamp = 槽位时刻 + 10 分钟；其余槽位不受影响。"""
    trading_date = "2026-10-12"  # 周一
    slots = generate_slots(trading_date, ["half_hour"])
    by_time = {s.slot_time: s for s in slots}
    base = _make_timestamp_ms(trading_date, "09:30")
    assert by_time["09:30"].timestamp_ms == base + 10 * 60 * 1000
    assert by_time["10:00"].timestamp_ms == _make_timestamp_ms(trading_date, "10:00")
    # 槽位标识不被改写（帧/叙事/jev 全链仍按 09:30 归档）
    assert by_time["09:30"].slot_time == "09:30"


def test_opening_slot_eligible_window_shifts():
    """到期窗口整体后移：09:35 不可采、09:41 可采、09:46 过期（grace 5 分钟）。"""
    trading_date = "2026-10-12"
    slot = next(s for s in generate_slots(trading_date, ["half_hour"]) if s.slot_time == "09:30")
    assert is_slot_eligible(_make_timestamp_ms(trading_date, "09:35"), slot) is False
    assert is_slot_eligible(_make_timestamp_ms(trading_date, "09:41"), slot) is True
    assert is_slot_eligible(_make_timestamp_ms(trading_date, "09:46"), slot) is False


def test_all_types_shift_opening_slot():
    """三种含 09:30 的快照类型（five_minutes/quarter_hour/half_hour）全部后移。"""
    trading_date = "2026-10-12"
    for st in ("five_minutes", "quarter_hour", "half_hour"):
        assert "09:30" in SLOT_TIMES[st]
        slot = next(s for s in generate_slots(trading_date, [st]) if s.slot_time == "09:30")
        assert slot.timestamp_ms == _make_timestamp_ms(trading_date, "09:30") + 10 * 60 * 1000
