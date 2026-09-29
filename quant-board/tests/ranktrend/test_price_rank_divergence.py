# -*- coding: utf-8 -*-
"""价格-排名背离观察因子（priceRankDivergence）测试。

设计（2026-08-18）：价格动能与排名 Jump 的相位差因子——价升排名跌（出货预警）、
排名升价跌（关注度先行）均为可观察信号。输入 change 序列 + percentile 序列：
- confirm_up（价升+排名升）= A 真强势
- rank_lead（排名升+价跌）= B 关注度先行（排名先行，h1 预测力）
- confirm_down（价跌+排名跌）= C
- price_lead_warn（价升+排名跌）= D 出货预警
- unknown：价格/排名数据不足
不进 synergy 投票（观察验证，同 crossSection 流程）。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.price_rank_divergence import (
    PRICE_RANK_DIVERGENCE_DEFAULTS,
    compute_price_rank_divergence,
)


def cfg(**patch) -> RankTrendConfig:
    base = dict(RankTrendConfig().__dict__)
    base.update(patch)
    return RankTrendConfig(**base)


# ---------- 默认值契约 ----------

def test_defaults_match_engine_config() -> None:
    c = RankTrendConfig()
    assert c.priceRankChangeMin == PRICE_RANK_DIVERGENCE_DEFAULTS["priceRankChangeMin"]
    assert c.priceRankDeltaMin == PRICE_RANK_DIVERGENCE_DEFAULTS["priceRankDeltaMin"]
    assert c.priceRankChangeMin == 0.0
    assert c.priceRankDeltaMin == 0.0


# ---------- 四态判定 ----------

def test_confirm_up_price_and_rank_rise() -> None:
    # change 当前 +2%，percentile 上升（delta>0）→ A 一致强
    r = compute_price_rank_divergence(
        price_changes=[1.0, 2.0], percentiles=[50.0, 70.0], config=cfg()
    )
    assert r["state"] == "confirm_up"
    assert r["signalTier"] == "A"
    assert r["priceDir"] == "up"
    assert r["rankDir"] == "up"


def test_price_lead_warn_price_up_rank_down() -> None:
    # 价升（+2%）但排名降（delta<0）→ D 出货预警
    r = compute_price_rank_divergence(
        price_changes=[1.0, 2.0], percentiles=[70.0, 50.0], config=cfg()
    )
    assert r["state"] == "price_lead_warn"
    assert r["signalTier"] == "D"
    assert any("出货" in x or "背离" in x for x in r["tierReasons"])


def test_rank_lead_rank_up_price_down() -> None:
    # 排名升（delta>0）但价跌（-1%）→ B 关注度先行
    r = compute_price_rank_divergence(
        price_changes=[1.0, -1.0], percentiles=[50.0, 70.0], config=cfg()
    )
    assert r["state"] == "rank_lead"
    assert r["signalTier"] == "B"
    assert any("先行" in x for x in r["tierReasons"])


def test_confirm_down_price_and_rank_fall() -> None:
    r = compute_price_rank_divergence(
        price_changes=[1.0, -2.0], percentiles=[70.0, 50.0], config=cfg()
    )
    assert r["state"] == "confirm_down"
    assert r["signalTier"] == "C"


# ---------- unknown / 数据不足 ----------

def test_unknown_insufficient_data() -> None:
    r = compute_price_rank_divergence(price_changes=[], percentiles=[], config=cfg())
    assert r["signalTier"] == "unknown"
    assert any("数据不足" in x for x in r["tierReasons"])


def test_unknown_none_values() -> None:
    r = compute_price_rank_divergence(
        price_changes=[None, None], percentiles=[None, None], config=cfg()
    )
    assert r["signalTier"] == "unknown"


# ---------- 阈值生效 ----------

def test_thresholds_effective() -> None:
    # 价格方向阈值：change 需 ≥ 0.5 才算涨
    c = cfg(priceRankChangeMin=0.5)
    r = compute_price_rank_divergence(
        price_changes=[0.1, 0.3], percentiles=[50.0, 70.0], config=c
    )
    assert r["priceDir"] != "up"  # 0.3 < 0.5 → 非涨


def test_zero_change_flat_not_confirm_up() -> None:
    # 2026-08-19 审计修复：默认阈值 0.0 时 change=0/delta=0 必须归 flat（严格 >），
    # 不得标 confirm_up/A 污染档位统计。
    r = compute_price_rank_divergence(
        price_changes=[1.0, 0.0], percentiles=[60.0, 60.0], config=cfg()
    )
    assert r["state"] == "unknown"  # priceDir=flat + rankDir=flat → unknown（方向不明确）
    assert r["signalTier"] == "unknown"
