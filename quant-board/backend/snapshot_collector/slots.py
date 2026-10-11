"""Slot table, trading-time helpers, and eligibility rules.

Every time is Asia/Shanghai.  The slot table is the single source of truth
for which HH:MM times belong to each snapshot type.
"""

from __future__ import annotations

import datetime

from .trading_calendar import TZ_SHANGHAI

from .models import SnapshotSlot

# ── Slot table ───────────────────────────────────────────────────────────────
#
# Matches the design document and the frontend schedule.
#
# five_minutes:  50 slots (09:30-11:30 + 13:00-15:00, every 5 minutes; 2026-09-28
#                重新入采——短间距研究口径，盘中序列止于 15:00，不含盘后槽)
# quarter_hour: 19 slots  (09:30-11:30 + 13:00-15:15)
# half_hour:    10 slots (intraday series ends at 15:00 close fixing; the
#               15:30 post-close value is daily-only — 2026-09-11 口径)
# hourly:        5 slots
# daily:         1 slot  (15:30 post-close value)

SLOT_TIMES: dict[str, list[str]] = {
    "five_minutes": [
        "09:30", "09:35", "09:40", "09:45", "09:50", "09:55",
        "10:00", "10:05", "10:10", "10:15", "10:20", "10:25",
        "10:30", "10:35", "10:40", "10:45", "10:50", "10:55",
        "11:00", "11:05", "11:10", "11:15", "11:20", "11:25", "11:30",
        "13:00", "13:05", "13:10", "13:15", "13:20", "13:25",
        "13:30", "13:35", "13:40", "13:45", "13:50", "13:55",
        "14:00", "14:05", "14:10", "14:15", "14:20", "14:25",
        "14:30", "14:35", "14:40", "14:45", "14:50", "14:55",
        "15:00",
    ],
    "quarter_hour": [
        "09:30", "09:45",
        "10:00", "10:15", "10:30", "10:45",
        "11:00", "11:15", "11:30",
        "13:00", "13:15", "13:30", "13:45",
        "14:00", "14:15", "14:30", "14:45",
        "15:00", "15:15",
    ],
    "half_hour": [
        "09:30",
        "10:00", "10:30",
        "11:00", "11:30",
        "13:00", "13:30",
        "14:00", "14:30",
        "15:00",
    ],
    "hourly": [
        "10:00", "11:00",
        "13:00", "14:00",
        "15:00",
    ],
    "daily": ["15:30"],
}

# 题材/板块行（theme heat → sectorRows）的携带类型（2026-09-28 用户决策）：
# 题材热度半小时一档已够研究用，five_minutes / quarter_hour 帧不携带题材行，
# 题材序列研究走 half_hour / hourly / daily 帧。采集侧同时按此决策跳过
# 纯高频槽位唤醒的 theme heat 计算（上游开销不随 5 分钟频率放大）。
SECTOR_SNAPSHOT_TYPES: frozenset[str] = frozenset({"half_hour", "hourly", "daily"})

# ── 开盘槽采集延迟 ─────────────────────────────────────────────────────────────
# 2026-10-10 用户裁决：开盘时点主力资金等数据源需 5-10 分钟轮询才完整
#（2026-10-09 实测 09:30 帧 197/200 行 zlje 缺失，jev 冰点误判）。
# 09:30 槽的「到期时刻」延后 10 分钟：采集/情绪/jev 全链改用 09:40 时点数据，
# 槽位标识仍为 09:30（帧 timestamp 口径不变；实际晚采由既有 late-capture 质量链路如实标注）。
# 单一事实源：scheduler 到期/缺失/grace 判定与 is_slot_eligible 均消费 generate_slots 的时间戳。
SLOT_COLLECTION_DELAY_MS: dict[str, int] = {"09:30": 10 * 60 * 1000}


# ── Internal helpers ─────────────────────────────────────────────────────────

def _make_timestamp_ms(trading_date: str, slot_time: str) -> int:
    """Return the epoch-ms instant of *trading_date* + *slot_time* in TZ_SHANGHAI."""
    try:
        dt = datetime.datetime.strptime(
            f"{trading_date} {slot_time}", "%Y-%m-%d %H:%M"
        )
    except ValueError as exc:
        raise ValueError(
            f"Invalid slot datetime: trading_date={trading_date!r}, slot_time={slot_time!r}"
        ) from exc
    dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return int(dt.timestamp() * 1000)


# ── Public API ───────────────────────────────────────────────────────────────

def generate_slots(
    trading_date: str,
    snapshot_types: list[str],
) -> list[SnapshotSlot]:
    """Generate every `SnapshotSlot` for *trading_date* and *snapshot_types*.

    Slots are returned sorted by ``timestamp_ms`` ascending.  Unknown
    *snapshot_types* are silently skipped.
    """
    slots: list[SnapshotSlot] = []
    for st in snapshot_types:
        times = SLOT_TIMES.get(st)
        if times is None:
            continue
        for t in times:
            ts = _make_timestamp_ms(trading_date, t) + SLOT_COLLECTION_DELAY_MS.get(t, 0)
            slots.append(SnapshotSlot(st, trading_date, t, ts))
    slots.sort(key=lambda s: s.timestamp_ms)
    return slots


def is_slot_eligible(
    now_ts: int,
    slot: SnapshotSlot,
    *,
    grace_minutes: int = 5,
) -> bool:
    """Return `True` when *slot* can be collected at *now_ts*.

    A slot is eligible once the wall clock reaches its scheduled time and
    stays eligible for at most *grace_minutes* afterward.  The grace window
    is particularly important for the close slot (15:00) so the collector
    has time to receive final market data after the session ends.
    """
    grace_ms = grace_minutes * 60 * 1000
    return slot.timestamp_ms <= now_ts <= slot.timestamp_ms + grace_ms
