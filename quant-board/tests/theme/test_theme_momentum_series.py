# quant-board/backend/tests/test_theme_momentum.py
import math

import pytest

from backend.analysis.theme.momentum import (
    THEME_CROSS_SECTION_MIN,
    build_theme_strength_series,
    compute_theme_momentum_series,
    stock_theme_exposure,
)


def _theme(theme_id, heat, rank, rotation="neutral", eligible=True, extra=None):
    item = {
        "entityType": "hot_theme",
        "themeId": theme_id,
        "themeName": f"{theme_id}概念板块",
        "heatScore": heat,
        "rank": rank,
        "rotationState": rotation,
        "metadata": {"rankEligible": eligible},
    }
    if extra:
        item.update(extra)
    return item


def _frame(index, theme_rows):
    return {
        "tradingDate": "2026-08-04",
        "slotTime": f"{index:02d}:00",
        "type": "half_hour",
        "timestamp": index,
        "stocks": [],
        "hotThemes": theme_rows,
    }


def test_series_keeps_only_rank_eligible_finite_heat():
    frames = [
        _frame(0, [
            _theme("A", 50.0, 1),
            _theme("B", math.nan, 2),
            _theme("C", 40.0, 3, eligible=False),
        ]),
    ]
    series = build_theme_strength_series(frames)
    assert list(series) == ["A"]
    assert series["A"][0][:2] == (0, 50.0)


def test_momentum_series_mirrors_resonance_bounds():
    themes = [_theme(f"T{i}", 50.0, i + 1) for i in range(25)]
    # T0 持续升温，其余横盘
    frames = []
    for idx in range(12):
        rows = [_theme("T0", 40.0 + idx * 2.0, 1)]
        rows += [_theme(f"T{i}", 50.0, i + 1) for i in range(1, 25)]
        frames.append(_frame(idx, rows))
    result = compute_theme_momentum_series(frames)
    frame = result["frames"][-1]
    assert frame["themeSampleCount"] >= THEME_CROSS_SECTION_MIN
    assert frame["qualityFlags"] == []
    momentum = frame["themes"]["T0"]
    assert momentum["status"] == "ok"
    assert 0 <= momentum["score"] <= 100
    assert momentum["direction"] == "buy"
    assert momentum["relativeMomentum"] > 0


def test_momentum_series_insufficient_cross_section():
    frames = [_frame(idx, [_theme(f"T{i}", 50.0, i + 1) for i in range(5)]) for idx in range(12)]
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert frame["themeSampleCount"] < THEME_CROSS_SECTION_MIN
    assert "theme_cross_section_insufficient" in frame["qualityFlags"]


def test_momentum_series_skips_short_history_theme():
    frames = [_frame(idx, [_theme("A", 50.0 + idx, 1), _theme("B", 50.0, 2)]) for idx in range(12)]
    # B 只在前 4 帧出现，之后缺槽
    for idx in range(4, 12):
        frames[idx]["hotThemes"] = [_theme("A", 50.0 + idx, 1)]
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert "B" not in frame["themes"]
    assert "A" in frame["themes"]


def test_momentum_series_all_nan_heat_is_insufficient():
    frames = [
        _frame(idx, [_theme("A", math.nan, 1), _theme("B", math.nan, 2)]) for idx in range(12)
    ]
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert frame["themes"] == {}
    assert frame["themeSampleCount"] == 0
    assert "theme_cross_section_insufficient" in frame["qualityFlags"]


def test_momentum_series_jump_by_rank_only():
    # heatScore 恒定，但第 10 帧 rank 从 8 跳到 1（提升 >= 3 槽）
    frames = []
    for idx in range(12):
        rank = 8 - (3 if idx >= 10 else 0)
        rows = [_theme(f"T{i}", 50.0, i + 1) for i in range(25)]
        rows[0] = _theme("T0", 50.0, rank)
        frames.append(_frame(idx, rows))
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    momentum = frame["themes"]["T0"]
    assert momentum["jumpFreshness"] > 0


def test_momentum_series_rank_missing_uses_heat_jump():
    # rank 全部缺失，heatScore 单帧提升 >= 15 触发 Jump
    frames = []
    for idx in range(12):
        rows = [_theme(f"T{i}", 50.0, None) for i in range(25)]
        rows[0] = _theme("T0", 50.0 if idx < 9 else 70.0, None)
        frames.append(_frame(idx, rows))
    frame = compute_theme_momentum_series(frames)["frames"][-1]
    assert frame["themes"]["T0"]["jumpFreshness"] > 0


def test_momentum_series_reversal_penalty_adds_cooling_bonus():
    frames = []
    for idx in range(12):
        rows = [_theme(f"T{i}", 50.0, i + 1) for i in range(25)]
        rows[0] = _theme("T0", 50.0, 1, rotation="cooling")
        frames.append(_frame(idx, rows))
    momentum = compute_theme_momentum_series(frames)["frames"][-1]["themes"]["T0"]
    assert momentum["reversalPenalty"] == pytest.approx(0.2)


