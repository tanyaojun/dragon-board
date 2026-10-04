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
    eod = {"2026-10-09": 55.0, "2026-10-12": 70.0, "2026-10-13": 60.0}
    out, unbanded = band_stats(trades, eod, "2026-10")
    assert out["弱势40-60"]["trades"] == 1 and out["弱势40-60"]["sumNetReturn"] == -0.07
    assert out["强60-80"]["trades"] == 1 and out["强60-80"]["avgPerTrade"] == 0.14
    assert out["冷10-40"]["trades"] == 0
    assert unbanded == 0
    # 展示语义随档携带（前端纯渲染不自建映射）
    assert out["弱势40-60"]["label"] == "弱势期" and out["弱势40-60"]["rangeText"] == "40-60"


def test_band_stats_extreme_hot_band_no_silent_drop():
    """2026-10-04 事故回归：前日 EOD ≥80 的交易必须进极热档，不得静默丢档（11 笔≠10 笔）。"""
    from backend.operations.phase_pulse import band_stats

    trades = [
        {"entryTradingDate": "2026-10-12", "netReturn": -0.07},  # 前日 10-09=55 → 弱势
        {"entryTradingDate": "2026-10-13", "netReturn": 0.14},   # 前日 10-12=85 → 极热≥80
    ]
    eod = {"2026-10-09": 55.0, "2026-10-12": 85.0, "2026-10-13": 60.0}
    out, unbanded = band_stats(trades, eod, "2026-10")
    assert out["极热≥80"]["trades"] == 1 and out["极热≥80"]["sumNetReturn"] == 0.14
    assert out["极热≥80"]["label"] == "极热期"
    assert sum(b["trades"] for b in out.values()) == 2
    assert unbanded == 0


def test_band_stats_unbanded_visible():
    """缺前一日分/缺平仓价的当月入场笔 → unbanded 计数显式暴露（fail-visible 不静默）。"""
    from backend.operations.phase_pulse import band_stats

    trades = [
        {"entryTradingDate": "2026-10-12", "netReturn": -0.07},  # 前日 10-09=55 → 弱势
        {"entryTradingDate": "2026-10-13", "netReturn": 0.14},   # 自身无 EOD 文档 → unbanded
        {"entryTradingDate": "2026-10-14", "netReturn": None},   # 无平仓价 → unbanded
    ]
    eod = {"2026-10-09": 55.0, "2026-10-12": 55.0}
    out, unbanded = band_stats(trades, eod, "2026-10")
    assert out["弱势40-60"]["trades"] == 1
    assert unbanded == 2


def test_band_stats_stale_anchor_not_used():
    """前日解算与引擎同口径：EOD 文档存在但分数缺失 → 当缺处理，不跳锚更早日（review P2）。"""
    from backend.operations.phase_pulse import band_stats

    trades = [
        {"entryTradingDate": "2026-10-13", "netReturn": 0.14},   # 前日 10-12 文档在但分 None → unbanded（不锚 10-09 的 55）
    ]
    eod = {"2026-10-09": 55.0, "2026-10-12": None, "2026-10-13": 60.0}
    out, unbanded = band_stats(trades, eod, "2026-10")
    assert sum(b["trades"] for b in out.values()) == 0
    assert unbanded == 1


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
