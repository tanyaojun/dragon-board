from __future__ import annotations

import json
from pathlib import Path

from backend.analysis.theme.heat import FACTOR_VERSION, compute_theme_heat


def test_compute_theme_heat_matches_v2_contract() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "theme_heat_market_golden_v2.json"
    case = json.loads(fixture_path.read_text(encoding="utf-8"))

    result = compute_theme_heat(**case["input"])

    assert result == case["expected"]


def test_factor_version_is_theme_market_v2() -> None:
    """热度口径切换为 KPL 人气总和（tck2.js 口径），版本号必须升级防止新旧数据混淆。"""
    assert FACTOR_VERSION == "theme-market-v2"


def test_heat_score_equals_kpl_hotness_sum() -> None:
    """heatScore = 题材成分股 KPL 人气值总和（tck2.js fetchThemeData 口径）。"""
    result = compute_theme_heat(
        themes=[{"id": "AI", "name": "人工智能", "stocks": ["000001", "000002"]}],
        quotes={
            "000001": {"code": "000001", "change": 6, "amount": 100000000, "volumeRatio": 2},
            "000002": {"code": "000002", "change": 2, "amount": 80000000, "volumeRatio": 1.5},
        },
        funds={},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
        kpl_hots={"AI": {"000001": 1200, "000002": 800}},
    )

    factor = result["factors"][0]
    assert factor["heatScore"] == 2000
    assert factor["hotnessCoveredCount"] == 2
    assert factor["rankEligible"] is True
    assert "kpl_hotness_unavailable" not in factor["qualityFlags"]


def test_kpl_missing_theme_gets_none_heat_score() -> None:
    """KPL 人气缺失保持缺失（fail-visible）：heatScore=None + 结构化标记，不伪装成 0。"""
    result = compute_theme_heat(
        themes=[{"id": "AI", "name": "人工智能", "stocks": ["000001", "000002"]}],
        quotes={
            "000001": {"code": "000001", "change": 6, "amount": 100000000, "volumeRatio": 2},
            "000002": {"code": "000002", "change": 2, "amount": 80000000, "volumeRatio": 1.5},
        },
        funds={},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
        kpl_hots={"OTHER": {"000001": 1200}},
    )

    factor = result["factors"][0]
    assert factor["heatScore"] is None
    assert factor["hotnessCoveredCount"] == 0
    assert factor["rankEligible"] is False
    assert "kpl_hotness_unavailable" in factor["qualityFlags"]


def test_kpl_empty_dict_is_real_zero_not_missing() -> None:
    """KPL 数据源可用但题材无 Hot>0 股票 → 真实零值，不标缺失。"""
    result = compute_theme_heat(
        themes=[{"id": "AI", "name": "人工智能", "stocks": ["000001", "000002"]}],
        quotes={
            "000001": {"code": "000001", "change": 6, "amount": 100000000, "volumeRatio": 2},
            "000002": {"code": "000002", "change": 2, "amount": 80000000, "volumeRatio": 1.5},
        },
        funds={},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
        kpl_hots={"AI": {}},
    )

    factor = result["factors"][0]
    assert factor["heatScore"] == 0
    assert "kpl_hotness_unavailable" not in factor["qualityFlags"]


def test_momentum_uses_hotness_change_ratio() -> None:
    """momentum 新口径：热度环比 +10% → 50 + 15 = 65（涨幅 0 贡献为 0）。"""
    result = compute_theme_heat(
        themes=[{"id": "AI", "name": "人工智能", "stocks": ["000001", "000002"]}],
        quotes={
            "000001": {"code": "000001", "change": 0, "amount": 100000000, "volumeRatio": 2},
            "000002": {"code": "000002", "change": 0, "amount": 80000000, "volumeRatio": 1.5},
        },
        funds={},
        previous_factors={"AI": {"heatScore": 2000}},
        computed_at=1782018300000,
        mapping_version="v1",
        kpl_hots={"AI": {"000001": 1320, "000002": 880}},
    )

    factor = result["factors"][0]
    assert factor["momentumScore"] == 65
    assert factor["metadata"]["hotnessChangeRatio"] == 0.1


def test_stale_zero_to_hundred_baseline_does_not_explode_momentum() -> None:
    """公式切换后上一帧可能是旧 0-100 口径残留：环比不计算，momentum 回中值 + 重置标记。"""
    result = compute_theme_heat(
        themes=[{"id": "AI", "name": "人工智能", "stocks": ["000001", "000002"]}],
        quotes={
            "000001": {"code": "000001", "change": 0, "amount": 100000000, "volumeRatio": 2},
            "000002": {"code": "000002", "change": 0, "amount": 80000000, "volumeRatio": 1.5},
        },
        funds={},
        previous_factors={"AI": {"heatScore": 88}},
        computed_at=1782018300000,
        mapping_version="v1",
        kpl_hots={"AI": {"000001": 1200, "000002": 800}},
    )

    factor = result["factors"][0]
    assert factor["momentumScore"] == 50
    assert factor["metadata"]["hotnessChangeRatio"] is None
    assert "kpl_hotness_baseline_reset" in factor["qualityFlags"]


