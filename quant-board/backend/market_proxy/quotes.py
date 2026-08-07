from __future__ import annotations

import asyncio
import json
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


@contextmanager
def _bounded_requests(request_timeout_seconds: float) -> Iterator[None]:
    """akshare 内部 requests 调用不带 timeout，IPv6 黑洞链路会让线程永久挂起。

    在拉取期间：
    1. 给 requests.get/post 注入默认 timeout；
    2. 强制 getaddrinfo 优先返回 IPv4——qt.gtimg.cn 在本机 IPv6 链路可建立连接但
       数据被黑洞（IPv4 直连正常），IPv4 优先 + timeout 双保险（同 akshare_fund_provider）。
    避免 to_thread worker 被永不上限的 socket/DNS 调用占死（线程池耗尽风险）。
    """
    import requests as requests_module
    import socket as socket_module

    original_get = requests_module.get
    original_post = requests_module.post
    original_getaddrinfo = socket_module.getaddrinfo

    def _with_timeout(original: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(url: str, *args: Any, **kwargs: Any) -> Any:
            kwargs.setdefault("timeout", request_timeout_seconds)
            return original(url, *args, **kwargs)

        return wrapped

    def _ipv4_first_getaddrinfo(*args: Any, **kwargs: Any) -> list[Any]:
        results = original_getaddrinfo(*args, **kwargs)
        ipv4 = [item for item in results if item[0] == socket_module.AF_INET]
        return ipv4 or results

    requests_module.get = _with_timeout(original_get)
    requests_module.post = _with_timeout(original_post)
    socket_module.getaddrinfo = _ipv4_first_getaddrinfo
    try:
        yield
    finally:
        requests_module.get = original_get
        requests_module.post = original_post
        socket_module.getaddrinfo = original_getaddrinfo


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
        redis_client: Any | None = None,
        redis_key_prefix: str = "",
        ttl_seconds: float = 300.0,
        now_ms: Callable[[], int] | None = None,
        fetch_timeout_seconds: float = 120.0,
    ) -> None:
        # 与 settings 的下限保持一致（QUANT_BOARD_MARKET_QUOTES_REFRESH_INTERVAL_SECONDS 最小 60s）
        self.refresh_interval_seconds = max(60.0, float(refresh_interval_seconds))
        self._ak = akshare_module
        self._tqdm_module = tqdm_module
        self._redis = redis_client
        self._redis_prefix = str(redis_key_prefix or "").strip(":")
        self._ttl_seconds = max(60, int(ttl_seconds))
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._fetch_timeout_seconds = max(30.0, float(fetch_timeout_seconds))
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
                frame = await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_sync),
                    timeout=self._fetch_timeout_seconds,
                )
            except asyncio.TimeoutError:
                # 上游挂起不能拖死刷新任务：超时熔断，保留 last-good，下个周期自动重试
                self._last_error = "fetch_timeout"
                logger.warning(
                    "market quotes refresh timed out after %.0fs, keeping last-good rows",
                    self._fetch_timeout_seconds,
                )
                return False
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
            self._redis_set_all(rows)
            return True

    def get_diff(self, codes: list[str]) -> dict[str, Any]:
        normalized = [normalize_stock_code(raw) for raw in codes]
        unique = list(dict.fromkeys(code for code in normalized if code))
        if not unique:
            return {"rc": 0, "data": {"diff": []}}

        # 进程内未就绪（冷启动/重启）：从共享 Redis TTL 缓存兜底，保证首屏秒开
        if not self._rows:
            redis_rows = self._redis_get_many(unique)
            if redis_rows:
                return {
                    "rc": 0,
                    "data": {"diff": [redis_rows[code] for code in unique if code in redis_rows]},
                }
            return {"rc": 0, "data": {"diff": []}}

        ordered: list[dict[str, Any]] = []
        for code in unique:
            row = self._rows.get(code)
            if row:
                ordered.append(row)
        return {"rc": 0, "data": {"diff": ordered}}

    def _redis_key(self) -> str:
        suffix = "market:quotes:tencent:v1"
        return f"{self._redis_prefix}:{suffix}" if self._redis_prefix else suffix

    def _redis_set_all(self, rows: dict[str, dict[str, Any]]) -> None:
        client = self._redis
        if client is None or not rows:
            return
        try:
            pipe = client.pipeline(transaction=False)
            key = self._redis_key()
            for code, row in rows.items():
                pipe.hset(key, code, json.dumps(row, ensure_ascii=False))
            pipe.expire(key, self._ttl_seconds)
            pipe.execute()
        except Exception:
            return

    def _redis_get_many(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        client = self._redis
        normalized = list(dict.fromkeys(code for code in codes if code))
        if client is None or not normalized:
            return {}
        try:
            raw_values = client.hmget(self._redis_key(), normalized)
        except Exception:
            return {}
        result: dict[str, dict[str, Any]] = {}
        for code, raw in zip(normalized, raw_values):
            try:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                value = json.loads(raw) if raw else None
            except (TypeError, ValueError, UnicodeDecodeError):
                continue
            if isinstance(value, dict):
                result[code] = value
        return result
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
        with _silence_tqdm(module), _bounded_requests(self._fetch_timeout_seconds):
            return ak.stock_zh_a_spot_tx()

    async def _run(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self.refresh()
                backoff = 1.0
                await asyncio.sleep(self.refresh_interval_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market quotes refresh cycle failed; backing off %.0fs", backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300.0)


_quotes_cache: MarketQuotesCache | None = None


def get_market_quotes_cache() -> MarketQuotesCache:
    global _quotes_cache
    if _quotes_cache is None:
        from backend.core.settings import get_settings
        from backend.market_proxy.cache import get_hotlist_redis_client

        settings = get_settings()
        _quotes_cache = MarketQuotesCache(
            refresh_interval_seconds=settings.market_quotes_refresh_interval_seconds,
            redis_client=get_hotlist_redis_client(settings),
            redis_key_prefix=settings.redis_key_prefix,
            ttl_seconds=settings.market_quotes_refresh_interval_seconds,
        )
    return _quotes_cache


async def start_market_quotes_refresh() -> None:
    get_market_quotes_cache().start()


async def stop_market_quotes_refresh() -> None:
    await get_market_quotes_cache().stop()
