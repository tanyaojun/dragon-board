# -*- coding: utf-8 -*-
"""priceMomentum（价格动量观察因子）测试。

设计（2026-08-17 审计缺口 G1）：趋势维度全是排名百分位时序（momentum/MA/MACD/zeroCross），
价格（change 涨跌幅）只进量价单帧与 fallback——价格时序信息完全没进趋势。本因子补：
- priceMaShort/priceMaLong：change 序列均线方向（价格均线，up/down/steady）
- priceMomentumScore：短周期 change 均值动量（buy/sell/hold）
- signalTier：A 强（动量 buy + 均线上行）/ B 偏强 / C 偏弱 / D 弱 / unknown（change 不足）
MACD 保持排名口径（G5 定义），不做价格 MACD。
不进 synergy 投票（观察验证，同 crossSection 流程）。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.price_momentum import (
    PRICE_MOMENTUM_DEFAULTS,
    compute_price_momentum,
)


def cfg(**patch) -> RankTrendConfig:
    base = dict(RankTrendConfig().__dict__)
    base.update(patch)
    return RankTrendConfig(**base)


# ---------- 默认值契约 ----------

def test_price_momentum_defaults_match_engine_config() -> None:
    c = RankTrendConfig()
    assert c.priceMaShort == PRICE_MOMENTUM_DEFAULTS["priceMaShort"]
    assert c.priceMaLong == PRICE_MOMENTUM_DEFAULTS["priceMaLong"]
    assert c.priceMomentumPeriod == PRICE_MOMENTUM_DEFAULTS["priceMomentumPeriod"]
    assert c.priceMomentumScoreThreshold == PRICE_MOMENTUM_DEFAULTS["priceMomentumScoreThreshold"]
    assert c.priceMaShort == 5
    assert c.priceMaLong == 10
    assert c.priceMomentumPeriod == 3
    assert c.priceMomentumScoreThreshold == 0.5


# ---------- 档位判定 ----------

def test_tier_a_rising_price_and_ma_up() -> None:
    # 持续上涨：change 全正，ma5 > ma10，动量 buy
    changes = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]
    r = compute_price_momentum(changes, config=cfg())
    assert r["signalTier"] == "A"
    assert r["maTrend"] == "up"
    assert r["momentumSignal"] == "buy"
    assert r["priceMaShort"] == pytest.approx(sum(changes[-5:]) / 5)


def test_tier_d_falling_price_and_ma_down() -> None:
    changes = [-1.0, -1.5, -2.0, -2.5, -3.0, -3.5, -4.0, -4.5, -5.0, -5.5, -6.0]
    r = compute_price_momentum(changes, config=cfg())
    assert r["signalTier"] == "D"
    assert r["maTrend"] == "down"
    assert r["momentumSignal"] == "sell"


def test_tier_b_mixed_but_net_positive() -> None:
    changes = [1.0, -0.5, 2.0, 1.0, 1.5, 0.5, 2.0, 1.0, 1.5, 1.0, 0.5]
    r = compute_price_momentum(changes, config=cfg())
    assert r["signalTier"] in ("A", "B")
    assert r["momentumSignal"] == "buy"


def test_unknown_when_changes_insufficient() -> None:
    r = compute_price_momentum([], config=cfg())
    assert r["signalTier"] == "unknown"
    assert any("价格时序不足" in x for x in r["tierReasons"])
    r2 = compute_price_momentum([1.0, 2.0], config=cfg())  # 短于 maLong
    assert r2["signalTier"] == "unknown"


def test_nan_and_none_handled_fail_visible() -> None:
    r = compute_price_momentum([1.0, None, float("nan"), 2.0, 3.0], config=cfg())
    # 含无效值：可计算部分保留，不阻断；缺失比例高时降级 unknown
    assert r["signalTier"] in ("A", "B", "C", "D", "unknown")
    assert r["invalidCount"] >= 2


# ---------- config 生效 ----------

def test_config_periods_effective() -> None:
    c = cfg(priceMaShort=3, priceMaLong=6, priceMomentumPeriod=2)
    changes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    r = compute_price_momentum(changes, config=c)
    assert r["priceMaShort"] == pytest.approx(6.0)  # 短均线周期 3：(5+6+7)/3
    assert r["maTrend"] == "up"
    assert r["momentumSignal"] == "buy"
