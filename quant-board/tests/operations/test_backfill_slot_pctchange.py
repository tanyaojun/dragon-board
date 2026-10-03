# -*- coding: utf-8 -*-
"""槽位 pctChange 回填纯函数测试：棒映射/前收/涨跌幅。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.backfill_slot_pctchange import prev_close_of, slot_price

S = {
    "2026-04-14 15:00": (10.0, 10.0),
    "2026-04-15 09:35": (10.5, 10.6),   # 首棒：open=10.5 close=10.6
    "2026-04-15 10:30": (10.8, 11.0),
    "2026-04-15 11:30": (11.0, 11.2),
    "2026-04-15 13:30": (11.2, 11.3),
    "2026-04-15 15:00": (11.3, 11.5),
}


def test_slot_mapping():
    assert slot_price(S, "2026-04-15", "09:30") == 10.5   # 首棒 open
    assert slot_price(S, "2026-04-15", "09:35") == 10.6   # 首棒 close
    assert slot_price(S, "2026-04-15", "10:30") == 11.0   # 同刻棒 close
    assert slot_price(S, "2026-04-15", "13:00") == 11.2   # 午休结转 11:30
    assert slot_price(S, "2026-04-15", "14:30") is None   # 缺棒 fail-visible


def test_prev_close_and_pct():
    pc = prev_close_of(S, "2026-04-15")
    assert pc == 10.0
    price = slot_price(S, "2026-04-15", "15:00")
    assert round((price / pc - 1) * 100, 2) == 15.0
    assert prev_close_of(S, "2026-04-14") is None  # 首日无前收
