from __future__ import annotations

import threading
import time
from urllib.parse import parse_qs, urlparse

from backend.settings import Settings
from backend.snapshot_collector.models import SourceHealth
from backend.snapshot_collector.providers import EastmoneyFundFlowProvider, TencentBasicQuoteProvider


class FakeBatchHttp:
    def __init__(self, *, fail_once_for: str = "") -> None:
        self.batch_sizes: list[int] = []
        self.calls: dict[str, int] = {}
        self.fail_once_for = fail_once_for
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, url: str, timeout_s: float) -> dict:
        del timeout_s
        codes = parse_qs(urlparse(url).query)["codes"][0].split(",")
        key = codes[0]
        with self._lock:
            self.batch_sizes.append(len(codes))
            self.calls[key] = self.calls.get(key, 0) + 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.005)
            if key == self.fail_once_for and self.calls[key] == 1:
                raise OSError("temporary upstream failure")
            return {
                "data": {
                    "diff": [
                        {
                            "f12": code,
                            "f14": f"股票{code}",
                            "f2": 10,
                            "f3": 2,
                            "f5": 1000,
                            "f6": 2000,
                            "f8": 3,
                            "f10": 1.2,
                            "f62": 100,
                            "f66": 40,
                            "f69": 10,
                            "f184": 5,
                        }
                        for code in codes
                    ]
                }
            }
        finally:
            with self._lock:
                self.active -= 1


def test_tencent_provider_batches_and_keeps_only_basic_fields(monkeypatch) -> None:
    fake_http = FakeBatchHttp()
    monkeypatch.setattr("backend.snapshot_collector.providers._http_get_json", fake_http)
    provider = TencentBasicQuoteProvider("http://127.0.0.1:3000", batch_size=50, max_concurrency=3)

    rows, health = provider.collect([f"{index:06d}" for index in range(120)])

    assert sorted(fake_http.batch_sizes) == [20, 50, 50]
    assert fake_http.max_active <= 3
    assert health.requested_count == 120
    assert health.returned_count == 120
    assert set(rows["000001"]) == {
        "code",
        "name",
        "price",
        "change",
        "volume",
        "amount",
        "turnoverRate",
        "volumeRatio",
    }


def test_eastmoney_provider_discards_basic_quote_fields(monkeypatch) -> None:
    fake_http = FakeBatchHttp()
    monkeypatch.setattr("backend.snapshot_collector.providers._http_get_json", fake_http)
    provider = EastmoneyFundFlowProvider("http://127.0.0.1:3000", batch_size=50, max_concurrency=3)

    rows, health = provider.collect(["000001"])

    assert health.ok is True
    assert set(rows["000001"]) == {
        "code",
        "mainNetInflow",
        "superLargeNetInflow",
        "superLargeNetRatio",
        "mainNetRatio",
    }


def test_failed_batch_is_retried_once(monkeypatch) -> None:
    fake_http = FakeBatchHttp(fail_once_for="000000")
    monkeypatch.setattr("backend.snapshot_collector.providers._http_get_json", fake_http)
    provider = TencentBasicQuoteProvider(
        "http://127.0.0.1:3000",
        batch_size=50,
        max_concurrency=3,
        failed_batch_retries=1,
    )

    rows, health = provider.collect([f"{index:06d}" for index in range(60)])

    assert len(rows) == 60
    assert fake_http.calls["000000"] == 2
    assert health.failed_batches == []


def test_source_health_extended_fields_keep_old_construction_compatible() -> None:
    health = SourceHealth(source="legacy", ok=True)

    assert health.requested_count == 0
    assert health.returned_count == 0
    assert health.coverage_ratio == 0.0
    assert health.failed_batches == []
    assert health.stale is False


def test_theme_heat_settings_read_and_clamp_environment(monkeypatch) -> None:
    monkeypatch.setenv("QUANT_BOARD_THEME_HEAT_BATCH_SIZE", "0")
    monkeypatch.setenv("QUANT_BOARD_THEME_HEAT_MAX_CONCURRENCY", "2")
    monkeypatch.setenv("QUANT_BOARD_THEME_HEAT_CACHE_TTL_SECONDS", "60")
    monkeypatch.setenv("QUANT_BOARD_THEME_HEAT_FAILED_BATCH_RETRIES", "0")
    monkeypatch.setenv("QUANT_BOARD_THEME_HEAT_QUOTE_TIMEOUT_MS", "20")
    monkeypatch.setenv("QUANT_BOARD_THEME_HEAT_FUND_TIMEOUT_MS", "30")

    settings = Settings()

    assert settings.theme_heat_batch_size == 1
    assert settings.theme_heat_max_concurrency == 2
    assert settings.theme_heat_cache_ttl_seconds == 60
    assert settings.theme_heat_failed_batch_retries == 1
    assert settings.theme_heat_quote_timeout_ms == 100
    assert settings.theme_heat_fund_timeout_ms == 100
