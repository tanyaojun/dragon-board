# -*- coding: utf-8 -*-
"""comprehensive_rank 后端五维综合排名单测（2026-08-23 前后端分离 G1）。"""
from backend.analysis.ranktrend.comprehensive_rank import (
    FUND_PENETRATION,
    HOT_RANK,
    MONEY_RATIO,
    OPTIMAL_TURNOVER,
    TURNOVER_RATE,
    TURNOVER_SIGMA,
    VOLUME,
    compute_comprehensive_scores,
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
