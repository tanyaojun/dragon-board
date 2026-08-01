from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

import httpx


logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

THS_LIMIT_UP_POOLS: list[dict[str, str]] = [
    {"key": "one", "cate": "limit_up_one", "sourceType": "limit-up-layer"},
    {"key": "two", "cate": "limit_up_two", "sourceType": "limit-up-layer"},
    {"key": "three", "cate": "limit_up_three", "sourceType": "limit-up-layer"},
    {"key": "four", "cate": "limit_up_four", "sourceType": "limit-up-layer"},
    {"key": "high", "cate": "limit_up_high", "sourceType": "limit-up-layer"},
    {"key": "failed", "cate": "limit_up_fail", "sourceType": "open-limit-pool"},
    {"key": "rushing", "cate": "rushing", "sourceType": "rushing-limit-up"},
    {"key": "drawdown", "cate": "limit_up_bigboard", "sourceType": "limit-up-drawdown"},
]


def _current_date() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d")


def _normalize_date(value: str | None) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits if len(digits) == 8 else _current_date()


def _build_pool_url(pool: dict[str, str], date: str) -> str:
    source_type = pool["sourceType"]
    if source_type == "limit-up-drawdown":
        return (
            "https://data.10jqka.com.cn/mobileapi/hotspot_focus/stock_pool/v1/"
            f"get_drawdown_stocks?date={date}&cate=limit_up&sort_field=max_drawdown"
            "&sort_dir=asc&page=1&size=200"
        )
    if source_type == "open-limit-pool":
        return (
            "https://data.10jqka.com.cn/dataapi/limit_up/open_limit_pool?page=1&limit=200"
            "&field=199112%2C9002%2C48%2C1968584%2C19%2C3475914%2C9003%2C10%2C9004"
            f"&filter=HS%2CGEM2STAR&order_field=199112&order_type=0&date={date}"
        )
    if source_type == "rushing-limit-up":
        return (
            "https://data.10jqka.com.cn/dataapi/limit_up/limit_up?page=1&limit=200"
            "&field=199112%2C10%2C48%2C1968584%2C19%2C3475914%2C9003%2C9004"
            f"&filter=HS%2CGEM2STAR&order_field=199112&order_type=0&date={date}"
        )
    return (
        "https://data.10jqka.com.cn/mobileapi/hotspot_focus/stock_pool/v1/"
        f"get_limit_up_stocks?date={date}&cate={pool['cate']}&sort_field=limit_up_time"
        "&sort_dir=asc&page=1&size=200"
    )


def _extract_items(payload: Any) -> list[Any]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        if isinstance(data.get("stock_list"), list):
            return data["stock_list"]
        if isinstance(data.get("info"), list):
            return data["info"]
    if isinstance(payload, dict):
        if isinstance(payload.get("stock_list"), list):
            return payload["stock_list"]
        if isinstance(payload.get("info"), list):
            return payload["info"]
    return []


def _extract_total(payload: Any, items: list[Any]) -> int:
    data = payload.get("data") if isinstance(payload, dict) else None
    candidates = []
    if isinstance(data, dict):
        candidates.extend([data.get("page_info"), data.get("page")])
    if isinstance(payload, dict):
        candidates.extend([payload.get("page_info"), payload.get("page")])
    for candidate in candidates:
        if isinstance(candidate, dict):
            for key in ("total",):
                try:
                    value = int(candidate.get(key) or 0)
                except (TypeError, ValueError):
                    continue
                if value:
                    return value
    return len(items)


def _validate_10jqka_payload(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("invalid ths limit-up payload")
    data = payload.get("data")
    if data is not None and not isinstance(data, dict):
        raise ValueError("invalid ths limit-up payload")
    if isinstance(data, dict) and "info" in data and not isinstance(data["info"], list):
        raise ValueError("invalid ths limit-up payload")
    if not isinstance(data, dict) or not isinstance(data.get("info"), list):
        raise ValueError("missing ths limit-up info")


class LimitUpService:
    """THS 涨停池/细分池：httpx 直连 10jqka，进程内 TTL 缓存。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        ttl_seconds: float = 30.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache: dict[str, dict[str, Any]] = {}

    async def get_limit_up_list(self, date: str | None = None) -> Any:
        date_str = _normalize_date(date)
        cache_key = f"limitup:{date_str}"
        cached = self._cache.get(cache_key)
        now_ms = self._now_ms()
        if cached and now_ms - cached["fetched_at_ms"] < self._ttl_ms:
            return cached["payload"]
        url = (
            "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200"
            "&field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,"
            "1968584,3475914,9003,9004,continue_day,continue_day_cnt,high_days,reason_type"
            f"&filter=HS,GEM2STAR&order_field=330324&order_type=0&date={date_str}"
        )
        response = await (self._client or get_limitup_client()).get(
            url, timeout=8.0, headers={"User-Agent": UA}
        )
        response.raise_for_status()
        payload = response.json()
        _validate_10jqka_payload(payload)
        self._cache[cache_key] = {"payload": payload, "fetched_at_ms": now_ms}
        return payload

    async def get_ths_pools(self, date: str | None = None) -> dict[str, Any]:
        date_str = _normalize_date(date)
        cache_key = f"ths-pools:{date_str}"
        cached = self._cache.get(cache_key)
        now_ms = self._now_ms()
        if cached and now_ms - cached["fetched_at_ms"] < self._ttl_ms:
            return cached["payload"]
        client = self._client or get_limitup_client()

        async def load(pool: dict[str, str]) -> tuple[str, dict[str, Any]]:
            try:
                response = await client.get(
                    _build_pool_url(pool, date_str),
                    timeout=8.0,
                    headers={"User-Agent": UA},
                )
                response.raise_for_status()
                payload = response.json()
                items = _extract_items(payload)
                return pool["key"], {
                    "ok": True,
                    "key": pool["key"],
                    "cate": pool["cate"],
                    "total": _extract_total(payload, items),
                    "items": items,
                }
            except Exception as exc:
                return pool["key"], {
                    "ok": False,
                    "key": pool["key"],
                    "cate": pool["cate"],
                    "total": 0,
                    "items": [],
                    "errorCode": "upstream_unavailable",
                    "message": str(exc)[:200],
                }

        entries = await asyncio.gather(*(load(pool) for pool in THS_LIMIT_UP_POOLS))
        pools = dict(entries)
        errors = [
            {"pool": pool["key"], "errorCode": info.get("errorCode"), "message": info.get("message")}
            for pool, info in zip(THS_LIMIT_UP_POOLS, entries)
            if not info[1].get("ok")
        ]
        payload = {
            "ok": len(errors) == 0,
            "degraded": len(errors) > 0,
            "source": "limitup-ths-pools",
            "date": date_str,
            "timestamp": now_ms,
            "pools": pools,
            "errors": errors,
        }
        self._cache[cache_key] = {"payload": payload, "fetched_at_ms": now_ms}
        return payload


_limitup_client: httpx.AsyncClient | None = None
_limitup_service: LimitUpService | None = None


def get_limitup_client() -> httpx.AsyncClient:
    global _limitup_client
    if _limitup_client is None:
        _limitup_client = httpx.AsyncClient(
            timeout=8.0, headers={"User-Agent": UA}
        )
    return _limitup_client


def get_limitup_service() -> LimitUpService:
    global _limitup_service
    if _limitup_service is None:
        _limitup_service = LimitUpService()
    return _limitup_service


async def close_limitup_client() -> None:
    global _limitup_client
    client = _limitup_client
    _limitup_client = None
    if client is not None:
        await client.aclose()
