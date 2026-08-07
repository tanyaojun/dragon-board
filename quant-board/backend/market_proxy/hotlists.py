from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from contextlib import suppress
from typing import Any, Callable

import httpx


logger = logging.getLogger(__name__)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/90.0.4430.85 Safari/537.36"
)

# 各平台空壳降级结构，与旧 proxy fallback 一致，前端 adapter 读到空列表。
FALLBACKS: dict[str, Any] = {
    "xueqiu": {"data": {"items": []}},
    "cls": {"errno": -1, "data": []},
    "eastmoney": {"data": []},
    "ths": {"data": {"stock_list": []}},
    "kpl": {"List": []},
    "tdx": [],
    "tgb": {"dto": []},
    "dzh": {"result": []},
}

GET_PLATFORMS = {"xueqiu", "cls", "ths", "kpl", "tgb", "dzh"}
POST_PLATFORMS = {"eastmoney", "tdx"}

_CLS_PARAMS = {"app": "cailianpress", "os": "android", "sv": "835"}


def generate_cls_sign() -> tuple[dict[str, str], str]:
    """与旧 proxy helpers/sign.js 一致：sha1(排序参数串) 后再 md5。"""
    text = "&".join(
        f"{key}={_CLS_PARAMS[key]}" for key in sorted(_CLS_PARAMS)
    )
    sha1_hex = hashlib.sha1(text.encode("utf-8")).hexdigest()
    sign = hashlib.md5(sha1_hex.encode("utf-8")).hexdigest()
    return dict(_CLS_PARAMS), sign


