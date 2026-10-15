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
import logging
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

import httpx

from backend.analysis.ranktrend.ranking.comprehensive_rank import (
    average_rank_fields,
    HOTLIST_DEFAULT_RANK as _DEFAULT_RANK,
    HOTLIST_PLATFORMS as _HOTLIST_PLATFORMS,
    HOTLIST_RANK_FIELDS as _HOTLIST_RANK_FIELDS,
    HOTLIST_WEIGHTS as _HOTLIST_WEIGHTS,
)

from backend.core.fund_sources import (
    FUND_SOURCE_THS_MAIN_MONITOR,
    SUPPORTED_FUND_SOURCES,
)
if TYPE_CHECKING:
    from backend.services.theme.fund_cache import ThemeFundCache

from .gateway import HttpMarketDataGateway
from .models import MarketDataContext, SourceHealth

# ── constants ───────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)
_DEFAULT_PROXY_BASE_URL = "http://127.0.0.1:3000"
_DEFAULT_BRIDGE_BASE_URL = "http://127.0.0.1:8765"
_DEFAULT_TIMEOUT_MS = 5000
_THS_RETRY_DELAY_S = 2.5  # THS 涨停池首试失败后的重试间隔（限流/抖动多为瞬时）
# 采集链消费的池子集；连板层五池 2026-10-10 起重新入采（仅 EOD 时段拉取一次）：
# jev 叙事/连板指数成为新消费者后「零消费」前提失效（b5d4ac36 当时的砍除依据）。
# 日增仅 EOD 后若个证据构建 ×5 发，服务层 250ms 节流+退避负缓存仍在，风控成本可控。
_COLLECTOR_POOL_KEYS = ("failed", "rushing", "drawdown")
_LADDER_POOL_KEYS = ("one", "two", "three", "four", "high")
_EOD_LADDER_CUTOFF_MIN = 15 * 60  # 上海时间 ≥15:00 起连板层并入采集（EOD 帧口径）


def _evidence_pool_keys(now_sh: Any) -> tuple[tuple[str, ...], str]:
    """盘中三池；EOD 时段（上海 ≥15:00）连板层五池并入。返回 (pool_keys, cache_key 后缀)。"""
    include = now_sh.hour * 60 + now_sh.minute >= _EOD_LADDER_CUTOFF_MIN
    return ((_COLLECTOR_POOL_KEYS + _LADDER_POOL_KEYS) if include else _COLLECTOR_POOL_KEYS,
            ":ladder" if include else "")
# 证据级缓存（模块级：provider 实例每次上下文构建都新建）；风控优化详见 ths-limitup-arsenal-audit.md
_SERVER_EVIDENCE_CACHE: dict[str, dict[str, Any]] = {}
_SERVER_EVIDENCE_TTL_S = 300.0

# 默认数据网关：CLI/手动链路走 HTTP（proxy 转发）；collector_main 独立采集进程
# 通过 set_default_gateway() 切换为进程内直连，避免 8000 自环依赖。
_DEFAULT_GATEWAY: Any | None = None

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

# 采集池来源模式（2026-09-20 spec：docs/superpowers/specs/2026-09-19-snapshot-pool-autonomous-source-design.md）
# autonomous = 八平台热榜实时合并池为主池（bundle 只供 snapshotContext，merged 全挂时 bundle 行兜底）；
# bundle_first = 旧行为（bundle 为主池，merged/单平台热榜仅 fallback）。
POOL_SOURCE_MODES = ("autonomous", "bundle_first")
_POOL_SOURCE_AUTONOMOUS = "autonomous"
_POOL_SOURCE_BUNDLE_FALLBACK = "bundle_fallback"


def normalize_pool_source_mode(value: Any) -> str:
    mode = str(value or "").strip()
    if mode in POOL_SOURCE_MODES:
        return mode
    logger.warning("snapshot collector pool_source_mode 非法值 %r，折算为 autonomous", value)
    return "autonomous"


