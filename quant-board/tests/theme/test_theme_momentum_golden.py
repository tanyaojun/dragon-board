# quant-board/tests/test_theme_momentum_v2.py
"""题材动量 v2 纯函数 golden case：日线六维合成 + direction + phaseLabel + intraday。"""
from __future__ import annotations

import pytest

from backend.analysis.theme.daily_series import ThemeDailySeries
from backend.analysis.theme.momentum import (
    _apply_crowding_penalty,
    _near_high_score,
    _percentile_rank,
    _phase_label,
    _window_momentum_score,
    compute_theme_momentum_v2,
)
from backend.analysis.theme.momentum_config import ThemeMomentumConfig


def _series(
    theme_id: str,
    name: str,
    changes: list[float],
    zt: list[int] | None = None,
    breadth: list[float] | None = None,
    inflow: list[float] | None = None,
    ratio: list[float] | None = None,
) -> ThemeDailySeries:
    n = len(changes)
    return ThemeDailySeries(
        theme_id=theme_id,
        theme_name=name,
        dates=[f"2026-07-{10 + i:02d}" for i in range(n)],
        changes=changes,
        zt_counts=zt or [0] * n,
        breadths=breadth or [50.0] * n,
        inflows=inflow or [0.0] * n,
        amount_ratios=ratio or [0.05] * n,
        quality_flags=[],
    )


def test_percentile_rank_highest_is_100():
    assert _percentile_rank(10.0, [1.0, 3.0, 10.0]) == 100.0
    assert _percentile_rank(2.0, [1.0, 3.0, 10.0]) == pytest.approx(100.0 / 3)
    assert _percentile_rank(0.0, []) == 50.0


def test_v2_leader_has_top_rps_and_direction():
    """BKAI 近 25 日涨幅全市场最高 → RPS d20=100，score 高、direction up。"""
    others = [_series(f"BK{i:02d}", f"题材{i}", [0.01] * 25) for i in range(19)]
    leader = _series("BKAI", "人工智能", [0.05] * 25)
    result = compute_theme_momentum_v2([leader, *others], cfg=ThemeMomentumConfig())
    row = result["factors"]["BKAI"]
    assert row["rps"]["d20"] == 100.0
    assert row["rps"]["d5"] == 100.0
    assert row["direction"] == "up"
    assert 0 <= row["score"] <= 100
    assert row["phaseLabel"] in {"启动", "扩散", "过热", "退潮", "中性"}


def test_v2_insufficient_history_flags_and_null():
    """不足 min_history_days 的题材 RPS/动量维度为 None + reason。"""
    short = _series("BKAI", "人工智能", [0.01] * 3)
    result = compute_theme_momentum_v2([short], cfg=ThemeMomentumConfig())
    row = result["factors"]["BKAI"]
    assert row["rps"]["d20"] is None
    assert any("history_insufficient" in r for r in row["reasons"])


def test_v2_cross_section_insufficient_flag():
    """全市场板块数 < cross_section_min 时打 qualityFlags 标记（不阻断）。"""
    one = _series("BKAI", "人工智能", [0.01] * 20)
    result = compute_theme_momentum_v2([one], cfg=ThemeMomentumConfig())
    assert "cross_section_insufficient" in result["qualityFlags"]
    # 即使横截面不足，题材自身仍输出（fail-visible）
    assert "BKAI" in result["factors"]


def test_v2_crowding_penalty_reduces_score():
    base = 80.0
    cfg = ThemeMomentumConfig()
    assert _apply_crowding_penalty(base, 40.0, cfg) == base  # 未超阈值不扣
    penalized = _apply_crowding_penalty(base, 90.0, cfg)
    assert penalized < base
    assert penalized >= 0.0
    # 线性公式 (crowding-start)*slope，封顶 penalty_max：crowding=100 → 12
    assert _apply_crowding_penalty(base, 100.0, cfg) == base - 12.0
    assert _apply_crowding_penalty(base, 300.0, cfg) == base - cfg.crowding_penalty_max


