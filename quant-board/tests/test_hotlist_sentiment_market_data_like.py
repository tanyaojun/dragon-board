"""_build_market_data_like 锁行为测试（WP1a spec 遗留观察项①，2026-09-09 补）。

背景：frame.limitSummary → DragonBreathMarketDataLike 映射自上线起零单测覆盖，
仅靠生产核对（2026-09-09 抽查 9/9 槽位文档 limitEvidence 实质完整）验证。本文件
锁定其映射合同——任何偏离都必须显式修改本文件（视为合同变更），而非静默漂移。

两个调用方共用：series lazy compute（hotlist_sentiment_compute.py:145）与
collector 槽位落库（hotlist_sentiment_compute.py:193）。

有意不锁的现行为：boards 值为非数字字符串（如 "abc"）时 float() 抛 ValueError——
真实采集数据为数字，该崩溃路径由 compute_and_upsert_for_slot 外层 except 兜为
reason 上报，不把崩溃固化为合同。
"""
from __future__ import annotations

import pytest

from backend.analysis.hotlist.sentiment import build_limit_evidence
from backend.services.theme.hotlist_sentiment_compute import _build_market_data_like


# 2026-09-09 生产槽位帧 limitSummary 的真实形状（continuousBoards/zhaban/thsPools 为 dict，
# yesterdayZt 等其余键不进入映射输出）
PRODUCTION_SHAPE = {
    "continuousBoards": {"yiban": 23, "erban": 8, "sanban": 3, "sibanPlus": 1, "wubanPlus": 1},
    "zhaban": {"count": 12, "fengbanRate": 63.2},
    "yesterdayZt": ["000001", "000002"],
    "thsPools": {"failedCount": 11, "drawdownCount": 7, "drawdownRiskLabel": "涨停股回撤榜"},
}


def test_production_shape_maps_all_five_keys():
    result = _build_market_data_like(PRODUCTION_SHAPE)
    # 精确相等锁完整输出合同：五键齐全、无多余键（yesterdayZt/未知键不得混入）
    assert result == {
        "ztCount": 35,  # yiban+erban+sanban+siban；wubanPlus 等未知键不参与聚合
        "zhaban": {"count": 12, "fengbanRate": 63.2},
        "limitData": {"yiban": 23, "erban": 8, "sanban": 3, "sibanPlus": 1, "wubanPlus": 1},
        "maxContinuousDays": 4,
        "thsLimitUpPools": {"failedCount": 11, "drawdownCount": 7, "drawdownRiskLabel": "涨停股回撤榜"},
    }


@pytest.mark.parametrize("bad_input", [None, "not-a-dict", 123, ["list"], [("k", "v")]])
def test_non_dict_limit_summary_returns_none(bad_input):
    # 无 market 证据 → None；由纯函数 missingEvidence 标注，不得伪造空结构
    assert _build_market_data_like(bad_input) is None


@pytest.mark.parametrize(
    "boards, expected_days",
    [
        ({"sibanPlus": 1}, 4),
        ({"sanban": 2, "yiban": 10}, 3),   # 取最高存在档，不看 yiban 数量
        ({"erban": 1}, 2),
        ({"yiban": 5}, 1),
        ({}, 0),
        ({"yiban": 0, "erban": 0, "sanban": 0, "sibanPlus": 0}, 0),
    ],
)
def test_max_continuous_days_ladder(boards, expected_days):
    assert _build_market_data_like({"continuousBoards": boards})["maxContinuousDays"] == expected_days


def test_continuous_boards_missing_or_non_dict_yields_zero_evidence():
    for limit_summary in ({}, {"continuousBoards": None}, {"continuousBoards": ["bad"]}):
        result = _build_market_data_like(limit_summary)
        assert result["ztCount"] == 0
        assert result["limitData"] == {}
        assert result["maxContinuousDays"] == 0
        assert result["zhaban"] == {}            # 输入无 zhaban → 空字典（下游 to_number 兜 0）
        assert result["thsLimitUpPools"] is None  # 输入无 thsPools → None（下游换空池结构）


def test_zhaban_and_ths_pools_non_dict_asymmetry():
    # 现行为：zhaban 非字典 → {}；thsPools 非字典 → None。两分支兜底方式不同，
    # 下游（build_limit_evidence）对两者各自再判 isinstance，故均为安全兜底；
    # 但合同不同，改动任一侧须显式更新本测试。
    result = _build_market_data_like({"zhaban": "bad", "thsPools": [1, 2]})
    assert result["zhaban"] == {}
    assert result["thsLimitUpPools"] is None


def test_string_numbers_coerce_via_float():
    # 库内数字可能以字符串落存（历史 JSON 导入链）；float() 收敛是现行为
    result = _build_market_data_like({"continuousBoards": {"yiban": "12"}})
    assert result["ztCount"] == 12
    assert result["maxContinuousDays"] == 1
    # 小数连板数同样参与阶梯（erban=0.5>0 → 2 档；首版用例误预期 1，锁行为修正）
    result2 = _build_market_data_like({"continuousBoards": {"yiban": "12", "erban": 0.5}})
    assert result2["ztCount"] == 12.5
    assert result2["maxContinuousDays"] == 2


def test_mapping_output_feeds_build_limit_evidence():
    # 消费端贯通：映射五键正是 build_limit_evidence 读取的合同键
    market = _build_market_data_like(PRODUCTION_SHAPE)
    evidence = build_limit_evidence([], [], None, market)
    assert evidence["market"]["ztCount"] == 35
    assert evidence["market"]["zhabanCount"] == 12
    assert evidence["market"]["fengbanRate"] == pytest.approx(63.2)
    assert evidence["market"]["maxContinuousDays"] == 4
    assert evidence["market"]["thsPools"]["failedCount"] == 11


def test_none_market_data_keeps_market_evidence_empty_not_crash():
    # market_data=None（limitSummary 缺失帧）→ 全市场证据为空结构，缺而不伪
    evidence = build_limit_evidence([], [], None, None)
    assert evidence["market"]["ztCount"] == 0
    assert evidence["market"]["zhabanCount"] == 0
    assert evidence["market"]["maxContinuousDays"] == 0
