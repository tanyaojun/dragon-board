from __future__ import annotations

import asyncio
from contextlib import suppress

from backend.theme_fund_cache import ThemeFundCache, get_theme_fund_cache


class ThemeFundStream:
    def __init__(self, *, cache: ThemeFundCache) -> None:
        self.cache = cache
        self._subscribers: dict[
            asyncio.Queue[dict[str, object]], tuple[list[str], list[str]]
        ] = {}

    def subscribe(
        self,
        *,
        market_codes: list[str],
        priority_codes: list[str],
    ) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=32)
        market = self._normalize_codes(market_codes)
        priority = self._normalize_codes(priority_codes)
        self._subscribers[queue] = (market, priority)
        self._persist_active_market_codes()
        queue.put_nowait(self.snapshot(market, priority))
        return queue

    async def subscribe_async(
        self,
        *,
        market_codes: list[str],
        priority_codes: list[str],
    ) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=32)
        market = self._normalize_codes(market_codes)
        priority = self._normalize_codes(priority_codes)
        self._subscribers[queue] = (market, priority)
        await self._persist_active_market_codes_async()
        queue.put_nowait(await self.snapshot_async(market, priority))
        return queue

    def update_subscription(
        self,
        queue: asyncio.Queue[dict[str, object]],
        *,
        market_codes: list[str],
        priority_codes: list[str],
    ) -> None:
        if queue not in self._subscribers:
            return
        market = self._normalize_codes(market_codes)
        priority = self._normalize_codes(priority_codes)
        self._subscribers[queue] = (market, priority)
        self._persist_active_market_codes()

    async def update_subscription_async(
        self,
        queue: asyncio.Queue[dict[str, object]],
        *,
        market_codes: list[str],
        priority_codes: list[str],
    ) -> None:
        if queue not in self._subscribers:
            return
        market = self._normalize_codes(market_codes)
        priority = self._normalize_codes(priority_codes)
        self._subscribers[queue] = (market, priority)
        await self._persist_active_market_codes_async()

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._subscribers.pop(queue, None)
        self._persist_active_market_codes()

    async def unsubscribe_async(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._subscribers.pop(queue, None)
        await self._persist_active_market_codes_async()

    def market_codes(self) -> list[str]:
        owners = self.cache.get_owner_codes()
        return self._normalize_codes(owners.get("dragon-board", []))

    def priority_codes(self) -> list[str]:
        return self._merge(priority for _, priority in self._subscribers.values())

    def _persist_active_market_codes(self) -> None:
        if not self._subscribers:
            return
        market = self._merge(codes for codes, _ in self._subscribers.values())
        if market:
            self.cache.set_owner_codes("dragon-board", market)

    async def _persist_active_market_codes_async(self) -> None:
        if not self._subscribers:
            return
        market = self._merge(codes for codes, _ in list(self._subscribers.values()))
        if market:
            await asyncio.to_thread(self.cache.set_owner_codes, "dragon-board", market)

    def snapshot(self, market_codes: list[str], priority_codes: list[str]) -> dict[str, object]:
        codes = self._merge((market_codes, priority_codes))
        rows = list(self.cache.get_latest(codes).values())
        return {
            "type": "fund_full_state",
            "version": self.cache.current_version(),
            "items": rows,
        }

    async def snapshot_async(
        self,
        market_codes: list[str],
        priority_codes: list[str],
    ) -> dict[str, object]:
        codes = self._merge((market_codes, priority_codes))
        rows = list((await asyncio.to_thread(self.cache.get_latest, codes)).values())
        version = await asyncio.to_thread(self.cache.current_version)
        return {
            "type": "fund_full_state",
            "version": version,
            "items": rows,
        }

    def publish(self, rows: list[dict[str, object]]) -> None:
        for queue, (market, priority) in list(self._subscribers.items()):
            code_set = set(self._merge((market, priority)))
            items = [row for row in rows if str(row.get("code") or "") in code_set]
            if not items:
                continue
            payload: dict[str, object] = {
                "type": "fund_patch",
                "version": max(int(row.get("version") or 0) for row in items),
                "items": items,
            }
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(payload)

    @staticmethod
    def _normalize_codes(codes: list[str]) -> list[str]:
        return list(
            dict.fromkeys(
                str(code).strip()
                for code in codes
                if len(str(code).strip()) == 6 and str(code).strip().isdigit()
            )
        )

    @classmethod
    def _merge(cls, groups) -> list[str]:
        merged: list[str] = []
        seen: set[str] = set()
        for group in groups:
            for code in cls._normalize_codes(list(group)):
                if code not in seen:
                    seen.add(code)
                    merged.append(code)
        return merged


_theme_fund_stream: ThemeFundStream | None = None


def get_theme_fund_stream() -> ThemeFundStream:
    global _theme_fund_stream
    if _theme_fund_stream is None:
        _theme_fund_stream = ThemeFundStream(cache=get_theme_fund_cache())
    return _theme_fund_stream
