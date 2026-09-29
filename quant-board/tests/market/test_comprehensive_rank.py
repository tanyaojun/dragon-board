# -*- coding: utf-8 -*-
"""comprehensive_rank 后端五维综合排名单测（2026-08-23 前后端分离 G1）。"""
from backend.analysis.ranktrend.comprehensive_rank import (
    FUND_PENETRATION,
    HOTLIST_WEIGHTS,
    HOT_RANK,
    MONEY_RATIO,
    OPTIMAL_TURNOVER,
    TURNOVER_RATE,
    TURNOVER_SIGMA,
    VOLUME,
    average_rank_fields,
    compute_comprehensive_scores,
    compute_live_ranking,
    infer_platform_totals,
)


def _stock(avg, zljzb, fund, turnover_rate, turnover, code):
    return {
        "code": code, "avgRankNum": avg, "zljzb": zljzb, "fundPenetration": fund,
        "turnoverRate": turnover_rate, "turnover": turnover,
    }


# 前后端五维权重金标准（src/types/config.ts COMPREHENSIVE_WEIGHTS 同步锁）。
# 两端权重双份硬编码（跨语言无法运行时共享），此测试锁定后端值，
# 前端 config.ts COMPREHENSIVE_WEIGHTS 由对应前端测试锁定，保证两端一致防漂移。
def test_weights_aligned_with_frontend_golden():
    assert HOT_RANK == 0.45
    assert MONEY_RATIO == 0.25
    assert FUND_PENETRATION == 0.10
    assert TURNOVER_RATE == 0.12
    assert VOLUME == 0.08
    # 前端 config.ts：PENALTY_SCORE=100 / DEFAULT_RANK=999 / OPTIMAL_TURNOVER=15 / TURNOVER_SIGMA=10
    assert OPTIMAL_TURNOVER == 15.0
    assert TURNOVER_SIGMA == 10.0


def test_rank_order_follows_comp_score_desc():
    stocks = [
        _stock(10, 5, 2, 12, 300, "a"),   # avgRankNum 小（好）→ HOT_RANK 高
        _stock(80, -5, 0.5, 30, 100, "b"), # avgRankNum 大（差）→ HOT_RANK 低
    ]
    r = compute_comprehensive_scores(stocks)
    by_code = {s["code"]: s for s in r}
    assert by_code["a"]["compRank"] < by_code["b"]["compRank"]
    assert "compScore" in by_code["a"] and "compRank" in by_code["a"]


def test_deterministic_tie_break_by_code():
    # 完全相同输入 → 按 code 稳定排序（确定性）
    stocks = [_stock(50, 1, 1, 15, 100, "b"), _stock(50, 1, 1, 15, 100, "a")]
    r = compute_comprehensive_scores(stocks)
    codes = [s["code"] for s in sorted(r, key=lambda s: s["compRank"])]
    assert codes == ["a", "b"]


def test_empty_and_single():
    assert compute_comprehensive_scores([]) == []
    one = compute_comprehensive_scores([_stock(50, 1, 1, 15, 100, "a")])
    assert one[0]["compRank"] == 1


def test_normalize_reverse_gives_higher_for_smaller_rank():
    # avgRankNum 越小 → HOT_RANK 分量越高 → compScore 越高（排名反）
    good = _stock(10, 0, 0, 15, 100, "g")
    bad = _stock(90, 0, 0, 15, 100, "b")
    r = compute_comprehensive_scores([good, bad])
    by = {s["code"]: s for s in r}
    assert by["g"]["compScore"] > by["b"]["compScore"]


def test_average_rank_fields_matches_weighted_percentile_formula():
    # weighted_platform_percentile_v1：rank/total*100*weight 加权平均；缺失平台按 100 计权
    row = {"code": "a", "emRank": 1, "thsRank": 10, "kplRank": 999}
    totals = {"eastmoney": 100, "ths": 100, "kpl": 50}
    average_rank_fields(row, totals)
    expected = (
        (1 / 100) * 100 * HOTLIST_WEIGHTS["eastmoney"]
        + (10 / 100) * 100 * HOTLIST_WEIGHTS["ths"]
        + 100 * HOTLIST_WEIGHTS["kpl"]
    ) / (HOTLIST_WEIGHTS["eastmoney"] + HOTLIST_WEIGHTS["ths"] + HOTLIST_WEIGHTS["kpl"])
    assert row["platforms"] == 2  # 999 哨兵 = kpl 缺失
    assert abs(row["avgRankNum"] - expected) < 1e-9
    assert row["avgRank"] == f"{row['avgRankNum']:.1f}"


def test_average_rank_fields_total_missing_platform_skips_weight():
    # platform_totals 缺某平台 → 该平台不计权（与采集链 total<=0 语义一致）
    row = {"code": "a", "emRank": 1}
    average_rank_fields(row, {"eastmoney": 100})
    assert abs(row["avgRankNum"] - 1.0) < 1e-9
    assert row["platforms"] == 1


def test_infer_platform_totals_uses_max_rank_below_sentinel():
    rows = [
        {"emRank": 96, "xqRank": 58, "kplRank": 999},
        {"emRank": 40, "xqRank": 3, "kplRank": 50},
    ]
    totals = infer_platform_totals(rows)
    assert totals["eastmoney"] == 96
    assert totals["xueqiu"] == 58
    assert totals["kpl"] == 50
    assert totals["tgb"] == 0  # 整榜缺失


def test_compute_live_ranking_produces_full_row_ranking():
    # 2026-09-22 实时口径：均榜输入由平台 rank 实时推算，compScore/compRank 随之产出
    rows = [
        {"code": "a", "emRank": 1, "thsRank": 2, "zljzb": 5, "turnoverRate": 12, "turnover": 300},
        {"code": "b", "emRank": 90, "thsRank": 80, "zljzb": -5, "turnoverRate": 30, "turnover": 100},
    ]
    out = compute_live_ranking([dict(r) for r in rows])
    by = {r["code"]: r for r in out}
    assert by["a"]["compRank"] < by["b"]["compRank"]
    assert by["a"]["platforms"] == 2
    assert by["a"]["avgRankNum"] < by["b"]["avgRankNum"]  # a 平台排名全面靠前
    # 原输入行不被污染（路由层传副本调用）
    assert "compScore" not in rows[0]
    assert "avgRankNum" not in rows[0]
