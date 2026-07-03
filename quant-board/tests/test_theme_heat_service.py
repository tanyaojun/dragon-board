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

    def collect(self, codes: list[str], *, timeout_ms: int) -> tuple[dict[str, dict], SourceHealth]:
        del timeout_ms
        self.calls += 1
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


def _quotes() -> dict[str, dict]:
    return {
        "000001": {"code": "000001", "name": "样本一", "price": 10, "change": 6, "amount": 1000, "volumeRatio": 2},
        "000002": {"code": "000002", "name": "样本二", "price": 9, "change": 2, "amount": 800, "volumeRatio": 1.5},
    }


def _funds() -> dict[str, dict]:
    return {
        "000001": {"code": "000001", "mainNetInflow": 100},
        "000002": {"code": "000002", "mainNetInflow": -20},
    }


def test_service_coalesces_same_bucket_refreshes() -> None:
    quote_provider = FakeProvider(_quotes(), source="quotes", delay=0.02)
    fund_provider = FakeProvider(_funds(), source="funds", delay=0.02)
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
    assert fund_provider.calls == 1


def test_mapping_empty_raises_structured_error() -> None:
    service = ThemeHeatService(
        FakeRepo(empty=True),
        FakeProvider({}, source="quotes"),
        FakeProvider({}, source="funds"),
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
        FakeProvider(_funds(), source="funds"),
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
    fund_provider = FakeProvider(_funds(), source="funds")
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
    assert fund_provider.calls == 1


def test_factory_rejects_unconfigured_mongodb(monkeypatch) -> None:
    import backend.theme_heat_service as module

    monkeypatch.setattr(module, "_theme_heat_service", None)
    monkeypatch.setattr(module, "get_runtime_mongodb_database", lambda: None)

    with pytest.raises(ThemeHeatUnavailable) as caught:
        module.get_theme_heat_service()

    assert caught.value.code == "mapping_unavailable"