def _mark_pool_source(rows: list[dict[str, Any]], source: str) -> None:
    for row in rows:
        if isinstance(row, dict):
            row["poolSource"] = source


def _codes_of(rows: list[dict[str, Any]]) -> list[str]:
    return [
        str(row.get("code") or "").strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("code") or "").strip()
    ]


def _append_pool_composition(health: SourceHealth, *, mode: str, pool_size: int) -> None:
    composition = {
        "poolComposition": {
            "mode": mode,
            "poolSize": pool_size,
            "failedPlatforms": list(health.failed_batches or []),
            "platformTotals": (health.details or {}).get("rankProvenance", {}).get("platformTotals", {}),
        }
    }
    if isinstance(health.details, dict):
        health.details.update(composition)

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


def _append_quote_coverage_warning(ctx: MarketDataContext, active_codes: list[str]) -> None:
    """行情覆盖率告警（2026-08-17 A3）：quotes 覆盖热榜 code 比例 < 0.8 时记录 warning health。

    high/low 缺失根因（2026-08-17）：热榜源无 high/low，依赖行情补充；行情采集间歇性
    覆盖不全（批次失败/桥 dead_code 挂起）→ 该帧股票缺 high/low。此处把低覆盖率显式暴露
    （fail-visible），供采集审计/监控发现。
    """
    if not active_codes or not ctx.quotes:
        return
    quoted_codes = {str(q.get("code") or "").strip() for q in ctx.quotes if q.get("code")}
    covered = sum(1 for code in active_codes if code in quoted_codes)
    coverage = covered / len(active_codes)
    if coverage < 0.8:
        ctx.source_health.append(
            SourceHealth(
                source="quote_coverage",
                ok=True,
                row_count=covered,
                requested_count=len(active_codes),
                coverage_ratio=round(coverage, 4),
                error=f"quotes 覆盖率 {covered}/{len(active_codes)}（{coverage:.0%}）< 80%",
                details={
                    "quoteCoverage": round(coverage, 4),
                    "covered": covered,
                    "total": len(active_codes),
                },
                captured_at=_iso_now(),
            )
        )


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
    """均榜计算（weighted_platform_percentile_v1）。

    2026-09-22 实现提升到 analysis 层（backend.analysis.ranktrend.ranking.
    comprehensive_rank，采集/实时共用唯一实现，防两处公式漂移）；本函数保留
    模块内调用点别名。
    """
    average_rank_fields(row, platform_totals)


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
        failed_batch_retries: int = 2,  # 2026-08-17 A1：批次失败重试 1→2，降低行情补充丢股票（high/low 缺失根因）
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

        # 保留 avgRankNum 单维 rank（历史消费口径）：按 avgRankNum 排序序号
        rows.sort(key=lambda item: (float(item.get("avgRankNum") or _DEFAULT_RANK), -int(item.get("platforms") or 0)))
        for index, row in enumerate(rows, start=1):
            row["rank"] = index

        # 2026-08-23 前后端分离：五维综合排名后端 golden（前端零计算）。
        # compScore/compRank 用五维（avgRankNum 反 + zljzb + fundPenetration + turnoverRate + turnover），
        # avgRankNum 作 HOT_RANK 输入；fundPenetration = zlje/cirMV*100。
        from backend.analysis.ranktrend.comprehensive_rank import compute_comprehensive_scores

        for row in rows:
            try:
                cir_mv = float(row.get("cirMV"))
                zlje = float(row.get("zlje"))
                row["fundPenetration"] = (zlje / cir_mv) * 100 if math.isfinite(cir_mv) and math.isfinite(zlje) and cir_mv != 0 else None
            except (TypeError, ValueError):
                row["fundPenetration"] = None
        compute_comprehensive_scores(rows)  # 赋 compScore + compRank（五维降序稳定）
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
    pool_source_mode: str = "autonomous",
) -> MarketDataContext:
    """Collect data from all *providers* and assemble a ``MarketDataContext``（sync 薄壳）。

    2026-09-20 parity 收敛：路由状态机只有 ``collect_market_context_async`` 一份实现，
    本函数是它的 ``asyncio.run`` 薄壳（CLI/测试/手动场景专用，调用方不得处于
    running event loop 内）。生产采集进程走 ``_collect_context`` 默认分支直接 await
    async 版，不经本函数。参数与行为契约见 async 版 docstring，两入口永远同语义——
    不再有"人工镜像"，漂移在结构上不可能。
    """
    return asyncio.run(
        collect_market_context_async(
            providers,
            codes,
            timeout_ms=timeout_ms,
            pool_source_mode=pool_source_mode,
        )
    )

