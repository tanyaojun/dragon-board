"""题材日线序列聚合（题材动量 v2 第一层）。

把 sector rows（hot_theme；生产=帧内嵌 sectorRows，2026-11-19 起独立集合已 drop）按交易日聚合为每题材日线序列：
- 虚拟收益指数：每个交易日取收盘槽（15:00 或最后一槽）的 change（成分股平均涨幅），
  累乘合成 Index_t = Π(1 + change_t)，供 RPS/距年内高点/多窗口动量使用。
- 辅助日线：日 ztCount（收盘槽）、日 breadthScore（收盘槽）、日 mainNetInflow（收盘槽）、
  日成交额占比（metadata.amountRatio）。

纯函数 + 可注入 rows，不访问 HTTP/MongoDB；缺失只打标记不补零。
本模块是 v2 重构的日线聚合层，与单文件 theme_momentum.py（v1）并存，未来可并入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator


@dataclass
class ThemeDailySeries:
    """一个题材的日线序列。

    各维度以平行列表字段存储（dates/changes/...，供 virtual_index 与动量计算直接消费），
    days 派生为 dict 列表，每个 day dict 含 date/change/ztCount/breadthScore/
    mainNetInflow/amountRatio/qualityFlags 键，支持下标与迭代访问。
    """

    theme_id: str
    theme_name: str
    dates: list[str] = field(default_factory=list)
    changes: list[float] = field(default_factory=list)
    zt_counts: list[int] = field(default_factory=list)
    breadths: list[float] = field(default_factory=list)
    inflows: list[float] = field(default_factory=list)
    amount_ratios: list[float] = field(default_factory=list)
    crowding_days: list[float | None] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    latest_slots: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _day_flags: list[list[str]] = field(default_factory=list, repr=False)

    @property
    def days(self) -> list[dict[str, Any]]:
        return [
            {
                "date": date,
                "change": change,
                "ztCount": zt,
                "breadthScore": breadth,
                "mainNetInflow": inflow,
                "amountRatio": ratio,
                "crowdingRisk": (
                    self.crowding_days[i] if i < len(self.crowding_days) else None
                ),
                "qualityFlags": (
                    self._day_flags[i] if i < len(self._day_flags) else []
                ),
            }
            for i, (date, change, zt, breadth, inflow, ratio) in enumerate(
                zip(
                    self.dates, self.changes, self.zt_counts,
                    self.breadths, self.inflows, self.amount_ratios,
                )
            )
        ]

    def __len__(self) -> int:
        return len(self.dates)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self.days[index]

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self.days)


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return v if v == v else default  # NaN → None


def _theme_key(row: dict[str, Any]) -> str:
    return str(row.get("themeId") or row.get("entityKey") or row.get("code") or "").strip()


def _theme_name(row: dict[str, Any]) -> str:
    return str(row.get("themeName") or row.get("entityName") or _theme_key(row))


def _close_slot_time(slot_time: str) -> bool:
    """收盘槽：15:00 之后（A 股 15:00 收盘），或 11:30-13:00 之间的上午收盘槽。"""
    if slot_time >= "15:00":
        return True
    return "11:30" <= slot_time < "13:00"


def build_daily_series(
    sector_rows: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
) -> dict[str, ThemeDailySeries]:
    """按交易日聚合 sector rows 为日线序列。

    - 每日期望取收盘槽（slotTime >= 15:00 或 11:30-13:00）；无收盘槽回退当日最后一槽并打
      `close_slot_missing` 标记。
    - 漏采交易日为空槽（不补零，由消费方按日期间隔判定缺槽）。
    - stock_rows（snapshot_stock_rows）当前仅预留参数位：个股明细聚合由后续任务消费。
    """
    by_theme: dict[str, list[dict[str, Any]]] = {}
    for row in sector_rows:
        key = _theme_key(row)
        if not key or str(row.get("entityType") or "hot_theme") != "hot_theme":
            continue
        by_theme.setdefault(key, []).append(row)

    out: dict[str, ThemeDailySeries] = {}
    for key, rows in by_theme.items():
        by_date: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            date = str(row.get("tradingDate") or "").strip()
            if date:
                by_date.setdefault(date, []).append(row)
        dates = sorted(by_date)
        if not dates:
            continue
        day_dates: list[str] = []
        day_changes: list[float] = []
        day_zt: list[int] = []
        day_breadths: list[float] = []
        day_inflows: list[float] = []
        day_ratios: list[float] = []
        day_crowding: list[float | None] = []
        day_flags: list[list[str]] = []
        latest_slots: list[dict[str, Any]] = []
        for date in dates:
            day_rows = sorted(
                by_date[date], key=lambda r: str(r.get("slotTime") or "")
            )
            close = [
                r for r in day_rows
                if _close_slot_time(str(r.get("slotTime") or ""))
            ]
            chosen = close[-1] if close else day_rows[-1]
            flags: list[str] = []
            if not close:
                flags.append("close_slot_missing")
            metadata = chosen.get("metadata")
            ratio = metadata.get("amountRatio") if isinstance(metadata, dict) else None
            if _num(ratio) is None:
                flags.append("amount_ratio_missing")
            crowding_raw = chosen.get("crowdingRisk")
            crowding = (
                float(crowding_raw) if _num(crowding_raw) is not None else None
            )
            day_dates.append(date)
            day_changes.append(_num(chosen.get("change")) or 0.0)
            day_zt.append(int(_num(chosen.get("ztCount"), 0) or 0))
            day_breadths.append(_num(chosen.get("breadthScore")) or 0.0)
            day_inflows.append(_num(chosen.get("mainNetInflow")) or 0.0)
            day_ratios.append(float(ratio) if _num(ratio) is not None else 0.0)
            day_crowding.append(crowding)
            day_flags.append(flags)
            # 槽位快照（供 intraday 辅口径）：保留当日收盘槽与前一日收盘槽
            latest_slots.append({
                "tradingDate": date,
                "slotTime": str(chosen.get("slotTime") or ""),
                "change": _num(chosen.get("change")) or 0.0,
                "ztCount": int(_num(chosen.get("ztCount"), 0) or 0),
                "mainNetInflow": _num(chosen.get("mainNetInflow")) or 0.0,
            })
        theme_flags: list[str] = []
        for flags in day_flags:
            for flag in flags:
                if flag not in theme_flags:
                    theme_flags.append(flag)
        out[key] = ThemeDailySeries(
            theme_id=key,
            theme_name=_theme_name(rows[0]),
            dates=day_dates,
            changes=day_changes,
            zt_counts=day_zt,
            breadths=day_breadths,
            inflows=day_inflows,
            amount_ratios=day_ratios,
            crowding_days=day_crowding,
            quality_flags=theme_flags,
            latest_slots=latest_slots,
            _day_flags=day_flags,
        )
    return out


def virtual_index(changes: list[float]) -> list[float]:
    """累乘合成虚拟收益指数：Index_t = Π(1 + change_t)，起点 1.0。"""
    index: list[float] = []
    value = 1.0
    for change in changes:
        value *= 1.0 + change
        index.append(value)
    return index
