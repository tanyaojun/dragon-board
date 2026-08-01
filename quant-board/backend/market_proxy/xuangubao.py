from __future__ import annotations

import time
from typing import Any, Callable

import httpx


XUANGUBAO_EVENT_HOSTS = [
    "https://flash-api.xuangubao.com.cn/api/event/history",
    "https://flash-api.xuangubao.cn/api/event/history",
]

DEFAULT_EVENT_TYPES = [
    10001,
    10005,
    10003,
    10007,
    10002,
    10006,
    10004,
    10008,
    10012,
    10014,
    10009,
    10010,
    11000,
    11001,
]
EVENT_TYPE_SET = set(DEFAULT_EVENT_TYPES)
DEFAULT_COUNT = 100
MAX_COUNT = 200


def _normalize_count(value: str | None) -> int:
    try:
        count = int(str(value or "").strip())
    except (TypeError, ValueError):
        return DEFAULT_COUNT
    if count <= 0:
        return DEFAULT_COUNT
    return min(count, MAX_COUNT)


def _normalize_types(value: str | None) -> list[int]:
    requested = []
    for raw in str(value or "").split(","):
        try:
            requested.append(int(raw.strip()))
        except (TypeError, ValueError):
            continue
    requested = list(dict.fromkeys(t for t in requested if t in EVENT_TYPE_SET))
    return requested or list(DEFAULT_EVENT_TYPES)


def _extract_events(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    # 与旧 proxy `payload?.data ?? payload` 一致：data 缺失或为 null 时回退到 payload 本身
    source = payload.get("data") if payload.get("data") is not None else payload
    if isinstance(source, list):
        return source
    if not isinstance(source, dict):
        return []
    nested: list[Any] = []
    for key in (
        "stock_abnormal_event_data",
        "plate_abnormal_event_data",
        "stockAbnormalEventData",
        "plateAbnormalEventData",
    ):
        value = source.get(key)
        if isinstance(value, list):
            nested.extend(value)
    if nested:
        return nested
    for key in ("items", "list", "events"):
        value = source.get(key)
        if isinstance(value, list):
            return value
    events = payload.get("events")
    return events if isinstance(events, list) else []


def _filter_supported_events(events: list[Any]) -> list[Any]:
    result = []
    for event in events:
        if not isinstance(event, dict):
            continue
        nested = event.get("stock_abnormal_event_data") or event.get(
            "plate_abnormal_event_data"
        ) or event.get("stockAbnormalEventData") or event.get("plateAbnormalEventData") or {}
        nested = nested if isinstance(nested, dict) else {}
        raw_type = (
            event.get("event_type")
            or event.get("eventType")
            or event.get("type")
            or nested.get("event_type")
            or nested.get("eventType")
            or nested.get("type")
        )
        try:
            event_type = int(raw_type)
        except (TypeError, ValueError):
            continue
        if event_type in EVENT_TYPE_SET:
            result.append(event)
    return result


class XuangubaoEventService:
    """选股宝异动事件：多 host 容错直连，进程内短缓存。"""

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
        self._cache: dict[str, Any] | None = None
        self._cached_at_ms = 0

    async def get_events(self, count: str | None = None, types: str | None = None) -> dict[str, Any]:
        now_ms = self._now_ms()
        cache_key = f"{_normalize_count(count)}:{','.join(map(str, _normalize_types(types)))}"
        if (
            self._cache is not None
            and self._cache.get("key") == cache_key
            and now_ms - self._cached_at_ms < self._ttl_ms
        ):
            return self._cache["payload"]
        client = self._client or _get_xuangubao_client()
        params = {
            "count": str(_normalize_count(count)),
            "types": ",".join(map(str, _normalize_types(types))),
        }
        last_error: Exception | None = None
        for host in XUANGUBAO_EVENT_HOSTS:
            try:
                response = await client.get(host, params=params, timeout=8.0)
                response.raise_for_status()
                body = response.json()
                payload = {
                    "ok": True,
                    "source": "xuangubao-events",
                    "data": _filter_supported_events(_extract_events(body)),
                    "upstreamCode": body.get("code", response.status_code),
                    "timestamp": now_ms,
                }
                self._cache = {"key": cache_key, "payload": payload}
                self._cached_at_ms = now_ms
                return payload
            except Exception as exc:
                last_error = exc
        raise RuntimeError(
            f"no xuangubao event source available: {last_error}" if last_error else "no source"
        )


_xuangubao_client: httpx.AsyncClient | None = None
_xuangubao_service: XuangubaoEventService | None = None


def _get_xuangubao_client() -> httpx.AsyncClient:
    global _xuangubao_client
    if _xuangubao_client is None:
        _xuangubao_client = httpx.AsyncClient(timeout=8.0)
    return _xuangubao_client


def get_xuangubao_service() -> XuangubaoEventService:
    global _xuangubao_service
    if _xuangubao_service is None:
        _xuangubao_service = XuangubaoEventService()
    return _xuangubao_service


async def close_xuangubao_client() -> None:
    global _xuangubao_client
    client = _xuangubao_client
    _xuangubao_client = None
    if client is not None:
        await client.aclose()