async def collect_market_context_async(
    providers: list[Any],
    codes: list[str],
    *,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    pool_source_mode: str = "autonomous",
) -> MarketDataContext:
    """异步采集：await 各 provider 的 acollect（进程内直连真实服务）。

    唯一的路由状态机实现（2026-09-20 parity 收敛）：sync 入口
    ``collect_market_context`` 是本函数的 ``asyncio.run`` 薄壳，两入口永远同语义。
    Provider 路由（pool_source_mode）：
    * ``autonomous``（默认）: ``ProxyMergedHotlistProvider`` 为主池来源；
      ``StartupBundleStockProvider`` 只供 ``snapshot_context``（其 stocks 不入池），
      merged 全挂时 bundle 行兜底（``poolSource=bundle_fallback``）：bundle 缓存就绪时
      立即兜底（下游 provider 按兜底池补齐）；bundle 在 merged 之后才出现时由循环
      结束后的安全网统一兜底——不依赖 provider 顺序。
      ``ProxyHotlistProvider``（单平台诊断源）不入池。
    * ``bundle_first``（回退）: 旧行为——bundle 为主池，merged/单平台热榜仅 fallback。
    * ``TencentBasicQuoteProvider`` → ``ctx.quotes``；``BridgeQuoteProvider`` → quotes/depth/market_meta；
      ``ThemeMappingProvider`` → ``ctx.themes``；``ProxyLimitUpProvider`` → ``ctx.limit_up``

    Unknown provider types are silently ignored.
    """
    ctx = MarketDataContext()
    active_codes = [str(code).strip() for code in codes if str(code).strip()]
    mode = normalize_pool_source_mode(pool_source_mode)

    bundle_fallback_rows: list[dict[str, Any]] = []
    merged_failed_empty = False
    merged_health: SourceHealth | None = None
    for provider in providers:
        try:
            if isinstance(provider, StartupBundleStockProvider):
                rows, health = await provider.acollect(timeout_ms=timeout_ms)
                ctx.source_health.append(health)
                if mode == "bundle_first":
                    if rows:
                        ctx.stocks = rows
                        ctx.snapshot_context = dict(provider.snapshot_context)
                        active_codes = _codes_of(rows)
                else:
                    # autonomous：bundle 只供 context；rows 留作 merged 全挂时的兜底池
                    if provider.snapshot_context:
                        ctx.snapshot_context = dict(provider.snapshot_context)
                    bundle_fallback_rows = [row for row in rows if isinstance(row, dict)]

            elif isinstance(provider, ProxyMergedHotlistProvider):
                if ctx.stocks:
                    continue
                try:
                    rows, health = await provider.acollect(timeout_ms=timeout_ms)
                except Exception as exc:
                    # 正常实现下 merged.acollect 按平台聚合失败、不抛错；若意外抛错，
                    # 折叠为失败 health 继续走下方 bundle 兜底，不让异常跳过兜底（fail-visible）。
                    rows = []
                    health = SourceHealth(
                        source="merged_hotlist_proxy",
                        ok=False,
                        error=str(exc),
                        captured_at=_iso_now(),
                    )
                ctx.source_health.append(health)
                merged_health = health
                if mode == "bundle_first":
                    if not ctx.stocks:
                        ctx.stocks.extend(rows)
                        if not active_codes:
                            active_codes = _codes_of(rows)
                elif rows:
                    _mark_pool_source(rows, _POOL_SOURCE_AUTONOMOUS)
                    ctx.stocks = rows
                    active_codes = _codes_of(rows)
                else:
                    # autonomous：merged 全挂/空池——置位供循环后安全网兜底（顺序反转场景）。
                    merged_failed_empty = True
                    if bundle_fallback_rows:
                        # 快路径：bundle 缓存行已就绪——立即兜底入池，下游 quote/theme/limitup
                        # provider 仍按兜底池补齐（fail-visible：不构成丢帧）
                        _mark_pool_source(bundle_fallback_rows, _POOL_SOURCE_BUNDLE_FALLBACK)
                        ctx.stocks = bundle_fallback_rows
                        active_codes = _codes_of(bundle_fallback_rows)
                _append_pool_composition(health, mode=mode, pool_size=len(ctx.stocks))

            elif isinstance(provider, ProxyHotlistProvider):
                # 单平台诊断源：仅 bundle_first 且池为空时沿用旧行为；autonomous 不入池。
                # 跳过发生在 collect 之前，故 autonomous 下没有该源的 health 记录——有意省略。
                if mode == "autonomous" or ctx.stocks:
                    continue
                # 该 provider 未实现 acollect，按文件内既有适配模式经线程池走同步 collect。
                rows, health = await asyncio.to_thread(provider.collect, timeout_ms=timeout_ms)
                ctx.stocks.extend(rows)
                ctx.source_health.append(health)
                if not active_codes:
                    active_codes = _codes_of(rows)

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

            elif isinstance(provider, ServerMarketEvidenceProvider):
                evidence, health = await provider.acollect(timeout_ms=timeout_ms)
                ctx.source_health.append(health)
                if isinstance(evidence, dict) and evidence:
                    limit_summary = evidence.get("limitSummary")
                    if isinstance(limit_summary, dict) and limit_summary:
                        ctx.limit_summary = limit_summary
                    indices = evidence.get("indices")
                    if isinstance(indices, dict) and indices:
                        ctx.indices = indices

        except Exception as exc:
            health = SourceHealth(
                source=getattr(provider, "__class__", type(provider)).__name__,
                ok=False,
                error=str(exc),
                captured_at=_iso_now(),
            )
            ctx.source_health.append(health)

    if (
        mode == "autonomous"
        and merged_failed_empty
        and not ctx.stocks
        and bundle_fallback_rows
    ):
        # 顺序反转安全网：merged 失败时 bundle 尚未缓存（bundle 在后），快路径未命中；
        # 循环后统一兜底（不依赖 provider 顺序，fail-visible：不构成丢帧）。
        # not ctx.stocks 守卫使快路径已兜底的场景在此天然跳过，不会双重入池。
        _mark_pool_source(bundle_fallback_rows, _POOL_SOURCE_BUNDLE_FALLBACK)
        ctx.stocks = bundle_fallback_rows
        active_codes = _codes_of(bundle_fallback_rows)
        if merged_health is not None:
            _append_pool_composition(merged_health, mode=mode, pool_size=len(ctx.stocks))

    _append_quote_coverage_warning(ctx, active_codes)
    return ctx


