from __future__ import annotations

import json
from pathlib import Path

from backend.analysis.theme_heat import compute_theme_heat


def test_compute_theme_heat_matches_v1_contract() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "theme_heat_market_golden_v1.json"
    case = json.loads(fixture_path.read_text(encoding="utf-8"))

    result = compute_theme_heat(**case["input"])

    assert result == case["expected"]


def test_fund_unavailable_is_nullable_and_reweighted() -> None:
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
    )

    factor = result["factors"][0]
    assert factor["fundScore"] is None
    assert factor["degraded"] is True
    assert "fund_flow_unavailable" in factor["qualityFlags"]
    assert factor["heatScore"] > 0


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
