from __future__ import annotations

import asyncio
from contextlib import suppress

from backend.services.theme.fund_cache import ThemeFundCache, get_theme_fund_cache


class MarketFundStream:
    """fund-stream 订阅池（market_codes）与 P0 可见行（priority_codes）管理。

    priority_codes 是前端上报的"当前可见/高关注"股票子集（如热榜排序前 N 只），
    供 ThsFundRefreshScheduler 做 P0/P1 分级刷新（P0 更快校准，默认 30 秒）。
    """

    def __init__(self, *, cache: ThemeFundCache) -> None:
        self.cache = cache
        self._subscribers: dict[asyncio.Queue[dict[str, object]], dict[str, object]] = {}
        # 最后已知 owner（浏览器断开后继续刷新的持久池）：订阅/更新时刷新，
        # 全部订阅者断开后由 market_codes/priority_codes 继续返回（owner 持久化）
        self._persisted: dict[str, list[str]] = {"codes": [], "priority": []}
        self.codes_changed = asyncio.Event()

    async def subscribe(
        self,
        codes: list[str],
        *,
        priority_codes: list[str] | None = None,
    ) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=32)
        normalized = self._normalize(codes)
        priority = self._normalize(priority_codes or [])
        self._subscribers[queue] = {"codes": normalized, "priority": priority}
        self._persisted = {"codes": normalized, "priority": priority}
        self.codes_changed.set()
        queue.put_nowait(await self.snapshot(normalized))
        return queue

    async def update(
        self,
        queue: asyncio.Queue[dict[str, object]],
        codes: list[str],
        *,
        priority_codes: list[str] | None = None,
    ) -> None:
        if queue in self._subscribers:
            normalized = self._normalize(codes)
            priority = self._normalize(priority_codes or [])
            self._subscribers[queue] = {"codes": normalized, "priority": priority}
            self._persisted = {"codes": normalized, "priority": priority}
            self.codes_changed.set()

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        # 只移除订阅者；持久池保留（浏览器断开后继续按最后已知池刷新）
        self._subscribers.pop(queue, None)

    def market_codes(self) -> list[str]:
        subscriber_codes = self._normalize(
            [code for sub in self._subscribers.values() for code in sub["codes"]]
        )
        if subscriber_codes:
            return subscriber_codes
        return list(self._persisted["codes"])

    def priority_codes(self) -> list[str]:
        subscriber_priority = self._normalize(
            [code for sub in self._subscribers.values() for code in sub["priority"]]
        )
        if subscriber_priority:
            return subscriber_priority
        return list(self._persisted["priority"])

    def has_active_owner(self) -> bool:
        return bool(self._subscribers)

    def persisted_owner(self) -> dict[str, list[str]]:
        return {
            "codes": list(self._persisted["codes"]),
            "priority": list(self._persisted["priority"]),
        }

    async def snapshot(self, codes: list[str]) -> dict[str, object]:
        rows = await asyncio.to_thread(self.cache.get_latest, self._normalize(codes))
        version = await asyncio.to_thread(self.cache.current_version)
        return {"type": "fund_full_state", "version": version, "items": list(rows.values())}

    def publish(self, rows: list[dict[str, object]]) -> None:
        for queue, sub in list(self._subscribers.items()):
            allowed = set(sub["codes"])
            items = [row for row in rows if str(row.get("code") or "") in allowed]
            if not items:
                continue
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(
                {
                    "type": "fund_patch",
                    "version": max(int(row.get("version") or 0) for row in items),
                    "items": items,
                }
            )

    @staticmethod
    def _normalize(codes: list[str]) -> list[str]:
        return sorted(
            {
                str(code).strip()
                for code in codes
                if len(str(code).strip()) == 6 and str(code).strip().isdigit()
            }
        )


_stream: MarketFundStream | None = None


def get_market_fund_stream() -> MarketFundStream:
    global _stream
    if _stream is None:
        _stream = MarketFundStream(cache=get_theme_fund_cache())
    return _stream
