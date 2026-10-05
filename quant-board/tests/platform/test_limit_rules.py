# -*- coding: utf-8 -*-
"""板块涨跌幅限制单一权威源测试（core/limit_rules，2026-10-05 单源化）。

口径：主板 0.10 / 创业板·科创板 0.20 / 北交所 0.30；2026-09 新规无 ST 特判；
判定线 = ratio×100 − 容差（默认 0.2pp → 9.8/19.8/29.8）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.limit_rules import (
    is_limit_down_pct,
    limit_down_price,
    limit_ratio,
    limit_threshold_pct,
    limit_up_price,
)


def test_limit_ratio_by_board():
    assert limit_ratio("600000") == 0.10          # 沪主板
    assert limit_ratio("000001") == 0.10          # 深主板
    assert limit_ratio("002001") == 0.10          # 中小板并入主板
    assert limit_ratio("300750") == 0.20          # 创业板
    assert limit_ratio("301001") == 0.20
    assert limit_ratio("688981") == 0.20          # 科创板
    assert limit_ratio("689009") == 0.20          # 科创板 CDR
    assert limit_ratio("430047") == 0.30          # 北交所
    assert limit_ratio("832000") == 0.30          # 8 开头
    assert limit_ratio("920001") == 0.30          # 920 北交新股


def test_limit_ratio_normalizes_and_tolerates_junk():
    assert limit_ratio("sh600000") == 0.10        # 带前缀：非纯数字按字面前缀不匹配 → 主板兜底
    assert limit_ratio(" 600000 ") == 0.10        # 去空白后 zfill
    assert limit_ratio("60000") == 0.10           # 5 位数字 zfill(6)
    assert limit_ratio(None) == 0.10              # 空值兜底主板
    assert limit_ratio("") == 0.10


def test_limit_prices_round_to_tick():
    assert limit_up_price("600000", 10.0) == 11.0
    assert limit_up_price("600000", 3.33) == 3.66    # 3.66/3.33 → 真实 pctChange 9.91%（容差存在的原因）
    assert limit_down_price("600000", 10.0) == 9.0
    assert limit_up_price("300750", 10.0) == 12.0
    assert limit_up_price("430047", 10.0) == 13.0


def test_limit_threshold_pct_default_tolerance():
    assert limit_threshold_pct("600000") == 9.8
    assert limit_threshold_pct("300750") == 19.8
    assert limit_threshold_pct("688981") == 19.8
    assert limit_threshold_pct("832000") == 29.8


def test_limit_threshold_pct_custom_tolerance():
    # theme/heat 链路容差 0.7（历史口径 9.3/19.3/29.3 逐位等价）
    assert limit_threshold_pct("600000", tolerance_pct=0.7) == 9.3
    assert limit_threshold_pct("300750", tolerance_pct=0.7) == 19.3
    assert limit_threshold_pct("920001", tolerance_pct=0.7) == 29.3


def test_is_limit_down_pct_by_board():
    assert is_limit_down_pct(-9.9, "600000") is True
    assert is_limit_down_pct(-9.7, "600000") is False
    assert is_limit_down_pct(-19.9, "300750") is True
    assert is_limit_down_pct(-29.9, "920001") is True
    # 新规无 ST 特判：主板 ST -5.0 不计
    assert is_limit_down_pct(-5.0, "600000") is False
    assert is_limit_down_pct(None, "600000") is False   # 非数值不伪造
    assert is_limit_down_pct("junk", "600000") is False
    assert is_limit_down_pct(True, "600000") is False   # bool 是 int 子类，显式拒绝