async def _fetch_platform(
    client: httpx.AsyncClient,
    platform: str,
    xueqiu_cookie: str,
) -> Any:
    headers = {"User-Agent": UA}
    if platform == "xueqiu":
        if not xueqiu_cookie:
            raise RuntimeError("XUEQIU_COOKIE is not configured")
        headers.update({"Referer": "https://xueqiu.com/", "Cookie": xueqiu_cookie})
        response = await client.get(
            "https://stock.xueqiu.com/v5/stock/hot_stock/list.json",
            params={"size": 100, "_type": 10, "type": 10},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    if platform == "cls":
        params, sign = generate_cls_sign()
        headers["Referer"] = "https://www.cls.cn/"
        response = await client.get(
            "https://api3.cls.cn/v1/hot_stock",
            params={**params, "sign": sign},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    if platform == "eastmoney":
        headers["Content-Type"] = "application/json"
        response = await client.post(
            "https://emappdata.eastmoney.com/stockrank/getAllCurrentList",
            json={
                "appId": "appId01",
                "globalId": "786e4c21-70dc-435a-93bb-38",
                "pageNo": 1,
                "pageSize": 100,
            },
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    if platform == "ths":
        response = await client.get(
            "https://eq.10jqka.com.cn/open/api/hot_list/v1/hot_stock/a/hour/data.txt",
            headers=headers,
        )
        response.raise_for_status()
        return json.loads(response.text)
    if platform == "kpl":
        response = await client.get(
            "https://apphq.longhuvip.com/w1/api/index.php",
            params={
                "Order": "1",
                "a": "GetHotPHB",
                "st": "60",
                "apiv": "w21",
                "Type": "1",
                "c": "StockBidYiDong",
                "PhoneOSNew": "1",
                "VerSion": "5",
                "_": "1734567890000",
            },
            headers={"User-Agent": "curl/7.88.1", "Accept": "*/*"},
        )
        response.raise_for_status()
        return response.json()
    if platform == "tdx":
        response = await client.post(
            "https://pul.tdx.com.cn/TQLEX?Entry=JNLPSE.hotStockList&RI=",
            json=[{"listType": "0", "cycle": "0"}],
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    if platform == "tgb":
        response = await client.get(
            "https://www.tgb.cn/new/nrnt/getNoticeStock",
            params={"type": "H"},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    if platform == "dzh":
        response = await client.get(
            "https://imsearch.dzh.com.cn/stock/top",
            params={"size": 100, "type": 0, "time": "h"},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()
    raise ValueError(f"unsupported hotlist platform: {platform}")


class HotlistService:
    """八平台热榜：httpx 直连原上游，进程内 TTL 缓存 + last-good 降级。"""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        redis_client: Any | None = None,
        redis_key_prefix: str = "",
        xueqiu_cookie: str = "",
        ttl_seconds: float = 60.0,
        negative_ttl_seconds: float = 15.0,
        retries: int = 1,
        retry_delay_seconds: float = 0.5,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._redis_client = redis_client
        self._redis_prefix = str(redis_key_prefix or "").strip(":")
        self._cookie = xueqiu_cookie
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._negative_ttl_ms = max(1.0, float(negative_ttl_seconds)) * 1000
        self._retries = max(0, int(retries))
        self._retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._task: asyncio.Task[None] | None = None
        self._refresh_interval_seconds = 600.0
        self._last_refresh_at_ms: int | None = None
        self._last_refresh_summary: dict[str, Any] | None = None

    def _lock(self, platform: str) -> asyncio.Lock:
        if platform not in self._locks:
            self._locks[platform] = asyncio.Lock()
        return self._locks[platform]

    def _redis_key(self, platform: str) -> str:
        suffix = f"market:hotlist:{platform}:v1"
        return f"{self._redis_prefix}:{suffix}" if self._redis_prefix else suffix

    def _redis_get(self, platform: str) -> dict[str, Any] | None:
        client = self._redis_client
        if client is None:
            return None
        try:
            raw = client.get(self._redis_key(platform))
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            entry = json.loads(str(raw))
            if not isinstance(entry, dict) or "payload" not in entry:
                return None
            return entry
        except Exception:
            return None

    def _redis_set(self, platform: str, entry: dict[str, Any], *, ttl_seconds: float) -> None:
        client = self._redis_client
        if client is None:
            return
        try:
            client.setex(
                self._redis_key(platform),
                max(1, int(ttl_seconds)),
                json.dumps(entry, ensure_ascii=False),
            )
        except Exception:
            return

    async def _fetch_with_retry(self, platform: str) -> Any:
        """拉取单个平台，失败按配置重试；重试耗尽后抛出最后一次异常。"""
        client = self._client or get_hotlist_client()
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                return await _fetch_platform(client, platform, self._cookie)
            except Exception as exc:
                last_exc = exc
                if attempt < self._retries:
                    await asyncio.sleep(self._retry_delay_seconds)
        raise RuntimeError(
            f"hotlist {platform} failed after {self._retries + 1} attempts: {last_exc}"
        ) from last_exc

    async def get(self, platform: str) -> Any:
        if platform not in GET_PLATFORMS and platform not in POST_PLATFORMS:
            raise ValueError(f"unsupported hotlist platform: {platform}")
        async with self._lock(platform):
            cached = self._cache.get(platform)
            now_ms = self._now_ms()
            if cached:
                # 失败降级结果使用更短的负缓存 TTL，避免每次刷新都重打上游
                ttl_ms = self._negative_ttl_ms if cached.get("degraded") else self._ttl_ms
                if now_ms - cached["fetched_at_ms"] < ttl_ms:
                    return cached["payload"]
            # 共享 Redis 缓存：命中即返回并回填进程内缓存（跨进程/跨刷新共享）
            redis_entry = self._redis_get(platform)
            if redis_entry is not None:
                self._cache[platform] = redis_entry
                return redis_entry["payload"]
            try:
                payload = await self._fetch_with_retry(platform)
            except Exception as exc:
                if cached is not None:
                    logger.warning("hotlist %s failed, serving stale: %s", platform, exc)
                    return cached["payload"]
                logger.warning(
                    "hotlist %s failed after %d attempts: %s",
                    platform,
                    self._retries + 1,
                    exc,
                )
                degraded = {
                    "ok": False,
                    "degraded": True,
                    "source": platform,
                    "errorCode": "upstream_unavailable",
                    "message": str(exc)[:200],
                    "data": FALLBACKS.get(platform, {}),
                }
                # 负缓存：失败结果也短 TTL 缓存，保证“失败原因”可观察且不连续打上游
                # TTL 从抓取完成时刻起算，避免慢上游拉取期间把缓存“跑过期”
                degraded_entry = {
                    "payload": degraded,
                    "fetched_at_ms": self._now_ms(),
                    "degraded": True,
                }
                self._cache[platform] = degraded_entry
                self._redis_set(
                    platform,
                    degraded_entry,
                    ttl_seconds=self._negative_ttl_ms / 1000.0,
                )
                return degraded
            # TTL 从抓取完成时刻起算
            entry = {
                "payload": payload,
                "fetched_at_ms": self._now_ms(),
                "degraded": False,
            }
            self._cache[platform] = entry
            self._redis_set(platform, entry, ttl_seconds=self._ttl_ms / 1000.0)
            return payload

    async def refresh_all(self) -> dict[str, Any]:
        """后台预取八平台排名：复用 get() 的进程内/Redis 缓存与降级逻辑。

        单平台失败不中断整体（get() 失败返回降级结果并写负缓存），保证部分来源
        异常时其他平台照常写入缓存（fail-visible）。
        """
        platforms = sorted(GET_PLATFORMS | POST_PLATFORMS)
        ok_count = 0
        degraded_count = 0
        per_platform: dict[str, dict[str, bool]] = {}

        async def fetch_one(platform: str) -> None:
            nonlocal ok_count, degraded_count
            try:
                payload = await self.get(platform)
            except Exception:
                payload = None
            # 合法载荷：顶层数组（如 tdx）或非降级 dict；降级信封 ok:false/degraded:true
            ok = isinstance(payload, list) or (
                isinstance(payload, dict) and payload.get("ok") is not False
            )
            degraded = isinstance(payload, dict) and payload.get("degraded") is True
            success = ok and not degraded
            per_platform[platform] = {"ok": success, "degraded": degraded}
            if success:
                ok_count += 1
            elif degraded or payload is None:
                degraded_count += 1

        await asyncio.gather(*(fetch_one(platform) for platform in platforms))
        self._last_refresh_at_ms = self._now_ms()
        self._last_refresh_summary = {
            "total": len(platforms),
            "ok": ok_count,
            "degraded": degraded_count,
            "platforms": per_platform,
        }
        return dict(self._last_refresh_summary)

    def start(self, interval_seconds: float = 600.0) -> None:
        """启动后台预取任务：启动即预取一轮，之后按 interval 周期刷新。"""
        self._refresh_interval_seconds = max(60.0, float(interval_seconds))
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="market-hotlist-refresh")

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self.refresh_all()
                backoff = 1.0
                await asyncio.sleep(self._refresh_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market hotlist refresh cycle failed; backing off %.0fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300.0)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "running": self._task is not None and not self._task.done(),
            "source": "market-proxy-hotlists",
            "platformCount": len(GET_PLATFORMS | POST_PLATFORMS),
            "refreshIntervalSeconds": self._refresh_interval_seconds,
            "lastRefreshAtMs": self._last_refresh_at_ms,
            "lastRefresh": self._last_refresh_summary,
        }


_hotlist_client: httpx.AsyncClient | None = None
_hotlist_service: HotlistService | None = None


def get_hotlist_client() -> httpx.AsyncClient:
    global _hotlist_client
    if _hotlist_client is None:
        _hotlist_client = httpx.AsyncClient(timeout=12.0)
    return _hotlist_client


def get_hotlist_service() -> HotlistService:
    global _hotlist_service
    if _hotlist_service is None:
        from backend.core.settings import get_settings
        from backend.market_proxy.redis_client import get_hotlist_redis_client

        settings = get_settings()
        _hotlist_service = HotlistService(
            xueqiu_cookie=settings.xueqiu_cookie,
            redis_client=get_hotlist_redis_client(settings),
            redis_key_prefix=settings.redis_key_prefix,
        )
    return _hotlist_service


async def start_hotlist_refresh() -> None:
    """后端启动时预取八平台排名并周期性写入 Redis（首屏零等待）。"""
    from backend.core.settings import get_settings

    get_hotlist_service().start(get_settings().hotlist_refresh_interval_seconds)


async def stop_hotlist_refresh() -> None:
    await get_hotlist_service().stop()


async def close_hotlist_client() -> None:
    global _hotlist_client
    client = _hotlist_client
    _hotlist_client = None
    if client is not None:
        await client.aclose()
