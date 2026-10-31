# -*- coding: utf-8 -*-
"""个股日线形态分型（游资复盘口径，2026-10-31 用户裁决；下跌/上涨复盘页共用单一实现）。

不含收盘封板股（涨停/跌停由页面既有徽标表达，shape=None）；判定树（互斥，从上到下）：
1. **大面** `big_face`：触板未封且收盘 `pct ≤ −3%`（深度线，用户裁决 1）；
2. **炸板** `zha_ban`：触板未封且收盘 > −3%（含收平/收红；与大面互斥取优先级，用户裁决 2）；
3. **冲高回落** `fade`：未触板，盘中最高涨幅 ≥5% 且收盘 <5%（高点线降到 5% 覆盖温和回落，用户裁决 3）；
4. **强势（高位收盘）** `high_close`：收盘涨幅 ≥5% 未涨停且收盘位于全天高位
   （`closePos ≥ 0.7`）——上涨名单的正向对照面；
5. **尾盘跳水** `tail_dive`：未触板，盘中最高涨幅 ≥3% 且收盘位于全天低位
   （`closePos ≤ 0.25`）——日线近似口径（无法区分真尾盘跳水与全天阴跌，用户裁决 4 知情采纳）；
6. 兜底：`up`（收盘红盘）/ `down`（收盘绿盘）/ `flat`（平盘）。

派生量（随分型一并返回，页面行展开/表格可核）：
- `highPct`：盘中最高涨幅 `(high − preClose) / preClose`；缺 high/preClose → None；
- `closePos`：收盘位置 `(close − low) / (high − low)`；high==low（一字）或缺价 → None。

fail-visible：缺价一律 None（未知不判否），不伪造形态；触板判定同一条价格精确闸
（±0.005 元，与 market_rise_pool.is_sealed_limit_up / 涨停价精确闸同源）。
调用方可用 `touched` 传入已判定的触板事实（如快照口径已算过），缺省由本模块按日线 high 自算。
"""
from __future__ import annotations

from typing import Any

from backend.core.limit_rules import limit_up_price
from backend.operations.market_rise_pool import is_sealed_limit_up

BIG_FACE = "big_face"        # 大面
ZHA_BAN = "zha_ban"          # 炸板（触板未封，未达大面深度线）
FADE = "fade"                # 冲高回落
HIGH_CLOSE = "high_close"    # 强势（高位收盘）
TAIL_DIVE = "tail_dive"      # 尾盘跳水
UP = "up"                    # 收盘红盘（兜底）
DOWN = "down"                # 收盘绿盘（兜底）
FLAT = "flat"                # 平盘（兜底）

BIG_FACE_PCT = -3.0        # 大面深度线：触板未封且收盘 ≤ −3%
FADE_HIGH_PCT = 5.0        # 冲高回落高点线：盘中最高涨幅 ≥5%
FADE_CLOSE_PCT = 5.0       # 冲高回落收盘线：收盘 <5%
STRONG_CLOSE_POS = 0.7     # 强势收盘位置线：收盘位于全天区间上 30%
STRONG_PCT = 5.0           # 强势收盘涨幅线（与上涨名单基线一致）
DIVE_HIGH_PCT = 3.0        # 尾盘跳水盘中线：盘中最高涨幅 ≥3%
DIVE_CLOSE_POS = 0.25      # 尾盘跳水收盘位置线：收盘位于全天区间下 25%

_PRICE_TOL = 0.005         # 触板价格容差（元），与涨停价精确闸同源


def _num(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def shape_fields(code: object, pct: object, price: object, pre_close: object,
                 high: object, low: object, *, sealed_down: bool = False,
                 touched: bool | None = None) -> dict[str, Any]:
    """日线形态分型 → {highPct, closePos, shape}。缺价不猜（None），封板股 shape=None。"""
    high_f, low_f, price_f, pre_f = _num(high), _num(low), _num(price), _num(pre_close)
    pct_f = _num(pct)

    high_pct = (round((high_f / pre_f - 1) * 100, 2)
                if high_f is not None and pre_f is not None and pre_f > 0 else None)
    close_pos = (round((price_f - low_f) / (high_f - low_f), 4)
                 if None not in (price_f, low_f, high_f) and high_f > low_f else None)

    # 触板事实：调用方未传入时按日线 high ≈ 涨停价（±0.005 元，同一条价格精确闸）
    if touched is None and high_f is not None and pre_f is not None and pre_f > 0:
        touched = abs(high_f - limit_up_price(code, pre_f)) <= _PRICE_TOL
    sealed_up = is_sealed_limit_up(price_f, pre_f, code)

    shape = None
    if sealed_up is not True and not sealed_down and pct_f is not None:
        if touched is True:
            shape = BIG_FACE if pct_f <= BIG_FACE_PCT else ZHA_BAN
        elif high_pct is not None and high_pct >= FADE_HIGH_PCT and pct_f < FADE_CLOSE_PCT:
            shape = FADE
        elif (pct_f >= STRONG_PCT and close_pos is not None
              and close_pos >= STRONG_CLOSE_POS):
            shape = HIGH_CLOSE
        elif (high_pct is not None and high_pct >= DIVE_HIGH_PCT
              and close_pos is not None and close_pos <= DIVE_CLOSE_POS):
            shape = TAIL_DIVE
        elif pct_f > 0:
            shape = UP
        elif pct_f < 0:
            shape = DOWN
        else:
            shape = FLAT
    return {"highPct": high_pct, "closePos": close_pos, "shape": shape}