def test_v2_phase_label_thresholds():
    cfg = ThemeMomentumConfig()
    assert _phase_label(80.0, 40.0, cfg) == "扩散"
    assert _phase_label(80.0, 80.0, cfg) == "过热"
    assert _phase_label(65.0, 40.0, cfg) == "启动"
    assert _phase_label(30.0, 40.0, cfg) == "退潮"
    assert _phase_label(50.0, 40.0, cfg) == "中性"


def test_v2_near_high_and_window_momentum():
    series = _series("BKAI", "人工智能", [0.01] * 20)
    cfg = ThemeMomentumConfig()
    near = _near_high_score(series, cfg)
    assert near is not None and 0 <= near <= 100
    momentum = _window_momentum_score(series, cfg)
    assert momentum is not None and 0 <= momentum <= 100


def test_v2_intraday_state_from_latest_slots():
    """intraday 辅口径：有 latest_slots 时按当日/前一日收盘槽真实计算。"""
    series = _series("BKAI", "人工智能", [0.01] * 25)
    series.latest_slots = [
        {"tradingDate": "2026-07-33", "slotTime": "15:00",
         "change": 0.01, "ztCount": 2, "mainNetInflow": 1.0},
        {"tradingDate": "2026-07-34", "slotTime": "15:00",
         "change": 0.03, "ztCount": 5, "mainNetInflow": 2.5},
    ]
    result = compute_theme_momentum_v2([series], cfg=ThemeMomentumConfig())
    row = result["factors"]["BKAI"]
    assert set(row["intraday"]) == {"shortChange", "ztDelta", "inflowDelta"}
    assert row["intraday"]["ztDelta"] == 3
    assert row["intraday"]["inflowDelta"] == 1.5


def test_v2_intraday_unavailable_without_slots():
    """无 latest_slots（直接构造的 series）时 intraday 标注 unavailable（fail-visible）。"""
    result = compute_theme_momentum_v2(
        [_series("BKAI", "人工智能", [0.01] * 25)],
        cfg=ThemeMomentumConfig(),
    )
    row = result["factors"]["BKAI"]
    assert set(row["intraday"]) == {"shortChange", "ztDelta", "inflowDelta", "unavailable"}
    assert row["intraday"]["unavailable"] is True


def test_v2_rotation_state_direction_labels():
    """v2 输出 rotationState 方向标签（spec D10）：动量上行 → inflow。"""
    leader = _series("BKAI", "人工智能", [0.05] * 25)
    result = compute_theme_momentum_v2([leader], cfg=ThemeMomentumConfig())
    row = result["factors"]["BKAI"]
    assert row["rotationState"] in {"mainline", "inflow", "outflow", "neutral"}
    assert "rotationState=inflow(v2)" in row["reasons"] or row["direction"] != "up"


def test_v2_empty_input_not_crash():
    result = compute_theme_momentum_v2([], cfg=ThemeMomentumConfig())
    assert result["factors"] == {}
    # 空输入：无板块 → 横截面不足标记（fail-visible，不伪装成功）
    assert result["qualityFlags"] == ["cross_section_insufficient"]


def test_v2_direction_requires_momentum_consistency():
    """普跌市中 RPS 分位高但绝对动量负 → 不标 up（MEDIUM-1）。"""
    # 全市场都在跌：BKAI 跌得最少（相对最强，RPS 高）但绝对收益为负
    others = [_series(f"BK{i:02d}", f"题材{i}", [-0.05] * 25) for i in range(19)]
    leader = _series("BKAI", "人工智能", [-0.01] * 25)
    result = compute_theme_momentum_v2([leader, *others], cfg=ThemeMomentumConfig())
    row = result["factors"]["BKAI"]
    # 绝对动量 windowMomentum < 50（负收益）→ 不标 up，即使 RPS 分位高
    assert row["direction"] != "up"
    assert row["direction"] in {"neutral", "down"}


def test_v2_near_high_degraded_without_new_high():
    """窗内从未创新高（一路阴跌）→ nearHigh None + near_high_window_limited（MEDIUM-2）。"""
    falling = _series("BKAI", "人工智能", [-0.01] * 25)
    result = compute_theme_momentum_v2([falling], cfg=ThemeMomentumConfig())
    row = result["factors"]["BKAI"]
    assert row["nearHigh"] is None
    assert "near_high_window_limited" in row["reasons"]

