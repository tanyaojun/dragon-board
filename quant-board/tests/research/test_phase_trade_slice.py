# -*- coding: utf-8 -*-
"""M1 交易层相位切片测试：54 笔 roundTrip 交易按入场相位 + 入场 regime 双口径切片。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.phase_trade_slice import round_trips_of, slice_trades, wrxpf_of


TRADES = [
    {"entryTradingDate": "2026-05-06", "regime": "strong", "netReturn": 0.10},
    {"entryTradingDate": "2026-05-07", "regime": "strong", "netReturn": -0.05},
    {"entryTradingDate": "2026-07-29", "regime": "retreat", "netReturn": -0.08},
    {"entryTradingDate": "2026-07-30", "regime": "retreat", "netReturn": None},  # 缺失：计数不伪装
]


def test_wrxpf_of_basic_and_missing():
    m = wrxpf_of(TRADES)
    assert m["trades"] == 3            # 只计有效 netReturn
    assert m["missingNetReturn"] == 1  # 缺失显式计数（fail-visible，M1）
    assert m["winRate"] == round(1 / 3, 4)
    assert m["profitFactor"] == round(0.10 / 0.13, 4)  # grossWin 0.10 / grossLoss 0.13
    assert m["wrxpf"] == round((1 / 3) * (0.10 / 0.13), 4)
    assert m["sumNetReturn"] == -0.03


def test_wrxpf_of_empty():
    assert wrxpf_of([])["wrxpf"] is None


def test_round_trips_of_prefers_roundtrip_array():
    summary = {"roundTripTrades": [{"netReturn": 0.1}], "trades": [{"netReturn": 0.2}, {"netReturn": 0.3}]}
    assert len(round_trips_of(summary)) == 1  # 口径=roundTripTrades（54），不用含分片的 trades（65）


def test_slice_trades_by_daily_phase():
    daily = {"2026-05-06": "offense", "2026-05-07": "offense", "2026-07-29": "defense"}
    out = slice_trades(TRADES, daily=daily, phase_key="phase")
    assert out["offense"]["trades"] == 2
    assert out["defense"]["trades"] == 1
    assert out["defense"]["sumNetReturn"] == -0.08


def test_slice_trades_by_regime_field():
    out = slice_trades(TRADES, daily=None, phase_key="regime")
    assert out["strong"]["trades"] == 2
    assert out["retreat"]["trades"] == 1
    assert out["retreat"]["sumNetReturn"] == -0.08
