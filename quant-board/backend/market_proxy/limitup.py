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
    """THS 涨停池/细分池：httpx 直连 10jqka，进程内 TTL 缓存。

    风控对策（2026-10-02 复盘：9 月 limitSummary 间歇缺失=THS 限流返空 200+空 info，
    越到尾盘累计量越大失败越狠）：
    - 请求最小间隔节流（含并行池错峰），杜绝同刻 8 连发突发；
    - 疑似风控返空（HTTP 200 但 info 空）按连续次数指数退避负缓存，不原样重打。
    """

    # 连板层池（one/two/three/four/high）在采集链零消费、仅面板透传展示用
    POOL_KEYS_ALL = tuple(p["key"] for p in THS_LIMIT_UP_POOLS)

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        ttl_seconds: float = 30.0,
        now_ms: Callable[[], int] | None = None,
        sleep_fn: Callable[..., Any] | None = None,
        min_request_gap_ms: float = 250.0,
        empty_backoff_base_ms: float = 30_000.0,
        empty_backoff_cap_ms: float = 300_000.0,
    ) -> None:
        self._client = client
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._sleep = sleep_fn or asyncio.sleep
        self._min_gap_ms = max(0.0, float(min_request_gap_ms))
        self._empty_backoff_base_ms = float(empty_backoff_base_ms)
        self._empty_backoff_cap_ms = float(empty_backoff_cap_ms)
        self._cache: dict[str, dict[str, Any]] = {}
        self._last_request_ms: float | None = None
        self._empty_streak: dict[str, int] = {}

    async def _throttle(self) -> None:
        """全局最小请求间隔（跨并行任务串行放行，错峰不突发）。"""
        if self._min_gap_ms <= 0:
            return
        async with asyncio.Lock():
            now = self._now_ms()
            if self._last_request_ms is not None:
                wait_ms = self._min_gap_ms - (now - self._last_request_ms)
                if wait_ms > 0:
                    await self._sleep(wait_ms / 1000.0)
            self._last_request_ms = self._now_ms()

    def _empty_backoff_ms(self, key: str) -> float:
        streak = self._empty_streak.get(key, 0)
        if streak <= 0:
            return 0.0
        return min(self._empty_backoff_base_ms * (2 ** (streak - 1)), self._empty_backoff_cap_ms)

    async def get_limit_up_list(self, date: str | None = None) -> Any:
        date_str = _normalize_date(date)
        cache_key = f"limitup:{date_str}"
        cached = self._cache.get(cache_key)
        now_ms = self._now_ms()
        backoff_ms = self._empty_backoff_ms(cache_key)
        if cached and now_ms - cached["fetched_at_ms"] < self._ttl_ms:
            return cached["payload"]
        if cached and cached.get("empty") and now_ms - cached["fetched_at_ms"] < backoff_ms:
            # 疑似风控返空：退避窗口内直接复用空结果，不原样重打
            return cached["payload"]
        await self._throttle()
        url = (
            "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool?page=1&limit=200"
            "&field=199112,10,9001,330323,330324,330325,9002,330329,133971,133970,"
            "1968584,3475914,9003,9004,continue_day,continue_day_cnt,high_days,reason_type"
            f"&filter=HS,GEM2STAR&order_field=330324&order_type=0&date={date_str}"
        )
        client = self._client or get_limitup_client()
        response = await client.get(
            url, timeout=8.0, headers={"User-Agent": UA}
        )
        response.raise_for_status()
        payload = response.json()
        _validate_10jqka_payload(payload)
        data = payload.get("data") if isinstance(payload, dict) else None
        info = data.get("info") if isinstance(data, dict) else None
        empty = isinstance(info, list) and len(info) == 0
        if empty:
            self._empty_streak[cache_key] = self._empty_streak.get(cache_key, 0) + 1
        else:
            self._empty_streak[cache_key] = 0
        self._cache[cache_key] = {"payload": payload, "fetched_at_ms": now_ms, "empty": empty}
        return payload

    async def get_ths_pools(self, date: str | None = None,
                            keys: tuple[str, ...] | None = None) -> dict[str, Any]:
        """获取细分池；keys=None 全量（面板透传），子集=采集链按需（failed/rushing/drawdown）。

        缓存键带子集（面板全量与采集子集互不污染）；每池独立请求经 _throttle 错峰。
        """
        date_str = _normalize_date(date)
        wanted = tuple(keys) if keys else self.POOL_KEYS_ALL
        cache_key = f"ths-pools:{date_str}:{','.join(wanted)}"
        cached = self._cache.get(cache_key)
        now_ms = self._now_ms()
        if cached and now_ms - cached["fetched_at_ms"] < self._ttl_ms:
            return cached["payload"]
        client = self._client or get_limitup_client()
        pools_to_load = [p for p in THS_LIMIT_UP_POOLS if p["key"] in wanted]

        async def load(pool: dict[str, str]) -> tuple[str, dict[str, Any]]:
            try:
                await self._throttle()
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

        entries = await asyncio.gather(*(load(pool) for pool in pools_to_load))
        pools = dict(entries)
        # 2026-10-22 review 修：entries 元素是 (key, dict) 元组——此前对元组调 .get 会在
        # 「任一池失败」时抛 AttributeError（失败信息上报路径整体不可用，上游故障被伪装成
        # 崩溃）。改为解包 entry[1]
        errors = [
            {"pool": pool["key"], "errorCode": entry[1].get("errorCode"),
             "message": entry[1].get("message")}
            for pool, entry in zip(pools_to_load, entries)
            if not entry[1].get("ok")
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
