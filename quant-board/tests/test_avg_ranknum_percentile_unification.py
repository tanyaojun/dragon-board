"""avgRankNum 重排口径合一测试（2026-09-12，防口径漂移）。

背景：``frame_cross_section``（横截面）与 ``attention_rank_lookup + percentile_rank``
（趋势 replay / routes rank-series 权威口径）历史上是两份独立实现——过滤（finite>0）、
排序键 ``(avgRankNum, code)`` 升序、百分位公式在数值上等价但代码重复，存在漂移风险。

本测试用硬编码锚点值 + 边界用例锁住横截面口径：并列 tie-break、脏数据过滤、空池、
单元素。``frame_cross_section`` 重构为委托 ``attention_rank_lookup`` 的实现后，本文件
即"所有 avgRankNum→序号/百分位消费走同一实现"的回归护栏。
"""

from __future__ import annotations

import math

from backend.analysis.ranktrend.engine import (
    attention_rank_lookup,
    frame_cross_section,
    percentile_rank,
)


def test_frame_cross_section_matches_authoritative_lookup() -> None:
    """横截面百分位与权威口径（attention_rank_lookup + percentile_rank）逐位一致。"""
    stocks = [{"code": f"{i:06d}", "avgRankNum": float(i + 1)} for i in range(10)]
    frame = {"stocks": stocks}
    ranks, total = attention_rank_lookup(stocks)
    expected = {code: percentile_rank(rank, total) for code, rank in ranks.items()}
    assert frame_cross_section(frame) == expected


def test_percentile_formula_anchor_values() -> None:
    """锚点值锁公式与计算顺序：先除后乘 (x/n)*100（与先乘后除差 1 ULP，golden 逐位
    对齐下计算顺序即合同）。total=3，rank1→100、rank2→(2/3)*100、rank3→(1/3)*100。"""
    stocks = [
        {"code": "000003", "avgRankNum": 3.0},
        {"code": "000001", "avgRankNum": 1.0},
        {"code": "000002", "avgRankNum": 2.0},
    ]
    assert frame_cross_section({"stocks": stocks}) == {
        "000001": 100.0,
        "000002": ((3 - 1) / 3) * 100,
        "000003": ((3 - 2) / 3) * 100,
    }


def test_tied_avg_rank_num_breaks_by_code_ascending() -> None:
    """并列 avgRankNum 按 (avgRankNum, code) 升序：code 小者 rank 靠前、百分位高。"""
    stocks = [
        {"code": "000002", "avgRankNum": 5.0},
        {"code": "000001", "avgRankNum": 5.0},
    ]
    assert frame_cross_section({"stocks": stocks}) == {"000001": 100.0, "000002": 50.0}
    ranks, total = attention_rank_lookup(stocks)
    assert (ranks["000001"], ranks["000002"], total) == (1, 2, 2)


def test_invalid_avg_rank_num_rows_are_filtered() -> None:
    """avgRankNum 缺失/None/非数值/≤0/NaN 的行全部剔除，不进横截面也不进 attention 序号。"""
    stocks = [
        {"code": "000001", "avgRankNum": 2.0},
        {"code": "000002"},  # 缺字段
        {"code": "000003", "avgRankNum": None},
        {"code": "000004", "avgRankNum": "abc"},
        {"code": "000005", "avgRankNum": 0.0},
        {"code": "000006", "avgRankNum": -1.0},
        {"code": "000007", "avgRankNum": float("nan")},
        {"code": "000008", "avgRankNum": float("inf")},
        {"code": "", "avgRankNum": 1.0},  # 空 code 剔除
        "not-a-dict",  # 非 dict 行剔除
    ]
    assert frame_cross_section({"stocks": stocks}) == {"000001": 100.0}
    ranks, total = attention_rank_lookup(stocks)
    assert ranks == {"000001": 1}
    assert total == 1


def test_empty_and_single_stock_edges() -> None:
    """空池返回空 dict 不除零；单元素百分位=100。"""
    assert frame_cross_section({"stocks": []}) == {}
    assert frame_cross_section({}) == {}
    assert attention_rank_lookup([]) == ({}, 0)
    single = [{"code": "600000", "avgRankNum": 7.5}]
    assert frame_cross_section({"stocks": single}) == {"600000": 100.0}
    assert attention_rank_lookup(single) == ({"600000": 1}, 1)


def test_percentile_rank_guard_zero_inputs() -> None:
    """percentile_rank 守卫：rank≤0 或 total≤0 返回 0（不除零），正常路径如锚点。"""
    assert percentile_rank(0, 10) == 0.0
    assert percentile_rank(1, 0) == 0.0
    assert math.isclose(percentile_rank(2, 4), 75.0)
