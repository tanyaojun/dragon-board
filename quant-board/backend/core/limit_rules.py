# -*- coding: utf-8 -*-
"""A 股板块涨跌幅限制单一权威源（主板 / 创业板 / 科创板 / 北交所）。

2026-09 口径（与前端 src/utils/common.ts StockUtils、规则情绪链、快照派生一致）：
全市场按所属板块阈值，**无 ST 特判**（主板 ST 亦 ±10%；创业板/科创板 ST ±20%、
北交所 ±30%）。历史副本（hotlist/sentiment、theme/heat、snapshot_derivation/projection、
jev 弹药层）一律委托本模块；ranktrend 域（golden 引擎 volume_price/engine config/research
审计）暂独立维护不接入——golden 红线，见 docs/hotlist-jev/jev-limitup-code-audit-20261005.md。

两个语义，勿混用：
- ``limit_ratio(code)``：精确比例（乘 prev_close 取整到分 = 真实涨/跌停价）；
- ``limit_threshold_pct(code, tolerance_pct)``：pctChange 判定线（百分点，含容差；
  默认 0.2pp——tick 取整致真实涨跌停 pctChange 有 ±0.2pp 浮动，故主板线 9.8 而非 10）。
"""
from __future__ import annotations

LIMIT_TOLERANCE_PCT = 0.2


def limit_ratio(code: object) -> float:
    """板块涨跌幅限制（精确比例）：主板 0.10 / 创业板·科创板 0.20 / 北交所 0.30。

    前缀口径：688/689→科创板；30 开头→创业板；43/8 开头/92→北交所；其余→主板。
    6 位数字自动 zfill；无 ST 特判（2026-09 新规，与前端 StockUtils 一致）。
    """
    value = str(code or "").strip()
    if value.isdigit():
        value = value.zfill(6)
    if value.startswith(("688", "689")) or value.startswith("30"):
        return 0.20
    if value.startswith(("43", "8", "92")):
        return 0.30
    return 0.10


def limit_up_price(code: object, prev_close: float) -> float:
    """真实涨停价：prev_close × (1 + ratio)，四舍五入到分。"""
    return round(float(prev_close) * (1 + limit_ratio(code)), 2)


def limit_down_price(code: object, prev_close: float) -> float:
    """真实跌停价：prev_close × (1 − ratio)，四舍五入到分。"""
    return round(float(prev_close) * (1 - limit_ratio(code)), 2)


def limit_threshold_pct(code: object, tolerance_pct: float = LIMIT_TOLERANCE_PCT) -> float:
    """pctChange 涨停判定线（百分点）：ratio×100 − 容差。默认 9.8 / 19.8 / 29.8。

    tolerance_pct 由调用方按各自链路容差传入（如 theme/heat 用 0.7 → 9.3/19.3/29.3）。
    """
    return limit_ratio(code) * 100 - tolerance_pct


def is_limit_down_pct(pct_change: object, code: object,
                      tolerance_pct: float = LIMIT_TOLERANCE_PCT) -> bool:
    """pctChange 是否达到跌停判定线（非数值一律 False，不伪造）。"""
    if not isinstance(pct_change, (int, float)) or isinstance(pct_change, bool):
        return False
    return pct_change <= -(limit_ratio(code) * 100 - tolerance_pct)
