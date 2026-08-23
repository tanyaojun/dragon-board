# -*- coding: utf-8 -*-
"""providers 五维综合排名接线测试（2026-08-23 前后端分离 G1）。"""
from backend.snapshot_collector.providers import ProxyMergedHotlistProvider  # noqa: F401


def _row(code, avg_rank, zljzb, turnover_rate, turnover, zlje, cir_mv):
    return {
        "code": code, "avgRankNum": avg_rank, "zljzb": zljzb, "turnoverRate": turnover_rate,
        "turnover": turnover, "zlje": zlje, "cirMV": cir_mv, "platforms": 1,
    }


def test_rank_rows_sets_five_dim_comp_rank():
    # 《 直接调用 _rank_rows 需要实例；用类实例化最简（无状态）。
    provider = object.__new__(ProxyMergedHotlistProvider)
    rows = [_row("a", 10, 5, 12, 300, 2e8, 1e10), _row("b", 80, -5, 30, 100, -1e8, 2e10)]
    out = provider._rank_rows({r["code"]: r for r in rows}, {})
    by = {r["code"]: r for r in out}
    # a 排名靠前(avgRankNum 小)+资金正 → 五维 compRank 优于 b
    assert by["a"]["compRank"] < by["b"]["compRank"]
    assert "compScore" in by["a"]
    assert "fundPenetration" in by["a"]
    assert "rank" in by["a"]  # avgRankNum 单维 rank 保留
