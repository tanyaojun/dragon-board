from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, Callable

logger = logging.getLogger(__name__)


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
    """指数大盘概览：**本地行情桥（TDX）为主源**，akshare 仅作显式回退 + 进程内短缓存。

    源选择（2026-10-19 复盘，用户指令「akshare 被风控限流，先把指数改成行情桥」）：

    - ``bridge``（默认）：``GET 127.0.0.1:8765/api/quotes/index-snapshot``（TDX 主站直连，
      不经第三方 HTTP，不受限流影响）；
    - ``akshare``：仅显式指定时使用（`QUANT_BOARD_INDEX_SOURCE=akshare`），
      受新浪风控限流，盘中会挂死；
    - ``bridge_then_akshare``：桥失败时再试 akshare（迁移期选项）。

    显式注入 ``bridge_fetcher`` / ``akshare_module`` 时以注入为准（测试与自定义接线）。

    上游失败时保留上次成功结果并标记 stale（fail-visible）；从未成功过则抛错由路由降级。

    上游超时封顶（2026-10-19 复盘）：``akshare.stock_zh_index_spot_sina`` 是同步
    requests 抓取、**自身没有超时**，新浪限流时会挂住 130~299s。现在任何源都套
    ``fetch_timeout_s`` 上限：超时→退避 ``timeout_backoff_s`` 内不再重打，且优先返回
    last-good 并标 ``stale=True``（暴露不隐藏）；无 last-good 才抛 ``TimeoutError`` 由调用方降级。
    """

    def __init__(
        self,
        *,
        akshare_module: Any | None = None,
        redis_client: Any | None = None,
        redis_key_prefix: str = "",
        ttl_seconds: float = 10.0,
        now_ms: Callable[[], int] | None = None,
        fetch_timeout_s: float = 8.0,
        timeout_backoff_s: float = 60.0,
        last_good_ttl_s: float = 300.0,
        source: str | None = None,
        bridge_base_url: str | None = None,
        bridge_fetcher: Callable[..., Any] | None = None,
    ) -> None:
        self._ak = akshare_module
        self._redis = redis_client
        self._redis_prefix = str(redis_key_prefix or "").strip(":")
        self._ttl_ms = max(1.0, float(ttl_seconds)) * 1000
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._snapshot: dict[str, Any] | None = None
        self._cached_at_ms = 0
        self._fetch_timeout_s = max(0.05, float(fetch_timeout_s))
        self._timeout_backoff_ms = max(0.0, float(timeout_backoff_s)) * 1000
        # last-good 兜底库（2026-10-19 复盘，用户指出短 TTL 后重审）：
        # 新鲜缓存 TTL（10s）不能撑过重启/上游故障，否则指数就会"裸取"（修复前
        # 那条路上游可卡 130~299s）。这里另存一份更长寿的 last-good，**只在**
        # 取数失败/超时时用，且一定带 stale 标记——happy path 永远不降级用旧值，
        # 因此 8000 的 /api/market/overview 与采集链都不会拿旧数据当新鲜。
        self._last_good_ttl_s = max(1.0, float(last_good_ttl_s))
        self._next_attempt_ms = 0
        self._bridge_fetcher = bridge_fetcher
        self._bridge_base_url = str(bridge_base_url or "").strip()
        self._source = self._resolve_source(source, akshare_module, bridge_fetcher)
        # 专用单线程执行器（2026-10-19 复盘）：akshare 同步抓取挂住后无法取消，
        # 用单 worker 兼作天然断路器——卡死期间新提交的抓取会排队并被 wait_for 取消，
        # 既不会堆积挂死线程，也不会拖垮共享默认执行器（Mongo 写入/其他 provider 都走它）。
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="market-overview-akshare"
        )

    @staticmethod
    def _resolve_source(
        source: str | None,
        akshare_module: Any | None,
        bridge_fetcher: Callable[..., Any] | None,
    ) -> str:
        """解析实际取数源：显式 source > 显式注入的源 > 全局设置（默认 bridge）。

        显式 ``source`` 优先：迁移期选项 ``bridge_then_akshare`` 需要同时注入桥与
        akshare 回退源，不能被"注入了哪个就锁定哪个"的启发式覆盖。
        """
        candidate = str(source or "").strip().lower()
        if candidate in {"bridge", "akshare", "bridge_then_akshare"}:
            return candidate
        if bridge_fetcher is not None:
            return "bridge"
        if akshare_module is not None:
            return "akshare"
        try:
            from backend.core.settings import get_settings

            configured = str(getattr(get_settings(), "index_source", "") or "").strip().lower()
            if configured in {"bridge", "akshare", "bridge_then_akshare"}:
                return configured
        except Exception:
            pass
        return "bridge"

    def _bridge_url(self) -> str:
        if self._bridge_base_url:
            return self._bridge_base_url
        try:
            from backend.core.settings import get_settings

            return str(
                getattr(get_settings(), "snapshot_collector_bridge_base_url", "")
                or "http://127.0.0.1:8765"
            )
        except Exception:
            return "http://127.0.0.1:8765"

    async def _fetch_bridge_items(self, timeout_s: float) -> list[dict[str, Any]]:
        from backend.market_proxy.index_bridge_source import fetch_index_items

        fetcher = self._bridge_fetcher
        if fetcher is not None:
            result = fetcher(timeout_s=timeout_s)
            if asyncio.iscoroutine(result):
                result = await result
            return list(result or [])
        return await fetch_index_items(base_url=self._bridge_url(), timeout_s=timeout_s)

    async def _fetch_akshare_items(self, timeout_s: float) -> list[dict[str, Any]]:
        loop = asyncio.get_running_loop()
        frame = await asyncio.wait_for(
            loop.run_in_executor(self._executor, self._fetch_sync), timeout=timeout_s
        )
        return self._normalize(frame)

    async def _fetch_items(self, timeout_s: float) -> tuple[list[dict[str, Any]], str]:
        """取指数 items；返回 (items, source_label)。空结果一律抛错，不冒充成功。"""
        source = self._source
        if source == "bridge":
            items = await self._fetch_bridge_items(timeout_s)
            if not items:
                raise RuntimeError("bridge index snapshot returned empty items")
            return items, "tdx-bridge-index"
        if source == "bridge_then_akshare":
            try:
                items = await self._fetch_bridge_items(timeout_s)
                if items:
                    return items, "tdx-bridge-index"
                bridge_error: Exception = RuntimeError("bridge index snapshot returned empty items")
            except Exception as exc:  # noqa: BLE001 —— 回退源就是为任何桥失败兜底
                bridge_error = exc
            logger.warning("index bridge source failed (%s); falling back to akshare", str(bridge_error)[:120])
            items = await self._fetch_akshare_items(timeout_s)
            if not items:
                raise RuntimeError("akshare index snapshot returned empty items")
            return items, "akshare-sina-index"
        items = await self._fetch_akshare_items(timeout_s)
        if not items:
            raise RuntimeError("akshare index snapshot returned empty items")
        return items, "akshare-sina-index"

    async def get_overview(self, timeout_s: float | None = None) -> dict[str, Any]:
        now_ms = self._now_ms()
        if self._snapshot is not None and now_ms - self._cached_at_ms < self._ttl_ms:
            return self._snapshot
        # 共享 Redis TTL 缓存：跨进程/跨重启 last-good，冷启动直接命中
        redis_snapshot = self._redis_get()
        if redis_snapshot is not None:
            self._snapshot = redis_snapshot
            self._cached_at_ms = now_ms
            return redis_snapshot
        if self._next_attempt_ms and now_ms < self._next_attempt_ms:
            # 上游刚超时：退避窗口内不再阻塞重打（每次 8s 的等待会叠加进采集预算）
            stale = self.stale_snapshot() or self._redis_get_last_good()
            if stale is not None:
                return {**stale, "errorCode": "upstream_timeout_backoff"}
            raise TimeoutError(
                "market overview upstream in cooldown after timeout "
                f"({(self._next_attempt_ms - now_ms) / 1000:.0f}s left)"
            )
        wait_s = max(0.05, float(timeout_s) if timeout_s else self._fetch_timeout_s)
        started = time.monotonic()
        try:
            items, source_label = await asyncio.wait_for(
                self._fetch_items(wait_s), timeout=wait_s + 0.5
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            elapsed_s = time.monotonic() - started
            self._next_attempt_ms = now_ms + int(self._timeout_backoff_ms)
            logger.warning(
                "market overview fetch timed out after %.1fs (limit %.1fs, source %s); "
                "backing off %.0fs and serving last-good if available",
                elapsed_s,
                wait_s,
                self._source,
                self._timeout_backoff_ms / 1000,
            )
            stale = self.stale_snapshot() or self._redis_get_last_good()
            if stale is not None:
                return {**stale, "stale": True, "errorCode": "upstream_timeout"}
            # 注意：超时的线程无法取消，仍在后台跑完；这里只保证调用方不再被它阻塞
            raise TimeoutError(
                f"market overview upstream timeout after {elapsed_s:.1f}s (limit {wait_s:.1f}s)"
            ) from exc
        except Exception as exc:
            # 上游直接报错（如 akshare 解析异常 list index out of range）：类契约
            # （见类 docstring）承诺"上游失败时保留上次成功结果并标 stale"，
            # 原实现只在超时分支做了。这里补齐：有 last-good 就用（带 stale 标记），
            # 没有才把异常抛给调用方降级（fail-visible，不伪造新鲜）。
            self._next_attempt_ms = now_ms + int(self._timeout_backoff_ms)
            stale = self.stale_snapshot() or self._redis_get_last_good()
            if stale is not None:
                logger.warning(
                    "market overview upstream failed (%s); serving last-good stale data",
                    str(exc)[:120],
                )
                return {**stale, "stale": True, "errorCode": "upstream_error"}
            raise
        snapshot = {
            "ok": True,
            "source": source_label,
            "timestamp": now_ms,
            "stale": False,
            "items": items,
        }
        self._snapshot = snapshot
        self._cached_at_ms = now_ms
        self._redis_set(snapshot)
        self._redis_set_last_good(snapshot)
        return snapshot

    def stale_snapshot(self) -> dict[str, Any] | None:
        if self._snapshot is None:
            return None
        return {**self._snapshot, "stale": True}

    def _redis_key(self) -> str:
        suffix = "market:overview:v1"
        return f"{self._redis_prefix}:{suffix}" if self._redis_prefix else suffix

    def _last_good_key(self) -> str:
        suffix = "market:overview:last-good:v1"
        return f"{self._redis_prefix}:{suffix}" if self._redis_prefix else suffix

    def _redis_get_last_good(self) -> dict[str, Any] | None:
        """只在上游超时/失败时调用：返回带 stale 与 staleSeconds 的最近有效快照。"""
        client = self._redis
        if client is None:
            return None
        try:
            raw = client.get(self._last_good_key())
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            value = json.loads(str(raw))
            if not isinstance(value, dict) or value.get("items") is None:
                return None
            stamp = value.get("timestamp")
            age_s = max(0.0, (self._now_ms() - float(stamp)) / 1000.0) if stamp else None
            return {
                **value,
                "stale": True,
                "staleSeconds": round(age_s, 1) if age_s is not None else None,
            }
        except Exception:
            return None

    def _redis_set_last_good(self, snapshot: dict[str, Any]) -> None:
        client = self._redis
        if client is None:
            return
        try:
            client.setex(
                self._last_good_key(),
                max(1, int(self._last_good_ttl_s)),
                json.dumps(snapshot, ensure_ascii=False),
            )
        except Exception:
            return

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
        from backend.market_proxy.redis_client import get_hotlist_redis_client

        settings = get_settings()
        _overview_service = MarketOverviewService(
            redis_client=get_hotlist_redis_client(settings),
            redis_key_prefix=settings.redis_key_prefix,
            source=getattr(settings, "index_source", "bridge"),
            bridge_base_url=settings.snapshot_collector_bridge_base_url,
        )
    return _overview_service
