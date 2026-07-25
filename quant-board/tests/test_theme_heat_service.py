from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.theme_heat_service import ThemeHeatService, ThemeHeatUnavailable
from backend.snapshot_collector.models import SourceHealth


class FakeRepo:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty
        self.calls = 0

    def get_market_universe(self) -> dict:
        self.calls += 1
        if self.empty:
            return {
                "version": "empty",
                "lastUpdate": "",
                "themes": [],
                "themeStocks": {},
                "stockThemes": {},
                "stockCodes": [],
            }
        return {
            "version": "theme-v8-test",
            "lastUpdate": "2026-05-05T09:30:00Z",
            "themes": [{"id": "AI", "name": "人工智能", "zsCode": "BK0800"}],
            "themeStocks": {"AI": ["000001", "000002"]},
            "stockThemes": {"000001": ["AI"], "000002": ["AI"]},
            "stockCodes": ["000001", "000002"],
        }


class FakeProvider:
    def __init__(self, rows: dict[str, dict], *, source: str, delay: float = 0) -> None:
        self.rows = rows
        self.source = source
        self.delay = delay
        self.calls = 0
        self.requested_codes: list[list[str]] = []

    def collect(self, codes: list[str], *, timeout_ms: int) -> tuple[dict[str, dict], SourceHealth]:
        del timeout_ms
        self.calls += 1
        self.requested_codes.append(list(codes))
        if self.delay:
            time.sleep(self.delay)
        returned = sum(code in self.rows for code in codes)
        return self.rows, SourceHealth(
            source=self.source,
            ok=True,
            requested_count=len(codes),
            returned_count=returned,
            coverage_ratio=returned / len(codes) if codes else 1,
        )


class FakeFundCache:
    def __init__(self, rows: dict[str, dict], *, version: int = 7) -> None:
        self.rows = rows
        self.version = version
        self.calls: list[list[str]] = []

    def get_latest(self, codes: list[str]) -> dict[str, dict]:
        self.calls.append(list(codes))
        return {code: self.rows[code] for code in codes if code in self.rows}

    def current_version(self) -> int:
        return self.version


def _quotes() -> dict[str, dict]:
    return {
        "000001": {"code": "000001", "name": "样本一", "price": 10, "change": 6, "amount": 1000, "volumeRatio": 2},
        "000002": {"code": "000002", "name": "样本二", "price": 9, "change": 2, "amount": 800, "volumeRatio": 1.5},
    }


def _funds() -> dict[str, dict]:
    return {
        "000001": {
            "code": "000001", "zlje": 100, "version": 7,
            "moneyFlowSource": "ths_main_monitor", "sessionDate": "2026-07-24",
        },
        "000002": {
            "code": "000002", "zlje": -20, "version": 7,
            "moneyFlowSource": "ths_main_monitor", "sessionDate": "2026-07-24",
        },
    }


