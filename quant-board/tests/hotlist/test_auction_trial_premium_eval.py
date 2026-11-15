# -*- coding: utf-8 -*-
"""竞价试盘溢价/封板率规则档评估脚本纯函数测试（转正 TDD，零网络零 jev 零写库）。

覆盖 scripts/auction_trial_premium_eval.py 新增判定逻辑：一字/T字板、封板结局
（trial percent 权威 + TDX 补证）、板块竞价强度档边界、桶边界、竞价强度比、
溢价缺值不进分母、交易轴假期守卫。IO/板块全链由生产单源既有测试覆盖。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

QB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(QB))
_spec = importlib.util.spec_from_file_location(
    "ape", QB / "scripts" / "auction_trial_premium_eval.py")
ape = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ape)

LP = 10.0   # 涨停价


# ── 一字 / T 字板判定 ──
def test_one_word_open_and_low_at_limit():
    assert ape.is_one_word(LP, LP, LP) is True


def test_t_word_open_at_limit_low_below_kept():
    # T 字板：开=涨停但低<涨停 → 非一字（可买，保留）
    assert ape.is_one_word(LP, LP - 1.0, LP) is False


def test_not_one_word_open_below_limit():
    assert ape.is_one_word(LP - 1.0, LP - 1.0, LP) is False


def test_one_word_epsilon_tolerance():
    assert ape.is_one_word(LP - 0.0005, LP - 0.0005, LP) is True   # eps 内视为涨停


# ── 封板结局：trial percent 权威 + TDX 补证 + 一字剔除 ──
def test_seal_trial_true_non_oneword():
    r = ape.seal_outcome(True, LP, LP - 1.0, LP - 1.0, LP)
    assert r["seal_all"] is True and r["seal_n1w"] is True and r["one_word"] is False


def test_seal_trial_true_oneword_not_buyable():
    r = ape.seal_outcome(True, LP, LP, LP, LP)
    assert r["seal_all"] is True and r["seal_n1w"] is False and r["one_word"] is True


def test_seal_percent_missing_tdx_confirm():
    # percent 缺位（None）→ TDX 收盘补证封板
    r = ape.seal_outcome(None, LP, LP - 1.0, LP - 1.0, LP)
    assert r["seal_all"] is True and r["seal_n1w"] is True


def test_seal_percent_missing_tdx_not_sealed():
    r = ape.seal_outcome(None, LP - 1.0, LP - 1.0, LP - 1.0, LP)
    assert r["seal_all"] is False and r["seal_n1w"] is False


def test_seal_trial_false_authoritative_over_tdx():
    # trial percent 未封（False）即使 TDX 达涨停价（除权/舍入分歧）仍以 trial 为准
    r = ape.seal_outcome(False, LP, LP - 1.0, LP - 1.0, LP)
    assert r["seal_all"] is False and r["seal_n1w"] is False


# ── 板块竞价强度档边界 ──
def test_board_tier_none_unmapped():
    assert ape.board_tier(None) == "未分板块"


def test_board_tier_boundaries():
    assert ape.board_tier(0) == "冷 <5000万"
    assert ape.board_tier(5e7 - 1) == "冷 <5000万"
    assert ape.board_tier(5e7) == "温 5000万-2亿"
    assert ape.board_tier(2e8) == "中热 2-5亿"
    assert ape.board_tier(5e8) == "热 5-10亿"
    assert ape.board_tier(1e9) == "过热 ≥10亿"
    assert ape.board_tier(3.78e9) == "过热 ≥10亿"


# ── 桶边界 / 缺值 ──
def test_bucket_missing():
    assert ape.bucket(None, [5, 10], ["<5", "5-10", "≥10"]) == "缺值"


def test_bucket_boundaries():
    edges, labels = [5, 10], ["<5", "5-10", "≥10"]
    assert ape.bucket(3, edges, labels) == "<5"
    assert ape.bucket(5, edges, labels) == "5-10"
    assert ape.bucket(10, edges, labels) == "≥10"
    assert ape.bucket(99, edges, labels) == "≥10"


# ── 竞价强度比 jj_ratio（tier_jj 同锚：PRESEAL 用 pre_percent，否则限价）──
def test_jj_ratio_preseal_uses_pre_percent():
    assert abs(ape.jj_ratio(9.54, 10.0, 10.0, True) - 95.4) < 1e-6


def test_jj_ratio_non_preseal_uses_limit():
    assert abs(ape.jj_ratio(5.0, None, 10.0, False) - 50.0) < 1e-6


def test_jj_ratio_missing():
    assert ape.jj_ratio(None, 10.0, 10.0, True) is None
    assert ape.jj_ratio(5.0, None, 0, False) is None


# ── 溢价：缺值不进分母（不伪装 0）──
def test_premium_pct():
    assert abs(ape.premium_pct(10.0, 10.5) - 5.0) < 1e-6


def test_premium_missing_not_zero():
    assert ape.premium_pct(10.0, None) is None
    assert ape.premium_pct(0, 10.5) is None


# ── 交易轴假期守卫 ──
def test_trading_axis_guard():
    axis = {"2026-11-12", "2026-11-13"}
    assert ape.on_trading_axis("2026-11-13", axis) is True
    assert ape.on_trading_axis("2026-10-01", axis) is False   # 国庆冒充档须被剔


# ── fnum 解析 ──
def test_fnum():
    assert ape.fnum("12.5") == 12.5
    assert ape.fnum(None) is None
    assert ape.fnum("abc") is None
