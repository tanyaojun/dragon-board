# -*- coding: utf-8 -*-
"""成交额量比（G3 amount 落地）测试：compute_amount_ratio + volume_price amount 增强。

2026-08-18：跨帧成交额量比进量价——当前成交额 / 前 N 帧均额。
fail-visible：历史不足/全缺失/0 值 → None，不参与量价资金判定（不破坏原档位）。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.volume_price import (
    compute_amount_ratio,
    compute_volume_price_score,
)


def cfg(**patch) -> RankTrendConfig:
    base = dict(RankTrendConfig().__dict__)
    base.update(patch)
    return RankTrendConfig(**base)


def vp_score(amount_ratio=None, *, change=2.0, vr=1.5, zljzb=1.0, **patch):
    return compute_volume_price_score(
        "000001", change, vr, 1200, zljzb, cfg(**patch), amount_ratio=amount_ratio
    )


# ---------- compute_amount_ratio ----------

def test_amount_ratio_basic() -> None:
    # 前 5 帧均额 100，当前 200 → 2.0（放量）
    history = [100.0] * 5 + [200.0]
    r = compute_amount_ratio(history, cfg())
    assert r == pytest.approx(2.0)


def test_amount_ratio_uses_recent_window() -> None:
    # 当前 60，前 5 帧均额 120 → 0.5（缩量）
    history = [120.0] * 6 + [60.0]
    r = compute_amount_ratio(history, cfg())
    assert r == pytest.approx(0.5)


def test_amount_ratio_insufficient_history_none() -> None:
    assert compute_amount_ratio([100.0], cfg()) is None
    assert compute_amount_ratio([], cfg()) is None
    assert compute_amount_ratio(None, cfg()) is None


def test_amount_ratio_zero_and_none_skipped() -> None:
    # 0 值视为缺失跳过（早期快照 amount=0）
    history = [100.0, 0, None, 100.0, 100.0, 150.0]
    r = compute_amount_ratio(history, cfg())
    assert r is not None
    assert r == pytest.approx(1.5)  # 均额基于有效值 100,100,100 → 150/100


def test_amount_ratio_current_zero_fail_visible() -> None:
    # 2026-08-19 审计 blocking 修复：当前帧 0/None → None（不静默回退上一帧）
    assert compute_amount_ratio([100.0, 200.0, 0.0], cfg()) is None
    assert compute_amount_ratio([100.0, 200.0, None], cfg()) is None
    assert compute_amount_ratio([100.0, 200.0, float("nan")], cfg()) is None


# ---------- compute_volume_price_score amount 增强 ----------

def test_vp_amount_high_adds_score() -> None:
    base = vp_score(None)
    boosted = vp_score(2.0)
    assert boosted["score"] == base["score"] + 5
    assert any("成交额放量资金" in x for x in boosted["reasons"])
    assert boosted["breakdown"]["amount"] == pytest.approx(5.0)


def test_vp_amount_low_deducts_score() -> None:
    base = vp_score(None)
    shrunk = vp_score(0.4)
    assert shrunk["score"] == base["score"] - 5
    assert any("成交额缩量资金" in x for x in shrunk["reasons"])


def test_vp_amount_none_no_effect() -> None:
    base = vp_score(None)
    none_ratio = vp_score(None)
    assert none_ratio["score"] == base["score"]
    assert none_ratio["breakdown"]["amount"] == pytest.approx(0.0)


def test_vp_amount_zero_fail_visible() -> None:
    r = vp_score(0.0)
    assert r["breakdown"]["amount"] == pytest.approx(0.0)
    assert any("成交额数据缺失" in x for x in r["reasons"])


def test_vp_amount_thresholds_configurable() -> None:
    c = cfg(amountRatioHigh=2.0)
    r = compute_volume_price_score(
        "000001", 2.0, 1.5, 1200, 1.0, c, amount_ratio=1.8
    )
    assert r["breakdown"]["amount"] == pytest.approx(0.0)  # 1.8 < 2.0 不高不低
