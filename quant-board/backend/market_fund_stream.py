from __future__ import annotations

import asyncio
from contextlib import suppress

from backend.theme_fund_cache import ThemeFundCache, get_theme_fund_cache


class MarketFundStream:
    def __init__(self, *, cache: ThemeFundCache) -> None:
        self.cache = cache
        self._subscribers: dict[asyncio.Queue[dict[str, object]], list[str]] = {}
        self.codes_changed = asyncio.Event()

    async def subscribe(self, codes: list[str]) -> asyncio.Queue[dict[str, object]]:
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=32)
        normalized = self._normalize(codes)
        self._subscribers[queue] = normalized
        self.codes_changed.set()
        queue.put_nowait(await self.snapshot(normalized))
        return queue

    async def update(self, queue: asyncio.Queue[dict[str, object]], codes: list[str]) -> None:
        if queue in self._subscribers:
            self._subscribers[queue] = self._normalize(codes)
            self.codes_changed.set()

    def unsubscribe(self, queue: asyncio.Queue[dict[str, object]]) -> None:
        self._subscribers.pop(queue, None)

    def market_codes(self) -> list[str]:
        return self._normalize([code for codes in self._subscribers.values() for code in codes])

    async def snapshot(self, codes: list[str]) -> dict[str, object]:
        rows = await asyncio.to_thread(self.cache.get_latest, self._normalize(codes))
        version = await asyncio.to_thread(self.cache.current_version)
        return {"type": "fund_full_state", "version": version, "items": list(rows.values())}

    def publish(self, rows: list[dict[str, object]]) -> None:
        for queue, codes in list(self._subscribers.items()):
            allowed = set(codes)
            items = [row for row in rows if str(row.get("code") or "") in allowed]
            if not items:
                continue
            if queue.full():
                with suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait({"type": "fund_patch", "version": max(int(row.get("version") or 0) for row in items), "items": items})

    @staticmethod
    def _normalize(codes: list[str]) -> list[str]:
        return sorted({str(code).strip() for code in codes if len(str(code).strip()) == 6 and str(code).strip().isdigit()})


_stream: MarketFundStream | None = None


def get_market_fund_stream() -> MarketFundStream:
    global _stream
    if _stream is None:
        _stream = MarketFundStream(cache=get_theme_fund_cache())
    return _stream
