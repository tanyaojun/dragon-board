from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.analysis.hotlist.sentiment import (
    STAGE_KEYS,
    build_comparison,
    build_layer_metrics,
    build_limit_evidence,
    build_transition_counts,
    build_yesterday_strong_performance,
    check_limit_status,
    compute_hotlist_sentiment,
    compute_turnover,
    derive_fallback_row_signals,
    resolve_row_signals,
    sort_rows,
)

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "hotlist_sentiment" / "golden_cases.json"


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


def test_zhaban_signal_boolean_flag_precedence():
    # TS 时代浏览器原料合同布尔字段仍优先（golden fixture 兼容）
    from backend.analysis.hotlist.sentiment import _has_stock_zhaban_signal

    assert _has_stock_zhaban_signal({"isZhaban": True}) is True
    assert _has_stock_zhaban_signal({"failedLimitUp": True}) is True
    # 布尔字段全缺 + 无价格字段（采集链前的输入形态）→ False，不伪造
    assert _has_stock_zhaban_signal({"change": 5.0}) is False


def test_zhaban_signal_price_derivation():
    # 2026-09-25 采集链行无炸板布尔字段：high ≥ limitUpPrice 且当前未封住 → 炸板
    from backend.analysis.hotlist.sentiment import _has_stock_zhaban_signal

    touched_open = {"code": "000001", "high": 11.0, "limitUpPrice": 11.0, "change": 2.0}
    assert _has_stock_zhaban_signal(touched_open) is True
    # 触及但当前仍封住（change ≥ 阈值-容差）→ 不算炸板
    touched_sealed = {"code": "000001", "high": 11.0, "limitUpPrice": 11.0, "change": 9.98}
    assert _has_stock_zhaban_signal(touched_sealed) is False
    # 未触及涨停价（high < limitUpPrice）→ 不算
    not_touched = {"code": "000001", "high": 10.5, "limitUpPrice": 11.0, "change": 2.0}
    assert _has_stock_zhaban_signal(not_touched) is False
    # 字段缺失/非法 → False
    assert _has_stock_zhaban_signal({"code": "000001", "high": 11.0, "change": 2.0}) is False
    # 创业板 20% 阈值按 code 判定：触及 20% 价后回到 11% → 炸板
    gem = {"code": "301001", "high": 12.0, "limitUpPrice": 12.0, "change": 11.0}
    assert _has_stock_zhaban_signal(gem) is True
    # 北交所 30% 阈值：触及 30% 价后回落到 +15% → 炸板；贴近阈值 (+29.9%) 判封住
    bj_open = {"code": "830001", "high": 13.0, "limitUpPrice": 13.0, "change": 15.0}
    assert _has_stock_zhaban_signal(bj_open) is True
    bj_sealed = {"code": "830001", "high": 13.0, "limitUpPrice": 13.0, "change": 29.9}
    assert _has_stock_zhaban_signal(bj_sealed) is False


def test_count_zhaban_input_missing():
    # 炸板推导输入缺失统计（bridge 离线时 high 缺失 → 编排层写 diagnostics，fail-visible）
    from backend.analysis.hotlist.sentiment import count_zhaban_input_missing

    rows = [
        {"code": "000001", "change": 5.0},                                        # 无标记无价格 → 缺失
        {"code": "000002", "high": 11.0, "limitUpPrice": 11.0, "change": 2.0},    # 价格齐全 → 不缺
        {"code": "000003", "isZhaban": False, "change": 5.0},                     # 布尔已定性 → 不缺
        {"code": "000004", "isZhaban": True},                                     # 布尔定性 → 不缺
        {"code": "000005", "high": 0, "limitUpPrice": 0, "change": 5.0},          # 非法价格 → 缺失
        "not-a-dict",
    ]
    assert count_zhaban_input_missing(rows) == 2
    assert count_zhaban_input_missing([]) == 0
    assert count_zhaban_input_missing(None) == 0


def test_limit_intersection_counts_price_derived_zhaban():
    # intersection 聚合消费价格推导：1 涨停 + 1 炸板 + 1 未触板
    rows = [
        {"code": "000001", "name": "甲", "change": 9.98, "compRank": 1},
        {"code": "000002", "name": "乙", "change": 3.0, "compRank": 2, "high": 11.0, "limitUpPrice": 11.0},
        {"code": "000003", "name": "丙", "change": 5.0, "compRank": 3, "high": 10.0, "limitUpPrice": 11.0},
    ]
    evidence = build_limit_evidence(rows, [], None, None)["intersection"]
    assert evidence["top100LimitUpCount"] == 1
    assert evidence["top100ZhabanCount"] == 1
    assert evidence["top100ZhabanShare"] == pytest.approx(1 / 3)


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


