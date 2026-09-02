from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.services.theme.heat_service import ThemeHeatService, ThemeHeatUnavailable


class FakeRepository:
    def __init__(self, *, empty: bool = False) -> None:
        self.empty = empty

    def get_market_universe(self) -> dict:
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
            "themes": [
                {"id": "AI", "name": "人工智能"},
                {"id": "POWER", "name": "电力"},
            ],
            "stockCodes": ["000001", "000002", "000003", "000004"],
            "themeStocks": {
                "AI": ["000001", "000002"],
                "POWER": ["000003", "000004"],
            },
            "stockThemes": {"000001": ["AI"], "000002": ["AI"]},
        }


class FakeQuoteProvider:
    def __init__(self, rows: dict | None = None, *, source: str = "quotes", delay: float = 0) -> None:
        self.rows = rows if rows is not None else _quotes()
        self.source = source
        self.delay = delay
        self.calls = 0

    def collect(self, codes, *, timeout_ms: int):
        import time

        self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        rows = {code: self.rows[code] for code in codes if code in self.rows}
        return rows, {"ok": True, "requested": len(codes), "returned": len(rows)}


class FakeFundCache:
    def __init__(self, rows: dict | None = None, *, version: int = 7) -> None:
        self.rows = rows if rows is not None else _funds()
        self.version = version
        self.calls: list[list[str]] = []

    def current_version(self) -> int:
        return self.version

    def get_akshare_latest(self, codes):
        self.calls.append(list(codes))
        return {code: self.rows[code] for code in codes if code in self.rows}


class FakeKplCache:
    def __init__(self, hots: dict | None = None) -> None:
        self._hots = hots or {}
        self.requested_ids: list[str] | None = None

    def get_theme_hots(self, theme_ids):
        self.requested_ids = list(theme_ids)
        return self._hots

    def get_health(self) -> dict:
        return {"cachedThemeCount": len(self._hots), "lastResult": {"ok": True}}


class BrokenKplCache:
    """模拟缓存内部异常：读路径不应炸掉整个 heat 快照（fail-visible 降级）。"""

    def get_theme_hots(self, theme_ids):
        raise RuntimeError("cache corrupted")

    def get_health(self) -> dict:
        raise RuntimeError("cache corrupted")


def _quotes() -> dict[str, dict]:
    return {
        "000001": {"code": "000001", "name": "样本一", "price": 10, "change": 6, "amount": 1000, "volumeRatio": 2},
        "000002": {"code": "000002", "name": "样本二", "price": 9, "change": 2, "amount": 800, "volumeRatio": 1.5},
        "000003": {"code": "000003", "name": "样本三", "price": 8, "change": -2, "amount": 600, "volumeRatio": 1.2},
        "000004": {"code": "000004", "name": "样本四", "price": 7, "change": 1, "amount": 500, "volumeRatio": 1.1},
    }


def _funds() -> dict[str, dict]:
    def _row(code: str, zlje: int) -> dict:
        return {
            "code": code, "zlje": zlje, "version": 7,
            "moneyFlowSource": "ths_main_monitor", "sessionDate": "2026-07-24",
        }

    return {
        "000001": _row("000001", 100),
        "000002": _row("000002", -20),
        "000003": _row("000003", 30),
        "000004": _row("000004", 5),
    }


def _build_service(kpl_cache) -> ThemeHeatService:
    return ThemeHeatService(
        FakeRepository(),
        FakeQuoteProvider(),
        FakeFundCache(),
        kpl_cache=kpl_cache,
        now_ms=lambda: 1782018300000,
        cache_ttl_seconds=300,
    )


# ── theme-market-v2：KPL 人气总和口径（2026-09 迁移新增） ──

def test_refresh_computes_heat_score_from_kpl_cache() -> None:
    """heat_service 把 KPL 人气缓存传入热度计算：heatScore = 人气总和。"""
    service = _build_service(FakeKplCache({"AI": {"000001": 1200, "000002": 800}}))

    snapshot = service.get_snapshot()

    factor_ai = next(factor for factor in snapshot["factors"] if factor["themeId"] == "AI")
    assert factor_ai["heatScore"] == 2000
    assert factor_ai["rankEligible"] is True
    assert service._kpl_cache.requested_ids == ["AI", "POWER"]