def test_service_coalesces_same_bucket_refreshes() -> None:
    quote_provider = FakeProvider(_quotes(), source="quotes", delay=0.02)
    fund_provider = FakeFundCache(_funds())
    service = ThemeHeatService(
        FakeRepo(),
        quote_provider,
        fund_provider,
        now_ms=lambda: 1782018300000,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(service.get_snapshot)
        second_future = pool.submit(service.get_snapshot)
        first = first_future.result()
        second = second_future.result()

    assert first is second
    assert quote_provider.calls == 1
    assert len(fund_provider.calls) == 1


def test_fund_version_change_invalidates_same_bucket_snapshot() -> None:
    quote_provider = FakeProvider(_quotes(), source="quotes")
    fund_cache = FakeFundCache(_funds(), version=7)
    service = ThemeHeatService(
        FakeRepo(),
        quote_provider,
        fund_cache,
        now_ms=lambda: 1782018300000,
    )

    first = service.get_snapshot()
    fund_cache.rows["000001"] = {**fund_cache.rows["000001"], "zlje": 500, "version": 8}
    fund_cache.version = 8
    second = service.get_snapshot()

    assert second is not first
    assert quote_provider.calls == 1
    assert service.get_theme_stocks("AI")["stocks"][0]["mainNetInflow"] == 500


def test_mapping_empty_raises_structured_error() -> None:
    service = ThemeHeatService(
        FakeRepo(empty=True),
        FakeProvider({}, source="quotes"),
        FakeFundCache({}),
        now_ms=lambda: 1782018300000,
    )

    with pytest.raises(ThemeHeatUnavailable) as caught:
        service.get_snapshot()

    assert caught.value.code == "mapping_empty"


def test_blocked_refresh_preserves_last_success_as_stale_data() -> None:
    quote_provider = FakeProvider(_quotes(), source="quotes")
    service = ThemeHeatService(
        FakeRepo(),
        quote_provider,
        FakeFundCache(_funds()),
        now_ms=lambda: 1782018300000,
    )
    first = service.get_snapshot()
    quote_provider.rows = {"000001": _quotes()["000001"]}

    with pytest.raises(ThemeHeatUnavailable) as caught:
        service.get_snapshot(force=True)

    assert caught.value.code == "quote_coverage_blocked"
    assert caught.value.stale_data is first
    assert service.get_snapshot() is first


def test_theme_stock_slice_uses_cached_rows_without_refresh() -> None:
    quote_provider = FakeProvider(_quotes(), source="quotes")
    fund_provider = FakeFundCache(_funds())
    service = ThemeHeatService(
        FakeRepo(),
        quote_provider,
        fund_provider,
        now_ms=lambda: 1782018300000,
    )
    service.get_snapshot()

    result = service.get_theme_stocks("AI", offset=0, limit=1)

    assert result["total"] == 2
    assert [row["code"] for row in result["stocks"]] == ["000001"]
    assert quote_provider.calls == 1
    assert len(fund_provider.calls) == 1


def test_snapshot_reads_available_funds_without_upstream_refresh() -> None:
    fund_provider = FakeFundCache(_funds())
    service = ThemeHeatService(
        FakeRepo(),
        FakeProvider(_quotes(), source="quotes"),
        fund_provider,
        now_ms=lambda: 1782018300000,
    )

    snapshot = service.get_snapshot()

    assert snapshot["sources"]["funds"]["returned_count"] == 2
    assert service.get_fund_rows(["000001"])["000001"]["mainNetInflow"] == 100


def test_fund_cache_reuses_the_same_ths_version_for_theme_and_market_consumers() -> None:
    service = ThemeHeatService(
        FakeRepo(),
        FakeProvider(_quotes(), source="quotes"),
        FakeFundCache(_funds()),
        now_ms=lambda: 1782018300000,
    )

    service.get_snapshot()
    theme_stock = service.get_theme_stocks("AI")["stocks"][0]
    market_row = service.get_fund_rows(["000001"])["000001"]
    assert theme_stock["mainNetInflow"] == market_row["mainNetInflow"] == 100
    assert market_row["version"] == 7
    assert market_row["moneyFlowSource"] == "ths_main_monitor"


def test_formal_snapshot_scope_excludes_runtime_ths_funds() -> None:
    service = ThemeHeatService(
        FakeRepo(),
        FakeProvider(_quotes(), source="quotes"),
        FakeFundCache(_funds()),
        now_ms=lambda: 1782018300000,
    )

    snapshot = service.get_snapshot(include_runtime_funds=False)

    assert snapshot["fundRowsByCode"] == {}
    assert snapshot["sources"]["funds"]["source"] == "formal_fund_unavailable"
    assert all(factor["fundScore"] is None for factor in snapshot["factors"])


def test_missing_cache_row_stays_missing() -> None:
    fund_provider = FakeFundCache({"000001": _funds()["000001"]})
    service = ThemeHeatService(
        FakeRepo(),
        FakeProvider(_quotes(), source="quotes"),
        fund_provider,
        now_ms=lambda: 1782018300000,
    )

    assert service.get_fund_rows(["000002"]) == {}
    assert service.get_theme_stocks("AI")["stocks"][1]["mainNetInflow"] is None


def test_factory_rejects_unconfigured_mongodb(monkeypatch) -> None:
    import backend.theme_heat_service as module

    monkeypatch.setattr(module, "_theme_heat_service", None)
    monkeypatch.setattr(module, "get_runtime_mongodb_database", lambda: None)

    with pytest.raises(ThemeHeatUnavailable) as caught:
        module.get_theme_heat_service()

    assert caught.value.code == "mapping_unavailable"
