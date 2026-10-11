# -*- coding: utf-8 -*-
"""EOD 连板层五池重新入采的池键选择（2026-10-10 Phase 0）。

b5d4ac36（2026-10-02）以「连板层五池零消费」为由把采集层砍到三池；jev 叙事/
连板指数成为新消费者后恢复——但仅 EOD 时段（上海 ≥15:00）并入，盘中仍三池。"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.snapshot_collector.providers import (
    _COLLECTOR_POOL_KEYS,
    _LADDER_POOL_KEYS,
    _evidence_pool_keys,
)

_TZ = ZoneInfo("Asia/Shanghai")


def _at(hhmm: str) -> datetime:
    hh, mm = hhmm.split(":")
    return datetime(2026, 10, 13, int(hh), int(mm), tzinfo=_TZ)


def test_intraday_keeps_three_pools():
    """盘中（含 14:59）只取三池，缓存键不加后缀。"""
    for t in ("09:40", "11:30", "13:05", "14:59"):
        keys, suffix = _evidence_pool_keys(_at(t))
        assert keys == _COLLECTOR_POOL_KEYS
        assert suffix == ""


def test_eod_window_merges_ladder_pools():
    """EOD 时段（≥15:00）连板层五池并入，缓存键 :ladder 隔离（盘中缓存不复用）。"""
    for t in ("15:00", "15:05", "15:30", "21:00"):
        keys, suffix = _evidence_pool_keys(_at(t))
        assert keys == _COLLECTOR_POOL_KEYS + _LADDER_POOL_KEYS
        assert len(keys) == 8
        assert suffix == ":ladder"


def test_pool_key_sets_disjoint_semantics():
    """连板层五池与三池不重叠；LADDER 五键与 THS 梯队口径对齐。"""
    assert set(_LADDER_POOL_KEYS) == {"one", "two", "three", "four", "high"}
    assert not (set(_LADDER_POOL_KEYS) & set(_COLLECTOR_POOL_KEYS))
