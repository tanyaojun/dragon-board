# -*- coding: utf-8 -*-
"""日线形态分型测试（services/jev/shape_types，2026-10-31 用户裁决版）。

判定树（互斥优先级，不含收盘封板股）：触板未封 → 大面（收盘 ≤−3%）/炸板（>−3%）；
未触板 → 冲高回落（最高 ≥5% 且收盘 <5%）→ 强势（收盘 ≥5% 且 closePos ≥0.7）→
尾盘跳水（最高 ≥3% 且 closePos ≤0.25）→ 兜底 up/down/flat。
fail-visible：缺价一律 None 不猜；封板股 shape=None 由既有涨停/跌停徽标表达。

全离线零外呼零模型（§1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.jev.shape_types import (
    BIG_FACE, DOWN, FADE, FLAT, HIGH_CLOSE, TAIL_DIVE, UP, ZHA_BAN, shape_fields,
)


def _shape(pct, price, pre_close=10.0, high=None, low=None, touched=None,
           sealed_down=False):
    high = high if high is not None else price
    low = low if low is not None else price
    return shape_fields("600001", pct, price, pre_close, high, low,
                        sealed_down=sealed_down, touched=touched)


def test_touched_limit_deep_drop_is_big_face():
    """触板未封 + 收盘 ≤−3% → 大面（用户裁决 1：加深度线）。"""
    out = _shape(-4.0, 9.6, high=11.0, low=9.5)          # 触板 11.00=涨停价，收 −4%
    assert out["shape"] == BIG_FACE
    assert out["highPct"] == 10.0 and out["closePos"] is not None


def test_touched_limit_mild_drop_is_zha_ban():
    """触板未封 + 收盘 >−3%（收平/收红）→ 炸板，与大面互斥。"""
    assert _shape(-1.0, 9.9, high=11.0, low=9.8)["shape"] == ZHA_BAN
    assert _shape(2.0, 10.2, high=11.0, low=10.0)["shape"] == ZHA_BAN


def test_fade_covers_mild_spike():
    """未触板：盘中最高 ≥5% 且收盘 <5% → 冲高回落（高点线 5%，用户裁决 3）。"""
    assert _shape(3.0, 10.3, high=10.6, low=10.1)["shape"] == FADE   # 高点 +6%，收 +3%
    assert _shape(1.0, 10.1, high=10.5, low=10.0)["shape"] == FADE   # 高点 +5%，收 +1%


def test_high_close_is_strong():
    """收盘 ≥5% 未涨停且收在全天高位（closePos ≥0.7）→ 强势；收中位 → 兜底 up。"""
    assert _shape(6.0, 10.6, high=10.62, low=10.0)["shape"] == HIGH_CLOSE
    assert _shape(6.0, 10.6, high=10.9, low=10.0)["shape"] == UP      # 收盘中位，非强势


def test_tail_dive():
    """未触板：盘中最高 ≥3% 且收在全天低位（closePos ≤0.25）→ 尾盘跳水（日线近似口径）。"""
    assert _shape(0.5, 10.05, high=10.4, low=10.0)["shape"] == TAIL_DIVE


def test_fallback_up_down_flat():
    """兜底：收盘红盘 up / 绿盘 down / 平盘 flat（不满足任何形态线）。"""
    assert _shape(2.0, 10.2, high=10.3, low=10.0)["shape"] == UP
    assert _shape(-2.0, 9.8, high=10.1, low=9.7)["shape"] == DOWN
    assert _shape(0.0, 10.0, high=10.1, low=9.9)["shape"] == FLAT


def test_sealed_stocks_shape_none():
    """收盘封涨停/跌停股不入形态分型（shape=None，由既有涨停/跌停徽标表达）。"""
    # 收盘封涨停：10→11.00（主板涨停价）
    assert _shape(10.0, 11.0, high=11.0, low=10.0)["shape"] is None
    # 收盘跌停（调用方 sealed_down=True）
    assert _shape(-10.0, 9.0, high=10.5, low=9.0, sealed_down=True)["shape"] is None


def test_missing_prices_none_not_false():
    """缺价不猜：缺 high/highPct=None；缺涨停价基准时触板不可判，形态退兜底/None。"""
    out = shape_fields("600001", 2.0, 10.2, 10.0, None, None)
    assert out["highPct"] is None and out["closePos"] is None
    assert out["shape"] == UP                      # 兜底仍可判（仅 pct）
    assert shape_fields("600001", None, 10.2, 10.0, 10.6, 10.1)["shape"] is None
