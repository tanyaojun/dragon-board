# -*- coding: utf-8 -*-
"""JEV 读口交易日历回退（2026-10-27 用户裁决：文字描述 → 回退显示）。

背景：JEV 叙事工作台日期框默认=当天，盘前/盘中查「当日」时各读口精确匹配到无档
（当日档 15:30-16:20 盘后链才落库），前端整版只剩文字说明（「当日无 X 存档」）。
裁决：全部改为回退显示最近可得存档；前端不加标注文字。

交易日历口径：回退锚 = 各自集合里 ``< 指定日`` 的最大 ``tradingDate``——档案日只
在真实交易日产生，等价交易日历回退（节假日/周末自然跳过），**不做自然日减法**
（TDX 交易日历无需显式引入，档案日期即事实日历）。
"""
from __future__ import annotations

from typing import Any


def resolve_view_date(
    col: Any,
    date: str,
    probe: dict[str, Any] | None = None,
) -> tuple[str, dict[str, str] | None]:
    """返回 ``(生效日期, dateFallback 标记)``。

    指定日有档 → 原样返回、无标记；无档 → ``< 指定日`` 的最新档日并带
    ``{"requested": 原日期, "served": 生效日期}``；全库无档 → 原样返回（由读口
    既有「无存档」路径兜底，不伪造）。``probe`` 为集合特定的前置过滤（如
    datasetId / kind / origin），与档案日共同构成「该源当日有档」的判定。
    """
    query = dict(probe or {})
    if col.find_one({**query, "tradingDate": date}, {"_id": 1}):
        return date, None
    prev = col.find_one(
        {**query, "tradingDate": {"$lt": date, "$ne": None}},
        {"tradingDate": 1},
        sort=[("tradingDate", -1)],
    )
    served = str((prev or {}).get("tradingDate") or "")
    if not served:
        return date, None
    return served, {"requested": date, "served": served}