# ═════════════════════════════════════════════════════════════════════════════
# ServerLimitSummaryProvider
# ═════════════════════════════════════════════════════════════════════════════


def _limit_board_bucket(item: dict[str, Any]) -> int:
    """THS 涨停池条目 → 连板高度（1=首板，0=未知）。解析链同 LimitUpPoolProvider._normalize_item。"""
    if "首板" in str(item.get("high_days") or ""):
        return 1
    for key in ("continue_day", "continue_day_cnt"):
        value = _positive_int(item.get(key))
        if value:
            return value
    for key in ("high_days", "high_days_value"):
        value = _parse_board_text(item.get(key))
        if value:
            return value
    return 0


def _int_or_zero(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def build_server_limit_summary(
    info_items: list[dict[str, Any]],
    ths_pools: dict[str, Any],
) -> dict[str, Any]:
    """THS 涨停池原始数据 → frame.limitSummary（服务端构建，脱离浏览器 startup-bundle）。

    2026-09-24 排查：limitSummary 此前取自前端写入 proxy 的 startup-bundle（TTL 300s），
    浏览器断供的槽位帧该字段为空（11:00/11:30/14:00/15:00 四帧），触发情绪文档全市场
    证据回退。本函数用进程内 THS 涨停池接口构建同形数据：

    - continuousBoards：limit_up_pool 条目按连板高度分桶（yiban/erban/sanban/sibanPlus/maxBoard）；
    - zhaban：count=炸板池家数（poolCounts.failed 缺失时按 pools.failed.items 派生，
      禁止把「取不到」伪装成 0），fengbanRate=zt/(zt+炸板)；
    - thsPools：get_ths_pools 响应透传，failedCount/rushingCount/drawdownCount 缺失时按
      对应池 items 数派生；
    - yesterdayZt 不再产出（下游 limitEvidence 未消费，仅历史帧遗留键）。
    """
    if not isinstance(info_items, list) or not info_items:
        # 上游无数据：空 dict（falsy），由调用方回退浏览器原料/最近有效帧，
        # 绝不产出全零结构（会被 _limit_summary_has_evidence 误判为有效证据）
        return {}
    boards = {"yiban": 0, "erban": 0, "sanban": 0, "sibanPlus": 0, "maxBoard": 0}
    for item in info_items if isinstance(info_items, list) else []:
        if not isinstance(item, dict):
            continue
        height = _limit_board_bucket(item)
        if height <= 0:
            continue
        if height == 1:
            boards["yiban"] += 1
        elif height == 2:
            boards["erban"] += 1
        elif height == 3:
            boards["sanban"] += 1
        else:
            boards["sibanPlus"] += 1
        boards["maxBoard"] = max(boards["maxBoard"], height)

    pools = ths_pools.get("pools") if isinstance(ths_pools, dict) else None
    pools = pools if isinstance(pools, dict) else {}

    def _pool_items(key: str) -> list[dict[str, Any]]:
        pool = pools.get(key)
        items = pool.get("items") if isinstance(pool, dict) else None
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    def _pool_count(key: str) -> int | None:
        explicit = ths_pools.get(key) if isinstance(ths_pools, dict) else None
        if isinstance(explicit, (int, float)):
            return int(explicit)
        counts = ths_pools.get("poolCounts") if isinstance(ths_pools, dict) else None
        from_counts = counts.get(key) if isinstance(counts, dict) else None
        if isinstance(from_counts, (int, float)):
            return int(from_counts)
        items = _pool_items(key)
        if items:
            return len(items)
        pool = pools.get(key)
        if isinstance(pool, dict) and pool.get("ok") is False:
            return None  # 单池上游失败：取不到，禁止伪装成 0
        return 0 if pools else None

    failed = _pool_count("failed")
    zt_count = len([i for i in info_items if isinstance(i, dict)]) if isinstance(info_items, list) else 0
    if failed is None:
        # 炸板池不可用（缺失/上游失败）：不产出数值，禁止伪装成 0/封板率 100%
        zhaban = {"count": None, "rate": None, "fengbanRate": None, "ztCount": zt_count}
    else:
        total = zt_count + failed
        zhaban = {
            "count": failed,
            "rate": round(failed / total * 100, 2) if total else 0,
            "fengbanRate": round(zt_count / total * 100, 2) if total else 0,
            "ztCount": zt_count,
        }

    ths_pools_out = dict(ths_pools) if isinstance(ths_pools, dict) else {}
    for count_key, pool_key in (
        ("failedCount", "failed"),
        ("rushingCount", "rushing"),
        ("drawdownCount", "drawdown"),
    ):
        if ths_pools_out.get(count_key) is None:
            derived = _pool_count(pool_key)
            if derived is not None:
                ths_pools_out[count_key] = derived

    # 大幅回撤池（THS drawdown）：曾触板后深度回撤个股——负反馈候选指标（2026-10-02 弹药扩展，
    # 先采集+回测验证，过验前不进 jev 判层）。API max_drawdown 为负数字符串，此处存正幅值；
    # 池上游失败时 count=None（fail-visible，不伪装 0）。逐股明细不落 limitSummary（体积），
    # 回测/研究走回撤池接口现查。
    dd_count = _pool_count("drawdown")
    dd_draws: list[float] = []
    for it in _pool_items("drawdown"):
        v = it.get("max_drawdown")
        if isinstance(v, str):
            try:
                v = float(v)
            except ValueError:
                v = None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            dd_draws.append(round(-float(v), 2))
    drawdown = {
        "count": dd_count,
        "avgDrawdownPct": round(sum(dd_draws) / len(dd_draws), 2) if dd_draws else None,
        "deepestDrawdownPct": max(dd_draws) if dd_draws else None,
    }

    # 封板质量（THS info open_num 波次 + limit_up_suc_rate，2026-10-02 裁决采集）：
    # open_num 语义=None=一字/秒板（开盘即封无波次数据，键缺失≠0）、1=一波封住（硬板）、
    # ≥2=开板重封（烂板，回测次日溢价单调劣于硬板/一字）；limit_up_suc_rate=个股历史封板
    # 成功率 [0,1]（此前未采集，用户裁决补上）。inf0=0 与 info 为空时全 None（fail-visible）。
    byz = hard = rotten = 0
    suc_vals: list[float] = []
    for it in info_items if isinstance(info_items, list) else []:
        if not isinstance(it, dict):
            continue
        on = it.get("open_num")
        if on is None:
            byz += 1
        elif isinstance(on, (int, float)) and not isinstance(on, bool):
            if on <= 1:
                hard += 1
            else:
                rotten += 1
        suc = it.get("limit_up_suc_rate")
        if isinstance(suc, (int, float)) and not isinstance(suc, bool) and 0 <= suc <= 1:
            suc_vals.append(float(suc))
    quality_n = byz + hard + rotten
    seal_quality = {
        "byzCount": byz,
        "hardCount": hard,
        "rottenCount": rotten,
        "rottenShare": round(rotten / quality_n, 3) if quality_n else None,
        "avgSucRate": round(sum(suc_vals) / len(suc_vals), 3) if suc_vals else None,
    }

    return {
        "continuousBoards": boards,
        "zhaban": zhaban,
        "drawdown": drawdown,
        "sealQuality": seal_quality,
        "thsPools": ths_pools_out,
        "source": "server-limitup",
        "capturedAt": _iso_now(),
    }


# 浏览器原 indices 键位（rotation 引擎 _market_change 仅对各 change 求均值）
_INDEX_ALIASES = {
    "sh000001": "sh",
    "sh000300": "hs300",
    "sh000905": "zz500",
    "sh000852": "zz1000",
}


def build_server_indices(overview: dict[str, Any]) -> dict[str, Any]:
    """MarketOverviewService overview → frame.indices（键位对齐原浏览器 marketData.indices）。

    2026-09-30 增补 totalAmount：两市总成交额（当日累计，元）= 上证 sh000001 + 深市 sz399001
    （sina 深证系列同源，399001 与 399106 同值，即深市全口径）。值形如 {"amount": N}，
    **不带 change 键**——rotation 引擎 _market_change 遍历所有键取 change 求均值，
    无 change 则免疫，golden 输入零漂移。
    2026-10-16 增补 changePct：与 change（涨跌额=点位）伴生落 changePct（涨跌幅=百分比）——
    此前只落点位，消费端按 % 呈现即伪造暴跌（实证：帧值 -60.75 点被渲染成「上证 -60.75%」，
    10-12 两只 zhaban label 因此误判 broad_market）。rotation 引擎只取 change 键，
    新增键对其免疫；changePct 缺失（上游未给）时只落点位，由消费端诚实降级。
    """
    items = overview.get("items") if isinstance(overview, dict) else []
    out: dict[str, Any] = {}
    market_amounts: list[float] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "")
        alias = _INDEX_ALIASES.get(code)
        change = item.get("change")
        pct = item.get("changePct")
        if alias and isinstance(change, (int, float)) and not isinstance(change, bool):
            entry: dict[str, Any] = {"change": change}
            if isinstance(pct, (int, float)) and not isinstance(pct, bool):
                entry["changePct"] = pct
            out[alias] = entry
        if code in ("sh000001", "sz399001") and isinstance(item.get("amount"), (int, float)) \
                and not isinstance(item.get("amount"), bool):
            market_amounts.append(float(item["amount"]))
    if len(market_amounts) == 2:
        # 两市都可得才写（避免单市场半口径伪装全口径）
        out["totalAmount"] = {"amount": sum(market_amounts)}
    return out


