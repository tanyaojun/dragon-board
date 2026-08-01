from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any, Callable

import httpx


logger = logging.getLogger(__name__)

LONGHU_URL = "https://apphwhq.longhuvip.com/w1/api/index.php"
UA = "Dalvik/2.1.0 (Linux; U; Android 9; MI 8 MIUI/V11.0.5.0.PEACNXM)"
PAGE_SIZE = 200


class LonghuIntegrityError(RuntimeError):
    pass


def _form_body(stock_code: str, money: int, index: int, device: str) -> dict[str, str]:
    return {
        "Order": "0",
        "st": str(PAGE_SIZE),
        "a": "GetMainMonitor_w30",
        "c": "StockYiDongKanPan",
        "PhoneOSNew": "1",
        "DeviceID": device,
        "VerSion": "5.17.0.4",
        "Index": str(index),
        "Money": str(money),
        "apiv": "w36",
        "StockID": stock_code,
        "IsBS": "0",
    }


class LonghuBigOrderService:
    """龙虎榜大单（GetMainMonitor_w30）分页抓取 + 进程内缓存 + 熔断。

    响应合同与旧 proxy 一致：main-monitor 返回 `{errcode, Total, List}`，
    all-day 返回 `{List}`；List 元素为 `[type, orderId, volume, amount, price, time]`。
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        delay_ms: float = 150.0,
        ttl_seconds: float = 60.0,
        full_rebuild_budget_ms: float = 45_000.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._delay_seconds = max(0.0, delay_ms / 1000)
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._budget_ms = max(1_000.0, float(full_rebuild_budget_ms))
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._all_day_cache: dict[str, dict[str, Any]] = {}
        self._source_failure_count = 0
        self._breaker_until_ms = 0
        # 与旧 proxy 的 maxEntries=24 对齐：防止长跑服务无界增长
        self._all_day_max_entries = 24

    async def load_page(
        self,
        stock_code: str,
        *,
        money: int = 0,
        index: int = 0,
        limit: int = 100,
    ) -> dict[str, Any]:
        device = secrets.token_hex(16)
        output: list[Any] = []
        offset = index
        expected_total: int | None = None
        client = self._client or _get_longhu_client()
        while True:
            rows, total = await self._request_page(
                client, stock_code, money, offset, device
            )
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise LonghuIntegrityError("Longhu Total changed during pagination")
            take = min(len(rows), limit - len(output))
            output.extend(rows[:take])
            offset += len(rows)
            target = min(limit, max(0, expected_total - index))
            if len(output) >= target:
                return {"errcode": "0", "Total": expected_total, "List": output}
            if len(rows) < PAGE_SIZE:
                raise LonghuIntegrityError("truncated Longhu page response")
            await asyncio.sleep(self._delay_seconds)

    async def load_all_day(self, stock_code: str, *, money: int = 0) -> dict[str, Any]:
        cache_key = f"{stock_code}:{money}"
        cached = self._all_day_cache.get(cache_key)
        now_ms = self._now_ms()
        if cached and now_ms - cached["fetched_at_ms"] < self._ttl_ms:
            return {"List": cached["payload"]}
        started_at = now_ms
        try:
            rows = await self._rebuild(stock_code, money, started_at)
        except Exception:
            if cached is not None:
                logger.warning("longhu rebuild failed, serving last-good: %s", stock_code)
                return {"List": cached["payload"]}
            raise
        self._all_day_cache[cache_key] = {"payload": rows, "fetched_at_ms": now_ms}
        if len(self._all_day_cache) > self._all_day_max_entries:
            oldest_key = min(
                self._all_day_cache,
                key=lambda key: self._all_day_cache[key]["fetched_at_ms"],
            )
            self._all_day_cache.pop(oldest_key, None)
        return {"List": rows}

    async def _rebuild(self, stock_code: str, money: int, started_at: int) -> list[Any]:
        device = secrets.token_hex(16)
        rows: list[Any] = []
        expected_total: int | None = None
        client = self._client or _get_longhu_client()
        while expected_total is None or len(rows) < expected_total:
            if self._now_ms() - started_at > self._budget_ms:
                raise LonghuIntegrityError("Longhu full rebuild budget exceeded")
            index = len(rows)
            page_rows, total = await self._request_page(
                client, stock_code, money, index, device
            )
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise LonghuIntegrityError("Longhu Total changed during pagination")
            expected_page_len = min(PAGE_SIZE, max(0, total - index))
            if len(page_rows) < expected_page_len:
                # 短页 = 上游截断：静默拼接会让后续行整体错位，必须显式失败（fail-visible）
                raise LonghuIntegrityError("truncated Longhu page response")
            if len(page_rows) > expected_page_len:
                raise LonghuIntegrityError("Longhu response exceeds page boundary")
            rows.extend(page_rows)
            if len(rows) > expected_total:
                raise LonghuIntegrityError("Longhu response exceeds Total")
            if len(rows) < expected_total:
                await asyncio.sleep(self._delay_seconds)
        return rows

    async def _request_page(
        self,
        client: httpx.AsyncClient,
        stock_code: str,
        money: int,
        index: int,
        device: str,
    ) -> tuple[list[Any], int]:
        now_ms = self._now_ms()
        if now_ms < self._breaker_until_ms:
            raise LonghuIntegrityError("big_order_source_circuit_open")
        try:
            response = await client.post(
                LONGHU_URL,
                data=_form_body(stock_code, money, index, device),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": UA,
                },
                timeout=15.0,
            )
            self._source_failure_count = 0
        except Exception:
            self._source_failure_count += 1
            if self._source_failure_count >= 3:
                self._breaker_until_ms = now_ms + 60_000
                self._source_failure_count = 0
                logger.warning("[龙虎大单] 连续 3 次网络级失败，熔断 60 秒")
            raise
        payload = response.json()
        if (
            not isinstance(payload, dict)
            or str(payload.get("errcode")) != "0"
            or not isinstance(payload.get("List"), list)
        ):
            raise LonghuIntegrityError(str(payload.get("msg") or "invalid Longhu payload"))
        try:
            total = int(payload.get("Total"))
        except (TypeError, ValueError):
            raise LonghuIntegrityError("invalid Longhu Total") from None
        if total < 0:
            raise LonghuIntegrityError("invalid Longhu Total")
        return payload["List"], total


_longhu_client: httpx.AsyncClient | None = None
_longhu_service: LonghuBigOrderService | None = None


def _get_longhu_client() -> httpx.AsyncClient:
    global _longhu_client
    if _longhu_client is None:
        _longhu_client = httpx.AsyncClient(timeout=15.0)
    return _longhu_client


def get_longhu_service() -> LonghuBigOrderService:
    global _longhu_service
    if _longhu_service is None:
        _longhu_service = LonghuBigOrderService()
    return _longhu_service


async def close_longhu_client() -> None:
    global _longhu_client
    client = _longhu_client
    _longhu_client = None
    if client is not None:
        await client.aclose()
