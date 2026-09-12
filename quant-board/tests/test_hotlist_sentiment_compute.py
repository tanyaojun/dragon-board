from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.hotlist.sentiment import (
    STAGE_KEYS,
    build_comparison,
    build_layer_metrics,
    build_limit_evidence,
    build_yesterday_strong_performance,
    check_limit_status,
    compute_hotlist_sentiment,
    compute_turnover,
    derive_fallback_row_signals,
    resolve_row_signals,
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
    # 2026-09-10（spec §10）：8 类 statusCounts 与展示派生指标已删除，分布改为 stageCounts。
    # 语义等价性由 test_display_status_reconciliation.py 与下方 golden stage case 守护。
    assert layers["top20"]["strongMoneyShare"] >= 0
    assert set(layers["top20"]["stageCounts"]) == set(STAGE_KEYS)


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


def test_join_signals_preferred_over_fallback():
    # join 层注入 stage + 标记 → 直接采用，来源计 displayStatus
    row = {"code": "000001", "change": 5, "displayStatusStage": "cooling",
           "displayStatusStrongMoney": True, "displayStatusRisk": False}
    source = {"displayStatus": 0, "fallback": 0}
    assert resolve_row_signals(row, [row], source) == ("cooling", True, False, False)
    assert source == {"displayStatus": 1, "fallback": 0}


def test_fallback_signals_when_no_join_record():
    # 无 join 记录 → 走等价 fallback 判据（旧「新入观察」等价为 unknown），来源计 fallback
    row = {"code": "000001", "change": 5}
    source = {"displayStatus": 0, "fallback": 0}
    assert resolve_row_signals(row, [row], source) == ("unknown", False, False, True)
    assert source == {"displayStatus": 0, "fallback": 1}


def test_fallback_signals_classify_old_categories_equivalently():
    # 旧「强资确认」→ cooling + strong；旧「高位拥挤」→ crowded；旧「资金背离」→ risk
    strong = {"change": 5, "compRank": 1, "zlje": 1e8, "zljzb": 12, "cddje": 1e8}
    assert derive_fallback_row_signals(strong) == ("cooling", True, False)
    overheated = {"change": 9, "compRank": 10, "volumeRatio": 2.0}
    assert derive_fallback_row_signals(overheated) == ("crowded", False, False)
    divergence = {"change": 5, "compRank": 10, "zlje": -1e8, "zljzb": -9}
    assert derive_fallback_row_signals(divergence) == ("unknown", False, True)


# 阶段判定 + 风险 + 信号/警告文案全量对齐的 7+3 个 case（名称与 golden_cases.json 一致）
STAGE_CASES = [
    "强扩散但高拥挤时识别为高潮",
    "强资确认增加且风险低时识别为发酵",
    "新入和机会状态改善时识别为启动",
    "风险状态上升且 TRIN 偏弱时识别为退潮",
    "上涨承接较强时高风险压力不直接判为退潮",
    "严重风险叠加昨日强票失败且成交承接转弱时识别为退潮",
    "热榜收缩且机会少时识别为冰点",
    "输出前20、前50、前100分层统计",
    "输出全池 all 分层统计",
    "按A股板块阈值统计热榜涨停和近涨停证据",
    "热榜涨停证据只使用热榜交集，全市场数据仅作为背景",
    "THS炸板池和涨停股回撤榜只作为全市场补充证据",
    "昨日热榜涨停今日表现纳入持续性证据",
    "fallback status ignores suspicious capped volume ratio when detecting crowded stocks",
    "统计昨日强票今日平均涨幅、正收益率和转弱率",
    "默认使用全热榜池统计主情绪指标",
    "分析结果包含当日 turnover 汇总",
]


def _to_py_input(raw_input: dict) -> dict:
    def snap(snapshot: dict | None) -> dict | None:
        if not snapshot:
            return None
        return {"tradingDate": snapshot.get("tradingDate"), "rows": snapshot.get("hotlist") or snapshot.get("rows") or []}
    return {
        "stocks": raw_input.get("stocks") or [],
        "yesterday": snap(raw_input.get("yesterday")),
        "day_before": snap(raw_input.get("dayBefore")),
        "market_data": raw_input.get("marketData"),
        "top_n": raw_input.get("topN"),
    }


@pytest.mark.parametrize("name", STAGE_CASES)
def test_golden_stage_full_alignment(name: str) -> None:
    case = get_case(load_golden_cases(), name)
    if "todayStocks" in case["input"]:   # computeTurnover 直测 case，不经 analyze
        pytest.skip("computeTurnover case 已由 test_golden_turnover_details 覆盖")
    result = compute_hotlist_sentiment(**_to_py_input(case["input"]))
    expected = case["expected"]
    assert result["stage"] == expected["stage"], f"stage: {result['stage']} != {expected['stage']}"
    assert result["riskLevel"] == expected["riskLevel"]
    assert result["confidence"] == expected["confidence"]
    assert result["summary"] == expected["summary"]
    assert result["signals"] == expected["signals"], f"signals 差异:\n got={result['signals']}\n exp={expected['signals']}"
    assert result["warnings"] == expected["warnings"], f"warnings 差异:\n got={result['warnings']}\n exp={expected['warnings']}"
    assert result["turnover"] == expected["turnover"]
    expected_metrics = expected["metrics"]
    assert result["metrics"]["topN"] == expected_metrics["topN"]
    for layer in ("top20", "top50", "top100", "all"):
        # 8 类 statusCounts 已删除：分布改为 stageCounts，其守恒性由 test_display_status_reconciliation.py 守护
        assert set(result["metrics"]["layers"][layer]["stageCounts"]) == set(STAGE_KEYS), layer
        assert result["metrics"]["layers"][layer]["hotTrin"] == expected_metrics["layers"][layer]["hotTrin"], layer
        assert result["metrics"]["layers"][layer]["nearLimitUpCount"] == expected_metrics["layers"][layer]["nearLimitUpCount"], layer
    cmp_expected = expected_metrics["comparison"]
    cmp_result = result["metrics"]["comparison"]
    for key in ("totalChange1d", "totalChange2d", "top100RetainFromYesterday", "top100RetainFromDayBefore",
                "newTop100Count", "newTop100StrongMoneyCount", "yesterdayStrongRetainRate", "yesterdayCrowdedRiskCount"):
        assert cmp_result[key] == cmp_expected[key], key
    assert cmp_result["yesterdayStrongPerformance"] == cmp_expected["yesterdayStrongPerformance"]
    assert result["metrics"]["limitEvidence"] == expected_metrics["limitEvidence"]


def test_insufficient_data_marks_missing_evidence():
    result = compute_hotlist_sentiment([])
    assert result["stage"] == "冰点"
    assert result["metrics"]["comparison"]["today"]["topN"] == 0
    # 2026-09-10：stageMissing 随分类层删除；阶段缺失体现在 stageCounts.unknown
    assert result["statusSourceCounts"] == {"displayStatus": 0, "fallback": 0}
    assert result["metrics"]["layers"]["all"]["stageCounts"]["unknown"] == 0


def test_summary_generated_for_each_stage():
    from backend.analysis.hotlist.sentiment import _STAGE_SUMMARY
    for stage in _STAGE_SUMMARY:
        assert _STAGE_SUMMARY[stage]


def test_status_source_summary_reads_stage_counts():
    # 2026-09-12：8 类 statusCounts 退役后，recompute 的 before/after 摘要必须读
    # stageCounts（实施计划 Task 2 Step 5 遗留）；读不到时保持 None，不伪造 0。
    from backend.services.theme import hotlist_sentiment_compute as svc

    doc = {
        "slotTime": "EOD",
        "stage": "退潮",
        "metrics": {
            "layers": {
                "all": {"stageCounts": {"ignition": 1, "cooling": 2, "unknown": 0}},
            },
            "statusSourceCounts": {"displayStatus": 3, "fallback": 0},
        },
    }

    summary = svc._status_source_summary(doc)

    assert summary["stageCounts"] == {"ignition": 1, "cooling": 2, "unknown": 0}
    assert summary["statusSourceCounts"] == {"displayStatus": 3, "fallback": 0}
    assert "statusCounts" not in summary
