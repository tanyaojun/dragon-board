from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.hotlist.sentiment import (
    build_comparison,
    build_layer_metrics,
    build_limit_evidence,
    build_yesterday_strong_performance,
    check_limit_status,
    compute_turnover,
    resolve_stock_status,
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


def test_golden_limit_intersection_board_thresholds():
    case = get_case(load_golden_cases(), "按A股板块阈值统计热榜涨停和近涨停证据")
    rows = sort_rows(case["input"]["stocks"])
    evidence = build_limit_evidence(rows, [], case["input"].get("topN"), None)
    expected = case["expected"]["metrics"]["limitEvidence"]
    assert evidence["intersection"]["top100LimitUpCount"] == expected["intersection"]["top100LimitUpCount"] == 2
    assert evidence["intersection"]["top100NearLimitUpCount"] == expected["intersection"]["top100NearLimitUpCount"] == 3


def test_golden_market_evidence_passthrough():
    case = get_case(load_golden_cases(), "热榜涨停证据只使用热榜交集，全市场数据仅作为背景")
    rows = sort_rows(case["input"]["stocks"])
    evidence = build_limit_evidence(rows, [], None, case["input"]["marketData"])
    assert evidence["market"]["ztCount"] == 98
    assert evidence["market"]["zhabanCount"] == 24
    assert evidence["intersection"]["top100LimitUpCount"] == 4


def test_golden_ths_pools_evidence():
    case = get_case(load_golden_cases(), "THS炸板池和涨停股回撤榜只作为全市场补充证据")
    rows = sort_rows(case["input"]["stocks"])
    evidence = build_limit_evidence(rows, [], None, case["input"]["marketData"])
    assert evidence["market"]["thsPools"]["failedCount"] == 11
    assert evidence["market"]["thsPools"]["drawdownCount"] == 7
    assert evidence["market"]["thsPools"]["drawdownRiskLabel"] == "涨停股回撤榜"


def test_golden_yesterday_hot_limit():
    case = get_case(load_golden_cases(), "昨日热榜涨停今日表现纳入持续性证据")
    today = sort_rows(case["input"]["stocks"])
    yesterday = sort_rows(case["input"]["yesterday"]["hotlist"])
    evidence = build_limit_evidence(today, yesterday, None, None)
    expected = case["expected"]["metrics"]["limitEvidence"]["yesterdayHotLimit"]
    result = evidence["yesterdayHotLimit"]
    assert result["count"] == expected["count"] == 6
    assert result["retainedTop100Count"] == 6
    assert result["positiveRate"] == pytest.approx(expected["positiveRate"])
    assert result["failedOrWeakRate"] >= 0.5


def test_golden_yesterday_strong_performance():
    case = get_case(load_golden_cases(), "统计昨日强票今日平均涨幅、正收益率和转弱率")
    today = sort_rows(case["input"]["stocks"])
    yesterday = sort_rows(case["input"]["yesterday"]["hotlist"])
    result = build_yesterday_strong_performance(yesterday, today, None)
    assert result["count"] == 10
    assert result["matchedCount"] == 10
    assert result["positiveRate"] == pytest.approx(0.6)
    assert result["weakeningRate"] == pytest.approx(0.4)
    assert result["avgChange"] == pytest.approx(0)


def test_golden_comparison_three_day():
    case = get_case(load_golden_cases(), "热榜收缩且机会少时识别为冰点")
    yesterday_rows = case["input"]["yesterday"]["hotlist"]
    day_before_rows = case["input"]["dayBefore"]["hotlist"]
    comparison = build_comparison(case["input"]["stocks"], yesterday_rows, day_before_rows, None)
    assert comparison["totalChange1d"] == case["expected"]["metrics"]["comparison"]["totalChange1d"] < 0
    assert comparison["totalChange2d"] == case["expected"]["metrics"]["comparison"]["totalChange2d"] < 0


def test_display_status_preferred_over_fallback():
    row = {"code": "000001", "change": 5, "displayStatusLabel": "资金背离"}
    source = {"displayStatus": 0, "fallback": 0}
    assert resolve_stock_status(row, [row], source) == "资金背离"
    assert source == {"displayStatus": 1, "fallback": 0}


def test_display_status_fallback_when_missing():
    row = {"code": "000001", "change": 5}
    source = {"displayStatus": 0, "fallback": 0}
    assert resolve_stock_status(row, [row], source) == "新入观察"
    assert source == {"displayStatus": 0, "fallback": 1}


def test_display_status_invalid_label_falls_back():
    row = {"code": "000001", "change": 5, "displayStatusLabel": "无效标签"}
    assert resolve_stock_status(row, [row]) == "新入观察"