def test_transition_counts_aggregated_from_joined_rows():
    """阶段迁移聚合（2026-09-16）：join 注入 cycleTransition → metrics.transitionCounts 计数降序。"""
    rows = [
        {"code": "000001", "rank": 1, "change": 5, "cycleTransition": "ignition->cooling"},
        {"code": "000002", "rank": 2, "change": 3, "cycleTransition": "ignition->cooling"},
        {"code": "000003", "rank": 3, "change": 2, "cycleTransition": "cooling"},
        {"code": "000004", "rank": 4, "change": 1},  # 无 join（fallback 行）→ 不计数
        {"code": "000005", "rank": 5, "change": 1, "cycleTransition": None},
    ]
    counts = build_transition_counts(rows)
    assert counts == {"ignition->cooling": 2, "cooling": 1}


def test_join_injects_cycle_transition():
    """join 层注入 cycleTransition（analysis.cycle.transition 原样透传，缺则为 None）。"""
    from backend.services.theme.hotlist_sentiment_compute import _join_display_status

    class _Coll:
        def find(self, query, projection):
            return [_Row("000001", {"cycle": {"transition": "ignition->cooling"},
                                    "displayStatus": {"stage": "cooling", "label": "冷却"}}),
                    _Row("000002", {"displayStatus": {"stage": "cooling", "label": "冷却"}})]

    class _Row(dict):
        def __init__(self, code, analysis):
            super().__init__(code=code, analysis=analysis)

    class _FakeMongoRepoDB(dict):
        pass

    rows = [{"code": "000001"}, {"code": "000002"}]
    import backend.services.theme.hotlist_sentiment_compute as mod

    class _FakeRepo:
        def __init__(self, db):
            self.db = db

        def load_snapshot_analysis(self, dataset_id, snapshot_id, codes):
            return {"000001": {"cycle": {"transition": "ignition->cooling"},
                               "displayStatus": {"stage": "cooling", "label": "冷却"}},
                    "000002": {"displayStatus": {"stage": "cooling", "label": "冷却"}}}

    import backend.data.repositories.mongo_repository as mongo_mod
    orig = mongo_mod.MongoRepository
    mongo_mod.MongoRepository = _FakeRepo
    try:
        stats = _join_display_status(_FakeMongoRepoDB(), "ds", "snap", rows)
    finally:
        mongo_mod.MongoRepository = orig
    assert stats["joined"] == 2
    assert rows[0]["cycleTransition"] == "ignition->cooling"
    assert rows[1]["cycleTransition"] is None


# ---------------------------------------------------------------------------
# 2026-09-24 口径统一（行情列表「样本不足」 vs 情绪聚合桶不一致修复）：
# meta.sampleQuality.status=insufficient 的行，展示桶归 unknown（与行情列表口径一致），
# 来源仍计 displayStatus（join 命中），规则输入（strongMoneyShare 等）保持按判据计。
# ---------------------------------------------------------------------------


def _patch_analysis_repo(monkeypatch, analysis_by_code: dict):
    import backend.data.repositories.mongo_repository as mongo_mod

    class _FakeRepo:
        def __init__(self, db):
            self.db = db

        def load_snapshot_analysis(self, dataset_id, snapshot_id, codes=None):
            return analysis_by_code

    monkeypatch.setattr(mongo_mod, "MongoRepository", _FakeRepo)


def test_join_injects_sample_insufficient_flag(monkeypatch):
    """join 层按 analysis.meta.sampleQuality.status 注入 displayStatusSampleInsufficient 布尔。"""
    from backend.services.theme.hotlist_sentiment_compute import _join_display_status

    _patch_analysis_repo(
        monkeypatch,
        {
            "000001": {
                "cycle": {"stage": "cooling"},
                "displayStatus": {"stage": "cooling", "label": "冷却"},
                "meta": {"sampleQuality": {"status": "insufficient"}},
            },
            "000002": {
                "cycle": {"stage": "cooling"},
                "displayStatus": {"stage": "cooling", "label": "冷却"},
                "meta": {"sampleQuality": {"status": "ok"}},
            },
        },
    )
    rows = [{"code": "000001"}, {"code": "000002"}]
    stats = _join_display_status({}, "ds", "snap", rows)
    assert stats["joined"] == 2
    assert rows[0]["displayStatusSampleInsufficient"] is True
    assert rows[1]["displayStatusSampleInsufficient"] is False


