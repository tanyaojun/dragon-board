from __future__ import annotations

import asyncio
import json
import time
from contextlib import contextmanager
from typing import Any, Callable


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@contextmanager
def _silence_tqdm(module: Any):
    original = getattr(module, "get_tqdm", None) if module is not None else None
    if module is not None and original is not None:
        module.get_tqdm = lambda *args, **kwargs: (
            lambda iterable, *iter_args, **iter_kwargs: iterable
        )
    try:
        yield
    finally:
        if module is not None and original is not None:
            module.get_tqdm = original


class MarketOverviewService:
    """指数大盘概览：akshare 新浪指数实时行情 + 进程内短缓存。

    上游失败时保留上次成功结果并标记 stale（fail-visible）；从未成功过则抛错由路由降级。
    """

    def __init__(
        self,
        *,
        akshare_module: Any | None = None,
        redis_client: Any | None = None,
        redis_key_prefix: str = "",
        ttl_seconds: float = 10.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._ak = akshare_module
        self._redis = redis_client
        self._redis_prefix = str(redis_key_prefix or "").strip(":")
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._snapshot: dict[str, Any] | None = None
        self._cached_at_ms = 0

    async def get_overview(self) -> dict[str, Any]:
        now_ms = self._now_ms()
        if self._snapshot is not None and now_ms - self._cached_at_ms < self._ttl_ms:
            return self._snapshot
        # 共享 Redis TTL 缓存：跨进程/跨重启 last-good，冷启动直接命中
        redis_snapshot = self._redis_get()
        if redis_snapshot is not None:
            self._snapshot = redis_snapshot
            self._cached_at_ms = now_ms
            return redis_snapshot
        frame = await asyncio.to_thread(self._fetch_sync)
        items = self._normalize(frame)
        snapshot = {
            "ok": True,
            "source": "akshare-sina-index",
            "timestamp": now_ms,
            "stale": False,
            "items": items,
        }
        self._snapshot = snapshot
        self._cached_at_ms = now_ms
        self._redis_set(snapshot)
        return snapshot

    def stale_snapshot(self) -> dict[str, Any] | None:
        if self._snapshot is None:
            return None
        return {**self._snapshot, "stale": True}

    def _redis_key(self) -> str:
        suffix = "market:overview:v1"
        return f"{self._redis_prefix}:{suffix}" if self._redis_prefix else suffix

    def _redis_get(self) -> dict[str, Any] | None:
        client = self._redis
        if client is None:
            return None
        try:
            raw = client.get(self._redis_key())
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(str(raw))
            return value if isinstance(value, dict) and value.get("items") is not None else None
        except Exception:
            return None

    def _redis_set(self, snapshot: dict[str, Any]) -> None:
        client = self._redis
        if client is None:
            return
        try:
            client.setex(
                self._redis_key(),
                max(1, int(self._ttl_ms / 1000)),
                json.dumps(snapshot, ensure_ascii=False),
            )
        except Exception:
            return

    def _fetch_sync(self) -> Any:
        ak = self._ak
        if ak is None:
            import akshare

            ak = akshare
        module = None
        if self._ak is None:
            try:
                import akshare.index.index_stock_zh as index_module

                module = index_module
            except Exception:
                module = None
        with _silence_tqdm(module):
            return ak.stock_zh_index_spot_sina()

    @staticmethod
    def _normalize(frame: Any) -> list[dict[str, Any]]:
        if frame is None or not hasattr(frame, "to_dict"):
            return []
        items: list[dict[str, Any]] = []
        for record in frame.to_dict("records"):
            if not isinstance(record, dict):
                continue
            items.append(
                {
                    "code": str(record.get("代码") or ""),
                    "name": str(record.get("名称") or ""),
                    "price": _number(record.get("最新价")),
                    "change": _number(record.get("涨跌额")),
                    "changePct": _number(record.get("涨跌幅")),
                    "prevClose": _number(record.get("昨收")),
                    "open": _number(record.get("今开")),
                    "high": _number(record.get("最高")),
                    "low": _number(record.get("最低")),
                    "volume": _number(record.get("成交量")),
                    "amount": _number(record.get("成交额")),
                }
            )
        return items


_overview_service: MarketOverviewService | None = None


def get_market_overview_service() -> MarketOverviewService:
    global _overview_service
    if _overview_service is None:
        from backend.core.settings import get_settings
        from backend.market_proxy.cache import get_hotlist_redis_client

        settings = get_settings()
        _overview_service = MarketOverviewService(
            redis_client=get_hotlist_redis_client(settings),
            redis_key_prefix=settings.redis_key_prefix,
        )
    return _overview_service
