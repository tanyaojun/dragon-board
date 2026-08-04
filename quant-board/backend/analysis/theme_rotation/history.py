"""历史槽位读取：从 MongoDB 加载当前槽之前的最近 N 个槽（sector rows + 最近槽 stock rows）。"""

from __future__ import annotations

import datetime
from typing import Any

from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.models import HistorySlot, RotationHistory
from backend.snapshot_collector.trading_calendar import (
    TradingCalendarUnavailable,
    is_trading_day,
)


def _is_trading_day(day: datetime.date) -> bool:
    """交易日判定：桥可用用桥结果；桥不可用退化为工作日启发（H1 跨日基线不阻断）。"""
    try:
        return is_trading_day(day)
    except TradingCalendarUnavailable:
        # 节假日多查无害：日期范围内无数据即空槽；优先保跨日基线可用
        return day.weekday() < 5


def previous_trading_day(value: str) -> str:
    """返回 *value*（YYYY-MM-DD）之前最近的交易日（审计 H1 跨日基线）。"""
    current = datetime.date.fromisoformat(value)
    probe = current - datetime.timedelta(days=1)
    while not _is_trading_day(probe):
        probe -= datetime.timedelta(days=1)
    return probe.isoformat()


class RotationHistoryService:
    """有 I/O 的历史读取；repo 实现 SnapshotRepository 协议（测试可注入 fake）。"""

    def __init__(
        self,
        repo: Any,
        config: ThemeRotationConfig | None = None,
        previous_trading_day_fn: Any = None,
    ) -> None:
        self._repo = repo
        self.config = config or ThemeRotationConfig()
        self._previous_trading_day = previous_trading_day_fn or previous_trading_day

    def load(
        self,
        dataset_id: str,
        snapshot_type: str,
        trading_date: str,
        current_timestamp_ms: int,
        window: int | None = None,
    ) -> RotationHistory:
        window = window or self.config.window_slots
        end_date = trading_date
        start_date = self._previous_trading_day(trading_date)  # 跨日基线（H1）
        sector_result = self._repo.list_snapshot_sector_rows(
            dataset_id,
            snapshot_type=snapshot_type,
            start_date=start_date,
            end_date=end_date,
            entity_type="hot_theme",
            sort="asc",
            limit=None,  # 日期范围有界，不做行数截断（M4）
        )
        rows = sector_result.get("rows") or []
        slots_by_ts: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            ts = int(row.get("timestamp") or 0)
            if ts <= 0 or ts >= current_timestamp_ms:
                continue
            slots_by_ts.setdefault(ts, []).append(row)
        ordered = sorted(slots_by_ts.items())[-window:]

        stock_rows = None
        if ordered:
            last_slot_rows = ordered[-1][1]
            last_slot = last_slot_rows[0]
            stock_result = self._repo.list_snapshot_stock_rows(
                dataset_id,
                snapshot_type=snapshot_type,
                trading_date=str(last_slot.get("tradingDate") or trading_date),
                slot_time=str(last_slot.get("slotTime") or ""),
                sort="asc",
                limit=None,
            )
            stock_rows = stock_result.get("rows") or []

        slots: list[HistorySlot] = []
        for index, (ts, slot_rows) in enumerate(ordered):
            is_last = index == len(ordered) - 1
            slots.append(
                HistorySlot(
                    timestamp_ms=ts,
                    trading_date=str(slot_rows[0].get("tradingDate") or ""),
                    sector_rows=slot_rows,
                    stock_rows=stock_rows if is_last else None,
                )
            )
        return RotationHistory(slots=slots, source=str(sector_result.get("source") or "mongodb"))