def test_insufficient_join_row_maps_to_unknown_display_bucket():
    """join 命中但样本不足 → 来源仍计 displayStatus；stage 保留 golden 判定（规则输入用），
    第 4 分量置位 → 计量层展示桶归 unknown（下一条测试验证），非 fallback 来源。"""
    row = {"code": "000001", "change": 5, "displayStatusStage": "cooling",
           "displayStatusStrongMoney": True, "displayStatusRisk": False,
           "displayStatusSampleInsufficient": True}
    source = {"displayStatus": 0, "fallback": 0}
    assert resolve_row_signals(row, [row], source) == ("cooling", True, False, True)
    assert source == {"displayStatus": 1, "fallback": 0}


def test_insufficient_rows_counted_in_unknown_stage_bucket():
    """计量层：样本不足行进 unknown 展示桶；规则输入（strongMoneyShare）保持按判据计。"""
    from backend.analysis.hotlist.sentiment import build_day_metrics_from_sorted

    rows = [
        {"code": "000001", "rank": 1, "change": 5, "zlje": 1e8, "zljzb": 12,
         "displayStatusStage": "cooling", "displayStatusStrongMoney": True,
         "displayStatusRisk": False, "displayStatusSampleInsufficient": True},
        {"code": "000002", "rank": 2, "change": 3,
         "displayStatusStage": "cooling", "displayStatusStrongMoney": False,
         "displayStatusRisk": False},
    ]
    metrics = build_day_metrics_from_sorted(sort_rows(rows), 2)
    assert metrics["stageCounts"]["unknown"] == 1
    assert metrics["stageCounts"]["cooling"] == 1
    # 规则输入不受展示桶影响：样本不足行的强资判定（cooling + zlje/zljzb）仍进 strongMoneyShare
    assert metrics["strongMoneyShare"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 2026-09-24 盘中趋势证据（日内边际）：编排层透传当日已有槽位的 stageShares 序列，
# 纯函数生成首末对比类证据文案。规则：
# - 少于 2 个有效点（无历史）→ 不生成任何证据（不伪造趋势）
# - 阈值 0.04 与 risk_rising/expansion 现有口径一致
# - 证据只进 signals/warnings 文案，不产生 level、不参与情绪阶段级联（golden 零漂移）
# ---------------------------------------------------------------------------


def test_intraday_trend_needs_history():
    from backend.analysis.hotlist.sentiment import _evaluate_intraday_trend

    """无历史（None / 空 / 单点）→ 无趋势证据，不伪造。"""
    today = {"stageShares": {"cooling": 0.8, "ignition": 0.05, "expansion": 0.05}}
    for history in (None, [], [{"slotTime": "09:30", "stageShares": today["stageShares"]}]):
        r = _evaluate_intraday_trend(today, history, "11:30")
        assert r["signals"] == [] and r["warnings"] == []


def test_intraday_trend_cooling_rising_warning():
    from backend.analysis.hotlist.sentiment import _evaluate_intraday_trend
    """冷却占比首末走高 ≥4pp → 风险提示；文案含首末槽位与百分比。"""
    today = {"stageShares": {"cooling": 0.82, "ignition": 0.04, "expansion": 0.04}}
    history = [
        {"slotTime": "09:30", "stageShares": {"cooling": 0.76, "ignition": 0.08, "expansion": 0.06}},
        {"slotTime": "10:00", "stageShares": {"cooling": 0.79, "ignition": 0.06, "expansion": 0.05}},
    ]
    r = _evaluate_intraday_trend(today, history, "11:30")
    assert r["signals"] == []
    # 攻击（点火+扩散）0.14→0.08 走低 ≥4pp → 同步风险提示
    assert r["warnings"] == [
        "冷却占比盘中走高 76%→82%（09:30→11:30）",
        "攻击占比盘中走低 14%→8%（09:30→11:30）",
    ]


def test_intraday_trend_attack_rising_signal():
    from backend.analysis.hotlist.sentiment import _evaluate_intraday_trend
    """攻击占比走高 ≥4pp → 强证据。"""
    today = {"stageShares": {"cooling": 0.70, "ignition": 0.10, "expansion": 0.08}}
    history = [{"slotTime": "09:30", "stageShares": {"cooling": 0.78, "ignition": 0.07, "expansion": 0.05}}]
    r = _evaluate_intraday_trend(today, history, "10:00")
    # 冷却 0.78→0.70 同步回落 ≥4pp → 两条强证据
    assert r["warnings"] == []
    assert r["signals"] == [
        "冷却占比盘中回落 78%→70%（09:30→10:00）",
        "攻击占比盘中走高 12%→18%（09:30→10:00）",
    ]


def test_intraday_trend_small_change_no_evidence():
    from backend.analysis.hotlist.sentiment import _evaluate_intraday_trend
    """首末变化 <4pp → 不生成证据（噪音不进文案）。"""
    today = {"stageShares": {"cooling": 0.78, "ignition": 0.06, "expansion": 0.05}}
    history = [{"slotTime": "09:30", "stageShares": {"cooling": 0.76, "ignition": 0.07, "expansion": 0.05}}]
    r = _evaluate_intraday_trend(today, history, "10:00")
    assert r["signals"] == [] and r["warnings"] == []


def test_intraday_trend_skips_invalid_history_points():
    from backend.analysis.hotlist.sentiment import _evaluate_intraday_trend
    """缺 stageShares 的历史点跳过；全部无效时等同于无历史。"""
    today = {"stageShares": {"cooling": 0.82, "ignition": 0.04, "expansion": 0.04}}
    history = [{"slotTime": "09:30"}, {"slotTime": "10:00", "stageShares": None}]
    r = _evaluate_intraday_trend(today, history, "11:30")
    assert r["signals"] == [] and r["warnings"] == []


def test_intraday_trend_not_in_golden_without_history():
    """不传 history → 输出与旧行为完全一致（golden 零漂移）。"""
    case = get_case(load_golden_cases(), "热榜收缩且机会少时识别为冰点")
    raw = case["input"]
    result_a = compute_hotlist_sentiment(_to_py_input(raw)["stocks"], yesterday=_to_py_input(raw).get("yesterday"),
                                         day_before=_to_py_input(raw).get("dayBefore"), market_data=raw.get("marketData"))
    result_b = compute_hotlist_sentiment(_to_py_input(raw)["stocks"], yesterday=_to_py_input(raw).get("yesterday"),
                                         day_before=_to_py_input(raw).get("dayBefore"), market_data=raw.get("marketData"),
                                         intraday_history=None, current_slot=None)
    assert result_a["signals"] == result_b["signals"]
    assert result_a["warnings"] == result_b["warnings"]


# ---------------------------------------------------------------------------
# 2026-09-24 诊断与业务提示分离：编排层标注（join 失败/缺失、市场证据回退）进
# doc["diagnostics"]，不再混入业务 warnings；纯函数 warnings 保持纯业务证据。
# 文档构造默认带空 diagnostics（schema 稳定，前端按字段存在性渲染）。
# ---------------------------------------------------------------------------


def test_document_has_diagnostics_field():
    """文档构造输出 diagnostics 字段（默认空数组，编排层填充）。"""
    from backend.operations.hotlist_sentiment import build_hotlist_sentiment_document

    # limitSummary 在场（2026-10-05 起 limitStruct 缺失会产诊断行）——本测试锁"无异常时默认空"
    frame = {"snapshotId": "s1", "slotTime": "10:00", "timestamp": 100,
             "limitSummary": {"zhaban": {"ztCount": 30, "rate": 15.0},
                              "continuousBoards": {"maxBoard": 4}}}
    doc = build_hotlist_sentiment_document(
        dataset_id="dragonboard_live", snapshot_type="half_hour", trading_date="2026-06-04",
        frame=frame, stocks=[{"code": "000001", "rank": 1, "change": 5, "zlje": 0, "volumeRatio": 1.5}],
    )
    assert doc["diagnostics"] == []
    # 诊断类标注不再写入 warnings 的由编排层保证，此处锁 schema
    assert isinstance(doc["warnings"], list)


# ---------------------------------------------------------------------------
# 2026-09-24 阶段多帧确认：确认槽数配置解析（fail-visible——非法值回裁决默认 2 并
# 返回结构化诊断，禁止静默退化为 1 关闭平滑）。
# ---------------------------------------------------------------------------


def test_stage_confirm_config_default_is_two(monkeypatch):
    import backend.services.theme.hotlist_sentiment_compute as compute_mod

    monkeypatch.delenv("HOTLIST_STAGE_CONFIRM_SLOTS", raising=False)
    assert compute_mod._stage_confirm_config() == (2, None)


def test_stage_confirm_config_accepts_legal_values(monkeypatch):
    import backend.services.theme.hotlist_sentiment_compute as compute_mod

    for value in (1, 3):
        monkeypatch.setenv("HOTLIST_STAGE_CONFIRM_SLOTS", str(value))
        assert compute_mod._stage_confirm_config() == (value, None)


def test_stage_confirm_config_invalid_values_fall_back_with_diagnostic(monkeypatch):
    import backend.services.theme.hotlist_sentiment_compute as compute_mod

    for raw in ("abc", "0", "-2", "1.5"):
        monkeypatch.setenv("HOTLIST_STAGE_CONFIRM_SLOTS", raw)
        slots, diagnostic = compute_mod._stage_confirm_config()
        assert slots == 2
        assert diagnostic is not None and "stage_confirm_invalid_config" in diagnostic
