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


def test_main_theme_resolves_by_day_strength_not_list_order() -> None:
    """主题材判定（治理 P2 2026-10-25）：跟强不跟弱。

    大业股份案例基准：themes 列表「轮胎」在前（mappings themeId 字符串序），
    但当日人形机器人 zt=16 完胜轮胎 zt=1 → mainTheme 必须判人形机器人；
    旧 themes[0] 口径判「轮胎」即本立项根因。
    """
    from backend.services.theme.dict_governance import GovernanceSpec

    fact = _fact_no_pre_close_with_theme()
    fact.stocks = [{
        "code": "603278", "name": "大业股份", "rank": 1,
        "price": 15.0, "pctChange": 10.0,
    }]
    fact.themes = {"603278": ["轮胎", "商业航天", "电力", "人形机器人"]}
    fact.sectors = [
        {"entityType": "hot_theme", "entityName": "轮胎",
         "ztCount": 1, "heatScore": 44367.0, "rank": 79},
        {"entityType": "hot_theme", "entityName": "人形机器人",
         "ztCount": 16, "heatScore": 272276.0, "rank": 2},
    ]
    gov = GovernanceSpec({
        "familyLinks": [{"parent": "人形机器人", "child": "宇树机器人"}],
        "excludeThemeNames": ["中证A50成分股"],
    })
    bundle = SnapshotDerivationService().derive(fact, theme_governance=gov)
    row = bundle.stock_rows[0]
    assert row["mainTheme"] == "人形机器人"
    assert row["sectorLabel"] == "人形机器人"
    assert "ztCount=16" in row["mainThemeBasis"]


def test_main_theme_none_when_no_sector_strength() -> None:
    """强度全缺（如非 sector 帧）：mainTheme=None + basis 标注，不回退 themes[0]。"""
    fact = _fact_no_pre_close_with_theme()
    fact.sectors = []
    fact.themes = {"000001": ["银行"]}
    bundle = SnapshotDerivationService().derive(fact)
    row = bundle.stock_rows[0]
    assert row.get("mainTheme") is None
    assert row["mainThemeBasis"] == "sector_strength_missing"


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


def test_limit_prices_main_board_st_follows_main_board_ratio_since_rule_change() -> None:
    """2026-09 起主板 ST 涨跌幅 ±10%，涨停/跌停价不再按 5% 派生。"""
    fact = _fact()
    fact.stocks = [
        {
            "code": "600001",
            "name": "ST测试",
            "rank": 1,
            "preClose": 10.0,
            "price": 10.5,
            "pctChange": 5.0,
        }
    ]
    bundle = SnapshotDerivationService().derive(fact)
    row = bundle.stock_rows[0]
    assert row["limitUpPrice"] == 11.0
    assert row["limitDownPrice"] == 9.0


def test_limit_prices_follow_board_aware_ratios() -> None:
    """创业板/科创板 ±20%、北交所 ±30%、主板 ±10%，与前端 StockUtils 口径一致。"""
    fact = _fact()
    fact.stocks = [
        {"code": "300001", "name": "创业板股", "rank": 1, "preClose": 10.0, "price": 10.5},
        {"code": "302001", "name": "创业板股B", "rank": 2, "preClose": 10.0, "price": 10.5},
        {"code": "688001", "name": "科创板股", "rank": 3, "preClose": 10.0, "price": 10.5},
        {"code": "689009", "name": "科创板CDR", "rank": 4, "preClose": 10.0, "price": 10.5},
        {"code": "430001", "name": "北交所股", "rank": 5, "preClose": 10.0, "price": 10.5},
        {"code": "830001", "name": "北交所股B", "rank": 6, "preClose": 10.0, "price": 10.5},
        {"code": "920001", "name": "北交所股C", "rank": 7, "preClose": 10.0, "price": 10.5},
        {"code": "600001", "name": "主板股", "rank": 8, "preClose": 10.0, "price": 10.5},
    ]
    bundle = SnapshotDerivationService().derive(fact)
    by_code = {row["code"]: row for row in bundle.stock_rows}

    for code in ("300001", "302001", "688001", "689009"):
        assert by_code[code]["limitUpPrice"] == 12.0
        assert by_code[code]["limitDownPrice"] == 8.0
    for code in ("430001", "830001", "920001"):
        assert by_code[code]["limitUpPrice"] == 13.0
        assert by_code[code]["limitDownPrice"] == 7.0
    assert by_code["600001"]["limitUpPrice"] == 11.0
    assert by_code["600001"]["limitDownPrice"] == 9.0


# ── heatLevel 落库迁移（2026-09 design B7）：stock row themeHeat 改相对分口径 ──

def test_stock_theme_heat_consumes_sector_heat_level_and_caliber() -> None:
    """collector 新行：stock row themeHeat 吃 sector heatLevel 相对分（不再落绝对值）。"""
    fact = _fact_no_pre_close_with_theme()
    fact.sectors[0]["heatScore"] = 2000.0
    fact.sectors[0]["heatLevel"] = 96.3
    fact.sectors[0]["metadata"] = {"factorVersion": "theme-market-v2"}
    bundle = SnapshotDerivationService().derive(fact)
    assert bundle.stock_rows[0]["themeHeat"] == 96.3


def test_stock_theme_heat_v2_sector_without_heat_level_stays_missing() -> None:
    """v2 标记 sector 行无 heatLevel key：≤100 绝对值不回退，themeHeat 保持缺失。"""
    fact = _fact_no_pre_close_with_theme()
    fact.sectors[0]["heatScore"] = 85.0
    fact.sectors[0]["metadata"] = {"factorVersion": "theme-market-v2"}
    bundle = SnapshotDerivationService().derive(fact)
    assert "themeHeat" not in bundle.stock_rows[0]
