# -*- coding: utf-8 -*-
"""API 实时链路 crossSection 挂载 + synergy 第 5 维投票断言（2026-08-18）。

review nit 固化：_analyze_one_stock（前端 POST /api/ranktrend/analyze 数据源，assemble=False）
必须挂载 observation.crossSection，synergy 才能计入第 5 维投票——防回测改进不同步前端。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig, market_regime


def _make_stock(change=2.0, volume_ratio=1.5) -> dict:
    return {
        "code": "000001", "name": "样本", "change": change, "volumeRatio": volume_ratio,
        "zlje": 1200, "zljzb": 1.2, "avgRankNum": 3, "rank": 3,
    }


def _make_args(percentiles):
    from backend.api.ranktrend_routes import _analyze_one_stock  # 延迟 import 防循环
    stock = _make_stock()
    frame = {"snapshotId": "s1", "type": "half_hour", "tradingDate": "2026-08-14", "slotTime": "14:00"}
    ranks = list(range(len(percentiles), 0, -1))
    regime = market_regime(frame)
    return _analyze_one_stock, (
        RankTrendConfig(), stock, frame, ranks, percentiles, regime, [],
        {"version": "t", "frames": [], "themes": {}},
        None, 0, None,
    )


def test_api_link_mounts_cross_section_and_votes() -> None:
    func, args = _make_args([16.0 + i * 14 for i in range(7)])  # percentile 上升 → A 档（delta=14 ≥5，末值 100 ≥85）
    result = func(args)
    assert result is not None
    obs = result["analysis"].get("observation") or {}
    cs = obs.get("crossSection") or {}
    assert cs.get("signalTier") in ("A", "B", "C", "D", "unknown"), "crossSection 未挂载"
    syn = obs.get("synergy") or {}
    assert syn.get("signalTier"), "synergy 档位缺失"
    assert cs.get("signalTier") in ("A", "B"), f"测试数据应产生强势档，实际 {cs.get('signalTier')}"
    for key in ("atrMeanReversion", "priceMomentum", "amountRatio", "priceRankDivergence"):
        assert key in obs, f"API observation 缺失 {key}"


def test_api_link_fail_visible_none_market_median() -> None:
    func, args = _make_args([30.0, 40.0, 50.0, 60.0, 70.0])
    # market_median=None → relativeToMarket=None，绝对档照常（fail-visible，不阻断）
    result = func(args)
    assert result is not None
    obs = result["analysis"].get("observation") or {}
    cs = obs.get("crossSection") or {}
    assert cs.get("signalTier") in ("A", "B", "C", "D", "unknown"), "crossSection 未挂载（回归）"
    assert cs.get("relativeToMarket") is None, "market_median=None 时应保留 relativeToMarket=None"