def test_refresh_exposes_kpl_health_in_sources() -> None:
    service = _build_service(FakeKplCache({"AI": {"000001": 1200}}))

    snapshot = service.get_snapshot()

    assert "kplHotness" in snapshot["sources"]
    assert snapshot["sources"]["kplHotness"]["cachedThemeCount"] == 1


def test_refresh_without_kpl_data_keeps_snapshot_visible_with_flags() -> None:
    """KPL 缓存未预热/为空：热度缺失打标（fail-visible），行情侧因子照常返回。"""
    service = _build_service(FakeKplCache({}))

    snapshot = service.get_snapshot()

    assert snapshot["ok"] is True  # 行情覆盖正常，KPL 缺失不阻断整个快照
    for factor in snapshot["factors"]:
        assert factor["heatScore"] is None
        assert factor["rankEligible"] is False
        assert "kpl_hotness_unavailable" in factor["qualityFlags"]
    assert snapshot["quality"]["kplHotnessCoverage"] == 0.0


def test_refresh_survives_kpl_cache_error() -> None:
    """KPL 缓存读路径异常不炸整个 heat 快照：降级为缺失 + sources 结构化标注。"""
    service = _build_service(BrokenKplCache())

    snapshot = service.get_snapshot()

    assert snapshot["ok"] is True
    for factor in snapshot["factors"]:
        assert factor["heatScore"] is None
        assert "kpl_hotness_unavailable" in factor["qualityFlags"]
    kpl_health = snapshot["sources"]["kplHotness"]
    assert kpl_health["available"] is False
    assert "kpl_cache_error" in str(kpl_health.get("reason") or "")


# ── 服务级核心行为（2026-09 审计 M4 恢复：并发合并/版本失效/降级/缓存/scope） ──

