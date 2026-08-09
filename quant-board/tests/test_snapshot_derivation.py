from __future__ import annotations

from backend.snapshot_collector.models import SourceHealth
from backend.snapshot_derivation import SnapshotDerivationService
from backend.snapshot_derivation.models import MarketFactBundle


def _fact(snapshot_type: str = "half_hour") -> MarketFactBundle:
    return MarketFactBundle(
        snapshot_type=snapshot_type,
        trading_date="2026-08-04",
        slot_time="15:30",
        timestamp_ms=1785835800000,
        dataset_id="dragonboard_live",
        capture_mode="real_time",
        stocks=[
            {
                "code": "000001",
                "name": "平安银行",
                "rank": 1,
                "preClose": 10.0,
                "price": 10.5,
                "volume": 1000,
                "pctChange": 5.0,
            }
        ],
        source_health=[SourceHealth(source="startup_bundle", ok=True, row_count=1)],
        quality_issues=[{"code": "demo", "detail": "ok"}],
    )


def test_derive_produces_full_bundle() -> None:
    bundle = SnapshotDerivationService().derive(_fact())

    assert len(bundle.records) == 1
    assert len(bundle.frames) == 1
    assert len(bundle.stock_rows) == 1
    assert bundle.stock_rows[0]["code"] == "000001"
    assert bundle.records[0]["snapshotId"] == "half_hour:2026-08-04:15:30"


def test_derive_attaches_derivation_metadata() -> None:
    bundle = SnapshotDerivationService().derive(_fact())
    derivation = bundle.frames[0]["metadata"]["derivation"]

    assert derivation["algorithmVersion"] == "snapshot_derivation_v1"
    assert derivation["configHash"] == "snapshot_derivation_v1_default"
    assert derivation["inputEvidence"]["stocks"] == 1
    assert derivation["inputEvidence"]["sourceHealth"] == 1
    assert derivation["derivedAt"]
    assert derivation["qualityIssues"] == [{"code": "demo", "detail": "ok"}]


def test_same_fact_derives_per_type_without_shared_mutation() -> None:
    service = SnapshotDerivationService()
    half = service.derive(_fact("half_hour"))
    daily = service.derive(_fact("daily"))

    assert half.records[0]["snapshotId"] == "half_hour:2026-08-04:15:30"
    assert daily.records[0]["snapshotId"] == "daily:2026-08-04:15:30"
    assert half.frames[0]["type"] == "half_hour"
    assert daily.frames[0]["type"] == "daily"


def _fact_no_pre_close_with_theme() -> MarketFactBundle:
    return MarketFactBundle(
        snapshot_type="half_hour",
        trading_date="2026-08-04",
        slot_time="15:30",
        timestamp_ms=1785835800000,
        dataset_id="dragonboard_live",
        stocks=[
            {
                "code": "000001",
                "name": "平安银行",
                "rank": 1,
                "price": 10.5,
                "pctChange": 5.0,
            }
        ],
        themes={"000001": ["银行"]},
        sectors=[
            {
                "entityType": "hot_theme",
                "entityName": "银行",
                "heatScore": 80.0,
                "crowdingRisk": 75.0,
            }
        ],
    )


def test_pre_close_derived_from_price_and_change() -> None:
    bundle = SnapshotDerivationService().derive(_fact_no_pre_close_with_theme())
    row = bundle.stock_rows[0]
    assert row["preClose"] == round(10.5 / (1 + 5.0 / 100), 4)
    assert row["limitUpPrice"] == round(row["preClose"] * 1.1, 2)


def test_theme_heat_and_risk_flags_derived_from_sector() -> None:
    bundle = SnapshotDerivationService().derive(_fact_no_pre_close_with_theme())
    row = bundle.stock_rows[0]
    assert row["mainTheme"] == "银行"
    assert row["themeHeat"] == 80.0
    assert row["themeRiskFlags"] == ["题材拥挤风险高"]


def test_high_low_price_aliases_from_quote() -> None:
    fact = _fact_no_pre_close_with_theme()
    fact.quotes = [
        {
            "code": "000001",
            "price": 10.5,
            "pctChange": 5.0,
            "high": 10.8,
            "low": 10.2,
            "preClose": 10.0,
        }
    ]
    bundle = SnapshotDerivationService().derive(fact)
    row = bundle.stock_rows[0]
    assert row["highPrice"] == 10.8
    assert row["lowPrice"] == 10.2


def test_lead_status_marked_limit_up_when_price_hits_limit() -> None:
    fact = _fact_no_pre_close_with_theme()
    fact.stocks = [
        {
            "code": "000001",
            "name": "平安银行",
            "rank": 1,
            "price": 11.0,
            "pctChange": 10.0,
            "preClose": 10.0,
        }
    ]
    bundle = SnapshotDerivationService().derive(fact)
    row = bundle.stock_rows[0]
    assert row["limitUpPrice"] == 11.0
    assert row["leadStatus"] == "涨停"


def test_quote_fills_speed_from_bridge() -> None:
    fact = _fact()
    fact.quotes = [
        {
            "code": "000001",
            "price": 10.5,
            "pctChange": 5.0,
            "speed": 1.23,
        }
    ]
    bundle = SnapshotDerivationService().derive(fact)
    row = bundle.stock_rows[0]
    # 涨速由 python-bridge 计算，stock row 缺失时从 quote 填补
    assert row["speed"] == 1.23


def test_quote_volume_ratio_meta_passthrough() -> None:
    fact = _fact()
    fact.quotes = [
        {
            "code": "000001",
            "price": 10.5,
            "pctChange": 5.0,
            "volumeRatio": 1.8,
            "volumeRatioMeta": {"source": "tencent_f10", "status": "available"},
        }
    ]
    bundle = SnapshotDerivationService().derive(fact)
    row = bundle.stock_rows[0]
    # 腾讯 f10 兜底值连同来源标记一起透传（golden 三日口径覆盖前可见）
    assert row["volumeRatio"] == 1.8
    assert row["volumeRatioMeta"]["source"] == "tencent_f10"


def test_quote_volume_ratio_stamps_tencent_f10_meta_when_missing() -> None:
    fact = _fact()
    fact.quotes = [
        {
            "code": "000001",
            "price": 10.5,
            "pctChange": 5.0,
            "volumeRatio": 2.2,
        }
    ]
    bundle = SnapshotDerivationService().derive(fact)
    row = bundle.stock_rows[0]
    # quote 层无来源标记时，派生层补 tencent_f10 兜底标记（golden 三日覆盖前可见）
    assert row["volumeRatio"] == 2.2
    assert row["volumeRatioMeta"]["source"] == "tencent_f10"
