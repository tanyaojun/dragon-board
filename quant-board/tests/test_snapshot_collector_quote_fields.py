from __future__ import annotations

from backend.snapshot_collector.builder import build_ingest_payload
from backend.snapshot_collector.models import MarketDataContext, SnapshotSlot
from backend.snapshot_collector.providers import TencentBasicQuoteProvider


def _diff_row() -> dict:
    return {
        "f12": "000001",
        "f14": "平安银行",
        "f2": 11.62,
        "f3": -0.09,
        "f6": 1060851.0,
        "f5": 1232708862.0,
        "f8": 0.55,
        "f9": 5.24,
        "f10": 0.64,
        "f20": 22549700.0,
        "f21": 22549300.0,
        "f23": 0.49,
    }


def _slot() -> SnapshotSlot:
    return SnapshotSlot("half_hour", "2026-08-03", "15:00", 1785751200000)


def test_tencent_provider_maps_full_fields() -> None:
    provider = TencentBasicQuoteProvider()
    row = provider._normalize_row(_diff_row())
    assert row["pe"] == 5.24
    assert row["pb"] == 0.49
    # f20/f21 单位为万元，落库统一为元
    assert row["totalMarketValue"] == 22549700.0 * 10000
    assert row["cirMV"] == 22549300.0 * 10000
    assert row["volumeRatio"] == 0.64


def test_builder_passes_quote_extra_fields_through() -> None:
    ctx = MarketDataContext(
        stocks=[{"code": "000001", "name": "平安银行", "rank": 1}],
        quotes=[
            {
                "code": "000001",
                "price": 11.62,
                "pctChange": -0.09,
                "volume": 1060851.0,
                "amount": 1232708862.0,
                "pe": 5.24,
                "pb": 0.49,
                "totalMarketValue": 225497000000.0,
                "cirMV": 225493000000.0,
                "limitUpPrice": 12.78,
                "limitDownPrice": 10.46,
            }
        ],
    )
    payload = build_ingest_payload(_slot(), ctx, dataset_id="dragonboard_live")
    row = payload["stockRows"][0]
    assert row["pe"] == 5.24
    assert row["pb"] == 0.49
    assert row["totalMV"] == 225497000000.0
    assert row["cirMV"] == 225493000000.0
    assert row["limitUpPrice"] == 12.78
    assert row["limitDownPrice"] == 10.46
    assert row["lastTradePrice"] == 11.62
    assert row["lastTradeVolume"] == 1060851.0


def test_builder_derives_limit_prices_from_pre_close() -> None:
    ctx = MarketDataContext(
        stocks=[{"code": "000001", "name": "平安银行", "rank": 1}],
        quotes=[
            {
                "code": "000001",
                "price": 11.62,
                "preClose": 11.63,
                "high": 11.66,
                "low": 11.52,
            }
        ],
    )
    payload = build_ingest_payload(_slot(), ctx, dataset_id="dragonboard_live")
    row = payload["stockRows"][0]
    assert row["limitUpPrice"] == round(11.63 * 1.1, 2)  # 主板 10%
    assert row["limitDownPrice"] == round(11.63 * 0.9, 2)


def test_builder_derives_gem_limit_prices_with_st_overrides() -> None:
    # 创业板 20%
    ctx = MarketDataContext(
        stocks=[{"code": "300750", "name": "宁德时代", "rank": 1}],
        quotes=[{"code": "300750", "price": 394.4, "preClose": 390.0}],
    )
    payload = build_ingest_payload(_slot(), ctx, dataset_id="dragonboard_live")
    row = payload["stockRows"][0]
    assert row["limitUpPrice"] == round(390.0 * 1.2, 2)
    # ST 5%
    ctx = MarketDataContext(
        stocks=[{"code": "000001", "name": "*ST平安", "rank": 1}],
        quotes=[{"code": "000001", "price": 5.0, "preClose": 5.0}],
    )
    payload = build_ingest_payload(_slot(), ctx, dataset_id="dragonboard_live")
    row = payload["stockRows"][0]
    assert row["limitUpPrice"] == round(5.0 * 1.05, 2)


def test_service_enriches_volume_ratios_from_golden(monkeypatch) -> None:
    from backend.snapshot_collector.service import SnapshotCollectorService

    rows = [{"code": "000001", "volume": 1060851.0}]
    service = SnapshotCollectorService(repo=object())
    monkeypatch.setattr(
        "backend.services.market.volume_ratio_service.compute_volume_ratios",
        lambda db, stocks, now=None: {
            "000001": {
                "volumeRatio": 1.23,
                "source": "intraday_snapshot",
                "status": "ok",
                "calculatedAt": 1,
            }
        },
    )
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    service._enrich_volume_ratios(rows)
    assert rows[0]["volumeRatio"] == 1.23
    assert rows[0]["volumeRatioMeta"]["source"] == "intraday_snapshot"
