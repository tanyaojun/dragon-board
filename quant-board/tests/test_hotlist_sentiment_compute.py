from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.hotlist.sentiment import (
    build_layer_metrics,
    check_limit_status,
    compute_turnover,
    sort_rows,
)

FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "hotlist_sentiment" / "golden_cases.json"


def load_golden_cases() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def get_case(cases: dict, name: str) -> dict:
    for case in cases["cases"]:
        if case["name"] == name:
            return case
    raise AssertionError(f"golden case 不存在: {name}")


def test_golden_all_pool_layer():
    case = get_case(load_golden_cases(), "输出全池 all 分层统计")
    rows = case["input"]["stocks"]
    layers = build_layer_metrics(rows)
    expected = case["expected"]["metrics"]["layers"]
    assert layers["all"]["topN"] == expected["all"]["topN"] == 120
    assert layers["all"]["upCount"] == 100
    assert layers["all"]["downCount"] == 20
    assert layers["all"]["upRatio"] == pytest.approx(expected["all"]["upRatio"])


def test_golden_layer_top20_50_100():
    case = get_case(load_golden_cases(), "输出前20、前50、前100分层统计")
    layers = build_layer_metrics(case["input"]["stocks"])
    expected = case["expected"]["metrics"]["layers"]
    assert layers["top20"]["topN"] == 20
    assert layers["top50"]["topN"] == 50
    assert layers["top100"]["topN"] == 100
    assert layers["top20"]["upRatio"] > layers["top100"]["upRatio"]
    assert layers["top20"]["activeOpportunityCount"] > 0
    assert layers["top20"]["statusCounts"] == expected["top20"]["statusCounts"]


def test_golden_turnover_details():
    case = get_case(load_golden_cases(), "统计热榜股票池每日进出明细")
    result = compute_turnover(case["input"]["todayStocks"], case["input"]["yesterdayStocks"])
    assert result == case["expected"]


def test_golden_limit_threshold_by_board():
    # 对应 TS case「按A股板块阈值统计热榜涨停和近涨停证据」的判定基线：
    # 主板 ST（*ST测试 4.9%）按 ±10% 判定，不计入涨停/近涨停
    assert check_limit_status(9.9, "600001")["isLimitUp"] is True
    assert check_limit_status(19.8, "688001")["isLimitUp"] is True
    assert check_limit_status(29.0, "830001")["isLimitUp"] is False      # 北交所阈值 29.8-0.5=29.3，29.0 未达
    assert check_limit_status(29.4, "830001")["isAlmostLimitUp"] is True
    assert check_limit_status(4.9, "000001")["isLimitUp"] is False
    assert check_limit_status(8.4, "000001")["isAlmostLimitUp"] is True  # 9.8-1.5=8.3
    assert check_limit_status(8.2, "000001")["isAlmostLimitUp"] is False


def test_get_trusted_volume_ratio_branches():
    # TS: VolumeRatioTrust.ts L1-12 四分支逐一对齐
    from backend.analysis.hotlist.sentiment import get_trusted_volume_ratio

    assert get_trusted_volume_ratio({"volumeRatio": 3.2}) == 3.2                                   # 无 meta → 原值直通
    assert get_trusted_volume_ratio({"volumeRatio": 3.2, "volumeRatioMeta": {"status": "fresh"}}) == 3.2
    assert get_trusted_volume_ratio({"volumeRatio": 3.2, "volumeRatioMeta": {"status": "suspicious"}}) == 0.0
    assert get_trusted_volume_ratio({"volumeRatio": 0}) == 0.0                                     # value<=0 → 0
    assert get_trusted_volume_ratio({"volumeRatio": "abc"}) == 0.0                                 # 非有限 → 0
