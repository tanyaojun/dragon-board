from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import contextmanager, suppress
from typing import Any, Callable, Iterator


logger = logging.getLogger(__name__)

EMPTY_QUOTES: dict[str, Any] = {"rc": 0, "data": {"diff": []}}
_CODE_RE = re.compile(r"^\d{6}$")
_PREFIXES = ("sh", "sz", "bj")


def normalize_stock_code(value: Any) -> str:
    """Normalize a quote code to a 6-digit string, or empty when invalid."""
    text = str(value or "").strip().lower()
    if text[:2] in _PREFIXES:
        text = text[2:]
    text = re.sub(r"\D", "", text)
    return text if _CODE_RE.fullmatch(text) else ""


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_tencent_diff_item(row: dict[str, Any]) -> dict[str, Any]:
    """Map a tencent rank row to the legacy proxy f-field contract.

    旧 proxy `/api/quotes/tencent` 的 `data.diff` 字段（f12/f14/f2/f3/f6/f5/f8/f9/f10/
    f20/f21/f23/f62/f66/f69/f184），前端 QuoteHttpFeed 直接消费，不能改变。
    单位约定：f20/f21 为万元（前端再乘 10000 得到元），f5 为元。
    """
    price = _number(row.get("zxj"))
    volume = _number(row.get("volume"))
    return {
        "f12": normalize_stock_code(row.get("code")),
        "f14": str(row.get("name") or ""),
        "f2": price,
        "f3": _number(row.get("zdf")),
        "f6": volume,
        "f5": round(price * volume * 100, 2),
        "f8": _number(row.get("hsl")),
        "f9": _number(row.get("pe_ttm")),
        "f10": _number(row.get("lb")),
        "f20": round(_number(row.get("zsz")) * 10000, 2),
        "f21": round(_number(row.get("ltsz")) * 10000, 2),
        "f23": _number(row.get("pn")),
        "f62": 0,
        "f66": 0,
        "f69": 0,
        "f184": 0,
    }


@contextmanager
def _silence_tqdm(module: Any) -> Iterator[None]:
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


class MarketQuotesCache:
    """全市场行情（腾讯源）周期刷新缓存。

    用 akshare `stock_zh_a_spot_tx()` 一次拉全市场（约 49 秒），进程内 last-good；
    上游失败保留上一份并记录错误，绝不让行情列表空白（fail-visible）。
    """

    def __init__(
        self,
        *,
        refresh_interval_seconds: float = 300.0,
        akshare_module: Any | None = None,
        tqdm_module: Any | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        # 与 settings 的下限保持一致（QUANT_BOARD_MARKET_QUOTES_REFRESH_INTERVAL_SECONDS 最小 60s）
        self.refresh_interval_seconds = max(60.0, float(refresh_interval_seconds))
        self._ak = akshare_module
        self._tqdm_module = tqdm_module
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._rows: dict[str, dict[str, Any]] = {}
        self._fetched_at_ms = 0
        self._last_error: str | None = None
        self._refresh_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="market-quotes-refresh")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def refresh(self) -> bool:
        if self._refresh_lock.locked():
            return False
        async with self._refresh_lock:
            try:
                frame = await asyncio.to_thread(self._fetch_sync)
            except Exception as exc:
                self._last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                logger.warning("market quotes refresh failed: %s", self._last_error)
                return False
            rows: dict[str, dict[str, Any]] = {}
            records = frame.to_dict("records") if frame is not None else []
            for record in records:
                if not isinstance(record, dict):
                    continue
                code = normalize_stock_code(record.get("code"))
                if not code:
                    continue
                rows[code] = to_tencent_diff_item(record)
            self._rows = rows
            self._fetched_at_ms = self._now_ms()
            self._last_error = None
            return True

    def get_diff(self, codes: list[str]) -> dict[str, Any]:
        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in codes:
            code = normalize_stock_code(raw)
            if not code or code in seen:
                continue
            row = self._rows.get(code)
            if row:
                ordered.append(row)
                seen.add(code)
        return {"rc": 0, "data": {"diff": ordered}}

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "running": self._task is not None and not self._task.done(),
            "source": "akshare-tencent-spot",
            "rowCount": len(self._rows),
            "fetchedAtMs": self._fetched_at_ms,
            "lastError": self._last_error,
            "refreshIntervalSeconds": self.refresh_interval_seconds,
        }

    def _fetch_sync(self) -> Any:
        ak = self._ak
        if ak is None:
            import akshare

            ak = akshare
        module = self._tqdm_module
        if module is None:
            try:
                import akshare.stock.stock_zh_a_tx as tx_module

                module = tx_module
            except Exception:
                module = None
        with _silence_tqdm(module):
            return ak.stock_zh_a_spot_tx()

    async def _run(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(self.refresh_interval_seconds)


_quotes_cache: MarketQuotesCache | None = None


def get_market_quotes_cache() -> MarketQuotesCache:
    global _quotes_cache
    if _quotes_cache is None:
        from backend.settings import get_settings

        _quotes_cache = MarketQuotesCache(
            refresh_interval_seconds=get_settings().market_quotes_refresh_interval_seconds
        )
    return _quotes_cache


async def start_market_quotes_refresh() -> None:
    get_market_quotes_cache().start()


async def stop_market_quotes_refresh() -> None:
    await get_market_quotes_cache().stop()