def test_service_coalesces_same_bucket_refreshes() -> None:
    quote_provider = FakeQuoteProvider(delay=0.02)
    fund_cache = FakeFundCache()
    service = ThemeHeatService(
        FakeRepository(),
        quote_provider,
        fund_cache,
        now_ms=lambda: 1782018300000,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(service.get_snapshot)
        second_future = pool.submit(service.get_snapshot)
        first = first_future.result()
        second = second_future.result()

    assert first is second
    assert quote_provider.calls == 1
    assert len(fund_cache.calls) == 1


def test_fund_version_change_invalidates_same_bucket_snapshot() -> None:
    fund_cache = FakeFundCache()
    service = ThemeHeatService(
        FakeRepository(),
        FakeQuoteProvider(),
        fund_cache,
        now_ms=lambda: 1782018300000,
    )

    first = service.get_snapshot()
    fund_cache.rows["000001"] = {**fund_cache.rows["000001"], "zlje": 500, "version": 8}
    fund_cache.version = 8
    second = service.get_snapshot()

    assert second is not first
    assert service.get_theme_stocks("AI")["stocks"][0]["mainNetInflow"] == 500


def test_mapping_empty_raises_structured_error() -> None:
    service = ThemeHeatService(
        FakeRepository(empty=True),
        FakeQuoteProvider({}),
        FakeFundCache({}),
        now_ms=lambda: 1782018300000,
    )

    with pytest.raises(ThemeHeatUnavailable) as caught:
        service.get_snapshot()

    assert caught.value.code == "mapping_empty"


def test_low_quote_coverage_returns_degraded_snapshot_with_quality_reason() -> None:
    quote_provider = FakeQuoteProvider()
    service = ThemeHeatService(
        FakeRepository(),
        quote_provider,
        FakeFundCache(),
        now_ms=lambda: 1782018300000,
    )
    first = service.get_snapshot()
    assert first["ok"] is True

    # 覆盖率不足不是硬门禁：返回已计算的降级因子 + 结构化质量原因（fail-visible）
    quote_provider.rows = {"000001": _quotes()["000001"]}
    degraded = service.get_snapshot(force=True)

    assert degraded["ok"] is False
    assert degraded["degraded"] is True
    assert degraded["quality"]["errorCode"] == "quote_coverage_blocked"
    assert degraded["quality"]["quoteCoverage"] < 0.85
    assert all(
        factor["rank"] == 0 and factor["rankEligible"] is False
        for factor in degraded["factors"]
    )
    # 降级快照同样进入缓存供后续读取，不退回旧数据
    assert service.get_snapshot() is degraded


def test_theme_stock_slice_uses_cached_rows_without_refresh() -> None:
    quote_provider = FakeQuoteProvider()
    service = ThemeHeatService(
        FakeRepository(),
        quote_provider,
        FakeFundCache(),
        now_ms=lambda: 1782018300000,
    )
    service.get_snapshot()

    result = service.get_theme_stocks("AI", offset=0, limit=1)

    assert result["total"] == 2
    assert [row["code"] for row in result["stocks"]] == ["000001"]
    assert quote_provider.calls == 1


def test_snapshot_reads_available_funds_without_upstream_refresh() -> None:
    fund_cache = FakeFundCache()
    service = ThemeHeatService(
        FakeRepository(),
        FakeQuoteProvider(),
        fund_cache,
        now_ms=lambda: 1782018300000,
    )

    snapshot = service.get_snapshot()

    assert snapshot["sources"]["funds"]["returned_count"] == 4
    assert fund_cache.calls == [["000001", "000002", "000003", "000004"]]
    assert service.get_fund_rows(["000001"])["000001"]["mainNetInflow"] == 100


def test_fund_cache_reuses_the_same_ths_version_for_theme_and_market_consumers() -> None:
    service = ThemeHeatService(
        FakeRepository(),
        FakeQuoteProvider(),
        FakeFundCache(),
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
        FakeRepository(),
        FakeQuoteProvider(),
        FakeFundCache(),
        now_ms=lambda: 1782018300000,
    )

    snapshot = service.get_snapshot(include_runtime_funds=False)

    assert snapshot["fundRowsByCode"] == {}
    assert snapshot["sources"]["funds"]["source"] == "formal_fund_unavailable"
    assert all(factor["fundScore"] is None for factor in snapshot["factors"])


def test_missing_cache_row_stays_missing() -> None:
    fund_cache = FakeFundCache({"000001": _funds()["000001"]})
    service = ThemeHeatService(
        FakeRepository(),
        FakeQuoteProvider(),
        fund_cache,
        now_ms=lambda: 1782018300000,
    )

    assert service.get_fund_rows(["000002"]) == {}
    assert service.get_theme_stocks("AI")["stocks"][1]["mainNetInflow"] is None


def test_factory_rejects_unconfigured_mongodb(monkeypatch) -> None:
    import backend.services.theme.heat_service as module

    monkeypatch.setattr(module, "_theme_heat_service", None)
    monkeypatch.setattr(module, "get_runtime_mongodb_database", lambda: None)

    with pytest.raises(ThemeHeatUnavailable) as caught:
        module.get_theme_heat_service()

    assert caught.value.code == "mapping_unavailable"


def test_factory_starts_kpl_cache_thread(monkeypatch) -> None:
    """工厂创建 service 时即启动 KPL 缓存后台刷新：lifespan 启动失败后，
    首次请求重建服务也能自愈（2026-09 审计 M2）。"""
    import backend.services.theme.heat_service as module

    class StubKplCache:
        def __init__(self, *args, **kwargs) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

    created: list[StubKplCache] = []

    def fake_cache_factory(*args, **kwargs) -> StubKplCache:
        cache = StubKplCache(*args, **kwargs)
        created.append(cache)
        return cache

    monkeypatch.setattr(module, "_theme_heat_service", None)
    monkeypatch.setattr(module, "get_runtime_mongodb_database", lambda: object())
    monkeypatch.setattr(module, "MongoThemeRepository", lambda db: object())
    monkeypatch.setattr(module, "TencentBasicQuoteProvider", lambda *a, **k: object())
    monkeypatch.setattr(module, "get_theme_fund_cache", lambda: object())
    monkeypatch.setattr(module, "KplHotnessCache", fake_cache_factory)

    try:
        service = module.get_theme_heat_service()
        assert created and created[0].started is True
        assert service.kpl_cache is created[0]
    finally:
        module._theme_heat_service = None
