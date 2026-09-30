# -*- coding: utf-8 -*-
"""M3 脉拍纯函数测试：当月切片（roundTrip+equity 按 EOD 同日定相）→ 北极星读数。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_pulse import build_pulse_report


def _summary(trades: list[dict], equity: list[tuple[str, float]]) -> dict:
    return {
        "roundTripTrades": trades,
        "equityCurve": [{"tradingDate": d, "equity": e} for d, e in equity],
    }


def test_build_pulse_report_month_filter_and_phases():
    summary = _summary(
        [
            {"entryTradingDate": "2026-10-12", "netReturn": 0.10},   # 10 月，前日 EOD 70 → offense
            {"entryTradingDate": "2026-10-13", "netReturn": -0.04},  # 前日 EOD 45 → defense
            {"entryTradingDate": "2026-09-30", "netReturn": 0.99},   # 上月：剔除
        ],
        [("2026-09-28", 100.0), ("2026-10-12", 110.0), ("2026-10-13", 104.0)],
    )
    eod = {"2026-09-28": 55.0, "2026-10-09": 70.0, "2026-10-12": 45.0}
    report = build_pulse_report(summary, eod, "2026-10")
    assert report["tradeCount"] == 2
    # 10-12 前同日 EOD 45 → defense；10-13 无 EOD → unknown
    assert report["byPhase"]["defense"]["trades"] == 1
    assert report["byPhase"]["unknown"]["trades"] == 1
    assert report["byPhase"]["offense"]["trades"] == 0  # 稳定键空桶
    assert report["equitySlices"]["defense"]["equityPoints"] == 1
    assert report["equitySlices"]["unknownPoints"] == 1
    assert report["northstar"]["offense"]["pass"] is False  # 0 笔 <60 线
    assert report["fullWindow"]["segReturn"] == round(104.0 / 110.0 - 1, 4)


def test_build_pulse_report_empty_month():
    report = build_pulse_report(_summary([], []), {"2026-10-09": 60.0}, "2026-10")
    assert report["tradeCount"] == 0
    assert report["northstar"]["offense"]["pass"] is False


def test_band_stats_prev_day_as_of():
    """C6 证据累积：按前一日 EOD 分带（as-of 可实操口径），月内过滤。"""
    from backend.operations.phase_pulse import band_stats

    trades = [
        {"entryTradingDate": "2026-10-12", "netReturn": -0.07},  # 前日 10-09=55 → 弱势
        {"entryTradingDate": "2026-10-13", "netReturn": 0.14},   # 前日 10-12=70 → 强
        {"entryTradingDate": "2026-09-30", "netReturn": 0.99},   # 上月：剔除
    ]
    eod = {"2026-10-09": 55.0, "2026-10-12": 70.0}
    out = band_stats(trades, eod, "2026-10")
    assert out["弱势40-60"]["trades"] == 1 and out["弱势40-60"]["sumNetReturn"] == -0.07
    assert out["强60-80"]["trades"] == 1 and out["强60-80"]["avgPerTrade"] == 0.14
    assert out["冷10-40"]["trades"] == 0


def test_ab_compare_delta():
    from backend.operations.phase_pulse import ab_compare

    baseline = _summary(
        [{"entryTradingDate": "2026-10-12", "netReturn": -0.07},
         {"entryTradingDate": "2026-10-13", "netReturn": 0.14}],
        [("2026-10-12", 100.0)],
    )
    controlled = _summary(
        [{"entryTradingDate": "2026-10-13", "netReturn": 0.14}],
        [("2026-10-12", 100.0)],
    )
    out = ab_compare(baseline, controlled, "2026-10")
    assert out["baseline"]["tradeCount"] == 2
    assert out["bandAvoided"]["tradeCount"] == 1
    assert out["delta"]["tradesRemoved"] == 1
    assert out["delta"]["netReturnSaved"] == 0.07  # 回避了 -7% 那笔
