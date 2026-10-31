# -*- coding: utf-8 -*-
"""龙虎榜按日读口「当日无数据回退」公共助手（2026-10-30 用户裁决）。

当日（盘前/盘中未生成/非交易日）结构化空态时，按日历日逐日回看至最近有数据的
交易日（默认上限 10 个日历日，跨更长假期请显式指定历史日期）。回退必须显式
标注（note + effective_date + requested_date），不得伪装成当日数据（fail-visible：
AGENTS §4.0 禁止把空结果伪装成有数据；回退是显式降级展示而非硬门禁）。

fetch 由调用方提供，需自带缓存/限频保护（KPL 上游限频分钟级、东财多报表拉全）。
"""
from __future__ import annotations

import datetime as dt
import inspect
from collections.abc import Callable
from typing import Any

MAX_BACK_DAYS = 10


def _prev_date(date: str) -> str | None:
    try:
        return (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()
    except ValueError:
        return None


async def walk_back(
    date: str,
    fetch: Callable[[str], Any],
    is_empty: Callable[[Any], bool],
    max_back: int = MAX_BACK_DAYS,
) -> Any:
    """从 date 起逐日历日回看，返回首个非空 payload；全空返回最后一次空 payload。

    fetch 同步/异步皆可（返回 awaitable 自动 await）；命中回退时在 payload 上补：
    requested_date（用户请求日）、effective_date（实际数据日）、note（「当日无数据，
    已回退至 X」）；连续 max_back 日全空则保留空 payload 并显式注明未回退，由调用方
    按各自空态合同返回。
    """
    cur = date
    payload: Any = None
    for _ in range(max_back + 1):
        payload = fetch(cur)
        if inspect.isawaitable(payload):
            payload = await payload
        if not is_empty(payload):
            if cur != date:
                effective = payload.get("date") or cur
                payload["requested_date"] = date
                payload["effective_date"] = effective
                payload["note"] = (
                    f"{date} 当日无数据，已回退至 {effective}"
                    + (f"（{payload['note']}）" if payload.get("note") else "")
                )
            return payload
        nxt = _prev_date(cur)
        if nxt is None:
            break
        cur = nxt
    if payload is not None:
        payload["requested_date"] = date
        payload["note"] = (
            f"{date} 起回看 {max_back} 个日历日均为空（盘前/盘中查当日属正常：榜约 17:00 "
            "后生成；跨长假请显式指定历史日期），未回退，非降级"
            + (f"（{payload['note']}）" if payload.get("note") else "")
        )
    return payload
