"""Transitional data-source providers for the backend snapshot collector.

Each provider fetches raw material from one external source and returns
a ``(data, SourceHealth)`` tuple.  Providers never write MongoDB snapshot
collections and never generate ``snapshot_id`` values.

- ``StartupBundleStockProvider`` ── live-equivalent stock pool from proxy cache
- ``ProxyMergedHotlistProvider`` ── merged multi-platform hotlist fallback
- ``ProxyHotlistProvider`` ── single-platform hotlist diagnostic provider
- ``BridgeQuoteProvider``   ── real-time quotes from the python-bridge
- ``ThemeMappingProvider``  ── code➜theme mapping from MongoDB theme tables
- ``ProxyLimitUpProvider``  ── THS limit-up pool enrichment from proxy-server
- ``collect_market_context``── assembles all providers into a MarketDataContext
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

import httpx

from backend.core.fund_sources import (
    FUND_SOURCE_THS_MAIN_MONITOR,
    SUPPORTED_FUND_SOURCES,
)
if TYPE_CHECKING:
    from backend.services.theme.fund_cache import ThemeFundCache

from .gateway import HttpMarketDataGateway
from .models import MarketDataContext, SourceHealth

# ── constants ───────────────────────────────────────────────────────────────

_DEFAULT_PROXY_BASE_URL = "http://127.0.0.1:3000"
_DEFAULT_BRIDGE_BASE_URL = "http://127.0.0.1:8765"
_DEFAULT_TIMEOUT_MS = 5000
_DEFAULT_RANK = 999

# 默认数据网关：CLI/手动链路走 HTTP（proxy 转发）；collector_main 独立采集进程
# 通过 set_default_gateway() 切换为进程内直连，避免 8000 自环依赖。
_DEFAULT_GATEWAY: Any | None = None

_HOTLIST_PLATFORMS = ("eastmoney", "ths", "kpl", "tdx", "xueqiu", "cls", "tgb", "dzh")
_HOTLIST_RANK_FIELDS = {
    "eastmoney": "emRank",
    "ths": "thsRank",
    "kpl": "kplRank",
    "tdx": "tdxRank",
    "xueqiu": "xqRank",
    "cls": "clsRank",
    "tgb": "tgbRank",
    "dzh": "dzhRank",
}


def _rank_provenance(platform_totals: dict[str, int]) -> dict[str, Any]:
    return {
        "formulaVersion": "weighted_platform_percentile_v1",
        "platformTotals": {
            platform: int(platform_totals.get(platform, 0))
            for platform in _HOTLIST_PLATFORMS
        },
        "platformWeights": dict(_HOTLIST_WEIGHTS),
        "rankFields": dict(_HOTLIST_RANK_FIELDS),
        "defaultRank": _DEFAULT_RANK,
    }
_HOTLIST_WEIGHTS = {
    "kpl": 1.0,
    "tdx": 0.9,
    "ths": 0.85,
    "eastmoney": 0.75,
    "dzh": 0.7,
    "tgb": 0.4,
    "xueqiu": 0.35,
    "cls": 0.35,
}

_LIMIT_UP_POOL_KEYS = ("one", "two", "three", "four", "high", "failed", "rushing", "drawdown")
_TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# 共享同步 HTTP 客户端与线程池：providers 由 asyncio.to_thread(service.run_once) 串行调用，
# 但批内请求可并行；复用同一客户端/线程池避免每次 collect 新建线程池（线程抖动）。
_PROXY_HTTP_TIMEOUT_SECONDS = 30.0
_COLLECTOR_THREAD_POOL: ThreadPoolExecutor | None = None
_PROXY_HTTP_CLIENT: httpx.Client | None = None


def set_default_gateway(gateway: Any) -> None:
    """Install the default market data gateway for the collector process."""
    global _DEFAULT_GATEWAY
    _DEFAULT_GATEWAY = gateway


def _get_default_gateway() -> Any:
    global _DEFAULT_GATEWAY
    if _DEFAULT_GATEWAY is None:
        _DEFAULT_GATEWAY = HttpMarketDataGateway()
    return _DEFAULT_GATEWAY


def _is_in_process_gateway(gateway: Any) -> bool:
    from .gateway import InProcessMarketDataGateway

    return isinstance(gateway, InProcessMarketDataGateway)


def _get_collector_thread_pool() -> ThreadPoolExecutor:
    global _COLLECTOR_THREAD_POOL
    if _COLLECTOR_THREAD_POOL is None:
        _COLLECTOR_THREAD_POOL = ThreadPoolExecutor(
            max_workers=8,
            thread_name_prefix="snapshot-collector",
        )
    return _COLLECTOR_THREAD_POOL


def _get_proxy_http_client() -> httpx.Client:
    global _PROXY_HTTP_CLIENT
    if _PROXY_HTTP_CLIENT is None:
        # trust_env=False：本机系统代理（如 iKuuuVPN 127.0.0.1:7890）会把 localhost
        # 内网请求也劫持并返回 502。采集器只访问本地基础设施（proxy/bridge），
        # 不应走系统代理；外部上游由 market_proxy 服务自行处理。
        _PROXY_HTTP_CLIENT = httpx.Client(
            timeout=_PROXY_HTTP_TIMEOUT_SECONDS,
            trust_env=False,
        )
    return _PROXY_HTTP_CLIENT


def close_collector_http() -> None:
    """关闭共享客户端与线程池（FastAPI shutdown / CLI 退出时调用）。"""
    global _PROXY_HTTP_CLIENT, _COLLECTOR_THREAD_POOL
    client = _PROXY_HTTP_CLIENT
    _PROXY_HTTP_CLIENT = None
    if client is not None:
        client.close()
    pool = _COLLECTOR_THREAD_POOL
    _COLLECTOR_THREAD_POOL = None
    if pool is not None:
        pool.shutdown(wait=False, cancel_futures=True)


# ── helpers ─────────────────────────────────────────────────────────────────


def _iso_now() -> str:
    """ISO-8601 UTC timestamp string for health records."""
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce *value* to float, returning *default* on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce *value* to int via float, returning *default* on failure."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _calculate_average_rank_fields(
    row: dict[str, Any],
    platform_totals: dict[str, int],
) -> None:
    weighted_sum = 0.0
    total_weight = 0.0
    platforms = 0
    for platform in _HOTLIST_PLATFORMS:
        total = platform_totals.get(platform, 0)
        if total <= 0:
            continue
        field = _HOTLIST_RANK_FIELDS[platform]
        weight = _HOTLIST_WEIGHTS[platform]
        total_weight += weight
        rank = _safe_int(row.get(field), _DEFAULT_RANK)
        if rank < _DEFAULT_RANK:
            platforms += 1
            weighted_sum += (rank / total) * 100 * weight
        else:
            weighted_sum += 100 * weight
    row["platforms"] = platforms
    row["avgRankNum"] = weighted_sum / total_weight if total_weight else float(_DEFAULT_RANK)
    row["avgRank"] = f"{row['avgRankNum']:.1f}"


def _normalize_stock_code(value: Any) -> str:
    code = "".join(ch for ch in str(value or "").strip() if ch.isdigit())
    if len(code) >= 6:
        code = code[-6:]
    return code if len(code) == 6 else ""


def _http_get_json(url: str, timeout_s: float) -> Any:
    """Perform a GET request and return the parsed JSON body.

    Raises ``httpx.HTTPError`` / ``ValueError`` on failure.
    """
    response = _get_proxy_http_client().get(url, timeout=timeout_s)
    response.raise_for_status()
    return response.json()


def _http_post_json(url: str, timeout_s: float, payload: Any = None) -> Any:
    """Perform a POST request and return the parsed JSON body.

    When *payload* is provided it is sent as a JSON-encoded body.
    Raises ``httpx.HTTPError`` / ``ValueError`` on failure.
    """
    headers = {"Content-Type": "application/json"} if payload is not None else None
    response = _get_proxy_http_client().post(
        url,
        content=json.dumps(payload) if payload is not None else None,
        headers=headers,
        timeout=timeout_s,
    )
    response.raise_for_status()
    return response.json()


class _BatchedProxyProvider:
    source = ""
    endpoint = ""
    stop_on_systemic_failure = False

    def __init__(
        self,
        base_url: str = _DEFAULT_PROXY_BASE_URL,
        *,
        batch_size: int = 50,
        max_concurrency: int = 3,
        failed_batch_retries: int = 1,
        collection_timeout_ms: int = 120000,
        gateway: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._batch_size = max(1, batch_size)
        self._max_concurrency = max(1, max_concurrency)
        self._failed_batch_retries = max(0, failed_batch_retries)
        self._collection_timeout_ms = max(1, collection_timeout_ms)
        self._gateway = gateway or _get_default_gateway()

    def collect(
        self,
        codes: list[str],
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[dict[str, dict[str, Any]], SourceHealth]:
        started_at = _iso_now()
        started = time.monotonic()
        requested_codes = list(dict.fromkeys(str(code).strip() for code in codes if str(code).strip()))
        if not requested_codes:
            completed_at = _iso_now()
            return {}, SourceHealth(
                source=self.source,
                ok=False,
                latency_ms=int((time.monotonic() - started) * 1000),
                row_count=0,
                error="no requested codes",
                captured_at=completed_at,
                requested_count=0,
                returned_count=0,
                coverage_ratio=0.0,
                started_at=started_at,
                completed_at=completed_at,
            )
        batches = [
            requested_codes[index : index + self._batch_size]
            for index in range(0, len(requested_codes), self._batch_size)
        ]
        rows: dict[str, dict[str, Any]] = {}
        failed_batches: list[int] = []
        errors: list[str] = []

        if batches:
            # 复用共享线程池：避免每次 collect 新建/销毁线程池
            pool = _get_collector_thread_pool()
            for wave_start in range(0, len(batches), self._max_concurrency):
                wave = list(enumerate(
                    batches[wave_start : wave_start + self._max_concurrency],
                    start=wave_start,
                ))
                futures = {
                    pool.submit(self._collect_batch, index, batch, timeout_ms): index
                    for index, batch in wave
                }
                wave_failures = 0
                for future in as_completed(futures):
                    index = futures[future]
                    try:
                        batch_rows = future.result()
                        rows.update(batch_rows)
                    except Exception as exc:
                        wave_failures += 1
                        failed_batches.append(index)
                        errors.append(str(exc))
                if self.stop_on_systemic_failure and not rows and wave_failures == len(wave):
                    remaining_start = wave_start + len(wave)
                    failed_batches.extend(range(remaining_start, len(batches)))
                    errors.append("upstream unavailable; remaining batches skipped")
                    break
                remaining_start = wave_start + len(wave)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                if remaining_start < len(batches) and elapsed_ms >= self._collection_timeout_ms:
                    failed_batches.extend(range(remaining_start, len(batches)))
                    errors.append("collection timeout; remaining batches skipped")
                    break

        returned_count = sum(code in rows for code in requested_codes)
        requested_count = len(requested_codes)
        completed_at = _iso_now()
        health = SourceHealth(
            source=self.source,
            ok=not failed_batches,
            latency_ms=int((time.monotonic() - started) * 1000),
            row_count=returned_count,
            error="; ".join(errors),
            captured_at=completed_at,
            requested_count=requested_count,
            returned_count=returned_count,
            coverage_ratio=round(returned_count / requested_count, 4) if requested_count else 1.0,
            started_at=started_at,
            completed_at=completed_at,
            failed_batches=sorted(failed_batches),
        )
        return rows, health

    def _collect_batch(
        self,
        index: int,
        codes: list[str],
        timeout_ms: int,
    ) -> dict[str, dict[str, Any]]:
        del index
        last_error: Exception | None = None
        for _attempt in range(self._failed_batch_retries + 1):
            try:
                url = (
                    f"{self._base_url}{self.endpoint}"
                    f"?codes={quote(','.join(codes), safe=',')}"
                )
                body = self._gateway.get_json(url, timeout_ms / 1000.0)
                degraded_error = _proxy_degraded_error(body)
                if degraded_error:
                    raise RuntimeError(degraded_error)
                return {
                    row["code"]: row
                    for item in _extract_proxy_quote_rows(body)
                    if (row := self._normalize_row(item)) is not None
                }
            except Exception as exc:
                last_error = exc
        raise RuntimeError(str(last_error or "batch request failed"))

    def _normalize_row(self, item: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError


class TencentBasicQuoteProvider(_BatchedProxyProvider):
    """Fetch full-market basic quotes from Tencent through proxy-server."""

    source = "theme_quote_tencent"
    endpoint = "/api/quotes/tencent"

    def _normalize_row(self, item: dict[str, Any]) -> dict[str, Any] | None:
        code = str(item.get("f12") or "").strip()
        if not code:
            return None
        row = {
            "code": code,
            "name": str(item.get("f14") or code),
            "price": _safe_float(item.get("f2")),
            "change": _safe_float(item.get("f3")),
            "volume": _safe_float(item.get("f6")),
            "amount": _safe_float(item.get("f5")),
            "turnoverRate": _safe_float(item.get("f8")),
        }
        pe = _safe_float(item.get("f9"), float("nan"))
        if math.isfinite(pe):
            row["pe"] = pe
        pb = _safe_float(item.get("f23"), float("nan"))
        if math.isfinite(pb):
            row["pb"] = pb
        # f20/f21 单位为万元（前端合同），collector 落库统一为元
        total_mv = _safe_float(item.get("f20"), float("nan"))
        if math.isfinite(total_mv):
            row["totalMarketValue"] = total_mv * 10000
        cir_mv = _safe_float(item.get("f21"), float("nan"))
        if math.isfinite(cir_mv):
            row["cirMV"] = cir_mv * 10000
        # 上游若透传涨停/跌停价（ztPrice/dtPrice）则保留；缺失由 builder 从 preClose 派生
        limit_up = _safe_float(item.get("ztPrice"), float("nan"))
        if math.isfinite(limit_up) and limit_up > 0:
            row["limitUpPrice"] = limit_up
        limit_down = _safe_float(item.get("dtPrice"), float("nan"))
        if math.isfinite(limit_down) and limit_down > 0:
            row["limitDownPrice"] = limit_down
        volume_ratio = _safe_float(item.get("f10"), float("nan"))
        if math.isfinite(volume_ratio) and volume_ratio > 0:
            row["volumeRatio"] = volume_ratio
        return row

    async def acollect(
        self,
        codes: list[str],
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[dict[str, dict[str, Any]], SourceHealth]:
        """进程内直读共享行情缓存（collector_main 内由 MarketQuotesCache 常驻刷新）。"""
        if not _is_in_process_gateway(self._gateway):
            return await asyncio.to_thread(self.collect, codes, timeout_ms=timeout_ms)

        from backend.market_proxy.quotes import get_market_quotes_cache

        started = time.monotonic()
        requested = list(dict.fromkeys(str(code).strip() for code in codes if str(code).strip()))
        cache = get_market_quotes_cache()
        status = cache.status()
        if status["rowCount"] == 0:
            return {}, SourceHealth(
                source=self.source,
                ok=False,
                latency_ms=int((time.monotonic() - started) * 1000),
                row_count=0,
                error=status["lastError"] or "cache_not_ready",
                captured_at=_iso_now(),
                requested_count=len(requested),
                returned_count=0,
                coverage_ratio=0.0,
            )
        body = cache.get_diff(requested)
        rows: dict[str, dict[str, Any]] = {}
        for item in _extract_proxy_quote_rows(body):
            row = self._normalize_row(item)
            if row is not None:
                rows[row["code"]] = row
        returned = sum(code in rows for code in requested)
        return rows, SourceHealth(
            source=self.source,
            ok=True,
            latency_ms=int((time.monotonic() - started) * 1000),
            row_count=len(rows),
            captured_at=_iso_now(),
            requested_count=len(requested),
            returned_count=returned,
            coverage_ratio=round(returned / len(requested), 4) if requested else 1.0,
        )


# ═════════════════════════════════════════════════════════════════════════════
# StartupBundleStockProvider
# ═════════════════════════════════════════════════════════════════════════════


class StartupBundleStockProvider:
    """Fetch live's merged stock pool from proxy-server startup cache."""

    def __init__(
        self,
        base_url: str = _DEFAULT_PROXY_BASE_URL,
        *,
        cache_key_prefix: str = "default",
        trading_date: str | None = None,
        gateway: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._cache_key_prefix = cache_key_prefix
        self._trading_date = trading_date
        self.snapshot_context: dict[str, Any] = {}
        # startup-bundle 由 proxy-server 本地缓存提供（独立于 8000），恒走 HTTP。
        self._gateway = gateway or HttpMarketDataGateway()

    def collect(
        self,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[list[dict[str, Any]], SourceHealth]:
        start = time.monotonic()
        key = self._cache_key()
        try:
            url = f"{self._base_url}/api/cache/startup-bundle?{urlencode({'key': key})}"
            body = self._gateway.get_json(url, timeout_ms / 1000.0)
            degraded_error = _proxy_degraded_error(body)
            if degraded_error:
                return [], self._health(False, start, error=degraded_error)

            bundle = body.get("data") if isinstance(body, dict) else None
            self.snapshot_context = (
                dict(bundle.get("snapshotContext"))
                if isinstance(bundle, dict) and isinstance(bundle.get("snapshotContext"), dict)
                else {}
            )
            stocks = bundle.get("stocks") if isinstance(bundle, dict) else None
            if not isinstance(stocks, list) or not stocks:
                return [], self._health(False, start, error="startup bundle missing")

            rows = self._normalize(stocks)
            if not rows:
                return [], self._health(False, start, error="startup bundle has no valid stocks")
            platform_data = bundle.get("platformData") if isinstance(bundle, dict) else None
            platform_totals = {
                platform: len(platform_data.get(platform) or [])
                if isinstance(platform_data, dict) and isinstance(platform_data.get(platform), list)
                else 0
                for platform in _HOTLIST_PLATFORMS
            }
            self._restore_rank_fields(rows, platform_data, platform_totals)
            has_snapshot_context = (
                isinstance(self.snapshot_context.get("breathData"), dict)
                and bool(self.snapshot_context["breathData"])
                and isinstance(self.snapshot_context.get("marketData"), dict)
                and bool(self.snapshot_context["marketData"])
            )
            return rows, self._health(
                has_snapshot_context,
                start,
                row_count=len(rows),
                error="" if has_snapshot_context else "startup bundle snapshotContext missing or incomplete",
                coverage_ratio=1.0,
                details={"rankProvenance": _rank_provenance(platform_totals)},
            )
        except Exception as exc:
            return [], self._health(False, start, error=str(exc))

    def _cache_key(self) -> str:
        trading_date = self._trading_date or datetime.now().strftime("%Y-%m-%d")
        return f"{self._cache_key_prefix}:{trading_date}"

    async def acollect(
        self,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[list[dict[str, Any]], SourceHealth]:
        """异步采集 startup bundle（proxy 本地缓存路由，始终 HTTP）。"""
        return await asyncio.to_thread(self.collect, timeout_ms=timeout_ms)

    def _health(
        self,
        ok: bool,
        start: float,
        *,
        row_count: int = 0,
        error: str = "",
        coverage_ratio: float = 0.0,
        details: dict[str, Any] | None = None,
    ) -> SourceHealth:
        return SourceHealth(
            source="startup_bundle",
            ok=ok,
            latency_ms=int((time.monotonic() - start) * 1000),
            row_count=row_count,
            error=error,
            captured_at=_iso_now(),
            requested_count=row_count,
            returned_count=row_count,
            coverage_ratio=coverage_ratio,
            details=details or {},
        )

    def _normalize(self, stocks: list[Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for item in stocks:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            row = dict(item)
            row["code"] = code
            row["name"] = str(row.get("name") or code)
            row["rank"] = _safe_int(row.get("rank") or row.get("compRank"), len(rows) + 1)
            if "change" in row and "pctChange" not in row:
                row["pctChange"] = row["change"]
            if "turnover" in row and "amount" not in row:
                row["amount"] = row["turnover"]
            if "hotness" in row and "heat" not in row:
                row["heat"] = row["hotness"]
            rows.append(row)
        return rows

    def _restore_rank_fields(
        self,
        rows: list[dict[str, Any]],
        platform_data: Any,
        platform_totals: dict[str, int],
    ) -> None:
        rows_by_code = {str(row.get("code") or ""): row for row in rows}
        parser = ProxyMergedHotlistProvider(self._base_url)
        for row in rows:
            for field in _HOTLIST_RANK_FIELDS.values():
                row[field] = _DEFAULT_RANK
        if isinstance(platform_data, dict):
            for platform in _HOTLIST_PLATFORMS:
                rank_field = _HOTLIST_RANK_FIELDS[platform]
                for platform_row in parser._normalize_platform(platform, platform_data.get(platform)):
                    stock = rows_by_code.get(str(platform_row.get("code") or ""))
                    if stock is not None:
                        stock[rank_field] = platform_row["rank"]
        for row in rows:
            _calculate_average_rank_fields(row, platform_totals)


# ═════════════════════════════════════════════════════════════════════════════
# ProxyHotlistProvider
# ═════════════════════════════════════════════════════════════════════════════


class ProxyHotlistProvider:
    """Fetch hotlist stock data from the proxy-server (eastmoney endpoint).

    Returns normalized stock rows suitable for ingestion into the snapshot
    pipeline.  Each row carries ``code``, ``name``, ``rank``, ``price``,
    ``pctChange``, ``volume``, ``amount``, ``turnover``, ``heat``.
    """

    def __init__(
        self,
        base_url: str = _DEFAULT_PROXY_BASE_URL,
        platform: str = "eastmoney",
        gateway: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._platform = platform
        self._gateway = gateway or _get_default_gateway()

    # ── public API ──────────────────────────────────────────────────────

    def collect(
        self,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[list[dict[str, Any]], SourceHealth]:
        """Fetch hotlist stocks and return ``(stock_rows, health)``.

        Never raises — errors are captured in the returned ``SourceHealth``.
        """
        start = time.monotonic()
        try:
            url = f"{self._base_url}/api/{self._platform}/hot"
            timeout_s = timeout_ms / 1000.0
            # Eastmoney endpoint uses POST
            body = self._gateway.post_json(url, timeout_s)
            rows = self._normalize(body)
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="hotlist_proxy",
                ok=True,
                latency_ms=latency_ms,
                row_count=len(rows),
                captured_at=_iso_now(),
            )
            return rows, health
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="hotlist_proxy",
                ok=False,
                latency_ms=latency_ms,
                error=str(exc),
                captured_at=_iso_now(),
            )
            return [], health

    # ── internal ────────────────────────────────────────────────────────

    def _normalize(self, body: Any) -> list[dict[str, Any]]:
        """Convert raw proxy response to a list of stock row dicts.

        Supports both legacy field names (c, r, n, p, zdf, etc.) and
        eastmoney native field names (sc, rk).
        """
        items = _extract_items(body)
        rows: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            # Eastmoney uses "sc", legacy format uses "c"/"code"
            code = str(item.get("sc") or item.get("c") or item.get("code") or "").strip()
            # Strip exchange prefix: SZ000630 → 000630, SH603993 → 603993
            if len(code) >= 8 and code[:2] in ("SZ", "SH", "BJ"):
                code = code[2:]
            if not code:
                continue
            row: dict[str, Any] = {
                "code": code,
                "name": str(item.get("n") or item.get("name") or code),
                "rank": _safe_int(item.get("rk") or item.get("r") or item.get("rank"), len(rows) + 1),
                "price": _safe_float(item.get("p") or item.get("price")),
                "pctChange": _safe_float(item.get("zdf") or item.get("pctChange")),
                "volume": _safe_int(item.get("cjl") or item.get("volume")),
                "amount": _safe_float(item.get("cje") or item.get("amount")),
                "turnover": _safe_float(item.get("hsl") or item.get("turnover")),
                "heat": _safe_float(item.get("hot") or item.get("heat")),
            }
            rows.append(row)
        return rows


class ProxyMergedHotlistProvider:
    """Fetch and merge all proxy hotlist platforms into a live-like stock pool."""

    def __init__(
        self,
        base_url: str = _DEFAULT_PROXY_BASE_URL,
        gateway: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._gateway = gateway or _get_default_gateway()

    def collect(
        self,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[list[dict[str, Any]], SourceHealth]:
        start = time.monotonic()
        stock_map: dict[str, dict[str, Any]] = {}
        platform_totals: dict[str, int] = {}
        failed_platforms: list[str] = []
        errors: list[str] = []

        for platform in _HOTLIST_PLATFORMS:
            try:
                body = self._fetch_platform(platform, timeout_ms / 1000.0)
                degraded_error = _proxy_degraded_error(body)
                if degraded_error:
                    raise RuntimeError(degraded_error)
                rows = self._normalize_platform(platform, body)
                platform_totals[platform] = len(rows)
                self._merge_platform_rows(stock_map, platform, rows)
            except Exception as exc:
                failed_platforms.append(platform)
                errors.append(f"{platform}: {exc}")
                platform_totals[platform] = 0

        rows = self._rank_rows(stock_map, platform_totals)
        completed_at = _iso_now()
        ok = bool(rows) and len(failed_platforms) < len(_HOTLIST_PLATFORMS)
        return rows, SourceHealth(
            source="merged_hotlist_proxy",
            ok=ok,
            latency_ms=int((time.monotonic() - start) * 1000),
            row_count=len(rows),
            error="; ".join(errors),
            captured_at=completed_at,
            requested_count=sum(platform_totals.values()),
            returned_count=len(rows),
            coverage_ratio=round(len(rows) / sum(platform_totals.values()), 4)
            if sum(platform_totals.values())
            else 0.0,
            failed_batches=failed_platforms,
            details={"rankProvenance": _rank_provenance(platform_totals)},
        )

    def _fetch_platform(self, platform: str, timeout_s: float) -> Any:
        url = f"{self._base_url}/api/{platform}/hot"
        if platform in ("eastmoney", "tdx"):
            payload = {} if platform == "eastmoney" else [{"listType": "0", "cycle": "0"}]
            return self._gateway.post_json(url, timeout_s, payload)
        return self._gateway.get_json(url, timeout_s)

    async def acollect(
        self,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[list[dict[str, Any]], SourceHealth]:
        """进程内直连热榜服务真实 get()：缓存→Redis→single-flight→last-good。"""
        if not _is_in_process_gateway(self._gateway):
            return await asyncio.to_thread(self.collect, timeout_ms=timeout_ms)

        from backend.market_proxy.hotlists import get_hotlist_service

        service = get_hotlist_service()
        start = time.monotonic()
        stock_map: dict[str, dict[str, Any]] = {}
        platform_totals: dict[str, int] = {}
        failed_platforms: list[str] = []
        errors: list[str] = []

        async def fetch_one(platform: str) -> None:
            try:
                payload = await service.get(platform)
            except Exception as exc:
                failed_platforms.append(platform)
                errors.append(f"{platform}: {exc}")
                platform_totals[platform] = 0
                return
            if payload is None or (
                isinstance(payload, dict) and payload.get("ok") is False
            ):
                failed_platforms.append(platform)
                errors.append(
                    f"{platform}: {str(payload.get('message') or payload.get('error') or 'degraded')[:120]}"
                    if isinstance(payload, dict)
                    else f"{platform}: empty payload"
                )
                platform_totals[platform] = 0
                return
            try:
                rows = self._normalize_platform(platform, payload)
            except Exception as exc:
                failed_platforms.append(platform)
                errors.append(f"{platform}: {exc}")
                platform_totals[platform] = 0
                return
            platform_totals[platform] = len(rows)
            self._merge_platform_rows(stock_map, platform, rows)

        await asyncio.gather(*(fetch_one(platform) for platform in _HOTLIST_PLATFORMS))
        rows = self._rank_rows(stock_map, platform_totals)
        completed_at = _iso_now()
        ok = bool(rows) and len(failed_platforms) < len(_HOTLIST_PLATFORMS)
        return rows, SourceHealth(
            source="merged_hotlist_proxy",
            ok=ok,
            latency_ms=int((time.monotonic() - start) * 1000),
            row_count=len(rows),
            error="; ".join(errors),
            captured_at=completed_at,
            requested_count=sum(platform_totals.values()),
            returned_count=len(rows),
            coverage_ratio=round(len(rows) / sum(platform_totals.values()), 4)
            if sum(platform_totals.values())
            else 0.0,
            failed_batches=failed_platforms,
            details={"rankProvenance": _rank_provenance(platform_totals)},
        )

    def _merge_platform_rows(
        self,
        stock_map: dict[str, dict[str, Any]],
        platform: str,
        rows: list[dict[str, Any]],
    ) -> None:
        rank_field = _HOTLIST_RANK_FIELDS[platform]
        for row in rows:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            stock = stock_map.get(code)
            if stock is None:
                stock = self._empty_stock(code)
                stock_map[code] = stock
            stock[rank_field] = row["rank"]
            name = str(row.get("name") or "").strip()
            if name and name != "-" and stock.get("name") in ("", "-"):
                stock["name"] = name
                stock["platformName"] = name

    def _normalize_platform(self, platform: str, body: Any) -> list[dict[str, Any]]:
        items = _extract_items(body)
        rows: list[dict[str, Any]] = []
        for index, item in enumerate(items):
            row = self._normalize_platform_item(platform, item, index)
            if row is not None:
                rows.append(row)
        return rows

    def _normalize_platform_item(
        self,
        platform: str,
        item: Any,
        index: int,
    ) -> dict[str, Any] | None:
        if isinstance(item, dict) and item.get("code") and item.get("rank") is not None:
            return self._row(code=item["code"], name=item.get("name"), rank=item["rank"])
        if platform == "kpl" and isinstance(item, list) and len(item) >= 2:
            return self._row(
                code=item[0],
                name=item[1],
                rank=item[4] if len(item) > 4 else index + 1,
            )
        if platform == "tdx" and isinstance(item, list) and len(item) >= 11:
            return self._row(code=item[1], name=item[2], rank=item[10])
        if platform == "dzh" and isinstance(item, dict):
            code_key = next(iter(item.keys()), "")
            return self._row(code=code_key, name="-", rank=index + 1)
        if platform == "cls" and isinstance(item, dict):
            stock = item.get("stock") if isinstance(item.get("stock"), dict) else {}
            return self._row(
                code=stock.get("StockID"),
                name=stock.get("name"),
                rank=index + 1,
            )
        if not isinstance(item, dict):
            return None

        code = (
            item.get("sc")
            or item.get("c")
            or item.get("code")
            or item.get("symbol")
            or item.get("fullCode")
            or item.get("StockID")
        )
        name = (
            item.get("sn")
            or item.get("n")
            or item.get("name")
            or item.get("stockName")
            or "-"
        )
        rank = item.get("rk") or item.get("r") or item.get("rank") or item.get("order") or item.get("ranking")
        return self._row(code=code, name=name, rank=rank or index + 1)

    def _row(self, *, code: Any, name: Any, rank: Any) -> dict[str, Any] | None:
        code_str = _normalize_stock_code(code)
        if not code_str:
            return None
        return {
            "code": code_str,
            "name": str(name or "-"),
            "rank": _safe_int(rank, _DEFAULT_RANK),
        }

    def _empty_stock(self, code: str) -> dict[str, Any]:
        row: dict[str, Any] = {
            "code": code,
            "name": "-",
            "price": 0,
            "pctChange": 0,
            "volume": 0,
            "amount": 0,
            "turnover": 0,
            "turnoverRate": 0,
            "heat": 0,
            "platformName": "",
        }
        for field in _HOTLIST_RANK_FIELDS.values():
            row[field] = _DEFAULT_RANK
        return row

    def _rank_rows(
        self,
        stock_map: dict[str, dict[str, Any]],
        platform_totals: dict[str, int],
    ) -> list[dict[str, Any]]:
        rows = list(stock_map.values())
        for row in rows:
            _calculate_average_rank_fields(row, platform_totals)

        rows.sort(key=lambda item: (float(item.get("avgRankNum") or _DEFAULT_RANK), -int(item.get("platforms") or 0)))
        for index, row in enumerate(rows, start=1):
            row["compRank"] = index
            row["rank"] = index
        return rows


def _extract_items(body: Any) -> list[Any]:
    """Extract the item list from a variety of proxy response shapes."""
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        # eastmoney shape: {"data": [...]}
        for key in ("data", "items", "List", "result", "dto"):
            value = body.get(key)
            if isinstance(value, list):
                return value
        # ths shape: {"data": {"stock_list": [...]}}
        data = body.get("data")
        if isinstance(data, dict):
            for key in ("stock_list", "items", "List"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
    return []


# ═════════════════════════════════════════════════════════════════════════════
# ProxyLimitUpProvider
# ═════════════════════════════════════════════════════════════════════════════


class ProxyLimitUpProvider:
    """Fetch THS limit-up pool enrichment from proxy-server."""

    def __init__(
        self,
        base_url: str = _DEFAULT_PROXY_BASE_URL,
        *,
        trading_date: str | None = None,
        gateway: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._trading_date = trading_date
        self._gateway = gateway or _get_default_gateway()

    def collect(
        self,
        codes: list[str] | None = None,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[list[dict[str, Any]], SourceHealth]:
        start = time.monotonic()
        requested = {_normalize_stock_code(code) for code in (codes or [])}
        requested.discard("")
        try:
            query = {}
            date = self._date_param()
            if date:
                query["date"] = date
            suffix = f"?{urlencode(query)}" if query else ""
            body = self._gateway.get_json(
                f"{self._base_url}/api/limitup/ths/pools{suffix}",
                timeout_ms / 1000.0,
            )
            degraded_error = _proxy_degraded_error(body)
            rows = self._normalize(body, requested_codes=requested)
            ok = not degraded_error
            return rows, self._health(
                ok,
                start,
                row_count=len(rows),
                error=degraded_error,
                requested_count=len(requested),
                returned_count=len(rows),
                coverage_ratio=round(len(rows) / len(requested), 4) if requested else 1.0,
            )
        except Exception as exc:
            return [], self._health(False, start, error=str(exc), requested_count=len(requested))

    def _date_param(self) -> str:
        digits = "".join(ch for ch in str(self._trading_date or "") if ch.isdigit())
        return digits if len(digits) == 8 else ""

    async def acollect(
        self,
        codes: list[str] | None = None,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[list[dict[str, Any]], SourceHealth]:
        """进程内直连涨停池服务真实 get_ths_pools()（含拉取，不依赖预缓存）。"""
        if not _is_in_process_gateway(self._gateway):
            return await asyncio.to_thread(self.collect, codes, timeout_ms=timeout_ms)

        from backend.market_proxy.limitup import get_limitup_service

        start = time.monotonic()
        requested = {_normalize_stock_code(code) for code in (codes or [])}
        requested.discard("")
        try:
            date = self._date_param()
            body = await get_limitup_service().get_ths_pools(date or None)
            degraded_error = _proxy_degraded_error(body)
            rows = self._normalize(body, requested_codes=requested)
            ok = not degraded_error
            return rows, self._health(
                ok,
                start,
                row_count=len(rows),
                error=degraded_error,
                requested_count=len(requested),
                returned_count=len(rows),
                coverage_ratio=round(len(rows) / len(requested), 4) if requested else 1.0,
            )
        except Exception as exc:
            return [], self._health(False, start, error=str(exc), requested_count=len(requested))

    def _health(
        self,
        ok: bool,
        start: float,
        *,
        row_count: int = 0,
        error: str = "",
        requested_count: int = 0,
        returned_count: int = 0,
        coverage_ratio: float = 0.0,
    ) -> SourceHealth:
        return SourceHealth(
            source="limitup_proxy",
            ok=ok,
            latency_ms=int((time.monotonic() - start) * 1000),
            row_count=row_count,
            error=error,
            captured_at=_iso_now(),
            requested_count=requested_count,
            returned_count=returned_count or row_count,
            coverage_ratio=coverage_ratio,
        )

    def _normalize(
        self,
        body: Any,
        *,
        requested_codes: set[str],
    ) -> list[dict[str, Any]]:
        pools = body.get("pools") if isinstance(body, dict) else None
        if not isinstance(pools, dict):
            return []
        by_code: dict[str, dict[str, Any]] = {}
        for pool_key in _LIMIT_UP_POOL_KEYS:
            pool = pools.get(pool_key)
            if not isinstance(pool, dict):
                continue
            items = pool.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                row = self._normalize_item(pool_key, item)
                if row is None:
                    continue
                code = row["code"]
                if requested_codes and code not in requested_codes:
                    continue
                existing = by_code.get(code, {})
                by_code[code] = {**existing, **row}
        return list(by_code.values())

    def _normalize_item(self, pool_key: str, item: Any) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None
        code = _normalize_stock_code(item.get("stock_code") or item.get("code"))
        if not code:
            return None
        first_time = _normalize_limit_time(
            item.get("limit_up_time") or item.get("first_limit_up_time")
        )
        last_time = _normalize_limit_time(item.get("last_limit_up_time")) or first_time
        board_height = (
            _positive_int(item.get("continue_day"))
            or _positive_int(item.get("continue_day_cnt"))
            or _parse_board_text(item.get("high_days"))
            or _parse_board_text(item.get("high_days_value"))
        )
        row: dict[str, Any] = {
            "code": code,
            "limitUpPool": pool_key,
        }
        name = str(item.get("stock_name") or item.get("name") or "").strip()
        if name:
            row["name"] = name
        reason = str(item.get("limit_up_reason") or item.get("reason_type") or "").strip()
        if reason:
            row["reason"] = reason
        if first_time:
            row["firstZtTime"] = first_time
        if last_time:
            row["lastZtTime"] = last_time
        if board_height is not None:
            row["boardHeight"] = board_height
            row["highDays"] = board_height
        for source_key, target_key in (
            ("volume_money", "fengdan"),
            ("order_amount", "fengdan"),
            ("turnover_rate", "turnoverRate"),
            ("rise_rate", "speed"),
            ("max_drawdown", "maxDrawdown"),
        ):
            value = item.get(source_key)
            if value is not None and target_key not in row:
                row[target_key] = _safe_float(value)
        return row


def _normalize_limit_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit() and len(text) == 10:
        return datetime.fromtimestamp(int(text), _TZ_SHANGHAI).strftime("%H:%M:%S")
    if text.isdigit() and len(text) in (3, 4, 5, 6):
        padded = text.zfill(6)
        return f"{padded[0:2]}:{padded[2:4]}:{padded[4:6]}"
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:00"
        if len(parts) >= 3:
            return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}:{parts[2].zfill(2)}"
    return text


def _positive_int(value: Any) -> int | None:
    number = _safe_int(value, 0)
    return number if number > 0 else None


def _parse_board_text(value: Any) -> int | None:
    text = str(value or "").strip()
    if text.isdigit():
        number = int(text)
        if number > 0xFFFF:
            decoded = number >> 16
            if decoded <= 0:
                decoded = number & 0xFFFF
            return decoded if decoded > 0 else None
    match = re.search(r"(\d+)\s*板", text)
    if not match:
        match = re.search(r"\d+", text)
    if not match:
        return None
    number = int(match.group(1) if match.groups() else match.group(0))
    return number if number > 0 else None


def _proxy_degraded_error(body: Any) -> str:
    """Return a proxy degraded/error message, or empty string for healthy bodies."""
    if not isinstance(body, dict):
        return ""
    if body.get("ok") is False or body.get("degraded") is True:
        return str(
            body.get("error")
            or body.get("message")
            or body.get("source")
            or "proxy returned degraded response"
        )
    return ""


def _extract_proxy_quote_rows(body: Any) -> list[dict[str, Any]]:
    """Extract field-coded quote rows from a proxy response."""
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, dict):
            diff = data.get("diff")
            if isinstance(diff, list):
                return diff
    return []


def _merge_rows_by_code(target: list[dict[str, Any]], rows: Any) -> None:
    if not isinstance(rows, list):
        return
    index: dict[str, int] = {}
    for pos, row in enumerate(target):
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if code:
            index[code] = pos
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        if code in index:
            target[index[code]] = {**target[index[code]], **row}
        else:
            index[code] = len(target)
            target.append(row)


# ═════════════════════════════════════════════════════════════════════════════
# BridgeQuoteProvider
# ═════════════════════════════════════════════════════════════════════════════


class BridgeQuoteProvider:
    """Fetch real-time quote snapshot from the python-bridge.

    Calls ``GET /api/quotes/snapshot?codes=...`` (direct mode) or
    ``GET /api/quotes/snapshot`` (pool mode, after ``set_pool()`` was
    called) and returns a dict containing ``quotes``, ``depth``,
    ``money_flow``, and ``market_meta``.

    Phase 2 adds a backend subscription pool so the collector can maintain
    a persistent set of stocks on the bridge without passing codes on every
    request.
    """

    # SourceHealth error attribute key for staleness warnings.
    STALE_KEY = "quote_stale"

    def __init__(
        self,
        base_url: str = _DEFAULT_BRIDGE_BASE_URL,
        *,
        pool_staleness_ms: int = 30000,
        gateway: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._pool_staleness_ms = pool_staleness_ms
        # bridge 是独立进程，行情/深度恒走 HTTP，不参与进程内网关。
        self._gateway = gateway or HttpMarketDataGateway()

    # ── public API ──────────────────────────────────────────────────────

    def set_pool(
        self,
        codes: list[str],
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> dict[str, Any]:
        """Register *codes* as the backend subscription pool on the bridge.

        Calls ``POST /api/quotes/subscriptions``.  Returns a dict with
        ``ok``, ``count``, and any error information.
        """
        try:
            url = f"{self._base_url}/api/quotes/subscriptions"
            timeout_s = timeout_ms / 1000.0
            body = self._gateway.post_json(url, timeout_s, {"codes": codes})
            return {
                "ok": body.get("ok", False),
                "count": body.get("count", 0),
                "codes": body.get("codes", []),
                "setAt": body.get("setAt", 0),
            }
        except Exception as exc:
            return {"ok": False, "count": 0, "error": str(exc)}

    def collect(
        self,
        codes: list[str] | None = None,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        use_pool: bool = False,
    ) -> tuple[dict[str, Any], SourceHealth]:
        """Fetch bridge snapshot for *codes* (or the pool when *use_pool*).

        Returns ``(data, health)`` where *data* is::

            {
                "quotes": [...],
                "depth": [...],
                "money_flow": [...],
                "market_meta": {...},
            }

        When *use_pool* is True the *codes* parameter is ignored and the
        request is sent without a ``codes`` query parameter, letting the
        bridge return cached pool data.

        When the bridge response includes ``"pooled": true`` and the
        ``poolRefreshedAt`` timestamp is older than *pool_staleness_ms*,
        a ``quote_stale`` warning key is added to ``SourceHealth.error``.

        Never raises — errors are captured in the returned ``SourceHealth``.
        """
        start = time.monotonic()
        if not use_pool and not codes:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="quote_bridge",
                ok=True,
                latency_ms=latency_ms,
                row_count=0,
                captured_at=_iso_now(),
            )
            return {"quotes": [], "depth": [], "money_flow": [], "market_meta": {}}, health

        try:
            if use_pool:
                # Pool mode: no codes param, bridge returns cached pool data
                url = f"{self._base_url}/api/quotes/snapshot"
            else:
                codes_param = ",".join(str(c).strip() for c in codes if str(c).strip())
                if not codes_param:
                    raise ValueError("no valid codes after filtering")
                url = (
                    f"{self._base_url}/api/quotes/snapshot"
                    f"?codes={quote(codes_param, safe='')}"
                )

            timeout_s = timeout_ms / 1000.0
            body = self._gateway.get_json(url, timeout_s)

            # Interpret bridge ok flag
            bridge_ok = body.get("ok", True)  # default True when absent
            if not bridge_ok:
                # Build a sensible error message from the body
                error_detail = body.get("error") or f"bridge returned ok=false (subscribedCount={body.get('subscribedCount', 0)})"
                latency_ms = int((time.monotonic() - start) * 1000)
                health = SourceHealth(
                    source="quote_bridge",
                    ok=False,
                    latency_ms=latency_ms,
                    error=str(error_detail),
                    captured_at=_iso_now(),
                )
                return {"quotes": [], "depth": [], "money_flow": [], "market_meta": {}}, health

            quotes = _normalize_quote_list(body.get("quotes"))
            depth = _normalize_depth_list(body.get("depth"))
            # Bridge HTTP money fields are not part of the formal snapshot contract.
            money_flow: list[dict[str, Any]] = []
            market_meta = _normalize_quote_stats(body.get("quoteStats"))

            latency_ms = int((time.monotonic() - start) * 1000)
            row_count = max(len(quotes), len(depth), len(money_flow))

            # Phase 2: staleness detection for pool-based responses
            error_msg = ""
            if use_pool and body.get("pooled") is True:
                pool_refreshed_at = body.get("poolRefreshedAt", 0)
                now = int(time.time() * 1000)
                if pool_refreshed_at and (now - pool_refreshed_at) > self._pool_staleness_ms:
                    age_ms = now - pool_refreshed_at
                    error_msg = (
                        f"{self.STALE_KEY}: pool data {age_ms}ms old "
                        f"(refreshedAt={pool_refreshed_at}, staleThresholdMs={self._pool_staleness_ms})"
                    )

            health = SourceHealth(
                source="quote_bridge",
                ok=True,
                latency_ms=latency_ms,
                row_count=row_count,
                error=error_msg,
                captured_at=_iso_now(),
            )
            data = {
                "quotes": quotes,
                "depth": depth,
                "money_flow": money_flow,
                "market_meta": market_meta,
            }
            return data, health

        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="quote_bridge",
                ok=False,
                latency_ms=latency_ms,
                error=str(exc),
                captured_at=_iso_now(),
            )
            return {"quotes": [], "depth": [], "money_flow": [], "market_meta": {}}, health

    async def acollect(
        self,
        codes: list[str] | None = None,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        use_pool: bool = False,
    ) -> tuple[dict[str, Any], SourceHealth]:
        """异步采集 bridge 行情（HTTP，独立进程）。"""
        return await asyncio.to_thread(
            self.collect,
            codes,
            timeout_ms=timeout_ms,
            use_pool=use_pool,
        )


def _normalize_quote_list(raw: Any) -> list[dict[str, Any]]:
    """Coerce raw quotes to a list of dicts with known keys."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        result.append(
            _with_optional_fields(
                {
                    "code": code,
                    "price": _safe_float(_first_non_empty(item, "price", "lastPrice")),
                    "pctChange": _safe_float(_first_non_empty(item, "pctChange", "changePct")),
                    "volume": _safe_int(item.get("volume")),
                    "amount": _safe_float(item.get("amount")),
                    "turnover": _safe_float(_first_non_empty(item, "turnover", "turnoverRate")),
                },
                {
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "preClose": item.get("preClose"),
                    "open": item.get("open"),
                    # 涨速由 python-bridge 计算（compute_quote_speed，60s 窗口），
                    # bridge 的 quotes 输出恒带 speed；透传供 stock row 填补。
                    "speed": item.get("speed"),
                },
            )
        )
    return result


def _with_optional_fields(row: dict[str, Any], raw_values: dict[str, Any]) -> dict[str, Any]:
    for key, value in raw_values.items():
        if value is not None:
            row[key] = _safe_float(value)
    return row


def _first_non_empty(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


def _normalize_depth_list(raw: Any) -> list[dict[str, Any]]:
    """Coerce raw depth to a list of dicts."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        row: dict[str, Any] = {"code": code}
        bids = _normalize_depth_side(item.get("bids"))
        asks = _normalize_depth_side(item.get("asks"))
        if bids:
            row["bids"] = bids
        if asks:
            row["asks"] = asks
        for i in range(1, 6):  # up to 5 bid/ask levels
            for prefix in ("bid", "ask"):
                for suffix in ("Price", "Vol"):
                    key = f"{prefix}{suffix}{i}"
                    if key in item:
                        row[key] = item[key]
        # Also copy any top-level depth fields
        for k in ("bidPrice1", "askPrice1", "bidVol1", "askVol1"):
            if k in item:
                row.setdefault(k, item[k])
        result.append(row)
    return result


def _normalize_depth_side(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw[:10]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "price": _safe_float(item.get("price")),
                "volume": _safe_int(item.get("volume")),
            }
        )
    return result


def _normalize_money_flow_list(raw: Any) -> list[dict[str, Any]]:
    """Coerce raw moneyFlow to a list of dicts."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        result.append(
            {
                "code": code,
                "mainNetInflow": _safe_float(item.get("mainNetInflow")),
                "superLargeNetInflow": _safe_float(item.get("superLargeNetInflow")),
                "largeNetInflow": _safe_float(item.get("largeNetInflow")),
                "mediumNetInflow": _safe_float(item.get("mediumNetInflow")),
                "smallNetInflow": _safe_float(item.get("smallNetInflow")),
            }
        )
    return result


def _normalize_quote_stats(raw: Any) -> dict[str, Any]:
    """Coerce raw quoteStats to a plain dict."""
    if not isinstance(raw, dict):
        return {}
    return {
        "totalVolume": _safe_int(raw.get("totalVolume")),
        "totalAmount": _safe_float(raw.get("totalAmount")),
        "upCount": _safe_int(raw.get("upCount")),
        "downCount": _safe_int(raw.get("downCount")),
        "flatCount": _safe_int(raw.get("flatCount")),
    }


# ═════════════════════════════════════════════════════════════════════════════
# ThemeMappingProvider
# ═════════════════════════════════════════════════════════════════════════════


class ThemeMappingProvider:
    """Map stock codes to theme/plate lists via the MongoDB theme repository.

    The repository object must expose a ``get_stock_themes(code: str) -> dict``
    method whose return value contains a ``"themes"`` key with a list of
    ``{"id": str, "name": str}`` dicts.
    """

    def __init__(self, theme_repository: Any) -> None:
        self._repo = theme_repository

    # ── public API ──────────────────────────────────────────────────────

    def collect(
        self,
        codes: list[str],
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[dict[str, list[str]], SourceHealth]:
        """Map *codes* to their theme name lists.

        Returns ``({code: [theme_name, ...]}, health)``.

        Per-code errors are tolerated and produce empty theme lists for that
        code.  The provider only reports ``ok=False`` when **every** requested
        code failed (or a catastrophic error occurred outside the per-code
        loop).
        """
        start = time.monotonic()
        if not codes:
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="theme_mapping",
                ok=True,
                latency_ms=latency_ms,
                row_count=0,
                captured_at=_iso_now(),
            )
            return {}, health

        try:
            result: dict[str, list[str]] = {}
            failed_count = 0
            first_error: str = ""
            pool = _get_collector_thread_pool()
            futures = {
                pool.submit(self._map_one, str(code).strip()): code
                for code in codes
            }
            for future in as_completed(futures):
                code = futures[future]
                key = str(code).strip()
                if not key:
                    result[key or code] = []
                    failed_count += 1
                    continue
                try:
                    themes, error = future.result()
                    result[key] = themes
                    if error:
                        failed_count += 1
                        if not first_error:
                            first_error = error
                except Exception as exc:
                    result[key] = []
                    failed_count += 1
                    if not first_error:
                        first_error = str(exc)

            latency_ms = int((time.monotonic() - start) * 1000)
            all_failed = failed_count == len(codes) and len(codes) > 0
            error_msg = ""
            if all_failed:
                error_msg = first_error or "all requested codes failed to map themes"
            health = SourceHealth(
                source="theme_mapping",
                ok=not all_failed,
                latency_ms=latency_ms,
                row_count=len(result) - failed_count,
                error=error_msg,
                captured_at=_iso_now(),
            )
            return result, health

        except Exception as exc:
            # Catastrophic error outside the per-code loop (e.g. repo init failed)
            latency_ms = int((time.monotonic() - start) * 1000)
            health = SourceHealth(
                source="theme_mapping",
                ok=False,
                latency_ms=latency_ms,
                error=str(exc),
                captured_at=_iso_now(),
            )
            return {}, health

    def _map_one(self, key: str) -> tuple[list[str], str | None]:
        """单 code 题材映射：返回 (themes, error)；异常不阻断其他 code。"""
        if not key:
            return [], None
        try:
            stock_data = self._repo.get_stock_themes(key)
            theme_items = stock_data.get("themes", [])
            if isinstance(theme_items, list):
                themes = [
                    str(t.get("name") or t.get("id") or "")
                    for t in theme_items
                    if isinstance(t, dict)
                ]
            else:
                themes = []
            return themes, None
        except Exception as exc:
            return [], str(exc)

    async def acollect(
        self,
        codes: list[str],
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[dict[str, list[str]], SourceHealth]:
        """异步逐 code 题材映射（信号量限制并发，不占用固定线程池）。"""
        started = time.monotonic()
        if not codes:
            return {}, SourceHealth(
                source="theme_mapping",
                ok=True,
                latency_ms=0,
                row_count=0,
                captured_at=_iso_now(),
            )
        sem = asyncio.Semaphore(8)

        async def map_one(code: Any) -> tuple[str, list[str], str | None]:
            key = str(code).strip()
            async with sem:
                themes, error = await asyncio.to_thread(self._map_one, key)
            return key, themes, error

        results = await asyncio.gather(
            *(map_one(code) for code in codes),
            return_exceptions=True,
        )
        result: dict[str, list[str]] = {}
        failed_count = 0
        first_error = ""
        for item in results:
            if isinstance(item, Exception):
                failed_count += 1
                if not first_error:
                    first_error = str(item)
                continue
            key, themes, error = item
            result[key] = themes
            if error:
                failed_count += 1
                if not first_error:
                    first_error = error
        all_failed = failed_count == len(codes) and len(codes) > 0
        return result, SourceHealth(
            source="theme_mapping",
            ok=not all_failed,
            latency_ms=int((time.monotonic() - started) * 1000),
            row_count=len(result) - failed_count,
            error=first_error if all_failed else "",
            captured_at=_iso_now(),
        )


class MarketFundCacheProvider:
    """Read last-good market funds without issuing upstream requests."""

    def __init__(self, cache: ThemeFundCache) -> None:
        self._cache = cache

    def collect(self, codes: list[str], *, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> tuple[list[dict[str, Any]], SourceHealth]:
        del timeout_ms
        started = time.monotonic()
        requested = list(dict.fromkeys(code for code in codes if code))
        cached = self._cache.get_latest(requested)
        rows: list[dict[str, Any]] = []
        for code in requested:
            row = cached.get(code)
            # 2026-08-12：资金行 source 诚实标识后，接受 L2 主源与 akshare 网页
            # 估算两种（此前只收 ths_main_monitor，akshare 行会被过滤导致快照资金列空）
            source = str(row.get("moneyFlowSource") or row.get("source") or "") if row else ""
            if source not in SUPPORTED_FUND_SOURCES:
                continue
            zlje = row.get("zlje")
            if not isinstance(zlje, (int, float)) or isinstance(zlje, bool) or not math.isfinite(float(zlje)):
                continue
            item: dict[str, Any] = {
                "code": code, "mainNetInflow": float(zlje),
                "moneyFlowSource": source,
                "moneyFlowEstimated": source != FUND_SOURCE_THS_MAIN_MONITOR,
                "capitalFlowSource": source,
                "capitalFlowConfidence": "high" if source == FUND_SOURCE_THS_MAIN_MONITOR else "medium",
                # M1（2026-08-11 审计）：暴露资金行时效信息
                "moneyFlowSessionDate": row.get("sessionDate"),
                "moneyFlowSourceTs": row.get("sourceTs"),
            }
            if isinstance(row.get("zljzb"), (int, float)) and math.isfinite(float(row["zljzb"])):
                item["mainNetRatio"] = float(row["zljzb"])
            rows.append(item)
        returned = len(rows)
        requested_count = len(requested)
        return rows, SourceHealth(
            source="market_fund_cache", ok=returned == requested_count,
            latency_ms=int((time.monotonic() - started) * 1000), row_count=returned,
            error="" if returned == requested_count else "partial last-good fund coverage",
            captured_at=_iso_now(), requested_count=requested_count, returned_count=returned,
            coverage_ratio=round(returned / requested_count, 4) if requested_count else 1.0, stale=True,
        )

    async def acollect(
        self,
        codes: list[str],
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[list[dict[str, Any]], SourceHealth]:
        return await asyncio.to_thread(self.collect, codes, timeout_ms=timeout_ms)


# ═════════════════════════════════════════════════════════════════════════════
# Collector orchestrator
# ═════════════════════════════════════════════════════════════════════════════


def collect_market_context(
    providers: list[Any],
    codes: list[str],
    *,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> MarketDataContext:
    """Collect data from all *providers* and assemble a ``MarketDataContext``.

    Each provider is called with either ``.collect(timeout_ms=...)`` or
    ``.collect(codes, timeout_ms=...)`` depending on its type.  The
    ``MarketDataContext`` aggregates all returned data rows and health
    records.

    Provider routing
    ----------------
    * ``StartupBundleStockProvider`` / ``ProxyMergedHotlistProvider`` / ``ProxyHotlistProvider`` → ``ctx.stocks``
    * ``TencentBasicQuoteProvider`` → ``ctx.quotes``
    * ``BridgeQuoteProvider``   → ``ctx.quotes``, ``ctx.depth``, ``ctx.market_meta``
    * ``ThemeMappingProvider``  → ``ctx.themes``
    * ``ProxyLimitUpProvider``  → ``ctx.limit_up``

    Unknown provider types are silently ignored.
    """
    ctx = MarketDataContext()
    active_codes = [str(code).strip() for code in codes if str(code).strip()]

    for provider in providers:
        try:
            if isinstance(provider, StartupBundleStockProvider):
                rows, health = provider.collect(timeout_ms=timeout_ms)
                ctx.source_health.append(health)
                if rows:
                    ctx.stocks = rows
                    ctx.snapshot_context = dict(provider.snapshot_context)
                    active_codes = [
                        str(row.get("code") or "").strip()
                        for row in rows
                        if isinstance(row, dict) and str(row.get("code") or "").strip()
                    ]

            elif isinstance(provider, (ProxyMergedHotlistProvider, ProxyHotlistProvider)):
                if ctx.stocks:
                    continue
                rows, health = provider.collect(timeout_ms=timeout_ms)
                ctx.stocks.extend(rows)
                ctx.source_health.append(health)
                if not active_codes:
                    active_codes = [
                        str(row.get("code") or "").strip()
                        for row in rows
                        if isinstance(row, dict) and str(row.get("code") or "").strip()
                    ]

            elif isinstance(provider, TencentBasicQuoteProvider):
                rows, health = provider.collect(active_codes, timeout_ms=timeout_ms)
                _merge_rows_by_code(ctx.quotes, list(rows.values()))
                ctx.source_health.append(health)

            elif isinstance(provider, BridgeQuoteProvider):
                data, health = provider.collect(active_codes, timeout_ms=timeout_ms)
                if isinstance(data, dict):
                    _merge_rows_by_code(ctx.quotes, data.get("quotes") or [])
                    ctx.depth.extend(data.get("depth") or [])
                    if data.get("market_meta"):
                        ctx.market_meta.update(data["market_meta"])
                ctx.source_health.append(health)

            elif isinstance(provider, MarketFundCacheProvider):
                rows, health = provider.collect(active_codes, timeout_ms=timeout_ms)
                ctx.money_flow.extend(rows)
                ctx.source_health.append(health)

            elif isinstance(provider, ThemeMappingProvider):
                themes, health = provider.collect(active_codes, timeout_ms=timeout_ms)
                if isinstance(themes, dict):
                    ctx.themes.update(themes)
                ctx.source_health.append(health)

            elif isinstance(provider, ProxyLimitUpProvider):
                rows, health = provider.collect(active_codes, timeout_ms=timeout_ms)
                for row in rows:
                    if isinstance(row, dict):
                        code = str(row.get("code") or "").strip()
                        if code:
                            ctx.limit_up[code] = row
                ctx.source_health.append(health)

        except Exception as exc:
            # A provider raised unexpectedly — record it as a failed health
            health = SourceHealth(
                source=getattr(provider, "__class__", type(provider)).__name__,
                ok=False,
                error=str(exc),
                captured_at=_iso_now(),
            )
            ctx.source_health.append(health)

    return ctx


async def collect_market_context_async(
    providers: list[Any],
    codes: list[str],
    *,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> MarketDataContext:
    """异步采集：await 各 provider 的 acollect（进程内直连真实服务）。"""
    ctx = MarketDataContext()
    active_codes = [str(code).strip() for code in codes if str(code).strip()]

    for provider in providers:
        try:
            if isinstance(provider, StartupBundleStockProvider):
                rows, health = await provider.acollect(timeout_ms=timeout_ms)
                ctx.source_health.append(health)
                if rows:
                    ctx.stocks = rows
                    ctx.snapshot_context = dict(provider.snapshot_context)
                    active_codes = [
                        str(row.get("code") or "").strip()
                        for row in rows
                        if isinstance(row, dict) and str(row.get("code") or "").strip()
                    ]

            elif isinstance(provider, (ProxyMergedHotlistProvider, ProxyHotlistProvider)):
                if ctx.stocks:
                    continue
                rows, health = await provider.acollect(timeout_ms=timeout_ms)
                ctx.stocks.extend(rows)
                ctx.source_health.append(health)
                if not active_codes:
                    active_codes = [
                        str(row.get("code") or "").strip()
                        for row in rows
                        if isinstance(row, dict) and str(row.get("code") or "").strip()
                    ]

            elif isinstance(provider, TencentBasicQuoteProvider):
                rows, health = await provider.acollect(active_codes, timeout_ms=timeout_ms)
                _merge_rows_by_code(ctx.quotes, list(rows.values()))
                ctx.source_health.append(health)

            elif isinstance(provider, BridgeQuoteProvider):
                data, health = await provider.acollect(active_codes, timeout_ms=timeout_ms)
                if isinstance(data, dict):
                    _merge_rows_by_code(ctx.quotes, data.get("quotes") or [])
                    ctx.depth.extend(data.get("depth") or [])
                    if data.get("market_meta"):
                        ctx.market_meta.update(data["market_meta"])
                ctx.source_health.append(health)

            elif isinstance(provider, MarketFundCacheProvider):
                rows, health = await provider.acollect(active_codes, timeout_ms=timeout_ms)
                ctx.money_flow.extend(rows)
                ctx.source_health.append(health)

            elif isinstance(provider, ThemeMappingProvider):
                themes, health = await provider.acollect(active_codes, timeout_ms=timeout_ms)
                if isinstance(themes, dict):
                    ctx.themes.update(themes)
                ctx.source_health.append(health)

            elif isinstance(provider, ProxyLimitUpProvider):
                rows, health = await provider.acollect(active_codes, timeout_ms=timeout_ms)
                for row in rows:
                    if isinstance(row, dict):
                        code = str(row.get("code") or "").strip()
                        if code:
                            ctx.limit_up[code] = row
                ctx.source_health.append(health)

        except Exception as exc:
            health = SourceHealth(
                source=getattr(provider, "__class__", type(provider)).__name__,
                ok=False,
                error=str(exc),
                captured_at=_iso_now(),
            )
            ctx.source_health.append(health)

    return ctx
