# -*- coding: utf-8 -*-
"""frame_market_percentiles G3 全市场量能分位单测（2026-08-23 前后端分离）。"""
from backend.analysis.ranktrend.engine import (_percentile_sorted, frame_market_percentiles)


def _frame(count=30):
    # 构造 30 只股票：turnover=code 序号, volumeRatio=*2, turnoverRate=*3（全部 >0）
    stocks = [
        {"code": f"{i:06d}", "turnover": float(i + 1), "volumeRatio": float((i + 1) * 2), "turnoverRate": float((i + 1) * 3)}
        for i in range(count)
    ]
    return {"stocks": stocks}


def test_percentile_sorted_linear():
    assert _percentile_sorted([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5  # 中值
    assert _percentile_sorted([1.0], 0.5) == 1.0


def test_market_percentiles_flat_keys():
    r = frame_market_percentiles(_frame(30))
    assert "turnoverP50" in r and "turnoverP70" in r and "turnoverP85" in r
    assert "volumeRatioP50" in r and "turnoverRateP50" in r
    # turnover=1..30 → P50≈15.5, P85≈25.65
    assert 14.5 < r["turnoverP50"] < 16.5
    assert r["turnoverRateP50"] == r["turnoverP50"] * 3


def test_insufficient_sample_omits_field():
    # 仅 3 只（<20）→ 三字段整组不产出（fail-visible）
    r = frame_market_percentiles(_frame(3))
    assert r == {}


def test_invalid_and_negative_filtered():
    stocks = [
        {"code": "a", "turnover": 10.0, "volumeRatio": 5.0, "turnoverRate": 2.0},
        {"code": "b", "turnover": -1.0, "volumeRatio": 0, "turnoverRate": "nan"},
        {"code": "c", "turnover": None, "volumeRatio": 3.0, "turnoverRate": 4.0},
    ] * 8  # 24 个（有效 <20 的维不产出）
    r = frame_market_percentiles({"stocks": stocks})
    # turnover 仅 8 个有效(<20) → 不产出；volumeRatio 有效较多
    assert "turnoverP50" not in r
