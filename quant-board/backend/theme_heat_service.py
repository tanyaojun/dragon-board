from __future__ import annotations

import time
from concurrent.futures import Future
from dataclasses import asdict, is_dataclass
from datetime import datetime
from threading import Lock
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backend.analysis.theme_heat import compute_theme_heat
from backend.data.mongo_theme_repository import MongoThemeRepository
from backend.data.repository_factory import get_runtime_mongodb_database
from backend.settings import get_settings
from backend.snapshot_collector.providers import EastmoneyFundFlowProvider, TencentBasicQuoteProvider


class ThemeHeatUnavailable(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str = "",
        stale_data: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.stale_data = stale_data


class ThemeHeatService:
    def __init__(
        self,
        repository: Any,
        quote_provider: Any,
        fund_provider: Any,
        *,
        now_ms: Callable[[], int] | None = None,
        cache_ttl_seconds: int = 300,
        quote_timeout_ms: int = 10000,
        fund_timeout_ms: int = 12000,
    ) -> None:
        self._repository = repository
        self._quote_provider = quote_provider
        self._fund_provider = fund_provider
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache_ttl_seconds = max(1, cache_ttl_seconds)
        self._quote_timeout_ms = max(100, quote_timeout_ms)
        self._fund_timeout_ms = max(100, fund_timeout_ms)
        self._cache: dict[str, dict[str, object]] = {}
        self._inflight: dict[str, Future[dict[str, object]]] = {}
        self._last_success: dict[str, object] | None = None
        self._lock = Lock()

    def get_snapshot(self, *, force: bool = False) -> dict[str, object]:
        universe = self._repository.get_market_universe()
        if not universe.get("themes") or not universe.get("stockCodes"):
            raise ThemeHeatUnavailable(
                code="mapping_empty",
                message="MongoDB theme mapping is empty",
                stale_data=self._last_success,
            )
        cache_key, cache_bucket = self._cache_key(str(universe.get("version") or "unknown"))

        owner = False
        with self._lock:
            if not force and cache_key in self._cache:
                return self._cache[cache_key]
            future = self._inflight.get(cache_key)
            if future is None:
                future = Future()
                self._inflight[cache_key] = future
                owner = True

        if not owner:
            return future.result()

        try:
            snapshot = self._refresh(universe, cache_bucket)
            with self._lock:
                self._cache = {cache_key: snapshot}
                self._last_success = snapshot
            future.set_result(snapshot)
            return snapshot
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._inflight.pop(cache_key, None)

    def get_theme_stocks(
        self,
        theme_id: str,
        *,
        offset: int = 0,
        limit: int = 80,
        sort_by: str = "change",
        descending: bool = True,
    ) -> dict[str, object]:
        snapshot = self.get_snapshot(force=False)
        return self._slice_theme_stocks(
            snapshot,
            theme_id=theme_id,
            offset=offset,
            limit=limit,
            sort_by=sort_by,
            descending=descending,
        )

    def _cache_key(self, mapping_version: str) -> tuple[str, str]:
        bucket_ms = self._cache_ttl_seconds * 1000
        bucket_start = self._now_ms() // bucket_ms * bucket_ms
        bucket = datetime.fromtimestamp(
            bucket_start / 1000,
            tz=ZoneInfo("Asia/Shanghai"),
        ).isoformat()
        return f"{mapping_version}:{bucket}", bucket

    def _refresh(self, universe: dict[str, object], cache_bucket: str) -> dict[str, object]:
        stock_codes = [str(code) for code in universe.get("stockCodes", [])]
        quote_rows, quote_health = self._quote_provider.collect(
            stock_codes,
            timeout_ms=self._quote_timeout_ms,
        )
        fund_rows, fund_health = self._fund_provider.collect(
            stock_codes,
            timeout_ms=self._fund_timeout_ms,
        )
        theme_stocks = universe.get("themeStocks") if isinstance(universe.get("themeStocks"), dict) else {}
        themes = [
            {
                **theme,
                "stocks": list(theme_stocks.get(str(theme.get("id") or ""), [])),
            }
            for theme in universe.get("themes", [])
            if isinstance(theme, dict)
        ]
        previous_factors = {
            str(factor.get("themeId") or ""): factor
            for factor in (self._last_success or {}).get("factors", [])
            if isinstance(factor, dict)
        }
        computed_at = self._now_ms()
        result = compute_theme_heat(
            themes=themes,
            quotes=quote_rows,
            funds=fund_rows,
            previous_factors=previous_factors,
            computed_at=computed_at,
            mapping_version=str(universe.get("version") or "unknown"),
        )
        if not result["ok"]:
            raise ThemeHeatUnavailable(
                code="quote_coverage_blocked",
                message="Tencent quote coverage is below 85%",
                stale_data=self._last_success,
            )

        result.update(
            {
                "cacheBucket": cache_bucket,
                "sources": {
                    "quotes": self._health_dict(quote_health),
                    "funds": self._health_dict(fund_health),
                },
                "quoteRowsByCode": quote_rows,
                "fundRowsByCode": fund_rows,
                "themeStocks": theme_stocks,
                "stockThemes": universe.get("stockThemes", {}),
            }
        )
        return result

    def _slice_theme_stocks(
        self,
        snapshot: dict[str, object],
        *,
        theme_id: str,
        offset: int,
        limit: int,
        sort_by: str,
        descending: bool,
    ) -> dict[str, object]:
        theme_stocks = snapshot.get("themeStocks") if isinstance(snapshot.get("themeStocks"), dict) else {}
        quote_rows = snapshot.get("quoteRowsByCode") if isinstance(snapshot.get("quoteRowsByCode"), dict) else {}
        fund_rows = snapshot.get("fundRowsByCode") if isinstance(snapshot.get("fundRowsByCode"), dict) else {}
        rows: list[dict[str, object]] = []
        for code in theme_stocks.get(theme_id, []):
            quote = quote_rows.get(code) if isinstance(quote_rows.get(code), dict) else {}
            fund = fund_rows.get(code) if isinstance(fund_rows.get(code), dict) else {}
            change = float(quote.get("change") or 0)
            rows.append(
                {
                    "code": code,
                    "name": str(quote.get("name") or code),
                    "change": change,
                    "price": float(quote.get("price") or 0),
                    "volumeRatio": quote.get("volumeRatio"),
                    "mainNetInflow": fund.get("mainNetInflow"),
                    "turnoverRate": quote.get("turnoverRate"),
                    "rank": 0,
                    "role": "leader" if change >= 9.5 else "core" if change >= 5 else "follower",
                    "qualityFlags": [],
                }
            )
        rows.sort(
            key=lambda row: (float(row.get(sort_by) or 0), str(row.get("code") or "")),
            reverse=descending,
        )
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        start = max(0, offset)
        end = start + max(1, limit)
        return {
            "themeId": theme_id,
            "total": len(rows),
            "offset": start,
            "limit": max(1, limit),
            "stocks": rows[start:end],
            "computedAt": snapshot.get("computedAt"),
        }

    @staticmethod
    def _health_dict(health: object) -> dict[str, object]:
        if is_dataclass(health):
            return asdict(health)
        return dict(health) if isinstance(health, dict) else {}


_theme_heat_service: ThemeHeatService | None = None
_theme_heat_service_lock = Lock()


def get_theme_heat_service() -> ThemeHeatService:
    global _theme_heat_service
    with _theme_heat_service_lock:
        if _theme_heat_service is None:
            settings = get_settings()
            try:
                database = get_runtime_mongodb_database()
            except Exception as exc:
                raise ThemeHeatUnavailable(
                    code="mapping_unavailable",
                    message=str(exc),
                ) from exc
            if database is None:
                raise ThemeHeatUnavailable(
                    code="mapping_unavailable",
                    message="MongoDB theme database is not configured",
                )
            provider_options = {
                "batch_size": settings.theme_heat_batch_size,
                "max_concurrency": settings.theme_heat_max_concurrency,
                "failed_batch_retries": settings.theme_heat_failed_batch_retries,
            }
            proxy_base = settings.snapshot_collector_proxy_base_url
            _theme_heat_service = ThemeHeatService(
                MongoThemeRepository(database),
                TencentBasicQuoteProvider(proxy_base, **provider_options),
                EastmoneyFundFlowProvider(proxy_base, **provider_options),
                cache_ttl_seconds=settings.theme_heat_cache_ttl_seconds,
                quote_timeout_ms=settings.theme_heat_quote_timeout_ms,
                fund_timeout_ms=settings.theme_heat_fund_timeout_ms,
            )
    return _theme_heat_service