class ServerMarketEvidenceProvider:
    """服务端直连构建 frame 的浏览器依赖证据：limitSummary + indices。

    2026-09-24/25 排查：limitSummary 与 indices 此前均取自前端写入 proxy 的
    startup-bundle（TTL 300s），浏览器断供的槽位帧相应字段为空——limitSummary 空
    触发情绪文档全市场证据回退（09-24 四帧），indices 空导致题材轮动引擎
    `_market_change` 输入缺失。本 provider 进程内直连：

    - market_proxy.limitup（THS 涨停池/炸板池）→ limitSummary；
    - market_proxy.indices（MarketOverviewService，akshare-sina，Redis 缓存）→ indices
      （sh/hs300/zz500/zz1000 四指数涨跌，与原浏览器键位对齐）。

    上游失败返回空 dict + 失败 health（fail-visible，不阻断采集）；
    frames 帧级 moneyFlow/sentiment 为遗留键（无下游消费方/仅对照），不从服务端重建。
    """

    def __init__(
        self,
        *,
        trading_date: str | None = None,
        gateway: Any = None,
    ) -> None:
        self._trading_date = trading_date
        self._gateway = gateway or _get_default_gateway()

    async def acollect(
        self,
        *,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> tuple[dict[str, Any], SourceHealth]:
        start = time.monotonic()
        digits = "".join(ch for ch in str(self._trading_date or "") if ch.isdigit())
        date = digits if len(digits) == 8 else None
        # 证据级 TTL 缓存（2026-10-02 风控优化）：provider 实例每次上下文构建都新建，
        # 缓存挂模块级——同交易日 5 分钟内复用同一份证据（capturedAt 保留原取数时刻可追溯），
        # THS 请求从 ~48 槽组×4 请求/日 降到 ~10 半小时边界×4（约 -90%）。
        # 2026-10-10：EOD 时段（≥15:00）连板层五池并入，缓存键加 :ladder 后缀隔离，
        # 盘中缓存的三池证据不会被 EOD 构建复用（反之亦然）。
        now_sh = datetime.now(_TZ_SHANGHAI)
        pool_keys, cache_suffix = _evidence_pool_keys(now_sh)
        cache_key = (date or "live") + cache_suffix
        cached = _SERVER_EVIDENCE_CACHE.get(cache_key)
        if cached and time.monotonic() - cached["at"] < _SERVER_EVIDENCE_TTL_S:
            return cached["evidence"], cached["health"]
        info_items: list[dict[str, Any]] = []
        pools_body: dict[str, Any] = {}
        indices: dict[str, Any] = {}
        limit_summary: dict[str, Any] = {}
        errors: list[str] = []
        try:
            if _is_in_process_gateway(self._gateway):
                from backend.market_proxy.indices import get_market_overview_service
                from backend.market_proxy.limitup import get_limitup_service

                async def _attempt_limit_evidence() -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
                    """THS 涨停池证据单次尝试：返回 (info_items, pools_body, attempt_errors)。

                    盘中只取采集链消费的三池（failed/rushing/drawdown）；EOD 时段连板层
                    五池并入（pool_keys 由外层按上海时钟决定）；面板全量走 API 路由
                    （独立缓存键互不污染）。
                    """
                    attempt_errors: list[str] = []
                    service = get_limitup_service()
                    list_body = await service.get_limit_up_list(date or None)
                    pools_body = await service.get_ths_pools(
                        date or None, keys=pool_keys)
                    data = list_body.get("data") if isinstance(list_body, dict) else None
                    raw_info = data.get("info") if isinstance(data, dict) else None
                    items = [i for i in raw_info if isinstance(i, dict)] if isinstance(raw_info, list) else []
                    if not items:
                        attempt_errors.append("THS limit_up_pool info 为空")
                    return items, pools_body if isinstance(pools_body, dict) else {}, attempt_errors

                # THS 收盘时点间歇失败（限流/超时）曾致 9 月 15:00 limitSummary 缺 13/21 帧；
                # 首试失败隔短延时重试一次；service 侧风控返空已有指数退避负缓存，
                # 重试若落在退避窗口内会直接复用空结果（不再打上游），不会放大突发
                first_errors: list[str] = []
                try:
                    info_items, pools_body, first_errors = await _attempt_limit_evidence()
                except Exception as exc:
                    first_errors = [str(exc)[:200]]
                    info_items, pools_body = [], {}
                if not info_items:
                    logger.warning("server_market_evidence THS 首试失败，重试一次：%s", first_errors)
                    await asyncio.sleep(_THS_RETRY_DELAY_S)
                    try:
                        info_items, pools_body, retry_errors = await _attempt_limit_evidence()
                    except Exception as exc:
                        retry_errors = [str(exc)[:200]]
                        info_items, pools_body = [], {}
                    if not info_items:
                        errors.extend(f"重试后仍失败：{e}" for e in retry_errors)
                if info_items:
                    limit_summary = build_server_limit_summary(info_items, pools_body)
                # 单池上游失败冒泡为可观察标记（get_ths_pools 对单池独立 try/except 不抛出）
                pools = pools_body.get("pools") if isinstance(pools_body, dict) else None
                if isinstance(pools, dict):
                    for pool_key, pool in pools.items():
                        if isinstance(pool, dict) and pool.get("ok") is False:
                            errors.append(f"ths pool {pool_key} 上游失败")
                try:
                    overview = await get_market_overview_service().get_overview()
                    indices = build_server_indices(overview)
                except Exception as exc:
                    errors.append(f"indices_failed: {str(exc)[:120]}")
            else:
                errors.append("in-process gateway unavailable")
        except Exception as exc:
            errors.append(str(exc)[:200])

        # Critical（评审 2026-09-25）：上游失败/无数据时绝不携带 limitSummary——
        # 全零结构会被下游误判为有效证据（_limit_summary_has_evidence=True），
        # 既伪装「取不到为 0」又废掉情绪文档的 EOD 回退机制；不携带则由下游
        # 回退浏览器原料，再回退最近有效槽位。
        evidence: dict[str, Any] = {"indices": indices}
        if limit_summary:
            evidence["limitSummary"] = limit_summary
        health = SourceHealth(
            source="server_market_evidence",
            ok=not errors,
            latency_ms=int((time.monotonic() - start) * 1000),
            row_count=len(info_items),
            error="; ".join(errors),
            captured_at=_iso_now(),
        )
        # 只缓存成功证据：失败不缓存（下一槽组应重试新鲜数据）
        if not errors:
            _SERVER_EVIDENCE_CACHE[cache_key] = {"evidence": evidence, "health": health,
                                                 "at": time.monotonic()}
        return evidence, health
