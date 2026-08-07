from __future__ import annotations

import time
from concurrent.futures import Future
from dataclasses import asdict, is_dataclass
from datetime import datetime
from threading import Lock
from typing import Any, Callable
from zoneinfo import ZoneInfo

from backend.analysis.theme.heat import compute_theme_heat
from backend.data.mongo_theme_repository import MongoThemeRepository
from backend.data.repository_factory import get_runtime_mongodb_database
from backend.settings import get_settings
from backend.snapshot_collector.providers import TencentBasicQuoteProvider
from backend.services.theme.fund_cache import get_theme_fund_cache


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
        fund_cache: Any,
        *,
        now_ms: Callable[[], int] | None = None,
        cache_ttl_seconds: int = 300,
        quote_timeout_ms: int = 10000,
    ) -> None:
        self._repository = repository
        self._quote_provider = quote_provider
        self._fund_cache = fund_cache
        self._now_ms = now_ms or (lambda: int(time.time() * 1000))
        self._cache_ttl_seconds = max(1, cache_ttl_seconds)
        self._quote_timeout_ms = max(100, quote_timeout_ms)
        self._cache: dict[str, dict[str, object]] = {}
        self._quote_cache: dict[str, tuple[dict[str, dict[str, object]], object]] = {}
        self._inflight: dict[str, Future[dict[str, object]]] = {}
        self._last_success: dict[str, object] | None = None
        self._lock = Lock()

    def get_snapshot(
        self,
        *,
        force: bool = False,
        include_runtime_funds: bool = True,
        include_rotation_state: bool = False,
    ) -> dict[str, object]:
        snapshot = self._get_snapshot_core(
            force=force,
            include_runtime_funds=include_runtime_funds,
        )
        if include_rotation_state and isinstance(snapshot, dict):
            snapshot = self._with_rotation_state(snapshot)
        return snapshot

    def _get_snapshot_core(
        self,
        *,
        force: bool,
        include_runtime_funds: bool,
    ) -> dict[str, object]:
        universe = self._repository.get_market_universe()
        if not universe.get("themes") or not universe.get("stockCodes"):
            raise ThemeHeatUnavailable(
                code="mapping_empty",
                message="MongoDB theme mapping is empty",
                stale_data=self._last_success,
            )
        cache_key, cache_bucket = self._cache_key(
            str(universe.get("version") or "unknown"),
            self._fund_cache.current_version() if include_runtime_funds else -1,
            include_runtime_funds,
        )

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
            snapshot = self._refresh(
                universe,
                cache_bucket,
                force_quotes=force,
                include_runtime_funds=include_runtime_funds,
            )
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

    def _with_rotation_state(self, snapshot: dict[str, object]) -> dict[str, object]:
        """合并引擎落库的最新 rotationState/lifecycle/rotationScore（后端生产，前端只消费）。"""
        rotation_by_theme = self._load_latest_rotation_state()
        if not rotation_by_theme:
            return snapshot
        factors = snapshot.get("factors")
        if not isinstance(factors, list):
            return snapshot
        enriched: list[object] = []
        for factor in factors:
            if not isinstance(factor, dict):
                enriched.append(factor)
                continue
            state = rotation_by_theme.get(str(factor.get("themeId") or ""))
            if not state:
                enriched.append(factor)
                continue
            item = {**factor}
            item["rotationState"] = str(state.get("rotationState") or "neutral")
            if state.get("lifecycle"):
                item["lifecycle"] = state["lifecycle"]
            if state.get("rotationScore") is not None:
                item["rotationScore"] = state["rotationScore"]
            enriched.append(item)
        return {**snapshot, "factors": enriched}

    def _load_latest_rotation_state(self) -> dict[str, dict[str, object]]:
        """读取最近一次引擎落库的 sector rows rotationState（只读，异常时按无数据处理）。"""
        try:
            db = get_runtime_mongodb_database()
            latest = db["snapshot_sector_rows"].find_one(
                {
                    "entityType": "hot_theme",
                    "rotationState": {"$nin": [None, ""]},
                },
                sort=[("timestamp", -1)],
            )
            if not latest:
                return {}
            rows = list(
                db["snapshot_sector_rows"].find(
                    {
                        "snapshotId": latest.get("snapshotId"),
                        "entityType": "hot_theme",
                    },
                    {
                        "themeId": 1,
                        "entityKey": 1,
                        "rotationState": 1,
                        "lifecycle": 1,
                        "rotationScore": 1,
                        "_id": 0,
                    },
                )
            )
        except Exception:
            return {}
        result: dict[str, dict[str, object]] = {}
        for row in rows or []:
            theme_id = str(row.get("themeId") or row.get("entityKey") or "")
            state = str(row.get("rotationState") or "")
            if theme_id and state:
                result[theme_id] = {
                    "rotationState": state,
                    "lifecycle": row.get("lifecycle"),
                    "rotationScore": row.get("rotationScore"),
                }
        return result

    def get_fund_rows(self, codes: list[str]) -> dict[str, dict[str, object]]:
        normalized = list(dict.fromkeys(str(code).strip() for code in codes if str(code).strip()))
        rows = self._fund_cache.get_latest(normalized)
        return {
            code: {
                **row,
                "mainNetInflow": row.get("zlje"),
                "superLargeNetInflow": row.get("cddje"),
                "superLargeNetRatio": row.get("cddjzb"),
                "mainNetRatio": row.get("zljzb"),
            }
            for code, row in rows.items()
        }

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

    def _cache_key(
        self,
        mapping_version: str,
        fund_version: int,
        include_runtime_funds: bool,
    ) -> tuple[str, str]:
        bucket_ms = self._cache_ttl_seconds * 1000
        bucket_start = self._now_ms() // bucket_ms * bucket_ms
        bucket = datetime.fromtimestamp(
            bucket_start / 1000,
            tz=ZoneInfo("Asia/Shanghai"),
        ).isoformat()
        scope = "runtime" if include_runtime_funds else "formal"
        return f"{mapping_version}:{fund_version}:{scope}:{bucket}", bucket

    def _refresh(
        self,
        universe: dict[str, object],
        cache_bucket: str,
        *,
        force_quotes: bool,
        include_runtime_funds: bool,
    ) -> dict[str, object]:
        stock_codes = [str(code) for code in universe.get("stockCodes", [])]
        quote_key = f"{universe.get('version') or 'unknown'}:{cache_bucket}"
        cached_quotes = self._quote_cache.get(quote_key)
        if force_quotes or cached_quotes is None:
            quote_rows, quote_health = self._quote_provider.collect(
                stock_codes,
                timeout_ms=self._quote_timeout_ms,
            )
            self._quote_cache = {quote_key: (quote_rows, quote_health)}
        else:
            quote_rows, quote_health = cached_quotes
        fund_rows = self.get_fund_rows(stock_codes) if include_runtime_funds else {}
        fund_health = {
            "source": "ths_main_monitor" if include_runtime_funds else "formal_fund_unavailable",
            "ok": include_runtime_funds,
            "requested_count": len(stock_codes),
            "returned_count": len(fund_rows),
            "coverage_ratio": len(fund_rows) / len(stock_codes) if stock_codes else 1.0,
        }
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
            # 覆盖率不足不是硬门禁：返回已计算的降级因子与结构化质量原因（fail-visible）。
            # 前端展示可计算部分 + 缺失位置/原因，不整段 503 隐藏已有数据。
            result["degraded"] = True

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
                TencentBasicQuoteProvider(
                    proxy_base,
                    collection_timeout_ms=settings.theme_heat_quote_collection_timeout_ms,
                    **provider_options,
                ),
                get_theme_fund_cache(),
                cache_ttl_seconds=settings.theme_heat_cache_ttl_seconds,
                quote_timeout_ms=settings.theme_heat_quote_timeout_ms,
            )
    return _theme_heat_service