# ── theme-market-v2 口径迁移：绝对值 heatScore（KPL 人气总和，>100）不参与 0-100 计算 ──

def test_series_skips_absolute_heat_scores():
    """新口径绝对值落库行（>100）视为口径不兼容缺失，不进动量序列，
    避免 /15.0 归一与 JUMP_DELTA=15 在绝对值量纲下恒饱和（2026-09 审计 H1）。"""
    frames = [
        _frame(0, [
            _theme("A", 2000.0, 1),
            _theme("B", 80.0, 2),
        ]),
        _frame(1, [
            _theme("A", 2200.0, 1),
            _theme("B", 85.0, 2),
        ]),
    ]
    series = build_theme_strength_series(frames)
    assert list(series) == ["B"]


def test_exposure_role_ignores_absolute_heat_score():
    """heatScore=2000 不得触发 core 阈值（>=70）；热度缺失时只按涨跌判定。"""
    theme = _theme("A", 2000.0, 1)
    stock = {"code": "600001", "name": "样本", "themes": ["A概念板块"], "change": 10.0}
    exposure = stock_theme_exposure(stock, [theme])
    assert exposure is not None
    assert exposure["role"] == "independent"


def test_exposure_role_missing_heat_is_not_noise():
    """热度缺失（None）不算 heat<20 的 noise：正涨跌个股按 independent 分层。"""
    theme = _theme("A", None, 1)
    stock = {"code": "600001", "name": "样本", "themes": ["A概念板块"], "change": 2.0}
    exposure = stock_theme_exposure(stock, [theme])
    assert exposure is not None
    assert exposure["role"] == "independent"


# ── heatLevel 落库迁移：序列与角色判定统一走 heat_level.resolve_heat_level（design §4.2）──

def test_series_consumes_heat_level_rows():
    """collector 新行（heatScore 绝对值 + heatLevel 相对分）→ 序列吃 heatLevel。"""
    frames = [
        _frame(0, [
            _theme("A", 2000.0, 1, extra={"heatLevel": 100.0}),
            _theme("B", 300.0, 2, extra={"heatLevel": 50.0}),
        ]),
        _frame(1, [
            _theme("A", 2200.0, 1, extra={"heatLevel": 100.0}),
            _theme("B", 320.0, 2, extra={"heatLevel": 50.0}),
        ]),
    ]
    series = build_theme_strength_series(frames)
    assert list(series) == ["A", "B"]
    assert series["A"][0][:2] == (0, 100.0)
    assert series["B"][1][:2] == (1, 50.0)


def test_series_explicit_none_heat_level_is_missing():
    """heatLevel 显式 None（降级行）：诚实缺失，不回退 heatScore 绝对值。"""
    frames = [_frame(0, [_theme("A", 2000.0, 1, extra={"heatLevel": None})])]
    assert build_theme_strength_series(frames) == {}


def test_series_v2_marked_small_absolute_heat_not_relative():
    """v2 标记行无 heatLevel key：≤100 绝对值不回退为相对分（M1 边界窗口消除）。"""
    frames = [
        _frame(0, [
            _theme("A", 85.0, 1, extra={"metadata": {"rankEligible": True, "factorVersion": "theme-market-v2"}}),
        ]),
    ]
    assert build_theme_strength_series(frames) == {}


def test_series_v1_marked_row_heat_score_fallback():
    """v1 标记行无 heatLevel key：≤100 heatScore 回退为相对分（旧行为保留）。"""
    frames = [
        _frame(0, [
            _theme("A", 85.0, 1, extra={"metadata": {"rankEligible": True, "factorVersion": "theme-market-v1"}}),
        ]),
    ]
    series = build_theme_strength_series(frames)
    assert series["A"][0][:2] == (0, 85.0)


def test_exposure_role_consumes_heat_level():
    """新行 heatLevel=92 → core 阈值恢复语义；heatScore 绝对值不参与阈值。"""
    theme = _theme("A", 2000.0, 1, extra={"heatLevel": 92.0})
    stock = {"code": "600001", "name": "样本", "themes": ["A概念板块"], "change": 10.0}
    exposure = stock_theme_exposure(stock, [theme])
    assert exposure is not None
    assert exposure["role"] == "core"


def test_exposure_role_v2_row_without_heat_level_heatless_not_noise():
    """v2 标记行无 heatLevel：热度缺失只按涨跌判定，正涨跌不误判 noise。"""
    theme = _theme("A", 85.0, 1, extra={"metadata": {"rankEligible": True, "factorVersion": "theme-market-v2"}})
    stock = {"code": "600001", "name": "样本", "themes": ["A概念板块"], "change": 10.0}
    exposure = stock_theme_exposure(stock, [theme])
    assert exposure is not None
    assert exposure["role"] == "independent"