def test_fund_unavailable_is_reported_without_hiding_subscores() -> None:
    """资金缺失：heatScore 仍来自 KPL 人气；资金子分保持缺失并打标。"""
    result = compute_theme_heat(
        themes=[{"id": "AI", "name": "人工智能", "stocks": ["000001", "000002"]}],
        quotes={
            "000001": {"code": "000001", "change": 6, "amount": 100000000, "volumeRatio": 2},
            "000002": {"code": "000002", "change": 2, "amount": 80000000, "volumeRatio": 1.5},
        },
        funds={},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
        kpl_hots={"AI": {"000001": 1200, "000002": 800}},
    )

    factor = result["factors"][0]
    assert factor["fundScore"] is None
    assert factor["degraded"] is True
    assert "fund_flow_unavailable" in factor["qualityFlags"]
    assert factor["heatScore"] == 2000


def test_partial_fund_coverage_keeps_covered_value_visible() -> None:
    codes = [f"{index:06d}" for index in range(1, 11)]
    result = compute_theme_heat(
        themes=[{"id": "AI", "name": "人工智能", "stocks": codes}],
        quotes={
            code: {"code": code, "change": 2, "amount": 1000000, "volumeRatio": 1.2}
            for code in codes
        },
        funds={"000001": {"mainNetInflow": 300000}},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
    )

    factor = result["factors"][0]
    assert factor["mainNetInflow"] == 300000
    assert factor["fundScore"] is not None
    assert "fund_flow_partial" in factor["qualityFlags"]
    assert "fund_flow_unavailable" not in factor["qualityFlags"]


def test_global_quote_coverage_below_gate_blocks_all_ranks() -> None:
    result = compute_theme_heat(
        themes=[{"id": "AI", "name": "人工智能", "stocks": ["000001", "000002"]}],
        quotes={"000001": {"code": "000001", "change": 2, "amount": 1000}},
        funds={},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
    )

    assert result["ok"] is False
    assert result["quality"]["errorCode"] == "quote_coverage_blocked"
    assert result["factors"][0]["rank"] == 0
    assert result["factors"][0]["rankEligible"] is False


def test_invalid_quote_is_reported_while_partial_snapshot_remains_rankable() -> None:
    codes = [f"{index:06d}" for index in range(1, 11)]
    quotes = {
        code: {"code": code, "change": 1, "amount": 1000, "volumeRatio": 1}
        for code in codes[:-1]
    }
    quotes[codes[-1]] = {"code": codes[-1], "change": "NaN", "amount": 1000}

    result = compute_theme_heat(
        themes=[{"id": "AI", "name": "人工智能", "stocks": codes}],
        quotes=quotes,
        funds={},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
    )

    assert result["ok"] is True
    assert result["quality"]["qualityFlags"] == ["quote_coverage_partial"]
    assert "invalid_number" in result["factors"][0]["qualityFlags"]


def test_theme_zt_count_uses_board_aware_thresholds() -> None:
    """军工板块真实场景：主板 10cm 涨停 4 家；创业/北交所大涨幅不误判为涨停。"""
    result = compute_theme_heat(
        themes=[{
            "id": "MIL",
            "name": "军工",
            "stocks": ["600967", "002265", "601606", "002300", "301357", "920006", "000519"],
        }],
        quotes={
            "600967": {"code": "600967", "name": "内蒙一机", "change": 10.01, "amount": 1000, "volumeRatio": 2},
            "002265": {"code": "002265", "name": "建设工业", "change": 10.01, "amount": 1000, "volumeRatio": 2},
            "601606": {"code": "601606", "name": "长城军工", "change": 10.00, "amount": 1000, "volumeRatio": 2},
            "002300": {"code": "002300", "name": "太阳电缆", "change": 9.94, "amount": 1000, "volumeRatio": 2},
            "301357": {"code": "301357", "name": "北方长龙", "change": 15.19, "amount": 1000, "volumeRatio": 2},
            "920006": {"code": "920006", "name": "晟楠科技", "change": 19.54, "amount": 1000, "volumeRatio": 2},
            "000519": {"code": "000519", "name": "中兵红箭", "change": 4.64, "amount": 1000, "volumeRatio": 2},
        },
        funds={},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
    )

    assert result["factors"][0]["ztCount"] == 4


def test_gem_star_bse_high_gains_count_as_limit_up_at_own_thresholds() -> None:
    """创业板/科创板 20cm、北交所 30cm 达到各自阈值时计入涨停。"""
    result = compute_theme_heat(
        themes=[{
            "id": "HIGH",
            "name": "高波动画材",
            "stocks": ["920043", "300875", "688543", "689009"],
        }],
        quotes={
            "920043": {"code": "920043", "change": 29.5, "amount": 1000, "volumeRatio": 2},
            "300875": {"code": "300875", "change": 19.5, "amount": 1000, "volumeRatio": 2},
            "688543": {"code": "688543", "change": 19.5, "amount": 1000, "volumeRatio": 2},
            "689009": {"code": "689009", "change": 10.0, "amount": 1000, "volumeRatio": 2},
        },
        funds={},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
    )

    assert result["factors"][0]["ztCount"] == 3


def test_main_board_st_uses_main_board_threshold_since_rule_change() -> None:
    """2026-09 规则：主板 ST 涨跌幅 ±10%，与主板一致，不再按 ±5% 特判。"""
    result = compute_theme_heat(
        themes=[{"id": "ST", "name": "ST样本", "stocks": ["600001", "000010"]}],
        quotes={
            "600001": {"code": "600001", "name": "ST测试", "change": 4.6, "amount": 1000, "volumeRatio": 1},
            "000010": {"code": "000010", "name": "*ST测试", "change": 9.4, "amount": 1000, "volumeRatio": 1},
        },
        funds={},
        previous_factors={},
        computed_at=1782018300000,
        mapping_version="v1",
    )

    assert result["factors"][0]["ztCount"] == 1
