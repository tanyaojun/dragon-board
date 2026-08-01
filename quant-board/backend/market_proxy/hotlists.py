from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
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
        xueqiu_cookie: str = "",
        ttl_seconds: float = 60.0,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._cookie = xueqiu_cookie
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache: dict[str, dict[str, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, platform: str) -> asyncio.Lock:
        if platform not in self._locks:
            self._locks[platform] = asyncio.Lock()
        return self._locks[platform]

    async def get(self, platform: str) -> Any:
        if platform not in GET_PLATFORMS and platform not in POST_PLATFORMS:
            raise ValueError(f"unsupported hotlist platform: {platform}")
        async with self._lock(platform):
            cached = self._cache.get(platform)
            now_ms = self._now_ms()
            if cached and now_ms - cached["fetched_at_ms"] < self._ttl_ms:
                return cached["payload"]
            try:
                payload = await _fetch_platform(
                    self._client or get_hotlist_client(),
                    platform,
                    self._cookie,
                )
            except Exception as exc:
                if cached is not None:
                    logger.warning("hotlist %s failed, serving stale: %s", platform, exc)
                    return cached["payload"]
                logger.warning("hotlist %s failed: %s", platform, exc)
                return {
                    "ok": False,
                    "degraded": True,
                    "source": platform,
                    "errorCode": "upstream_unavailable",
                    "message": str(exc)[:200],
                    "data": FALLBACKS.get(platform, {}),
                }
            self._cache[platform] = {"payload": payload, "fetched_at_ms": now_ms}
            return payload


_hotlist_client: httpx.AsyncClient | None = None
_hotlist_service: HotlistService | None = None


def get_hotlist_client() -> httpx.AsyncClient:
    global _hotlist_client
    if _hotlist_client is None:
        _hotlist_client = httpx.AsyncClient(timeout=8.0)
    return _hotlist_client


def get_hotlist_service() -> HotlistService:
    global _hotlist_service
    if _hotlist_service is None:
        from backend.settings import get_settings

        _hotlist_service = HotlistService(
            xueqiu_cookie=get_settings().xueqiu_cookie
        )
    return _hotlist_service


async def close_hotlist_client() -> None:
    global _hotlist_client
    client = _hotlist_client
    _hotlist_client = None
    if client is not None:
        await client.aclose()
